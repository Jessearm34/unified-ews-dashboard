"""
Geotab data module — unified data loading layer for the EWS dashboard.

Adapted from geotab-fleet-dashboard/analytics.py (AnalyticsService),
database.py, models.py, and schemas.py.

Exposes all the same query methods as AnalyticsService but as
module-level functions that accept a SQLAlchemy Session directly.

Usage:
    from data.gt_data import (
        get_db, create_engine_from_url,
        gt_fleet_summary, gt_vehicle_utilization,
        gt_daily_trends, gt_speed_analysis,
        gt_idling_summary, gt_latest_locations,
        gt_driver_metrics, gt_maintenance_metrics,
        gt_load_data,
    )
"""

from __future__ import annotations

import logging
import os
import threading
import time
from collections.abc import Generator
from datetime import date, datetime, timedelta, timezone
from typing import Any, Optional

from pydantic import BaseModel
from sqlalchemy import (
    Date,
    Float,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    case,
    cast,
    create_engine,
    desc,
    func,
    select,
)
from sqlalchemy.orm import (
    DeclarativeBase,
    Mapped,
    Session,
    mapped_column,
    relationship,
    sessionmaker,
)

logger = logging.getLogger(__name__)

# ── Engine & Session ─────────────────────────────────────────────────── #

GT_DATABASE_URL = os.environ.get(
    "GT_DATABASE_URL", "postgresql://localhost/geotab"
)


def create_engine_from_url(url: str | None = None) -> ...:
    """Create a SQLAlchemy engine from *url* (defaults to GT_DATABASE_URL).

    Returns an engine instance immediately; callers that want lazy
    instantiation should call this on demand.
    """
    url = url or GT_DATABASE_URL
    connect_args: dict[str, object] = {}
    if url.startswith("sqlite"):
        connect_args["check_same_thread"] = False
    return create_engine(url, pool_pre_ping=True, future=True, connect_args=connect_args)


# Lazy engine + sessionmaker — created on first call to get_db() so that
# importing the module does not require the database driver to be installed.
_engine: Any | None = None
_SessionLocal: Any | None = None
_engine_lock = threading.Lock()


def _ensure_engine() -> None:
    """Create the shared engine and sessionmaker on first demand."""
    global _engine, _SessionLocal
    if _engine is not None:
        return
    with _engine_lock:
        if _engine is not None:
            return
        _engine = create_engine_from_url()
        _SessionLocal = sessionmaker(
            bind=_engine,
            autoflush=False,
            autocommit=False,
            expire_on_commit=False,
        )


def get_db() -> Generator[Session, None, None]:
    """Yield a SQLAlchemy Session (context-manager friendly).

    Lazily initialises the engine and sessionmaker on first call.
    """
    _ensure_engine()
    db = _SessionLocal()  # type: ignore[union-attr]
    try:
        yield db
    finally:
        db.close()


# ── ORM Models (copied from geotab-fleet-dashboard/models.py) ────────── #


class Base(DeclarativeBase):
    pass


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class Vehicle(Base, TimestampMixin):
    __tablename__ = "vehicles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    geotab_id: Mapped[str] = mapped_column(
        String(128), nullable=False, unique=True, index=True
    )
    serial_number: Mapped[Optional[str]] = mapped_column(String(128))
    vin: Mapped[Optional[str]] = mapped_column(String(64), index=True)
    license_plate: Mapped[Optional[str]] = mapped_column(String(64))
    make: Mapped[Optional[str]] = mapped_column(String(128))
    model: Mapped[Optional[str]] = mapped_column(String(128))
    year: Mapped[Optional[int]] = mapped_column(Integer)

    trips: Mapped[list["Trip"]] = relationship(back_populates="vehicle")
    gps_logs: Mapped[list["GPSLog"]] = relationship(back_populates="vehicle")
    fault_codes: Mapped[list["FaultCode"]] = relationship(
        back_populates="vehicle"
    )


class Driver(Base, TimestampMixin):
    __tablename__ = "drivers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    geotab_id: Mapped[str] = mapped_column(
        String(128), nullable=False, unique=True, index=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    employee_id: Mapped[Optional[str]] = mapped_column(String(128), index=True)

    trips: Mapped[list["Trip"]] = relationship(back_populates="driver")


class Trip(Base, TimestampMixin):
    __tablename__ = "trips"
    __table_args__ = (
        UniqueConstraint("geotab_trip_id", name="uq_trips_geotab_trip_id"),
        Index("ix_trips_vehicle_id", "vehicle_id"),
        Index("ix_trips_driver_id", "driver_id"),
        Index("ix_trips_start_time", "start_time"),
        Index("ix_trips_end_time", "end_time"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    geotab_trip_id: Mapped[str] = mapped_column(String(128), nullable=False)
    vehicle_id: Mapped[int] = mapped_column(
        ForeignKey("vehicles.id", ondelete="CASCADE"), nullable=False
    )
    driver_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("drivers.id", ondelete="SET NULL")
    )
    start_time: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    end_time: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    distance_miles: Mapped[float] = mapped_column(
        Float, nullable=False, default=0
    )
    fuel_used: Mapped[float] = mapped_column(Float, nullable=False, default=0)
    idle_time: Mapped[float] = mapped_column(Float, nullable=False, default=0)

    vehicle: Mapped[Vehicle] = relationship(back_populates="trips")
    driver: Mapped[Optional[Driver]] = relationship(back_populates="trips")


class GPSLog(Base, TimestampMixin):
    __tablename__ = "gps_logs"
    __table_args__ = (
        UniqueConstraint("geotab_log_id", name="uq_gps_logs_geotab_log_id"),
        Index("ix_gps_logs_vehicle_id", "vehicle_id"),
        Index("ix_gps_logs_timestamp", "timestamp"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    geotab_log_id: Mapped[str] = mapped_column(String(128), nullable=False)
    vehicle_id: Mapped[int] = mapped_column(
        ForeignKey("vehicles.id", ondelete="CASCADE"), nullable=False
    )
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    latitude: Mapped[float] = mapped_column(Float, nullable=False)
    longitude: Mapped[float] = mapped_column(Float, nullable=False)
    speed: Mapped[float] = mapped_column(Float, nullable=False, default=0)

    vehicle: Mapped[Vehicle] = relationship(back_populates="gps_logs")


class FaultCode(Base, TimestampMixin):
    __tablename__ = "fault_codes"
    __table_args__ = (
        UniqueConstraint(
            "geotab_fault_id", name="uq_fault_codes_geotab_fault_id"
        ),
        Index("ix_fault_codes_vehicle_id", "vehicle_id"),
        Index("ix_fault_codes_timestamp", "timestamp"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    geotab_fault_id: Mapped[str] = mapped_column(String(128), nullable=False)
    vehicle_id: Mapped[int] = mapped_column(
        ForeignKey("vehicles.id", ondelete="CASCADE"), nullable=False
    )
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    fault_code: Mapped[str] = mapped_column(String(128), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text)

    vehicle: Mapped[Vehicle] = relationship(back_populates="fault_codes")


# ── Pydantic Schemas (copied from geotab-fleet-dashboard/schemas.py) ─── #


class FleetSummary(BaseModel):
    total_vehicles: int
    active_vehicles: int
    total_fleet_miles: float
    total_fuel_consumed: float
    average_mpg: Optional[float]


# ── Helper utilities ────────────────────────────────────────────────── #


def _since(since: datetime | None = None) -> datetime:
    return since or datetime.now(timezone.utc) - timedelta(days=30)


def _until(until: datetime | None = None) -> datetime:
    return until or datetime.now(timezone.utc)


# ═══════════════════════════════════════════════════════════════════════ #
#  Query functions — each mirrors a method on the original              #
#  AnalyticsService but takes an explicit Session as the first arg.     #
# ═══════════════════════════════════════════════════════════════════════ #


def gt_fleet_summary(
    db: Session,
    since: datetime | None = None,
    until: datetime | None = None,
) -> FleetSummary:
    """High-level fleet summary counts and mileage."""
    since, until = _since(since), _until(until)
    total_vehicles = (
        db.scalar(select(func.count(Vehicle.id))) or 0
    )
    trip_count = (
        db.scalar(
            select(func.count(Trip.id)).where(
                Trip.start_time.between(since, until)
            )
        )
        or 0
    )
    logger.info(
        "gt_fleet_summary total_vehicles=%s trip_count=%s since=%s until=%s",
        total_vehicles,
        trip_count,
        since.isoformat(),
        until.isoformat(),
    )
    active_vehicles = (
        db.scalar(
            select(func.count(func.distinct(Trip.vehicle_id))).where(
                Trip.start_time.between(since, until)
            )
        )
        or 0
    )
    total_miles = (
        db.scalar(
            select(func.coalesce(func.sum(Trip.distance_miles), 0.0)).where(
                Trip.start_time.between(since, until)
            )
        )
        or 0
    )
    return FleetSummary(
        total_vehicles=int(total_vehicles),
        active_vehicles=int(active_vehicles),
        total_fleet_miles=round(float(total_miles), 2),
        total_fuel_consumed=0.0,
        average_mpg=None,
    )


def gt_vehicle_utilization(
    db: Session,
    since: datetime | None = None,
    until: datetime | None = None,
) -> list[dict[str, Any]]:
    """Per-vehicle utilization: miles driven, hours, utilisation %."""
    since, until = _since(since), _until(until)
    rows = db.execute(
        select(
            Vehicle.id,
            Vehicle.license_plate,
            Vehicle.vin,
            func.coalesce(func.sum(Trip.distance_miles), 0.0).label("miles"),
            func.coalesce(
                func.sum(
                    func.extract("epoch", Trip.end_time)
                    - func.extract("epoch", Trip.start_time)
                )
                / 3600,
                0.0,
            ).label("hours"),
        )
        .join(
            Trip,
            (Trip.vehicle_id == Vehicle.id)
            & (Trip.start_time.between(since, until)),
            isouter=True,
        )
        .group_by(Vehicle.id)
        .order_by(desc("miles"))
    ).mappings()
    period_hours = max(
        (datetime.now(timezone.utc) - since).total_seconds() / 3600, 1
    )
    return [
        {
            "vehicle_id": row["id"],
            "label": row["license_plate"]
            or row["vin"]
            or f"Vehicle {row['id']}",
            "total_miles": round(float(row["miles"]), 2),
            "hours_driven": round(float(row["hours"]), 2),
            "utilization_percentage": round(
                min((float(row["hours"]) / period_hours) * 100, 100), 2
            ),
        }
        for row in rows
    ]


def gt_daily_trends(
    db: Session,
    since: datetime | None = None,
    until: datetime | None = None,
) -> list[dict[str, Any]]:
    """Daily mileage and trip counts."""
    since, until = _since(since), _until(until)
    rows = db.execute(
        select(
            func.date(Trip.start_time).label("day"),
            func.coalesce(func.sum(Trip.distance_miles), 0.0).label("miles"),
            func.count(Trip.id).label("trips"),
        )
        .where(Trip.start_time.between(since, until))
        .group_by(func.date(Trip.start_time))
        .order_by(func.date(Trip.start_time))
    ).mappings()
    result = [
        {
            "day": row["day"].isoformat()
            if isinstance(row["day"], date)
            else str(row["day"]),
            "mileage": round(float(row["miles"]), 2),
            "fuel": 0.0,
            "trips": int(row["trips"]),
        }
        for row in rows
    ]
    logger.info("gt_daily_trends rows=%s", len(result))
    return result


def gt_speed_analysis(
    db: Session,
    since: datetime | None = None,
    until: datetime | None = None,
) -> dict[str, Any]:
    """Speeding analysis: GPS points above threshold, speed distribution."""
    since, until = _since(since), _until(until)
    SPEED_THRESHOLD = 70
    stats = db.execute(
        select(
            func.count(GPSLog.id).label("count"),
            func.coalesce(func.avg(GPSLog.speed), 0.0).label("avg"),
            func.coalesce(func.max(GPSLog.speed), 0.0).label("max"),
            func.coalesce(
                func.sum(
                    case((GPSLog.speed > SPEED_THRESHOLD, 1), else_=0)
                ),
                0,
            ).label("speeding"),
        ).where(GPSLog.timestamp.between(since, until))
    ).one()
    sample = [
        float(r[0])
        for r in db.execute(
            select(GPSLog.speed)
            .where(GPSLog.timestamp.between(since, until))
            .order_by(func.random())
            .limit(1000)
        ).all()
        if r[0] is not None
    ]
    logger.info("gt_speed_analysis gps_points=%s", stats.count)
    return {
        "total_gps_points": int(stats.count),
        "speeding_count": int(stats.speeding),
        "speeding_pct": (
            round((float(stats.speeding) / float(stats.count)) * 100, 2)
            if stats.count
            else 0.0
        ),
        "speed_distribution": sample,
        "avg_speed": (
            round(float(stats.avg), 1) if stats.count else 0.0
        ),
        "max_speed": (
            round(float(stats.max), 1) if stats.count else 0.0
        ),
    }


def gt_idling_summary(
    db: Session,
    since: datetime | None = None,
    until: datetime | None = None,
) -> dict[str, Any]:
    """Per-vehicle idling breakdown."""
    since, until = _since(since), _until(until)
    rows = db.execute(
        select(
            Vehicle.id,
            Vehicle.license_plate,
            func.coalesce(func.sum(Trip.idle_time), 0.0).label("idle"),
            func.coalesce(
                func.sum(
                    func.extract("epoch", Trip.end_time)
                    - func.extract("epoch", Trip.start_time)
                ),
                0.0,
            ).label("total_time"),
        )
        .join(Trip, Trip.vehicle_id == Vehicle.id)
        .where(Trip.start_time.between(since, until))
        .group_by(Vehicle.id)
        .order_by(desc("idle"))
    ).mappings()
    vehicles = []
    total_idle = 0.0
    total_time = 0.0
    for r in rows:
        idle = float(r["idle"])
        tot = float(r["total_time"])
        total_idle += idle
        total_time += tot
        vehicles.append(
            {
                "vehicle_id": r["id"],
                "label": r["license_plate"] or f"Vehicle {r['id']}",
                "idle_seconds": round(idle, 1),
                "idle_pct": round((idle / tot) * 100, 2) if tot else 0.0,
            }
        )
    return {
        "vehicles": vehicles,
        "total_idle_hours": round(total_idle / 3600, 2),
        "idle_pct": (
            round((total_idle / total_time) * 100, 2) if total_time else 0.0
        ),
    }


def gt_latest_locations(
    db: Session, max_age_days: int = 365
) -> list[dict[str, Any]]:
    """Latest GPS position for every vehicle."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=max_age_days)
    subq = (
        select(
            GPSLog.vehicle_id,
            func.max(GPSLog.timestamp).label("max_timestamp"),
        )
        .where(GPSLog.timestamp >= cutoff)
        .group_by(GPSLog.vehicle_id)
        .subquery()
    )
    rows = db.execute(
        select(GPSLog, Vehicle)
        .join(
            subq,
            (GPSLog.vehicle_id == subq.c.vehicle_id)
            & (GPSLog.timestamp == subq.c.max_timestamp),
        )
        .join(Vehicle, Vehicle.id == GPSLog.vehicle_id)
    ).all()
    return [
        {
            "vehicle": vehicle.license_plate
            or vehicle.vin
            or vehicle.geotab_id,
            "latitude": log.latitude,
            "longitude": log.longitude,
            "speed": log.speed,
            "timestamp": log.timestamp.isoformat(),
            "status": "moving" if log.speed > 1 else "stopped",
        }
        for log, vehicle in rows
    ]


def gt_driver_metrics(
    db: Session,
    since: datetime | None = None,
    until: datetime | None = None,
) -> list[dict[str, Any]]:
    """Per-driver trip counts, distance, average trip length."""
    since, until = _since(since), _until(until)
    rows = db.execute(
        select(
            Driver.id,
            Driver.name,
            func.count(Trip.id).label("trip_count"),
            func.coalesce(func.sum(Trip.distance_miles), 0.0).label(
                "distance"
            ),
            func.coalesce(func.avg(Trip.distance_miles), 0.0).label(
                "avg_trip"
            ),
        )
        .join(
            Trip,
            (Trip.driver_id == Driver.id)
            & (Trip.start_time.between(since, until)),
            isouter=True,
        )
        .group_by(Driver.id)
        .order_by(desc("distance"))
    ).mappings()
    return [
        {
            "driver_id": row["id"],
            "name": row["name"],
            "trip_count": int(row["trip_count"]),
            "distance_driven": round(float(row["distance"]), 2),
            "average_trip_length": round(float(row["avg_trip"]), 2),
        }
        for row in rows
    ]


def gt_maintenance_metrics(
    db: Session,
    since: datetime | None = None,
    until: datetime | None = None,
) -> dict[str, Any]:
    """Fault code frequency and recent fault list."""
    since, until = _since(since), _until(until)
    fault_rows = list(
        db.execute(
            select(
                FaultCode.fault_code,
                func.count(FaultCode.id).label("count"),
            )
            .where(FaultCode.timestamp.between(since, until))
            .group_by(FaultCode.fault_code)
            .order_by(desc("count"))
        ).mappings()
    )
    current = (
        db.execute(
            select(FaultCode, Vehicle)
            .join(Vehicle, Vehicle.id == FaultCode.vehicle_id)
            .where(FaultCode.timestamp.between(since, until))
            .order_by(FaultCode.timestamp.desc())
            .limit(100)
        )
        .all()
    )
    return {
        "open_fault_counts": sum(int(row["count"]) for row in fault_rows),
        "fault_frequency": [
            {"fault_code": row["fault_code"], "count": int(row["count"])}
            for row in fault_rows
        ],
        "current_faults": [
            {
                "vehicle": vehicle.license_plate
                or vehicle.vin
                or vehicle.geotab_id,
                "timestamp": fault.timestamp.isoformat(),
                "fault_code": fault.fault_code,
                "description": fault.description,
            }
            for fault, vehicle in current
        ],
    }


# ── Convenience: cached bulk loader ─────────────────────────────────── #

_cache: dict[str, Any] = {}
_cache_lock = threading.Lock()
_cache_ts: float = 0.0
_CACHE_TTL = 60.0  # seconds


def gt_load_data(
    db: Session,
    since: datetime | None = None,
    until: datetime | None = None,
    force_refresh: bool = False,
) -> dict[str, Any]:
    """Return a dict of *all* Geotab analytics, cached for 60 seconds.

    Keys returned:
        fleet_summary, vehicle_utilization, daily_trends,
        speed_analysis, idling_summary, latest_locations,
        driver_metrics, maintenance_metrics
    """
    global _cache_ts

    now = time.monotonic()
    if not force_refresh and _cache and (now - _cache_ts) < _CACHE_TTL:
        logger.debug("gt_load_data returning cached result")
        return dict(_cache)  # shallow copy

    with _cache_lock:
        # Double-check after acquiring lock
        if (
            not force_refresh
            and _cache
            and (time.monotonic() - _cache_ts) < _CACHE_TTL
        ):
            return dict(_cache)

        since, until = _since(since), _until(until)

        data = {
            "fleet_summary": gt_fleet_summary(db, since, until),
            "vehicle_utilization": gt_vehicle_utilization(db, since, until),
            "daily_trends": gt_daily_trends(db, since, until),
            "speed_analysis": gt_speed_analysis(db, since, until),
            "idling_summary": gt_idling_summary(db, since, until),
            "latest_locations": gt_latest_locations(db),
            "driver_metrics": gt_driver_metrics(db, since, until),
            "maintenance_metrics": gt_maintenance_metrics(db, since, until),
        }

        _cache.clear()
        _cache.update(data)
        _cache_ts = time.monotonic()

        logger.info(
            "gt_load_data loaded %d keys since=%s until=%s",
            len(data),
            since.isoformat(),
            until.isoformat(),
        )
        return dict(data)

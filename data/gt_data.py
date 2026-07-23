"""GeoTab data queries for the unified dashboard.

All queries go through raw SQL against the GT Postgres database.
Follows the same pattern as qb_data.py and sd_data.py.
"""

from __future__ import annotations

import os
from datetime import date, datetime, timedelta, timezone
from functools import lru_cache
from typing import Any

from sqlalchemy import create_engine, text

KM_TO_MILES = 0.621371


def gt_get_db_url() -> str:
    url = os.getenv("GT_DATABASE_URL", os.getenv("DATABASE_URL", ""))
    if not url:
        return ""
    if url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql+psycopg2://", 1)
    elif url.startswith("postgresql://") and "+psycopg2" not in url:
        url = url.replace("postgresql://", "postgresql+psycopg2://", 1)
    return url


@lru_cache(maxsize=1)
def gt_engine():
    url = gt_get_db_url()
    if not url:
        return None
    return create_engine(url, pool_pre_ping=True, connect_args={"connect_timeout": 5})


def gt_conn():
    eng = gt_engine()
    if eng is None:
        return None
    return eng.connect()


# ── Query helpers ─────────────────────────────────────────────────────

def _exec(sql: str, params: dict | None = None) -> list[dict[str, Any]]:
    conn = gt_conn()
    if conn is None:
        return []
    try:
        r = conn.execute(text(sql), params or {})
        cols = r.keys()
        return [dict(zip(cols, row)) for row in r.fetchall()]
    finally:
        conn.close()


def _scalar(sql: str, params: dict | None = None) -> Any:
    conn = gt_conn()
    if conn is None:
        return None
    try:
        return conn.execute(text(sql), params or {}).scalar()
    finally:
        conn.close()


# ── GT Queries ────────────────────────────────────────────────────────

def fleet_summary(since: datetime | None = None, until: datetime | None = None) -> dict[str, Any]:
    if since is None:
        since = datetime.now(timezone.utc) - timedelta(days=365)
    if until is None:
        until = datetime.now(timezone.utc)
    total_v = _scalar("SELECT COUNT(*) FROM vehicles") or 0
    active_v = _scalar(
        "SELECT COUNT(DISTINCT vehicle_id) FROM trips WHERE start_time BETWEEN :s AND :u",
        {"s": since, "u": until}
    ) or 0
    total_mi = _scalar(
        "SELECT COALESCE(SUM(distance_miles), 0) FROM trips WHERE start_time BETWEEN :s AND :u",
        {"s": since, "u": until}
    ) or 0.0
    return {"total_vehicles": int(total_v), "active_vehicles": int(active_v),
            "total_fleet_miles": round(float(total_mi), 2)}


def daily_trends(since: datetime | None = None, until: datetime | None = None) -> list[dict[str, Any]]:
    if since is None:
        since = datetime.now(timezone.utc) - timedelta(days=365)
    if until is None:
        until = datetime.now(timezone.utc)
    return _exec(
        "SELECT DATE(start_time) as day, COALESCE(SUM(distance_miles),0) as mileage, COUNT(*) as trips "
        "FROM trips WHERE start_time BETWEEN :s AND :u "
        "GROUP BY DATE(start_time) ORDER BY day",
        {"s": since, "u": until}
    )


def vehicle_utilization(since: datetime | None = None, until: datetime | None = None) -> list[dict[str, Any]]:
    if since is None:
        since = datetime.now(timezone.utc) - timedelta(days=365)
    if until is None:
        until = datetime.now(timezone.utc)
    rows = _exec(
        "SELECT v.id, v.license_plate, v.vin, v.assigned_driver, "
        "COALESCE(SUM(t.distance_miles),0) as miles, "
        "COALESCE(SUM(EXTRACT(EPOCH FROM (t.end_time - t.start_time))/3600),0) as hours "
        "FROM vehicles v LEFT JOIN trips t ON t.vehicle_id=v.id AND t.start_time BETWEEN :s AND :u "
        "GROUP BY v.id ORDER BY miles DESC LIMIT 15",
        {"s": since, "u": until}
    )
    period_hrs = max((datetime.now(timezone.utc) - since).total_seconds() / 3600, 1)
    result = []
    for r in rows:
        label = r["assigned_driver"] or r["license_plate"] or r["vin"] or f"V{r['id']}"
        result.append({
            "label": label, "total_miles": round(float(r["miles"]), 2),
            "hours_driven": round(float(r["hours"]), 2),
            "utilization_percentage": round(min(float(r["hours"]) / period_hrs * 100, 100), 2),
            "assigned_driver": r["assigned_driver"] or "",
        })
    return result


def idling_summary(since: datetime | None = None, until: datetime | None = None) -> dict[str, Any]:
    if since is None:
        since = datetime.now(timezone.utc) - timedelta(days=365)
    if until is None:
        until = datetime.now(timezone.utc)
    rows = _exec(
        "SELECT v.id, v.license_plate, v.assigned_driver, "
        "COALESCE(SUM(t.idle_time),0) as idle, "
        "COALESCE(SUM(EXTRACT(EPOCH FROM (t.end_time - t.start_time))),0) as total_time "
        "FROM vehicles v JOIN trips t ON t.vehicle_id=v.id "
        "WHERE t.start_time BETWEEN :s AND :u "
        "GROUP BY v.id ORDER BY idle DESC",
        {"s": since, "u": until}
    )
    vehicles = []
    total_idle = total_time = 0.0
    for r in rows:
        idle = float(r["idle"])
        tot = float(r["total_time"])
        total_idle += idle
        total_time += tot
        label = r["assigned_driver"] or r["license_plate"] or f"V{r['id']}"
        vehicles.append({
            "vehicle_id": r["id"], "label": label,
            "idle_seconds": round(idle, 1),
            "idle_pct": round(idle / tot * 100, 2) if tot else 0.0,
            "assigned_driver": r["assigned_driver"] or "",
        })
    return {
        "vehicles": vehicles,
        "total_idle_hours": round(total_idle / 3600, 2),
        "idle_pct": round(total_idle / total_time * 100, 2) if total_time else 0.0,
    }


def speed_analysis(since: datetime | None = None, until: datetime | None = None) -> dict[str, Any]:
    if since is None:
        since = datetime.now(timezone.utc) - timedelta(days=365)
    if until is None:
        until = datetime.now(timezone.utc)
    rows = _exec(
        "SELECT COUNT(*) as cnt, COALESCE(AVG(speed),0) as avg_s, COALESCE(MAX(speed),0) as max_s, "
        "COALESCE(SUM(CASE WHEN speed>70 THEN 1 ELSE 0 END),0) as spd "
        "FROM gps_logs WHERE timestamp BETWEEN :s AND :u",
        {"s": since, "u": until}
    )
    r = rows[0] if rows else {"cnt": 0, "avg_s": 0, "max_s": 0, "spd": 0}
    cnt = int(r["cnt"])
    return {
        "total_gps_points": cnt,
        "speeding_count": int(r["spd"]),
        "speeding_pct": round(int(r["spd"]) / cnt * 100, 2) if cnt else 0.0,
        "avg_speed": round(float(r["avg_s"]), 1) if cnt else 0.0,
        "max_speed": round(float(r["max_s"]), 1) if cnt else 0.0,
        "speed_distribution": [r["speed"] for r in _exec(
            "SELECT speed FROM gps_logs WHERE timestamp BETWEEN :s AND :u ORDER BY RANDOM() LIMIT 1000",
            {"s": since, "u": until}
        ) if r.get("speed") is not None],
    }


def driver_metrics(since: datetime | None = None, until: datetime | None = None) -> list[dict[str, Any]]:
    if since is None:
        since = datetime.now(timezone.utc) - timedelta(days=365)
    if until is None:
        until = datetime.now(timezone.utc)
    return _exec(
        "SELECT d.id, d.name, COUNT(t.id) as trip_count, "
        "COALESCE(SUM(t.distance_miles),0) as distance_driven, "
        "COALESCE(AVG(t.distance_miles),0) as average_trip_length "
        "FROM drivers d LEFT JOIN trips t ON t.driver_id=d.id AND t.start_time BETWEEN :s AND :u "
        "GROUP BY d.id ORDER BY distance_driven DESC",
        {"s": since, "u": until}
    )


def maintenance_metrics(since: datetime | None = None, until: datetime | None = None) -> dict[str, Any]:
    if since is None:
        since = datetime.now(timezone.utc) - timedelta(days=365)
    if until is None:
        until = datetime.now(timezone.utc)
    freq = _exec(
        "SELECT fault_code, COUNT(*) as count FROM fault_codes "
        "WHERE timestamp BETWEEN :s AND :u GROUP BY fault_code ORDER BY count DESC LIMIT 15",
        {"s": since, "u": until}
    )
    current = _exec(
        "SELECT fc.*, v.license_plate, v.vin, v.assigned_driver "
        "FROM fault_codes fc JOIN vehicles v ON v.id=fc.vehicle_id "
        "WHERE fc.timestamp BETWEEN :s AND :u ORDER BY fc.timestamp DESC LIMIT 50",
        {"s": since, "u": until}
    )
    return {
        "open_fault_counts": sum(int(r["count"]) for r in freq),
        "fault_frequency": [{"fault_code": r["fault_code"], "count": int(r["count"])} for r in freq],
        "current_faults": [
            {"vehicle": r["assigned_driver"] or r["license_plate"] or r["vin"] or "",
             "timestamp": r["timestamp"].isoformat() if hasattr(r["timestamp"], 'isoformat') else str(r["timestamp"]),
             "fault_code": r["fault_code"], "description": r.get("description", "") or ""}
            for r in current
        ],
    }


# ── NEW: Enhanced analytics ───────────────────────────────────────────

def seatbelt_analysis(since: datetime | None = None, until: datetime | None = None) -> list[dict[str, Any]]:
    if since is None:
        since = datetime.now(timezone.utc) - timedelta(days=365)
    if until is None:
        until = datetime.now(timezone.utc)
    return _exec(
        "SELECT DATE(start_time) as day, COUNT(*) as total_trips, "
        "COALESCE(SUM(CASE WHEN is_seatbelt_off=1 THEN 1 ELSE 0 END),0) as seatbelt_off, "
        "COALESCE(SUM(CASE WHEN is_seatbelt_off=0 THEN 1 ELSE 0 END),0) as seatbelt_on "
        "FROM trips WHERE start_time BETWEEN :s AND :u AND is_seatbelt_off IS NOT NULL "
        "GROUP BY DATE(start_time) ORDER BY day",
        {"s": since, "u": until}
    )


def after_hours_analysis(since: datetime | None = None, until: datetime | None = None) -> list[dict[str, Any]]:
    if since is None:
        since = datetime.now(timezone.utc) - timedelta(days=365)
    if until is None:
        until = datetime.now(timezone.utc)
    return _exec(
        "SELECT DATE(start_time) as day, "
        "COALESCE(SUM(after_hours_distance*:km),0) as after_hours_miles, "
        "COALESCE(SUM(work_distance*:km),0) as work_miles "
        "FROM trips WHERE start_time BETWEEN :s AND :u "
        "GROUP BY DATE(start_time) ORDER BY day",
        {"s": since, "u": until, "km": KM_TO_MILES}
    )


def speed_trend(since: datetime | None = None, until: datetime | None = None) -> list[dict[str, Any]]:
    if since is None:
        since = datetime.now(timezone.utc) - timedelta(days=365)
    if until is None:
        until = datetime.now(timezone.utc)
    return _exec(
        "SELECT DATE(start_time) as day, "
        "COALESCE(AVG(average_speed),0) as avg_speed, "
        "COALESCE(MAX(maximum_speed),0) as max_speed, "
        "COALESCE(SUM(CASE WHEN maximum_speed>70 THEN 1 ELSE 0 END),0) as speeding_trips, "
        "COUNT(*) as trip_count "
        "FROM trips WHERE start_time BETWEEN :s AND :u AND average_speed IS NOT NULL "
        "GROUP BY DATE(start_time) ORDER BY day",
        {"s": since, "u": until}
    )


def exception_analysis(since: datetime | None = None, until: datetime | None = None) -> dict[str, Any]:
    if since is None:
        since = datetime.now(timezone.utc) - timedelta(days=365)
    if until is None:
        until = datetime.now(timezone.utc)
    # Check if table exists
    try:
        _scalar("SELECT 1 FROM exception_events LIMIT 1")
    except Exception:
        return {"total": 0, "by_type": [], "by_vehicle": [], "daily_trend": []}

    by_type = _exec(
        "SELECT event_type, COUNT(*) as count FROM exception_events "
        "WHERE timestamp BETWEEN :s AND :u GROUP BY event_type ORDER BY count DESC LIMIT 15",
        {"s": since, "u": until}
    )
    by_vehicle = _exec(
        "SELECT COALESCE(v.assigned_driver,v.license_plate,v.vin,v.geotab_id) as vehicle, "
        "COUNT(ee.id) as count, COALESCE(v.assigned_driver,'') as driver "
        "FROM exception_events ee LEFT JOIN vehicles v ON v.id=ee.vehicle_id "
        "WHERE ee.timestamp BETWEEN :s AND :u GROUP BY v.id ORDER BY count DESC LIMIT 15",
        {"s": since, "u": until}
    )
    daily = _exec(
        "SELECT DATE(timestamp) as day, event_type, COUNT(*) as count "
        "FROM exception_events WHERE timestamp BETWEEN :s AND :u "
        "GROUP BY DATE(timestamp), event_type ORDER BY day",
        {"s": since, "u": until}
    )
    total = _scalar(
        "SELECT COUNT(*) FROM exception_events WHERE timestamp BETWEEN :s AND :u",
        {"s": since, "u": until}
    ) or 0
    return {
        "total": int(total),
        "by_type": [{"event_type": r["event_type"], "count": int(r["count"])} for r in by_type],
        "by_vehicle": [{"vehicle": r["vehicle"], "count": int(r["count"]), "driver": r["driver"]} for r in by_vehicle],
        "daily_trend": [{"day": str(r["day"]), "event_type": r["event_type"], "count": int(r["count"])} for r in daily],
    }


def vehicle_maintenance_status(since: datetime | None = None, until: datetime | None = None) -> list[dict[str, Any]]:
    if since is None:
        since = datetime.now(timezone.utc) - timedelta(days=365)
    if until is None:
        until = datetime.now(timezone.utc)
    rows = _exec(
        "SELECT v.id, v.license_plate, v.vin, v.assigned_driver, v.make, v.model, v.year, "
        "COALESCE(MAX(t.odometer_end),0) as odometer, "
        "COALESCE(MAX(t.engine_hours),0) as engine_hours, "
        "COALESCE(SUM(t.distance_miles),0) as total_miles, "
        "COUNT(t.id) as trip_count "
        "FROM vehicles v LEFT JOIN trips t ON t.vehicle_id=v.id AND t.start_time BETWEEN :s AND :u "
        "GROUP BY v.id ORDER BY v.license_plate",
        {"s": since, "u": until}
    )
    result = []
    for r in rows:
        odo = float(r["odometer"])
        result.append({
            "id": r["id"],
            "label": r["assigned_driver"] or r["license_plate"] or r["vin"] or f"V{r['id']}",
            "assigned_driver": r["assigned_driver"] or "",
            "license_plate": r["license_plate"] or "",
            "vin": r["vin"] or "",
            "odo_mi": round(odo / 1609.34, 0) if odo else 0,
            "engine_hours": round(float(r["engine_hours"]), 1),
            "total_miles": round(float(r["total_miles"]), 0),
            "trip_count": int(r["trip_count"]),
        })
    return result


def safety_driver_rankings(since: datetime | None = None, until: datetime | None = None) -> list[dict[str, Any]]:
    if since is None:
        since = datetime.now(timezone.utc) - timedelta(days=365)
    if until is None:
        until = datetime.now(timezone.utc)
    rows = _exec(
        "SELECT d.name, COUNT(t.id) as trip_count, "
        "COALESCE(SUM(t.distance_miles),0) as miles, "
        "COALESCE(SUM(CASE WHEN t.is_seatbelt_off=1 THEN 1 ELSE 0 END),0) as seatbelt_violations, "
        "COUNT(CASE WHEN t.is_seatbelt_off IS NOT NULL THEN 1 END) as seatbelt_recorded, "
        "COALESCE(SUM(CASE WHEN t.after_hours_distance>0 THEN 1 ELSE 0 END),0) as after_hours_trips, "
        "COALESCE(SUM(t.idle_time),0) as idle_time, "
        "COALESCE(SUM(CASE WHEN t.maximum_speed>70 THEN 1 ELSE 0 END),0) as speeding_trips, "
        "COALESCE(SUM(EXTRACT(EPOCH FROM (t.end_time-t.start_time))),0) as total_time "
        "FROM drivers d JOIN trips t ON t.driver_id=d.id "
        "WHERE t.start_time BETWEEN :s AND :u GROUP BY d.id ORDER BY miles DESC",
        {"s": since, "u": until}
    )
    result = []
    for r in rows:
        tc = int(r["trip_count"])
        seat_rec = int(r["seatbelt_recorded"])
        seat_viol = int(r["seatbelt_violations"])
        seat_pct = round(seat_viol / seat_rec * 100, 1) if seat_rec else 0
        ah_pct = round(int(r["after_hours_trips"]) / tc * 100, 1) if tc else 0
        idle_pct = round(float(r["idle_time"]) / float(r["total_time"]) * 100, 1) if float(r["total_time"]) else 0
        spd_pct = round(int(r["speeding_trips"]) / tc * 100, 1) if tc else 0
        score = max(0, round(100 - seat_pct - ah_pct - idle_pct - spd_pct, 1))
        result.append({
            "name": r["name"], "trip_count": tc,
            "seatbelt_violation_pct": seat_pct,
            "after_hours_pct": ah_pct, "idle_pct": idle_pct,
            "speeding_pct": spd_pct, "score": score,
        })
    return sorted(result, key=lambda x: x["score"], reverse=True)

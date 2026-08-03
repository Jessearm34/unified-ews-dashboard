"""Insperity data module — reads from warehouse tables populated by the sync worker.

The sync worker (pull_insperity.py) runs on the DigitalOcean droplet every 10 min,
pulling from Insperity's API and upserting into these warehouse tables:

    insperity_employees    — employee_id, first_name, last_name, email, status
    insperity_employment   — employee_id, hire_date, employment_status, worker_type
    insperity_positions    — employee_id, job_title, department_id, department_name, supervisor_id
    insperity_departments  — department_id, department_name
    insperity_locations    — location_id, location_name
    insperity_communication — employee_id, email, phone
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

import pandas as pd
from sqlalchemy import create_engine, text


def ins_engine():
    """SQLAlchemy engine using the shared DATABASE_URL (reads from warehouse)."""
    url = os.environ.get("DATABASE_URL", "")
    if not url:
        raise RuntimeError("DATABASE_URL not set")
    if url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql+psycopg2://", 1)
    elif url.startswith("postgresql://") and "+psycopg2" not in url:
        url = url.replace("postgresql://", "postgresql+psycopg2://", 1)
    return create_engine(url, connect_args={"sslmode": "require"})


@dataclass
class InsDataset:
    employees: pd.DataFrame = field(default_factory=pd.DataFrame)
    employment: pd.DataFrame = field(default_factory=pd.DataFrame)
    positions: pd.DataFrame = field(default_factory=pd.DataFrame)
    departments: pd.DataFrame = field(default_factory=pd.DataFrame)
    locations: pd.DataFrame = field(default_factory=pd.DataFrame)
    communication: pd.DataFrame = field(default_factory=pd.DataFrame)
    workers: pd.DataFrame = field(default_factory=pd.DataFrame)  # unified view

    @property
    def has_data(self) -> bool:
        return not self.workers.empty or not self.employees.empty


def load_dataset() -> InsDataset | None:
    """Read Insperity data from the warehouse tables."""
    try:
        eng = ins_engine()
        with eng.connect() as conn:
            workers = pd.read_sql("SELECT * FROM insperity_workers", conn)
            # Optional raw tables for debugging
            try:
                employees = pd.read_sql("SELECT * FROM insperity_employees", conn)
            except Exception:
                employees = pd.DataFrame()
            try:
                departments = pd.read_sql("SELECT * FROM insperity_departments", conn)
            except Exception:
                departments = pd.DataFrame()
            try:
                locations = pd.read_sql("SELECT * FROM insperity_locations", conn)
            except Exception:
                locations = pd.DataFrame()
            return InsDataset(
                employees=employees, departments=departments, locations=locations,
                workers=workers,
            )
    except Exception:
        return InsDataset()


def compute_kpis(ds: InsDataset) -> list[dict[str, Any]]:
    """Compute dashboard KPIs from the loaded dataset."""
    kpis = []

    # Employee counts
    total = len(ds.employees)
    active = int((ds.employees["status"].str.lower() == "active").sum()) if not ds.employees.empty and "status" in ds.employees.columns else 0

    kpis.append({"label": "Total Employees", "value": total, "unit": "", "hint": "", "rag": None, "platform": "IN", "delta": None, "delta_up_good": True, "help": "All employees in Insperity", "deltaLabel": ""})
    kpis.append({"label": "Active Workers", "value": active, "unit": "", "hint": f"of {total} total", "rag": None, "platform": "IN", "delta": None, "delta_up_good": True, "help": "Currently active / not terminated", "deltaLabel": ""})

    # Department count
    dept_count = len(ds.departments)
    kpis.append({"label": "Departments", "value": dept_count, "unit": "", "hint": "", "rag": None, "platform": "IN", "delta": None, "delta_up_good": True, "help": "Departments / cost centers", "deltaLabel": ""})

    # Contractor count
    if not ds.employment.empty and "worker_type" in ds.employment.columns:
        contractors = int((ds.employment["worker_type"].str.lower().str.contains("contractor|1099")).sum())
        kpis.append({"label": "Contractors", "value": contractors, "unit": "", "hint": "", "rag": None, "platform": "IN", "delta": None, "delta_up_good": True, "help": "Non-employee workers", "deltaLabel": ""})

    return kpis


def source_label() -> str:
    return "Insperity HR · synced via DigitalOcean droplet"

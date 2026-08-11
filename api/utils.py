"""Shared utility functions for the EWS Dashboard API layer."""

from datetime import date, timedelta
from typing import Optional


def resolve_date_range(range_key, end_date: Optional[date] = None):
    """Return (start, end) for a date range key.

    YTD: Jan 1 to today (actual year-to-date)
    LM:  Last full calendar month
    LQ:  Last full calendar quarter
    LY:  Last full calendar year
    """
    today = end_date or date.today()

    if range_key == "ytd":
        return date(today.year, 1, 1), today

    if range_key == "lm":
        # Last full month — go back to first of this month, then back one day
        first_of_this_month = date(today.year, today.month, 1)
        last_of_last_month = first_of_this_month - timedelta(days=1)
        first_of_last_month = date(last_of_last_month.year, last_of_last_month.month, 1)
        return first_of_last_month, last_of_last_month

    if range_key == "lq":
        # Last full calendar quarter
        current_quarter = (today.month - 1) // 3
        if current_quarter == 0:
            # Q1 — last quarter was Q4 of previous year
            return date(today.year - 1, 10, 1), date(today.year - 1, 12, 31)
        else:
            q_start_month = (current_quarter - 1) * 3 + 1
            q_end_month = q_start_month + 2
            q_end_day = 31 if q_end_month in (3, 12) else 30
            return date(today.year, q_start_month, 1), date(today.year, q_end_month, q_end_day)

    if range_key == "ly":
        # Last full calendar year
        return date(today.year - 1, 1, 1), date(today.year - 1, 12, 31)

    if range_key == "30d":
        return today - timedelta(days=30), today

    if range_key == "90d":
        return today - timedelta(days=90), today

    # "all" — everything from 2020 onward
    return date(2020, 1, 1), today


RANGE_PRESETS = [
    ("ytd", "YTD"),
    ("lm", "Last Month"),
    ("lq", "Last Quarter"),
    ("ly", "Last Year"),
    ("all", "All"),
]


def _rgba(h: str, a: float) -> str:
    h = h.lstrip("#")
    return f"rgba({int(h[0:2],16)},{int(h[2:4],16)},{int(h[4:6],16)},{a})"


def empty(msg: str = "No data for this period"):
    return Div(msg, cls="chart-empty")


# ── Period-over-period delta helpers ───────────────────────────────────


def previous_range(range_key: str, start: date, end: date) -> tuple[date, date]:
    """Return the previous equivalent time range for comparison."""
    duration = (end - start).days
    if range_key == "ytd":
        return date(start.year - 1, start.month, start.day), date(end.year - 1, end.month, end.day)
    if range_key == "lm":
        lm_end = date(start.year, start.month, 1) - timedelta(days=1)
        lm_start = date(lm_end.year, lm_end.month, 1)
        return lm_start, lm_end
    if range_key == "lq":
        return start - timedelta(days=91), end - timedelta(days=91)
    if range_key == "ly":
        return date(start.year - 1, 1, 1), date(start.year - 1, 12, 31)
    if range_key in ("30d", "90d"):
        return start - timedelta(days=duration), end - timedelta(days=duration)
    return start, end


def compute_delta(current: float, previous: float) -> float | None:
    """Return the percentage change ((current - previous) / previous * 100)."""
    if previous == 0:
        return None
    return round((current - previous) / previous * 100, 1)

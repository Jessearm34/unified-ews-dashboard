"""Shared utility functions for the EWS Dashboard API layer."""

from datetime import date, timedelta
from typing import Optional


def resolve_date_range(range_key, end_date: Optional[date] = None):
    """Return (start, end) where end is the last completed month."""
    if end_date is None:
        end_date = date.today()
    # End of last completed month = 1st of current month - 1 day
    end = date(end_date.year, end_date.month, 1) - timedelta(days=1)
    if end < date(2020, 1, 1):
        end = end_date  # fallback if something weird
    if range_key == "ytd":
        return date(end.year, 1, 1), end
    if range_key == "30d":
        return end - timedelta(days=30), end
    if range_key == "90d":
        return end - timedelta(days=90), end
    if range_key == "lm":
        # Last completed month
        lm_end = date(end.year, end.month, 1) - timedelta(days=1)
        lm_start = date(lm_end.year, lm_end.month, 1)
        return lm_start, lm_end
    if range_key == "12m":
        return date(end.year - 1, 1, 1), date(end.year - 1, 12, 31)
    if range_key == "ly":
        return date(end.year - 1, 1, 1), date(end.year - 1, 12, 31)
    return date(2020, 1, 1), end


RANGE_PRESETS = [("ytd", "YTD"), ("lm", "Last month"), ("30d", "30d"), ("90d", "90d"), ("ly", "Last year"), ("all", "All")]


def _rgba(h: str, a: float) -> str:
    h = h.lstrip("#")
    return f"rgba({int(h[0:2],16)},{int(h[2:4],16)},{int(h[4:6],16)},{a})"


def empty(msg: str = "No data for this period"):
    return Div(msg, cls="chart-empty")
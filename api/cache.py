"""In-memory data cache with TTL — shared across all route modules."""

from __future__ import annotations

import time
from typing import Any, Callable, Optional

_data_cache: dict[str, Any] = {}
_cache_ts: dict[str, float] = {}
_DATA_CACHE_TTL = 60  # match frontend poll interval

# Chart HTML cache
_chart_html_cache: dict[str, tuple[str, float]] = {}
_CHART_CACHE_DURATION = 30  # seconds


def cached(key: str, loader: Callable[[], Any], ttl: int | None = None) -> Any:
    """Load data once and cache for ttl seconds."""
    ttl = ttl or _DATA_CACHE_TTL
    now = time.time()
    if key in _data_cache and (now - _cache_ts.get(key, 0) < ttl):
        return _data_cache[key]
    try:
        val = loader()
        if val is not None:
            _data_cache[key] = val
            _cache_ts[key] = now
        return val
    except Exception:
        return None


def clear_cache() -> None:
    _data_cache.clear()
    _cache_ts.clear()
    _chart_html_cache.clear()


def get_cache_stats() -> dict:
    return {
        "data_keys": list(_data_cache.keys()),
        "data_age": {k: f"{time.time() - _cache_ts.get(k, 0):.0f}s" for k in _data_cache},
        "chart_cache_entries": len(_chart_html_cache),
    }
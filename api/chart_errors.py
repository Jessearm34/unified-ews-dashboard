"""Chart error logging — replace bare ``except Exception: pass`` with logged failures."""

from __future__ import annotations

import logging
import traceback
from typing import Callable

log = logging.getLogger("ewsd.chart")


def safe_chart(builder: Callable, chart_name: str, *args, **kwargs):
    """Call a chart builder, log any failure, return empty HTML on error."""
    try:
        return builder(*args, **kwargs)
    except Exception:
        log.exception("Chart render failed: %s", chart_name)
        return f"<div class='chart-empty'>Error rendering {chart_name}</div>"

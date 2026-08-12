from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class DataSheet:
    """A single dataset pulled from SiteDocs, ready to be exported as a CSV sheet."""

    dataset: str
    sheet: str
    rows: list[dict[str, Any]]
    metadata: dict[str, Any] = field(default_factory=dict)

from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from src.models import DataSheet


def _safe_name(value: str) -> str:
    cleaned = re.sub(r"[^\w\-. ]+", "", value, flags=re.UNICODE)
    cleaned = re.sub(r"\s+", "_", cleaned.strip())
    return cleaned or "unnamed"


class CsvExporter:
    def __init__(self, output_dir: Path) -> None:
        self.output_dir = output_dir
        self.run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")

    def export_all(self, sheets: list[DataSheet]) -> list[Path]:
        written: list[Path] = []
        for sheet in sheets:
            folder = self.output_dir / _safe_name(sheet.dataset)
            folder.mkdir(parents=True, exist_ok=True)
            path = folder / f"{_safe_name(sheet.sheet)}.csv"
            pd.DataFrame(sheet.rows).to_csv(path, index=False)
            written.append(path)

        manifest_dir = self.output_dir / "_manifests"
        manifest_dir.mkdir(parents=True, exist_ok=True)
        pd.DataFrame(
            [
                {
                    "run_id": self.run_id,
                    "dataset": s.dataset,
                    "sheet": s.sheet,
                    "row_count": len(s.rows),
                    **{f"meta_{k}": v for k, v in s.metadata.items()},
                }
                for s in sheets
            ]
        ).to_csv(manifest_dir / f"export_{self.run_id}.csv", index=False)

        pd.DataFrame({"path": [str(p) for p in written]}).to_csv(
            self.output_dir / "file_index.csv", index=False
        )
        return written

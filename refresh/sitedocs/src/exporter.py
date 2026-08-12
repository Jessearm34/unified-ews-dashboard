"""CSV exporter — writes pulled datasets to CSV files on disk."""

from __future__ import annotations

import csv
import logging
from datetime import datetime
from pathlib import Path

from src.config import settings
from src.models import DataSheet

logger = logging.getLogger(__name__)


class CsvExporter:
    def __init__(self) -> None:
        self.output_dir = settings.output_dir

    def export_all(self, sheets: list[DataSheet]) -> dict[str, Path | None]:
        """Write each DataSheet to its CSV path.

        Returns a dict of ``{dataset: path or None}``.
        """
        results: dict[str, Path | None] = {}
        run_id = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        manifest_rows: list[dict[str, str]] = []

        for sheet in sheets:
            ds = sheet.dataset
            dest = self.output_dir / ds / f"{sheet.sheet}.csv"
            dest.parent.mkdir(parents=True, exist_ok=True)
            try:
                self._write_csv(dest, sheet.rows)
                results[ds] = dest
                manifest_rows.append(
                    {
                        "dataset": ds,
                        "sheet": sheet.sheet,
                        "path": str(dest.relative_to(self.output_dir)),
                        "rows": str(len(sheet.rows)),
                    }
                )
                logger.info("  wrote %s (%d rows)", dest, len(sheet.rows))
            except Exception as exc:
                logger.error("  failed to write %s: %s", dest, exc)
                results[ds] = None

        # Write manifest
        manifest_dir = self.output_dir / "_manifests"
        manifest_dir.mkdir(parents=True, exist_ok=True)
        manifest_path = manifest_dir / f"export_{run_id}.csv"
        self._write_csv(manifest_path, manifest_rows)
        logger.info("  manifest: %s", manifest_path)

        # Write file index
        idx_path = self.output_dir / "file_index.csv"
        idx_rows = [
            {"dataset": ds, "file": str(path.relative_to(self.output_dir))}
            for ds, path in results.items()
            if path is not None
        ]
        self._write_csv(idx_path, idx_rows)

        return results

    @staticmethod
    def _write_csv(path: Path, rows: list[dict]) -> None:
        if not rows:
            # Write empty file with just headers from first-row keys
            path.write_text("", encoding="utf-8")
            return
        keys = list(rows[0].keys())
        with path.open("w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=keys)
            writer.writeheader()
            for row in rows:
                # Flatten any nested dicts/values to JSON strings
                cleaned = {
                    k: (
                        str(v)
                        if isinstance(v, (list, dict))
                        else v
                    )
                    for k, v in row.items()
                }
                writer.writerow(cleaned)

"""Main — SiteDocs data export entry point."""

from __future__ import annotations

import logging
import sys

from src.config import settings
from src.exporter import CsvExporter
from src.sitedocs_client import SiteDocsClient

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("main")


def main() -> None:
    logger.info("═" * 50)
    logger.info("SiteDocs Data Export")
    logger.info("Output: %s", settings.output_dir)
    logger.info("Stub mode: %s", settings.use_stub_data or "auto" if not settings.sitedocs_api_key or settings.sitedocs_api_key.strip().upper().startswith("PLACEHOLDER") else False)
    logger.info("═" * 50)

    client = SiteDocsClient()

    if not client.credentials_ready():
        logger.info("No real SiteDocs API key — returning stub data")
        settings.use_stub_data = True

    sheets = client.fetch_all()
    logger.info("\nFetched %d datasets", len(sheets))

    exporter = CsvExporter()
    results = exporter.export_all(sheets)

    ok = sum(1 for v in results.values() if v is not None)
    fail = sum(1 for v in results.values() if v is None)
    logger.info("\nDone: %d exported, %d failed", ok, fail)
    for ds, path in results.items():
        status = "✓" if path else "✗"
        logger.info("  %s %s %s", status, ds, path or "")

    if fail:
        logger.warning("Export failures — some datasets may be missing")
        if not settings.use_stub_data:
            sys.exit(1)
        logger.info("(Continuing in stub mode)")


if __name__ == "__main__":
    main()

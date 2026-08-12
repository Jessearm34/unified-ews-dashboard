"""Standalone config for the GeoTab sync worker.

Reads the same GEOTAB_* env vars the original geotab-data-export app used,
plus DATABASE_URL for the write target. No pydantic-settings dependency.
"""

from __future__ import annotations

import os


class GeotabSettings:
    def __init__(self) -> None:
        self.geotab_database: str | None = os.getenv("GEOTAB_DATABASE")
        self.geotab_username: str | None = os.getenv("GEOTAB_USERNAME")
        self.geotab_password: str | None = os.getenv("GEOTAB_PASSWORD")
        self.geotab_api_key: str | None = os.getenv("GEOTAB_API_KEY")
        self.geotab_server: str = os.getenv("GEOTAB_SERVER", "my.geotab.com")
        try:
            self.geotab_timeout_seconds: int = int(os.getenv("GEOTAB_TIMEOUT_SECONDS", "30"))
        except ValueError:
            self.geotab_timeout_seconds = 30

    @property
    def is_geotab_configured(self) -> bool:
        return all([self.geotab_database, self.geotab_username, self.geotab_password])


def missing_geotab_credentials(settings: GeotabSettings) -> list[str]:
    return [
        name
        for name, value in (
            ("GEOTAB_DATABASE", settings.geotab_database),
            ("GEOTAB_USERNAME", settings.geotab_username),
            ("GEOTAB_PASSWORD", settings.geotab_password),
        )
        if not value
    ]


def get_settings() -> GeotabSettings:
    return GeotabSettings()

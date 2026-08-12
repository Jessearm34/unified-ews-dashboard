from __future__ import annotations

import os
from pathlib import Path

import yaml
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
DOTENV_PATH = ROOT / ".env"
load_dotenv(DOTENV_PATH, override=True)


def _bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name, str(default)).strip().lower()
    return raw in ("1", "true", "yes", "on")


def is_placeholder(value: str | None) -> bool:
    if not value:
        return True
    return value.strip().upper().startswith("PLACEHOLDER")


class Settings:
    output_dir: Path = Path(os.getenv("OUTPUT_DIR", str(ROOT / "output"))).expanduser().resolve()
    use_stub_data: bool = _bool("USE_STUB_DATA", False)

    # SiteDocs API
    sitedocs_api_key: str = os.getenv("SITEDOCS_API_KEY", "")
    sitedocs_api_base: str = os.getenv("SITEDOCS_API_BASE", "https://api-1.sitedocs.com")
    sitedocs_company_id: str = os.getenv("SITEDOCS_COMPANY_ID", "")
    sitedocs_employee_id: str = os.getenv("SITEDOCS_EMPLOYEE_ID", "")

    @property
    def headers(self) -> dict[str, str]:
        return {"Authorization": self.sitedocs_api_key, "Accept": "application/json"}

    def datasets(self) -> list[dict]:
        path = ROOT / "config" / "datasets.yaml"
        with path.open(encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        return data.get("datasets", [])


settings = Settings()

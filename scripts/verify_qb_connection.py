#!/usr/bin/env python3
"""Verify production QuickBooks credentials from .env."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import requests
from requests.auth import HTTPBasicAuth
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env", override=True)


def missing(name: str) -> bool:
    value = os.getenv(name)
    return not value or value.strip() == ""


def print_env_status() -> None:
    required = [
        "QUICKBOOKS_CLIENT_ID",
        "QUICKBOOKS_CLIENT_SECRET",
        "QUICKBOOKS_REDIRECT_URI",
        "QUICKBOOKS_REALM_ID",
    ]
    print("Checking QuickBooks configuration from .env")
    for name in required:
        value = os.getenv(name)
        print(f"  {name}: {'SET' if value and value.strip() else 'MISSING'}")
    env_value = os.getenv("QUICKBOOKS_ENVIRONMENT", "production")
    print(f"  QUICKBOOKS_ENVIRONMENT value used: {env_value}")
    token = os.getenv("QUICKBOOKS_ACCESS_TOKEN")
    refresh = os.getenv("QUICKBOOKS_REFRESH_TOKEN")
    print(f"  QUICKBOOKS_ACCESS_TOKEN: {'SET' if token and token.strip() else 'MISSING'}")
    print(f"  QUICKBOOKS_REFRESH_TOKEN: {'SET' if refresh and refresh.strip() else 'MISSING'}")


def get_base_url(environment: str) -> str:
    return "https://quickbooks.api.intuit.com"


def company_info() -> None:
    env = os.getenv("QUICKBOOKS_ENVIRONMENT", "production").strip().lower()
    realm = os.getenv("QUICKBOOKS_REALM_ID", "").strip()
    token = os.getenv("QUICKBOOKS_ACCESS_TOKEN", "").strip()

    if not realm:
        print("ERROR: QUICKBOOKS_REALM_ID is missing.")
        sys.exit(1)
    if not token:
        print("ERROR: QUICKBOOKS_ACCESS_TOKEN is missing.")
        sys.exit(1)

    base_url = get_base_url(env)
    url = f"{base_url}/v3/company/{realm}/companyinfo/{realm}"
    print("Calling QuickBooks production companyinfo endpoint:")
    print(f"  {url}")

    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
    }

    resp = requests.get(url, headers=headers, timeout=30)
    print(f"HTTP {resp.status_code}")
    content_type = resp.headers.get("Content-Type", "<missing>")
    print(f"Content-Type: {content_type}")

    body = resp.text.strip()
    if resp.status_code == 200:
        try:
            data = resp.json()
        except ValueError:
            print("ERROR: Response is not valid JSON.")
            print(body[:1000])
            sys.exit(1)
        company = data.get("CompanyInfo") or data.get("CompanyInfoResponse")
        print("Success: QuickBooks returned company info.")
        if company and isinstance(company, dict):
            print(f"  CompanyName: {company.get('CompanyName')}")
            print(f"  LegalName: {company.get('LegalName')}")
            print(f"  CompanyId: {company.get('CompanyId')}")
            print(f"  Country: {company.get('Country')}")
        else:
            print("  Company info payload was not in the expected shape.")
            print(data)
        return

    print("ERROR: QuickBooks request failed.")
    if content_type.startswith("application/json"):
        try:
            print(resp.json())
        except ValueError:
            print(body[:1000])
    else:
        print(body[:1000])
    if resp.status_code == 401:
        refreshed = False
        if refresh_access_token():
            refreshed = True
            print("Retrying QuickBooks companyinfo with refreshed access token...")
            return company_info()
        print("Hint: Access token may be invalid or expired.")
    elif resp.status_code == 404:
        print("Hint: RealmId may be wrong for this token or environment.")
    elif resp.status_code == 429:
        print("Hint: Too many requests. Retry after a while.")
    sys.exit(1)


def refresh_access_token() -> bool:
    client_id = os.getenv("QUICKBOOKS_CLIENT_ID", "").strip()
    client_secret = os.getenv("QUICKBOOKS_CLIENT_SECRET", "").strip()
    refresh_token = os.getenv("QUICKBOOKS_REFRESH_TOKEN", "").strip()

    if not client_id or not client_secret or not refresh_token:
        print("Cannot refresh token: QUICKBOOKS_CLIENT_ID, QUICKBOOKS_CLIENT_SECRET, or QUICKBOOKS_REFRESH_TOKEN is missing.")
        return False

    print("Access token expired. Refreshing access token using QUICKBOOKS_REFRESH_TOKEN...")
    token_url = "https://oauth.platform.intuit.com/oauth2/v1/tokens/bearer"
    payload = {
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
    }
    headers = {"Accept": "application/json"}
    resp = None
    try:
        resp = requests.post(
            token_url,
            data=payload,
            auth=HTTPBasicAuth(client_id, client_secret),
            headers=headers,
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
    except Exception as exc:
        print(f"Refresh token request failed: {exc}")
        if resp is not None and resp.text:
            print(resp.text[:1000])
        return False

    access_token = data.get("access_token")
    new_refresh = data.get("refresh_token")
    if not access_token:
        print("Refresh response did not return an access token.")
        return False

    updates = {"QUICKBOOKS_ACCESS_TOKEN": access_token}
    if new_refresh:
        updates["QUICKBOOKS_REFRESH_TOKEN"] = new_refresh
    write_env_values(updates)
    load_dotenv(ROOT / ".env", override=True)
    return True


def write_env_values(replacements: dict[str, str]) -> None:
    path = ROOT / ".env"
    text = path.read_text()
    lines = text.splitlines()
    updated: list[str] = []
    remaining = replacements.copy()
    for line in lines:
        if not line or line.lstrip().startswith("#") or "=" not in line:
            updated.append(line)
            continue
        key, sep, value = line.partition("=")
        key = key.strip()
        if key in remaining:
            updated.append(f"{key}={remaining.pop(key)}")
        else:
            updated.append(line)
    for key, value in remaining.items():
        updated.append(f"{key}={value}")
    path.write_text("\n".join(updated) + "\n")


def main() -> int:
    print_env_status()
    print()
    company_info()
    return 0


if __name__ == "__main__":
    sys.exit(main())
#!/usr/bin/env python3
"""Obtain QuickBooks OAuth tokens for .env"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from dotenv import load_dotenv, set_key

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
load_dotenv(ROOT / ".env", override=True)

try:
    from intuitlib.client import AuthClient
    from intuitlib.enums import Scopes
except ImportError:
    print("Install dependencies: pip install -r requirements.txt")
    sys.exit(1)


def main() -> None:
    quickbooks_environment = os.environ["QUICKBOOKS_ENVIRONMENT"]
    quickbooks_redirect_uri = os.environ["QUICKBOOKS_REDIRECT_URI"]
    print(f"Using QuickBooks environment: {quickbooks_environment}")
    print(f"Using redirect URI: {quickbooks_redirect_uri}")
    auth_client = AuthClient(
        client_id=os.environ["QUICKBOOKS_CLIENT_ID"],
        client_secret=os.environ["QUICKBOOKS_CLIENT_SECRET"],
        redirect_uri=quickbooks_redirect_uri,
        environment=quickbooks_environment,
    )
    print("\nOpen this URL in a browser:\n")
    print(auth_client.get_authorization_url([Scopes.ACCOUNTING]))
    print("\nPaste the full redirect URL here:\n")
    redirect = input().strip().strip("'").strip('"')
    params = parse_qs(urlparse(redirect).query)
    code = params.get("code", [None])[0]
    realm_id = params.get("realmId", [None])[0]
    if not code:
        print("No authorization code in URL.")
        sys.exit(1)
    auth_client.get_bearer_token(code, realm_id=realm_id)
    print("\nAdd to .env:\n")
    print(f"QUICKBOOKS_REALM_ID={realm_id}")
    print(f"QUICKBOOKS_ACCESS_TOKEN={auth_client.access_token}")
    print(f"QUICKBOOKS_REFRESH_TOKEN={auth_client.refresh_token}")
    set_key(ROOT / ".env", "QUICKBOOKS_REALM_ID", realm_id)
    set_key(ROOT / ".env", "QUICKBOOKS_ACCESS_TOKEN", auth_client.access_token)
    set_key(ROOT / ".env", "QUICKBOOKS_REFRESH_TOKEN", auth_client.refresh_token)
    print("\nSaved credentials to .env")


if __name__ == "__main__":
    main()

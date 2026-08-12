from __future__ import annotations

import logging
import re
from datetime import date
from typing import Any
from urllib.parse import quote

import requests

from src.config import is_placeholder, settings
from src.models import DataSheet

logger = logging.getLogger(__name__)

# Profit & Loss is a *report* (nested), not a queryable entity. We pull it
# summarized by month for both accounting bases, over this many years back,
# and flatten it into tidy rows the warehouse/dashboard can aggregate.
PNL_LOOKBACK_YEARS = 5
PNL_BASES = ("Accrual", "Cash")
# QuickBooks' query API returns at most 1000 rows per page; we paginate with
# STARTPOSITION to pull everything (e.g. >1000 invoices).
QUERY_PAGE_SIZE = 1000
# Top-level P&L groups that own detail accounts (used to tag leaf rows).
_PNL_TOP_SECTIONS = {"Income", "COGS", "Expenses", "OtherIncome", "OtherExpenses"}


class QuickBooksClient:
    def __init__(self) -> None:
        self.session = requests.Session()
        self.dataset_defs = settings.datasets()
        self._refresh_access_token_if_needed()

    def _refresh_access_token_if_needed(self) -> None:
        """Use refresh token to get a fresh access token if needed."""
        if (
            not settings.refresh_token
            or is_placeholder(settings.refresh_token)
            or not settings.client_id
            or is_placeholder(settings.client_id)
            or not settings.client_secret
            or is_placeholder(settings.client_secret)
        ):
            return
        
        try:
            # Correct Intuit OAuth 2.0 token endpoint
            token_url = "https://oauth.platform.intuit.com/oauth2/v1/tokens/bearer"
            payload = {
                "grant_type": "refresh_token",
                "refresh_token": settings.refresh_token,
            }
            auth = (settings.client_id, settings.client_secret)
            headers = {"Accept": "application/json"}
            response = requests.post(token_url, data=payload, auth=auth, headers=headers, timeout=10)
            response.raise_for_status()
            data = response.json()
            new_token = data.get("access_token")
            new_refresh = data.get("refresh_token")
            if new_token:
                settings.access_token = new_token
                if new_refresh:
                    settings.refresh_token = new_refresh
                settings.save_oauth_tokens(new_token, new_refresh or settings.refresh_token)
                logger.info("✓ Refreshed access token from QuickBooks")
        except Exception as e:
            logger.warning(f"Could not refresh token: {e}. Continuing with existing token.")

    def _can_refresh(self) -> bool:
        return bool(
            settings.refresh_token
            and not is_placeholder(settings.refresh_token)
            and settings.client_id
            and not is_placeholder(settings.client_id)
            and settings.client_secret
            and not is_placeholder(settings.client_secret)
        )

    def credentials_ready(self) -> bool:
        return not any(
            is_placeholder(v)
            for v in (
                settings.client_id,
                settings.client_secret,
                settings.realm_id,
                settings.access_token,
            )
        )

    def _default_headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {settings.access_token}",
            "Accept": "application/json",
        }

    def _refresh_and_retry(self, url: str) -> Any:
        response = self.session.get(url, headers=self._default_headers(), timeout=60)
        if response.status_code == 401 and self._can_refresh():
            logger.info("Access token expired; refreshing and retrying request.")
            self._refresh_access_token_if_needed()
            response = self.session.get(url, headers=self._default_headers(), timeout=60)
        response.raise_for_status()
        return response.json()
    def fetch_all(self) -> list[DataSheet]:
        if not self.credentials_ready():
            logger.error("QuickBooks credentials not ready.")
            raise ValueError("Missing QuickBooks API credentials in environment.")

        realm = settings.realm_id
        sheets: list[DataSheet] = []

        for definition in self.dataset_defs:
            name = definition["name"]
            query = definition.get("query", "")
            rows = self._run_query_paged(query)
            sheets.append(
                DataSheet(
                    dataset=name,
                    sheet=name,
                    rows=rows,
                    metadata={"query": query, "row_count": len(rows)},
                )
            )

        sheets.extend(self._fetch_pnl_sheets())
        return sheets

    def _run_query_paged(self, query: str) -> list[dict[str, Any]]:
        """Run a QuickBooks query, paging past the 1000-row API limit.

        Any MAXRESULTS/STARTPOSITION in the configured query is stripped; we
        drive pagination ourselves with STARTPOSITION until a short page.
        """
        base = re.sub(r"\s+(MAXRESULTS|STARTPOSITION)\s+\d+", "", query,
                      flags=re.IGNORECASE).strip()
        realm = settings.realm_id
        rows: list[dict[str, Any]] = []
        position = 1
        while True:
            paged = f"{base} STARTPOSITION {position} MAXRESULTS {QUERY_PAGE_SIZE}"
            url = (
                f"{settings.api_base_url}/v3/company/{realm}/query"
                f"?query={quote(paged)}&minorversion=65"
            )
            page = self._parse_query(self._refresh_and_retry(url))
            rows.extend(page)
            if len(page) < QUERY_PAGE_SIZE:
                break
            position += QUERY_PAGE_SIZE
        return rows

    # ----- Profit & Loss report ------------------------------------------- #

    def _fetch_pnl_sheets(self) -> list[DataSheet]:
        """Pull the monthly P&L for each accounting basis and flatten it.

        Produces two landing tables: ``quickbooks_pnl`` (section totals per
        month/basis) and ``quickbooks_pnl_detail`` (per-account amounts).
        """
        end = date.today()
        start = date(end.year - PNL_LOOKBACK_YEARS, 1, 1)
        totals: list[dict[str, Any]] = []
        detail: list[dict[str, Any]] = []
        for basis in PNL_BASES:
            url = (
                f"{settings.api_base_url}/v3/company/{settings.realm_id}"
                f"/reports/ProfitAndLoss?start_date={start.isoformat()}"
                f"&end_date={end.isoformat()}&summarize_column_by=Month"
                f"&accounting_method={basis}&minorversion=65"
            )
            try:
                report = self._refresh_and_retry(url)
                t, d = self._flatten_pnl(report, basis)
                totals.extend(t)
                detail.extend(d)
                logger.info("✓ P&L (%s): %d section rows, %d detail rows", basis, len(t), len(d))
            except Exception as exc:  # one basis failing shouldn't kill the export
                logger.warning("Could not fetch P&L (%s): %s", basis, exc)

        sheets: list[DataSheet] = []
        if totals:
            sheets.append(DataSheet(dataset="pnl", sheet="pnl", rows=totals,
                                    metadata={"report": "ProfitAndLoss"}))
        if detail:
            sheets.append(DataSheet(dataset="pnl_detail", sheet="pnl_detail", rows=detail,
                                    metadata={"report": "ProfitAndLoss"}))
        return sheets

    @staticmethod
    def _flatten_pnl(report: dict[str, Any], basis: str) -> tuple[list[dict], list[dict]]:
        """Flatten a summarize-by-month ProfitAndLoss report.

        Returns (section_totals, account_detail). Section totals come from each
        grouped row's Summary; detail comes from leaf Data rows, tagged with the
        nearest top-level section (Income/COGS/Expenses/Other*).
        """
        columns = report.get("Columns", {}).get("Column", [])
        month_cols: dict[int, str] = {}
        for i, col in enumerate(columns):
            md = {m.get("Name"): m.get("Value") for m in col.get("MetaData", [])}
            if md.get("StartDate"):
                month_cols[i] = md["StartDate"]  # 'YYYY-MM-01'

        def num(coldata: list, i: int):
            if i >= len(coldata):
                return None
            try:
                return float(coldata[i].get("value"))
            except (TypeError, ValueError):
                return None

        totals: list[dict] = []
        detail: list[dict] = []

        def walk(rows: list[dict], section: str | None) -> None:
            for row in rows:
                group = row.get("group")
                summary = (row.get("Summary") or {}).get("ColData")
                if group and summary:
                    for i, month in month_cols.items():
                        val = num(summary, i)
                        if val is not None:
                            totals.append({"basis": basis, "month": month,
                                           "section": group, "amount": val})
                current = group if group in _PNL_TOP_SECTIONS else section
                coldata = row.get("ColData")
                if row.get("type") == "Data" and coldata:
                    account = coldata[0].get("value") or ""
                    for i, month in month_cols.items():
                        val = num(coldata, i)
                        if val:  # drop empty/zero cells to keep detail compact
                            detail.append({"basis": basis, "month": month,
                                           "section": current or "", "account": account,
                                           "amount": val})
                sub = row.get("Rows")
                if isinstance(sub, dict):
                    walk(sub.get("Row", []), current)

        walk(report.get("Rows", {}).get("Row", []), None)
        return totals, detail

    def _parse_query(self, payload: dict[str, Any]) -> list[dict[str, Any]]:
        query_response = payload.get("QueryResponse", {})
        for key, value in query_response.items():
            if isinstance(value, list) and key not in ("startPosition", "maxResults"):
                return value
        return []

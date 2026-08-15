"""Ticker ? CIK mapping from SEC company_tickers.json."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

from edgar_filings.client import pad_cik


@dataclass(frozen=True)
class CompanyRef:
    cik: str
    ticker: str
    name: str


def parse_company_tickers(payload: dict[str, Any] | list[Any]) -> list[CompanyRef]:
    """Parse SEC company_tickers.json (object of numbered entries)."""
    rows: Iterable[Any]
    if isinstance(payload, list):
        rows = payload
    else:
        rows = payload.values()

    companies: list[CompanyRef] = []
    for item in rows:
        if not isinstance(item, dict):
            continue
        ticker = str(item.get("ticker") or "").upper().strip()
        name = str(item.get("title") or item.get("name") or "").strip()
        cik_raw = item.get("cik_str", item.get("cik"))
        if not ticker or cik_raw is None:
            continue
        companies.append(CompanyRef(cik=pad_cik(cik_str(cik_raw)), ticker=ticker, name=name))
    return companies


def cik_str(value: Any) -> str:
    return str(int(str(value).strip()))


def find_by_ticker(companies: Iterable[CompanyRef], ticker: str) -> CompanyRef:
    needle = ticker.upper().strip()
    for company in companies:
        if company.ticker == needle:
            return company
    raise KeyError(f"Unknown ticker: {ticker}")

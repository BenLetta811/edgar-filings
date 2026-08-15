"""Ingest EDGAR daily indexes and XBRL facts into SQLite."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Iterable

from edgar_filings.client import EdgarClient
from edgar_filings.daily_index import parse_master_idx
from edgar_filings.db import Database
from edgar_filings.facts import parse_company_facts
from edgar_filings.tickers import CompanyRef, index_by_cik, parse_company_tickers

DEFAULT_FORMS = ("10-K", "10-Q", "8-K")
FACT_FORMS = {"10-K", "10-Q", "10-K/A", "10-Q/A"}
MAX_RANGE_DAYS = 62


class IngestError(RuntimeError):
    """Raised when an ingest job cannot complete."""


@dataclass
class IngestResult:
    days: list[str] = field(default_factory=list)
    companies: int = 0
    filings: int = 0
    facts: int = 0

    @property
    def message(self) -> str:
        day_bit = ", ".join(self.days) if self.days else "no published days"
        return (
            f"Loaded {day_bit}: {self.companies} companies, "
            f"{self.filings} filings, {self.facts} XBRL facts"
        )


def _forms(forms: Iterable[str] | None) -> list[str]:
    if not forms:
        return list(DEFAULT_FORMS)
    return [part.strip() for part in forms if part and part.strip()]


def _store_index(
    db: Database,
    payload: str,
    ticker_map: dict[str, CompanyRef],
    forms: list[str],
    *,
    skip_facts: bool,
    max_fact_companies: int,
    client: EdgarClient,
    seen_fact_ciks: list[str],
) -> tuple[set[str], int, int]:
    filings, names = parse_master_idx(payload, forms=forms)
    companies: dict[str, CompanyRef] = {}
    for filing in filings:
        if filing.cik in companies:
            continue
        known = ticker_map.get(filing.cik)
        companies[filing.cik] = known or CompanyRef(
            cik=filing.cik,
            ticker="",
            name=names.get(filing.cik, ""),
        )
        db.upsert_company(companies[filing.cik])
    n_filings = db.upsert_filings(filings)
    n_facts = 0
    if not skip_facts:
        for filing in filings:
            if filing.form.upper() not in FACT_FORMS:
                continue
            if filing.cik in seen_fact_ciks:
                continue
            if len(seen_fact_ciks) >= max(max_fact_companies, 0):
                break
            seen_fact_ciks.append(filing.cik)
            facts_payload = client.company_facts(filing.cik)
            if facts_payload:
                n_facts += db.upsert_facts(parse_company_facts(facts_payload))
    return set(companies), n_filings, n_facts


def ingest_latest(
    db: Database,
    *,
    as_of: date | None = None,
    lookback_days: int = 10,
    forms: Iterable[str] | None = None,
    skip_facts: bool = False,
    max_fact_companies: int = 40,
    client: EdgarClient | None = None,
) -> IngestResult:
    client = client or EdgarClient()
    form_list = _forms(forms)
    try:
        ticker_payload = client.company_tickers()
    except Exception as exc:
        raise IngestError(
            "SEC request failed. Set EDGAR_USER_AGENT to a real name and email "
            f"(not a GitHub noreply address). {exc}"
        ) from exc

    if as_of:
        candidates = [as_of]
    else:
        start = date.today()
        candidates = [start - timedelta(days=i) for i in range(max(lookback_days, 1))]

    payload = None
    index_day = None
    for day in candidates:
        payload = client.daily_master(day)
        if payload:
            index_day = day
            break
    if not payload or index_day is None:
        raise IngestError("No published daily master index found in the lookback window.")

    ticker_map = index_by_cik(parse_company_tickers(ticker_payload))
    company_ciks, filings, facts = _store_index(
        db,
        payload,
        ticker_map,
        form_list,
        skip_facts=skip_facts,
        max_fact_companies=max_fact_companies,
        client=client,
        seen_fact_ciks=[],
    )
    return IngestResult(
        days=[index_day.isoformat()],
        companies=len(company_ciks),
        filings=filings,
        facts=facts,
    )


def ingest_range(
    db: Database,
    start: date,
    end: date,
    *,
    forms: Iterable[str] | None = None,
    skip_facts: bool = False,
    max_fact_companies: int = 25,
    client: EdgarClient | None = None,
) -> IngestResult:
    if end < start:
        start, end = end, start
    span = (end - start).days + 1
    if span > MAX_RANGE_DAYS:
        raise IngestError(f"Date range is {span} days; maximum is {MAX_RANGE_DAYS}.")

    client = client or EdgarClient()
    form_list = _forms(forms)
    try:
        ticker_payload = client.company_tickers()
    except Exception as exc:
        raise IngestError(
            "SEC request failed. Set EDGAR_USER_AGENT to a real name and email "
            f"(not a GitHub noreply address). {exc}"
        ) from exc

    ticker_map = index_by_cik(parse_company_tickers(ticker_payload))
    result = IngestResult()
    seen_fact_ciks: list[str] = []
    all_companies: set[str] = set()
    day = start
    while day <= end:
        payload = client.daily_master(day)
        if payload:
            company_ciks, filings, facts = _store_index(
                db,
                payload,
                ticker_map,
                form_list,
                skip_facts=skip_facts,
                max_fact_companies=max_fact_companies,
                client=client,
                seen_fact_ciks=seen_fact_ciks,
            )
            result.days.append(day.isoformat())
            result.filings += filings
            result.facts += facts
            all_companies.update(company_ciks)
        day += timedelta(days=1)

    if not result.days:
        raise IngestError("No published daily master index found in that date range.")
    result.companies = len(all_companies)
    return result

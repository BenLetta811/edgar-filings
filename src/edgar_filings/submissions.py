"""Parse EDGAR submissions JSON into filing metadata + document URLs."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

from edgar_filings.client import document_url, pad_cik


@dataclass(frozen=True)
class Filing:
    accession: str
    cik: str
    form: str
    filed_at: str
    report_date: str
    primary_document: str
    document_url: str


def parse_submissions(
    payload: dict[str, Any],
    forms: Iterable[str] | None = None,
) -> list[Filing]:
    cik = pad_cik(payload.get("cik", ""))
    recent = (payload.get("filings") or {}).get("recent") or {}
    accessions = recent.get("accessionNumber") or []
    form_list = recent.get("form") or []
    filing_dates = recent.get("filingDate") or []
    report_dates = recent.get("reportDate") or []
    primary_docs = recent.get("primaryDocument") or []

    allowed = {f.strip().upper() for f in forms} if forms else None
    filings: list[Filing] = []
    count = min(len(accessions), len(form_list), len(filing_dates), len(primary_docs))
    for i in range(count):
        form = str(form_list[i]).strip()
        if allowed and form.upper() not in allowed:
            continue
        accession = str(accessions[i]).strip()
        primary = str(primary_docs[i]).strip()
        report_date = ""
        if i < len(report_dates) and report_dates[i] is not None:
            report_date = str(report_dates[i]).strip()
        filings.append(
            Filing(
                accession=accession,
                cik=cik,
                form=form,
                filed_at=str(filing_dates[i]).strip(),
                report_date=report_date,
                primary_document=primary,
                document_url=document_url(cik, accession, primary) if primary else "",
            )
        )
    return filings

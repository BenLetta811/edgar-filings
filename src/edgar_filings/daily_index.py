"""Parse EDGAR daily master.idx files into filing rows."""

from __future__ import annotations

from collections.abc import Iterable

from edgar_filings.client import pad_cik
from edgar_filings.submissions import Filing

ARCHIVES_BASE = "https://www.sec.gov/Archives/"


def parse_master_idx(
    text: str, forms: Iterable[str] | None = None
) -> tuple[list[Filing], dict[str, str]]:
    """Parse a daily master.idx body.

    Rows after the header are: CIK|Company Name|Form Type|Date Filed|Filename
    Returns filings plus a CIK -> company name map from the index.
    """
    allowed = {f.strip().upper() for f in forms} if forms else None
    filings: list[Filing] = []
    names: dict[str, str] = {}
    in_table = False
    for raw in text.splitlines():
        line = raw.strip()
        if not in_table:
            if line.startswith("CIK|") or line.lower().startswith("cik|company name"):
                in_table = True
            continue
        if not line or line.startswith("-"):
            continue
        parts = line.split("|")
        if len(parts) < 5:
            continue
        cik_raw, name, form, filed_at, filename = parts[0], parts[1], parts[2], parts[3], parts[4]
        form = form.strip()
        if allowed and form.upper() not in allowed:
            continue
        cik = pad_cik(cik_raw)
        path = filename.strip().lstrip("/")
        accession = _accession_from_filename(path)
        primary = path.rsplit("/", 1)[-1]
        names[cik] = name.strip()
        filings.append(
            Filing(
                accession=accession,
                cik=cik,
                form=form,
                filed_at=_normalize_filed_at(filed_at.strip()),
                report_date="",
                primary_document=primary,
                document_url=ARCHIVES_BASE + path if path else "",
            )
        )
    return filings, names


def _accession_from_filename(path: str) -> str:
    stem = path.rsplit("/", 1)[-1]
    if stem.endswith(".txt"):
        stem = stem[:-4]
    if "-" in stem:
        return stem
    if len(stem) >= 18 and stem.isdigit():
        return f"{stem[:10]}-{stem[10:12]}-{stem[12:]}"
    return stem


def _normalize_filed_at(value: str) -> str:
    digits = value.replace("-", "")
    if len(digits) == 8 and digits.isdigit():
        return f"{digits[:4]}-{digits[4:6]}-{digits[6:]}"
    return value

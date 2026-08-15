"""SQLite storage for companies, filings, and XBRL facts."""

from __future__ import annotations

import os
import sqlite3
from collections.abc import Iterable, Sequence
from pathlib import Path

from edgar_filings.facts import XbrlFact
from edgar_filings.submissions import Filing
from edgar_filings.tickers import CompanyRef

SCHEMA = """
CREATE TABLE IF NOT EXISTS companies (
    cik TEXT PRIMARY KEY,
    ticker TEXT NOT NULL,
    name TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_companies_ticker ON companies (ticker);

CREATE TABLE IF NOT EXISTS filings (
    accession TEXT PRIMARY KEY,
    cik TEXT NOT NULL,
    form TEXT NOT NULL,
    filed_at TEXT NOT NULL,
    report_date TEXT NOT NULL DEFAULT '',
    primary_document TEXT NOT NULL DEFAULT '',
    document_url TEXT NOT NULL DEFAULT '',
    FOREIGN KEY (cik) REFERENCES companies (cik)
);

CREATE INDEX IF NOT EXISTS idx_filings_cik ON filings (cik);
CREATE INDEX IF NOT EXISTS idx_filings_form ON filings (form);

CREATE TABLE IF NOT EXISTS xbrl_facts (
    cik TEXT NOT NULL,
    taxonomy TEXT NOT NULL,
    concept TEXT NOT NULL,
    unit TEXT NOT NULL,
    period_start TEXT NOT NULL DEFAULT '',
    period_end TEXT NOT NULL DEFAULT '',
    fy TEXT NOT NULL DEFAULT '',
    fp TEXT NOT NULL DEFAULT '',
    form TEXT NOT NULL DEFAULT '',
    accession TEXT NOT NULL DEFAULT '',
    value TEXT NOT NULL DEFAULT '',
    filed TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (cik, taxonomy, concept, unit, period_start, period_end, accession)
);

CREATE INDEX IF NOT EXISTS idx_facts_concept ON xbrl_facts (cik, concept);
"""


def default_db_path() -> Path:
    raw = os.environ.get("EDGAR_DB_PATH")
    if raw:
        return Path(raw).expanduser()
    return Path.cwd() / "edgar.db"


class Database:
    def __init__(self, path: str | Path | None = None) -> None:
        self.path = Path(path) if path else default_db_path()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        self.conn.executescript(SCHEMA)

    def close(self) -> None:
        self.conn.close()

    def upsert_company(self, company: CompanyRef) -> None:
        self.conn.execute(
            """
            INSERT INTO companies (cik, ticker, name)
            VALUES (?, ?, ?)
            ON CONFLICT(cik) DO UPDATE SET ticker = excluded.ticker, name = excluded.name
            """,
            (company.cik, company.ticker, company.name),
        )
        self.conn.commit()

    def upsert_filings(self, filings: Iterable[Filing]) -> int:
        rows = [
            (
                f.accession,
                f.cik,
                f.form,
                f.filed_at,
                f.report_date,
                f.primary_document,
                f.document_url,
            )
            for f in filings
        ]
        self.conn.executemany(
            """
            INSERT INTO filings (
                accession, cik, form, filed_at, report_date, primary_document, document_url
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(accession) DO UPDATE SET
                cik = excluded.cik,
                form = excluded.form,
                filed_at = excluded.filed_at,
                report_date = excluded.report_date,
                primary_document = excluded.primary_document,
                document_url = excluded.document_url
            """,
            rows,
        )
        self.conn.commit()
        return len(rows)

    def upsert_facts(self, facts: Iterable[XbrlFact]) -> int:
        rows = [
            (
                f.cik,
                f.taxonomy,
                f.concept,
                f.unit,
                f.period_start,
                f.period_end,
                f.fy,
                f.fp,
                f.form,
                f.accession,
                f.value,
                f.filed,
            )
            for f in facts
        ]
        self.conn.executemany(
            """
            INSERT INTO xbrl_facts (
                cik, taxonomy, concept, unit, period_start, period_end,
                fy, fp, form, accession, value, filed
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(cik, taxonomy, concept, unit, period_start, period_end, accession)
            DO UPDATE SET
                fy = excluded.fy,
                fp = excluded.fp,
                form = excluded.form,
                value = excluded.value,
                filed = excluded.filed
            """,
            rows,
        )
        self.conn.commit()
        return len(rows)

    def _company_from_row(self, row: sqlite3.Row | None) -> CompanyRef | None:
        if not row:
            return None
        return CompanyRef(cik=row["cik"], ticker=row["ticker"], name=row["name"])

    def company_by_ticker(self, ticker: str) -> CompanyRef | None:
        row = self.conn.execute(
            "SELECT cik, ticker, name FROM companies WHERE ticker = ? COLLATE NOCASE",
            (ticker.upper().strip(),),
        ).fetchone()
        return self._company_from_row(row)

    def company_by_cik(self, cik: str) -> CompanyRef | None:
        row = self.conn.execute(
            "SELECT cik, ticker, name FROM companies WHERE cik = ?",
            (cik,),
        ).fetchone()
        return self._company_from_row(row)

    def search_companies(self, query: str, limit: int = 25) -> list[CompanyRef]:
        needle = query.strip()
        if not needle:
            return []
        like = f"%{needle}%"
        exact = needle.upper()
        prefix = f"{needle}%"
        rows = self.conn.execute(
            """
            SELECT cik, ticker, name
            FROM companies
            WHERE ticker LIKE ? COLLATE NOCASE
               OR name LIKE ? COLLATE NOCASE
            ORDER BY
                CASE
                    WHEN ticker = ? COLLATE NOCASE THEN 0
                    WHEN ticker LIKE ? COLLATE NOCASE THEN 1
                    WHEN name LIKE ? COLLATE NOCASE THEN 2
                    ELSE 3
                END,
                name
            LIMIT ?
            """,
            (like, like, exact, prefix, prefix, limit),
        )
        return [CompanyRef(cik=row["cik"], ticker=row["ticker"], name=row["name"]) for row in rows]

    def stats(self) -> dict[str, str | int]:
        companies = self.conn.execute("SELECT COUNT(*) FROM companies").fetchone()[0]
        filings = self.conn.execute("SELECT COUNT(*) FROM filings").fetchone()[0]
        facts = self.conn.execute("SELECT COUNT(*) FROM xbrl_facts").fetchone()[0]
        latest = self.conn.execute("SELECT MAX(filed_at) FROM filings").fetchone()[0] or ""
        return {
            "companies": int(companies),
            "filings": int(filings),
            "facts": int(facts),
            "latest_filed": str(latest),
        }

    def recent_filings(self, limit: int = 50) -> list[sqlite3.Row]:
        return list(
            self.conn.execute(
                """
                SELECT f.accession, f.cik, f.form, f.filed_at, f.report_date,
                       f.primary_document, f.document_url, c.ticker, c.name
                FROM filings f
                JOIN companies c ON c.cik = f.cik
                ORDER BY f.filed_at DESC, f.accession DESC
                LIMIT ?
                """,
                (limit,),
            )
        )

    def list_filings(self, cik: str, limit: int = 25) -> list[sqlite3.Row]:
        return list(
            self.conn.execute(
                """
                SELECT f.accession, f.cik, f.form, f.filed_at, f.report_date,
                       f.primary_document, f.document_url, c.ticker, c.name
                FROM filings f
                JOIN companies c ON c.cik = f.cik
                WHERE f.cik = ?
                ORDER BY f.filed_at DESC, f.accession DESC
                LIMIT ?
                """,
                (cik, limit),
            )
        )

    def query_facts(
        self,
        cik: str,
        concept: str | None = None,
        limit: int = 25,
    ) -> list[sqlite3.Row]:
        if concept:
            return list(
                self.conn.execute(
                    """
                    SELECT cik, taxonomy, concept, unit, period_start, period_end,
                           fy, fp, form, accession, value, filed
                    FROM xbrl_facts
                    WHERE cik = ? AND concept = ?
                    ORDER BY period_end DESC, filed DESC
                    LIMIT ?
                    """,
                    (cik, concept, limit),
                )
            )
        return list(
            self.conn.execute(
                """
                SELECT cik, taxonomy, concept, unit, period_start, period_end,
                       fy, fp, form, accession, value, filed
                FROM xbrl_facts
                WHERE cik = ?
                ORDER BY period_end DESC, filed DESC
                LIMIT ?
                """,
                (cik, limit),
            )
        )

    def query_facts_by_concepts(
        self,
        cik: str,
        concepts: Sequence[str],
        limit: int = 20000,
    ) -> list[sqlite3.Row]:
        names = [name for name in concepts if name]
        if not names:
            return []
        placeholders = ",".join("?" * len(names))
        return list(
            self.conn.execute(
                f"""
                SELECT cik, taxonomy, concept, unit, period_start, period_end,
                       fy, fp, form, accession, value, filed
                FROM xbrl_facts
                WHERE cik = ? AND concept IN ({placeholders})
                ORDER BY period_end DESC, filed DESC
                LIMIT ?
                """,
                (cik, *names, limit),
            )
        )

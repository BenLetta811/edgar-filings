"""SQLite storage for companies, filings, and XBRL facts."""

from __future__ import annotations

import os
import sqlite3
from collections.abc import Iterable, Sequence
from datetime import date
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

CREATE TABLE IF NOT EXISTS stock_quotes (
    ticker TEXT NOT NULL,
    name TEXT NOT NULL DEFAULT '',
    price REAL,
    change_amt REAL,
    change_pct REAL,
    volume_m REAL,
    avg_vol_3m_m REAL,
    market_cap_b REAL,
    pe_ratio REAL,
    wk52_change_pct REAL,
    wk52_low REAL,
    wk52_high REAL,
    as_of TEXT NOT NULL,
    PRIMARY KEY (ticker, as_of)
);

CREATE INDEX IF NOT EXISTS idx_quotes_ticker ON stock_quotes (ticker);
CREATE INDEX IF NOT EXISTS idx_quotes_as_of ON stock_quotes (as_of);

CREATE TABLE IF NOT EXISTS stock_ytd (
    ticker TEXT NOT NULL,
    year INTEGER NOT NULL,
    start_date TEXT NOT NULL,
    start_price REAL NOT NULL,
    last_date TEXT NOT NULL,
    last_price REAL NOT NULL,
    ytd_return_pct REAL,
    PRIMARY KEY (ticker, year)
);
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

    def recent_filings(self, limit: int = 50, form: str | None = None) -> list[sqlite3.Row]:
        sql = """
            SELECT f.accession, f.cik, f.form, f.filed_at, f.report_date,
                   f.primary_document, f.document_url, c.ticker, c.name
            FROM filings f
            JOIN companies c ON c.cik = f.cik
        """
        params: list[object] = []
        if form:
            sql += " WHERE f.form = ? COLLATE NOCASE"
            params.append(form.strip())
        sql += " ORDER BY f.filed_at DESC, f.accession DESC LIMIT ?"
        params.append(limit)
        return list(self.conn.execute(sql, params))

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

    def upsert_quotes(self, rows: Iterable[tuple]) -> int:
        payload = list(rows)
        self.conn.executemany(
            """
            INSERT INTO stock_quotes (
                ticker, name, price, change_amt, change_pct, volume_m, avg_vol_3m_m,
                market_cap_b, pe_ratio, wk52_change_pct, wk52_low, wk52_high, as_of
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(ticker, as_of) DO UPDATE SET
                name = excluded.name,
                price = excluded.price,
                change_amt = excluded.change_amt,
                change_pct = excluded.change_pct,
                volume_m = excluded.volume_m,
                avg_vol_3m_m = excluded.avg_vol_3m_m,
                market_cap_b = excluded.market_cap_b,
                pe_ratio = excluded.pe_ratio,
                wk52_change_pct = excluded.wk52_change_pct,
                wk52_low = excluded.wk52_low,
                wk52_high = excluded.wk52_high
            """,
            payload,
        )
        self.conn.commit()
        return len(payload)

    def latest_quote(self, ticker: str, year: int | None = None) -> sqlite3.Row | None:
        year = year or date.today().year
        return self.conn.execute(
            """
            SELECT q.ticker, q.name, q.price, q.change_amt, q.change_pct, q.volume_m,
                   q.avg_vol_3m_m, q.market_cap_b, q.pe_ratio, q.wk52_change_pct,
                   q.wk52_low, q.wk52_high, q.as_of,
                   y.start_date AS ytd_start_date,
                   y.start_price AS ytd_start_price,
                   y.ytd_return_pct AS ytd_return_pct
            FROM stock_quotes q
            LEFT JOIN stock_ytd y ON y.ticker = q.ticker AND y.year = ?
            WHERE q.ticker = ? COLLATE NOCASE
            ORDER BY q.as_of DESC
            LIMIT 1
            """,
            (year, ticker.upper().strip()),
        ).fetchone()

    def quote_history(self, ticker: str, limit: int = 90) -> list[sqlite3.Row]:
        return list(
            self.conn.execute(
                """
                SELECT ticker, name, price, change_amt, change_pct, volume_m, avg_vol_3m_m,
                       market_cap_b, pe_ratio, wk52_change_pct, wk52_low, wk52_high, as_of
                FROM stock_quotes
                WHERE ticker = ? COLLATE NOCASE
                ORDER BY as_of DESC
                LIMIT ?
                """,
                (ticker.upper().strip(), limit),
            )
        )

    def upsert_ytd(self, rows: Iterable[tuple]) -> int:
        payload = list(rows)
        self.conn.executemany(
            """
            INSERT INTO stock_ytd (
                ticker, year, start_date, start_price, last_date, last_price, ytd_return_pct
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(ticker, year) DO UPDATE SET
                start_date = excluded.start_date,
                start_price = excluded.start_price,
                last_date = excluded.last_date,
                last_price = excluded.last_price,
                ytd_return_pct = excluded.ytd_return_pct
            """,
            payload,
        )
        self.conn.commit()
        return len(payload)

    def latest_quotes(self, limit: int = 200, year: int | None = None) -> list[sqlite3.Row]:
        year = year or date.today().year
        return list(
            self.conn.execute(
                """
                SELECT q.ticker, q.name, q.price, q.change_amt, q.change_pct, q.volume_m,
                       q.avg_vol_3m_m, q.market_cap_b, q.pe_ratio, q.wk52_change_pct,
                       q.wk52_low, q.wk52_high, q.as_of,
                       y.start_date AS ytd_start_date,
                       y.start_price AS ytd_start_price,
                       y.ytd_return_pct AS ytd_return_pct
                FROM stock_quotes q
                JOIN (
                    SELECT ticker, MAX(as_of) AS as_of
                    FROM stock_quotes
                    GROUP BY ticker
                ) latest ON latest.ticker = q.ticker AND latest.as_of = q.as_of
                LEFT JOIN stock_ytd y ON y.ticker = q.ticker AND y.year = ?
                ORDER BY
                    CASE WHEN y.ytd_return_pct IS NULL THEN 1 ELSE 0 END,
                    y.ytd_return_pct DESC,
                    q.ticker
                LIMIT ?
                """,
                (year, limit),
            )
        )

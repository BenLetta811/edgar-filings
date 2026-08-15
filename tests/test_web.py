from pathlib import Path

from edgar_filings.facts import XbrlFact
from edgar_filings.db import Database
from edgar_filings.submissions import Filing
from edgar_filings.tickers import CompanyRef
from edgar_filings.web import create_app


def _seed(path: Path) -> None:
    db = Database(path)
    db.upsert_company(CompanyRef(cik="0000320193", ticker="AAPL", name="Apple Inc."))
    db.upsert_filings(
        [
            Filing(
                accession="0000320193-24-000123",
                cik="0000320193",
                form="10-K",
                filed_at="2024-11-01",
                report_date="2024-09-28",
                primary_document="aapl.htm",
                document_url="https://www.sec.gov/Archives/example.htm",
            )
        ]
    )
    db.upsert_facts(
        [
            XbrlFact(
                cik="0000320193",
                taxonomy="us-gaap",
                concept="NetIncomeLoss",
                unit="USD",
                period_start="2023-10-01",
                period_end="2024-09-28",
                fy="2024",
                fp="FY",
                form="10-K",
                accession="0000320193-24-000123",
                value="93736000000",
                filed="2024-11-01",
            )
        ]
    )
    db.close()


def test_web_search_and_company(tmp_path: Path):
    db_path = tmp_path / "ui.db"
    _seed(db_path)
    client = create_app(db_path).test_client()

    home = client.get("/")
    assert home.status_code == 200
    assert b"Apple Inc." in home.data

    search = client.get("/?q=apple")
    assert search.status_code == 200
    assert b"AAPL" in search.data

    page = client.get("/company/0000320193")
    assert page.status_code == 200
    assert b"Net income" in page.data
    assert b"93,736" in page.data
    assert b"Income statement" in page.data

    missing = client.get("/company/0000000000")
    assert missing.status_code == 404

    home = client.get("/")
    assert b"Download latest data" in home.data
    assert b"Load historical data" in home.data

    bad = client.post("/ingest/history", json={"start": "nope", "end": "2024-01-01"})
    assert bad.status_code == 400

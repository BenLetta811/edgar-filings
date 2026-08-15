from pathlib import Path

from edgar_filings.db import Database
from edgar_filings.facts import XbrlFact
from edgar_filings.submissions import Filing
from edgar_filings.tickers import CompanyRef


def test_db_upsert_and_query(tmp_path: Path):
    db = Database(tmp_path / "test.db")
    company = CompanyRef(cik="0000320193", ticker="AAPL", name="Apple Inc.")
    db.upsert_company(company)
    db.upsert_filings(
        [
            Filing(
                accession="0000320193-24-000123",
                cik=company.cik,
                form="10-K",
                filed_at="2024-11-01",
                report_date="2024-09-28",
                primary_document="aapl.htm",
                document_url="https://www.sec.gov/Archives/edgar/data/320193/000032019324000123/aapl.htm",
            )
        ]
    )
    db.upsert_facts(
        [
            XbrlFact(
                cik=company.cik,
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
    found = db.company_by_ticker("aapl")
    assert found is not None and found.cik == company.cik
    filings = db.list_filings(company.cik)
    assert filings[0]["form"] == "10-K"
    facts = db.query_facts(company.cik, concept="NetIncomeLoss")
    assert facts[0]["value"] == "93736000000"
    matches = db.search_companies("apple")
    assert len(matches) == 1 and matches[0].ticker == "AAPL"
    assert db.search_companies("AAPL")[0].cik == company.cik
    assert db.company_by_cik(company.cik) is not None
    recent = db.recent_filings()
    assert recent[0]["ticker"] == "AAPL"
    db.close()

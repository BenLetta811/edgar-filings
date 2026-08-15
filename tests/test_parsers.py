from edgar_filings.client import (
    EdgarClient,
    accession_no_dashes,
    document_url,
    pad_cik,
)
from edgar_filings.daily_index import parse_master_idx
from edgar_filings.facts import parse_company_facts
from edgar_filings.submissions import parse_submissions
from edgar_filings.tickers import find_by_ticker, parse_company_tickers


def test_pad_cik():
    assert pad_cik(320193) == "0000320193"
    assert pad_cik("320193") == "0000320193"
    assert pad_cik("0000320193") == "0000320193"


def test_document_url():
    url = document_url("0000320193", "0000320193-24-000123", "aapl-20240928.htm")
    assert url == (
        "https://www.sec.gov/Archives/edgar/data/320193/"
        "000032019324000123/aapl-20240928.htm"
    )
    assert accession_no_dashes("0000320193-24-000123") == "000032019324000123"


def test_parse_company_tickers():
    payload = {
        "0": {"cik_str": 320193, "ticker": "AAPL", "title": "Apple Inc."},
        "1": {"cik_str": 789019, "ticker": "MSFT", "title": "MICROSOFT CORP"},
    }
    companies = parse_company_tickers(payload)
    apple = find_by_ticker(companies, "aapl")
    assert apple.cik == "0000320193"
    assert apple.name == "Apple Inc."


def test_parse_submissions_filters_forms():
    payload = {
        "cik": "320193",
        "filings": {
            "recent": {
                "accessionNumber": ["0000320193-24-000123", "0000320193-24-000001"],
                "form": ["10-K", "8-K"],
                "filingDate": ["2024-11-01", "2024-01-02"],
                "reportDate": ["2024-09-28", "2024-01-01"],
                "primaryDocument": ["aapl-20240928.htm", "ex99.htm"],
            }
        },
    }
    filings = parse_submissions(payload, forms=["10-K"])
    assert len(filings) == 1
    assert filings[0].form == "10-K"
    assert filings[0].cik == "0000320193"
    assert filings[0].document_url.endswith("/aapl-20240928.htm")


def test_parse_master_idx():
    text = """
Daily Index of EDGAR Documents
CIK|Company Name|Form Type|Date Filed|Filename
--------------------------------------------------------------------------------
320193|Apple Inc.|10-K|20241101|edgar/data/320193/0000320193-24-000123.txt
789019|MICROSOFT CORP|8-K|20241101|edgar/data/789019/0000950170-24-000001.txt
320193|Apple Inc.|4|20241101|edgar/data/320193/0000320193-24-000124.txt
"""
    filings, names = parse_master_idx(text, forms=["10-K", "8-K"])
    assert len(filings) == 2
    assert names["0000320193"] == "Apple Inc."
    apple = filings[0]
    assert apple.accession == "0000320193-24-000123"
    assert apple.filed_at == "2024-11-01"
    assert apple.document_url.endswith("/0000320193-24-000123.txt")
    assert filings[1].form == "8-K"


def test_parse_company_facts():
    payload = {
        "cik": 320193,
        "facts": {
            "us-gaap": {
                "NetIncomeLoss": {
                    "units": {
                        "USD": [
                            {
                                "start": "2023-10-01",
                                "end": "2024-09-28",
                                "val": 93736000000,
                                "accn": "0000320193-24-000123",
                                "fy": 2024,
                                "fp": "FY",
                                "form": "10-K",
                                "filed": "2024-11-01",
                            }
                        ]
                    }
                }
            }
        },
    }
    facts = parse_company_facts(payload, concept="NetIncomeLoss")
    assert len(facts) == 1
    assert facts[0].cik == "0000320193"
    assert facts[0].taxonomy == "us-gaap"
    assert facts[0].value == "93736000000"
    assert facts[0].period_start == "2023-10-01"


def test_client_retries_403(monkeypatch):
    calls = {"n": 0}

    class FakeResponse:
        def __init__(self, status_code, payload=None):
            self.status_code = status_code
            self._payload = payload or {}

        def json(self):
            return self._payload

        def raise_for_status(self):
            if self.status_code >= 400:
                raise RuntimeError(self.status_code)

    class FakeSession:
        def get(self, url, headers=None, timeout=None):
            calls["n"] += 1
            assert headers["User-Agent"].startswith("edgar-filings")
            if calls["n"] == 1:
                return FakeResponse(403)
            return FakeResponse(200, {"ok": True})

    monkeypatch.setattr("edgar_filings.client.time.sleep", lambda *_: None)
    client = EdgarClient(
        user_agent="edgar-filings Test tester@example.com",
        rate_limit=10,
        session=FakeSession(),
        max_retries=3,
    )
    client.rate_limiter.min_interval = 0
    assert client.get_json("https://data.sec.gov/example.json") == {"ok": True}
    assert calls["n"] == 2

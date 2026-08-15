from datetime import date

from edgar_filings.daily_index import parse_master_idx
from edgar_filings.db import Database
from edgar_filings.ingest import IngestError, ingest_latest, ingest_range


MASTER = """
CIK|Company Name|Form Type|Date Filed|Filename
--------------------------------------------------------------------------------
320193|Apple Inc.|10-K|20241101|edgar/data/320193/0000320193-24-000123.txt
"""

TICKERS = {"0": {"cik_str": 320193, "ticker": "AAPL", "title": "Apple Inc."}}


class FakeClient:
    def __init__(self, days=None):
        self.days = set(days or [])

    def company_tickers(self):
        return TICKERS

    def daily_master(self, day):
        if day in self.days:
            return MASTER
        return None

    def company_facts(self, cik):
        return {
            "cik": cik,
            "facts": {
                "us-gaap": {
                    "NetIncomeLoss": {
                        "units": {
                            "USD": [
                                {
                                    "start": "2023-10-01",
                                    "end": "2024-09-28",
                                    "val": 1,
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


def test_parse_master_still_used():
    filings, names = parse_master_idx(MASTER, forms=["10-K"])
    assert len(filings) == 1
    assert names["0000320193"] == "Apple Inc."


def test_ingest_latest_and_range(tmp_path):
    db = Database(tmp_path / "i.db")
    client = FakeClient(days={date(2024, 11, 1), date(2024, 11, 4)})
    latest = ingest_latest(db, as_of=date(2024, 11, 1), client=client)
    assert latest.filings == 1
    assert latest.days == ["2024-11-01"]
    ranged = ingest_range(db, date(2024, 11, 1), date(2024, 11, 4), client=client)
    assert "2024-11-04" in ranged.days
    db.close()


def test_ingest_range_rejects_long_span(tmp_path):
    db = Database(tmp_path / "i.db")
    try:
        ingest_range(db, date(2024, 1, 1), date(2024, 12, 31), client=FakeClient())
        assert False, "expected IngestError"
    except IngestError:
        pass
    db.close()

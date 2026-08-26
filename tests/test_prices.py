from pathlib import Path

from openpyxl import Workbook

from edgar_filings.db import Database
from edgar_filings.prices import import_stock_prices, parse_stock_prices_xlsx


def _write_sample(path: Path) -> None:
    wb = Workbook()
    ws = wb.active
    ws.title = "Stock Prices"
    ws.append(
        [
            "Ticker",
            "Name",
            "Price",
            "Change",
            "Change %",
            "Volume (M)",
            "Avg Vol (3M) (M)",
            "Market Cap ($B)",
            "P/E Ratio (TTM)",
            "52 Wk Change %",
            "52 Wk Low",
            "52 Wk High",
        ]
    )
    ws.append(["NVDA", "NVIDIA Corp", 120.5, 1.25, 1.05, 10.2, 12.0, 3000.0, 40.0, 80.0, 90.0, 150.0])
    wb.save(path)


def test_parse_and_import_quotes(tmp_path: Path):
    xlsx = tmp_path / "quotes.xlsx"
    _write_sample(xlsx)
    rows = parse_stock_prices_xlsx(xlsx, as_of="2026-08-26")
    assert len(rows) == 1
    assert rows[0][0] == "NVDA"
    assert rows[0][2] == 120.5
    assert rows[0][-1] == "2026-08-26"

    db = Database(tmp_path / "q.db")
    count, snapshot = import_stock_prices(db, xlsx, as_of="2026-08-26")
    assert count == 1
    assert snapshot == "2026-08-26"
    quote = db.latest_quote("nvda")
    assert quote is not None
    assert quote["price"] == 120.5
    assert db.latest_quotes()[0]["ticker"] == "NVDA"
    db.close()


def test_fetch_live_quote(monkeypatch):
    from edgar_filings.prices import fetch_live_quote

    class FakeResponse:
        status_code = 200

        def json(self):
            return {
                "chart": {
                    "result": [
                        {
                            "meta": {
                                "symbol": "NVDA",
                                "longName": "NVIDIA Corporation",
                                "regularMarketPrice": 209.66,
                                "chartPreviousClose": 217.56,
                                "regularMarketVolume": 145070184,
                                "fiftyTwoWeekLow": 164.07,
                                "fiftyTwoWeekHigh": 236.54,
                            }
                        }
                    ]
                }
            }

    class FakeSession:
        def get(self, url, headers=None, timeout=None):
            assert "NVDA" in url
            return FakeResponse()

    row = fetch_live_quote("NVDA", session=FakeSession())
    assert row is not None
    assert row[0] == "NVDA"
    assert row[2] == 209.66
    assert round(row[3], 2) == -7.9


def test_fetch_ytd(monkeypatch):
    from datetime import date as real_date
    from datetime import datetime, timezone

    from edgar_filings.prices import fetch_ytd

    class FakeDate(real_date):
        @classmethod
        def today(cls):
            return cls(2026, 8, 26)

    monkeypatch.setattr("edgar_filings.prices.date", FakeDate)

    start = int(datetime(2026, 1, 2, 21, 0, tzinfo=timezone.utc).timestamp())
    last = int(datetime(2026, 8, 25, 20, 0, tzinfo=timezone.utc).timestamp())

    class FakeResponse:
        status_code = 200

        def json(self):
            return {
                "chart": {
                    "result": [
                        {
                            "meta": {"longName": "NVIDIA Corporation"},
                            "timestamp": [start, last],
                            "indicators": {"quote": [{"close": [100.0, 125.0]}]},
                        }
                    ]
                }
            }

    class FakeSession:
        def get(self, url, headers=None, timeout=None):
            assert "range=ytd" in url
            return FakeResponse()

    data = fetch_ytd("NVDA", session=FakeSession())
    assert data is not None
    assert data["start_date"] == "2026-01-02"
    assert data["start_price"] == 100.0
    assert data["last_price"] == 125.0
    assert data["ytd_return_pct"] == 25.0

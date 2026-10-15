from edgar_filings.statements import build_statements, format_amount


def test_format_amount_parens_and_scale():
    assert format_amount(None) == "—"
    assert format_amount(1234.5, per_share=True) == "1,234.50"
    assert format_amount(-12.3, per_share=True) == "(12.30)"
    assert format_amount(1_250_000_000, scale=1_000_000) == "1,250"
    assert format_amount(-50_000, scale=1_000) == "(50)"


def test_build_statements_groups_periods():
    rows = [
        {
            "concept": "Revenues",
            "unit": "USD",
            "period_start": "2023-10-01",
            "period_end": "2024-09-28",
            "fy": "2024",
            "fp": "FY",
            "form": "10-K",
            "value": "391000000000",
            "filed": "2024-11-01",
        },
        {
            "concept": "NetIncomeLoss",
            "unit": "USD",
            "period_start": "2023-10-01",
            "period_end": "2024-09-28",
            "fy": "2024",
            "fp": "FY",
            "form": "10-K",
            "value": "93736000000",
            "filed": "2024-11-01",
        },
        {
            "concept": "Assets",
            "unit": "USD",
            "period_start": "",
            "period_end": "2024-09-28",
            "fy": "2024",
            "fp": "FY",
            "form": "10-K",
            "value": "364980000000",
            "filed": "2024-11-01",
        },
        {
            "concept": "EarningsPerShareDiluted",
            "unit": "USD/shares",
            "period_start": "2023-10-01",
            "period_end": "2024-09-28",
            "fy": "2024",
            "fp": "FY",
            "form": "10-K",
            "value": "6.08",
            "filed": "2024-11-01",
        },
        {
            "concept": "Liabilities",
            "unit": "USD",
            "period_start": "",
            "period_end": "2024-09-28",
            "fy": "2024",
            "fp": "FY",
            "form": "10-K",
            "value": "200000000000",
            "filed": "2024-11-01",
        },
        {
            "concept": "StockholdersEquity",
            "unit": "USD",
            "period_start": "",
            "period_end": "2024-09-28",
            "fy": "2024",
            "fp": "FY",
            "form": "10-K",
            "value": "164980000000",
            "filed": "2024-11-01",
        },
        {
            "concept": "LongTermDebt",
            "unit": "USD",
            "period_start": "",
            "period_end": "2024-09-28",
            "fy": "2024",
            "fp": "FY",
            "form": "10-K",
            "value": "80000000000",
            "filed": "2024-11-01",
        },
        {
            "concept": "DebtCurrent",
            "unit": "USD",
            "period_start": "",
            "period_end": "2024-09-28",
            "fy": "2024",
            "fp": "FY",
            "form": "10-K",
            "value": "20000000000",
            "filed": "2024-11-01",
        },
    ]
    view = build_statements(rows)
    assert view["scale_label"] == "USD millions"
    titles = [section["title"] for section in view["sections"]]
    assert titles == ["Income statement", "Balance sheet", "Ratios"]
    income = view["sections"][0]["rows"]
    labels = [row["label"] for row in income]
    assert "Revenue" in labels
    assert "Net income" in labels
    end = view["periods"][0]["end"]
    net = next(row for row in income if row["label"] == "Net income")
    assert net["amounts"][end] == "93,736"
    eps = next(row for row in income if row["label"] == "EPS (diluted)")
    assert eps["amounts"][end] == "6.08"
    ratios = next(section["rows"] for section in view["sections"] if section["title"] == "Ratios")
    by_label = {row["label"]: row for row in ratios}
    assert by_label["EPS (diluted)"]["amounts"][end] == "6.08"
    assert by_label["Debt / equity"]["amounts"][end] == "0.61x"
    assert by_label["Liabilities / equity"]["amounts"][end] == "1.21x"
    assert by_label["Net margin"]["amounts"][end] == "24.0%"


def test_computed_eps_when_share_count_present():
    rows = [
        {
            "concept": "NetIncomeLoss",
            "unit": "USD",
            "period_start": "2023-01-01",
            "period_end": "2023-12-31",
            "fy": "2023",
            "fp": "FY",
            "form": "10-K",
            "value": "1000",
            "filed": "2024-02-01",
        },
        {
            "concept": "WeightedAverageNumberOfDilutedSharesOutstanding",
            "unit": "shares",
            "period_start": "2023-01-01",
            "period_end": "2023-12-31",
            "fy": "2023",
            "fp": "FY",
            "form": "10-K",
            "value": "200",
            "filed": "2024-02-01",
        },
    ]
    view = build_statements(rows)
    end = view["periods"][0]["end"]
    ratios = next(section["rows"] for section in view["sections"] if section["title"] == "Ratios")
    diluted = next(row for row in ratios if row["label"] == "EPS (diluted)")
    assert diluted["amounts"][end] == "5.00"

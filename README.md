# edgar-filings

CLI that pulls SEC EDGAR filing metadata, primary-document links, and XBRL company facts into a local SQLite database.

This is a backend/CLI tool. Do not call these endpoints from a browser (CORS is not supported).

Official docs:

- [EDGAR Application Developer FAQ](https://www.sec.gov/os/webmaster-faq#developers)
- [data.sec.gov APIs](https://www.sec.gov/search-filings/edgar-application-programming-interfaces)
- Tickers: `https://www.sec.gov/files/company_tickers.json`
- Submissions: `https://data.sec.gov/submissions/CIK##########.json`
- Company facts: `https://data.sec.gov/api/xbrl/companyfacts/CIK##########.json`

## SEC User-Agent (required)

The SEC does not use API keys, but every request must send a User-Agent that identifies a real person (name + email). A placeholder will get you blocked with HTTP 403.

```bash
export EDGAR_USER_AGENT="edgar-filings Your Name you@email.com"
```

Copy `.env.example` and replace `YourName` / `you@email.com`. The client also honors:

| Variable | Default | Notes |
| --- | --- | --- |
| `EDGAR_USER_AGENT` | `edgar-filings YourName you@email.com` | Must be a real name+email for live SEC access |
| `EDGAR_DB_PATH` | `./edgar.db` | SQLite file |
| `EDGAR_RATE_LIMIT` | `6` | Requests per second, capped at 10 |

The client throttles to at most 10 req/s (default 6) and retries HTTP 403/429/5xx with backoff. CIKs are stored as 10-digit zero-padded strings.

## Install

Python 3.10+.

```bash
cd /Users/benjaminletta/Projects/edgar-filings
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

## Usage

```bash
export EDGAR_USER_AGENT="edgar-filings Your Name you@email.com"

edgar-filings ingest AAPL --forms 10-K,10-Q,8-K
edgar-filings filings AAPL
edgar-filings facts AAPL --concept NetIncomeLoss
```

Skip XBRL on ingest:

```bash
edgar-filings ingest AAPL --skip-facts
```

Pull the latest published **daily master index** (10-K / 10-Q / 8-K by default) into SQLite. On weekends this walks back to the last trading day. XBRL is fetched for up to 40 companies that filed a 10-K or 10-Q that day.

```bash
edgar-filings ingest-latest
edgar-filings ingest-latest --date 2026-08-14 --skip-facts
edgar-filings ingest-range 2026-08-01 2026-08-14
```

Use a custom database path:

```bash
edgar-filings --db /tmp/edgar.db ingest MSFT
```

## Web UI

Browse stored filings by ticker or company name (local SQLite only; the browser does not call SEC.gov):

```bash
edgar-filings serve
```

Then open http://127.0.0.1:8000. **Recent updates** (`/updates`) lists stored filings newest first, grouped by filing date. **Prices** (`/prices`) shows the latest Excel quote snapshot.

Import Tableau/Excel quotes (`Ticker`, `Price`, 52-week range, etc.):

```bash
edgar-filings import-prices ~/Downloads/stock_prices_tableau.xlsx
```

The workbook is a point-in-time snapshot, not daily OHLC. Re-importing with a new `--as-of` date appends history.

## What is stored

- **companies**: CIK, ticker, name
- **filings**: accession, form, dates, primary document, archive URL  
  `https://www.sec.gov/Archives/edgar/data/{cik_no_leading_zeros}/{accession_no_dashes}/{primaryDocument}`
- **xbrl_facts**: flattened companyfacts (taxonomy, concept, unit, period, value, accession)

v1 does not download full HTML/PDF filing bodies or ingest nightly bulk ZIPs.

## Tests

```bash
pytest
```

Tests mock HTTP. They do not call the SEC.

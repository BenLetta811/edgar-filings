"""Command-line interface for ingesting and querying EDGAR data."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from datetime import date, datetime

from edgar_filings.client import EdgarClient
from edgar_filings.db import Database
from edgar_filings.ingest import ingest_latest, ingest_range
from edgar_filings.submissions import parse_submissions
from edgar_filings.facts import parse_company_facts
from edgar_filings.tickers import CompanyRef, find_by_ticker, parse_company_tickers


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="edgar-filings",
        description="Ingest and query SEC EDGAR filing metadata and XBRL company facts.",
    )
    parser.add_argument(
        "--db",
        default=None,
        help="SQLite path (default: EDGAR_DB_PATH or ./edgar.db)",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    ingest = sub.add_parser("ingest", help="Fetch filings and facts for a ticker")
    ingest.add_argument("ticker", help="Stock ticker, e.g. AAPL")
    ingest.add_argument(
        "--forms",
        default="10-K,10-Q,8-K",
        help="Comma-separated form types (default: 10-K,10-Q,8-K)",
    )
    ingest.add_argument(
        "--skip-facts",
        action="store_true",
        help="Skip companyfacts XBRL download",
    )

    latest = sub.add_parser(
        "ingest-latest",
        help="Fetch the latest published daily EDGAR master index into SQLite",
    )
    latest.add_argument(
        "--date",
        default=None,
        help="Index date YYYY-MM-DD (default: most recent published day)",
    )
    latest.add_argument(
        "--forms",
        default="10-K,10-Q,8-K",
        help="Comma-separated form types (default: 10-K,10-Q,8-K)",
    )
    latest.add_argument(
        "--skip-facts",
        action="store_true",
        help="Skip companyfacts XBRL download",
    )
    latest.add_argument(
        "--max-fact-companies",
        type=int,
        default=40,
        help="Max unique CIKs to pull XBRL for (10-K/10-Q filers). Default 40.",
    )
    latest.add_argument(
        "--lookback-days",
        type=int,
        default=10,
        help="How many calendar days back to search for a published index",
    )

    history = sub.add_parser(
        "ingest-range",
        help="Fetch daily EDGAR master indexes for a date range into SQLite",
    )
    history.add_argument("start", help="Start date YYYY-MM-DD")
    history.add_argument("end", help="End date YYYY-MM-DD")
    history.add_argument(
        "--forms",
        default="10-K,10-Q,8-K",
        help="Comma-separated form types (default: 10-K,10-Q,8-K)",
    )
    history.add_argument("--skip-facts", action="store_true")
    history.add_argument("--max-fact-companies", type=int, default=25)

    filings = sub.add_parser("filings", help="List stored filings for a ticker")
    filings.add_argument("ticker")
    filings.add_argument("--limit", type=int, default=25)

    facts = sub.add_parser("facts", help="Query stored XBRL facts for a ticker")
    facts.add_argument("ticker")
    facts.add_argument("--concept", default=None, help="e.g. NetIncomeLoss")
    facts.add_argument("--limit", type=int, default=25)

    serve = sub.add_parser("serve", help="Open a local web UI for stored filings")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8000)

    return parser


def resolve_company(db: Database, client: EdgarClient, ticker: str) -> CompanyRef:
    existing = db.company_by_ticker(ticker)
    if existing:
        return existing
    companies = parse_company_tickers(client.company_tickers())
    company = find_by_ticker(companies, ticker)
    db.upsert_company(company)
    return company


def cmd_ingest(args: argparse.Namespace) -> int:
    db = Database(args.db)
    client = EdgarClient()
    company = resolve_company(db, client, args.ticker)
    forms = [part.strip() for part in args.forms.split(",") if part.strip()]
    filings = parse_submissions(client.submissions(company.cik), forms=forms)
    n_filings = db.upsert_filings(filings)
    n_facts = 0
    if not args.skip_facts:
        facts_payload = client.company_facts(company.cik)
        if facts_payload:
            n_facts = db.upsert_facts(parse_company_facts(facts_payload))
    print(
        f"Ingested {company.ticker} (CIK {company.cik}): "
        f"{n_filings} filings, {n_facts} facts -> {db.path}"
    )
    db.close()
    return 0


def _parse_iso_date(value: str) -> date:
    return datetime.strptime(value, "%Y-%m-%d").date()


def cmd_ingest_latest(args: argparse.Namespace) -> int:
    db = Database(args.db)
    forms = [part.strip() for part in args.forms.split(",") if part.strip()]
    try:
        result = ingest_latest(
            db,
            as_of=_parse_iso_date(args.date) if args.date else None,
            lookback_days=args.lookback_days,
            forms=forms,
            skip_facts=args.skip_facts,
            max_fact_companies=args.max_fact_companies,
        )
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        db.close()
        return 1
    print(f"{result.message} -> {db.path}")
    db.close()
    return 0


def cmd_ingest_range(args: argparse.Namespace) -> int:
    db = Database(args.db)
    forms = [part.strip() for part in args.forms.split(",") if part.strip()]
    try:
        result = ingest_range(
            db,
            _parse_iso_date(args.start),
            _parse_iso_date(args.end),
            forms=forms,
            skip_facts=args.skip_facts,
            max_fact_companies=args.max_fact_companies,
        )
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        db.close()
        return 1
    print(f"{result.message} -> {db.path}")
    db.close()
    return 0


def cmd_filings(args: argparse.Namespace) -> int:
    db = Database(args.db)
    company = db.company_by_ticker(args.ticker)
    if not company:
        print(
            f"No company {args.ticker!r} in {db.path}. Run: edgar-filings ingest {args.ticker}",
            file=sys.stderr,
        )
        return 1
    rows = db.list_filings(company.cik, limit=args.limit)
    if not rows:
        print(f"No filings stored for {company.ticker}.")
        return 0
    print(f"{'form':<8} {'filed':<12} {'report':<12} {'accession':<22} document_url")
    for row in rows:
        print(
            f"{row['form']:<8} {row['filed_at']:<12} {row['report_date']:<12} "
            f"{row['accession']:<22} {row['document_url']}"
        )
    db.close()
    return 0


def cmd_facts(args: argparse.Namespace) -> int:
    db = Database(args.db)
    company = db.company_by_ticker(args.ticker)
    if not company:
        print(
            f"No company {args.ticker!r} in {db.path}. Run: edgar-filings ingest {args.ticker}",
            file=sys.stderr,
        )
        return 1
    rows = db.query_facts(company.cik, concept=args.concept, limit=args.limit)
    if not rows:
        hint = f" concept={args.concept}" if args.concept else ""
        print(f"No facts stored for {company.ticker}{hint}.")
        return 0
    print(f"{'concept':<28} {'unit':<8} {'end':<12} {'fy':<6} {'fp':<4} {'form':<8} value")
    for row in rows:
        print(
            f"{row['concept']:<28} {row['unit']:<8} {row['period_end']:<12} "
            f"{row['fy']:<6} {row['fp']:<4} {row['form']:<8} {row['value']}"
        )
    db.close()
    return 0


def cmd_serve(args: argparse.Namespace) -> int:
    from edgar_filings.web import run_server

    db = Database(args.db)
    path = db.path
    db.close()
    print(f"Serving {path} at http://{args.host}:{args.port}")
    run_server(path, host=args.host, port=args.port)
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "ingest":
        return cmd_ingest(args)
    if args.command == "ingest-latest":
        return cmd_ingest_latest(args)
    if args.command == "ingest-range":
        return cmd_ingest_range(args)
    if args.command == "filings":
        return cmd_filings(args)
    if args.command == "facts":
        return cmd_facts(args)
    if args.command == "serve":
        return cmd_serve(args)
    parser.error(f"unknown command {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())

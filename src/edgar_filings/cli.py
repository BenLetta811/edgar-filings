"""Command-line interface for ingesting and querying EDGAR data."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence

from edgar_filings.client import EdgarClient
from edgar_filings.db import Database
from edgar_filings.facts import parse_company_facts
from edgar_filings.submissions import parse_submissions
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

    filings = sub.add_parser("filings", help="List stored filings for a ticker")
    filings.add_argument("ticker")
    filings.add_argument("--limit", type=int, default=25)

    facts = sub.add_parser("facts", help="Query stored XBRL facts for a ticker")
    facts.add_argument("ticker")
    facts.add_argument("--concept", default=None, help="e.g. NetIncomeLoss")
    facts.add_argument("--limit", type=int, default=25)

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
        n_facts = db.upsert_facts(parse_company_facts(client.company_facts(company.cik)))
    print(
        f"Ingested {company.ticker} (CIK {company.cik}): "
        f"{n_filings} filings, {n_facts} facts ? {db.path}"
    )
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


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "ingest":
        return cmd_ingest(args)
    if args.command == "filings":
        return cmd_filings(args)
    if args.command == "facts":
        return cmd_facts(args)
    parser.error(f"unknown command {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())

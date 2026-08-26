"""Local web UI for searching stored EDGAR filings."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from itertools import groupby
from pathlib import Path

from flask import Flask, abort, g, jsonify, render_template, request

from edgar_filings.db import Database, default_db_path
from edgar_filings.ingest import MAX_RANGE_DAYS, ingest_latest, ingest_range
from edgar_filings.jobs import IngestHub
from edgar_filings.statements import build_statements, statement_concepts

PACKAGE_DIR = Path(__file__).resolve().parent


def _parse_iso_date(value: str) -> date:
    return datetime.strptime(value, "%Y-%m-%d").date()


def group_filings_by_date(filings) -> list[dict]:
    groups: list[dict] = []
    for filed_at, rows in groupby(filings, key=lambda row: row["filed_at"]):
        items = list(rows)
        groups.append({"filed_at": filed_at, "count": len(items), "filings": items})
    return groups


def create_app(db_path: str | Path | None = None) -> Flask:
    app = Flask(
        __name__,
        template_folder=str(PACKAGE_DIR / "templates"),
        static_folder=str(PACKAGE_DIR / "static"),
    )
    app.config["EDGAR_DB_PATH"] = str(Path(db_path) if db_path else default_db_path())
    hub = IngestHub()
    app.config["INGEST_HUB"] = hub

    @app.context_processor
    def ingest_defaults():
        today = date.today()
        return {
            "range_end": today.isoformat(),
            "range_start": (today - timedelta(days=7)).isoformat(),
            "max_range_days": MAX_RANGE_DAYS,
            "ingest": hub.snapshot(),
        }

    @app.before_request
    def open_db() -> None:
        g.db = Database(app.config["EDGAR_DB_PATH"])

    @app.teardown_appcontext
    def close_db(_exc: BaseException | None) -> None:
        db = g.pop("db", None)
        if db is not None:
            db.close()

    @app.route("/")
    def index():
        db: Database = g.db
        query = (request.args.get("q") or "").strip()
        stats = db.stats()
        companies = db.search_companies(query) if query else []
        filings = []
        statements = None
        if len(companies) == 1:
            filings = db.list_filings(companies[0].cik, limit=100)
            statements = build_statements(
                db.query_facts_by_concepts(companies[0].cik, statement_concepts())
            )
        elif not query:
            filings = db.recent_filings(limit=80)
        return render_template(
            "index.html",
            query=query,
            stats=stats,
            companies=companies,
            filings=filings,
            statements=statements,
            db_path=db.path.name,
        )

    @app.route("/updates")
    def updates():
        db: Database = g.db
        form = (request.args.get("form") or "").strip()
        filings = db.recent_filings(limit=400, form=form or None)
        return render_template(
            "updates.html",
            query="",
            stats=db.stats(),
            groups=group_filings_by_date(filings),
            form_filter=form,
            db_path=db.path.name,
        )

    @app.route("/prices")
    def prices():
        db: Database = g.db
        return render_template(
            "prices.html",
            query="",
            stats=db.stats(),
            quotes=db.latest_quotes(),
            db_path=db.path.name,
        )

    @app.route("/company/<cik>")
    def company(cik: str):
        db: Database = g.db
        found = db.company_by_cik(cik)
        if not found:
            abort(404)
        filings = db.list_filings(found.cik, limit=200)
        statements = build_statements(
            db.query_facts_by_concepts(found.cik, statement_concepts())
        )
        quote = db.latest_quote(found.ticker) if found.ticker else None
        history = db.quote_history(found.ticker, limit=30) if found.ticker else []
        return render_template(
            "company.html",
            company=found,
            filings=filings,
            statements=statements,
            quote=quote,
            quote_history=history,
            stats=db.stats(),
            db_path=db.path.name,
        )

    @app.get("/ingest/status")
    def ingest_status():
        return jsonify(hub.snapshot())

    @app.post("/ingest/latest")
    def ingest_latest_route():
        db_file = app.config["EDGAR_DB_PATH"]

        def worker():
            db = Database(db_file)
            try:
                return ingest_latest(db)
            finally:
                db.close()

        started = hub.start(worker)
        status = 202 if started else 409
        body = hub.snapshot()
        if not started:
            body["error"] = body["error"] or "An ingest job is already running."
        return jsonify(body), status

    @app.post("/ingest/history")
    def ingest_history_route():
        payload = request.get_json(silent=True) or request.form
        start_raw = str(payload.get("start") or "").strip()
        end_raw = str(payload.get("end") or "").strip()
        try:
            start = _parse_iso_date(start_raw)
            end = _parse_iso_date(end_raw)
        except ValueError:
            return jsonify({"state": "error", "error": "Use YYYY-MM-DD for both dates."}), 400

        db_file = app.config["EDGAR_DB_PATH"]

        def worker():
            db = Database(db_file)
            try:
                return ingest_range(db, start, end)
            finally:
                db.close()

        started = hub.start(worker)
        status = 202 if started else 409
        body = hub.snapshot()
        if not started:
            body["error"] = body["error"] or "An ingest job is already running."
        return jsonify(body), status

    return app


def run_server(db_path: str | Path | None = None, host: str = "127.0.0.1", port: int = 8000) -> None:
    create_app(db_path).run(host=host, port=port, debug=False)

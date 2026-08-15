"""Local web UI for searching stored EDGAR filings."""

from __future__ import annotations

from pathlib import Path

from flask import Flask, abort, g, render_template, request

from edgar_filings.db import Database, default_db_path

PACKAGE_DIR = Path(__file__).resolve().parent


def create_app(db_path: str | Path | None = None) -> Flask:
    app = Flask(
        __name__,
        template_folder=str(PACKAGE_DIR / "templates"),
        static_folder=str(PACKAGE_DIR / "static"),
    )
    app.config["EDGAR_DB_PATH"] = str(Path(db_path) if db_path else default_db_path())

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
        if len(companies) == 1:
            filings = db.list_filings(companies[0].cik, limit=100)
        elif not query:
            filings = db.recent_filings(limit=80)
        return render_template(
            "index.html",
            query=query,
            stats=stats,
            companies=companies,
            filings=filings,
            db_path=db.path.name,
        )

    @app.route("/company/<cik>")
    def company(cik: str):
        db: Database = g.db
        found = db.company_by_cik(cik)
        if not found:
            abort(404)
        filings = db.list_filings(found.cik, limit=200)
        facts = db.query_facts(found.cik, limit=40)
        return render_template(
            "company.html",
            company=found,
            filings=filings,
            facts=facts,
            stats=db.stats(),
            db_path=db.path.name,
        )

    return app


def run_server(db_path: str | Path | None = None, host: str = "127.0.0.1", port: int = 8000) -> None:
    create_app(db_path).run(host=host, port=port, debug=False)

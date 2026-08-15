from edgar_filings.cli import build_parser, main


def test_cli_help():
    parser = build_parser()
    args = parser.parse_args(["ingest", "AAPL", "--forms", "10-K"])
    assert args.command == "ingest"
    assert args.ticker == "AAPL"


def test_cli_ingest_latest_args():
    parser = build_parser()
    args = parser.parse_args(["ingest-latest", "--skip-facts", "--lookback-days", "5"])
    assert args.command == "ingest-latest"
    assert args.skip_facts is True
    assert args.lookback_days == 5
    serve = parser.parse_args(["serve", "--port", "9000"])
    assert serve.command == "serve"
    assert serve.port == 9000
    history = parser.parse_args(["ingest-range", "2026-08-01", "2026-08-14"])
    assert history.command == "ingest-range"


def test_filings_missing_company(tmp_path, capsys):
    code = main(["--db", str(tmp_path / "empty.db"), "filings", "AAPL"])
    assert code == 1
    err = capsys.readouterr().err
    assert "ingest AAPL" in err

"""HTTP client for SEC EDGAR with User-Agent, throttling, and retries."""

from __future__ import annotations

import os
import threading
import time
from datetime import date
from typing import Any

import requests

DEFAULT_USER_AGENT = "edgar-filings YourName you@email.com"
DEFAULT_RATE_LIMIT = 6.0
MAX_RATE_LIMIT = 10.0
TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik}.json"
COMPANYFACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json"
DAILY_MASTER_URL = (
    "https://www.sec.gov/Archives/edgar/daily-index/{year}/QTR{quarter}/master.{yyyymmdd}.idx"
)


class EdgarConfigError(RuntimeError):
    """Raised when EDGAR client configuration is invalid."""


class RateLimiter:
    """Simple token-less throttle: at most `requests_per_second` calls."""

    def __init__(self, requests_per_second: float = DEFAULT_RATE_LIMIT) -> None:
        rps = min(max(requests_per_second, 0.1), MAX_RATE_LIMIT)
        self.min_interval = 1.0 / rps
        self._lock = threading.Lock()
        self._last = 0.0

    def wait(self) -> None:
        with self._lock:
            now = time.monotonic()
            delay = self._last + self.min_interval - now
            if delay > 0:
                time.sleep(delay)
            self._last = time.monotonic()


def pad_cik(cik: int | str) -> str:
    """Return a 10-digit zero-padded CIK."""
    return str(int(str(cik).strip())).zfill(10)


def cik_no_leading_zeros(cik: int | str) -> str:
    return str(int(str(cik).strip()))


def accession_no_dashes(accession: str) -> str:
    return accession.replace("-", "")


def document_url(cik: int | str, accession: str, primary_document: str) -> str:
    """Build the standard EDGAR archive URL for a filing's primary document."""
    return (
        "https://www.sec.gov/Archives/edgar/data/"
        f"{cik_no_leading_zeros(cik)}/"
        f"{accession_no_dashes(accession)}/"
        f"{primary_document}"
    )


def resolve_user_agent(explicit: str | None = None) -> str:
    ua = (explicit or os.environ.get("EDGAR_USER_AGENT") or DEFAULT_USER_AGENT).strip()
    if not ua:
        raise EdgarConfigError("EDGAR_USER_AGENT must not be empty")
    return ua


def resolve_rate_limit(explicit: float | None = None) -> float:
    if explicit is not None:
        return min(max(float(explicit), 0.1), MAX_RATE_LIMIT)
    raw = os.environ.get("EDGAR_RATE_LIMIT")
    if raw:
        return min(max(float(raw), 0.1), MAX_RATE_LIMIT)
    return DEFAULT_RATE_LIMIT


class EdgarClient:
    """SEC data.sec.gov / www.sec.gov JSON client."""

    def __init__(
        self,
        user_agent: str | None = None,
        rate_limit: float | None = None,
        session: requests.Session | None = None,
        max_retries: int = 5,
        timeout: float = 30.0,
    ) -> None:
        self.user_agent = resolve_user_agent(user_agent)
        self.rate_limiter = RateLimiter(resolve_rate_limit(rate_limit))
        self.session = session or requests.Session()
        self.max_retries = max_retries
        self.timeout = timeout

    def _headers(self) -> dict[str, str]:
        return {
            "User-Agent": self.user_agent,
            "Accept-Encoding": "gzip, deflate",
        }

    def get_response(
        self,
        url: str,
        *,
        allow_404: bool = False,
        allow_403: bool = False,
    ) -> requests.Response | None:
        last_error: Exception | None = None
        for attempt in range(self.max_retries):
            self.rate_limiter.wait()
            try:
                response = self.session.get(url, headers=self._headers(), timeout=self.timeout)
            except requests.RequestException as exc:
                last_error = exc
                time.sleep(min(2**attempt, 16))
                continue

            if allow_404 and response.status_code == 404:
                return None
            if allow_403 and response.status_code == 403:
                return None

            if response.status_code in (403, 429) or response.status_code >= 500:
                last_error = requests.HTTPError(
                    f"{response.status_code} for {url}", response=response
                )
                time.sleep(min(2**attempt, 16))
                continue

            response.raise_for_status()
            return response

        if last_error:
            raise last_error
        raise RuntimeError(f"Failed to fetch {url}")

    def get_json(self, url: str) -> Any:
        response = self.get_response(url)
        if response is None:
            raise RuntimeError(f"Failed to fetch {url}")
        return response.json()

    def get_text(self, url: str, *, allow_404: bool = False, allow_403: bool = False) -> str | None:
        response = self.get_response(url, allow_404=allow_404, allow_403=allow_403)
        if response is None:
            return None
        return response.text

    def company_tickers(self) -> dict[str, Any]:
        return self.get_json(TICKERS_URL)

    def submissions(self, cik: int | str) -> dict[str, Any]:
        return self.get_json(SUBMISSIONS_URL.format(cik=pad_cik(cik)))

    def company_facts(self, cik: int | str) -> dict[str, Any] | None:
        url = COMPANYFACTS_URL.format(cik=pad_cik(cik))
        response = self.get_response(url, allow_404=True)
        if response is None:
            return None
        return response.json()

    def daily_master(self, day: date) -> str | None:
        """Return the daily master.idx text for `day`, or None if it is unpublished."""
        yyyymmdd = day.strftime("%Y%m%d")
        quarter = (day.month - 1) // 3 + 1
        url = DAILY_MASTER_URL.format(year=day.year, quarter=quarter, yyyymmdd=yyyymmdd)
        return self.get_text(url, allow_404=True, allow_403=True)

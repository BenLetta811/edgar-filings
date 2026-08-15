"""Background ingest job for the local web UI."""

from __future__ import annotations

import threading
from collections.abc import Callable
from datetime import datetime

from edgar_filings.ingest import IngestError, IngestResult


class IngestHub:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.state = "idle"
        self.message = ""
        self.error = ""
        self.updated_at = ""

    def snapshot(self) -> dict[str, str]:
        with self._lock:
            return {
                "state": self.state,
                "message": self.message,
                "error": self.error,
                "updated_at": self.updated_at,
            }

    def start(self, worker: Callable[[], IngestResult]) -> bool:
        with self._lock:
            if self.state == "running":
                return False
            self.state = "running"
            self.message = "Downloading from EDGAR…"
            self.error = ""
            self.updated_at = datetime.now().isoformat(timespec="seconds")
        thread = threading.Thread(target=self._run, args=(worker,), daemon=True)
        thread.start()
        return True

    def _run(self, worker: Callable[[], IngestResult]) -> None:
        try:
            result = worker()
            with self._lock:
                self.state = "done"
                self.message = result.message
                self.error = ""
                self.updated_at = datetime.now().isoformat(timespec="seconds")
        except IngestError as exc:
            with self._lock:
                self.state = "error"
                self.message = ""
                self.error = str(exc)
                self.updated_at = datetime.now().isoformat(timespec="seconds")
        except Exception as exc:
            with self._lock:
                self.state = "error"
                self.message = ""
                self.error = f"Ingest failed: {exc}"
                self.updated_at = datetime.now().isoformat(timespec="seconds")

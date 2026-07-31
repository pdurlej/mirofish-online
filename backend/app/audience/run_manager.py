"""Small private in-process run queue for audience simulations."""

from __future__ import annotations

import threading
import uuid
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from .audience_run import AudienceRunInput
from .graph_store import AudienceGraphStore
from .live_runner import AudienceLiveRunner, AudienceRunFailed


@dataclass(frozen=True)
class QueuedRun:
    run_input: AudienceRunInput
    store: AudienceGraphStore


class AudienceRunManager:
    def __init__(
        self,
        *,
        runner_factory: Callable[[], AudienceLiveRunner] | None = None,
        max_terminal_records: int = 64,
    ) -> None:
        self._runner_factory = runner_factory or AudienceLiveRunner
        self._max_terminal_records = max(1, int(max_terminal_records))
        self._lock = threading.Lock()
        self._queue: deque[QueuedRun] = deque()
        self._records: dict[str, dict[str, Any]] = {}
        self._worker: threading.Thread | None = None

    def enqueue(self, run_input: AudienceRunInput, store: AudienceGraphStore) -> dict[str, Any]:
        run_id = live_run_id(run_input)
        now = datetime.now(UTC).isoformat()
        with self._lock:
            record = self._records.get(run_id)
            if record and record["status"] in {"queued", "running"}:
                return dict(record)
            if record is None:
                record = {
                    "run_id": run_id,
                }
                self._records[run_id] = record
            record.clear()
            record.update(
                {
                    "run_id": run_id,
                    "status": "queued",
                    "created_at": now,
                    "updated_at": now,
                    "counts": {},
                }
            )
            self._queue.append(QueuedRun(run_input=run_input, store=store))
            self._ensure_worker_locked()
            return dict(record)

    def get(self, run_id: str, store: AudienceGraphStore) -> dict[str, Any] | None:
        with self._lock:
            record = self._records.get(run_id)
            if record:
                record = dict(record)
        if record and record.get("status") != "completed":
            return record
        stored = store.read_run(run_id)
        if stored:
            return {"run_id": run_id, "status": "completed", "data": stored}
        return record

    def active_work(self) -> dict[str, int]:
        """Return count-only queue state for lifecycle decisions."""
        with self._lock:
            return {
                "queued": len(self._queue),
                "running": sum(
                    record.get("status") == "running"
                    for record in self._records.values()
                ),
                "worker": int(bool(self._worker and self._worker.is_alive())),
            }

    def _ensure_worker_locked(self) -> None:
        if self._worker and self._worker.is_alive():
            return
        self._worker = threading.Thread(target=self._drain, daemon=True)
        self._worker.start()

    def _drain(self) -> None:
        while True:
            with self._lock:
                if not self._queue:
                    return
                item = self._queue.popleft()
                run_id = live_run_id(item.run_input)
                self._records[run_id].update(
                    {
                        "status": "running",
                        "updated_at": datetime.now(UTC).isoformat(),
                    }
                )
            try:
                result = self._runner_factory().run(
                    item.run_input,
                    previous_topics=item.store.previous_topics(),
                )
                counts = item.store.write_run(result)
                with self._lock:
                    self._records[run_id].update(
                        {
                            "status": "completed",
                            "updated_at": datetime.now(UTC).isoformat(),
                            "counts": counts,
                        }
                    )
                    self._prune_terminal_records_locked()
            except AudienceRunFailed as exc:
                self._mark_failed(run_id, type(exc).__name__, diagnostics=exc.diagnostics())
            except Exception as exc:
                self._mark_failed(run_id, type(exc).__name__)

    def _mark_failed(
        self,
        run_id: str,
        error_kind: str,
        *,
        diagnostics: dict[str, Any] | None = None,
    ) -> None:
        update = {
            "status": "failed",
            "updated_at": datetime.now(UTC).isoformat(),
            "error_kind": error_kind,
        }
        if diagnostics:
            update["diagnostics"] = diagnostics
        with self._lock:
            self._records[run_id].update(update)
            self._prune_terminal_records_locked()

    def _prune_terminal_records_locked(self) -> None:
        terminal = [
            (run_id, record)
            for run_id, record in self._records.items()
            if record.get("status") in {"completed", "failed"}
        ]
        overflow = len(terminal) - self._max_terminal_records
        if overflow <= 0:
            return
        terminal.sort(key=lambda item: str(item[1].get("updated_at") or ""))
        for run_id, _record in terminal[:overflow]:
            self._records.pop(run_id, None)


def live_run_id(run_input: AudienceRunInput) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"live:{run_input.topic_hash}:{run_input.run_seed}"))

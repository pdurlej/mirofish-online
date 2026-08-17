from __future__ import annotations

import threading
import time
from dataclasses import dataclass

from app.audience.audience_run import AudienceRunInput
from app.audience.run_manager import AudienceRunManager, live_run_id


@dataclass
class FakeResult:
    run_id: str
    payload: str = "result"

    def to_dict(self) -> dict[str, str]:
        return {"run_id": self.run_id, "payload": self.payload}


class RecordingStore:
    def __init__(self) -> None:
        self.runs: dict[str, dict[str, str]] = {}
        self.previous_topics_calls: list[bool] = []

    def previous_topics(self, limit: int = 25, *, live_only: bool = False) -> list[dict]:
        self.previous_topics_calls.append(live_only)
        return []

    def write_run(self, result: FakeResult) -> dict[str, int]:
        self.runs[result.run_id] = result.to_dict()
        return {"runs": 1}

    def read_run(self, run_id: str) -> dict[str, str] | None:
        return self.runs.get(run_id)


class FastRunner:
    def run(self, run_input: AudienceRunInput, *, previous_topics=None) -> FakeResult:
        return FakeResult(live_run_id(run_input), payload="x" * 50_000)


def _run_input(index: int) -> AudienceRunInput:
    return AudienceRunInput(
        topic=f"Controlled topic {index} with enough detail for validation",
        channel="blog",
        run_seed=str(index),
    )


def _wait_until_idle(manager: AudienceRunManager) -> None:
    deadline = time.monotonic() + 5
    while any(manager.active_work().values()):
        if time.monotonic() >= deadline:
            raise AssertionError("audience run manager did not become idle")
        time.sleep(0.01)


def test_completed_records_are_bounded_and_payloads_are_loaded_from_store():
    store = RecordingStore()
    manager = AudienceRunManager(runner_factory=FastRunner, max_terminal_records=2)
    run_ids = []

    for index in range(5):
        run_input = _run_input(index)
        run_ids.append(live_run_id(run_input))
        manager.enqueue(run_input, store)
    _wait_until_idle(manager)

    assert len(manager._records) == 2
    assert all("data" not in record for record in manager._records.values())
    assert manager.get(run_ids[0], store) == {
        "run_id": run_ids[0],
        "status": "completed",
        "data": store.runs[run_ids[0]],
    }
    assert manager.get(run_ids[-1], store) == {
        "run_id": run_ids[-1],
        "status": "completed",
        "data": store.runs[run_ids[-1]],
    }


def test_enqueue_is_idempotent_while_the_same_run_is_active():
    started = threading.Event()
    release = threading.Event()

    class BlockingRunner:
        calls = 0

        def run(self, run_input, *, previous_topics=None):
            BlockingRunner.calls += 1
            started.set()
            assert release.wait(timeout=2)
            return FakeResult(live_run_id(run_input))

    store = RecordingStore()
    manager = AudienceRunManager(runner_factory=BlockingRunner)
    run_input = _run_input(1)

    first = manager.enqueue(run_input, store)
    assert started.wait(timeout=2)
    second = manager.enqueue(run_input, store)
    release.set()
    _wait_until_idle(manager)

    assert first["run_id"] == second["run_id"]
    assert second["status"] in {"queued", "running"}
    assert BlockingRunner.calls == 1


def test_live_runs_ask_for_live_only_reviewer_memory():
    """The live path must not be fed imported or fake history.

    Reviewer memory is quoted back to the personas as their own past reactions,
    and production holds 73 runs from a one-off research import plus fake runs
    from the UI toggle. A live run that learns from those is learning from a
    different system. This asserts the request, because the alternative is
    noticing months later that the panel remembers things it never said.
    """
    store = RecordingStore()
    manager = AudienceRunManager(runner_factory=FastRunner)

    manager.enqueue(_run_input(1), store)
    _wait_until_idle(manager)

    assert store.previous_topics_calls == [True]

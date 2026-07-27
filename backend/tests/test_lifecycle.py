from __future__ import annotations

from dataclasses import dataclass

from app import create_app
from app.audience.run_manager import AudienceRunManager
from app.config import Config
from app.lifecycle import LifecycleState
from app.models.task import TaskManager, TaskStatus
from app.services.graph_memory_updater import GraphMemoryManager
from app.services.simulation_runner import SimulationRunner


class TestConfig(Config):
    TESTING = True
    DEBUG = False
    MIROFISH_START_DRAINED = False


@dataclass
class FakeDependency:
    ready: bool

    def health_check(self) -> bool:
        return self.ready

    def readiness_check(self) -> bool:
        return self.ready


def app_with_dependencies(monkeypatch, *, neo4j: bool, embedding: bool):
    from app import storage

    fake_neo4j = FakeDependency(neo4j)
    monkeypatch.setattr(storage, "Neo4jStorage", lambda: fake_neo4j)
    app = create_app(TestConfig)
    app.extensions["neo4j_storage"] = fake_neo4j
    app.extensions["embedding_service"] = FakeDependency(embedding)
    return app


def test_health_fails_closed_when_neo4j_or_ollama_is_unavailable(monkeypatch):
    app = app_with_dependencies(monkeypatch, neo4j=False, embedding=True)
    response = app.test_client().get("/health/ready")
    assert response.status_code == 503
    assert response.get_json()["dependencies"] == {
        "embedding_ollama": True,
        "neo4j": False,
    }

    app.extensions["neo4j_storage"].ready = True
    app.extensions["embedding_service"].ready = False
    response = app.test_client().get("/health/ready")
    assert response.status_code == 503
    assert response.get_json()["dependencies"] == {
        "embedding_ollama": False,
        "neo4j": True,
    }


def test_drain_rejects_new_mutations_but_allows_reads(monkeypatch):
    app = app_with_dependencies(monkeypatch, neo4j=True, embedding=True)
    client = app.test_client()

    drained = client.post("/internal/lifecycle/drain")
    assert drained.status_code == 200
    assert drained.get_json()["lifecycle"]["draining"] is True

    rejected = client.post("/api/audience/runs/fake", json={"topic": "blocked"})
    assert rejected.status_code == 503
    assert rejected.get_json()["error"] == "service_draining"

    allowed = client.get("/api/audience/personas")
    assert allowed.status_code == 200
    status = client.get("/internal/lifecycle/status").get_json()["lifecycle"]
    assert status["active_requests"] == 0

    resumed = client.post("/internal/lifecycle/resume")
    assert resumed.status_code == 200
    assert resumed.get_json()["lifecycle"]["draining"] is False


def test_internal_lifecycle_control_is_loopback_only(monkeypatch):
    app = app_with_dependencies(monkeypatch, neo4j=True, embedding=True)
    client = app.test_client()

    response = client.post(
        "/internal/lifecycle/drain",
        environ_base={"REMOTE_ADDR": "172.19.0.20"},
    )

    assert response.status_code == 403
    assert response.get_json() == {"success": False, "error": "forbidden"}


def test_resume_stays_drained_until_dependencies_are_ready(monkeypatch):
    app = app_with_dependencies(monkeypatch, neo4j=True, embedding=False)
    client = app.test_client()
    client.post("/internal/lifecycle/drain")

    response = client.post("/internal/lifecycle/resume")

    assert response.status_code == 503
    assert response.get_json()["lifecycle"]["draining"] is True


def test_snapshot_fails_closed_for_busy_and_unknown_providers():
    state = LifecycleState()
    state.register_provider("known", lambda: {"queued": 2})
    state.register_provider("unknown", lambda: 1 / 0)

    snapshot = state.drain()

    assert snapshot["idle"] is False
    assert snapshot["busy_count"] == 2
    assert snapshot["unknown_providers"] == 1
    assert snapshot["work"] == {"known": {"queued": 2}, "unknown": {}}


def test_count_only_adapters_cover_tasks_processes_monitors_and_updaters():
    task_manager = TaskManager()
    original_tasks = task_manager._tasks
    original_processes = SimulationRunner._processes
    original_monitors = SimulationRunner._monitor_threads
    original_queues = SimulationRunner._action_queues
    original_updaters = GraphMemoryManager._updaters

    class FakeProcess:
        def poll(self):
            return None

    class FakeThread:
        def is_alive(self):
            return True

    class FakeQueue:
        def qsize(self):
            return 3

    class FakeUpdater:
        def get_stats(self):
            return {
                "running": True,
                "queue_size": 2,
                "buffer_sizes": {"twitter": 1, "reddit": 4},
            }

    try:
        task_manager._tasks = {}
        pending = task_manager.create_task("graph")
        processing = task_manager.create_task("simulation")
        task_manager.update_task(processing, status=TaskStatus.PROCESSING)
        assert task_manager.active_work() == {"pending": 1, "processing": 1}

        SimulationRunner._processes = {"private-id": FakeProcess()}
        SimulationRunner._monitor_threads = {"private-id": FakeThread()}
        SimulationRunner._action_queues = {"private-id": FakeQueue()}
        assert SimulationRunner.active_work() == {
            "processes": 1,
            "monitors": 1,
            "queued_actions": 3,
        }

        GraphMemoryManager._updaters = {"private-id": FakeUpdater()}
        assert GraphMemoryManager.active_work() == {
            "updaters": 1,
            "running": 1,
            "queued_items": 2,
            "buffered_items": 5,
        }
        assert "private-id" not in str(GraphMemoryManager.active_work())
        assert pending not in str(task_manager.active_work())
    finally:
        task_manager._tasks = original_tasks
        SimulationRunner._processes = original_processes
        SimulationRunner._monitor_threads = original_monitors
        SimulationRunner._action_queues = original_queues
        GraphMemoryManager._updaters = original_updaters


def test_audience_adapter_counts_queue_run_and_worker_without_identifiers():
    manager = AudienceRunManager()

    class FakeThread:
        def is_alive(self):
            return True

    manager._queue = [object(), object()]
    manager._records = {
        "private-run-id": {"status": "running"},
        "finished-run-id": {"status": "completed"},
    }
    manager._worker = FakeThread()

    counts = manager.active_work()

    assert counts == {"queued": 2, "running": 1, "worker": 1}
    assert "private-run-id" not in str(counts)

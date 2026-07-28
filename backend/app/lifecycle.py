"""Fail-closed lifecycle coordination for the on-demand RS2000 stack."""

from __future__ import annotations

import argparse
import json
import threading
import urllib.error
import urllib.request
from collections.abc import Callable, Mapping
from typing import Any

from flask import Flask, g, jsonify, request


SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
LOOPBACK_ADDRESSES = frozenset({"127.0.0.1", "::1"})
CONTROL_BASE_URL = "http://127.0.0.1:5001/internal/lifecycle"

CountProvider = Callable[[], Mapping[str, int]]
ReadinessProbe = Callable[[], Mapping[str, bool]]


class LifecycleState:
    """Track draining, active requests, background work, and dependencies."""

    def __init__(self, *, start_drained: bool = False) -> None:
        self._lock = threading.RLock()
        self._draining = start_drained
        self._active_requests = 0
        self._providers: dict[str, CountProvider] = {}
        self._readiness_probe: ReadinessProbe | None = None

    def register_provider(self, name: str, provider: CountProvider) -> None:
        with self._lock:
            self._providers[name] = provider

    def set_readiness_probe(self, probe: ReadinessProbe) -> None:
        with self._lock:
            self._readiness_probe = probe

    def begin_request(self, path: str, method: str) -> bool | None:
        """Accept and count API work, reject new mutations while draining."""
        if not path.startswith("/api/"):
            return None
        with self._lock:
            if self._draining and method.upper() not in SAFE_METHODS:
                return False
            self._active_requests += 1
            return True

    def end_request(self) -> None:
        with self._lock:
            self._active_requests = max(self._active_requests - 1, 0)

    def drain(self) -> dict[str, Any]:
        with self._lock:
            self._draining = True
        return self.snapshot()

    def resume(self) -> tuple[bool, dict[str, Any]]:
        readiness = self.readiness()
        if not readiness["ready"]:
            return False, readiness
        with self._lock:
            self._draining = False
        return True, readiness

    def readiness(self) -> dict[str, Any]:
        with self._lock:
            probe = self._readiness_probe
        if probe is None:
            dependencies = {"probe_configured": False}
        else:
            try:
                dependencies = {
                    str(name): bool(ready)
                    for name, ready in probe().items()
                }
            except Exception:  # noqa: BLE001 - health must fail closed
                dependencies = {"probe_error": False}
        return {
            "ready": bool(dependencies) and all(dependencies.values()),
            "dependencies": dependencies,
        }

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            draining = self._draining
            active_requests = self._active_requests
            providers = list(self._providers.items())

        work: dict[str, dict[str, int]] = {}
        unknown_providers = 0
        busy_count = active_requests
        for name, provider in providers:
            try:
                counts = {
                    str(key): max(int(value), 0)
                    for key, value in provider().items()
                }
            except Exception:  # noqa: BLE001 - unknown work is never idle
                counts = {}
                unknown_providers += 1
            work[name] = counts
            busy_count += sum(counts.values())

        return {
            "draining": draining,
            "idle": busy_count == 0 and unknown_providers == 0,
            "busy_count": busy_count,
            "unknown_providers": unknown_providers,
            "active_requests": active_requests,
            "work": work,
        }


def dependency_readiness(app: Flask) -> dict[str, bool]:
    """Probe both stateful dependencies without returning error details."""
    neo4j_storage = app.extensions.get("neo4j_storage")
    embedding_service = app.extensions.get("embedding_service")
    return {
        "neo4j": bool(
            neo4j_storage
            and getattr(neo4j_storage, "health_check", lambda: False)()
        ),
        "embedding_ollama": bool(
            embedding_service
            and getattr(embedding_service, "readiness_check", lambda: False)()
        ),
    }


def register_default_work_providers(state: LifecycleState) -> None:
    """Attach count-only adapters for every in-process work owner."""
    from .api.audience import audience_active_work
    from .models.task import TaskManager
    from .services.graph_memory_updater import GraphMemoryManager
    from .services.simulation_runner import SimulationRunner

    state.register_provider("audience", audience_active_work)
    state.register_provider("tasks", TaskManager().active_work)
    state.register_provider("simulations", SimulationRunner.active_work)
    state.register_provider("graph_memory", GraphMemoryManager.active_work)


def register_lifecycle(app: Flask, state: LifecycleState) -> None:
    """Install health, readiness, drain gate, and loopback-only controls."""
    app.extensions["lifecycle"] = state
    state.set_readiness_probe(lambda: dependency_readiness(app))

    @app.before_request
    def lifecycle_request_gate():
        decision = state.begin_request(request.path, request.method)
        g.lifecycle_counted = decision is True
        if decision is False:
            return jsonify(
                {
                    "success": False,
                    "error": "service_draining",
                    "retryable": True,
                }
            ), 503
        return None

    @app.after_request
    def lifecycle_request_complete(response):
        if getattr(g, "lifecycle_counted", False):
            state.end_request()
            g.lifecycle_counted = False
        return response

    @app.teardown_request
    def lifecycle_request_teardown(_error):
        if getattr(g, "lifecycle_counted", False):
            state.end_request()
            g.lifecycle_counted = False

    @app.route("/health/live")
    def health_live():
        return {"status": "live", "service": "mirofish-online"}

    @app.route("/health/ready")
    def health_ready():
        readiness = state.readiness()
        snapshot = state.snapshot()
        ready = readiness["ready"] and not snapshot["draining"]
        return (
            {
                "status": "ready" if ready else "not_ready",
                "service": "mirofish-online",
                "draining": snapshot["draining"],
                "dependencies": readiness["dependencies"],
            },
            200 if ready else 503,
        )

    @app.route("/health")
    def health_compat():
        return health_ready()

    def require_loopback():
        if request.remote_addr not in LOOPBACK_ADDRESSES:
            return jsonify({"success": False, "error": "forbidden"}), 403
        return None

    @app.route("/internal/lifecycle/status", methods=["GET"])
    def lifecycle_status():
        denied = require_loopback()
        if denied:
            return denied
        return jsonify({"success": True, "lifecycle": state.snapshot()})

    @app.route("/internal/lifecycle/drain", methods=["POST"])
    def lifecycle_drain():
        denied = require_loopback()
        if denied:
            return denied
        return jsonify({"success": True, "lifecycle": state.drain()})

    @app.route("/internal/lifecycle/resume", methods=["POST"])
    def lifecycle_resume():
        denied = require_loopback()
        if denied:
            return denied
        resumed, readiness = state.resume()
        return (
            jsonify(
                {
                    "success": resumed,
                    "lifecycle": state.snapshot(),
                    "readiness": readiness,
                }
            ),
            200 if resumed else 503,
        )


def _control_request(action: str) -> tuple[int, dict[str, Any]]:
    method = "GET" if action == "status" else "POST"
    request_object = urllib.request.Request(
        f"{CONTROL_BASE_URL}/{action}",
        method=method,
        headers={"User-Agent": "mirofish-lifecycle-control/1"},
    )
    try:
        with urllib.request.urlopen(request_object, timeout=5) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        try:
            payload = json.loads(exc.read().decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            payload = {"success": False, "error": "control_failed"}
        return exc.code, payload
    except (urllib.error.URLError, TimeoutError):
        return 503, {"success": False, "error": "control_unreachable"}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("status", "drain", "resume"))
    args = parser.parse_args()
    status, payload = _control_request(args.action)
    print(json.dumps(payload, sort_keys=True))
    return 0 if 200 <= status < 300 else 2


if __name__ == "__main__":
    raise SystemExit(main())

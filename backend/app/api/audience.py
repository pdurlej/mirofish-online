"""Private Audience Graph API routes."""

from __future__ import annotations

from flask import current_app, jsonify, request

from ..audience import (
    AudienceLiveRunner,
    AudienceRunInput,
    AudienceRunManager,
    InMemoryAudienceGraphStore,
    Neo4jAudienceGraphStore,
    build_fake_audience_run,
    load_default_personas,
)
from ..config import Config
from ..storage.embedding_service import EmbeddingService
from . import audience_bp

_STORE = InMemoryAudienceGraphStore()
_RUN_MANAGER = AudienceRunManager(
    runner_factory=lambda: AudienceLiveRunner(
        failure_threshold=Config.MIROFISH_AUDIENCE_FAILURE_THRESHOLD,
        call_timeout_seconds=Config.MIROFISH_AUDIENCE_CALL_TIMEOUT_SECONDS,
        run_timeout_seconds=Config.MIROFISH_AUDIENCE_RUN_TIMEOUT_SECONDS,
        max_workers=min(Config.MIROFISH_AUDIENCE_MAX_WORKERS, 6),
        embedding_service_factory=_audience_embedding_service,
    ),
    max_terminal_records=Config.MIROFISH_AUDIENCE_MAX_TERMINAL_RECORDS,
)


def audience_active_work() -> dict[str, int]:
    """Expose sanitized in-process work counts to the lifecycle coordinator."""
    return _RUN_MANAGER.active_work()


def _get_store():
    if Config.MIROFISH_AUDIENCE_STORE == "memory":
        return _STORE
    storage = current_app.extensions.get("neo4j_storage")
    if storage:
        return Neo4jAudienceGraphStore(storage)
    return _STORE


def _audience_embedding_service() -> EmbeddingService:
    return EmbeddingService(max_retries=1, timeout=5)


def _run_input_from_payload(payload: dict) -> AudienceRunInput:
    return AudienceRunInput(
        topic=str(payload.get("topic", "")),
        channel=str(payload.get("channel", "unknown")),
        title=payload.get("title"),
        run_seed=str(payload.get("run_seed", "ui")),
    )


@audience_bp.route("/personas", methods=["GET"])
def list_personas():
    personas = load_default_personas()
    return jsonify(
        {
            "success": True,
            "data": [persona.to_dict() for persona in personas if persona.active],
            "count": len(personas),
        }
    )


@audience_bp.route("/runs", methods=["GET"])
def list_runs():
    try:
        limit = min(max(int(request.args.get("limit", 25)), 1), 100)
    except ValueError:
        limit = 25
    data = _get_store().list_runs(limit)
    return jsonify({"success": True, "data": data, "count": len(data)})


@audience_bp.route("/graph", methods=["GET"])
def get_graph_snapshot():
    try:
        limit = min(max(int(request.args.get("limit", 120)), 1), 300)
    except ValueError:
        limit = 120
    try:
        min_score = min(max(float(request.args.get("min_score", 0.35)), 0.0), 1.0)
    except ValueError:
        min_score = 0.35
    include_personas = str(request.args.get("include_personas", "false")).lower() in {
        "1",
        "true",
        "yes",
    }
    data = _get_store().graph_snapshot(
        limit=limit,
        min_score=min_score,
        include_personas=include_personas,
    )
    return jsonify({"success": True, "data": data})


@audience_bp.route("/runs", methods=["POST"])
def create_live_run():
    payload = request.get_json(silent=True) or {}
    try:
        run_input = _run_input_from_payload(payload)
        record = _RUN_MANAGER.enqueue(run_input, _get_store())
    except ValueError as exc:
        return jsonify({"success": False, "error": str(exc)}), 400
    return jsonify({"success": True, "data": record}), 202


@audience_bp.route("/runs/fake", methods=["POST"])
def create_fake_run():
    payload = request.get_json(silent=True) or {}
    try:
        run_input = _run_input_from_payload(payload)
        store = _get_store()
        result = build_fake_audience_run(
            run_input,
            previous_topics=store.previous_topics(),
        )
        counts = store.write_run(result)
    except ValueError as exc:
        return jsonify({"success": False, "error": str(exc)}), 400

    data = result.to_dict()
    data["write_counts"] = counts
    return jsonify({"success": True, "data": data})


@audience_bp.route("/runs/<run_id>", methods=["GET"])
def get_run(run_id: str):
    store = _get_store()
    stored = _RUN_MANAGER.get(run_id, store)
    if not stored:
        return jsonify({"success": False, "error": "Run not found"}), 404
    return jsonify({"success": True, "data": stored})

"""Private Audience Graph API routes."""

from __future__ import annotations

from flask import current_app, jsonify, request

from . import audience_bp
from ..audience import (
    AudienceRunInput,
    InMemoryAudienceGraphStore,
    Neo4jAudienceGraphStore,
    build_fake_audience_run,
    load_default_personas,
)


_STORE = InMemoryAudienceGraphStore()


def _get_store():
    storage = current_app.extensions.get("neo4j_storage")
    if storage:
        return Neo4jAudienceGraphStore(storage)
    return _STORE


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


@audience_bp.route("/runs/fake", methods=["POST"])
def create_fake_run():
    payload = request.get_json(silent=True) or {}
    try:
        run_input = AudienceRunInput(
            topic=str(payload.get("topic", "")),
            channel=str(payload.get("channel", "unknown")),
            title=payload.get("title"),
            run_seed=str(payload.get("run_seed", "ui")),
        )
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
    stored = _get_store().read_run(run_id)
    if not stored:
        return jsonify({"success": False, "error": "Run not found"}), 404
    return jsonify({"success": True, "data": stored})

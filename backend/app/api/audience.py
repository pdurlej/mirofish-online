"""Private Audience Graph API routes."""

from __future__ import annotations

from flask import jsonify, request

from . import audience_bp
from ..audience import (
    AudienceRunInput,
    InMemoryAudienceGraphStore,
    build_fake_audience_run,
    load_default_personas,
)


_STORE = InMemoryAudienceGraphStore()


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
        result = build_fake_audience_run(
            run_input,
            previous_topics=_STORE.previous_topics(),
        )
        counts = _STORE.write_run(result)
    except ValueError as exc:
        return jsonify({"success": False, "error": str(exc)}), 400

    data = result.to_dict()
    data["write_counts"] = counts
    return jsonify({"success": True, "data": data})


@audience_bp.route("/runs/<run_id>", methods=["GET"])
def get_run(run_id: str):
    stored = _STORE.read_run(run_id)
    if not stored:
        return jsonify({"success": False, "error": "Run not found"}), 404
    return jsonify({"success": True, "data": stored})

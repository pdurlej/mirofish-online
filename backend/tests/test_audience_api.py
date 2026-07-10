from __future__ import annotations

import json
import logging
import time
from io import StringIO

from app import create_app
from app.audience import (
    AudienceRunFailed,
    AudienceRunManager,
    InMemoryAudienceGraphStore,
    build_fake_audience_run,
    live_run_id,
)


def test_audience_personas_endpoint_returns_20_active_personas():
    app = create_app()
    client = app.test_client()

    response = client.get("/api/audience/personas")

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["success"] is True
    assert payload["count"] == 20
    assert len(payload["data"]) == 20


def test_fake_audience_run_returns_report_shape():
    app = create_app()
    client = app.test_client()

    response = client.post(
        "/api/audience/runs/fake",
        json={
            "topic": "Should product managers care about AI harnesses?",
            "channel": "linkedin",
            "title": "AI harnesses for PMs",
            "run_seed": "test",
        },
    )

    assert response.status_code == 200
    payload = response.get_json()
    data = payload["data"]
    assert payload["success"] is True
    assert data["recommendation"]["decision"] == "narrow"
    assert data["recommendation"]["best_channel"] == "linkedin"
    assert data["recommendation"]["channel_scores"][0]["channel"] == "linkedin"
    assert data["recommendation"]["channel_scores"][0]["score"] >= 60
    assert data["recommendation"]["channel_scores_source"] == "persona_aggregate"
    assert len(data["reactions"][0]["channel_scores"]) == 5
    assert len(data["reactions"]) == 20
    assert data["write_counts"]["reactions"] == 20

    stored = client.get(f"/api/audience/runs/{data['run_id']}").get_json()
    assert stored["success"] is True
    assert stored["data"]["status"] == "completed"
    assert stored["data"]["data"]["topic"]["title"] == "AI harnesses for PMs"
    assert stored["data"]["data"]["topic"]["cluster_label"] == "AI harnesses for PMs"
    assert stored["data"]["data"]["recommendation"]["channel_scores"]
    assert stored["data"]["data"]["persona_memory"]


def test_second_fake_run_can_report_similarity_edge():
    app = create_app()
    client = app.test_client()

    client.post(
        "/api/audience/runs/fake",
        json={
            "topic": "AI harnesses help product managers make reliable decisions",
            "run_seed": "one",
        },
    )
    response = client.post(
        "/api/audience/runs/fake",
        json={
            "topic": "Reliable AI decisions need product managers to use harnesses",
            "run_seed": "two",
        },
    )

    assert response.status_code == 200
    data = response.get_json()["data"]
    assert len(data["similarity_edges"]) >= 1
    assert data["similarity_edges"][0]["target_title"]
    assert data["similarity_edges"][0]["method"] in {"lexical", "hybrid", "semantic"}
    assert data["topic"]["cluster_label"]

    history = client.get("/api/audience/runs?limit=5").get_json()["data"]
    assert history[0]["similar_topics"][0]["title"]
    assert history[0]["cluster_label"]
    assert history[0]["channel_scores"]
    assert history[0]["channel_scores_source"] == "persona_aggregate"


def test_audience_graph_endpoint_returns_sanitized_topic_cluster_snapshot(monkeypatch):
    from app.api import audience as audience_api

    monkeypatch.setattr(audience_api, "_STORE", InMemoryAudienceGraphStore())
    app = create_app()
    client = app.test_client()

    client.post(
        "/api/audience/runs/fake",
        json={
            "topic": "SECRET_PRIVATE_TOPIC AI harnesses help PMs make reliable decisions",
            "title": "AI harnesses for PMs",
            "channel": "linkedin",
            "run_seed": "graph-one",
        },
    )
    client.post(
        "/api/audience/runs/fake",
        json={
            "topic": "Reliable AI decisions need PMs to use harnesses and evals",
            "title": "Reliable AI decisions",
            "channel": "blog",
            "run_seed": "graph-two",
        },
    )

    response = client.get("/api/audience/graph?limit=20&min_score=0.2")

    assert response.status_code == 200
    payload = response.get_json()
    data = payload["data"]
    assert payload["success"] is True
    assert data["stats"]["topic_count"] == 2
    assert data["stats"]["cluster_count"] >= 1
    assert data["stats"]["similarity_edge_count"] >= 1
    assert any(node["type"] == "topic" for node in data["nodes"])
    assert any(node["type"] == "cluster" for node in data["nodes"])
    assert any(edge["type"] == "IN_CLUSTER" for edge in data["edges"])
    assert any(edge["type"] == "SIMILAR_TO" for edge in data["edges"])
    assert "SECRET_PRIVATE_TOPIC" not in json.dumps(data)


def test_audience_graph_endpoint_filters_edges_and_limits_topics(monkeypatch):
    from app.api import audience as audience_api

    monkeypatch.setattr(audience_api, "_STORE", InMemoryAudienceGraphStore())
    app = create_app()
    client = app.test_client()

    client.post(
        "/api/audience/runs/fake",
        json={
            "topic": "AI harnesses help PMs make reliable decisions",
            "title": "AI harnesses for PMs",
            "run_seed": "limit-one",
        },
    )
    client.post(
        "/api/audience/runs/fake",
        json={
            "topic": "Reliable AI decisions need PMs to use harnesses and evals",
            "title": "Reliable AI decisions",
            "run_seed": "limit-two",
        },
    )

    limited = client.get("/api/audience/graph?limit=1&min_score=0.2").get_json()["data"]
    strict = client.get("/api/audience/graph?limit=20&min_score=0.99").get_json()["data"]

    assert limited["stats"]["topic_count"] == 1
    assert limited["stats"]["similarity_edge_count"] == 0
    assert strict["stats"]["topic_count"] == 2
    assert strict["stats"]["similarity_edge_count"] == 0


class FakeRunner:
    def run(self, run_input, *, previous_topics=None):
        result = build_fake_audience_run(
            run_input,
            previous_topics=previous_topics,
        )
        payload = result.to_dict()
        payload["receipt"] = payload["receipt"] | {
            "mode": "live",
            "usage": {
                "prompt_tokens": 100,
                "completion_tokens": 200,
                "total_tokens": 300,
            },
            "reliability_grade": "green",
            "model_routing": {
                "model_pool": ["gemma4:31b"],
                "high_quality_retry_model": "gemma4:31b",
                "failure_threshold": 0.3,
                "max_workers": 6,
            },
            "quality_warnings": [
                {
                    "kind": "duplicate_objections",
                    "message": "Treat this run as lower confidence.",
                }
            ],
            "duplicate_objection_count": 3,
            "max_duplicate_objections": 4,
        }
        return result.__class__(
            run_id=live_run_id(run_input),
            created_at=result.created_at,
            topic=result.topic,
            personas=result.personas,
            reactions=result.reactions,
            objections=result.objections,
            insights=result.insights,
            recommendation=result.recommendation,
            similarity_edges=result.similarity_edges,
            persona_memory=result.persona_memory,
            receipt=payload["receipt"],
            failures=[],
        )


def test_live_audience_run_endpoint_queues_completes_and_lists_history(monkeypatch):
    from app.api import audience as audience_api

    monkeypatch.setattr(
        audience_api,
        "_RUN_MANAGER",
        AudienceRunManager(runner_factory=FakeRunner),
    )
    app = create_app()
    client = app.test_client()

    response = client.post(
        "/api/audience/runs",
        json={
            "topic": "Should product managers care about AI harnesses?",
            "channel": "linkedin",
            "title": "AI harnesses for PMs",
            "run_seed": "live-api-test",
        },
    )

    assert response.status_code == 202
    run_id = response.get_json()["data"]["run_id"]
    final_payload = None
    for _ in range(20):
        status = client.get(f"/api/audience/runs/{run_id}").get_json()["data"]
        if status["status"] == "completed":
            final_payload = status
            break
        time.sleep(0.02)

    assert final_payload is not None
    assert final_payload["data"]["receipt"]["mode"] == "live"
    assert final_payload["data"]["receipt"]["usage"]["total_tokens"] == 300

    history = client.get("/api/audience/runs?limit=10").get_json()
    assert history["success"] is True
    assert history["data"][0]["run_id"] == run_id
    assert history["data"][0]["total_tokens"] == 300
    assert "similar_topics" in history["data"][0]
    assert "cluster_label" in history["data"][0]
    assert history["data"][0]["model_routing"]["model_pool"] == ["gemma4:31b"]
    assert history["data"][0]["quality_warnings"][0]["kind"] == "duplicate_objections"
    assert history["data"][0]["duplicate_objection_count"] == 3
    assert history["data"][0]["max_duplicate_objections"] == 4


class FailingRunner:
    def run(self, run_input, *, previous_topics=None):  # noqa: ANN001, ARG002
        raise AudienceRunFailed(
            "failure_threshold_exceeded",
            receipt={
                "mode": "live",
                "usage": {
                    "prompt_tokens": 100,
                    "completion_tokens": 50,
                    "total_tokens": 150,
                },
                "models": {
                    "deepseek-v4-flash": {
                        "calls": 20,
                        "failures": 9,
                        "prompt_tokens": 100,
                        "completion_tokens": 50,
                        "total_tokens": 150,
                        "latency_ms": 1000,
                    }
                },
                "latency_ms": 1000,
                "schema_fallback_count": 0,
                "failed_persona_count": 9,
                "low_quality_persona_count": 8,
                "failure_rate": 0.45,
                "reliability_grade": "red",
            },
            failures=[
                {
                    "persona_id": "operator-pm",
                    "model": "deepseek-v4-flash",
                    "error_kind": "low_quality_response",
                }
            ],
            partial_counts={"personas": 20, "reactions": 11, "objections": 11, "insights": 11},
        )


def test_failed_live_audience_run_exposes_sanitized_diagnostics(monkeypatch):
    from app.api import audience as audience_api

    monkeypatch.setattr(
        audience_api,
        "_RUN_MANAGER",
        AudienceRunManager(runner_factory=FailingRunner),
    )
    app = create_app()
    client = app.test_client()

    response = client.post(
        "/api/audience/runs",
        json={
            "topic": "SECRET_PRIVATE_TOPIC should not appear in failed diagnostics",
            "channel": "linkedin",
            "title": "Private test topic",
            "run_seed": "live-api-failed-test",
        },
    )

    assert response.status_code == 202
    run_id = response.get_json()["data"]["run_id"]
    final_payload = None
    for _ in range(20):
        status = client.get(f"/api/audience/runs/{run_id}").get_json()["data"]
        if status["status"] == "failed":
            final_payload = status
            break
        time.sleep(0.02)

    assert final_payload is not None
    assert final_payload["error_kind"] == "AudienceRunFailed"
    diagnostics = final_payload["diagnostics"]
    assert diagnostics["receipt"]["reliability_grade"] == "red"
    assert diagnostics["receipt"]["low_quality_persona_count"] == 8
    assert diagnostics["partial_counts"]["reactions"] == 11
    assert diagnostics["failures"][0]["error_kind"] == "low_quality_response"
    assert "SECRET_PRIVATE_TOPIC" not in json.dumps(final_payload)


def test_audience_request_logging_redacts_topic():
    app = create_app()
    client = app.test_client()
    logger = logging.getLogger("mirofish.request")
    logger.setLevel(logging.DEBUG)
    stream = StringIO()
    handler = logging.StreamHandler(stream)
    handler.setLevel(logging.DEBUG)
    logger.addHandler(handler)

    try:
        client.post(
            "/api/audience/runs/fake",
            json={
                "topic": "SECRET_PRIVATE_TOPIC should not appear in logs",
                "channel": "blog",
            },
        )
    finally:
        logger.removeHandler(handler)

    log_text = stream.getvalue()
    assert "SECRET_PRIVATE_TOPIC" not in log_text
    assert "redacted" in log_text

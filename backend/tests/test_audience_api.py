from __future__ import annotations

import json
import logging
import time
from io import StringIO

from app import create_app
from app.audience import AudienceRunFailed, AudienceRunManager, build_fake_audience_run, live_run_id


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
    assert len(data["reactions"]) == 20
    assert data["write_counts"]["reactions"] == 20

    stored = client.get(f"/api/audience/runs/{data['run_id']}").get_json()
    assert stored["success"] is True
    assert stored["data"]["status"] == "completed"
    assert stored["data"]["data"]["topic"]["title"] == "AI harnesses for PMs"
    assert stored["data"]["data"]["topic"]["cluster_label"] == "AI harnesses for PMs"
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

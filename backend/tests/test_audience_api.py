from __future__ import annotations

import logging
from io import StringIO

from app import create_app


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
    assert stored["data"]["topic"]["title"] == "AI harnesses for PMs"


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

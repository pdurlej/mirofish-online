from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from app.audience import (
    ACTIVE_PERSONA_COUNT,
    REQUIRED_SEGMENTS,
    AudienceRunInput,
    InMemoryAudienceGraphStore,
    ModelRouter,
    build_fake_audience_run,
    load_default_personas,
)


ROOT = Path(__file__).resolve().parents[2]


def test_default_personas_are_canonical_and_cover_segments():
    personas = load_default_personas()
    active = [persona for persona in personas if persona.active]

    assert len(active) == ACTIVE_PERSONA_COUNT
    assert len({persona.id for persona in active}) == ACTIVE_PERSONA_COUNT

    covered = {segment for persona in active for segment in persona.segments}
    assert REQUIRED_SEGMENTS <= covered


def test_model_router_is_seeded_and_records_attribution():
    persona = load_default_personas()[0]
    router = ModelRouter(model_pool=("model-a", "model-b"))

    first = router.assign(persona, "seed", "run-1")
    second = router.assign(persona, "seed", "run-1")
    retry = router.assign(persona, "seed", "run-1", high_quality_retry=True)

    assert first == second
    assert first.model in {"model-a", "model-b", persona.model_hint}
    assert retry.reason == "high_quality_retry"
    assert retry.model == "qwen3.5:397b-cloud"


def test_fake_audience_run_has_20_reactions_and_next_action():
    result = build_fake_audience_run(
        AudienceRunInput(
            topic="Should product managers care about AI harnesses?",
            channel="unknown",
            run_seed="test",
        )
    )

    assert len(result.personas) == 20
    assert len(result.reactions) == 20
    assert len(result.objections) == 20
    assert len(result.insights) >= 3
    assert result.recommendation["decision"] in {
        "publish",
        "rewrite",
        "narrow",
        "abandon",
        "ask_better_question",
    }
    assert result.recommendation["best_channel"]
    assert result.recommendation["next_action"]
    assert all("model_assignment" in persona for persona in result.personas)


def test_in_memory_graph_detects_previous_topic_similarity():
    store = InMemoryAudienceGraphStore()
    first = build_fake_audience_run(
        AudienceRunInput(
            topic="AI harnesses help product managers make reliable AI decisions",
            run_seed="a",
        )
    )
    store.write_run(first)

    second = build_fake_audience_run(
        AudienceRunInput(
            topic="Reliable AI decisions need product managers to use harnesses",
            run_seed="b",
        ),
        previous_topics=store.previous_topics(),
    )
    counts = store.write_run(second)

    assert counts["similarity_edges"] >= 1
    assert store.read_run(second.run_id)["topic"]["topic_hash"] == second.topic["topic_hash"]


def test_audience_graph_smoke_receipt_is_sanitized(tmp_path):
    output = tmp_path / "receipt.json"
    private_topic = "SECRET_PRIVATE_TOPIC should not appear in receipt"

    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "audience_graph_smoke.py"),
            "--topic",
            private_topic,
            "--channel",
            "linkedin",
            "--output",
            str(output),
        ],
        cwd=ROOT / "backend",
        check=True,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    assert "passed" in result.stdout
    receipt_text = output.read_text(encoding="utf-8")
    receipt = json.loads(receipt_text)
    assert receipt["status"] == "passed"
    assert receipt["counts"]["reactions"] == 20
    assert receipt["raw_topic_stored"] is False
    assert "SECRET_PRIVATE_TOPIC" not in receipt_text

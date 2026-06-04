from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from app.audience import (
    ACTIVE_PERSONA_COUNT,
    REQUIRED_SEGMENTS,
    AudienceRunInput,
    AudienceLiveRunner,
    InMemoryAudienceGraphStore,
    ModelRouter,
    build_fake_audience_run,
    load_default_personas,
)
from app.audience.live_runner import _parse_and_validate
from app.utils.llm_client import LLMChatResult


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
    assert retry.model == "qwen3.5:397b"


def test_model_router_normalizes_legacy_cloud_suffix(monkeypatch):
    monkeypatch.setenv("MIROFISH_AUDIENCE_MODEL_POOL", "glm-5.1:cloud,kimi-k2.6:cloud")
    persona = load_default_personas()[0]
    router = ModelRouter()

    assignment = router.assign(persona, "seed", "run-1")

    assert assignment.model in {"glm-5.1", "kimi-k2.6"}


def test_model_router_default_live_pool_is_deepseek_only():
    router = ModelRouter()

    assert router.model_pool == ("deepseek-v4-pro", "deepseek-v4-flash")


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
    history = store.list_runs()
    assert history[0]["run_id"] == second.run_id
    assert history[0]["reaction_count"] == 20


class FakeLLMClient:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail

    def chat_with_metadata(self, **kwargs):
        if self.fail:
            raise RuntimeError("SECRET_PRIVATE_TOPIC provider failure")
        return LLMChatResult(
            content=(
                '{"stance":"interested","channel_fit":"linkedin strong",'
                '"summary":"This angle is concrete enough for a product audience.",'
                '"objection":"Explain the buyer and practical consequence.",'
                '"objection_severity":"medium",'
                '"insight":"Frame the idea through a decision PMs already make.",'
                '"decision_impact":"rewrite around practical PM decisions"}'
            ),
            model=kwargs["model"],
            usage={"prompt_tokens": 10, "completion_tokens": 20, "total_tokens": 30},
            latency_ms=123,
            finish_reason="stop",
        )


def test_live_audience_runner_records_usage_and_receipt():
    runner = AudienceLiveRunner(client_factory=FakeLLMClient)
    result = runner.run(
        AudienceRunInput(
            topic="Should product managers care about AI harnesses?",
            channel="linkedin",
            run_seed="live-test",
        )
    )
    payload = result.to_dict()

    assert len(payload["reactions"]) == 20
    assert payload["receipt"]["mode"] == "live"
    assert payload["receipt"]["usage"]["total_tokens"] == 600
    assert payload["receipt"]["failed_persona_count"] == 0
    assert payload["receipt"]["reliability_grade"] == "green"


def test_live_runner_normalizes_loose_provider_json():
    parsed = _parse_and_validate(
        '{"reaction":"Wow, this is amazing!","sentiment":"positive"}'
    )

    assert parsed["stance"] == "interested"
    assert parsed["summary"] == "Wow, this is amazing!"
    assert parsed["objection"]
    assert parsed["decision_impact"]


def test_live_audience_runner_failure_threshold_does_not_leak_topic():
    runner = AudienceLiveRunner(
        client_factory=lambda: FakeLLMClient(fail=True),
        failure_threshold=0.05,
    )

    try:
        runner.run(AudienceRunInput(topic="SECRET_PRIVATE_TOPIC", run_seed="fail"))
    except Exception as exc:  # noqa: BLE001
        message = str(exc)
    else:
        raise AssertionError("expected failure")

    assert "SECRET_PRIVATE_TOPIC" not in message


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

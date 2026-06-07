from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

from app.audience import (
    ACTIVE_PERSONA_COUNT,
    REQUIRED_SEGMENTS,
    AudienceRunInput,
    AudienceRunFailed,
    AudienceLiveRunner,
    InMemoryAudienceGraphStore,
    ModelRouter,
    build_fake_audience_run,
    load_default_personas,
)
from app.audience.live_runner import (
    PersonaCallResult,
    _parse_and_validate,
    _recommendation_for,
    _reasoning_effort_for_model,
)
from app.audience.similarity import assign_topic_cluster, build_persona_memory, build_similarity_edges
from app.storage.embedding_service import EmbeddingError
from app.utils.llm_client import LLMChatResult


ROOT = Path(__file__).resolve().parents[2]
VALID_REACTION_JSON = (
    '{"stance":"interested","channel_fit":"linkedin strong",'
    '"summary":"This angle is concrete enough for a product audience.",'
    '"objection":"Explain the buyer and practical consequence.",'
    '"objection_severity":"medium",'
    '"insight":"Frame the idea through a decision PMs already make.",'
    '"decision_impact":"rewrite around practical PM decisions"}'
)


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
    assert retry.model == "deepseek-v4-pro"


def test_model_router_normalizes_legacy_cloud_suffix(monkeypatch):
    monkeypatch.setenv("MIROFISH_AUDIENCE_MODEL_POOL", "glm-5.1:cloud,kimi-k2.6:cloud")
    persona = load_default_personas()[0]
    router = ModelRouter()

    assignment = router.assign(persona, "seed", "run-1")

    assert assignment.model in {"glm-5.1", "kimi-k2.6"}


def test_model_router_default_live_pool_is_flash_only():
    router = ModelRouter()

    assert router.model_pool == ("deepseek-v4-flash",)


def test_deepseek_flash_uses_low_reasoning_effort():
    assert _reasoning_effort_for_model("deepseek-v4-flash") == "low"
    assert _reasoning_effort_for_model("deepseek-v4-pro") == "medium"


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
    assert second.similarity_edges[0]["target_title"] == first.topic["title"]
    assert second.similarity_edges[0]["method"] in {"lexical", "hybrid", "semantic"}
    assert store.read_run(second.run_id)["topic"]["topic_hash"] == second.topic["topic_hash"]
    history = store.list_runs()
    assert history[0]["run_id"] == second.run_id
    assert history[0]["reaction_count"] == 20
    assert history[0]["cluster_label"]
    assert history[0]["similar_topics"][0]["title"] == first.topic["title"]


def test_similarity_blocks_self_loop_for_same_topic_hash():
    topic = {
        "id": "topic-one",
        "topic_hash": "same-hash",
        "title": "AI workflow",
        "summary": "AI workflow for product managers",
        "channel": "blog",
    }

    edges = build_similarity_edges(topic, [topic | {"id": "topic-two"}])

    assert edges == []


def test_similarity_blocks_duplicate_title_even_with_new_hash():
    current = {
        "id": "topic-current",
        "topic_hash": "current-hash",
        "title": "Evals i ROI dla funkcji AI",
        "summary": "Jak udowodnic ROI funkcji AI w produkcie.",
        "channel": "podcast",
    }
    previous = current | {
        "id": "topic-previous",
        "topic_hash": "previous-hash",
        "summary": "Wczesniejszy run o tym samym tytule i podobnym temacie.",
    }

    edges = build_similarity_edges(current, [previous])

    assert edges == []


class SemanticEmbeddingProvider:
    def embed_batch(self, texts, batch_size=32):  # noqa: ANN001, ARG002
        return [self._vector(text) for text in texts]

    def _vector(self, text):  # noqa: ANN001
        normalized = text.lower()
        if "pricing" in normalized or "saas" in normalized or "packaging" in normalized:
            return [0.0, 1.0, 0.0]
        if "eudi" in normalized or "mobywatel" in normalized or "onboarding" in normalized:
            return [0.0, 0.0, 1.0]
        if "ai" in normalized or "evals" in normalized or "roi" in normalized or "agent" in normalized:
            return [1.0, 0.0, 0.0]
        return [0.0, 0.0, 0.0]


class RaisingEmbeddingProvider:
    def embed_batch(self, texts, batch_size=32):  # noqa: ANN001, ARG002
        raise EmbeddingError("embedding endpoint unavailable")


class SameEmbeddingProvider:
    def embed_batch(self, texts, batch_size=32):  # noqa: ANN001, ARG002
        return [[1.0, 0.0, 0.0] for _text in texts]


def test_semantic_similarity_links_ai_evals_to_ai_workflow():
    previous = {
        "id": "topic-ai-workflow",
        "topic_hash": "ai-workflow",
        "title": "AI-native PM workflow z agentami",
        "summary": "Jak product manager używa agentów do discovery, briefów i prototypów.",
        "channel": "blog",
        "cluster_id": "cluster-ai",
        "cluster_label": "AI-native PM workflow z agentami",
    }
    current = {
        "id": "topic-ai-evals",
        "topic_hash": "ai-evals",
        "title": "Evals i ROI dla funkcji AI",
        "summary": "Jak udowodnić, że funkcje AI działają i nie przepalają kosztu inference.",
        "channel": "podcast",
    }

    edges = build_similarity_edges(
        current,
        [previous],
        embedding_provider=SemanticEmbeddingProvider(),
    )

    assert len(edges) == 1
    assert edges[0]["target_title"] == previous["title"]
    assert edges[0]["semantic_score"] >= 0.68
    assert edges[0]["method"] in {"semantic", "hybrid"}


def test_semantic_similarity_requires_lexical_or_concept_overlap():
    current = {
        "id": "topic-pricing",
        "topic_hash": "pricing",
        "title": "Pricing polskiego SaaS",
        "summary": "Packaging, revenue i monetyzacja planow enterprise.",
        "channel": "linkedin",
    }
    previous = {
        "id": "topic-eudi",
        "topic_hash": "eudi",
        "title": "EUDI Wallet i mObywatel",
        "summary": "Onboarding, KYC i cyfrowa tozsamosc w produkcie.",
        "channel": "product-idea",
    }

    edges = build_similarity_edges(
        current,
        [previous],
        embedding_provider=SameEmbeddingProvider(),
        semantic_threshold=0.99,
    )

    assert edges == []


def test_control_topics_do_not_join_ai_cluster():
    ai_previous = {
        "id": "topic-ai-workflow",
        "topic_hash": "ai-workflow",
        "title": "AI-native PM workflow z agentami",
        "summary": "Jak product manager używa agentów do discovery, briefów i prototypów.",
        "channel": "blog",
        "cluster_id": "cluster-ai",
        "cluster_label": "AI-native PM workflow z agentami",
    }
    controls = [
        {
            "id": "topic-saas-pricing",
            "topic_hash": "saas-pricing",
            "title": "Pricing polskiego SaaS",
            "summary": "Packaging kontra wzrost revenue i monetyzacja planów.",
            "channel": "linkedin",
        },
        {
            "id": "topic-eudi-wallet",
            "topic_hash": "eudi-wallet",
            "title": "EUDI Wallet i mObywatel",
            "summary": "Nowy onboarding, KYC i cyfrowa tożsamość w produkcie.",
            "channel": "product-idea",
        },
    ]

    for control in controls:
        assert build_similarity_edges(
            control,
            [ai_previous],
            embedding_provider=SemanticEmbeddingProvider(),
        ) == []


def test_embedding_failure_falls_back_to_lexical_similarity():
    previous = {
        "id": "topic-ai-harnesses",
        "topic_hash": "ai-harnesses",
        "title": "AI harnesses for PMs",
        "summary": "AI harnesses help product managers make reliable AI decisions",
        "channel": "linkedin",
    }
    current = {
        "id": "topic-ai-decisions",
        "topic_hash": "ai-decisions",
        "title": "Reliable AI decisions",
        "summary": "Reliable AI decisions need product managers to use harnesses",
        "channel": "blog",
    }

    edges = build_similarity_edges(
        current,
        [previous],
        embedding_provider=RaisingEmbeddingProvider(),
    )

    assert len(edges) == 1
    assert edges[0]["method"] == "lexical"
    assert edges[0]["semantic_score"] is None


def test_topic_cluster_starts_singleton_then_joins_existing_cluster():
    first = {
        "id": "topic-first",
        "topic_hash": "first",
        "title": "AI-native PM workflow",
        "summary": "Agentic AI workflow for product managers",
        "channel": "blog",
    }
    assign_topic_cluster(first, [])

    second = {
        "id": "topic-second",
        "topic_hash": "second",
        "title": "Evals i ROI dla funkcji AI",
        "summary": "AI feature evals and ROI for product managers",
        "channel": "podcast",
    }
    edges = build_similarity_edges(
        second,
        [first],
        embedding_provider=SemanticEmbeddingProvider(),
    )
    assign_topic_cluster(second, edges)

    assert first["cluster_label"] == first["title"]
    assert second["cluster_id"] == first["cluster_id"]
    assert second["cluster_label"] == first["title"]


def test_reviewer_memory_counts_same_persona_on_related_topics():
    previous = {
        "id": "topic-ai-workflow",
        "topic_hash": "ai-workflow",
        "title": "AI workflow",
        "summary": "AI workflow for PMs",
        "channel": "blog",
        "reactions": [
            {
                "persona_id": "operator-pm",
                "summary": "AI workflow matters only if it changes a PM decision.",
            }
        ],
        "objections": [
            {
                "persona_id": "operator-pm",
                "text": "Show the product decision, not the AI theater.",
            }
        ],
    }
    personas = [{"id": "operator-pm"}, {"id": "founder-pm"}]
    edges = [
        {
            "target_topic_id": "topic-ai-workflow",
            "score": 0.9,
            "method": "semantic",
        }
    ]

    memory = build_persona_memory(personas, edges, [previous])

    operator_memory = next(item for item in memory if item["persona_id"] == "operator-pm")
    founder_memory = next(item for item in memory if item["persona_id"] == "founder-pm")
    assert operator_memory["related_topic_count"] == 1
    assert "product decision" in operator_memory["last_related_objection"]
    assert founder_memory["related_topic_count"] == 0


class FakeLLMClient:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail

    def chat_with_metadata(self, **kwargs):
        if self.fail:
            raise RuntimeError("SECRET_PRIVATE_TOPIC provider failure")
        return LLMChatResult(
            content=VALID_REACTION_JSON,
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


def test_live_runner_retries_invalid_json_with_high_quality_model():
    class InvalidJsonThenProClient:
        def chat_with_metadata(self, **kwargs):  # noqa: ANN001
            model = kwargs["model"]
            if model == "deepseek-v4-flash":
                return LLMChatResult(
                    content="not json",
                    model=model,
                    usage={"prompt_tokens": 1, "completion_tokens": 2, "total_tokens": 3},
                    latency_ms=10,
                    finish_reason="stop",
                )
            return LLMChatResult(
                content=VALID_REACTION_JSON,
                model=model,
                usage={"prompt_tokens": 10, "completion_tokens": 20, "total_tokens": 30},
                latency_ms=20,
                finish_reason="stop",
            )

    runner = AudienceLiveRunner(
        client_factory=InvalidJsonThenProClient,
        max_workers=1,
    )

    result = runner.run(
        AudienceRunInput(topic="Czy Agile ma jeszcze sens w 2026?", run_seed="retry-invalid"),
        personas=load_default_personas()[:1],
    )

    assert len(result.reactions) == 1
    assert result.reactions[0]["model"] == "deepseek-v4-pro"
    assert result.receipt["usage"]["total_tokens"] == 36
    assert result.receipt["models"]["deepseek-v4-flash"]["calls"] == 2
    assert result.receipt["models"]["deepseek-v4-flash"]["failures"] == 2
    assert result.receipt["models"]["deepseek-v4-pro"]["calls"] == 1
    assert result.receipt["schema_fallback_attempt_count"] == 1
    assert result.receipt["schema_fallback_count"] == 0
    assert result.receipt["high_quality_retry_count"] == 1
    assert result.receipt["high_quality_retry_success_count"] == 1
    assert result.receipt["failed_persona_count"] == 0


def test_live_runner_retries_low_quality_with_visible_receipt_count():
    class LowQualityThenProClient:
        def chat_with_metadata(self, **kwargs):  # noqa: ANN001
            model = kwargs["model"]
            if model == "deepseek-v4-flash":
                return LLMChatResult(
                    content='{"reaction":"Looks interesting.","sentiment":"positive"}',
                    model=model,
                    usage={"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
                    latency_ms=10,
                    finish_reason="stop",
                )
            return LLMChatResult(
                content=VALID_REACTION_JSON,
                model=model,
                usage={"prompt_tokens": 10, "completion_tokens": 20, "total_tokens": 30},
                latency_ms=20,
                finish_reason="stop",
            )

    runner = AudienceLiveRunner(
        client_factory=LowQualityThenProClient,
        max_workers=1,
    )

    result = runner.run(
        AudienceRunInput(topic="Czy Agile ma jeszcze sens w 2026?", run_seed="retry-low"),
        personas=load_default_personas()[:1],
    )

    assert len(result.reactions) == 1
    assert result.receipt["usage"]["total_tokens"] == 32
    assert result.receipt["low_quality_persona_count"] == 1
    assert result.receipt["models"]["deepseek-v4-flash"]["calls"] == 1
    assert result.receipt["models"]["deepseek-v4-flash"]["failures"] == 1
    assert result.receipt["models"]["deepseek-v4-pro"]["calls"] == 1
    assert result.receipt["high_quality_retry_count"] == 1
    assert result.receipt["high_quality_retry_success_count"] == 1
    assert result.receipt["failed_persona_count"] == 0


def test_live_recommendation_uses_channel_and_objection_for_polish_next_action():
    recommendation = _recommendation_for(
        AudienceRunInput(
            topic="Czego kogokolwiek obchodzi Scrum i Agile w 2026?",
            run_seed="recommendation",
        ),
        reactions=[
            {
                "stance": "curious",
                "channel_fit": "linkedin strong",
            }
        ],
        objections=[
            {
                "text": "Brakuje dowodów, że porzucenie frameworków prowadzi do lepszych rezultatów.",
                "severity": "medium",
            }
        ],
    )

    assert recommendation["decision"] == "narrow"
    assert recommendation["best_channel"] == "linkedin"
    assert "Zacznij od linkedin" in recommendation["next_action"]
    assert "Brakuje dowodów" in recommendation["next_action"]
    assert "szerokim pytaniem" in recommendation["rationale"]


def test_live_runner_normalizes_loose_provider_json():
    parsed = _parse_and_validate(
        '{"reaction":"Wow, this is amazing!","sentiment":"positive",'
        '"concern":"Explain what changes for Scrum teams in 2026."}'
    )

    assert parsed["stance"] == "interested"
    assert parsed["summary"] == "Wow, this is amazing!"
    assert parsed["objection"] == "Explain what changes for Scrum teams in 2026."
    assert parsed["decision_impact"]


def test_live_runner_marks_generic_fallback_objections_as_low_quality():
    class LowQualityLLMClient:
        def chat_with_metadata(self, **kwargs):  # noqa: ANN001
            return LLMChatResult(
                content='{"reaction":"Looks interesting.","sentiment":"positive"}',
                model=kwargs["model"],
                usage={"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
                latency_ms=10,
                finish_reason="stop",
            )

    personas = load_default_personas()[:2]
    runner = AudienceLiveRunner(
        client_factory=LowQualityLLMClient,
        failure_threshold=1.0,
        max_workers=2,
    )

    result = runner.run(
        AudienceRunInput(
            topic="Czy Scrum i Kanban nadal obchodzą product managerów w 2026?",
            run_seed="generic-fallback",
        ),
        personas=personas,
    )

    assert result.reactions == []
    assert result.receipt["failed_persona_count"] == 2
    assert result.receipt["low_quality_persona_count"] == 2
    assert result.receipt["reliability_grade"] == "red"
    assert {failure["error_kind"] for failure in result.failures} == {"low_quality_response"}


def test_live_audience_runner_failure_threshold_does_not_leak_topic():
    runner = AudienceLiveRunner(
        client_factory=lambda: FakeLLMClient(fail=True),
        failure_threshold=0.05,
    )

    try:
        runner.run(AudienceRunInput(topic="SECRET_PRIVATE_TOPIC", run_seed="fail"))
    except AudienceRunFailed as exc:
        message = str(exc)
        diagnostics = exc.diagnostics()
    else:
        raise AssertionError("expected failure")

    assert "SECRET_PRIVATE_TOPIC" not in message
    assert diagnostics["receipt"]["failed_persona_count"] == 20
    assert diagnostics["receipt"]["reliability_grade"] == "red"
    assert diagnostics["partial_counts"]["reactions"] == 0
    assert {failure["error_kind"] for failure in diagnostics["failures"]} == {"RuntimeError"}
    assert "SECRET_PRIVATE_TOPIC" not in json.dumps(diagnostics)


def test_live_audience_runner_times_out_slow_personas_without_hanging():
    personas = load_default_personas()[:2]
    slow_persona_id = personas[1].id

    class SlowOneRunner(AudienceLiveRunner):
        def _call_persona(self, run_input, persona, model):  # noqa: ANN001
            if persona.id == slow_persona_id:
                time.sleep(0.3)
            return PersonaCallResult(
                parsed={
                    "stance": "interested",
                    "channel_fit": "linkedin strong",
                    "summary": "This angle is concrete enough for a product audience.",
                    "objection": "Explain the buyer and practical consequence.",
                    "objection_severity": "medium",
                    "insight": "Frame the idea through a decision PMs already make.",
                    "decision_impact": "rewrite around practical PM decisions",
                },
                metadata=LLMChatResult(
                    content="{}",
                    model=model,
                    usage={"prompt_tokens": 10, "completion_tokens": 20, "total_tokens": 30},
                    latency_ms=123,
                    finish_reason="stop",
                ),
                schema_fallback_used=False,
            )

    runner = SlowOneRunner(
        failure_threshold=0.75,
        run_timeout_seconds=0.05,
        max_workers=2,
    )

    result = runner.run(
        AudienceRunInput(topic="Should PMs care about AI harnesses?", run_seed="timeout"),
        personas=personas,
    )

    assert len(result.reactions) == 1
    assert result.failures == [
        {
            "persona_id": slow_persona_id,
            "model": "deepseek-v4-flash",
            "error_kind": "run_timeout",
        }
    ]
    assert result.receipt["run_timed_out"] is True
    assert result.receipt["failed_persona_count"] == 1


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

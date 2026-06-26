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
    PERSONA_JSON_MAX_TOKENS,
    PersonaCallResult,
    _parse_and_validate,
    _recommendation_for,
    _reasoning_effort_for_model,
)
from app.audience.channel_fit import build_channel_scores, top_channel
from app.audience.graph_store import _neo4j_history_summary
from app.audience.research_snapshot import SyntheticResearchDataset, build_snapshot_run
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
    assert retry.model == "gemma4:31b"


def test_model_router_normalizes_legacy_cloud_suffix(monkeypatch):
    monkeypatch.setenv("MIROFISH_AUDIENCE_MODEL_POOL", "glm-5.1:cloud,kimi-k2.6:cloud")
    persona = load_default_personas()[0]
    router = ModelRouter()

    assignment = router.assign(persona, "seed", "run-1")

    assert assignment.model in {"glm-5.1", "kimi-k2.6"}


def test_model_router_default_live_pool_is_gemma4():
    router = ModelRouter()

    assert router.model_pool == ("gemma4:31b",)
    assert router.high_quality_retry_model == "gemma4:31b"


def test_neo4j_history_summary_uses_stored_channel_scores_payload():
    payload = build_fake_audience_run(
        AudienceRunInput(
            topic="Czy tanie modele są dobrym treningiem AI dla produktowca?",
            title="Tanie modele jako trening AI",
            channel="unknown",
            run_seed="history-channel",
        )
    ).to_dict()
    payload["recommendation"]["best_channel"] = "linkedin"
    payload["recommendation"]["decision_confidence"] = 0.72
    payload["recommendation"]["channel_scores"] = [
        {"channel": "linkedin", "label": "LinkedIn", "score": 75},
        {"channel": "product-idea", "label": "Product idea", "score": 41},
    ]

    summary = _neo4j_history_summary({"payload_json": json.dumps(payload)})

    assert summary["best_channel"] == "linkedin"
    assert summary["decision_confidence"] == 0.72
    assert summary["channel_scores"][0]["channel"] == "linkedin"
    assert summary["channel_scores"][0]["score"] == 75


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
    assert len(result.recommendation["channel_scores"]) == 5
    assert result.recommendation["channel_scores"][0]["score"] >= result.recommendation["channel_scores"][-1]["score"]
    assert result.recommendation["best_channel"] == top_channel(result.recommendation["channel_scores"])
    assert result.recommendation["next_action"]
    assert all("model_assignment" in persona for persona in result.personas)


def test_synthetic_research_snapshot_builds_standard_run_contract():
    dataset = _synthetic_research_dataset()
    candidate = dataset.candidates[0]

    result = build_snapshot_run(dataset, candidate)

    assert result.receipt["mode"] == "synthetic_research_snapshot"
    assert result.receipt["reliability_grade"] == "green"
    assert result.topic["title"] == "Koszt bledu AI"
    assert result.topic["branch"] == "ai-evals"
    assert len(result.personas) == 2
    assert len(result.reactions) == 2
    assert len(result.objections) == 2
    assert result.recommendation["decision"] in {
        "publish",
        "rewrite",
        "narrow",
        "abandon",
    }
    assert len(result.recommendation["channel_scores"]) == 5
    assert all("model_assignment" in persona for persona in result.personas)
    assert all(reaction["model"] == "agy:gemini-3.5-flash-low" for reaction in result.reactions)


def test_synthetic_research_snapshot_reuses_similarity_and_memory():
    dataset = _synthetic_research_dataset()
    store = InMemoryAudienceGraphStore()
    first = build_snapshot_run(dataset, dataset.candidates[0])
    store.write_run(first)

    second = build_snapshot_run(
        dataset,
        dataset.candidates[1],
        previous_topics=store.previous_topics(),
    )

    assert second.similarity_edges
    assert second.similarity_edges[0]["target_title"] == first.topic["title"]
    assert second.topic["cluster_label"] == first.topic["title"]
    assert any(item["related_topic_count"] == 1 for item in second.persona_memory)


def test_synthetic_research_snapshot_keeps_cross_branch_similarity_out_of_cluster():
    dataset = _synthetic_research_dataset()
    store = InMemoryAudienceGraphStore()
    first = build_snapshot_run(dataset, dataset.candidates[0])
    store.write_run(first)
    control_candidate = {
        "id": "T003",
        "title": "Dobre pytania PM-a",
        "topic": "Jak PM powinien zadawac dobre pytania o ryzyko produktu?",
        "channel": "linkedin",
        "branch": "control-non-ai",
        "avg_fit": 72,
        "controversy": 1,
        "support": 1,
        "import_reason": "test",
    }
    control_dataset = SyntheticResearchDataset(
        snapshot_id=dataset.snapshot_id,
        archetypes=dataset.archetypes,
        topics=[
            *dataset.topics,
            {
                "id": "T003",
                "title": "Dobre pytania PM-a",
                "question": "Jak PM powinien zadawac dobre pytania o ryzyko produktu?",
                "primary_channel": "linkedin",
                "branch": "control-non-ai",
            },
        ],
        candidates=[*dataset.candidates, control_candidate],
        responses=[
            *dataset.responses,
            {
                "t": "T003",
                "a": "A01",
                "fit": 72,
                "stance": 1,
                "ch": "linkedin",
                "risk": "NONE",
                "note": "PM risk wording overlaps, but this is not an AI evals branch.",
            },
            {
                "t": "T003",
                "a": "A02",
                "fit": 68,
                "stance": 0,
                "ch": "blog",
                "risk": "NONE",
                "note": "Good product thinking topic, separate from AI launch gates.",
            },
        ],
    )

    control = build_snapshot_run(
        control_dataset,
        control_candidate,
        previous_topics=store.previous_topics(),
    )

    assert control.similarity_edges
    assert control.topic["cluster_label"] == "Dobre pytania PM-a"


def test_channel_scores_rank_requested_practical_channel():
    scores = build_channel_scores(
        topic_text=(
            "Kontrowersyjny LinkedIn post dla product managerow o tym, "
            "czemu agile frameworki przegrywaja z rezultatami."
        ),
        title="Agile kontra rezultaty",
        requested_channel="linkedin",
        reactions=[
            {"channel_fit": "linkedin strong"},
            {"channel_fit": "linkedin strong"},
            {"channel_fit": "blog medium"},
        ],
        objections=[{"severity": "medium"}],
    )

    assert scores[0]["channel"] == "linkedin"
    assert scores[0]["score"] >= 70
    assert scores[0]["suggested_format"]


def _synthetic_research_dataset() -> SyntheticResearchDataset:
    archetypes = [
        {
            "id": "A01",
            "label": "Procurement Skeptic",
            "pl": "Sceptyk zakupowy",
            "lens": "cost and risk",
            "skepticism": 4,
        },
        {
            "id": "A02",
            "label": "AI Workflow Builder",
            "pl": "Budowniczy workflow AI",
            "lens": "AI workflow reliability",
            "skepticism": 2,
        },
    ]
    topics = [
        {
            "id": "T001",
            "title": "Koszt bledu AI",
            "question": "Jak PM powinien szacowac koszt blednej odpowiedzi AI?",
            "primary_channel": "linkedin",
            "branch": "ai-evals",
        },
        {
            "id": "T002",
            "title": "Quality gates dla AI launchu",
            "question": "Jakie quality gates powinny blokowac ryzykowny launch AI?",
            "primary_channel": "blog",
            "branch": "ai-evals",
        },
    ]
    responses = [
        {
            "t": "T001",
            "a": "A01",
            "fit": 74,
            "stance": 1,
            "ch": "linkedin",
            "risk": "COST",
            "note": "To ma sens, jesli pokazesz koszt pomylki i kto go ponosi.",
        },
        {
            "t": "T001",
            "a": "A02",
            "fit": 88,
            "stance": 2,
            "ch": "product-idea",
            "risk": "NONE",
            "note": "Dobry temat, bo wymusza konkretne progi jakosci dla AI.",
        },
        {
            "t": "T002",
            "a": "A01",
            "fit": 76,
            "stance": 1,
            "ch": "blog",
            "risk": "COST",
            "note": "Quality gate bez kosztu bledu bedzie tylko checklistą.",
        },
        {
            "t": "T002",
            "a": "A02",
            "fit": 91,
            "stance": 2,
            "ch": "product-idea",
            "risk": "NONE",
            "note": "Launch AI potrzebuje mierzalnych gateow i fallbackow.",
        },
    ]
    return SyntheticResearchDataset(
        snapshot_id="test-snapshot",
        archetypes=archetypes,
        topics=topics,
        candidates=[
            {
                "id": "T001",
                "title": "Koszt bledu AI",
                "topic": "Jak PM powinien szacowac koszt blednej odpowiedzi AI?",
                "channel": "linkedin",
                "branch": "ai-evals",
                "avg_fit": 81,
                "controversy": 1,
                "support": 1,
                "import_reason": "test",
            },
            {
                "id": "T002",
                "title": "Quality gates dla AI launchu",
                "topic": "Jakie quality gates powinny blokowac ryzykowny launch AI?",
                "channel": "blog",
                "branch": "ai-evals",
                "avg_fit": 83,
                "controversy": 1,
                "support": 1,
                "import_reason": "test",
            },
        ],
        responses=responses,
    )


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
    assert second.similarity_edges[0]["explanation"].startswith("Connected by")

    legacy_payload = second.to_dict()
    legacy_payload["similarity_edges"][0].pop("explanation", None)
    store._runs[second.run_id] = legacy_payload  # noqa: SLF001

    assert store.read_run(second.run_id)["topic"]["topic_hash"] == second.topic["topic_hash"]
    assert store.read_run(second.run_id)["similarity_edges"][0]["explanation"].startswith("Connected by")
    legacy_payload["similarity_edges"][0].pop("explanation", None)
    history = store.list_runs()
    assert history[0]["run_id"] == second.run_id
    assert history[0]["reaction_count"] == 20
    assert history[0]["cluster_label"]
    assert history[0]["similar_topics"][0]["title"] == first.topic["title"]
    assert history[0]["similar_topics"][0]["explanation"]


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


def test_similarity_ignores_batch_boilerplate_and_broad_pm_overlap_for_controls():
    ai_previous = {
        "id": "topic-ai-builder",
        "topic_hash": "ai-builder",
        "title": "Repair E2E AI workflow builder 20260607155649",
        "summary": "PM w Polsce uzywa AI do szybkiego prototypu zamiast kolejnego briefu.",
        "channel": "linkedin",
        "cluster_id": "cluster-ai",
        "cluster_label": "AI workflow",
    }
    control = {
        "id": "topic-eudi-control",
        "topic_hash": "eudi-control",
        "title": "Repair E2E EUDI wallet onboarding 20260607155649",
        "summary": "EUDI Wallet i cyfrowa tozsamosc jako onboarding: co musi zrozumiec PM.",
        "channel": "product-idea",
    }

    edges = build_similarity_edges(
        control,
        [ai_previous],
        embedding_provider=SameEmbeddingProvider(),
    )

    assert edges == []


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
    assert payload["receipt"]["reliability_grade"] == "red"
    assert payload["receipt"]["duplicate_objection_count"] == 19
    assert payload["receipt"]["max_duplicate_objections"] == 20
    assert payload["receipt"]["quality_warnings"][0]["kind"] == "duplicate_objections"


def test_live_runner_records_model_routing_in_receipt():
    runner = AudienceLiveRunner(
        client_factory=FakeLLMClient,
        model_router=ModelRouter(
            model_pool=("gemma4:31b",),
            high_quality_retry_model="gemma4:31b",
        ),
    )

    result = runner.run(
        AudienceRunInput(
            topic="Should product managers care about AI harnesses?",
            channel="linkedin",
            run_seed="model-routing-receipt",
        ),
        personas=load_default_personas()[:1],
    )

    routing = result.receipt["model_routing"]
    assert routing["model_pool"] == ["gemma4:31b"]
    assert routing["high_quality_retry_model"] == "gemma4:31b"
    assert routing["failure_threshold"] == 0.30
    assert routing["max_workers"] == 10
    assert result.reactions[0]["model"] == "gemma4:31b"


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
        model_router=ModelRouter(
            model_pool=("deepseek-v4-flash",),
            high_quality_retry_model="deepseek-v4-pro",
        ),
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
    assert result.receipt["persona_repair_retry_count"] == 1
    assert result.receipt["persona_repair_retry_failure_count"] == 1
    assert result.receipt["high_quality_retry_count"] == 1
    assert result.receipt["high_quality_retry_success_count"] == 1
    assert result.receipt["failed_persona_count"] == 0


def test_live_runner_uses_larger_json_budget_for_schema_and_repair_calls():
    class CaptureBudgetClient:
        def __init__(self) -> None:
            self.max_tokens: list[int] = []

        def chat_with_metadata(self, **kwargs):  # noqa: ANN001
            self.max_tokens.append(int(kwargs["max_tokens"]))
            if len(self.max_tokens) == 1:
                return LLMChatResult(
                    content="{not valid json",
                    model=kwargs["model"],
                    usage={"prompt_tokens": 1, "completion_tokens": 450, "total_tokens": 451},
                    latency_ms=10,
                    finish_reason="length",
                )
            return LLMChatResult(
                content=VALID_REACTION_JSON,
                model=kwargs["model"],
                usage={"prompt_tokens": 10, "completion_tokens": 20, "total_tokens": 30},
                latency_ms=20,
                finish_reason="stop",
            )

    client = CaptureBudgetClient()
    runner = AudienceLiveRunner(client_factory=lambda: client, max_workers=1)

    result = runner.run(
        AudienceRunInput(topic="Czy PM powinien rozumieć CI/CD?", run_seed="json-budget"),
        personas=load_default_personas()[:1],
    )

    assert len(result.reactions) == 1
    assert client.max_tokens == [PERSONA_JSON_MAX_TOKENS, PERSONA_JSON_MAX_TOKENS]
    assert PERSONA_JSON_MAX_TOKENS >= 900


def test_live_runner_repairs_malformed_persona_json_before_high_quality_retry():
    class MalformedJsonThenRepairClient:
        def __init__(self) -> None:
            self.calls = 0

        def chat_with_metadata(self, **kwargs):  # noqa: ANN001
            self.calls += 1
            if self.calls == 1:
                return LLMChatResult(
                    content="{not valid json",
                    model=kwargs["model"],
                    usage={"prompt_tokens": 1, "completion_tokens": 2, "total_tokens": 3},
                    latency_ms=10,
                    finish_reason="stop",
                )
            return LLMChatResult(
                content=VALID_REACTION_JSON,
                model=kwargs["model"],
                usage={"prompt_tokens": 10, "completion_tokens": 20, "total_tokens": 30},
                latency_ms=20,
                finish_reason="stop",
            )

    runner = AudienceLiveRunner(
        client_factory=MalformedJsonThenRepairClient,
        max_workers=1,
    )

    result = runner.run(
        AudienceRunInput(topic="Czy Agile ma jeszcze sens w 2026?", run_seed="repair-invalid"),
        personas=load_default_personas()[:1],
    )

    assert len(result.reactions) == 1
    assert result.reactions[0]["model"] == "gemma4:31b"
    assert result.receipt["usage"]["total_tokens"] == 33
    assert result.receipt["models"]["gemma4:31b"]["calls"] == 2
    assert result.receipt["models"]["gemma4:31b"]["failures"] == 1
    assert result.receipt["schema_fallback_attempt_count"] == 1
    assert result.receipt["schema_fallback_count"] == 1
    assert result.receipt["persona_repair_retry_count"] == 1
    assert result.receipt["persona_repair_retry_success_count"] == 1
    assert result.receipt["persona_repair_retry_failure_count"] == 0
    assert result.receipt["high_quality_retry_count"] == 0
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
        model_router=ModelRouter(
            model_pool=("deepseek-v4-flash",),
            high_quality_retry_model="deepseek-v4-pro",
        ),
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
    assert recommendation["channel_scores"][0]["channel"] == "linkedin"
    assert recommendation["channel_scores"][0]["score"] >= 50
    assert "Zacznij od linkedin" in recommendation["next_action"]
    assert "Brakuje dowodów" in recommendation["next_action"]
    assert "szerokim pytaniem" in recommendation["rationale"]


def test_live_recommendation_can_publish_question_when_audience_signal_is_strong():
    recommendation = _recommendation_for(
        AudienceRunInput(
            topic=(
                "Czy PM powinien projektować workflow agentów AI, jeśli ma jasny przykład "
                "wpływu na decyzje discovery i delivery?"
            ),
            title="PM jako projektant workflow agentów AI",
            run_seed="recommendation-publish",
        ),
        reactions=[
            {
                "stance": "interested" if index < 12 else "curious",
                "channel_fit": "linkedin strong" if index < 14 else "blog medium",
            }
            for index in range(20)
        ],
        objections=[
            {
                "text": "Pokaż jeden konkretny przykład wpływu na decyzję PM-a.",
                "severity": "medium",
            }
            for _ in range(20)
        ],
    )

    assert recommendation["decision"] == "publish"
    assert recommendation["action_scorecard"][0]["decision"] == "publish"
    assert recommendation["decision_confidence"] > 0.4


def test_live_recommendation_rewrites_when_skepticism_and_high_objections_dominate():
    recommendation = _recommendation_for(
        AudienceRunInput(
            topic="Czy każdy PM musi znać observability, CI/CD i evale AI?",
            title="PM i techniczny ciężar AI delivery",
            run_seed="recommendation-rewrite",
        ),
        reactions=[
            {
                "stance": "skeptical" if index < 10 else "needs_translation" if index < 16 else "curious",
                "channel_fit": "linkedin weak" if index < 12 else "blog medium",
            }
            for index in range(20)
        ],
        objections=[
            {
                "text": "To miesza odpowiedzialność PM-a z pracą engineeringu bez jasnej granicy.",
                "severity": "high" if index < 8 else "medium",
            }
            for index in range(20)
        ],
    )

    assert recommendation["decision"] == "rewrite"
    assert recommendation["action_scorecard"][0]["decision"] == "rewrite"
    assert recommendation["action_scorecard"][0]["score"] > recommendation["action_scorecard"][1]["score"]


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
            "model": "gemma4:31b",
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

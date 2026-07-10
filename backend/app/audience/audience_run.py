"""Audience run contracts and deterministic fake runner."""

from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from .channel_fit import (
    CHANNELS as FIT_CHANNELS,
    build_channel_scores,
    channel_scores_source,
    top_channel,
)
from .model_router import ModelRouter
from .personas import AudiencePersona, load_default_personas
from .similarity import assign_topic_cluster, build_persona_memory, build_similarity_edges


CHANNELS = {"podcast", "linkedin", "blog", "twitter-x", "product-idea", "unknown"}
RECOMMENDATIONS = {"publish", "rewrite", "narrow", "abandon", "ask_better_question"}


@dataclass(frozen=True)
class AudienceRunInput:
    topic: str
    channel: str = "unknown"
    title: str | None = None
    run_seed: str = "default"

    def __post_init__(self) -> None:
        if not self.topic.strip():
            raise ValueError("topic is required")
        if self.channel not in CHANNELS:
            raise ValueError(f"Unsupported channel: {self.channel}")

    @property
    def topic_hash(self) -> str:
        return hashlib.sha256(self.topic.encode("utf-8")).hexdigest()

    @property
    def display_title(self) -> str:
        if self.title and self.title.strip():
            return self.title.strip()
        words = self.topic.split()
        return " ".join(words[:12])


@dataclass(frozen=True)
class AudienceRunResult:
    run_id: str
    created_at: str
    topic: dict[str, Any]
    personas: list[dict[str, Any]]
    reactions: list[dict[str, Any]]
    objections: list[dict[str, Any]]
    insights: list[dict[str, Any]]
    recommendation: dict[str, Any]
    similarity_edges: list[dict[str, Any]]
    persona_memory: list[dict[str, Any]] | None = None
    receipt: dict[str, Any] | None = None
    failures: list[dict[str, Any]] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "created_at": self.created_at,
            "topic": self.topic,
            "personas": self.personas,
            "reactions": self.reactions,
            "objections": self.objections,
            "insights": self.insights,
            "recommendation": self.recommendation,
            "similarity_edges": self.similarity_edges,
            "persona_memory": self.persona_memory or [],
            "receipt": self.receipt or _empty_receipt(),
            "failures": self.failures or [],
        }


def build_fake_audience_run(
    run_input: AudienceRunInput,
    *,
    personas: list[AudiencePersona] | None = None,
    model_router: ModelRouter | None = None,
    previous_topics: list[dict[str, Any]] | None = None,
) -> AudienceRunResult:
    active_personas = personas or load_default_personas()
    router = model_router or ModelRouter()
    run_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"{run_input.topic_hash}:{run_input.run_seed}"))
    created_at = datetime.now(timezone.utc).isoformat()

    topic = {
        "id": f"topic-{run_input.topic_hash[:16]}",
        "title": run_input.display_title,
        "channel": run_input.channel,
        "topic_hash": run_input.topic_hash,
        "summary": _structured_summary(run_input.topic),
    }

    persona_payloads: list[dict[str, Any]] = []
    reactions: list[dict[str, Any]] = []
    objections: list[dict[str, Any]] = []
    insights: list[dict[str, Any]] = []

    for persona in active_personas:
        assignment = router.assign(persona, run_input.run_seed, run_id)
        persona_payloads.append(persona.to_dict() | {"model_assignment": assignment.to_dict()})
        stance = _stance_for(persona, run_input.topic)
        reaction_id = f"reaction-{run_id[:8]}-{persona.id}"
        reactions.append(
            {
                "id": reaction_id,
                "persona_id": persona.id,
                "stance": stance,
                "channel_fit": _channel_fit(persona, run_input.channel),
                "channel_scores": _fake_persona_channel_scores(persona),
                "model": assignment.model,
                "summary": _reaction_summary(persona, run_input),
            }
        )
        objections.append(
            {
                "id": f"objection-{run_id[:8]}-{persona.id}",
                "persona_id": persona.id,
                "text": persona.objections[0],
                "severity": "high" if persona.skepticism >= 0.75 else "medium",
            }
        )

    insights.extend(_insights_for(run_input, active_personas))
    objections.sort(key=lambda objection: 0 if objection["severity"] == "high" else 1)
    if objections:
        objections[0]["drives_next_action"] = True
    channel_scores = build_channel_scores(
        topic_text=run_input.topic,
        title=run_input.display_title,
        requested_channel=run_input.channel,
        personas=[persona.to_dict() for persona in active_personas],
        reactions=reactions,
        objections=objections,
    )
    recommendation = {
        "decision": _recommendation_for(run_input, active_personas),
        "best_channel": top_channel(channel_scores),
        "channel_scores": channel_scores,
        "channel_scores_source": channel_scores_source(reactions),
        "requested_channel": run_input.channel,
        "primary_objection_id": objections[0]["id"] if objections else None,
        "next_action": _next_action_for(run_input),
        "rationale": (
            "Fake deterministic run: use this contract to validate graph/UI flow "
            "before live LLM audience calls."
        ),
    }
    previous = previous_topics or []
    similarity_edges = build_similarity_edges(topic, previous)
    assign_topic_cluster(topic, similarity_edges)
    persona_memory = build_persona_memory(persona_payloads, similarity_edges, previous)

    return AudienceRunResult(
        run_id=run_id,
        created_at=created_at,
        topic=topic,
        personas=persona_payloads,
        reactions=reactions,
        objections=objections,
        insights=insights,
        recommendation=recommendation,
        similarity_edges=similarity_edges,
        persona_memory=persona_memory,
    )


def _structured_summary(topic: str) -> str:
    return " ".join(topic.strip().split())[:480]


def _stance_for(persona: AudiencePersona, topic: str) -> str:
    text = topic.lower()
    if "ai" in text or "agent" in text or "harness" in text:
        if "ai-platform-devtools" in persona.segments:
            return "interested"
        if "skeptical-generalists" in persona.segments:
            return "needs_translation"
    if persona.skepticism >= 0.8:
        return "skeptical"
    return "curious"


def _channel_fit(persona: AudiencePersona, channel: str) -> str:
    if channel == "unknown":
        return persona.channel_preferences[0]
    if channel in persona.channel_preferences:
        return "strong"
    return "weak"


def _fake_persona_channel_scores(persona: AudiencePersona) -> dict[str, int]:
    preferences = list(persona.channel_preferences)
    return {
        channel: max(20, 82 - preferences.index(channel) * 12)
        if channel in preferences
        else 38
        for channel in FIT_CHANNELS
    }


def _reaction_summary(persona: AudiencePersona, run_input: AudienceRunInput) -> str:
    goal = persona.goals[0]
    objection = persona.objections[0]
    return (
        f"{persona.name} evaluates '{run_input.display_title}' through the goal "
        f"'{goal}' and asks: {objection}"
    )


def _insights_for(
    run_input: AudienceRunInput,
    personas: list[AudiencePersona],
) -> list[dict[str, Any]]:
    technical = [
        persona.id for persona in personas if "ai-platform-devtools" in persona.segments
    ]
    skeptical = [
        persona.id for persona in personas if "skeptical-generalists" in persona.segments
    ]
    return [
        {
            "id": "insight-technical-niche",
            "text": "AI/platform/devtools personas need concrete reliability framing.",
            "persona_ids": technical[:5],
        },
        {
            "id": "insight-jargon-risk",
            "text": "Skeptical generalists need jargon translated into product outcomes.",
            "persona_ids": skeptical[:5],
        },
        {
            "id": "insight-channel-fit",
            "text": f"The requested channel '{run_input.channel}' should be checked against persona preferences.",
            "persona_ids": [persona.id for persona in personas[:5]],
        },
    ]


def _recommendation_for(
    run_input: AudienceRunInput,
    personas: list[AudiencePersona],
) -> str:
    topic = run_input.topic.lower()
    if "?" in run_input.topic or "czy" in topic:
        return "narrow"
    if sum(1 for persona in personas if persona.skepticism >= 0.8) >= 3:
        return "rewrite"
    return "publish"


def _best_channel_for(run_input: AudienceRunInput, personas: list[AudiencePersona]) -> str:
    if run_input.channel != "unknown":
        return run_input.channel
    counts: dict[str, int] = {}
    for persona in personas:
        for channel in persona.channel_preferences:
            counts[channel] = counts.get(channel, 0) + 1
    return max(counts, key=counts.get)


def _next_action_for(run_input: AudienceRunInput) -> str:
    if run_input.channel == "unknown":
        return "Choose the channel before drafting the final version."
    return "Rewrite the topic around the strongest audience objection."


def _empty_receipt() -> dict[str, Any]:
    return {
        "mode": "fake",
        "pricing": "unknown",
        "models": {},
        "usage": {
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
        },
        "latency_ms": 0,
        "schema_fallback_count": 0,
        "failed_persona_count": 0,
        "failure_rate": 0.0,
        "reliability_grade": "test",
    }

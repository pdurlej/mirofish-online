"""Live 20-person audience runner with sanitized receipts."""

from __future__ import annotations

import json
import re
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable

from ..utils.llm_client import LLMClient, LLMChatResult, validate_json_schema
from .audience_run import AudienceRunInput, AudienceRunResult
from .model_router import ModelRouter
from .personas import AudiencePersona, load_default_personas


REACTION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": [
        "stance",
        "channel_fit",
        "summary",
        "objection",
        "objection_severity",
        "insight",
        "decision_impact",
    ],
    "properties": {
        "stance": {
            "type": "string",
            "enum": ["interested", "curious", "skeptical", "needs_translation"],
        },
        "channel_fit": {"type": "string", "minLength": 3},
        "summary": {"type": "string", "minLength": 12},
        "objection": {"type": "string", "minLength": 8},
        "objection_severity": {
            "type": "string",
            "enum": ["low", "medium", "high"],
        },
        "insight": {"type": "string", "minLength": 12},
        "decision_impact": {"type": "string", "minLength": 8},
    },
}


class AudienceRunFailed(RuntimeError):
    """Raised when a live run crosses the controlled-failure threshold."""


@dataclass(frozen=True)
class PersonaCallResult:
    parsed: dict[str, Any]
    metadata: LLMChatResult
    schema_fallback_used: bool


class AudienceLiveRunner:
    def __init__(
        self,
        *,
        client_factory: Callable[[], LLMClient] | None = None,
        model_router: ModelRouter | None = None,
        failure_threshold: float = 0.30,
    ) -> None:
        self._client_factory = client_factory or LLMClient
        self._model_router = model_router or ModelRouter()
        self._failure_threshold = failure_threshold

    def run(
        self,
        run_input: AudienceRunInput,
        *,
        personas: list[AudiencePersona] | None = None,
        previous_topics: list[dict[str, Any]] | None = None,
    ) -> AudienceRunResult:
        started = time.monotonic()
        active_personas = personas or load_default_personas()
        run_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"live:{run_input.topic_hash}:{run_input.run_seed}"))
        created_at = datetime.now(timezone.utc).isoformat()

        topic = {
            "id": f"topic-{run_input.topic_hash[:16]}",
            "title": run_input.display_title,
            "channel": run_input.channel,
            "topic_hash": run_input.topic_hash,
            "summary": _structured_summary(run_input.topic),
        }
        personas_payload: list[dict[str, Any]] = []
        reactions: list[dict[str, Any]] = []
        objections: list[dict[str, Any]] = []
        insights: list[dict[str, Any]] = []
        failures: list[dict[str, Any]] = []
        receipt = _empty_live_receipt()

        for persona in active_personas:
            assignment = self._model_router.assign(persona, run_input.run_seed, run_id)
            personas_payload.append(persona.to_dict() | {"model_assignment": assignment.to_dict()})
            try:
                call = self._call_persona(run_input, persona, assignment.model)
                parsed = call.parsed
                receipt["schema_fallback_count"] += int(call.schema_fallback_used)
                _record_usage(receipt, call.metadata)
                reactions.append(
                    {
                        "id": f"reaction-{run_id[:8]}-{persona.id}",
                        "persona_id": persona.id,
                        "stance": parsed["stance"],
                        "channel_fit": parsed["channel_fit"],
                        "model": call.metadata.model,
                        "summary": parsed["summary"],
                    }
                )
                objections.append(
                    {
                        "id": f"objection-{run_id[:8]}-{persona.id}",
                        "persona_id": persona.id,
                        "text": parsed["objection"],
                        "severity": parsed["objection_severity"],
                    }
                )
                insights.append(
                    {
                        "id": f"insight-{run_id[:8]}-{persona.id}",
                        "text": parsed["insight"],
                        "persona_ids": [persona.id],
                    }
                )
            except Exception as exc:  # noqa: BLE001
                failures.append(
                    {
                        "persona_id": persona.id,
                        "model": assignment.model,
                        "error_kind": _sanitized_error_kind(exc),
                    }
                )
                _record_failure(receipt, assignment.model)
                if len(failures) / len(active_personas) > self._failure_threshold:
                    raise AudienceRunFailed("failure_threshold_exceeded") from exc

        receipt["latency_ms"] = int((time.monotonic() - started) * 1000)
        receipt["failed_persona_count"] = len(failures)
        receipt["failure_rate"] = round(len(failures) / len(active_personas), 3)
        receipt["reliability_grade"] = _reliability_grade(receipt["failure_rate"])

        return AudienceRunResult(
            run_id=run_id,
            created_at=created_at,
            topic=topic,
            personas=personas_payload,
            reactions=reactions,
            objections=objections,
            insights=_select_insights(insights),
            recommendation=_recommendation_for(run_input, reactions, objections),
            similarity_edges=_similarity_edges(topic, previous_topics or []),
            receipt=receipt,
            failures=failures,
        )

    def _call_persona(
        self,
        run_input: AudienceRunInput,
        persona: AudiencePersona,
        model: str,
    ) -> PersonaCallResult:
        client = self._client_factory()
        messages = _persona_messages(run_input, persona)
        response_format = {
            "type": "json_schema",
            "json_schema": {
                "name": "mirofish_audience_reaction",
                "strict": True,
                "schema": REACTION_SCHEMA,
            },
        }
        try:
            result = client.chat_with_metadata(
                messages=messages,
                temperature=0.45,
                max_tokens=900,
                response_format=response_format,
                model=model,
                reasoning_effort="medium",
            )
            parsed = _parse_and_validate(result.content)
            return PersonaCallResult(parsed, result, False)
        except Exception as exc:
            if not _looks_like_schema_retry(exc):
                raise

        result = client.chat_with_metadata(
            messages=[
                {
                    "role": "system",
                    "content": (
                        "Return only valid JSON matching this schema. "
                        "No markdown, no commentary.\n"
                        f"{json.dumps(REACTION_SCHEMA, ensure_ascii=False)}"
                    ),
                },
                *messages,
            ],
            temperature=0.35,
            max_tokens=900,
            response_format={"type": "json_object"},
            model=model,
            reasoning_effort="medium",
        )
        return PersonaCallResult(_parse_and_validate(result.content), result, True)


def _persona_messages(run_input: AudienceRunInput, persona: AudiencePersona) -> list[dict[str, str]]:
    return [
        {
            "role": "system",
            "content": (
                "You are one synthetic audience persona in Piotr Durlej's private "
                "content/product thinking panel. Answer as this persona only. "
                "Be concrete, skeptical when appropriate, and return only JSON."
            ),
        },
        {
            "role": "user",
            "content": (
                f"Persona name: {persona.name}\n"
                f"Segments: {', '.join(persona.segments)}\n"
                f"Goals: {'; '.join(persona.goals)}\n"
                f"Known objections: {'; '.join(persona.objections)}\n"
                f"Channel preferences: {', '.join(persona.channel_preferences)}\n"
                f"Skepticism: {persona.skepticism}\n\n"
                f"Candidate channel: {run_input.channel}\n"
                f"Title: {run_input.display_title}\n"
                f"Topic/draft:\n{run_input.topic}\n\n"
                "Judge whether this should become a podcast, LinkedIn post, blog, "
                "Twitter/X post, product idea, or be narrowed/rewritten."
            ),
        },
    ]


def _parse_and_validate(content: str) -> dict[str, Any]:
    cleaned = content.strip()
    cleaned = re.sub(r"^```(?:json)?\s*\n?", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\n?```\s*$", "", cleaned).strip()
    try:
        parsed = json.loads(cleaned)
    except json.JSONDecodeError:
        start = cleaned.find("{")
        if start < 0:
            raise ValueError("invalid_json")
        parsed, _ = json.JSONDecoder().raw_decode(cleaned[start:])
    error = validate_json_schema(parsed, REACTION_SCHEMA)
    if error:
        path, message = error
        raise ValueError(f"schema_error:{path}:{message}")
    return parsed


def _empty_live_receipt() -> dict[str, Any]:
    return {
        "mode": "live",
        "pricing": "unknown",
        "models": {},
        "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
        "latency_ms": 0,
        "schema_fallback_count": 0,
        "failed_persona_count": 0,
        "failure_rate": 0.0,
        "reliability_grade": "unknown",
    }


def _record_usage(receipt: dict[str, Any], metadata: LLMChatResult) -> None:
    model = metadata.model
    model_entry = receipt["models"].setdefault(
        model,
        {
            "calls": 0,
            "failures": 0,
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
            "latency_ms": 0,
        },
    )
    model_entry["calls"] += 1
    model_entry["latency_ms"] += metadata.latency_ms
    for key in ("prompt_tokens", "completion_tokens", "total_tokens"):
        value = int(metadata.usage.get(key) or 0)
        model_entry[key] += value
        receipt["usage"][key] += value


def _record_failure(receipt: dict[str, Any], model: str) -> None:
    model_entry = receipt["models"].setdefault(
        model,
        {
            "calls": 0,
            "failures": 0,
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
            "latency_ms": 0,
        },
    )
    model_entry["calls"] += 1
    model_entry["failures"] += 1


def _recommendation_for(
    run_input: AudienceRunInput,
    reactions: list[dict[str, Any]],
    objections: list[dict[str, Any]],
) -> dict[str, Any]:
    skeptical = sum(1 for reaction in reactions if reaction["stance"] in {"skeptical", "needs_translation"})
    high_objections = sum(1 for objection in objections if objection["severity"] == "high")
    if skeptical >= 8:
        decision = "rewrite"
    elif high_objections >= 6 or "?" in run_input.topic:
        decision = "narrow"
    else:
        decision = "publish"
    return {
        "decision": decision,
        "best_channel": run_input.channel if run_input.channel != "unknown" else _best_channel(reactions),
        "next_action": _next_action(decision),
        "rationale": (
            f"Live 20-person audience run: {skeptical} skeptical/translation-needed "
            f"reactions and {high_objections} high-severity objections."
        ),
    }


def _best_channel(reactions: list[dict[str, Any]]) -> str:
    counts: dict[str, int] = {}
    for reaction in reactions:
        value = str(reaction.get("channel_fit") or "unknown").lower()
        for channel in ("podcast", "linkedin", "blog", "twitter-x", "product-idea"):
            if channel in value:
                counts[channel] = counts.get(channel, 0) + 1
    return max(counts, key=counts.get) if counts else "unknown"


def _next_action(decision: str) -> str:
    if decision == "publish":
        return "Draft the strongest version and keep the top objections visible."
    if decision == "rewrite":
        return "Rewrite the idea around the clearest audience value, not the tooling."
    if decision == "narrow":
        return "Narrow the question and test one sharper angle next."
    if decision == "abandon":
        return "Park this idea unless new evidence appears."
    return "Ask a better question before choosing a channel."


def _select_insights(insights: list[dict[str, Any]], limit: int = 8) -> list[dict[str, Any]]:
    return insights[:limit]


def _similarity_edges(
    topic: dict[str, Any],
    previous_topics: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    current_terms = set(topic["summary"].lower().split())
    edges = []
    for previous in previous_topics:
        previous_terms = set(str(previous.get("summary", "")).lower().split())
        if not previous_terms:
            continue
        overlap = len(current_terms & previous_terms) / max(len(current_terms), 1)
        if overlap >= 0.2:
            edges.append(
                {
                    "source_topic_id": topic["id"],
                    "target_topic_id": previous.get("id"),
                    "relationship": "similar_to",
                    "score": round(overlap, 3),
                }
            )
    return edges


def _structured_summary(topic: str) -> str:
    return " ".join(topic.strip().split())[:480]


def _reliability_grade(failure_rate: float) -> str:
    if failure_rate == 0:
        return "green"
    if failure_rate <= 0.15:
        return "yellow"
    return "red"


def _looks_like_schema_retry(exc: Exception) -> bool:
    text = str(exc).lower()
    return (
        "response_format" in text
        or "json_schema" in text
        or "unsupported" in text
        or "not support" in text
        or "invalid_json" in text
        or "schema_error" in text
    )


def _sanitized_error_kind(exc: Exception) -> str:
    if isinstance(exc, ValueError) and str(exc).startswith("schema_error"):
        return "schema_validation_failed"
    if isinstance(exc, ValueError) and str(exc) == "invalid_json":
        return "invalid_json"
    return type(exc).__name__

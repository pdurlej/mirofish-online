"""Live 20-person audience runner with sanitized receipts."""

from __future__ import annotations

import json
import re
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError, as_completed
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable

from ..utils.llm_client import LLMClient, LLMChatResult, validate_json_schema
from .audience_run import AudienceRunInput, AudienceRunResult
from .channel_fit import build_channel_scores, top_channel
from .model_router import ModelRouter
from .personas import AudiencePersona, load_default_personas
from .similarity import (
    EmbeddingProvider,
    assign_topic_cluster,
    build_persona_memory,
    build_similarity_edges,
)


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

    def __init__(
        self,
        message: str,
        *,
        receipt: dict[str, Any] | None = None,
        failures: list[dict[str, Any]] | None = None,
        partial_counts: dict[str, int] | None = None,
    ) -> None:
        super().__init__(message)
        self.receipt = receipt or {}
        self.failures = failures or []
        self.partial_counts = partial_counts or {}

    def diagnostics(self) -> dict[str, Any]:
        return {
            "receipt": self.receipt,
            "failures": self.failures,
            "partial_counts": self.partial_counts,
        }


@dataclass(frozen=True)
class PersonaAttempt:
    model: str
    metadata: LLMChatResult | None
    error_kind: str | None
    schema_fallback: bool = False
    high_quality_retry: bool = False


class PersonaCallFailed(RuntimeError):
    def __init__(
        self,
        error_kind: str,
        *,
        attempts: list[PersonaAttempt] | None = None,
        high_quality_retry_used: bool = False,
    ) -> None:
        super().__init__(error_kind)
        self.error_kind = error_kind
        self.attempts = attempts or []
        self.high_quality_retry_used = high_quality_retry_used


@dataclass(frozen=True)
class PersonaCallResult:
    parsed: dict[str, Any]
    metadata: LLMChatResult
    schema_fallback_used: bool
    attempts: tuple[PersonaAttempt, ...] = ()
    high_quality_retry_used: bool = False


GENERIC_OBJECTION_FALLBACKS = {
    "this needs a clearer practical consequence.",
    "this needs a clearer practical consequence for the audience.",
}
MAX_GREEN_DUPLICATE_OBJECTION_COUNT = 2
MAX_YELLOW_DUPLICATE_OBJECTION_COUNT = 4
RETRYABLE_PERSONA_ERRORS = {
    "invalid_json",
    "schema_validation_failed",
    "low_quality_response",
}
PERSONA_JSON_MAX_TOKENS = 900


class AudienceLiveRunner:
    def __init__(
        self,
        *,
        client_factory: Callable[[], LLMClient] | None = None,
        model_router: ModelRouter | None = None,
        failure_threshold: float = 0.30,
        call_timeout_seconds: float = 45,
        run_timeout_seconds: float = 210,
        max_workers: int = 10,
        embedding_service_factory: Callable[[], EmbeddingProvider] | None = None,
    ) -> None:
        self._client_factory = client_factory or (
            lambda: LLMClient(timeout=call_timeout_seconds)
        )
        self._model_router = model_router or ModelRouter()
        self._failure_threshold = failure_threshold
        self._run_timeout_seconds = run_timeout_seconds
        self._max_workers = max(1, max_workers)
        self._embedding_service_factory = embedding_service_factory

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
        receipt["model_routing"] = {
            "model_pool": list(self._model_router.model_pool),
            "high_quality_retry_model": self._model_router.high_quality_retry_model,
            "failure_threshold": self._failure_threshold,
            "max_workers": self._max_workers,
        }

        future_map = {}
        timed_out = False
        executor = ThreadPoolExecutor(max_workers=self._max_workers)
        try:
            for persona in active_personas:
                assignment = self._model_router.assign(persona, run_input.run_seed, run_id)
                personas_payload.append(persona.to_dict() | {"model_assignment": assignment.to_dict()})
                future = executor.submit(
                    self._call_persona_with_retry,
                    run_input,
                    persona,
                    assignment.model,
                )
                future_map[future] = (persona, assignment)

            for future in as_completed(future_map, timeout=self._run_timeout_seconds):
                persona, assignment = future_map[future]
                try:
                    call = future.result()
                    parsed = call.parsed
                    _record_attempts(receipt, call.attempts)
                    receipt["schema_fallback_count"] += int(call.schema_fallback_used)
                    receipt["high_quality_retry_count"] += int(call.high_quality_retry_used)
                    receipt["high_quality_retry_success_count"] += int(
                        call.high_quality_retry_used
                    )
                    receipt["low_quality_persona_count"] += int(
                        _has_attempt_error(call.attempts, "low_quality_response")
                    )
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
                except PersonaCallFailed as exc:
                    error_kind = exc.error_kind
                    _record_attempts(receipt, exc.attempts)
                    receipt["high_quality_retry_count"] += int(exc.high_quality_retry_used)
                    receipt["high_quality_retry_failure_count"] += int(
                        exc.high_quality_retry_used
                    )
                    receipt["low_quality_persona_count"] += int(
                        _has_attempt_error(exc.attempts, "low_quality_response")
                    )
                    failures.append(
                        {
                            "persona_id": persona.id,
                            "model": assignment.model,
                            "error_kind": error_kind,
                        }
                    )
                except Exception as exc:  # noqa: BLE001
                    error_kind = _sanitized_error_kind(exc)
                    failures.append(
                        {
                            "persona_id": persona.id,
                            "model": assignment.model,
                            "error_kind": error_kind,
                        }
                    )
                    if error_kind == "low_quality_response":
                        receipt["low_quality_persona_count"] += 1
                    _record_failure(receipt, assignment.model)
        except FuturesTimeoutError:
            timed_out = True
            receipt["run_timed_out"] = True
            for future, (persona, assignment) in future_map.items():
                if future.done():
                    continue
                future.cancel()
                failures.append(
                    {
                        "persona_id": persona.id,
                        "model": assignment.model,
                        "error_kind": "run_timeout",
                    }
                )
                _record_failure(receipt, assignment.model)
        finally:
            executor.shutdown(wait=not timed_out, cancel_futures=True)

        receipt["latency_ms"] = int((time.monotonic() - started) * 1000)
        receipt["failed_persona_count"] = len(failures)
        receipt["failure_rate"] = round(len(failures) / len(active_personas), 3)
        receipt["reliability_grade"] = _reliability_grade(receipt["failure_rate"])
        _apply_batch_quality_audit(receipt, objections)

        if receipt["failure_rate"] > self._failure_threshold:
            raise AudienceRunFailed(
                "failure_threshold_exceeded",
                receipt=receipt,
                failures=failures,
                partial_counts={
                    "personas": len(active_personas),
                    "reactions": len(reactions),
                    "objections": len(objections),
                    "insights": len(insights),
                },
            )

        previous = previous_topics or []
        embedding_provider = self._embedding_provider()
        similarity_edges = build_similarity_edges(
            topic,
            previous,
            embedding_provider=embedding_provider,
        )
        receipt["similarity"] = {
            "semantic_provider_configured": self._embedding_service_factory is not None,
            "semantic_edge_count": sum(
                1 for edge in similarity_edges if edge.get("semantic_score") is not None
            ),
        }
        assign_topic_cluster(topic, similarity_edges)
        persona_memory = build_persona_memory(personas_payload, similarity_edges, previous)

        return AudienceRunResult(
            run_id=run_id,
            created_at=created_at,
            topic=topic,
            personas=personas_payload,
            reactions=reactions,
            objections=objections,
            insights=_select_insights(insights),
            recommendation=_recommendation_for(run_input, reactions, objections),
            similarity_edges=similarity_edges,
            persona_memory=persona_memory,
            receipt=receipt,
            failures=failures,
        )

    def _embedding_provider(self) -> EmbeddingProvider | None:
        if not self._embedding_service_factory:
            return None
        try:
            return self._embedding_service_factory()
        except Exception:  # noqa: BLE001
            return None

    def _call_persona_with_retry(
        self,
        run_input: AudienceRunInput,
        persona: AudiencePersona,
        model: str,
    ) -> PersonaCallResult:
        try:
            call = self._call_persona(run_input, persona, model)
            return _ensure_success_attempts(call, high_quality_retry=False)
        except PersonaCallFailed as exc:
            if not _should_high_quality_retry(exc.error_kind, model, self._model_router.high_quality_retry_model):
                raise
            retry_model = self._model_router.high_quality_retry_model
            try:
                retry_call = self._call_persona(
                    run_input,
                    persona,
                    retry_model,
                    high_quality_retry=True,
                )
                retry_call = _ensure_success_attempts(retry_call, high_quality_retry=True)
                return PersonaCallResult(
                    parsed=retry_call.parsed,
                    metadata=retry_call.metadata,
                    schema_fallback_used=retry_call.schema_fallback_used,
                    attempts=(*exc.attempts, *retry_call.attempts),
                    high_quality_retry_used=True,
                )
            except PersonaCallFailed as retry_exc:
                raise PersonaCallFailed(
                    retry_exc.error_kind,
                    attempts=[*exc.attempts, *retry_exc.attempts],
                    high_quality_retry_used=True,
                ) from retry_exc

    def _call_persona(
        self,
        run_input: AudienceRunInput,
        persona: AudiencePersona,
        model: str,
        *,
        high_quality_retry: bool = False,
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
                temperature=0.35,
                max_tokens=PERSONA_JSON_MAX_TOKENS,
                response_format=response_format,
                model=model,
                reasoning_effort=_reasoning_effort_for_model(model),
            )
            try:
                parsed = _parse_and_validate(result.content)
                _validate_reaction_quality(parsed)
            except Exception as exc:  # noqa: BLE001
                error_kind = _sanitized_error_kind(exc)
                attempt = PersonaAttempt(
                    model=result.model,
                    metadata=result,
                    error_kind=error_kind,
                    high_quality_retry=high_quality_retry,
                )
                if not _looks_like_schema_retry(exc):
                    raise PersonaCallFailed(error_kind, attempts=[attempt]) from exc
                raise PersonaCallFailed(error_kind, attempts=[attempt]) from exc
            attempt = PersonaAttempt(
                model=result.model,
                metadata=result,
                error_kind=None,
                high_quality_retry=high_quality_retry,
            )
            return PersonaCallResult(parsed, result, False, (attempt,))
        except Exception as exc:
            if isinstance(exc, PersonaCallFailed):
                if not _looks_like_schema_retry(exc):
                    raise
                attempts = list(exc.attempts)
            else:
                error_kind = _sanitized_error_kind(exc)
                attempts = [
                    PersonaAttempt(
                        model=model,
                        metadata=None,
                        error_kind=error_kind,
                        high_quality_retry=high_quality_retry,
                    )
                ]
                if not _looks_like_schema_retry(exc):
                    raise PersonaCallFailed(error_kind, attempts=attempts) from exc

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
            max_tokens=PERSONA_JSON_MAX_TOKENS,
            response_format={"type": "json_object"},
            model=model,
            reasoning_effort=_reasoning_effort_for_model(model),
        )
        try:
            parsed = _parse_and_validate(result.content)
            _validate_reaction_quality(parsed)
        except Exception as exc:  # noqa: BLE001
            error_kind = _sanitized_error_kind(exc)
            attempts.append(
                PersonaAttempt(
                    model=result.model,
                    metadata=result,
                    error_kind=error_kind,
                    schema_fallback=True,
                    high_quality_retry=high_quality_retry,
                )
            )
            raise PersonaCallFailed(error_kind, attempts=attempts) from exc
        attempt = PersonaAttempt(
            model=result.model,
            metadata=result,
            error_kind=None,
            schema_fallback=True,
            high_quality_retry=high_quality_retry,
        )
        return PersonaCallResult(parsed, result, True, (*attempts, attempt))


def _persona_messages(run_input: AudienceRunInput, persona: AudiencePersona) -> list[dict[str, str]]:
    contract = (
        'Return exactly one JSON object with these keys: "stance", "channel_fit", '
        '"summary", "objection", "objection_severity", "insight", "decision_impact". '
        'The first character must be "{" and the last character must be "}". '
        "Use double quotes, no markdown, no prose, no arrays, no comments. "
        "If the submitted topic is Polish, write JSON string values in Polish."
    )
    return [
        {
            "role": "system",
            "content": (
                "You are one synthetic audience persona in Piotr Durlej's private "
                "content/product thinking panel. Answer as this persona only. "
                "Be concrete, skeptical when appropriate, and return only JSON. "
                "Keep every JSON string to one short sentence. Objections and insights "
                "must mention a concrete part of the submitted topic, not generic advice. "
                f"{contract}"
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
                "Twitter/X post, product idea, or be narrowed/rewritten.\n\n"
                f"{contract}"
            ),
        },
    ]


def _parse_and_validate(content: str) -> dict[str, Any]:
    cleaned = content.strip()
    cleaned = re.sub(r"^```(?:json)?\s*\n?", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\n?```\s*$", "", cleaned).strip()
    try:
        parsed = json.loads(cleaned)
    except json.JSONDecodeError as exc:
        start = cleaned.find("{")
        if start < 0:
            raise ValueError("invalid_json") from exc
        try:
            parsed, _ = json.JSONDecoder().raw_decode(cleaned[start:])
        except json.JSONDecodeError as raw_exc:
            raise ValueError("invalid_json") from raw_exc
    error = validate_json_schema(parsed, REACTION_SCHEMA)
    if error:
        parsed = _normalize_loose_response(parsed)
        error = validate_json_schema(parsed, REACTION_SCHEMA)
        if error:
            path, message = error
            raise ValueError(f"schema_error:{path}:{message}")
    return parsed


def _reasoning_effort_for_model(model: str) -> str:
    if model == "deepseek-v4-flash":
        return "low"
    return "medium"


def _normalize_loose_response(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError("schema_error:$:expected object")
    text_values = [
        str(item).strip()
        for item in value.values()
        if isinstance(item, str) and str(item).strip()
    ]
    summary = (
        value.get("summary")
        or value.get("reaction")
        or value.get("opinion")
        or value.get("answer")
        or value.get("response")
        or (text_values[0] if text_values else "")
    )
    objection = (
        value.get("objection")
        or value.get("concern")
        or value.get("risk")
        or "This needs a clearer practical consequence for the audience."
    )
    insight = (
        value.get("insight")
        or value.get("recommendation")
        or value.get("takeaway")
        or "Frame the idea through a concrete audience decision."
    )
    return {
        "stance": _normalize_stance(str(value.get("stance") or value.get("sentiment") or "")),
        "channel_fit": str(value.get("channel_fit") or value.get("channel") or "unknown fit"),
        "summary": _min_text(str(summary), "The persona gave a short, loosely structured reaction."),
        "objection": _min_text(str(objection), "This needs a clearer practical consequence."),
        "objection_severity": _normalize_severity(str(value.get("objection_severity") or value.get("severity") or "")),
        "insight": _min_text(str(insight), "Translate the idea into a concrete next decision."),
        "decision_impact": _min_text(
            str(value.get("decision_impact") or value.get("action") or ""),
            "Use this as a weak signal and compare it with stronger persona reactions.",
        ),
    }


def _validate_reaction_quality(parsed: dict[str, Any]) -> None:
    objection = str(parsed.get("objection") or "").strip().lower()
    if objection in GENERIC_OBJECTION_FALLBACKS:
        raise ValueError("low_quality_response")


def _normalize_stance(value: str) -> str:
    text = value.lower()
    if any(token in text for token in ("negative", "skeptic", "concern", "bad")):
        return "skeptical"
    if any(token in text for token in ("unclear", "confus", "translate")):
        return "needs_translation"
    if any(token in text for token in ("positive", "interested", "amazing", "good")):
        return "interested"
    return "curious"


def _normalize_severity(value: str) -> str:
    text = value.lower()
    if "high" in text or "critical" in text:
        return "high"
    if "low" in text or "minor" in text:
        return "low"
    return "medium"


def _min_text(value: str, fallback: str, min_length: int = 12) -> str:
    cleaned = " ".join(value.strip().split())
    if len(cleaned) >= min_length:
        return cleaned
    return fallback


def _empty_live_receipt() -> dict[str, Any]:
    return {
        "mode": "live",
        "pricing": "unknown",
        "models": {},
        "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
        "latency_ms": 0,
        "schema_fallback_count": 0,
        "schema_fallback_attempt_count": 0,
        "persona_repair_retry_count": 0,
        "persona_repair_retry_success_count": 0,
        "persona_repair_retry_failure_count": 0,
        "high_quality_retry_count": 0,
        "high_quality_retry_success_count": 0,
        "high_quality_retry_failure_count": 0,
        "similarity": {
            "semantic_provider_configured": False,
            "semantic_edge_count": 0,
        },
        "model_routing": {
            "model_pool": [],
            "high_quality_retry_model": None,
            "failure_threshold": None,
            "max_workers": None,
        },
        "quality_warnings": [],
        "duplicate_objection_count": 0,
        "max_duplicate_objections": 0,
        "run_timed_out": False,
        "failed_persona_count": 0,
        "low_quality_persona_count": 0,
        "failure_rate": 0.0,
        "reliability_grade": "unknown",
    }


def _record_attempts(receipt: dict[str, Any], attempts: tuple[PersonaAttempt, ...] | list[PersonaAttempt]) -> None:
    for attempt in attempts:
        if attempt.schema_fallback:
            receipt["schema_fallback_attempt_count"] += 1
            receipt["persona_repair_retry_count"] += 1
            if attempt.error_kind:
                receipt["persona_repair_retry_failure_count"] += 1
            else:
                receipt["persona_repair_retry_success_count"] += 1
        if attempt.metadata:
            _record_usage(receipt, attempt.metadata, failed=attempt.error_kind is not None)
        else:
            _record_failure(receipt, attempt.model)


def _has_attempt_error(
    attempts: tuple[PersonaAttempt, ...] | list[PersonaAttempt],
    error_kind: str,
) -> bool:
    return any(attempt.error_kind == error_kind for attempt in attempts)


def _record_usage(receipt: dict[str, Any], metadata: LLMChatResult, *, failed: bool = False) -> None:
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
    if failed:
        model_entry["failures"] += 1
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


def _apply_batch_quality_audit(receipt: dict[str, Any], objections: list[dict[str, Any]]) -> None:
    duplicates = _duplicate_objection_stats(objections)
    receipt["duplicate_objection_count"] = duplicates["duplicate_objection_count"]
    receipt["max_duplicate_objections"] = duplicates["max_duplicate_objections"]
    if duplicates["max_duplicate_objections"] <= MAX_GREEN_DUPLICATE_OBJECTION_COUNT:
        return

    warning = {
        "kind": "duplicate_objections",
        "message": (
            "Multiple personas returned the same objection; treat the run as lower confidence."
        ),
        "duplicate_objection_count": duplicates["duplicate_objection_count"],
        "max_duplicate_objections": duplicates["max_duplicate_objections"],
    }
    receipt.setdefault("quality_warnings", []).append(warning)
    if duplicates["max_duplicate_objections"] > MAX_YELLOW_DUPLICATE_OBJECTION_COUNT:
        receipt["reliability_grade"] = "red"
        return
    if receipt.get("reliability_grade") == "green":
        receipt["reliability_grade"] = "yellow"


def _duplicate_objection_stats(objections: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for objection in objections:
        normalized = _normalize_objection_for_duplicate_check(objection.get("text"))
        if not normalized:
            continue
        counts[normalized] = counts.get(normalized, 0) + 1

    max_duplicate = max(counts.values(), default=0)
    duplicate_count = sum(count - 1 for count in counts.values() if count > 1)
    return {
        "duplicate_objection_count": duplicate_count,
        "max_duplicate_objections": max_duplicate,
    }


def _normalize_objection_for_duplicate_check(value: Any) -> str:
    text = str(value or "").casefold()
    text = re.sub(r"[\W_]+", " ", text, flags=re.UNICODE)
    return " ".join(text.split())


def _ensure_success_attempts(
    call: PersonaCallResult,
    *,
    high_quality_retry: bool,
) -> PersonaCallResult:
    if call.attempts:
        return call
    attempt = PersonaAttempt(
        model=call.metadata.model,
        metadata=call.metadata,
        error_kind=None,
        schema_fallback=call.schema_fallback_used,
        high_quality_retry=high_quality_retry,
    )
    return PersonaCallResult(
        parsed=call.parsed,
        metadata=call.metadata,
        schema_fallback_used=call.schema_fallback_used,
        attempts=(attempt,),
        high_quality_retry_used=high_quality_retry,
    )


def _should_high_quality_retry(error_kind: str, model: str, retry_model: str) -> bool:
    return error_kind in RETRYABLE_PERSONA_ERRORS and model != retry_model


def _recommendation_for(
    run_input: AudienceRunInput,
    reactions: list[dict[str, Any]],
    objections: list[dict[str, Any]],
) -> dict[str, Any]:
    skeptical = sum(1 for reaction in reactions if reaction["stance"] in {"skeptical", "needs_translation"})
    high_objections = sum(1 for objection in objections if objection["severity"] == "high")
    question_driven = "?" in run_input.topic
    if skeptical >= 8:
        decision = "rewrite"
    elif high_objections >= 6 or question_driven:
        decision = "narrow"
    else:
        decision = "publish"
    channel_scores = build_channel_scores(
        topic_text=run_input.topic,
        title=run_input.display_title,
        requested_channel=run_input.channel,
        reactions=reactions,
        objections=objections,
    )
    best_channel = top_channel(channel_scores)
    top_objection = _representative_objection(objections)
    polish = _is_likely_polish(run_input.topic)
    return {
        "decision": decision,
        "best_channel": best_channel,
        "channel_scores": channel_scores,
        "next_action": _next_action(decision, best_channel, top_objection, polish=polish),
        "rationale": _recommendation_rationale(
            decision,
            skeptical,
            high_objections,
            question_driven,
            top_objection,
            polish=polish,
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


def _next_action(
    decision: str,
    best_channel: str,
    top_objection: str,
    *,
    polish: bool,
) -> str:
    if polish:
        if decision == "publish":
            return f"Opublikuj na {best_channel}, ale zostaw widoczną odpowiedź na obiekcję: {top_objection}"
        if decision == "rewrite":
            return f"Przepisz pod wartość dla odbiorcy, nie pod frameworki, zaczynając od obiekcji: {top_objection}"
        if decision == "narrow":
            return f"Zacznij od {best_channel}: zawęź do jednej tezy, dodaj konkretny przykład z rezultatami i odpowiedz na obiekcję: {top_objection}"
        if decision == "abandon":
            return f"Odłóż temat, chyba że znajdziesz dowód odpowiadający na obiekcję: {top_objection}"
        return f"Zadaj ostrzejsze pytanie przed wyborem kanału; najmocniejsza obiekcja to: {top_objection}"

    if decision == "publish":
        return f"Draft the strongest {best_channel} version and answer the top objection: {top_objection}"
    if decision == "rewrite":
        return f"Rewrite around audience value instead of tooling, starting with this objection: {top_objection}"
    if decision == "narrow":
        return f"Start with {best_channel}: narrow to one claim, add one evidence-backed example, and answer: {top_objection}"
    if decision == "abandon":
        return f"Park this idea unless you find evidence that answers: {top_objection}"
    return f"Ask a sharper question before choosing a channel; strongest objection: {top_objection}"


def _recommendation_rationale(
    decision: str,
    skeptical: int,
    high_objections: int,
    question_driven: bool,
    top_objection: str,
    *,
    polish: bool,
) -> str:
    if polish:
        drivers = []
        if question_driven:
            drivers.append("temat jest jeszcze szerokim pytaniem")
        if skeptical:
            drivers.append(f"{skeptical} reakcji wymaga doprecyzowania lub budzi sceptycyzm")
        if high_objections:
            drivers.append(f"{high_objections} obiekcji ma wysoką wagę")
        driver_text = ", ".join(drivers) if drivers else "panel nie widzi dużego ryzyka"
        return f"Decyzja {decision}: {driver_text}; najmocniejsza obiekcja: {top_objection}"

    drivers = []
    if question_driven:
        drivers.append("the topic is still framed as a broad question")
    if skeptical:
        drivers.append(f"{skeptical} reactions are skeptical or need translation")
    if high_objections:
        drivers.append(f"{high_objections} objections are high severity")
    driver_text = ", ".join(drivers) if drivers else "the panel sees low delivery risk"
    return f"Decision {decision}: {driver_text}; strongest objection: {top_objection}"


def _representative_objection(objections: list[dict[str, Any]]) -> str:
    if not objections:
        return "No strong objection was captured."
    preferred = [objection for objection in objections if objection.get("severity") == "high"]
    text = str((preferred or objections)[0].get("text") or "").strip()
    return _truncate_sentence(text or "No strong objection was captured.")


def _truncate_sentence(text: str, limit: int = 180) -> str:
    cleaned = " ".join(text.split())
    if len(cleaned) <= limit:
        return cleaned
    return f"{cleaned[: limit - 1].rstrip()}..."


def _is_likely_polish(text: str) -> bool:
    normalized = f" {text.lower()} "
    markers = (" czy ", " czego ", " wydaje ", " wazne ", " ważne ", " rezultat", " dostarcz")
    return any(marker in normalized for marker in markers)


def _select_insights(insights: list[dict[str, Any]], limit: int = 8) -> list[dict[str, Any]]:
    return insights[:limit]


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
        or "schema_validation_failed" in text
    )


def _sanitized_error_kind(exc: Exception) -> str:
    if isinstance(exc, json.JSONDecodeError):
        return "invalid_json"
    if isinstance(exc, ValueError) and str(exc).startswith("schema_error"):
        return "schema_validation_failed"
    if isinstance(exc, ValueError) and str(exc) == "invalid_json":
        return "invalid_json"
    if isinstance(exc, ValueError) and str(exc) == "low_quality_response":
        return "low_quality_response"
    return type(exc).__name__

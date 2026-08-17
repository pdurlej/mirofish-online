"""Live 20-person audience runner with sanitized receipts."""

from __future__ import annotations

import json
import re
import threading
import time
import uuid
from collections import Counter
from collections.abc import Iterable
from concurrent.futures import (
    Future,
    ThreadPoolExecutor,
    TimeoutError as FuturesTimeoutError,
    as_completed,
)
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable

from ..utils.llm_client import LLMClient, LLMChatResult, validate_json_schema
from .audience_run import AudienceRunInput, AudienceRunResult
from .channel_fit import CHANNELS, build_channel_scores, channel_scores_source, top_channel
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
        "channel_scores",
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
        "channel_scores": {
            "type": "object",
            "required": list(CHANNELS),
            "properties": {
                channel: {"type": "integer", "minimum": 0, "maximum": 100}
                for channel in CHANNELS
            },
            "additionalProperties": False,
        },
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

# Derived from the schema rather than restated, so the two cannot drift apart.
STANCE_VALUES: frozenset[str] = frozenset(REACTION_SCHEMA["properties"]["stance"]["enum"])
SEVERITY_VALUES: frozenset[str] = frozenset(
    REACTION_SCHEMA["properties"]["objection_severity"]["enum"]
)


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
    # Loose normalization rewrites the whole reaction, so a run can look clean
    # while every stance was invented by the fallback. Carry that to the receipt.
    loose_normalized: bool = False
    stance_unrecognized: bool = False
    severity_unrecognized: bool = False


class _RunClient:
    """Lazily create and own one thread-safe HTTP client for a single run."""

    def __init__(self, factory: Callable[[], LLMClient]) -> None:
        self._factory = factory
        self._lock = threading.Lock()
        self._client: LLMClient | None = None

    def get(self) -> LLMClient:
        with self._lock:
            if self._client is None:
                self._client = self._factory()
            return self._client

    def close(self) -> None:
        with self._lock:
            client = self._client
            self._client = None
        if client is not None:
            close = getattr(client, "close", None)
            if callable(close):
                close()


GENERIC_OBJECTION_FALLBACKS = {
    "this needs a clearer practical consequence.",
    "this needs a clearer practical consequence for the audience.",
}
MAX_GREEN_DUPLICATE_OBJECTION_COUNT = 2
MAX_YELLOW_DUPLICATE_OBJECTION_COUNT = 4
# A panel that agrees with itself has told you nothing. Production held 76 runs
# where all twenty personas were stored with the same stance, every one graded
# green, because nothing looked at the spread.
MIN_GREEN_STANCE_VARIETY = 2
MAX_GREEN_DOMINANT_STANCE_SHARE = 0.85
# How much of the panel's stance the fallback may have picked before the run
# stops counting as trustworthy.
MAX_GREEN_UNRECOGNIZED_STANCE_SHARE = 0.2
RETRYABLE_PERSONA_ERRORS = {
    "invalid_json",
    "schema_validation_failed",
    "low_quality_response",
    "truncated_response",
}
# This budget covers reasoning tokens, not just the answer. Measured on
# gemma4:31b: a 533-character JSON reply consumed 790 completion tokens, so
# roughly 600 went to reasoning that never reaches the content. At 900 the
# answer was being cut mid-key (finish_reason="length"), which the code then
# reported as invalid_json and rescued with a second call -- 38 calls for 20
# personas. Headroom is cheaper than a retry: unused tokens cost nothing, a
# truncated answer costs a whole extra request.
PERSONA_JSON_MAX_TOKENS = 2500


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
            # False when the retry model is already in the pool, which makes the
            # rescue path unreachable. It was silently unreachable by default.
            "high_quality_retry_available": (
                self._model_router.high_quality_retry_available
            ),
            "failure_threshold": self._failure_threshold,
            "max_workers": self._max_workers,
        }

        future_map = {}
        timed_out = False
        run_client = _RunClient(self._client_factory)
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
                    run_client.get,
                )
                future_map[future] = (persona, assignment)

            for future in as_completed(future_map, timeout=self._run_timeout_seconds):
                persona, assignment = future_map[future]
                try:
                    call = future.result()
                    parsed = call.parsed
                    _record_attempts(receipt, call.attempts)
                    receipt["schema_fallback_count"] += int(call.schema_fallback_used)
                    receipt["loose_normalization_count"] += int(call.loose_normalized)
                    receipt["unrecognized_stance_count"] += int(call.stance_unrecognized)
                    receipt["unrecognized_severity_count"] += int(
                        call.severity_unrecognized
                    )
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
                            "channel_scores": parsed["channel_scores"],
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
            if timed_out:
                self._close_client_when_futures_finish(run_client, list(future_map))
            else:
                run_client.close()

        receipt["latency_ms"] = int((time.monotonic() - started) * 1000)
        receipt["failed_persona_count"] = len(failures)
        _warn_if_retry_was_unavailable(
            receipt, failures, available=self._model_router.high_quality_retry_available
        )
        receipt["failure_rate"] = round(len(failures) / len(active_personas), 3)
        receipt["reliability_grade"] = _reliability_grade(receipt["failure_rate"])
        receipt["stance_distribution"] = _value_distribution(
            reaction["stance"] for reaction in reactions
        )
        receipt["severity_distribution"] = _value_distribution(
            objection["severity"] for objection in objections
        )
        _apply_batch_quality_audit(
            receipt,
            objections,
            topic_text=f"{run_input.display_title} {run_input.topic}",
            reactions=reactions,
        )

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

        objections = _prioritize_objections(objections)
        recommendation = _recommendation_for(run_input, reactions, objections)
        primary_objection_id = recommendation.get("primary_objection_id")
        for objection in objections:
            objection["drives_next_action"] = objection.get("id") == primary_objection_id

        return AudienceRunResult(
            run_id=run_id,
            created_at=created_at,
            topic=topic,
            personas=personas_payload,
            reactions=reactions,
            objections=objections,
            insights=_select_insights(insights),
            recommendation=recommendation,
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

    @staticmethod
    def _close_client_when_futures_finish(
        run_client: _RunClient, futures: list[Future[Any]]
    ) -> None:
        pending = [future for future in futures if not future.done()]
        if not pending:
            run_client.close()
            return

        remaining = len(pending)
        completion_lock = threading.Lock()

        def release_after_last_future(_future: Future[Any]) -> None:
            nonlocal remaining
            should_release = False
            with completion_lock:
                remaining -= 1
                should_release = remaining == 0
            if should_release:
                run_client.close()

        for future in pending:
            future.add_done_callback(release_after_last_future)

    def _call_persona_with_retry(
        self,
        run_input: AudienceRunInput,
        persona: AudiencePersona,
        model: str,
        client_provider: Callable[[], LLMClient] | None = None,
    ) -> PersonaCallResult:
        try:
            call = self._call_persona(
                run_input,
                persona,
                model,
                client_provider=client_provider,
            )
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
                    client_provider=client_provider,
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
        client_provider: Callable[[], LLMClient] | None = None,
    ) -> PersonaCallResult:
        client = client_provider() if client_provider else self._client_factory()
        messages = _persona_messages(run_input, persona)
        response_format = {
            "type": "json_schema",
            "json_schema": {
                "name": "mirofish_audience_reaction",
                "strict": True,
                "schema": REACTION_SCHEMA,
            },
        }
        strict_normalization: dict[str, bool] = {}
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
                _reject_if_truncated(result)
                parsed = _parse_and_validate(
                    result.content, normalization=strict_normalization
                )
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
            return PersonaCallResult(
                parsed,
                result,
                False,
                (attempt,),
                loose_normalized=strict_normalization.get("loose", False),
                stance_unrecognized=strict_normalization.get(
                    "stance_unrecognized", False
                ),
                severity_unrecognized=strict_normalization.get(
                    "severity_unrecognized", False
                ),
            )
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
        # A fresh dict: the strict attempt's normalization describes a response
        # that was thrown away, so reusing it would report stale coercions.
        repair_normalization: dict[str, bool] = {}
        try:
            _reject_if_truncated(result)
            parsed = _parse_and_validate(
                result.content, normalization=repair_normalization
            )
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
        return PersonaCallResult(
            parsed,
            result,
            True,
            (*attempts, attempt),
            loose_normalized=repair_normalization.get("loose", False),
            stance_unrecognized=repair_normalization.get("stance_unrecognized", False),
            severity_unrecognized=repair_normalization.get(
                "severity_unrecognized", False
            ),
        )


def _persona_messages(run_input: AudienceRunInput, persona: AudiencePersona) -> list[dict[str, str]]:
    stance_values = ", ".join(
        f'"{value}"' for value in REACTION_SCHEMA["properties"]["stance"]["enum"]
    )
    severity_values = ", ".join(
        f'"{value}"'
        for value in REACTION_SCHEMA["properties"]["objection_severity"]["enum"]
    )
    contract = (
        'Return exactly one JSON object with these keys: "stance", "channel_fit", '
        '"channel_scores", "summary", "objection", "objection_severity", "insight", '
        '"decision_impact". "channel_scores" must contain integer 0-100 scores for '
        '"linkedin", "podcast", "blog", "twitter-x", and "product-idea". '
        f'"stance" must be exactly one of {stance_values}. '
        f'"objection_severity" must be exactly one of {severity_values}. '
        'The first character must be "{" and the last character must be "}". '
        "Use double quotes, no markdown, no prose, no arrays, no comments. "
        # The old instruction said to write JSON string values in Polish for
        # Polish topics, which the model applied to the enums too. Every Polish
        # stance then failed validation and was silently rewritten.
        "Write free-text values in the same language as the submitted topic. "
        "Keys and the two enumerated values above are always English."
    )
    return [
        {
            "role": "system",
            "content": (
                "You are one synthetic audience persona in a private content and "
                "product thinking panel. Answer as this persona only.\n"
                "You are reacting, not reviewing. Do not describe or summarise the "
                'topic. Never open a value with "Analysis of", "A text about", '
                '"An overview of" or any equivalent. State what you think and why '
                "it matters to you specifically.\n"
                "Take a position. Pick the stance that matches your actual leaning, "
                'and use "curious" only when you genuinely have none — an evasive '
                "middle answer is worse than a wrong one, because the panel exists "
                "to disagree.\n"
                "Be concrete and return only JSON. Keep every JSON string to one "
                "short sentence. Objections and insights must name a concrete part "
                "of the submitted topic, not generic advice.\n"
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
                f"Title: {run_input.display_title}\n"
                f"Topic/draft:\n{run_input.topic}\n\n"
                '"summary" is your reaction to this, in your own voice: what you '
                "make of it and whether it earns your attention. It is not a "
                "description of what the topic is about.\n"
                "Score every channel independently before comparing them. Judge whether "
                "this should become a podcast, LinkedIn post, blog, Twitter/X post, product "
                "idea, or be narrowed/rewritten.\n\n"
                f"{contract}"
            ),
        },
    ]


def _parse_and_validate(
    content: str, *, normalization: dict[str, bool] | None = None
) -> dict[str, Any]:
    """Parse a persona reaction, optionally reporting what had to be rewritten.

    ``normalization`` is an out-parameter rather than a changed return type so
    existing callers and tests keep working. It matters because the loose path
    silently substitutes values, and until now nothing counted how often.
    """
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
        if normalization is not None:
            _record_normalization(normalization, parsed)
        parsed = _normalize_loose_response(parsed)
        error = validate_json_schema(parsed, REACTION_SCHEMA)
        if error:
            path, message = error
            raise ValueError(f"schema_error:{path}:{message}")
    return parsed


def _reject_if_truncated(result: LLMChatResult) -> None:
    """Name a cut-off answer for what it is.

    A response that hit the token ceiling is a budget problem. Reported as
    invalid_json it looks like a badly behaved model instead, which is how a
    900-token cap masqueraded as model unreliability for months.
    """
    if result.finish_reason == "length":
        raise ValueError("truncated_response")


def _record_normalization(normalization: dict[str, bool], parsed: Any) -> None:
    """Note that the loose path ran, and whether it had to invent a stance."""
    normalization["loose"] = True
    if not isinstance(parsed, dict):
        # Nothing usable arrived, so every field is about to be substituted.
        normalization["stance_unrecognized"] = True
        normalization["severity_unrecognized"] = True
        return
    raw_stance = str(parsed.get("stance") or parsed.get("sentiment") or "")
    raw_severity = str(
        parsed.get("objection_severity") or parsed.get("severity") or ""
    )
    # "Unrecognized" means the fallback had to pick, not merely that the raw
    # value was not literally an enum member.
    normalization["stance_unrecognized"] = not _resolve_stance(raw_stance)[1]
    normalization["severity_unrecognized"] = not _resolve_severity(raw_severity)[1]


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
    raw_channel_scores = value.get("channel_scores")
    if raw_channel_scores is None and str(objection).strip().lower() in GENERIC_OBJECTION_FALLBACKS:
        normalized_channel_scores = {channel: 50 for channel in CHANNELS}
    else:
        normalized_channel_scores = _normalize_channel_scores(raw_channel_scores)
    return {
        "stance": _normalize_stance(str(value.get("stance") or value.get("sentiment") or "")),
        "channel_fit": str(value.get("channel_fit") or value.get("channel") or "unknown fit"),
        "channel_scores": normalized_channel_scores,
        "summary": _min_text(str(summary), "The persona gave a short, loosely structured reaction."),
        "objection": _min_text(str(objection), "This needs a clearer practical consequence."),
        "objection_severity": _normalize_severity(str(value.get("objection_severity") or value.get("severity") or "")),
        "insight": _min_text(str(insight), "Translate the idea into a concrete next decision."),
        "decision_impact": _min_text(
            str(value.get("decision_impact") or value.get("action") or ""),
            "Use this as a weak signal and compare it with stronger persona reactions.",
        ),
    }


def _normalize_channel_scores(value: Any) -> dict[str, int]:
    if not isinstance(value, dict):
        raise ValueError("schema_error:$.channel_scores:expected object")
    scores: dict[str, int] = {}
    for channel in CHANNELS:
        try:
            score = int(round(float(value[channel])))
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError(
                f"schema_error:$.channel_scores.{channel}:expected integer"
            ) from exc
        scores[channel] = max(0, min(100, score))
    return scores


def _validate_reaction_quality(parsed: dict[str, Any]) -> None:
    objection = str(parsed.get("objection") or "").strip().lower()
    if objection in GENERIC_OBJECTION_FALLBACKS:
        raise ValueError("low_quality_response")


def _resolve_stance(value: str) -> tuple[str, bool]:
    """Map a free-form stance onto the enum.

    The second element is False only when nothing matched and the fallback had
    to pick for the model. That distinction is what makes the guess countable:
    "Sceptyczny" is now understood, so it is not reported as a lost stance,
    while genuinely opaque text still is.
    """
    text = value.strip().lower()
    if text in STANCE_VALUES:
        return text, True
    if any(
        token in text
        for token in (
            "negative", "skeptic", "concern", "bad", "doubt",
            # Polish stems. The prompt asks for Polish values on Polish topics,
            # and "sceptyczny" contains no "skeptic" because Polish spells it
            # with a c, which is how every Polish stance became "curious".
            "sceptyc", "krytyc", "negatyw", "wątpliw", "watpliw", "obaw", "ryzyk",
        )
    ):
        return "skeptical", True
    if any(
        token in text
        for token in (
            # "translat", not "translate": the enum value is "needs_translation".
            "unclear", "confus", "translat",
            "niejasn", "niezrozum", "tłumacz", "tlumacz",
        )
    ):
        return "needs_translation", True
    if any(
        token in text
        for token in (
            "positive", "interested", "amazing", "good", "support",
            "zainteresow", "pozytyw", "entuzj", "świetn", "swietn", "popier",
        )
    ):
        return "interested", True
    if any(
        token in text
        for token in ("curious", "neutral", "mixed", "ciekaw", "neutraln", "mieszan")
    ):
        return "curious", True
    return "curious", False


def _resolve_severity(value: str) -> tuple[str, bool]:
    """Map a free-form severity onto the enum; False when the fallback guessed."""
    text = value.strip().lower()
    if text in SEVERITY_VALUES:
        return text, True
    if any(token in text for token in ("high", "critical", "wysok", "krytyc", "poważn", "powazn")):
        return "high", True
    if any(token in text for token in ("low", "minor", "nisk", "drobn", "błah", "blah")):
        return "low", True
    if any(token in text for token in ("medium", "moderate", "średni", "sredni", "umiarkowan")):
        return "medium", True
    return "medium", False


def _normalize_stance(value: str) -> str:
    return _resolve_stance(value)[0]


def _normalize_severity(value: str) -> str:
    return _resolve_severity(value)[0]


def _min_text(value: str, fallback: str, min_length: int = 12) -> str:
    cleaned = " ".join(value.strip().split())
    if len(cleaned) >= min_length:
        return cleaned
    return fallback


def _value_distribution(values: Iterable[str]) -> dict[str, int]:
    """Count how often each value appears, most common first."""
    return dict(Counter(str(value) for value in values).most_common())


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
            "high_quality_retry_available": False,
            "failure_threshold": None,
            "max_workers": None,
        },
        "quality_warnings": [],
        "duplicate_objection_count": 0,
        "max_duplicate_objections": 0,
        "near_duplicate_objections": 0,
        "weak_topic_grounding": 0,
        # How much of the result the loose fallback wrote instead of the model.
        # schema_fallback_count is a different thing: it counts providers that
        # could not honour a strict json_schema request.
        "loose_normalization_count": 0,
        "unrecognized_stance_count": 0,
        "unrecognized_severity_count": 0,
        # Why calls were wasted, keyed by sanitized error kind.
        "error_kinds": {},
        # Whether the panel actually disagreed with itself. A run where every
        # persona lands on the same stance carries no signal, however clean it
        # looks by every other measure.
        "stance_distribution": {},
        "severity_distribution": {},
        "run_timed_out": False,
        "failed_persona_count": 0,
        "low_quality_persona_count": 0,
        "failure_rate": 0.0,
        "reliability_grade": "unknown",
    }


def _record_attempts(receipt: dict[str, Any], attempts: tuple[PersonaAttempt, ...] | list[PersonaAttempt]) -> None:
    for attempt in attempts:
        if attempt.error_kind:
            # Which failure, not just how many. Without this the receipt could
            # say a third of the calls were wasted but not why.
            kinds = receipt.setdefault("error_kinds", {})
            kinds[attempt.error_kind] = kinds.get(attempt.error_kind, 0) + 1
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


def _apply_batch_quality_audit(
    receipt: dict[str, Any],
    objections: list[dict[str, Any]],
    *,
    topic_text: str,
    reactions: list[dict[str, Any]] | None = None,
) -> None:
    duplicates = _duplicate_objection_stats(objections)
    receipt["duplicate_objection_count"] = duplicates["duplicate_objection_count"]
    receipt["max_duplicate_objections"] = duplicates["max_duplicate_objections"]
    if duplicates["max_duplicate_objections"] > MAX_GREEN_DUPLICATE_OBJECTION_COUNT:
        receipt.setdefault("quality_warnings", []).append(
            {
                "kind": "duplicate_objections",
                "message": (
                    "Multiple personas returned the same objection; treat the run as lower confidence."
                ),
                "duplicate_objection_count": duplicates["duplicate_objection_count"],
                "max_duplicate_objections": duplicates["max_duplicate_objections"],
            }
        )
        _lower_reliability(
            receipt,
            "red"
            if duplicates["max_duplicate_objections"]
            > MAX_YELLOW_DUPLICATE_OBJECTION_COUNT
            else "yellow",
        )

    near_duplicate_count = _near_duplicate_objection_count(objections)
    receipt["near_duplicate_objections"] = near_duplicate_count
    if near_duplicate_count:
        receipt.setdefault("quality_warnings", []).append(
            {
                "kind": "near_duplicate_objections",
                "message": "Several objections are near-duplicates despite different wording.",
                "count": near_duplicate_count,
            }
        )
        _lower_reliability(receipt, "red" if near_duplicate_count >= 6 else "yellow")

    weak_grounding_count = sum(
        1
        for objection in objections
        if not _is_topic_grounded(str(objection.get("text") or ""), topic_text)
    )
    receipt["weak_topic_grounding"] = weak_grounding_count
    if weak_grounding_count:
        receipt.setdefault("quality_warnings", []).append(
            {
                "kind": "weak_topic_grounding",
                "message": "Some objections do not reference a concrete part of the topic.",
                "count": weak_grounding_count,
            }
        )
        weak_share = weak_grounding_count / max(len(objections), 1)
        _lower_reliability(receipt, "red" if weak_share > 0.4 else "yellow")

    # Last, so the existing warning order stays stable for callers that read
    # quality_warnings[0]. Ordering does not affect the grade: _lower_reliability
    # only ever moves it down.
    _audit_stance_signal(receipt, reactions or [])


def _warn_if_retry_was_unavailable(
    receipt: dict[str, Any],
    failures: list[dict[str, Any]],
    *,
    available: bool,
) -> None:
    """Say so when a persona could have been rescued but there was nothing to try.

    Deliberately silent unless it actually cost something: a dead retry layer on
    a run where nobody failed is a configuration note, not a quality problem.
    The grade is left alone, because the failures themselves already move it.
    """
    if available or not failures:
        return
    retryable = [
        failure
        for failure in failures
        if failure.get("error_kind") in RETRYABLE_PERSONA_ERRORS
    ]
    if not retryable:
        return
    receipt.setdefault("quality_warnings", []).append(
        {
            "kind": "retry_layer_unavailable",
            "message": (
                "Personas failed with retryable errors, but the high-quality retry "
                "model is already in the pool, so nothing could be retried. Set "
                "MIROFISH_AUDIENCE_RETRY_MODEL to a different model."
            ),
            "count": len(retryable),
        }
    )


def _audit_stance_signal(
    receipt: dict[str, Any], reactions: list[dict[str, Any]]
) -> None:
    """Refuse to call a run green when the panel carries no disagreement.

    Two separate failures land here. A panel that answered with one stance has
    no signal to read, whatever its schema validity. And a panel whose stances
    were mostly picked by the fallback is not reporting the model's opinion at
    all — it is reporting ours.
    """
    if not reactions:
        return

    distribution = receipt.get("stance_distribution") or _value_distribution(
        reaction["stance"] for reaction in reactions
    )
    total = sum(distribution.values())
    if not total:
        return

    dominant_share = max(distribution.values()) / total
    if (
        len(distribution) < MIN_GREEN_STANCE_VARIETY
        or dominant_share > MAX_GREEN_DOMINANT_STANCE_SHARE
    ):
        receipt.setdefault("quality_warnings", []).append(
            {
                "kind": "flat_stance_signal",
                "message": (
                    "The panel barely disagreed, so the run cannot separate this "
                    "topic from any other."
                ),
                "distinct_stances": len(distribution),
                "dominant_stance_share": round(dominant_share, 3),
            }
        )
        _lower_reliability(
            receipt, "red" if len(distribution) < MIN_GREEN_STANCE_VARIETY else "yellow"
        )

    unrecognized = int(receipt.get("unrecognized_stance_count") or 0)
    if unrecognized:
        unrecognized_share = unrecognized / total
        if unrecognized_share > MAX_GREEN_UNRECOGNIZED_STANCE_SHARE:
            receipt.setdefault("quality_warnings", []).append(
                {
                    "kind": "substituted_stances",
                    "message": (
                        "Several stances were chosen by the fallback rather than by "
                        "the personas."
                    ),
                    "count": unrecognized,
                    "share": round(unrecognized_share, 3),
                }
            )
            _lower_reliability(receipt, "red" if unrecognized_share > 0.5 else "yellow")


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


def _near_duplicate_objection_count(objections: list[dict[str, Any]]) -> int:
    normalized = [
        _normalize_objection_for_duplicate_check(objection.get("text"))
        for objection in objections
    ]
    token_sets = [set(text.split()) for text in normalized]
    matched: set[int] = set()
    for left_index, left in enumerate(token_sets):
        if len(left) < 4:
            continue
        for right_index in range(left_index + 1, len(token_sets)):
            right = token_sets[right_index]
            if normalized[left_index] == normalized[right_index] or len(right) < 4:
                continue
            overlap = len(left & right) / max(len(left | right), 1)
            if overlap >= 0.72:
                matched.update((left_index, right_index))
    return len(matched)


GROUNDING_STOPWORDS = {
    "about",
    "audience",
    "because",
    "brakuje",
    "clear",
    "concrete",
    "dlaczego",
    "explain",
    "idea",
    "jak",
    "jest",
    "konkretny",
    "need",
    "needs",
    "practical",
    "show",
    "temat",
    "this",
    "what",
    "why",
}


def _grounding_tokens(value: str) -> set[str]:
    normalized = _normalize_objection_for_duplicate_check(value)
    return {
        token if len(token) <= 4 else token[:6]
        for token in normalized.split()
        if (len(token) >= 4 or token in {"ai", "cd", "ci", "llm", "pm", "qa", "roi"})
        and token not in GROUNDING_STOPWORDS
    }


def _is_topic_grounded(objection: str, topic_text: str) -> bool:
    return bool(_grounding_tokens(objection) & _grounding_tokens(topic_text))


def _lower_reliability(receipt: dict[str, Any], target: str) -> None:
    rank = {"unknown": 0, "green": 1, "test": 1, "yellow": 2, "red": 3}
    current = str(receipt.get("reliability_grade") or "unknown")
    if rank.get(target, 0) > rank.get(current, 0):
        receipt["reliability_grade"] = target


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
    skeptical = sum(1 for reaction in reactions if reaction["stance"] == "skeptical")
    needs_translation = sum(1 for reaction in reactions if reaction["stance"] == "needs_translation")
    resistant = skeptical + needs_translation
    high_objections = sum(1 for objection in objections if objection["severity"] == "high")
    question_driven = _is_question_driven(run_input.topic)
    channel_scores = build_channel_scores(
        topic_text=run_input.topic,
        title=run_input.display_title,
        requested_channel=run_input.channel,
        reactions=reactions,
        objections=objections,
    )
    best_channel = top_channel(channel_scores)
    action_scorecard = _action_scorecard(
        reactions=reactions,
        channel_scores=channel_scores,
        skeptical=skeptical,
        needs_translation=needs_translation,
        high_objections=high_objections,
        question_driven=question_driven,
    )
    decision = action_scorecard[0]["decision"]
    top_objection_record = _representative_objection_record(objections)
    top_objection = _truncate_sentence(
        str(top_objection_record.get("text") or "No strong objection was captured.")
    )
    polish = _is_likely_polish(run_input.topic)
    return {
        "decision": decision,
        "decision_confidence": _decision_confidence(action_scorecard),
        "action_scorecard": action_scorecard,
        "best_channel": best_channel,
        "channel_scores": channel_scores,
        "channel_scores_source": channel_scores_source(reactions),
        "requested_channel": run_input.channel,
        "primary_objection_id": top_objection_record.get("id"),
        "next_action": _next_action(decision, best_channel, top_objection, polish=polish),
        "rationale": _recommendation_rationale(
            decision,
            resistant,
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


def _action_scorecard(
    *,
    reactions: list[dict[str, Any]],
    channel_scores: list[dict[str, Any]],
    skeptical: int,
    needs_translation: int,
    high_objections: int,
    question_driven: bool,
) -> list[dict[str, Any]]:
    sample_size = max(len(reactions), 1)
    supportive = sum(1 for reaction in reactions if reaction["stance"] in {"interested", "curious"})
    support_share = supportive / sample_size
    resistant = skeptical + needs_translation
    top_score = int(channel_scores[0].get("score", 0)) if channel_scores else 0
    second_score = int(channel_scores[1].get("score", 0)) if len(channel_scores) > 1 else 0
    channel_gap = max(0, top_score - second_score)
    top_confidence = float(channel_scores[0].get("confidence", 0.0)) if channel_scores else 0.0
    small_sample = sample_size < 8

    publish = (
        38
        + (support_share * 32)
        + (max(0, top_score - 62) * 0.75)
        + min(10, channel_gap * 0.5)
        + (top_confidence * 8)
        - (resistant * 2.6)
        - (high_objections * 4.2)
        - (6 if question_driven else 0)
        - (18 if small_sample else 0)
    )
    rewrite = (
        24
        + (skeptical * 4.2)
        + (needs_translation * 3.4)
        + (high_objections * 3.4)
        + (8 if top_score < 65 else 0)
    )
    narrow = (
        34
        + (14 if question_driven else 0)
        + (needs_translation * 2.2)
        + (high_objections * 2.1)
        + (max(0, 74 - top_score) * 0.55)
        + (6 if channel_gap < 6 else 0)
        + (10 if small_sample else 0)
    )
    abandon = (
        4
        + (skeptical * 2.7)
        + (high_objections * 3.8)
        + (max(0, 58 - top_score) * 0.7)
        - (supportive * 1.5)
    )

    rows = [
        {
            "decision": "publish",
            "label": "Publish",
            "score": _bounded_action_score(publish),
            "driver": "Audience support and a clear top channel outweigh the remaining risk.",
        },
        {
            "decision": "rewrite",
            "label": "Rewrite",
            "score": _bounded_action_score(rewrite),
            "driver": "Skepticism, translation friction, or high-severity objections change the angle.",
        },
        {
            "decision": "narrow",
            "label": "Narrow",
            "score": _bounded_action_score(narrow),
            "driver": "The topic still needs one sharper claim, proof, or channel choice.",
        },
        {
            "decision": "abandon",
            "label": "Abandon",
            "score": _bounded_action_score(abandon),
            "driver": "The audience signal is too weak for this topic without new evidence.",
        },
    ]
    return sorted(rows, key=lambda item: (-int(item["score"]), item["decision"]))


def _bounded_action_score(score: float) -> int:
    return max(0, min(96, round(score)))


def _decision_confidence(action_scorecard: list[dict[str, Any]]) -> float:
    if not action_scorecard:
        return 0.0
    top_score = int(action_scorecard[0].get("score", 0))
    second_score = int(action_scorecard[1].get("score", 0)) if len(action_scorecard) > 1 else 0
    return round(max(0.35, min(0.94, 0.42 + ((top_score - second_score) / 100))), 2)


def _is_question_driven(text: str) -> bool:
    normalized = f" {text.casefold()} "
    return "?" in text or " czy " in normalized or " dlaczego " in normalized


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


def _representative_objection_record(
    objections: list[dict[str, Any]],
) -> dict[str, Any]:
    if not objections:
        return {"id": None, "text": "No strong objection was captured.", "severity": "low"}
    preferred = [objection for objection in objections if objection.get("severity") == "high"]
    return (preferred or objections)[0]


def _representative_objection(objections: list[dict[str, Any]]) -> str:
    objection = _representative_objection_record(objections)
    text = str(objection.get("text") or "").strip()
    return _truncate_sentence(text or "No strong objection was captured.")


def _prioritize_objections(
    objections: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    severity_rank = {"high": 0, "medium": 1, "low": 2}
    return sorted(
        objections,
        key=lambda objection: severity_rank.get(str(objection.get("severity")), 3),
    )


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
        or "truncated_response" in text
    )


def _sanitized_error_kind(exc: Exception) -> str:
    if isinstance(exc, json.JSONDecodeError):
        return "invalid_json"
    if isinstance(exc, ValueError) and str(exc).startswith("schema_error"):
        return "schema_validation_failed"
    if isinstance(exc, ValueError) and str(exc) == "truncated_response":
        return "truncated_response"
    if isinstance(exc, ValueError) and str(exc) == "invalid_json":
        return "invalid_json"
    if isinstance(exc, ValueError) and str(exc) == "low_quality_response":
        return "low_quality_response"
    return type(exc).__name__

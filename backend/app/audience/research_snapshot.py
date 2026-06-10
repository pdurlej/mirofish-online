"""Build controlled synthetic research snapshots as AudienceRun payloads."""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .audience_run import AudienceRunResult
from .channel_fit import build_channel_scores, top_channel
from .similarity import assign_topic_cluster, build_persona_memory, build_similarity_edges


SNAPSHOT_MODE = "synthetic_research_snapshot"
DEFAULT_SOURCE_MODEL = "agy:gemini-3.5-flash-low"
VALID_CHANNELS = {"podcast", "linkedin", "blog", "twitter-x", "product-idea", "unknown"}


@dataclass(frozen=True)
class SyntheticResearchDataset:
    snapshot_id: str
    archetypes: list[dict[str, Any]]
    topics: list[dict[str, Any]]
    candidates: list[dict[str, Any]]
    responses: list[dict[str, Any]]
    source: str = "gemini_research"


def load_research_dataset(
    *,
    research_path: Path,
    candidates_path: Path,
    snapshot_id: str,
) -> SyntheticResearchDataset:
    research = json.loads(research_path.read_text(encoding="utf-8"))
    candidate_payload = json.loads(candidates_path.read_text(encoding="utf-8"))
    candidates = (
        candidate_payload.get("candidates", [])
        if isinstance(candidate_payload, dict)
        else candidate_payload
    )
    return SyntheticResearchDataset(
        snapshot_id=snapshot_id,
        archetypes=list(research.get("archetypes") or []),
        topics=list(research.get("topics") or []),
        candidates=list(candidates or []),
        responses=list(research.get("responses") or []),
        source=str(candidate_payload.get("source") or "gemini_research")
        if isinstance(candidate_payload, dict)
        else "gemini_research",
    )


def build_snapshot_run(
    dataset: SyntheticResearchDataset,
    candidate: dict[str, Any],
    *,
    previous_topics: list[dict[str, Any]] | None = None,
    source_model: str = DEFAULT_SOURCE_MODEL,
    created_at: str | None = None,
) -> AudienceRunResult:
    topic_id = str(candidate["id"])
    responses = _responses_for_topic(dataset.responses, topic_id)
    if not responses:
        raise ValueError(f"No responses found for candidate topic {topic_id}")

    archetype_by_id = _by_id(dataset.archetypes)
    topic = _topic_payload(dataset, candidate)
    run_id = _run_id(dataset.snapshot_id, topic_id)
    timestamp = created_at or datetime.now(timezone.utc).isoformat()
    channel_preferences = _channel_preferences_by_archetype(dataset.responses)

    personas = [
        _persona_payload(
            archetype,
            snapshot_id=dataset.snapshot_id,
            source_model=source_model,
            channel_preferences=channel_preferences.get(str(archetype["id"]), []),
        )
        for archetype in dataset.archetypes
        if str(archetype.get("id")) in {str(response.get("a")) for response in responses}
    ]
    personas.sort(key=lambda persona: persona["id"])

    reactions = [
        _reaction_payload(
            run_id=run_id,
            response=response,
            persona_id=_persona_id(dataset.snapshot_id, str(response["a"])),
            source_model=source_model,
        )
        for response in responses
    ]
    objections = [
        _objection_payload(
            run_id=run_id,
            response=response,
            persona=_archetype_or_stub(archetype_by_id, str(response["a"])),
            persona_id=_persona_id(dataset.snapshot_id, str(response["a"])),
        )
        for response in responses
    ]
    insights = _insights(candidate, responses, archetype_by_id, dataset.snapshot_id, run_id)

    channel_scores = build_channel_scores(
        topic_text=str(candidate.get("topic") or candidate.get("question") or ""),
        title=str(candidate.get("title") or ""),
        requested_channel=topic["channel"],
        personas=personas,
        reactions=reactions,
        objections=objections,
    )
    recommendation = _recommendation(candidate, responses, channel_scores)

    previous = previous_topics or []
    similarity_edges = build_similarity_edges(topic, previous)
    cluster_edges = _same_branch_edges(
        current_branch=str(topic.get("branch") or ""),
        similarity_edges=similarity_edges,
        previous_topics=previous,
    )
    assign_topic_cluster(topic, cluster_edges)
    persona_memory = build_persona_memory(personas, similarity_edges, previous)
    receipt = _receipt(
        candidate=candidate,
        responses=responses,
        source_model=source_model,
        similarity_edges=similarity_edges,
        dataset=dataset,
    )

    return AudienceRunResult(
        run_id=run_id,
        created_at=timestamp,
        topic=topic,
        personas=personas,
        reactions=reactions,
        objections=objections,
        insights=insights,
        recommendation=recommendation,
        similarity_edges=similarity_edges,
        persona_memory=persona_memory,
        receipt=receipt,
        failures=[],
    )


def summarize_snapshot_results(
    results: list[tuple[AudienceRunResult, dict[str, Any]]],
) -> dict[str, Any]:
    similarity_edges = sum(len(result.similarity_edges) for result, _ in results)
    reaction_count = sum(len(result.reactions) for result, _ in results)
    objection_count = sum(len(result.objections) for result, _ in results)
    cluster_labels = Counter(
        str(result.topic.get("cluster_label") or "unknown") for result, _ in results
    )
    return {
        "run_count": len(results),
        "reaction_count": reaction_count,
        "objection_count": objection_count,
        "similarity_edge_count": similarity_edges,
        "cluster_count": len(cluster_labels),
        "top_clusters": [
            {"label": label, "count": count}
            for label, count in cluster_labels.most_common(10)
        ],
        "runs": [
            {
                "run_id": result.run_id,
                "title": result.topic.get("title"),
                "channel": result.topic.get("channel"),
                "cluster_label": result.topic.get("cluster_label"),
                "similarity_edges": len(result.similarity_edges),
                "decision": result.recommendation.get("decision"),
                "best_channel": result.recommendation.get("best_channel"),
            }
            for result, _ in results[:10]
        ],
    }


def _topic_payload(
    dataset: SyntheticResearchDataset,
    candidate: dict[str, Any],
) -> dict[str, Any]:
    topic_id = str(candidate["id"])
    raw_topic = _by_id(dataset.topics).get(topic_id, {})
    title = str(candidate.get("title") or raw_topic.get("title") or topic_id).strip()
    question = str(
        candidate.get("topic")
        or candidate.get("question")
        or raw_topic.get("question")
        or title
    ).strip()
    channel = _normalize_channel(
        candidate.get("channel")
        or raw_topic.get("primary_channel")
        or raw_topic.get("channel")
        or "unknown"
    )
    branch = str(candidate.get("branch") or raw_topic.get("branch") or "unknown").strip()
    summary = f"{question} Branch: {branch}."
    topic_hash = hashlib.sha256(
        f"{dataset.snapshot_id}:{topic_id}:{title}:{question}".encode("utf-8")
    ).hexdigest()
    return {
        "id": f"topic-snapshot-{_slug(dataset.snapshot_id)}-{_slug(topic_id)}",
        "title": title,
        "channel": channel,
        "topic_hash": topic_hash,
        "summary": summary[:480],
        "synthetic_snapshot_id": dataset.snapshot_id,
        "synthetic_source_topic_id": topic_id,
        "branch": branch,
    }


def _persona_payload(
    archetype: dict[str, Any],
    *,
    snapshot_id: str,
    source_model: str,
    channel_preferences: list[str],
) -> dict[str, Any]:
    archetype_id = str(archetype["id"])
    lens = str(archetype.get("lens") or archetype.get("label") or "product").strip()
    label = str(archetype.get("label") or archetype.get("pl") or archetype_id).strip()
    persona_id = _persona_id(snapshot_id, archetype_id)
    skepticism = _skepticism(archetype.get("skepticism"))
    preferences = channel_preferences or _fallback_channel_preferences(lens)
    return {
        "id": persona_id,
        "name": label,
        "active": True,
        "segments": [
            "synthetic-research-snapshot",
            f"snapshot-{_slug(snapshot_id)}",
            f"lens-{_slug(lens)}",
        ],
        "goals": [
            f"Evaluate product ideas through this lens: {lens}.",
            "Separate concrete operating value from interesting but vague content.",
        ],
        "objections": [
            "Needs a clearer practical consequence for a Polish product audience.",
        ],
        "channel_preferences": preferences,
        "skepticism": skepticism,
        "model_hint": source_model,
        "model_assignment": {
            "persona_id": persona_id,
            "model": source_model,
            "seed": f"{snapshot_id}:{archetype_id}",
            "reason": SNAPSHOT_MODE,
        },
        "synthetic_archetype_id": archetype_id,
        "synthetic_archetype_pl": archetype.get("pl"),
        "synthetic_lens": lens,
    }


def _reaction_payload(
    *,
    run_id: str,
    response: dict[str, Any],
    persona_id: str,
    source_model: str,
) -> dict[str, Any]:
    fit = _int(response.get("fit"), default=50)
    stance = _int(response.get("stance"), default=0)
    channel = _normalize_channel(response.get("ch") or "unknown")
    return {
        "id": f"reaction-{run_id[:8]}-{persona_id}",
        "persona_id": persona_id,
        "stance": _stance_label(stance),
        "channel_fit": f"{channel} {_fit_strength(fit)}",
        "model": source_model,
        "summary": _clean_note(response.get("note")),
        "fit_score": fit,
        "stance_score": stance,
        "risk": _risk(response),
    }


def _objection_payload(
    *,
    run_id: str,
    response: dict[str, Any],
    persona: dict[str, Any],
    persona_id: str,
) -> dict[str, Any]:
    risk = _risk(response)
    note = _clean_note(response.get("note"))
    label = str(persona.get("label") or persona.get("pl") or response.get("a"))
    prefix = "Risk" if risk != "NONE" else "Caveat"
    return {
        "id": f"objection-{run_id[:8]}-{persona_id}",
        "persona_id": persona_id,
        "text": f"{prefix} from {label}: {note}",
        "severity": _severity(response),
    }


def _insights(
    candidate: dict[str, Any],
    responses: list[dict[str, Any]],
    archetype_by_id: dict[str, dict[str, Any]],
    snapshot_id: str,
    run_id: str,
) -> list[dict[str, Any]]:
    support_ids = [
        _persona_id(snapshot_id, str(response.get("a")))
        for response in sorted(
            responses,
            key=lambda item: (_int(item.get("fit")), _int(item.get("stance"))),
            reverse=True,
        )[:5]
    ]
    risk_counts = Counter(_risk(response) for response in responses if _risk(response) != "NONE")
    channel_counts = Counter(_normalize_channel(response.get("ch")) for response in responses)
    skeptical = [
        _persona_id(snapshot_id, str(response.get("a")))
        for response in responses
        if _int(response.get("stance")) < 0 or _risk(response) != "NONE"
    ][:5]
    branch = str(candidate.get("branch") or "unknown")
    risk_text = (
        ", ".join(f"{risk} x{count}" for risk, count in risk_counts.most_common(3))
        if risk_counts
        else "no dominant risk code"
    )
    top_channel = channel_counts.most_common(1)[0][0] if channel_counts else "unknown"
    avg_fit = _average_fit(responses)
    return [
        {
            "id": f"insight-{run_id[:8]}-fit",
            "text": (
                f"Gemini snapshot avg fit is {avg_fit:.1f}/100; "
                f"strongest response channel is {top_channel}."
            ),
            "persona_ids": support_ids,
        },
        {
            "id": f"insight-{run_id[:8]}-risk",
            "text": f"Main synthetic pushback pattern: {risk_text}.",
            "persona_ids": skeptical,
        },
        {
            "id": f"insight-{run_id[:8]}-branch",
            "text": (
                f"Topic sits in branch '{branch}' and was imported because "
                f"{candidate.get('import_reason', 'selected for research coverage')}."
            ),
            "persona_ids": [
                _persona_id(snapshot_id, archetype_id)
                for archetype_id in list(archetype_by_id)[:5]
            ],
        },
    ]


def _recommendation(
    candidate: dict[str, Any],
    responses: list[dict[str, Any]],
    channel_scores: list[dict[str, Any]],
) -> dict[str, Any]:
    avg_fit = float(candidate.get("avg_fit") or _average_fit(responses))
    controversy = float(candidate.get("controversy") or _stance_spread(responses))
    support = float(candidate.get("support") or _support_score(responses))
    decision = _decision(avg_fit=avg_fit, controversy=controversy, support=support)
    best_channel = top_channel(channel_scores)
    return {
        "decision": decision,
        "best_channel": best_channel,
        "channel_scores": channel_scores,
        "next_action": _next_action(
            decision=decision,
            title=str(candidate.get("title") or "topic"),
            branch=str(candidate.get("branch") or "unknown"),
            best_channel=best_channel,
        ),
        "rationale": (
            "Controlled Gemini synthetic research snapshot: normalized "
            "archetype responses were imported as MiroFish AudienceRun payloads."
        ),
    }


def _receipt(
    *,
    candidate: dict[str, Any],
    responses: list[dict[str, Any]],
    source_model: str,
    similarity_edges: list[dict[str, Any]],
    dataset: SyntheticResearchDataset,
) -> dict[str, Any]:
    response_count = len(responses)
    return {
        "mode": SNAPSHOT_MODE,
        "pricing": "agy_cli_no_token_receipt",
        "models": {
            source_model: {
                "calls": response_count,
                "failures": 0,
                "prompt_tokens": 0,
                "completion_tokens": 0,
                "total_tokens": 0,
                "latency_ms": 0,
            }
        },
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
            "semantic_edge_count": sum(
                1 for edge in similarity_edges if edge.get("method") in {"semantic", "hybrid"}
            ),
            "edge_count": len(similarity_edges),
        },
        "run_timed_out": False,
        "failed_persona_count": 0,
        "low_quality_persona_count": 0,
        "failure_rate": 0.0,
        "reliability_grade": "green",
        "synthetic_snapshot": {
            "snapshot_id": dataset.snapshot_id,
            "source": dataset.source,
            "source_topic_id": candidate.get("id"),
            "branch": candidate.get("branch"),
            "response_count": response_count,
            "token_receipt_available": False,
        },
    }


def _run_id(snapshot_id: str, topic_id: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"mirofish:{snapshot_id}:{topic_id}"))


def _persona_id(snapshot_id: str, archetype_id: str) -> str:
    return f"gemini-{_slug(snapshot_id)}-{_slug(archetype_id)}"


def _responses_for_topic(
    responses: list[dict[str, Any]],
    topic_id: str,
) -> list[dict[str, Any]]:
    return [response for response in responses if str(response.get("t")) == topic_id]


def _same_branch_edges(
    *,
    current_branch: str,
    similarity_edges: list[dict[str, Any]],
    previous_topics: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    previous_by_id = {str(topic.get("id")): topic for topic in previous_topics}
    return [
        edge
        for edge in similarity_edges
        if str(previous_by_id.get(str(edge.get("target_topic_id")), {}).get("branch") or "")
        == current_branch
    ]


def _channel_preferences_by_archetype(
    responses: list[dict[str, Any]],
) -> dict[str, list[str]]:
    counts: dict[str, Counter[str]] = {}
    for response in responses:
        archetype_id = str(response.get("a") or "")
        channel = _normalize_channel(response.get("ch") or "unknown")
        if not archetype_id or channel == "unknown":
            continue
        counts.setdefault(archetype_id, Counter())[channel] += 1
    return {
        archetype_id: [channel for channel, _ in counter.most_common(3)]
        for archetype_id, counter in counts.items()
    }


def _by_id(items: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {str(item.get("id")): item for item in items if item.get("id") is not None}


def _archetype_or_stub(
    archetype_by_id: dict[str, dict[str, Any]],
    archetype_id: str,
) -> dict[str, Any]:
    return archetype_by_id.get(archetype_id, {"id": archetype_id, "label": archetype_id})


def _normalize_channel(value: Any) -> str:
    channel = str(value or "unknown").strip().lower()
    return channel if channel in VALID_CHANNELS else "unknown"


def _fallback_channel_preferences(lens: str) -> list[str]:
    folded = lens.lower()
    if "legal" in folded or "govern" in folded or "risk" in folded:
        return ["blog", "podcast", "linkedin"]
    if "founder" in folded or "sales" in folded or "market" in folded:
        return ["linkedin", "twitter-x", "product-idea"]
    if "design" in folded or "user" in folded or "research" in folded:
        return ["blog", "linkedin", "podcast"]
    return ["linkedin", "blog", "podcast"]


def _stance_label(value: int) -> str:
    if value >= 2:
        return "strong_support"
    if value == 1:
        return "interested"
    if value == 0:
        return "mixed"
    if value == -1:
        return "skeptical"
    return "rejects"


def _fit_strength(value: int) -> str:
    if value >= 70:
        return "strong"
    if value >= 45:
        return "medium"
    return "weak"


def _severity(response: dict[str, Any]) -> str:
    fit = _int(response.get("fit"), default=50)
    stance = _int(response.get("stance"), default=0)
    risk = _risk(response)
    if fit < 45 or stance <= -1:
        return "high"
    if risk != "NONE" or fit < 65 or stance == 0:
        return "medium"
    return "low"


def _risk(response: dict[str, Any]) -> str:
    return str(response.get("risk") or "NONE").strip().upper() or "NONE"


def _clean_note(value: Any) -> str:
    cleaned = " ".join(str(value or "").strip().split())
    return cleaned[:360] if cleaned else "No detailed note in synthetic response."


def _skepticism(value: Any) -> float:
    raw = _int(value, default=3)
    raw = max(1, min(5, raw))
    return round(0.2 + ((raw - 1) * 0.175), 3)


def _average_fit(responses: list[dict[str, Any]]) -> float:
    if not responses:
        return 0.0
    return sum(_int(response.get("fit"), default=0) for response in responses) / len(responses)


def _stance_spread(responses: list[dict[str, Any]]) -> float:
    if not responses:
        return 0.0
    values = [_int(response.get("stance"), default=0) for response in responses]
    return float(max(values) - min(values))


def _support_score(responses: list[dict[str, Any]]) -> float:
    if not responses:
        return 0.0
    positive = sum(1 for response in responses if _int(response.get("stance"), default=0) > 0)
    return positive / len(responses)


def _decision(*, avg_fit: float, controversy: float, support: float) -> str:
    if avg_fit >= 72 and support >= 0.55 and controversy <= 1.4:
        return "publish"
    if avg_fit >= 64 or controversy > 1.4:
        return "narrow"
    if avg_fit >= 52:
        return "rewrite"
    return "abandon"


def _next_action(
    *,
    decision: str,
    title: str,
    branch: str,
    best_channel: str,
) -> str:
    if decision == "publish":
        return f"Draft '{title}' for {best_channel} and keep the {branch} angle explicit."
    if decision == "narrow":
        return f"Narrow '{title}' to one concrete PM decision before drafting for {best_channel}."
    if decision == "rewrite":
        return f"Rewrite '{title}' around the strongest risk pattern before publishing."
    return f"Save '{title}' as research context, but do not publish without a sharper wedge."


def _int(value: Any, *, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _slug(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug or "unknown"

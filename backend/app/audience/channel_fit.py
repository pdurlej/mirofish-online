"""Channel fit scoring for audience reports.

The scorer is deliberately deterministic. Model-based judges can be compared
against it later without making the core report depend on another provider.
"""

from __future__ import annotations

from typing import Any

CHANNELS = ("linkedin", "podcast", "blog", "twitter-x", "product-idea")

CHANNEL_LABELS = {
    "linkedin": "LinkedIn",
    "podcast": "Podcast",
    "blog": "Blog",
    "twitter-x": "Twitter/X",
    "product-idea": "Product idea",
}

SUGGESTED_FORMATS = {
    "linkedin": "Sharp hook, practical claim, one objection handled in public.",
    "podcast": "Conversation arc with tension, examples, and room for nuance.",
    "blog": "Structured argument with definitions, evidence, and trade-offs.",
    "twitter-x": "Short provocation or thread that can survive compression.",
    "product-idea": "Problem framing, user segment, risk, and validation next step.",
}

PROFILE_RATIONALES = {
    "linkedin": "Best when the idea has a visible professional tension or strong practical consequence.",
    "podcast": "Best when the idea needs debate, story, or trade-offs instead of a one-shot claim.",
    "blog": "Best when the idea needs structure, definitions, and evidence.",
    "twitter-x": "Best when the idea is compact, pointed, and does not need much setup.",
    "product-idea": "Best when the topic is really a product bet, validation question, or onboarding/pricing problem.",
}

TOPIC_HEURISTICS: dict[str, tuple[tuple[str, float], ...]] = {
    "linkedin": (
        ("linkedin", 18),
        ("pm", 7),
        ("product manager", 7),
        ("produktowiec", 7),
        ("founder", 6),
        ("startup", 6),
        ("controvers", 8),
        ("masturbacja", 8),
        ("framework", 5),
    ),
    "podcast": (
        ("podcast", 18),
        ("rozmowa", 8),
        ("why", 5),
        ("dlaczego", 6),
        ("czy ", 5),
        ("?", 8),
        ("trade-off", 8),
        ("spór", 8),
    ),
    "blog": (
        ("blog", 18),
        ("guide", 8),
        ("poradnik", 8),
        ("jak ", 6),
        ("roi", 8),
        ("eval", 8),
        ("analysis", 6),
        ("analiza", 6),
        ("evidence", 5),
    ),
    "twitter-x": (
        ("twitter", 18),
        ("x.com", 18),
        ("hot take", 10),
        ("one-liner", 10),
        ("krótko", 8),
        ("thread", 8),
    ),
    "product-idea": (
        ("product idea", 18),
        ("produkt", 7),
        ("feature", 8),
        ("onboarding", 10),
        ("pricing", 10),
        ("saas", 8),
        ("wallet", 8),
        ("mobywatel", 8),
        ("eudi", 8),
        ("validation", 7),
    ),
}


def build_channel_scores(
    *,
    topic_text: str,
    title: str | None = None,
    requested_channel: str = "unknown",
    personas: list[dict[str, Any]] | None = None,
    reactions: list[dict[str, Any]] | None = None,
    objections: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    text = f"{title or ''} {topic_text or ''}".lower()
    scores = {channel: 34.0 for channel in CHANNELS}
    evidence: dict[str, list[str]] = {channel: [] for channel in CHANNELS}

    _apply_persona_preferences(scores, evidence, personas or [])
    _apply_reaction_fits(scores, evidence, reactions or [], requested_channel)
    _apply_topic_heuristics(scores, evidence, text)
    _apply_objection_risk(scores, evidence, objections or [])

    if requested_channel in CHANNELS:
        scores[requested_channel] += 7
        evidence[requested_channel].append("requested channel")

    max_score = max(scores.values()) if scores else 1.0
    result: list[dict[str, Any]] = []
    for channel in CHANNELS:
        score = _clamp(round(scores[channel]), 5, 96)
        confidence = _confidence(score, max_score, evidence[channel])
        result.append(
            {
                "channel": channel,
                "label": CHANNEL_LABELS[channel],
                "score": score,
                "confidence": confidence,
                "rationale": _rationale(channel, evidence[channel]),
                "suggested_format": SUGGESTED_FORMATS[channel],
            }
        )
    return sorted(result, key=lambda item: (-int(item["score"]), item["channel"]))


def top_channel(channel_scores: list[dict[str, Any]]) -> str:
    if not channel_scores:
        return "unknown"
    return str(max(channel_scores, key=lambda item: int(item.get("score", 0))).get("channel"))


def enrich_payload_channel_scores(payload: dict[str, Any]) -> dict[str, Any]:
    recommendation = payload.get("recommendation") or {}
    if recommendation.get("channel_scores"):
        return payload

    topic = payload.get("topic") or {}
    channel_scores = build_channel_scores(
        topic_text=str(topic.get("summary") or topic.get("title") or ""),
        title=topic.get("title"),
        requested_channel=str(topic.get("channel") or "unknown"),
        personas=list(payload.get("personas") or []),
        reactions=list(payload.get("reactions") or []),
        objections=list(payload.get("objections") or []),
    )
    recommendation["channel_scores"] = channel_scores
    recommendation["best_channel"] = recommendation.get("best_channel") or top_channel(channel_scores)
    payload["recommendation"] = recommendation
    return payload


def _apply_persona_preferences(
    scores: dict[str, float],
    evidence: dict[str, list[str]],
    personas: list[dict[str, Any]],
) -> None:
    if not personas:
        return
    counts = {channel: 0 for channel in CHANNELS}
    for persona in personas:
        for channel in persona.get("channel_preferences") or []:
            if channel in counts:
                counts[channel] += 1
    max_count = max(counts.values()) if counts else 0
    if max_count <= 0:
        return
    for channel, count in counts.items():
        if count <= 0:
            continue
        scores[channel] += 24 * (count / max_count)
        evidence[channel].append(f"{count} persona preferences")


def _apply_reaction_fits(
    scores: dict[str, float],
    evidence: dict[str, list[str]],
    reactions: list[dict[str, Any]],
    requested_channel: str,
) -> None:
    if not reactions:
        return
    direct_counts = {channel: 0 for channel in CHANNELS}
    direct_strength = {channel: 0.0 for channel in CHANNELS}
    requested_strong = 0
    requested_weak = 0
    for reaction in reactions:
        fit = str(reaction.get("channel_fit") or "").lower()
        for channel in CHANNELS:
            if channel in fit:
                direct_counts[channel] += 1
                if "strong" in fit:
                    direct_strength[channel] += 10
                elif "medium" in fit:
                    direct_strength[channel] += 5
        if requested_channel in CHANNELS:
            if "strong" in fit:
                requested_strong += 1
            if "weak" in fit:
                requested_weak += 1
    for channel, count in direct_counts.items():
        if count:
            scores[channel] += min(34, (count * 9) + direct_strength[channel])
            evidence[channel].append(f"{count} explicit reaction fits")
    if requested_channel in CHANNELS and (requested_strong or requested_weak):
        scores[requested_channel] += min(18, requested_strong * 1.8)
        scores[requested_channel] -= min(16, requested_weak * 1.4)
        evidence[requested_channel].append(
            f"{requested_strong} strong / {requested_weak} weak requested-channel fits"
        )


def _apply_topic_heuristics(
    scores: dict[str, float],
    evidence: dict[str, list[str]],
    text: str,
) -> None:
    for channel, patterns in TOPIC_HEURISTICS.items():
        hits: list[str] = []
        for pattern, weight in patterns:
            if pattern in text:
                scores[channel] += weight
                hits.append(pattern)
        if hits:
            evidence[channel].append("topic signals: " + ", ".join(hits[:3]))


def _apply_objection_risk(
    scores: dict[str, float],
    evidence: dict[str, list[str]],
    objections: list[dict[str, Any]],
) -> None:
    high_count = sum(1 for objection in objections if objection.get("severity") == "high")
    if high_count < 4:
        return
    scores["blog"] += 6
    scores["podcast"] += 4
    scores["twitter-x"] -= 6
    evidence["blog"].append(f"{high_count} high-severity objections need structure")
    evidence["podcast"].append(f"{high_count} high-severity objections need discussion")
    evidence["twitter-x"].append(f"{high_count} high-severity objections reduce compression fit")


def _confidence(score: int, max_score: float, channel_evidence: list[str]) -> float:
    spread = max(0.0, float(score) - 34.0) / max(1.0, max_score - 34.0)
    evidence_bonus = min(0.25, 0.06 * len(channel_evidence))
    return round(_clamp(0.35 + (spread * 0.35) + evidence_bonus, 0.15, 0.95), 2)


def _rationale(channel: str, channel_evidence: list[str]) -> str:
    if channel_evidence:
        return f"{PROFILE_RATIONALES[channel]} Signals: {'; '.join(channel_evidence[:3])}."
    return PROFILE_RATIONALES[channel]


def _clamp(value: float | int, minimum: float | int, maximum: float | int):
    return max(minimum, min(maximum, value))

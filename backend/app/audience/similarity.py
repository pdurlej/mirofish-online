"""Audience topic similarity, clustering, and reviewer memory."""

from __future__ import annotations

import hashlib
import math
import re
import unicodedata
from typing import Any, Protocol


LEXICAL_THRESHOLD = 0.20
SEMANTIC_THRESHOLD = 0.68
SEMANTIC_ONLY_LEXICAL_FLOOR = 0.30
MAX_SIMILARITY_EDGES = 5


class EmbeddingProvider(Protocol):
    def embed_batch(self, texts: list[str], batch_size: int = 32) -> list[list[float]]:
        """Return one vector per text."""


STOPWORDS = {
    "a",
    "albo",
    "ale",
    "and",
    "as",
    "be",
    "batch",
    "bo",
    "by",
    "czy",
    "dla",
    "do",
    "e2e",
    "go",
    "i",
    "in",
    "is",
    "jak",
    "jego",
    "jej",
    "ma",
    "na",
    "nie",
    "o",
    "of",
    "or",
    "po",
    "pod",
    "przez",
    "repair",
    "run",
    "się",
    "sie",
    "test",
    "the",
    "to",
    "w",
    "we",
    "z",
    "za",
    "ze",
    "że",
}
BROAD_CONCEPTS = {"concept_pm"}
CONCEPT_LABELS = {
    "concept_ai": "AI/LLM",
    "concept_evals": "evals/ROI",
    "concept_discovery": "discovery/customer insight",
    "concept_prototype": "prototype/builder workflow",
    "concept_governance": "AI governance",
    "concept_pricing": "pricing/packaging",
    "concept_identity": "digital identity/onboarding",
}

CONCEPT_PATTERNS = {
    "concept_ai": (
        " ai ",
        " llm",
        " genai",
        " agent",
        " agenty",
        " sztuczn",
        " funkcj ai",
        " model",
    ),
    "concept_pm": (
        " pm ",
        " product manager",
        " produktow",
        " manager produktu",
        " lider produktu",
    ),
    "concept_evals": (
        " eval",
        " roi",
        " metryk",
        " jakosc",
        " jakość",
        " koszt inference",
        " udowodni",
        " dziala",
        " działa",
    ),
    "concept_discovery": (
        " discovery",
        " rozmow",
        " rozmów",
        " klient",
        " insight",
        " hipotez",
        " ryzyk",
    ),
    "concept_prototype": (
        " prototyp",
        " builder",
        " brief",
        " klikal",
        " zbudow",
    ),
    "concept_governance": (
        " ai act",
        " legal",
        " compliance",
        " prawn",
        " governance",
        " constraint",
    ),
    "concept_pricing": (
        " pricing",
        " packaging",
        " saas",
        " revenue",
        " monetyzac",
        " cen",
    ),
    "concept_identity": (
        " eudi",
        " mobywatel",
        " onboarding",
        " kyc",
        " portfel",
        " tozsamosc",
        " tożsamość",
    ),
}


def build_similarity_edges(
    topic: dict[str, Any],
    previous_topics: list[dict[str, Any]],
    *,
    embedding_provider: EmbeddingProvider | None = None,
    lexical_threshold: float = LEXICAL_THRESHOLD,
    semantic_threshold: float = SEMANTIC_THRESHOLD,
    limit: int = MAX_SIMILARITY_EDGES,
) -> list[dict[str, Any]]:
    candidates = [
        previous
        for previous in previous_topics
        if not _is_self_topic(topic, previous) and previous.get("id")
    ]
    semantic_scores = _semantic_scores(topic, candidates, embedding_provider)

    edges: list[dict[str, Any]] = []
    for index, previous in enumerate(candidates):
        lexical_score = _lexical_score(topic, previous)
        semantic_score = semantic_scores[index] if semantic_scores else None
        semantic_match = _semantic_match_allowed(
            topic,
            previous,
            lexical_score,
            semantic_score,
            semantic_threshold,
        )
        score = max(lexical_score, semantic_score or 0.0) if semantic_match else lexical_score
        if lexical_score < lexical_threshold and not semantic_match:
            continue
        method = _similarity_method(lexical_score, semantic_match, lexical_threshold)
        edges.append(
            {
                "source_topic_id": topic["id"],
                "target_topic_id": previous["id"],
                "target_title": previous.get("title") or previous["id"],
                "target_channel": previous.get("channel", "unknown"),
                "target_cluster_id": previous.get("cluster_id"),
                "target_cluster_label": previous.get("cluster_label"),
                "relationship": "similar_to",
                "score": round(score, 3),
                "method": method,
                "lexical_score": round(lexical_score, 3),
                "semantic_score": round(semantic_score, 3) if semantic_score is not None else None,
                "explanation": _edge_explanation(
                    topic,
                    previous,
                    method=method,
                    lexical_score=lexical_score,
                    semantic_score=semantic_score,
                ),
            }
        )
    return sorted(edges, key=lambda edge: edge["score"], reverse=True)[:limit]


def assign_topic_cluster(topic: dict[str, Any], similarity_edges: list[dict[str, Any]]) -> dict[str, Any]:
    if similarity_edges:
        best = similarity_edges[0]
        cluster_id = best.get("target_cluster_id") or _cluster_id(best["target_topic_id"])
        cluster_label = best.get("target_cluster_label") or best.get("target_title") or topic["title"]
    else:
        cluster_id = _cluster_id(topic["id"])
        cluster_label = topic["title"]
    topic["cluster_id"] = cluster_id
    topic["cluster_label"] = cluster_label
    return topic


def build_persona_memory(
    personas: list[dict[str, Any]],
    similarity_edges: list[dict[str, Any]],
    previous_topics: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    related_ids = {edge["target_topic_id"] for edge in similarity_edges}
    related_topics = [
        previous
        for previous in previous_topics
        if previous.get("id") in related_ids
    ]

    memory = []
    for persona in personas:
        persona_id = persona["id"]
        related_count = 0
        last_objection = ""
        last_reaction = ""
        for previous in related_topics:
            reaction = _find_by_persona(previous.get("reactions", []), persona_id)
            objection = _find_by_persona(previous.get("objections", []), persona_id)
            if reaction or objection:
                related_count += 1
            if not last_reaction and reaction:
                last_reaction = _truncate(str(reaction.get("summary") or ""))
            if not last_objection and objection:
                last_objection = _truncate(str(objection.get("text") or ""))
        memory.append(
            {
                "persona_id": persona_id,
                "related_topic_count": related_count,
                "last_related_objection": last_objection,
                "last_related_reaction_summary": last_reaction,
            }
        )
    return memory


def topic_similarity_text(topic: dict[str, Any]) -> str:
    return " ".join(
        str(topic.get(key) or "").strip()
        for key in ("title", "summary", "channel")
        if str(topic.get(key) or "").strip()
    )


def _semantic_scores(
    topic: dict[str, Any],
    previous_topics: list[dict[str, Any]],
    embedding_provider: EmbeddingProvider | None,
) -> list[float] | None:
    if not embedding_provider or not previous_topics:
        return None
    texts = [topic_similarity_text(topic), *[topic_similarity_text(previous) for previous in previous_topics]]
    try:
        embeddings = embedding_provider.embed_batch(texts)
    except Exception:  # noqa: BLE001
        return None
    if len(embeddings) != len(texts):
        return None
    current = embeddings[0]
    return [_cosine(current, previous) for previous in embeddings[1:]]


def _lexical_score(current: dict[str, Any], previous: dict[str, Any]) -> float:
    current_terms = _weighted_terms(current)
    previous_terms = _weighted_terms(previous)
    if not current_terms or not previous_terms:
        return 0.0
    intersection = sum(min(current_terms.get(term, 0), previous_terms.get(term, 0)) for term in current_terms)
    denominator = max(sum(current_terms.values()), 1)
    return intersection / denominator


def _weighted_terms(topic: dict[str, Any]) -> dict[str, int]:
    terms: dict[str, int] = {}
    for token in _tokens(str(topic.get("summary") or "")):
        terms[token] = terms.get(token, 0) + 1
    for token in _tokens(str(topic.get("title") or "")):
        terms[token] = terms.get(token, 0) + 2
    for token in _specific_concept_tokens(topic_similarity_text(topic)):
        terms[token] = terms.get(token, 0) + 3
    return terms


def _tokens(text: str) -> list[str]:
    normalized = _fold(text)
    return [
        token
        for token in re.sub(r"[^a-z0-9]+", " ", normalized).split()
        if len(token) >= 2 and not token.isdigit() and token not in STOPWORDS
    ]


def _concept_tokens(text: str) -> list[str]:
    folded = f" {_fold(text)} "
    concepts = []
    for concept, patterns in CONCEPT_PATTERNS.items():
        if any(pattern in folded for pattern in patterns):
            concepts.append(concept)
    return concepts


def _fold(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text.lower())
    return "".join(char for char in decomposed if not unicodedata.combining(char))


def _cosine(left: list[float], right: list[float]) -> float:
    numerator = sum(a * b for a, b in zip(left, right))
    left_norm = math.sqrt(sum(a * a for a in left))
    right_norm = math.sqrt(sum(b * b for b in right))
    if left_norm == 0 or right_norm == 0:
        return 0.0
    return numerator / (left_norm * right_norm)


def _similarity_method(
    lexical_score: float,
    semantic_match: bool,
    lexical_threshold: float,
) -> str:
    lexical_match = lexical_score >= lexical_threshold
    if lexical_match and semantic_match:
        return "hybrid"
    if semantic_match:
        return "semantic"
    return "lexical"


def _is_self_topic(current: dict[str, Any], previous: dict[str, Any]) -> bool:
    current_id = current.get("id")
    previous_id = previous.get("id")
    if current_id and previous_id and current_id == previous_id:
        return True
    current_hash = current.get("topic_hash")
    previous_hash = previous.get("topic_hash")
    if current_hash and previous_hash and current_hash == previous_hash:
        return True
    current_title = _normalized_title(current)
    previous_title = _normalized_title(previous)
    return bool(current_title and previous_title and current_title == previous_title)


def _semantic_match_allowed(
    current: dict[str, Any],
    previous: dict[str, Any],
    lexical_score: float,
    semantic_score: float | None,
    semantic_threshold: float,
) -> bool:
    if semantic_score is None or semantic_score < semantic_threshold:
        return False
    if lexical_score >= SEMANTIC_ONLY_LEXICAL_FLOOR:
        return True
    current_concepts = set(_specific_concept_tokens(topic_similarity_text(current)))
    previous_concepts = set(_specific_concept_tokens(topic_similarity_text(previous)))
    return bool(current_concepts & previous_concepts)


def _specific_concept_tokens(text: str) -> list[str]:
    return [concept for concept in _concept_tokens(text) if concept not in BROAD_CONCEPTS]


def _edge_explanation(
    current: dict[str, Any],
    previous: dict[str, Any],
    *,
    method: str,
    lexical_score: float,
    semantic_score: float | None,
) -> str:
    current_terms = set(_weighted_terms(current))
    previous_terms = set(_weighted_terms(previous))
    shared = sorted(current_terms & previous_terms)
    concepts = [CONCEPT_LABELS[term] for term in shared if term in CONCEPT_LABELS]
    words = [term for term in shared if not term.startswith("concept_")][:4]

    signals = []
    if concepts:
        signals.append("shared concepts: " + ", ".join(concepts[:3]))
    if words:
        signals.append("shared terms: " + ", ".join(words))
    if semantic_score is not None and method in {"semantic", "hybrid"}:
        signals.append(f"semantic score {semantic_score:.2f}")
    if lexical_score:
        signals.append(f"lexical score {lexical_score:.2f}")

    if not signals:
        return f"Connected by {method} similarity."
    return f"Connected by {method} similarity; " + "; ".join(signals) + "."


def _normalized_title(topic: dict[str, Any]) -> str:
    return " ".join(_tokens(str(topic.get("title") or "")))


def _cluster_id(seed: str) -> str:
    digest = hashlib.sha256(seed.encode("utf-8")).hexdigest()
    return f"cluster-{digest[:16]}"


def _find_by_persona(items: list[dict[str, Any]], persona_id: str) -> dict[str, Any] | None:
    for item in items:
        if item.get("persona_id") == persona_id:
            return item
    return None


def _truncate(text: str, limit: int = 220) -> str:
    cleaned = " ".join(text.split())
    if len(cleaned) <= limit:
        return cleaned
    return f"{cleaned[: limit - 1].rstrip()}..."

"""Deterministic, additive v2 reclustering plans for audience topics."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from .similarity import (
    SIMILARITY_ALGORITHM_VERSION,
    EmbeddingProvider,
    assign_topic_cluster,
    build_similarity_edges,
)


def build_recluster_plan(
    topics: Iterable[dict[str, Any]],
    *,
    embedding_provider: EmbeddingProvider | None = None,
    previous_limit: int = 25,
) -> dict[str, Any]:
    ordered = sorted(
        (dict(topic) for topic in topics if topic.get("id")),
        key=lambda topic: str(topic.get("created_at") or topic.get("updated_at") or ""),
    )
    previous: list[dict[str, Any]] = []
    planned_topics: list[dict[str, Any]] = []
    planned_edges: list[dict[str, Any]] = []

    for source in ordered:
        topic = {
            "id": str(source["id"]),
            "topic_hash": source.get("topic_hash"),
            "title": str(source.get("title") or source["id"]),
            "summary": str(source.get("summary") or ""),
            "channel": str(source.get("channel") or "unknown"),
        }
        edges = build_similarity_edges(
            topic,
            previous[:previous_limit],
            embedding_provider=embedding_provider,
        )
        assign_topic_cluster(topic, edges)
        planned_topics.append(
            {
                "topic_id": topic["id"],
                "cluster_id": topic["cluster_id"],
                "cluster_label": topic["cluster_label"],
                "cluster_version": topic["cluster_version"],
                "legacy_cluster_id": source.get("cluster_id"),
            }
        )
        planned_edges.extend(edges)
        previous.insert(0, topic)

    return {
        "algorithm_version": SIMILARITY_ALGORITHM_VERSION,
        "topics": planned_topics,
        "similarity_edges": planned_edges,
    }


def summarize_recluster_plan(plan: dict[str, Any]) -> dict[str, Any]:
    topics = list(plan.get("topics") or [])
    legacy_cluster_ids = {
        topic.get("legacy_cluster_id")
        for topic in topics
        if topic.get("legacy_cluster_id")
    }
    cluster_ids = {
        topic.get("cluster_id") for topic in topics if topic.get("cluster_id")
    }
    changed = sum(
        1
        for topic in topics
        if topic.get("legacy_cluster_id")
        and topic.get("legacy_cluster_id") != topic.get("cluster_id")
    )
    return {
        "algorithm_version": int(plan.get("algorithm_version") or 0),
        "topic_count": len(topics),
        "cluster_count": len(cluster_ids),
        "similarity_edge_count": len(plan.get("similarity_edges") or []),
        "changed_cluster_count": changed,
        "before": {
            "topic_count": len(topics),
            "cluster_count": len(legacy_cluster_ids),
        },
        "after": {
            "topic_count": len(topics),
            "cluster_count": len(cluster_ids),
            "similarity_edge_count": len(plan.get("similarity_edges") or []),
        },
    }

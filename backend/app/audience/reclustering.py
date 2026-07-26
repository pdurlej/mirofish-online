"""Deterministic, additive v2 reclustering plans for audience topics."""

from __future__ import annotations

from collections import Counter
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
        key=lambda topic: (
            str(topic.get("created_at") or topic.get("updated_at") or ""),
            str(topic["id"]),
        ),
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

    _merge_connected_components(planned_topics, planned_edges)
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
    legacy_sizes = _cluster_sizes(topics, "legacy_cluster_id")
    cluster_sizes = _cluster_sizes(topics, "cluster_id")
    return {
        "algorithm_version": int(plan.get("algorithm_version") or 0),
        "topic_count": len(topics),
        "cluster_count": len(cluster_ids),
        "similarity_edge_count": len(plan.get("similarity_edges") or []),
        "changed_cluster_count": changed,
        "before": {
            "topic_count": len(topics),
            "cluster_count": len(legacy_cluster_ids),
            "singleton_cluster_count": _singleton_count(legacy_sizes),
            "largest_cluster_size": max(legacy_sizes.values(), default=0),
        },
        "after": {
            "topic_count": len(topics),
            "cluster_count": len(cluster_ids),
            "similarity_edge_count": len(plan.get("similarity_edges") or []),
            "singleton_cluster_count": _singleton_count(cluster_sizes),
            "largest_cluster_size": max(cluster_sizes.values(), default=0),
        },
    }


def _merge_connected_components(
    topics: list[dict[str, Any]],
    edges: list[dict[str, Any]],
) -> None:
    """Merge every topic connected by a strong cluster edge."""
    order = {topic["topic_id"]: index for index, topic in enumerate(topics)}
    parent = {topic_id: topic_id for topic_id in order}

    def find(topic_id: str) -> str:
        root = topic_id
        while parent[root] != root:
            root = parent[root]
        while parent[topic_id] != topic_id:
            next_id = parent[topic_id]
            parent[topic_id] = root
            topic_id = next_id
        return root

    def union(left_id: str, right_id: str) -> None:
        left_root = find(left_id)
        right_root = find(right_id)
        if left_root == right_root:
            return
        if order[left_root] <= order[right_root]:
            parent[right_root] = left_root
        else:
            parent[left_root] = right_root

    for edge in edges:
        source_id = str(edge.get("source_topic_id") or "")
        target_id = str(edge.get("target_topic_id") or "")
        if (
            edge.get("cluster_match")
            and source_id in parent
            and target_id in parent
        ):
            union(source_id, target_id)

    topics_by_id = {topic["topic_id"]: topic for topic in topics}
    component_identity: dict[str, tuple[str, str]] = {}
    for topic_id in order:
        root = find(topic_id)
        seed = topics_by_id[root]
        component_identity[root] = (
            str(seed["cluster_id"]),
            str(seed["cluster_label"]),
        )

    for topic in topics:
        cluster_id, cluster_label = component_identity[find(topic["topic_id"])]
        topic["cluster_id"] = cluster_id
        topic["cluster_label"] = cluster_label

    for edge in edges:
        target = topics_by_id.get(str(edge.get("target_topic_id") or ""))
        if target:
            edge["target_cluster_id"] = target["cluster_id"]
            edge["target_cluster_label"] = target["cluster_label"]


def _cluster_sizes(
    topics: list[dict[str, Any]],
    field: str,
) -> Counter[str]:
    return Counter(
        str(topic[field])
        for topic in topics
        if topic.get(field)
    )


def _singleton_count(cluster_sizes: Counter[str]) -> int:
    return sum(1 for size in cluster_sizes.values() if size == 1)

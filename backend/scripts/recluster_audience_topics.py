#!/usr/bin/env python
"""Preview or add v2 audience similarity and cluster relationships."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT))

from app.audience.reclustering import build_recluster_plan, summarize_recluster_plan  # noqa: E402
from app.storage.embedding_service import EmbeddingService  # noqa: E402
from app.storage.neo4j_storage import Neo4jStorage  # noqa: E402


def main() -> int:
    args = _parse_args()
    if args.apply and args.confirm_version != 2:
        raise SystemExit(
            "Refusing apply: pass --confirm-version 2 after reviewing dry-run output"
        )

    storage = Neo4jStorage()
    try:
        topics = _read_topics(storage, args.limit)
        embedding_provider = (
            None if args.lexical_only else EmbeddingService(max_retries=1, timeout=5)
        )
        plan = build_recluster_plan(
            topics,
            embedding_provider=embedding_provider,
            previous_limit=args.previous_limit,
        )
        if args.apply:
            _apply_plan(storage, plan)
        summary = summarize_recluster_plan(plan) | {
            "mode": "apply" if args.apply else "dry-run",
            "legacy_relationships_preserved": True,
        }
        print(json.dumps(summary, ensure_ascii=False, indent=2))
    finally:
        storage.close()
    return 0


def _read_topics(storage: Any, limit: int) -> list[dict[str, Any]]:
    def _read(tx):
        result = tx.run(
            """
            MATCH (t:AudienceTopic)
            OPTIONAL MATCH (r:AudienceRun)-[:TESTED_TOPIC]->(t)
            WITH t, min(r.created_at) AS created_at
            RETURN t.topic_id AS id,
                   t.topic_hash AS topic_hash,
                   t.title AS title,
                   t.summary AS summary,
                   t.channel AS channel,
                   t.cluster_id AS cluster_id,
                   created_at,
                   t.updated_at AS updated_at
            ORDER BY coalesce(created_at, t.updated_at) ASC
            LIMIT $limit
            """,
            limit=limit,
        )
        return [dict(record) for record in result]

    with storage._driver.session() as session:  # noqa: SLF001
        return storage._call_with_retry(session.execute_read, _read)  # noqa: SLF001


def _apply_plan(storage: Any, plan: dict[str, Any]) -> None:
    def _write(tx):
        for topic in plan.get("topics") or []:
            tx.run(
                """
                MATCH (t:AudienceTopic {topic_id: $topic_id})
                SET t.cluster_v2_id = $cluster_id,
                    t.cluster_v2_label = $cluster_label,
                    t.cluster_version = 2
                MERGE (c:AudienceTopicCluster {cluster_id: $cluster_id})
                SET c.label = $cluster_label,
                    c.algorithm_version = 2
                MERGE (t)-[:IN_CLUSTER_V2]->(c)
                """,
                topic_id=topic["topic_id"],
                cluster_id=topic["cluster_id"],
                cluster_label=topic["cluster_label"],
            )
        for edge in plan.get("similarity_edges") or []:
            tx.run(
                """
                MATCH (src:AudienceTopic {topic_id: $source_topic_id})
                MATCH (tgt:AudienceTopic {topic_id: $target_topic_id})
                MERGE (src)-[rel:SIMILAR_TO_V2]->(tgt)
                SET rel.score = $score,
                    rel.method = $method,
                    rel.lexical_score = $lexical_score,
                    rel.semantic_score = $semantic_score,
                    rel.explanation = $explanation,
                    rel.algorithm_version = 2
                """,
                source_topic_id=edge["source_topic_id"],
                target_topic_id=edge["target_topic_id"],
                score=edge["score"],
                method=edge.get("method", "lexical"),
                lexical_score=edge.get("lexical_score"),
                semantic_score=edge.get("semantic_score"),
                explanation=edge.get("explanation"),
            )

    with storage._driver.session() as session:  # noqa: SLF001
        storage._call_with_retry(session.execute_write, _write)  # noqa: SLF001


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Preview additive audience graph v2 relationships. Dry-run is the default; "
            "--apply also requires --confirm-version 2."
        )
    )
    parser.add_argument("--limit", type=int, default=300)
    parser.add_argument("--previous-limit", type=int, default=25)
    parser.add_argument("--lexical-only", action="store_true")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--confirm-version", type=int, default=None)
    return parser.parse_args()


if __name__ == "__main__":
    raise SystemExit(main())

"""Audience Graph persistence contracts."""

from __future__ import annotations

import json
from collections import OrderedDict
from typing import Any, Protocol

from .audience_run import AudienceRunResult
from .channel_fit import build_channel_scores, enrich_payload_channel_scores


class AudienceGraphStore(Protocol):
    def write_run(self, result: AudienceRunResult) -> dict[str, Any]:
        """Persist an audience run and return structured write counts."""

    def read_run(self, run_id: str) -> dict[str, Any] | None:
        """Return a stored audience run summary."""

    def previous_topics(self, limit: int = 25) -> list[dict[str, Any]]:
        """Return recent topics for similarity checks."""

    def list_runs(self, limit: int = 25) -> list[dict[str, Any]]:
        """Return recent audience runs for history UI."""

    def graph_snapshot(
        self,
        *,
        limit: int = 120,
        min_score: float = 0.35,
        include_personas: bool = False,
    ) -> dict[str, Any]:
        """Return a sanitized topic/cluster graph snapshot for UI rendering."""


class InMemoryAudienceGraphStore:
    def __init__(self, *, max_runs: int = 128) -> None:
        self._max_runs = max(1, int(max_runs))
        self._runs: OrderedDict[str, dict[str, Any]] = OrderedDict()

    def write_run(self, result: AudienceRunResult) -> dict[str, Any]:
        payload = result.to_dict()
        self._runs[result.run_id] = payload
        self._runs.move_to_end(result.run_id)
        while len(self._runs) > self._max_runs:
            self._runs.popitem(last=False)
        return _write_counts(payload)

    def read_run(self, run_id: str) -> dict[str, Any] | None:
        payload = self._runs.get(run_id)
        return _enrich_payload_for_read(payload) if payload else None

    def previous_topics(self, limit: int = 25) -> list[dict[str, Any]]:
        values = _latest_unique_payloads(self._runs.values(), limit)
        return [_previous_topic_payload(payload) for payload in values]

    def list_runs(self, limit: int = 25) -> list[dict[str, Any]]:
        values = list(self._runs.values())[-limit:]
        return [
            _history_summary(_enrich_payload_for_read(payload))
            for payload in reversed(values)
        ]

    def graph_snapshot(
        self,
        *,
        limit: int = 120,
        min_score: float = 0.35,
        include_personas: bool = False,
    ) -> dict[str, Any]:
        values = _latest_unique_payloads(self._runs.values(), limit)
        return _graph_snapshot_from_payloads(
            values,
            min_score=min_score,
            include_personas=include_personas,
        )


class Neo4jAudienceGraphStore:
    """Neo4j writer for structured audience runs.

    This deliberately stores structured summaries and decisions, not raw prompts,
    raw provider responses, headers, or API keys.
    """

    def __init__(self, neo4j_storage: Any) -> None:
        self._storage = neo4j_storage

    def write_run(self, result: AudienceRunResult) -> dict[str, Any]:
        payload = result.to_dict()

        def _write(tx):
            tx.run(
                """
                MERGE (r:AudienceRun {run_id: $run_id})
                SET r.created_at = $created_at,
                    r.payload_json = $payload_json,
                    r.mode = $mode,
                    r.total_tokens = $total_tokens,
                    r.failure_rate = $failure_rate,
                    r.reliability_grade = $reliability_grade
                MERGE (t:AudienceTopic {topic_id: $topic_id})
                SET t.title = $title,
                    t.channel = $channel,
                    t.topic_hash = $topic_hash,
                    t.summary = $summary,
                    t.cluster_version = $cluster_version,
                    t.updated_at = $created_at
                MERGE (r)-[:TESTED_TOPIC]->(t)
                """,
                run_id=payload["run_id"],
                created_at=payload["created_at"],
                payload_json=json.dumps(payload, ensure_ascii=False),
                mode=payload.get("receipt", {}).get("mode", "unknown"),
                total_tokens=payload.get("receipt", {})
                .get("usage", {})
                .get("total_tokens", 0),
                failure_rate=payload.get("receipt", {}).get("failure_rate", 0.0),
                reliability_grade=payload.get("receipt", {}).get(
                    "reliability_grade", "unknown"
                ),
                topic_id=payload["topic"]["id"],
                title=payload["topic"]["title"],
                channel=payload["topic"]["channel"],
                topic_hash=payload["topic"]["topic_hash"],
                summary=payload["topic"]["summary"],
                cluster_version=payload["topic"].get("cluster_version", 1),
            )
            cluster_id = payload["topic"].get("cluster_id")
            cluster_label = payload["topic"].get("cluster_label")
            cluster_version = int(payload["topic"].get("cluster_version") or 1)
            if cluster_id and cluster_label:
                if cluster_version >= 2:
                    tx.run(
                        """
                        MATCH (t:AudienceTopic {topic_id: $topic_id})
                        SET t.cluster_v2_id = $cluster_id,
                            t.cluster_v2_label = $cluster_label,
                            t.cluster_version = 2
                        MERGE (c:AudienceTopicCluster {cluster_id: $cluster_id})
                        ON CREATE SET c.created_at = $created_at
                        SET c.updated_at = $created_at,
                            c.label = $cluster_label,
                            c.algorithm_version = 2
                        MERGE (t)-[:IN_CLUSTER_V2]->(c)
                        """,
                        topic_id=payload["topic"]["id"],
                        cluster_id=cluster_id,
                        cluster_label=cluster_label,
                        created_at=payload["created_at"],
                    )
                else:
                    tx.run(
                        """
                        MATCH (t:AudienceTopic {topic_id: $topic_id})
                        SET t.cluster_id = $cluster_id,
                            t.cluster_label = $cluster_label
                        MERGE (c:AudienceTopicCluster {cluster_id: $cluster_id})
                        ON CREATE SET c.label = $cluster_label,
                                      c.created_at = $created_at
                        SET c.updated_at = $created_at,
                            c.label = coalesce(c.label, $cluster_label)
                        MERGE (t)-[:IN_CLUSTER]->(c)
                        """,
                        topic_id=payload["topic"]["id"],
                        cluster_id=cluster_id,
                        cluster_label=cluster_label,
                        created_at=payload["created_at"],
                    )
            for persona in payload["personas"]:
                tx.run(
                    """
                    MERGE (p:AudiencePersona {persona_id: $persona_id})
                    SET p.name = $name,
                        p.segments = $segments,
                        p.skepticism = $skepticism,
                        p.model = $model
                    WITH p
                    MATCH (r:AudienceRun {run_id: $run_id})
                    MERGE (r)-[:USED_PERSONA]->(p)
                    """,
                    run_id=payload["run_id"],
                    persona_id=persona["id"],
                    name=persona["name"],
                    segments=persona["segments"],
                    skepticism=persona["skepticism"],
                    model=persona["model_assignment"]["model"],
                )
            for reaction in payload["reactions"]:
                tx.run(
                    """
                    MATCH (r:AudienceRun {run_id: $run_id})
                    MATCH (p:AudiencePersona {persona_id: $persona_id})
                    MERGE (a:AudienceReaction {reaction_id: $reaction_id})
                    SET a.stance = $stance,
                        a.channel_fit = $channel_fit,
                        a.model = $model,
                        a.summary = $summary
                    MERGE (r)-[:HAS_REACTION]->(a)
                    MERGE (p)-[:GAVE_REACTION]->(a)
                    """,
                    run_id=payload["run_id"],
                    persona_id=reaction["persona_id"],
                    reaction_id=reaction["id"],
                    stance=reaction["stance"],
                    channel_fit=reaction["channel_fit"],
                    model=reaction["model"],
                    summary=reaction["summary"],
                )
            for objection in payload["objections"]:
                tx.run(
                    """
                    MATCH (r:AudienceRun {run_id: $run_id})
                    MATCH (p:AudiencePersona {persona_id: $persona_id})
                    MERGE (o:AudienceObjection {objection_id: $objection_id})
                    SET o.text = $text,
                        o.severity = $severity
                    MERGE (r)-[:HAS_OBJECTION]->(o)
                    MERGE (p)-[:RAISED_OBJECTION]->(o)
                    """,
                    run_id=payload["run_id"],
                    persona_id=objection["persona_id"],
                    objection_id=objection["id"],
                    text=objection["text"],
                    severity=objection["severity"],
                )
            for insight in payload["insights"]:
                tx.run(
                    """
                    MATCH (r:AudienceRun {run_id: $run_id})
                    MERGE (i:AudienceInsight {insight_id: $insight_id})
                    SET i.text = $text,
                        i.persona_ids = $persona_ids
                    MERGE (r)-[:HAS_INSIGHT]->(i)
                    """,
                    run_id=payload["run_id"],
                    insight_id=insight["id"],
                    text=insight["text"],
                    persona_ids=insight["persona_ids"],
                )
            tx.run(
                """
                MATCH (r:AudienceRun {run_id: $run_id})
                MERGE (rec:AudienceRecommendation {run_id: $run_id})
                SET rec.decision = $decision,
                    rec.best_channel = $best_channel,
                    rec.next_action = $next_action,
                    rec.rationale = $rationale
                MERGE (r)-[:HAS_RECOMMENDATION]->(rec)
                """,
                run_id=payload["run_id"],
                decision=payload["recommendation"]["decision"],
                best_channel=payload["recommendation"]["best_channel"],
                next_action=payload["recommendation"]["next_action"],
                rationale=payload["recommendation"]["rationale"],
            )
            for edge in payload["similarity_edges"]:
                relationship_type = (
                    "SIMILAR_TO_V2"
                    if int(edge.get("algorithm_version") or 1) >= 2
                    else "SIMILAR_TO"
                )
                query = f"""
                MATCH (src:AudienceTopic {{topic_id: $source_topic_id}})
                MATCH (tgt:AudienceTopic {{topic_id: $target_topic_id}})
                MERGE (src)-[rel:{relationship_type}]->(tgt)
                SET rel.score = $score,
                    rel.method = $method,
                    rel.lexical_score = $lexical_score,
                    rel.semantic_score = $semantic_score,
                    rel.explanation = $explanation,
                    rel.algorithm_version = $algorithm_version
                """
                tx.run(
                    query,
                    source_topic_id=edge["source_topic_id"],
                    target_topic_id=edge["target_topic_id"],
                    score=edge["score"],
                    method=edge.get("method", "lexical"),
                    lexical_score=edge.get("lexical_score"),
                    semantic_score=edge.get("semantic_score"),
                    explanation=edge.get("explanation"),
                    algorithm_version=edge.get("algorithm_version", 1),
                )

        with self._storage._driver.session() as session:  # noqa: SLF001
            self._storage._call_with_retry(session.execute_write, _write)  # noqa: SLF001

        return _write_counts(payload)

    def read_run(self, run_id: str) -> dict[str, Any] | None:
        def _read(tx):
            result = tx.run(
                """
                MATCH (r:AudienceRun {run_id: $run_id})
                OPTIONAL MATCH (r)-[:TESTED_TOPIC]->(t:AudienceTopic)
                OPTIONAL MATCH (t)-[sim_v2:SIMILAR_TO_V2]->(target_v2:AudienceTopic)
                RETURN r.payload_json AS payload_json,
                       coalesce(t.cluster_v2_id, t.cluster_id) AS cluster_id,
                       coalesce(t.cluster_v2_label, t.cluster_label) AS cluster_label,
                       coalesce(t.cluster_version, 1) AS cluster_version,
                       collect(DISTINCT {
                           source_topic_id: t.topic_id,
                           target_topic_id: target_v2.topic_id,
                           target_title: target_v2.title,
                           target_channel: target_v2.channel,
                           target_cluster_id: coalesce(target_v2.cluster_v2_id, target_v2.cluster_id),
                           target_cluster_label: coalesce(target_v2.cluster_v2_label, target_v2.cluster_label),
                           score: sim_v2.score,
                           method: sim_v2.method,
                           lexical_score: sim_v2.lexical_score,
                           semantic_score: sim_v2.semantic_score,
                           explanation: sim_v2.explanation,
                           algorithm_version: 2
                       }) AS similarity_edges_v2
                """,
                run_id=run_id,
            )
            record = result.single()
            if record and record["payload_json"]:
                record_data = dict(record)
                payload = _enrich_payload_for_read(json.loads(record["payload_json"]))
                _overlay_cluster_from_record(payload, record_data)
                if int(record_data.get("cluster_version") or 1) >= 2:
                    payload["similarity_edges"] = _preferred_similarity_edges(
                        list(record_data.get("similarity_edges_v2") or []),
                        v2_source_ids={
                            str((payload.get("topic") or {}).get("id") or "")
                        },
                    )
                return payload

            result = tx.run(
                """
                MATCH (r:AudienceRun {run_id: $run_id})
                OPTIONAL MATCH (r)-[:TESTED_TOPIC]->(t:AudienceTopic)
                OPTIONAL MATCH (r)-[:HAS_REACTION]->(reaction:AudienceReaction)
                OPTIONAL MATCH (r)-[:HAS_OBJECTION]->(objection:AudienceObjection)
                OPTIONAL MATCH (r)-[:HAS_INSIGHT]->(insight:AudienceInsight)
                OPTIONAL MATCH (r)-[:HAS_RECOMMENDATION]->(rec:AudienceRecommendation)
                RETURN r.run_id AS run_id,
                       t.title AS title,
                       t.channel AS channel,
                       count(DISTINCT reaction) AS reaction_count,
                       count(DISTINCT objection) AS objection_count,
                       count(DISTINCT insight) AS insight_count,
                       rec.decision AS decision,
                       rec.best_channel AS best_channel,
                       rec.next_action AS next_action
                """,
                run_id=run_id,
            )
            record = result.single()
            return dict(record) if record and record["run_id"] else None

        with self._storage._driver.session() as session:  # noqa: SLF001
            return self._storage._call_with_retry(session.execute_read, _read)  # noqa: SLF001

    def previous_topics(self, limit: int = 25) -> list[dict[str, Any]]:
        def _read(tx):
            result = tx.run(
                """
                MATCH (t:AudienceTopic)
                OPTIONAL MATCH (r:AudienceRun)-[:TESTED_TOPIC]->(t)
                WITH t, r
                ORDER BY r.created_at DESC
                WITH t, head(collect(r)) AS latest_run
                WHERE latest_run IS NOT NULL
                ORDER BY coalesce(t.updated_at, latest_run.created_at) DESC
                LIMIT $limit
                CALL {
                    WITH latest_run
                    OPTIONAL MATCH (latest_run)-[:HAS_REACTION]->(reaction:AudienceReaction)
                    OPTIONAL MATCH (persona:AudiencePersona)-[:GAVE_REACTION]->(reaction)
                    RETURN collect(DISTINCT CASE
                        WHEN reaction IS NULL OR persona IS NULL THEN null
                        ELSE {
                            persona_id: persona.persona_id,
                            summary: reaction.summary
                        }
                    END) AS reactions
                }
                CALL {
                    WITH latest_run
                    OPTIONAL MATCH (latest_run)-[:HAS_OBJECTION]->(objection:AudienceObjection)
                    OPTIONAL MATCH (persona:AudiencePersona)-[:RAISED_OBJECTION]->(objection)
                    RETURN collect(DISTINCT CASE
                        WHEN objection IS NULL OR persona IS NULL THEN null
                        ELSE {
                            persona_id: persona.persona_id,
                            text: objection.text
                        }
                    END) AS objections
                }
                RETURN latest_run.created_at AS created_at,
                       t.topic_id AS id,
                       t.topic_hash AS topic_hash,
                       t.summary AS summary,
                       t.title AS title,
                       t.channel AS channel,
                       coalesce(t.cluster_v2_id, t.cluster_id) AS cluster_id,
                       coalesce(t.cluster_v2_label, t.cluster_label) AS cluster_label,
                       coalesce(t.cluster_version, 1) AS cluster_version,
                       reactions AS reactions,
                       objections AS objections
                """,
                limit=limit,
            )
            return [_previous_topic_from_record(dict(record)) for record in result]

        with self._storage._driver.session() as session:  # noqa: SLF001
            return self._storage._call_with_retry(session.execute_read, _read)  # noqa: SLF001

    def list_runs(self, limit: int = 25) -> list[dict[str, Any]]:
        def _read(tx):
            result = tx.run(
                """
                MATCH (r:AudienceRun)-[:TESTED_TOPIC]->(t:AudienceTopic)
                OPTIONAL MATCH (r)-[:HAS_RECOMMENDATION]->(rec:AudienceRecommendation)
                OPTIONAL MATCH (r)-[:HAS_REACTION]->(reaction:AudienceReaction)
                OPTIONAL MATCH (t)-[sim_v2:SIMILAR_TO_V2]->(target_v2:AudienceTopic)
                OPTIONAL MATCH (t)-[sim_v1:SIMILAR_TO]->(target_v1:AudienceTopic)
                RETURN r.run_id AS run_id,
                       r.created_at AS created_at,
                       r.mode AS mode,
                       r.total_tokens AS total_tokens,
                       r.failure_rate AS failure_rate,
                       r.reliability_grade AS reliability_grade,
                       r.payload_json AS payload_json,
                       t.title AS title,
                       t.channel AS channel,
                       coalesce(t.cluster_v2_label, t.cluster_label) AS cluster_label,
                       coalesce(t.cluster_version, 1) AS cluster_version,
                       rec.decision AS decision,
                       rec.best_channel AS best_channel,
                       rec.next_action AS next_action,
                       count(DISTINCT reaction) AS reaction_count,
                       collect(DISTINCT {
                           target_topic_id: target_v2.topic_id,
                           title: target_v2.title,
                           score: sim_v2.score,
                           method: sim_v2.method,
                           explanation: sim_v2.explanation,
                           algorithm_version: 2
                       }) AS similar_topics_v2,
                       collect(DISTINCT {
                           target_topic_id: target_v1.topic_id,
                           title: target_v1.title,
                           score: sim_v1.score,
                           method: sim_v1.method,
                           explanation: sim_v1.explanation,
                           algorithm_version: 1
                       }) AS similar_topics_v1
                ORDER BY r.created_at DESC
                LIMIT $limit
                """,
                limit=limit,
            )
            return [_neo4j_history_summary(dict(record)) for record in result]

        with self._storage._driver.session() as session:  # noqa: SLF001
            return self._storage._call_with_retry(session.execute_read, _read)  # noqa: SLF001

    def graph_snapshot(
        self,
        *,
        limit: int = 120,
        min_score: float = 0.35,
        include_personas: bool = False,
    ) -> dict[str, Any]:
        def _read(tx):
            result = tx.run(
                """
                MATCH (t:AudienceTopic)
                OPTIONAL MATCH (r:AudienceRun)-[:TESTED_TOPIC]->(t)
                WITH t, r
                ORDER BY r.created_at DESC
                WITH t, head(collect(r)) AS latest_run
                WHERE latest_run IS NOT NULL
                OPTIONAL MATCH (latest_run)-[:HAS_RECOMMENDATION]->(rec:AudienceRecommendation)
                OPTIONAL MATCH (t)-[:IN_CLUSTER_V2]->(cluster_v2:AudienceTopicCluster)
                OPTIONAL MATCH (t)-[:IN_CLUSTER]->(cluster_v1:AudienceTopicCluster)
                WITH latest_run, t, rec,
                     head(collect(DISTINCT cluster_v2)) AS cluster_v2,
                     head(collect(DISTINCT cluster_v1)) AS cluster_v1
                ORDER BY coalesce(t.updated_at, latest_run.created_at) DESC
                LIMIT $limit
                WITH collect({
                    run_id: latest_run.run_id,
                    created_at: latest_run.created_at,
                    total_tokens: latest_run.total_tokens,
                    failure_rate: latest_run.failure_rate,
                    reliability_grade: latest_run.reliability_grade,
                    topic_id: t.topic_id,
                    title: t.title,
                    channel: t.channel,
                    summary: t.summary,
                    cluster_id: coalesce(t.cluster_v2_id, t.cluster_id, cluster_v2.cluster_id, cluster_v1.cluster_id),
                    cluster_label: coalesce(t.cluster_v2_label, t.cluster_label, cluster_v2.label, cluster_v1.label),
                    cluster_version: coalesce(t.cluster_version, 1),
                    decision: rec.decision,
                    best_channel: rec.best_channel,
                    next_action: rec.next_action
                }) AS topic_rows
                WITH topic_rows, [row IN topic_rows | row.topic_id] AS topic_ids
                UNWIND topic_rows AS row
                MATCH (src:AudienceTopic {topic_id: row.topic_id})
                OPTIONAL MATCH (src)-[sim_v2:SIMILAR_TO_V2]->(target_v2:AudienceTopic)
                WHERE sim_v2.score >= $min_score AND target_v2.topic_id IN topic_ids
                OPTIONAL MATCH (src)-[sim_v1:SIMILAR_TO]->(target_v1:AudienceTopic)
                WHERE sim_v1.score >= $min_score AND target_v1.topic_id IN topic_ids
                WITH topic_rows, collect(DISTINCT {
                    source_topic_id: row.topic_id,
                    target_topic_id: target_v2.topic_id,
                    target_title: target_v2.title,
                    score: sim_v2.score,
                    method: sim_v2.method,
                    lexical_score: sim_v2.lexical_score,
                    semantic_score: sim_v2.semantic_score,
                    explanation: sim_v2.explanation,
                    algorithm_version: 2
                }) + collect(DISTINCT {
                    source_topic_id: row.topic_id,
                    target_topic_id: target_v1.topic_id,
                    target_title: target_v1.title,
                    score: sim_v1.score,
                    method: sim_v1.method,
                    lexical_score: sim_v1.lexical_score,
                    semantic_score: sim_v1.semantic_score,
                    explanation: sim_v1.explanation,
                    algorithm_version: 1
                }) AS similarity_edges
                RETURN topic_rows AS topic_rows,
                       [edge IN similarity_edges WHERE edge.target_topic_id IS NOT NULL] AS similarity_edges
                """,
                limit=limit,
                min_score=min_score,
            )
            record = result.single()
            if not record:
                return _graph_snapshot_from_rows(
                    [], [], include_personas=include_personas
                )
            return _graph_snapshot_from_rows(
                list(record["topic_rows"] or []),
                list(record["similarity_edges"] or []),
                include_personas=include_personas,
            )

        with self._storage._driver.session() as session:  # noqa: SLF001
            snapshot = self._storage._call_with_retry(session.execute_read, _read)  # noqa: SLF001
        snapshot["filters"]["limit"] = limit
        snapshot["filters"]["min_score"] = min_score
        snapshot["filters"]["include_personas"] = include_personas
        return snapshot


def _latest_unique_payloads(
    payloads: Any,
    limit: int,
) -> list[dict[str, Any]]:
    unique: list[dict[str, Any]] = []
    seen: set[str] = set()
    for payload in reversed(list(payloads)):
        topic_id = str((payload.get("topic") or {}).get("id") or "")
        if not topic_id or topic_id in seen:
            continue
        seen.add(topic_id)
        unique.append(payload)
        if len(unique) >= limit:
            break
    return unique


def _dedupe_topic_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    unique: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in rows:
        topic_id = str(row.get("topic_id") or "")
        if not topic_id or topic_id in seen:
            continue
        seen.add(topic_id)
        unique.append(row)
    return unique


def _preferred_similarity_edges(
    edges: list[dict[str, Any]],
    *,
    v2_source_ids: set[str] | None = None,
) -> list[dict[str, Any]]:
    valid = [
        edge
        for edge in edges
        if edge.get("source_topic_id") and edge.get("target_topic_id")
    ]
    v2_sources = set(v2_source_ids or set()) | {
        str(edge["source_topic_id"])
        for edge in valid
        if int(edge.get("algorithm_version") or 1) >= 2
    }
    preferred = [
        edge
        for edge in valid
        if str(edge["source_topic_id"]) not in v2_sources
        or int(edge.get("algorithm_version") or 1) >= 2
    ]
    by_pair: dict[tuple[str, str], dict[str, Any]] = {}
    for edge in preferred:
        pair = (str(edge["source_topic_id"]), str(edge["target_topic_id"]))
        current = by_pair.get(pair)
        if current is None or (
            int(edge.get("algorithm_version") or 1),
            _safe_float(edge.get("score")),
        ) > (
            int(current.get("algorithm_version") or 1),
            _safe_float(current.get("score")),
        ):
            by_pair[pair] = edge
    return sorted(
        by_pair.values(),
        key=lambda edge: _safe_float(edge.get("score")),
        reverse=True,
    )


def _write_counts(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "run_id": payload["run_id"],
        "topics": 1,
        "personas": len(payload["personas"]),
        "reactions": len(payload["reactions"]),
        "objections": len(payload["objections"]),
        "insights": len(payload["insights"]),
        "recommendations": 1,
        "similarity_edges": len(payload["similarity_edges"]),
    }


def _graph_snapshot_from_payloads(
    payloads: list[dict[str, Any]],
    *,
    min_score: float,
    include_personas: bool,
) -> dict[str, Any]:
    topic_rows: list[dict[str, Any]] = []
    selected_ids: set[str] = set()
    for payload in payloads:
        topic = payload.get("topic") or {}
        topic_id = topic.get("id")
        if not topic_id:
            continue
        selected_ids.add(topic_id)
        receipt = payload.get("receipt") or {}
        recommendation = payload.get("recommendation") or {}
        topic_rows.append(
            {
                "run_id": payload.get("run_id"),
                "created_at": payload.get("created_at"),
                "total_tokens": receipt.get("usage", {}).get("total_tokens", 0),
                "failure_rate": receipt.get("failure_rate", 0.0),
                "reliability_grade": receipt.get("reliability_grade", "unknown"),
                "topic_id": topic_id,
                "title": topic.get("title"),
                "channel": topic.get("channel"),
                "cluster_id": topic.get("cluster_id"),
                "cluster_label": topic.get("cluster_label"),
                "cluster_version": topic.get("cluster_version", 1),
                "decision": recommendation.get("decision"),
                "best_channel": recommendation.get("best_channel"),
                "next_action": recommendation.get("next_action"),
            }
        )

    similarity_edges: list[dict[str, Any]] = []
    for payload in payloads:
        for edge in payload.get("similarity_edges", []):
            score = _safe_float(edge.get("score"))
            if score < min_score:
                continue
            source_id = edge.get("source_topic_id")
            target_id = edge.get("target_topic_id")
            if source_id in selected_ids and target_id in selected_ids:
                similarity_edges.append(edge)

    snapshot = _graph_snapshot_from_rows(
        topic_rows,
        similarity_edges,
        include_personas=include_personas,
    )
    snapshot["filters"]["limit"] = len(topic_rows)
    snapshot["filters"]["min_score"] = min_score
    snapshot["filters"]["include_personas"] = include_personas
    return snapshot


def _graph_snapshot_from_rows(
    topic_rows: list[dict[str, Any]],
    similarity_edges: list[dict[str, Any]],
    *,
    include_personas: bool,
) -> dict[str, Any]:
    topic_rows = _dedupe_topic_rows(topic_rows)
    v2_source_ids = {
        str(row.get("topic_id"))
        for row in topic_rows
        if int(row.get("cluster_version") or 1) >= 2 and row.get("topic_id")
    }
    similarity_edges = _preferred_similarity_edges(
        similarity_edges,
        v2_source_ids=v2_source_ids,
    )
    topic_ids = {str(row.get("topic_id")) for row in topic_rows if row.get("topic_id")}
    nodes: dict[str, dict[str, Any]] = {}
    cluster_topic_counts: dict[str, int] = {}
    channels: set[str] = set()

    for row in topic_rows:
        topic_id = str(row.get("topic_id") or "")
        if not topic_id:
            continue
        cluster_id = str(row.get("cluster_id") or f"singleton-{topic_id}")
        cluster_label = str(
            row.get("cluster_label") or row.get("title") or "Unclustered"
        )
        topic_node_id = _topic_graph_id(topic_id)
        cluster_node_id = _cluster_graph_id(cluster_id)
        channel = str(row.get("channel") or "unknown")
        channels.add(channel)
        cluster_topic_counts[cluster_node_id] = (
            cluster_topic_counts.get(cluster_node_id, 0) + 1
        )

        nodes[topic_node_id] = {
            "id": topic_node_id,
            "type": "topic",
            "topic_id": topic_id,
            "run_id": row.get("run_id"),
            "label": row.get("title") or topic_id,
            "title": row.get("title") or topic_id,
            "channel": channel,
            "cluster_id": cluster_id,
            "cluster_label": cluster_label,
            "cluster_version": int(row.get("cluster_version") or 1),
            "decision": row.get("decision"),
            "best_channel": row.get("best_channel"),
            "next_action": row.get("next_action"),
            "reliability_grade": row.get("reliability_grade") or "unknown",
            "failure_rate": row.get("failure_rate") or 0.0,
            "total_tokens": row.get("total_tokens") or 0,
            "created_at": row.get("created_at"),
            "similar_topics": [],
        }
        nodes.setdefault(
            cluster_node_id,
            {
                "id": cluster_node_id,
                "type": "cluster",
                "cluster_id": cluster_id,
                "label": cluster_label,
                "title": cluster_label,
                "topic_count": 0,
                "algorithm_version": int(row.get("cluster_version") or 1),
            },
        )

    edges: list[dict[str, Any]] = []
    for node in list(nodes.values()):
        if node.get("type") != "topic":
            continue
        cluster_node_id = _cluster_graph_id(str(node.get("cluster_id") or ""))
        edges.append(
            {
                "id": f"in-cluster:{node['id']}->{cluster_node_id}",
                "type": "IN_CLUSTER",
                "source": node["id"],
                "target": cluster_node_id,
                "score": 1.0,
                "method": "cluster",
            }
        )

    for edge in similarity_edges:
        source_id = str(edge.get("source_topic_id") or "")
        target_id = str(edge.get("target_topic_id") or "")
        if source_id not in topic_ids or target_id not in topic_ids:
            continue
        score = _safe_float(edge.get("score"))
        source_node_id = _topic_graph_id(source_id)
        target_node_id = _topic_graph_id(target_id)
        graph_edge = {
            "id": f"similar:{source_id}->{target_id}",
            "type": "SIMILAR_TO",
            "source": source_node_id,
            "target": target_node_id,
            "score": round(score, 3),
            "method": edge.get("method") or "lexical",
            "lexical_score": _nullable_float(edge.get("lexical_score")),
            "semantic_score": _nullable_float(edge.get("semantic_score")),
            "algorithm_version": int(edge.get("algorithm_version") or 1),
            "explanation": edge.get("explanation") or _fallback_edge_explanation(edge),
        }
        edges.append(graph_edge)
        source_node = nodes.get(source_node_id)
        target_node = nodes.get(target_node_id)
        if source_node and target_node:
            source_node["similar_topics"].append(
                {
                    "title": target_node.get("title"),
                    "score": graph_edge["score"],
                    "method": graph_edge["method"],
                    "algorithm_version": graph_edge["algorithm_version"],
                    "explanation": graph_edge["explanation"],
                }
            )

    clusters = []
    for node_id, count in cluster_topic_counts.items():
        if node_id in nodes:
            nodes[node_id]["topic_count"] = count
            clusters.append(
                {
                    "id": nodes[node_id]["cluster_id"],
                    "label": nodes[node_id]["label"],
                    "topic_count": count,
                }
            )

    node_values = list(nodes.values())
    return {
        "nodes": node_values,
        "edges": edges,
        "stats": {
            "topic_count": sum(
                1 for node in node_values if node.get("type") == "topic"
            ),
            "cluster_count": sum(
                1 for node in node_values if node.get("type") == "cluster"
            ),
            "similarity_edge_count": sum(
                1 for edge in edges if edge.get("type") == "SIMILAR_TO"
            ),
            "edge_count": len(edges),
            "persona_overlay_included": include_personas,
        },
        "filters": {
            "channels": sorted(channels),
            "clusters": sorted(clusters, key=lambda item: item["label"]),
            "include_personas": include_personas,
        },
    }


def _topic_graph_id(topic_id: str) -> str:
    return f"topic:{topic_id}"


def _cluster_graph_id(cluster_id: str) -> str:
    return f"cluster:{cluster_id}"


def _safe_float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _nullable_float(value: Any) -> float | None:
    if value is None:
        return None
    return round(_safe_float(value), 3)


def _fallback_edge_explanation(edge: dict[str, Any]) -> str:
    method = edge.get("method") or "lexical"
    score = edge.get("score")
    if score is None:
        return f"Connected by {method} similarity."
    return f"Connected by {method} similarity with score {_safe_float(score):.2f}."


def _enrich_payload_for_read(payload: dict[str, Any]) -> dict[str, Any]:
    payload = enrich_payload_channel_scores(payload)
    payload["similarity_edges"] = _preferred_similarity_edges(
        payload.get("similarity_edges") or []
    )
    for edge in payload["similarity_edges"]:
        edge["explanation"] = edge.get("explanation") or _fallback_edge_explanation(
            edge
        )
    return payload


def _overlay_cluster_from_record(
    payload: dict[str, Any], record: dict[str, Any]
) -> None:
    topic = payload.setdefault("topic", {})
    topic["cluster_id"] = record.get("cluster_id") or topic.get("cluster_id")
    topic["cluster_label"] = record.get("cluster_label") or topic.get("cluster_label")
    topic["cluster_version"] = record.get("cluster_version") or topic.get(
        "cluster_version", 1
    )


def _history_summary(payload: dict[str, Any]) -> dict[str, Any]:
    payload = _enrich_payload_for_read(payload)
    receipt = payload.get("receipt", {})
    recommendation = payload.get("recommendation", {})
    topic = payload.get("topic", {})
    similarity_edges = _preferred_similarity_edges(payload.get("similarity_edges", []))
    return {
        "run_id": payload.get("run_id"),
        "created_at": payload.get("created_at"),
        "mode": receipt.get("mode", "unknown"),
        "title": topic.get("title"),
        "channel": topic.get("channel"),
        "cluster_label": topic.get("cluster_label"),
        "cluster_version": topic.get("cluster_version", 1),
        "decision": recommendation.get("decision"),
        "decision_confidence": recommendation.get("decision_confidence"),
        "best_channel": recommendation.get("best_channel"),
        "channel_scores": recommendation.get("channel_scores", []),
        "channel_scores_source": recommendation.get(
            "channel_scores_source", "legacy_heuristic"
        ),
        "next_action": recommendation.get("next_action"),
        "reaction_count": len(payload.get("reactions", [])),
        "similarity_count": len(similarity_edges),
        "similar_topics": _similar_topics_from_edges(similarity_edges),
        "total_tokens": receipt.get("usage", {}).get("total_tokens", 0),
        "failure_rate": receipt.get("failure_rate", 0.0),
        "reliability_grade": receipt.get("reliability_grade", "unknown"),
        "model_routing": receipt.get("model_routing", {}),
        "quality_warnings": receipt.get("quality_warnings", []),
        "duplicate_objection_count": receipt.get("duplicate_objection_count", 0),
        "max_duplicate_objections": receipt.get("max_duplicate_objections", 0),
        "near_duplicate_objections": receipt.get("near_duplicate_objections", 0),
        "weak_topic_grounding": receipt.get("weak_topic_grounding", 0),
    }


def _previous_topic_payload(payload: dict[str, Any]) -> dict[str, Any]:
    topic = dict(payload.get("topic", {}))
    topic["created_at"] = payload.get("created_at")
    topic["reactions"] = payload.get("reactions", [])
    topic["objections"] = payload.get("objections", [])
    return topic


def _previous_topic_from_record(record: dict[str, Any]) -> dict[str, Any]:
    payload_json = record.get("payload_json")
    if payload_json:
        try:
            topic = _previous_topic_payload(json.loads(payload_json))
            topic["cluster_id"] = record.get("cluster_id") or topic.get("cluster_id")
            topic["cluster_label"] = record.get("cluster_label") or topic.get(
                "cluster_label"
            )
            topic["cluster_version"] = record.get("cluster_version") or topic.get(
                "cluster_version", 1
            )
            return topic
        except json.JSONDecodeError:
            pass
    return {
        "id": record.get("id"),
        "topic_hash": record.get("topic_hash"),
        "summary": record.get("summary"),
        "title": record.get("title"),
        "channel": record.get("channel"),
        "cluster_id": record.get("cluster_id"),
        "cluster_label": record.get("cluster_label"),
        "cluster_version": record.get("cluster_version", 1),
        "created_at": record.get("created_at"),
        "reactions": _compact_persona_rows(record.get("reactions"), "summary"),
        "objections": _compact_persona_rows(record.get("objections"), "text"),
    }


def _compact_persona_rows(value: Any, text_field: str) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for item in value or []:
        if not isinstance(item, dict) or not item.get("persona_id"):
            continue
        rows.append(
            {
                "persona_id": str(item["persona_id"]),
                text_field: str(item.get(text_field) or ""),
            }
        )
    return rows


def _similar_topics_from_edges(edges: list[dict[str, Any]]) -> list[dict[str, Any]]:
    topics = []
    for edge in _preferred_similarity_edges(edges):
        if not (edge.get("target_title") or edge.get("target_topic_id")):
            continue
        topics.append(
            {
                "target_topic_id": edge.get("target_topic_id"),
                "title": edge.get("target_title") or edge.get("target_topic_id"),
                "score": edge.get("score"),
                "method": edge.get("method", "lexical"),
                "algorithm_version": int(edge.get("algorithm_version") or 1),
                "explanation": edge.get("explanation")
                or _fallback_edge_explanation(edge),
            }
        )
    return _unique_similar_topics_by_title(topics)[:5]


def _record_similar_topics(record: dict[str, Any]) -> list[dict[str, Any]]:
    v2 = [topic for topic in record.get("similar_topics_v2", []) if topic.get("title")]
    legacy = [
        topic for topic in record.get("similar_topics_v1", []) if topic.get("title")
    ]
    if int(record.get("cluster_version") or 1) >= 2:
        topics = v2
    else:
        topics = (
            v2
            or legacy
            or [
                topic
                for topic in record.get("similar_topics", [])
                if topic.get("title")
            ]
        )
    return _unique_similar_topics_by_title(topics)


def _unique_similar_topics_by_title(
    topics: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    deduped: dict[str, dict[str, Any]] = {}
    for topic in topics:
        title = str(topic.get("title") or topic.get("target_topic_id") or "").strip()
        if not title:
            continue
        key = title.casefold()
        candidate = topic | {
            "title": title,
            "explanation": topic.get("explanation")
            or _fallback_edge_explanation(topic),
        }
        current = deduped.get(key)
        if current is None or _safe_float(candidate.get("score")) > _safe_float(
            current.get("score")
        ):
            deduped[key] = candidate
    return sorted(
        deduped.values(),
        key=lambda topic: _safe_float(topic.get("score")),
        reverse=True,
    )


def _neo4j_history_summary(record: dict[str, Any]) -> dict[str, Any]:
    similar_topics = _record_similar_topics(record)
    if record.get("payload_json"):
        summary = _history_summary(
            _enrich_payload_for_read(json.loads(record["payload_json"]))
        )
        summary["cluster_label"] = record.get("cluster_label") or summary.get(
            "cluster_label"
        )
        summary["cluster_version"] = record.get("cluster_version") or summary.get(
            "cluster_version", 1
        )
        if similar_topics:
            summary["similar_topics"] = similar_topics[:5]
            summary["similarity_count"] = len(similar_topics)
        return summary

    similar_topics.sort(key=lambda topic: topic.get("score") or 0, reverse=True)
    record["similar_topics"] = similar_topics[:5]
    record["similarity_count"] = len(similar_topics)
    record["channel_scores"] = build_channel_scores(
        topic_text=str(record.get("title") or ""),
        title=record.get("title"),
        requested_channel=str(record.get("channel") or "unknown"),
    )
    return record

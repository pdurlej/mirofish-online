"""Audience Graph persistence contracts."""

from __future__ import annotations

import json
from typing import Any, Protocol

from .audience_run import AudienceRunResult


class AudienceGraphStore(Protocol):
    def write_run(self, result: AudienceRunResult) -> dict[str, Any]:
        """Persist an audience run and return structured write counts."""

    def read_run(self, run_id: str) -> dict[str, Any] | None:
        """Return a stored audience run summary."""

    def previous_topics(self, limit: int = 25) -> list[dict[str, Any]]:
        """Return recent topics for similarity checks."""

    def list_runs(self, limit: int = 25) -> list[dict[str, Any]]:
        """Return recent audience runs for history UI."""


class InMemoryAudienceGraphStore:
    def __init__(self) -> None:
        self._runs: dict[str, dict[str, Any]] = {}

    def write_run(self, result: AudienceRunResult) -> dict[str, Any]:
        payload = result.to_dict()
        self._runs[result.run_id] = payload
        return _write_counts(payload)

    def read_run(self, run_id: str) -> dict[str, Any] | None:
        return self._runs.get(run_id)

    def previous_topics(self) -> list[dict[str, Any]]:
        return [payload["topic"] for payload in self._runs.values()]

    def list_runs(self, limit: int = 25) -> list[dict[str, Any]]:
        values = list(self._runs.values())[-limit:]
        return [_history_summary(payload) for payload in reversed(values)]


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
                tx.run(
                    """
                    MATCH (src:AudienceTopic {topic_id: $source_topic_id})
                    MATCH (tgt:AudienceTopic {topic_id: $target_topic_id})
                    MERGE (src)-[rel:SIMILAR_TO]->(tgt)
                    SET rel.score = $score
                    """,
                    source_topic_id=edge["source_topic_id"],
                    target_topic_id=edge["target_topic_id"],
                    score=edge["score"],
                )

        with self._storage._driver.session() as session:  # noqa: SLF001
            self._storage._call_with_retry(session.execute_write, _write)  # noqa: SLF001

        return _write_counts(payload)

    def read_run(self, run_id: str) -> dict[str, Any] | None:
        def _read(tx):
            result = tx.run(
                """
                MATCH (r:AudienceRun {run_id: $run_id})
                RETURN r.payload_json AS payload_json
                """,
                run_id=run_id,
            )
            record = result.single()
            if record and record["payload_json"]:
                return json.loads(record["payload_json"])

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
                RETURN t.topic_id AS id,
                       t.summary AS summary,
                       t.title AS title,
                       t.channel AS channel
                ORDER BY t.updated_at DESC
                LIMIT $limit
                """,
                limit=limit,
            )
            return [dict(record) for record in result]

        with self._storage._driver.session() as session:  # noqa: SLF001
            return self._storage._call_with_retry(session.execute_read, _read)  # noqa: SLF001

    def list_runs(self, limit: int = 25) -> list[dict[str, Any]]:
        def _read(tx):
            result = tx.run(
                """
                MATCH (r:AudienceRun)-[:TESTED_TOPIC]->(t:AudienceTopic)
                OPTIONAL MATCH (r)-[:HAS_RECOMMENDATION]->(rec:AudienceRecommendation)
                OPTIONAL MATCH (r)-[:HAS_REACTION]->(reaction:AudienceReaction)
                OPTIONAL MATCH (t)-[sim:SIMILAR_TO]->()
                RETURN r.run_id AS run_id,
                       r.created_at AS created_at,
                       r.mode AS mode,
                       r.total_tokens AS total_tokens,
                       r.failure_rate AS failure_rate,
                       r.reliability_grade AS reliability_grade,
                       t.title AS title,
                       t.channel AS channel,
                       rec.decision AS decision,
                       rec.best_channel AS best_channel,
                       rec.next_action AS next_action,
                       count(DISTINCT reaction) AS reaction_count,
                       count(DISTINCT sim) AS similarity_count
                ORDER BY r.created_at DESC
                LIMIT $limit
                """,
                limit=limit,
            )
            return [dict(record) for record in result]

        with self._storage._driver.session() as session:  # noqa: SLF001
            return self._storage._call_with_retry(session.execute_read, _read)  # noqa: SLF001


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


def _history_summary(payload: dict[str, Any]) -> dict[str, Any]:
    receipt = payload.get("receipt", {})
    recommendation = payload.get("recommendation", {})
    return {
        "run_id": payload.get("run_id"),
        "created_at": payload.get("created_at"),
        "mode": receipt.get("mode", "unknown"),
        "title": payload.get("topic", {}).get("title"),
        "channel": payload.get("topic", {}).get("channel"),
        "decision": recommendation.get("decision"),
        "best_channel": recommendation.get("best_channel"),
        "next_action": recommendation.get("next_action"),
        "reaction_count": len(payload.get("reactions", [])),
        "similarity_count": len(payload.get("similarity_edges", [])),
        "total_tokens": receipt.get("usage", {}).get("total_tokens", 0),
        "failure_rate": receipt.get("failure_rate", 0.0),
        "reliability_grade": receipt.get("reliability_grade", "unknown"),
    }

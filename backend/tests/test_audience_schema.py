"""The audience lane must ship with its own constraints.

Verified against a real Neo4j 5.18 (the production version): all eight
constraints and the range index are accepted, schema_errors comes back empty,
and writing ten runs against fifty runs of history took 85 ms/run with them
versus 127 ms/run without -- a MERGE on an unconstrained property is a full
label scan, so the gap widens as history accumulates. Production carries 193
runs and 4115 reactions with no constraint at all.

This test guards the composition, which is what a careless edit would break.
"""

from __future__ import annotations

from app.storage import neo4j_schema


def test_every_audience_label_written_by_the_store_has_a_unique_key():
    labels = {label for _, label, _ in neo4j_schema.AUDIENCE_UNIQUE_KEYS}

    # The eight labels Neo4jAudienceGraphStore.write_run MERGEs on.
    assert labels == {
        "AudienceRun",
        "AudienceTopic",
        "AudienceTopicCluster",
        "AudiencePersona",
        "AudienceReaction",
        "AudienceObjection",
        "AudienceInsight",
        "AudienceRecommendation",
    }


def test_audience_constraints_reach_the_startup_query_list():
    assert len(neo4j_schema.CREATE_AUDIENCE_CONSTRAINTS) == 8
    for statement in neo4j_schema.CREATE_AUDIENCE_CONSTRAINTS:
        assert statement in neo4j_schema.ALL_SCHEMA_QUERIES
    assert (
        neo4j_schema.CREATE_AUDIENCE_RUN_CREATED_AT_INDEX
        in neo4j_schema.ALL_SCHEMA_QUERIES
    )


def test_constraints_are_idempotent_and_name_the_merge_property():
    for name, label, prop in neo4j_schema.AUDIENCE_UNIQUE_KEYS:
        statement = next(
            s for s in neo4j_schema.CREATE_AUDIENCE_CONSTRAINTS if name in s
        )
        assert "IF NOT EXISTS" in statement
        assert f"(n:{label})" in statement
        assert f"n.{prop} IS UNIQUE" in statement


def test_no_index_on_a_property_only_ever_read_through_coalesce():
    """AudienceTopic.updated_at is always sorted as
    coalesce(t.updated_at, latest_run.created_at), and a function around the
    property stops the planner using an index. Adding one would be dead weight."""
    joined = " ".join(neo4j_schema.ALL_SCHEMA_QUERIES)
    assert "AudienceTopic) ON (n.updated_at)" not in joined
    assert "audience_run_created_at" in joined

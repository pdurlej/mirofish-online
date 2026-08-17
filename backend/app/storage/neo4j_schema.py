"""
Neo4j Schema — Cypher queries for index creation and schema management.

Called by Neo4jStorage.create_graph() to set up vector + fulltext indexes.
"""

# Constraints
CREATE_GRAPH_UUID_CONSTRAINT = """
CREATE CONSTRAINT graph_uuid IF NOT EXISTS
FOR (g:Graph) REQUIRE g.graph_id IS UNIQUE
"""

CREATE_ENTITY_UUID_CONSTRAINT = """
CREATE CONSTRAINT entity_uuid IF NOT EXISTS
FOR (n:Entity) REQUIRE n.uuid IS UNIQUE
"""

CREATE_EPISODE_UUID_CONSTRAINT = """
CREATE CONSTRAINT episode_uuid IF NOT EXISTS
FOR (ep:Episode) REQUIRE ep.uuid IS UNIQUE
"""

# Vector indexes (Neo4j 5.11+)
CREATE_ENTITY_VECTOR_INDEX = """
CREATE VECTOR INDEX entity_embedding IF NOT EXISTS
FOR (n:Entity) ON (n.embedding)
OPTIONS {indexConfig: {
    `vector.dimensions`: 768,
    `vector.similarity_function`: 'cosine'
}}
"""

CREATE_RELATION_VECTOR_INDEX = """
CREATE VECTOR INDEX fact_embedding IF NOT EXISTS
FOR ()-[r:RELATION]-() ON (r.fact_embedding)
OPTIONS {indexConfig: {
    `vector.dimensions`: 768,
    `vector.similarity_function`: 'cosine'
}}
"""

# Fulltext indexes (for BM25 keyword search)
CREATE_ENTITY_FULLTEXT_INDEX = """
CREATE FULLTEXT INDEX entity_fulltext IF NOT EXISTS
FOR (n:Entity) ON EACH [n.name, n.summary]
"""

CREATE_FACT_FULLTEXT_INDEX = """
CREATE FULLTEXT INDEX fact_fulltext IF NOT EXISTS
FOR ()-[r:RELATION]-() ON EACH [r.fact, r.name]
"""

# Audience lane constraints.
#
# Everything above covers the document-graph lane only. The audience lane -- the
# part of the product that is actually used -- had no constraint and no index at
# all, confirmed against production with SHOW CONSTRAINTS. Every MERGE therefore
# scanned the whole label: with 4115 AudienceReaction nodes, one write_run does
# roughly (3 + personas + reactions + objections + insights) full label scans, so
# the cost grows with the accumulated history.
#
# One key per label, matching the property each write_run MERGEs on in
# app/audience/graph_store.py. Uniqueness also closes the window where two
# concurrent writers could MERGE the same id into two nodes.
AUDIENCE_UNIQUE_KEYS = (
    ("audience_run_id", "AudienceRun", "run_id"),
    ("audience_topic_id", "AudienceTopic", "topic_id"),
    ("audience_cluster_id", "AudienceTopicCluster", "cluster_id"),
    ("audience_persona_id", "AudiencePersona", "persona_id"),
    ("audience_reaction_id", "AudienceReaction", "reaction_id"),
    ("audience_objection_id", "AudienceObjection", "objection_id"),
    ("audience_insight_id", "AudienceInsight", "insight_id"),
    ("audience_recommendation_run_id", "AudienceRecommendation", "run_id"),
)

CREATE_AUDIENCE_CONSTRAINTS = [
    f"""
CREATE CONSTRAINT {name} IF NOT EXISTS
FOR (n:{label}) REQUIRE n.{prop} IS UNIQUE
"""
    for name, label, prop in AUDIENCE_UNIQUE_KEYS
]

# History, previous_topics and graph_snapshot all sort on this.
#
# Deliberately no index on AudienceTopic.updated_at: those queries sort on
# coalesce(t.updated_at, latest_run.created_at), and a function call around the
# property stops the planner using an index anyway. Rewriting those queries is a
# separate job.
CREATE_AUDIENCE_RUN_CREATED_AT_INDEX = """
CREATE INDEX audience_run_created_at IF NOT EXISTS
FOR (r:AudienceRun) ON (r.created_at)
"""

# All schema queries to run on startup
ALL_SCHEMA_QUERIES = [
    CREATE_GRAPH_UUID_CONSTRAINT,
    CREATE_ENTITY_UUID_CONSTRAINT,
    CREATE_EPISODE_UUID_CONSTRAINT,
    CREATE_ENTITY_VECTOR_INDEX,
    CREATE_RELATION_VECTOR_INDEX,
    CREATE_ENTITY_FULLTEXT_INDEX,
    CREATE_FACT_FULLTEXT_INDEX,
    *CREATE_AUDIENCE_CONSTRAINTS,
    CREATE_AUDIENCE_RUN_CREATED_AT_INDEX,
]

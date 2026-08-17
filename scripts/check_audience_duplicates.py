#!/usr/bin/env python3
"""Read-only gate to run before the audience uniqueness constraints are created.

`CREATE CONSTRAINT ... IS UNIQUE` fails when existing data already violates it.
Production accumulated 193 runs with no constraint on any Audience label, so the
window for two concurrent writers to MERGE one id into two nodes was open the
whole time. If that happened, deploying the new schema leaves it incomplete --
visible now as an ERROR and in Neo4jStorage.schema_errors, but still incomplete.

So check first. Counts only; nothing is written or deleted.

Usage on the RS2000 host, with only Neo4j started:

    python3 scripts/check_audience_duplicates.py
    python3 scripts/check_audience_duplicates.py --container mirofish-online-neo4j

Exit code 0 means every key is unique and the constraints will be accepted.
Exit code 1 means duplicates exist and must be resolved first.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys

# Mirrors AUDIENCE_UNIQUE_KEYS in backend/app/storage/neo4j_schema.py. Kept as a
# literal so this script stays runnable on a host with no Python dependencies.
KEYS = [
    ("AudienceRun", "run_id"),
    ("AudienceTopic", "topic_id"),
    ("AudienceTopicCluster", "cluster_id"),
    ("AudiencePersona", "persona_id"),
    ("AudienceReaction", "reaction_id"),
    ("AudienceObjection", "objection_id"),
    ("AudienceInsight", "insight_id"),
    ("AudienceRecommendation", "run_id"),
]


def cypher(container: str, user: str, password: str, query: str) -> str:
    result = subprocess.run(
        [
            "docker", "exec", container,
            "cypher-shell", "-u", user, "-p", password,
            "--format", "plain", query,
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip()[:300] or "cypher-shell failed")
    return result.stdout


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--container", default="mirofish-online-neo4j")
    parser.add_argument("--env-file", default="/opt/mirofish-online/.env")
    args = parser.parse_args()

    user = os.environ.get("NEO4J_USER")
    password = os.environ.get("NEO4J_PASSWORD")
    if not password and os.path.exists(args.env_file):
        # Read the runtime env file rather than asking the operator to export
        # secrets into a shell that keeps history.
        for line in open(args.env_file, encoding="utf-8"):
            key, _, value = line.strip().partition("=")
            if key == "NEO4J_USER" and not user:
                user = value
            elif key == "NEO4J_PASSWORD" and not password:
                password = value
    if not password:
        print("NEO4J_PASSWORD not found in the environment or the env file.")
        return 2

    total_duplicates = 0
    print(f"{'label.property':44s} {'nodes':>8s} {'duplicate keys':>15s}")
    print("-" * 70)
    for label, prop in KEYS:
        counts = cypher(
            args.container,
            user or "neo4j",
            password,
            f"MATCH (n:{label}) RETURN count(n) AS total, "
            f"count(DISTINCT n.{prop}) AS distinct_keys;",
        )
        numbers = [
            line for line in counts.splitlines() if line and not line.startswith("total")
        ]
        total, distinct = (
            [int(part.strip()) for part in numbers[0].split(",")] if numbers else (0, 0)
        )
        duplicates = total - distinct
        total_duplicates += duplicates
        flag = "" if duplicates == 0 else "  <-- BLOCKS THE CONSTRAINT"
        print(f"{label + '.' + prop:44s} {total:8d} {duplicates:15d}{flag}")

    print("-" * 70)
    if total_duplicates:
        print(
            f"\n{total_duplicates} duplicate key(s) found. Deduplicate before deploying,\n"
            "or the CREATE CONSTRAINT statements will be rejected and the schema\n"
            "will stay half-applied."
        )
        return 1
    print("\nEvery key is unique. The constraints will be accepted.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

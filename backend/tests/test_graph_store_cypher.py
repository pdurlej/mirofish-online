"""Every Cypher statement the audience store sends must be valid Cypher.

Written after a live production run failed in 25 milliseconds, before its first
LLM call, with a syntax error: `previous_topics` had ORDER BY hanging off a WHERE,
which Neo4j rejects because ORDER BY is a sub-clause of WITH or RETURN. Introduced
by commit caa1e29 and undetectable by the rest of the suite, because

* the in-memory store used everywhere else never parses Cypher, and
* `list_runs` and `graph_snapshot` -- the history and graph views -- were fine,
  so the UI looked healthy while every live run was impossible.

Neo4j validates syntax on EXPLAIN without touching data, so this is cheap. It
needs a server, so it is opt-in:

    MIROFISH_TEST_NEO4J_URI=bolt://localhost:7692 \\
    MIROFISH_TEST_NEO4J_PASSWORD=... uv run pytest tests/test_graph_store_cypher.py

Skipped otherwise. A CI service container would make it unconditional and is the
durable fix; until then, run it whenever graph_store.py changes.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

import pytest

STORE = Path(__file__).resolve().parents[1] / "app" / "audience" / "graph_store.py"

URI = os.environ.get("MIROFISH_TEST_NEO4J_URI")
USER = os.environ.get("MIROFISH_TEST_NEO4J_USER", "neo4j")
PASSWORD = os.environ.get("MIROFISH_TEST_NEO4J_PASSWORD")

pytestmark = pytest.mark.skipif(
    not (URI and PASSWORD),
    reason="set MIROFISH_TEST_NEO4J_URI and MIROFISH_TEST_NEO4J_PASSWORD to run",
)

# Triple-quoted blocks holding a Cypher clause, which is how the store writes
# them. Parameters stay as $name; EXPLAIN accepts them unbound.
CYPHER_BLOCK = re.compile(r'"""\s*\n(\s*(?:MATCH|MERGE|CALL|UNWIND|WITH)\b.*?)"""', re.S)


def _as_runtime_cypher(statement: str) -> str:
    """Turn the source text of a block back into what Neo4j actually receives.

    Some blocks are f-strings, where a relationship type is interpolated and a
    literal brace is written doubled. Both have to be undone, in that order, or
    the check reports its own extraction as invalid Cypher.
    """
    # Placeholders first. At this point a real Cypher map literal still shows as
    # {{...}}, so any single-brace {name} is unambiguously an interpolation. Both
    # relationship types and labels are bare identifiers, so one stand-in serves
    # for syntax checking whatever the placeholder meant.
    resolved = re.sub(r"(?<!\{)\{[a-z_]+\}(?!\})", "SIMILAR_TO", statement)
    return resolved.replace("{{", "{").replace("}}", "}")


def _statements() -> list[str]:
    found = [
        block.strip()
        for block in CYPHER_BLOCK.findall(STORE.read_text(encoding="utf-8"))
    ]
    assert found, "no Cypher found -- the extraction regex needs updating"
    return found


def test_every_store_statement_parses():
    from neo4j import GraphDatabase

    driver = GraphDatabase.driver(URI, auth=(USER, PASSWORD))
    failures: list[str] = []
    try:
        with driver.session() as session:
            for statement in _statements():
                probe = _as_runtime_cypher(statement)
                try:
                    session.run("EXPLAIN " + probe).consume()
                except Exception as exc:  # noqa: BLE001
                    first_line = probe.strip().splitlines()[0][:70]
                    failures.append(f"{first_line} -> {type(exc).__name__}: {exc}"[:300])
    finally:
        driver.close()

    assert not failures, "invalid Cypher:\n" + "\n".join(failures)

#!/usr/bin/env python
"""Import a controlled Gemini research snapshot as MiroFish AudienceRun records."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT))

from app.audience.graph_store import InMemoryAudienceGraphStore, Neo4jAudienceGraphStore  # noqa: E402
from app.audience.research_snapshot import (  # noqa: E402
    DEFAULT_SOURCE_MODEL,
    build_snapshot_run,
    load_research_dataset,
    summarize_snapshot_results,
)
from app.storage.neo4j_storage import Neo4jStorage  # noqa: E402


DEFAULT_RESEARCH_PATH = Path(
    "/private/tmp/mirofish-gemini-research/oracle150_flash3600_raw.json"
)
DEFAULT_CANDIDATES_PATH = Path(
    "/private/tmp/mirofish-gemini-research/mirofish_import_candidates.json"
)


def main() -> int:
    args = _parse_args()
    dataset = load_research_dataset(
        research_path=args.research,
        candidates_path=args.candidates,
        snapshot_id=args.snapshot_id,
    )
    candidates = dataset.candidates[: args.limit] if args.limit else dataset.candidates
    if args.require_count is not None and len(candidates) != args.require_count:
        raise SystemExit(
            f"Refusing import: expected {args.require_count} candidates, got {len(candidates)}"
        )

    store: Any
    storage = None
    if args.write:
        storage = Neo4jStorage()
        store = Neo4jAudienceGraphStore(storage)
    else:
        store = InMemoryAudienceGraphStore()

    try:
        results = []
        for candidate in candidates:
            previous_topics = store.previous_topics(args.previous_limit)
            result = build_snapshot_run(
                dataset,
                candidate,
                previous_topics=previous_topics,
                source_model=args.source_model,
            )
            counts = store.write_run(result)
            results.append((result, counts))
    finally:
        if storage is not None:
            storage.close()

    summary = summarize_snapshot_results(results)
    summary["write"] = args.write
    summary["snapshot_id"] = args.snapshot_id
    summary["source_model"] = args.source_model
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Build controlled synthetic research AudienceRun records from Gemini "
            "batch outputs. Dry-run is the default; pass --write to persist to Neo4j."
        )
    )
    parser.add_argument("--research", type=Path, default=DEFAULT_RESEARCH_PATH)
    parser.add_argument("--candidates", type=Path, default=DEFAULT_CANDIDATES_PATH)
    parser.add_argument(
        "--snapshot-id",
        default="gemini-oracle150-flash3600-v1",
        help="Stable namespace for topic/run/persona ids.",
    )
    parser.add_argument("--source-model", default=DEFAULT_SOURCE_MODEL)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--previous-limit", type=int, default=120)
    parser.add_argument(
        "--require-count",
        type=int,
        default=None,
        help="Abort unless exactly this many candidates will be imported.",
    )
    parser.add_argument(
        "--write",
        action="store_true",
        help="Persist to configured Neo4j. Without this flag only an in-memory dry-run runs.",
    )
    return parser.parse_args()


if __name__ == "__main__":
    raise SystemExit(main())

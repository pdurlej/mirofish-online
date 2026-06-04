#!/usr/bin/env python3
"""Fake Audience Graph smoke.

Writes only a sanitized receipt to the requested output path. It does not call
LLMs, Neo4j, OASIS, or the live runtime.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BACKEND_DIR = ROOT / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.audience import (  # noqa: E402
    AudienceRunInput,
    InMemoryAudienceGraphStore,
    build_fake_audience_run,
    load_default_personas,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--topic", required=True)
    parser.add_argument("--channel", default="unknown")
    parser.add_argument("--title")
    parser.add_argument("--seed", default="smoke")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    run_input = AudienceRunInput(
        topic=args.topic,
        channel=args.channel,
        title=args.title,
        run_seed=args.seed,
    )
    personas = load_default_personas()
    store = InMemoryAudienceGraphStore()
    result = build_fake_audience_run(run_input, personas=personas)
    counts = store.write_run(result)
    stored = store.read_run(result.run_id)
    if not stored:
        raise RuntimeError("Audience graph smoke failed to read written run")

    receipt = {
        "status": "passed",
        "run_id": result.run_id,
        "topic_hash": result.topic["topic_hash"],
        "counts": counts,
        "recommendation": result.recommendation,
        "raw_topic_stored": False,
    }
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(receipt, indent=2), encoding="utf-8")
    print(json.dumps({"status": "passed", "output": str(output)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

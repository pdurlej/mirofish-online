#!/usr/bin/env python3
"""Measure the cost of full-run versus compact reviewer-memory context."""

from __future__ import annotations

import gc
import json
import tracemalloc
from typing import Any, Callable

from app.audience import AudienceRunInput, build_fake_audience_run
from app.audience.graph_store import _previous_topic_from_record
from app.audience.similarity import build_persona_memory


TOPIC_COUNT = 25
UNUSED_PAYLOAD_BYTES = 50_000


def _measure_peak(operation: Callable[[], Any]) -> tuple[Any, int]:
    gc.collect()
    tracemalloc.start()
    result = operation()
    _current, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    return result, peak


def _build_records() -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    legacy_records: list[dict[str, Any]] = []
    compact_records: list[dict[str, Any]] = []
    personas: list[dict[str, Any]] = []

    for index in range(TOPIC_COUNT):
        result = build_fake_audience_run(
            AudienceRunInput(
                topic=f"AI quality gate and product workflow benchmark topic {index}",
                title=f"Benchmark topic {index}",
                run_seed=f"benchmark-{index}",
            )
        )
        payload = result.to_dict()
        payload["unused_benchmark_payload"] = "x" * UNUSED_PAYLOAD_BYTES
        topic = payload["topic"]
        legacy_records.append(
            {
                "payload_json": json.dumps(payload),
                "cluster_id": topic.get("cluster_id"),
                "cluster_label": topic.get("cluster_label"),
                "cluster_version": topic.get("cluster_version"),
            }
        )
        compact_records.append(
            topic
            | {
                "created_at": payload["created_at"],
                "reactions": [
                    {
                        "persona_id": reaction["persona_id"],
                        "summary": reaction["summary"],
                    }
                    for reaction in payload["reactions"]
                ],
                "objections": [
                    {
                        "persona_id": objection["persona_id"],
                        "text": objection["text"],
                    }
                    for objection in payload["objections"]
                ],
            }
        )
        if not personas:
            personas = payload["personas"]

    return legacy_records, compact_records, personas


def main() -> int:
    legacy_records, compact_records, personas = _build_records()
    legacy_topics, legacy_peak = _measure_peak(
        lambda: [_previous_topic_from_record(record) for record in legacy_records]
    )
    compact_topics, compact_peak = _measure_peak(
        lambda: [_previous_topic_from_record(record) for record in compact_records]
    )
    edges = [
        {"target_topic_id": topic["id"]}
        for topic in compact_topics
    ]
    reviewer_memory_equal = build_persona_memory(
        personas, edges, legacy_topics
    ) == build_persona_memory(personas, edges, compact_topics)

    legacy_transport = sum(
        len(str(record["payload_json"]).encode()) for record in legacy_records
    )
    compact_transport = len(json.dumps(compact_records).encode())
    reduction = 1 - (compact_transport / legacy_transport)
    print(
        json.dumps(
            {
                "topics": TOPIC_COUNT,
                "unused_payload_bytes_per_run": UNUSED_PAYLOAD_BYTES,
                "legacy_transport_bytes": legacy_transport,
                "compact_transport_bytes": compact_transport,
                "transport_reduction_percent": round(reduction * 100, 1),
                "legacy_decode_peak_bytes": legacy_peak,
                "compact_decode_peak_bytes": compact_peak,
                "reviewer_memory_equal": reviewer_memory_equal,
            },
            indent=2,
        )
    )
    return 0 if reviewer_memory_equal else 1


if __name__ == "__main__":
    raise SystemExit(main())

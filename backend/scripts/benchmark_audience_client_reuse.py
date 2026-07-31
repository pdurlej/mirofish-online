#!/usr/bin/env python3
"""Measure construction cost removed by one shared HTTP client per run."""

from __future__ import annotations

import json
import time

from app.utils.llm_client import LLMClient


PERSONA_COUNT = 20
BENCHMARK_BASE_URL = "http://127.0.0.1:1/v1"


def _construct_clients(count: int) -> tuple[list[LLMClient], float]:
    started = time.perf_counter()
    clients = [
        LLMClient(api_key="benchmark-only", base_url=BENCHMARK_BASE_URL)
        for _ in range(count)
    ]
    elapsed_ms = (time.perf_counter() - started) * 1000
    return clients, elapsed_ms


def _close_all(clients: list[LLMClient]) -> None:
    for client in clients:
        client.close()


def main() -> int:
    warmup, _warmup_ms = _construct_clients(1)
    _close_all(warmup)

    legacy_clients, legacy_ms = _construct_clients(PERSONA_COUNT)
    shared_clients, shared_ms = _construct_clients(1)
    _close_all(legacy_clients)
    _close_all(shared_clients)

    reduction = 1 - (shared_ms / max(legacy_ms, 0.001))
    print(
        json.dumps(
            {
                "personas": PERSONA_COUNT,
                "legacy_client_instances": PERSONA_COUNT,
                "shared_client_instances": 1,
                "legacy_construction_ms": round(legacy_ms, 1),
                "shared_construction_ms": round(shared_ms, 1),
                "construction_time_reduction_percent": round(reduction * 100, 1),
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

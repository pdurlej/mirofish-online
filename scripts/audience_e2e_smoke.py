#!/usr/bin/env python3
"""Run a sanitized audience E2E smoke through the deployed HTTP API."""

from __future__ import annotations

import argparse
import hashlib
import json
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any


DEFAULT_TOPICS = [
    {
        "title": "AI harnesses for product managers",
        "channel": "podcast",
        "topic": "Czy product managerów powinny interesować AI harnessy?",
    },
    {
        "title": "Private Audience Graph for Produkt w Praktyce",
        "channel": "linkedin",
        "topic": (
            "Private Audience Graph jako narzędzie do testowania tematów "
            "Produkt w Praktyce."
        ),
    },
    {
        "title": "Audience segment conflict as podcast material",
        "channel": "podcast",
        "topic": (
            "Czy spór między segmentami odbiorców może być dobrym materiałem "
            "podcastowym?"
        ),
    },
]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:13000")
    parser.add_argument("--mode", choices=("fake", "live"), default="live")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--timeout-seconds", type=int, default=900)
    args = parser.parse_args()

    runs = []
    started = time.monotonic()
    for index, topic in enumerate(DEFAULT_TOPICS, start=1):
        run_id = _submit(args.base_url, args.mode, topic, index)
        result = _poll(args.base_url, run_id, args.timeout_seconds)
        data = result["data"]
        receipt = data.get("receipt", {})
        runs.append(
            {
                "index": index,
                "title": topic["title"],
                "topic_hash": hashlib.sha256(topic["topic"].encode()).hexdigest()[:12],
                "run_id": data["run_id"],
                "status": result["status"],
                "decision": data.get("recommendation", {}).get("decision"),
                "best_channel": data.get("recommendation", {}).get("best_channel"),
                "reaction_count": len(data.get("reactions", [])),
                "similarity_count": len(data.get("similarity_edges", [])),
                "total_tokens": receipt.get("usage", {}).get("total_tokens", 0),
                "failure_rate": receipt.get("failure_rate", 0.0),
                "reliability_grade": receipt.get("reliability_grade", "unknown"),
            }
        )

    payload = {
        "status": "passed",
        "mode": args.mode,
        "elapsed_seconds": round(time.monotonic() - started, 2),
        "run_count": len(runs),
        "runs": runs,
        "raw_topics_stored_in_receipt": False,
    }
    args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"status": "passed", "run_count": len(runs)}, indent=2))
    return 0


def _submit(base_url: str, mode: str, topic: dict[str, str], index: int) -> str:
    path = "/api/audience/runs/fake" if mode == "fake" else "/api/audience/runs"
    payload = topic | {"run_seed": f"e2e-{mode}-{int(time.time())}-{index}"}
    response = _request_json(base_url + path, payload)
    data = response["data"]
    if mode == "fake":
        return data["run_id"]
    return data["run_id"]


def _poll(base_url: str, run_id: str, timeout_seconds: int) -> dict[str, Any]:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        response = _request_json(base_url + f"/api/audience/runs/{run_id}")
        record = response["data"]
        if "status" not in record:
            return {"status": "completed", "data": record}
        if record["status"] == "completed":
            return record
        if record["status"] == "failed":
            raise RuntimeError(f"audience run failed: {record.get('error_kind', 'unknown')}")
        time.sleep(2)
    raise TimeoutError("audience run timed out")


def _request_json(url: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    data = None if payload is None else json.dumps(payload).encode()
    req = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST" if payload is not None else "GET",
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as response:
            result = json.loads(response.read().decode())
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"http_error:{exc.code}") from exc
    if result.get("success") is False:
        raise RuntimeError("api_error")
    return result


if __name__ == "__main__":
    raise SystemExit(main())

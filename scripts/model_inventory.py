#!/usr/bin/env python3
"""List and triage OpenAI-compatible cloud models without printing secrets."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))

from app.audience.model_inventory import list_openai_compatible_models  # noqa: E402
from app.config import Config  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON")
    args = parser.parse_args()

    inventory = list_openai_compatible_models(Config.LLM_BASE_URL, Config.LLM_API_KEY or "")
    payload = {
        "model_count": len(inventory.models),
        "models": inventory.models,
        "triage": inventory.triage(),
    }
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(f"Models: {payload['model_count']}")
        for bucket, models in payload["triage"].items():
            print(f"{bucket}: {', '.join(models) if models else '-'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

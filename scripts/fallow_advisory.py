#!/usr/bin/env python3
"""Run fallow-py as an advisory diff report.

The tool is intentionally non-blocking in CI while this fork establishes a
baseline. It still gives agents a deterministic cleanup report before claiming
work is done.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
FALLOW_REF = "959a8a55de1a2ecbe83195ab1c77ba41996446c4"
OUTPUT = ROOT / ".quality" / "fallow-agent-fix-plan.json"


def base_ref() -> str:
    return os.environ.get("QUALITY_BASE_REF") or os.environ.get("GITHUB_BASE_REF") or "origin/main"


def main() -> int:
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    command = [
        "uvx",
        "--from",
        f"git+https://github.com/pdurlej/fallow-py@{FALLOW_REF}",
        "fallow-py",
        "--format",
        "agent-fix-plan",
        "--root",
        ".",
        "--since",
        base_ref(),
        "--output",
        str(OUTPUT),
    ]
    print("Running:", " ".join(command))
    result = subprocess.run(command, cwd=ROOT)
    if result.returncode == 0:
        print(f"fallow-py advisory written to {OUTPUT}")
    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())

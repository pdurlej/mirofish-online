#!/usr/bin/env python3
"""Run ruff only on Python files changed in the current branch."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def base_ref() -> str:
    return os.environ.get("QUALITY_BASE_REF") or os.environ.get("GITHUB_BASE_REF") or "origin/main"


def changed_files() -> list[str]:
    candidates: set[str] = set()
    ranges = [f"{base_ref()}...HEAD", "HEAD"]
    for revision_range in ranges:
        result = subprocess.run(
            ["git", "diff", "--name-only", revision_range],
            cwd=ROOT,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
        )
        if result.returncode == 0:
            candidates.update(result.stdout.splitlines())
            break

    untracked = subprocess.run(
        ["git", "ls-files", "--others", "--exclude-standard"],
        cwd=ROOT,
        check=True,
        text=True,
        stdout=subprocess.PIPE,
    )
    candidates.update(untracked.stdout.splitlines())

    return sorted(
        path
        for path in candidates
        if path.endswith(".py") and (ROOT / path).exists()
    )


def main() -> int:
    files = changed_files()
    if not files:
        print("No changed Python files for ruff.")
        return 0

    command = ["uv", "run", "--with", "ruff==0.8.6", "ruff", "check", *files]
    print("Running:", " ".join(command))
    return subprocess.run(command, cwd=ROOT).returncode


if __name__ == "__main__":
    raise SystemExit(main())

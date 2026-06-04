#!/usr/bin/env python3
"""Small deterministic secret scanner for tracked repository files.

This is intentionally conservative and repo-local. It catches obvious bearer
tokens and committed env values before a PR can merge; it is not a replacement
for a dedicated secret-scanning product.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

SKIP_SUFFIXES = {
    ".jpeg",
    ".jpg",
    ".png",
    ".lock",
}

SKIP_PARTS = {
    ".git",
    ".quality",
    "node_modules",
    "dist",
    "build",
    "__pycache__",
}

ALLOW_VALUE_PREFIXES = (
    "replace-",
    "change-me",
    "changeme",
    "example",
    "dummy",
    "test",
    "ollama",
    "mirofish",
)

SECRET_PATTERNS = [
    ("bearer-token", re.compile(r"Bearer\s+[A-Za-z0-9._~+/=-]{20,}")),
    ("github-token", re.compile(r"gh[pousr]_[A-Za-z0-9_]{20,}")),
    ("openai-style-key", re.compile(r"sk-[A-Za-z0-9_-]{20,}")),
    ("olostep-token", re.compile(r"olostep_[A-Za-z0-9_]{16,}")),
    (
        "assigned-secret",
        re.compile(
            r"(?i)\b(api[_-]?key|token|secret|password|client[_-]?secret)\b"
            r"\s*[:=]\s*['\"]?([^'\"\s#]{16,})"
        ),
    ),
]


def tracked_files() -> list[Path]:
    result = subprocess.run(
        ["git", "-c", "core.quotePath=false", "ls-files"],
        cwd=ROOT,
        check=True,
        text=True,
        stdout=subprocess.PIPE,
    )
    return [
        ROOT / line
        for line in result.stdout.splitlines()
        if line.strip() and (ROOT / line).exists()
    ]


def should_skip(path: Path) -> bool:
    relative = path.relative_to(ROOT)
    if path.suffix.lower() in SKIP_SUFFIXES:
        return True
    return any(part in SKIP_PARTS for part in relative.parts)


def read_text(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return None


def allowed_assignment(match: re.Match[str]) -> bool:
    if match.lastindex != 2:
        return False
    value = match.group(2).strip().strip("'\"").lower()
    return value.startswith(ALLOW_VALUE_PREFIXES) or "${" in value


def main() -> int:
    findings: list[str] = []
    for path in tracked_files():
        if should_skip(path):
            continue
        text = read_text(path)
        if text is None:
            continue
        relative = path.relative_to(ROOT)
        for line_number, line in enumerate(text.splitlines(), start=1):
            for name, pattern in SECRET_PATTERNS:
                for match in pattern.finditer(line):
                    if name == "assigned-secret" and allowed_assignment(match):
                        continue
                    findings.append(f"{relative}:{line_number}: possible {name}")

    if findings:
        print("Secret scan found possible committed secrets:", file=sys.stderr)
        for finding in findings:
            print(f"- {finding}", file=sys.stderr)
        return 1

    print("Secret scan passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

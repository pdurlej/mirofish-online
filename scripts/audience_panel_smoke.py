#!/usr/bin/env python3
"""Run a tiny audience-panel product smoke without Neo4j, NER, or OASIS.

The smoke is intentionally narrow: prove whether a model can produce a useful
PM/audience critique report from one topic while keeping receipts sanitized.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol


ROOT = Path(__file__).resolve().parents[1]
BACKEND_DIR = ROOT / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.utils.llm_client import LLMClient, validate_json_schema  # noqa: E402


FINAL_RECOMMENDATIONS = [
    "publish",
    "rewrite",
    "narrow",
    "abandon",
    "ask_better_question",
]

AUDIENCE_PANEL_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": [
        "personas",
        "objections",
        "non_generic_insights",
        "decision_tests",
        "final_recommendation",
        "report_markdown",
    ],
    "properties": {
        "personas": {
            "type": "array",
            "minItems": 8,
            "maxItems": 12,
            "items": {
                "type": "object",
                "required": ["name", "perspective", "incentive", "likely_objection"],
                "properties": {
                    "name": {"type": "string", "minLength": 2},
                    "perspective": {"type": "string", "minLength": 8},
                    "incentive": {"type": "string", "minLength": 8},
                    "likely_objection": {"type": "string", "minLength": 8},
                },
            },
        },
        "objections": {
            "type": "array",
            "minItems": 8,
            "maxItems": 15,
            "items": {
                "type": "object",
                "required": ["objection", "why_it_matters", "severity"],
                "properties": {
                    "objection": {"type": "string", "minLength": 8},
                    "why_it_matters": {"type": "string", "minLength": 8},
                    "severity": {"type": "string", "enum": ["low", "medium", "high"]},
                },
            },
        },
        "non_generic_insights": {
            "type": "array",
            "minItems": 3,
            "items": {"type": "string", "minLength": 12},
        },
        "decision_tests": {
            "type": "array",
            "minItems": 5,
            "items": {"type": "string", "minLength": 12},
        },
        "final_recommendation": {
            "type": "string",
            "enum": FINAL_RECOMMENDATIONS,
        },
        "report_markdown": {"type": "string", "minLength": 500},
    },
}


class SmokeFailure(Exception):
    """Raised when a smoke run cannot produce an acceptable result."""


class AudienceBackend(Protocol):
    name: str
    model: str
    call_count: int

    def generate(self, payload: dict[str, str]) -> dict[str, Any]:
        """Generate a validated audience-panel result."""


@dataclass
class OpenAIBackend:
    model: str | None = None

    name: str = "openai"
    call_count: int = 0

    def generate(self, payload: dict[str, str]) -> dict[str, Any]:
        client = LLMClient(model=self.model)
        self.model = client.model_for_task("json")
        self.call_count += 1
        return client.chat_schema(
            task="json",
            schema=AUDIENCE_PANEL_SCHEMA,
            messages=build_messages(payload),
            temperature=0.2,
            max_tokens=8192,
        )


@dataclass
class AntigravityBackend:
    model: str = "Gemini 3.1 Pro (High)"
    timeout_seconds: int = 300

    name: str = "antigravity"
    call_count: int = 0

    def generate(self, payload: dict[str, str]) -> dict[str, Any]:
        self.call_count += 1
        prompt = build_single_prompt(payload)
        try:
            result = subprocess.run(
                ["agy", "--model", self.model, "--print", prompt],
                cwd=ROOT,
                check=False,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=self.timeout_seconds,
            )
        except subprocess.TimeoutExpired as exc:
            raise SmokeFailure(
                f"antigravity timeout after {self.timeout_seconds}s"
            ) from exc

        if result.returncode != 0:
            raise SmokeFailure(
                "antigravity command failed "
                f"(code={result.returncode}, stderr_chars={len(result.stderr)})"
            )

        try:
            parsed = LLMClient._parse_json_response(result.stdout.strip())
        except json.JSONDecodeError as exc:
            raise SmokeFailure(
                f"antigravity returned invalid JSON (chars={len(result.stdout)}, error={exc.msg})"
            ) from exc

        validation_error = validate_json_schema(parsed, AUDIENCE_PANEL_SCHEMA)
        if validation_error:
            path, message = validation_error
            raise SmokeFailure(
                f"antigravity schema validation failed (path={path}, error={message})"
            )
        return parsed


def load_input(path: Path) -> dict[str, str]:
    text = path.read_text(encoding="utf-8")
    if path.suffix.lower() == ".json":
        data = json.loads(text)
        return {
            "topic_summary": str(data.get("topic_summary", "")).strip(),
            "audience_hypothesis": str(data.get("audience_hypothesis", "")).strip(),
            "decision_question": str(data.get("decision_question", "")).strip(),
            "operator_context_optional": str(data.get("operator_context_optional", "")).strip(),
        }

    question = markdown_section(text, "Question")
    intended_use = markdown_section(text, "Intended Use")
    constraints = markdown_section(text, "Constraints")
    decision = markdown_section(text, "Decision The Report Must Support")
    return {
        "topic_summary": "\n\n".join(part for part in [question, intended_use] if part).strip(),
        "audience_hypothesis": intended_use.strip(),
        "decision_question": (question or decision).strip(),
        "operator_context_optional": "\n\n".join(part for part in [constraints, decision] if part).strip(),
    }


def markdown_section(text: str, heading: str) -> str:
    marker = f"## {heading}"
    start = text.find(marker)
    if start < 0:
        return ""
    body_start = text.find("\n", start)
    if body_start < 0:
        return ""
    next_heading = text.find("\n## ", body_start + 1)
    if next_heading < 0:
        next_heading = len(text)
    return text[body_start:next_heading].strip()


def build_messages(payload: dict[str, str]) -> list[dict[str, str]]:
    return [
        {
            "role": "system",
            "content": (
                "You are a private product and audience critique panel. "
                "Return only structured JSON matching the requested schema. "
                "Frame conclusions as critique and decision support, not prediction."
            ),
        },
        {"role": "user", "content": build_task_text(payload)},
    ]


def build_single_prompt(payload: dict[str, str]) -> str:
    return (
        "Return only valid JSON matching this JSON Schema. No markdown.\n"
        f"JSON Schema:\n{json.dumps(AUDIENCE_PANEL_SCHEMA, ensure_ascii=False)}\n\n"
        f"Task:\n{build_task_text(payload)}"
    )


def build_task_text(payload: dict[str, str]) -> str:
    return (
        "Build a decision-oriented audience panel report for this topic.\n\n"
        f"Topic summary:\n{payload.get('topic_summary', '')}\n\n"
        f"Audience hypothesis:\n{payload.get('audience_hypothesis', '')}\n\n"
        f"Decision question:\n{payload.get('decision_question', '')}\n\n"
        f"Operator context:\n{payload.get('operator_context_optional', '')}\n\n"
        "The report must include concrete, non-generic critique and practical next actions."
    )


def acceptance_summary(result: dict[str, Any]) -> dict[str, Any]:
    return {
        "personas": len(result.get("personas", [])),
        "objections": len(result.get("objections", [])),
        "non_generic_insights": len(result.get("non_generic_insights", [])),
        "decision_tests": len(result.get("decision_tests", [])),
        "final_recommendation": result.get("final_recommendation"),
        "report_chars": len(str(result.get("report_markdown", ""))),
    }


def write_success(output_dir: Path, result: dict[str, Any], receipt: dict[str, Any]) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "report.md").write_text(str(result["report_markdown"]).strip() + "\n", encoding="utf-8")
    (output_dir / "receipt.json").write_text(
        json.dumps(receipt, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def write_failure(output_dir: Path, receipt: dict[str, Any]) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "receipt.json").write_text(
        json.dumps(receipt, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def sanitized_error(exc: Exception) -> dict[str, str]:
    return {
        "type": type(exc).__name__,
        "message": str(exc)[:240],
    }


def run_smoke(input_path: Path, output_dir: Path, backend: AudienceBackend) -> int:
    started = time.monotonic()
    payload = load_input(input_path)
    base_receipt: dict[str, Any] = {
        "input_file": input_path.name,
        "input_chars": sum(len(value) for value in payload.values()),
        "backend": backend.name,
        "model": backend.model,
        "schema_pass": False,
    }

    try:
        result = backend.generate(payload)
        validation_error = validate_json_schema(result, AUDIENCE_PANEL_SCHEMA)
        if validation_error:
            path, message = validation_error
            raise SmokeFailure(f"schema validation failed (path={path}, error={message})")
        summary = acceptance_summary(result)
        receipt = {
            **base_receipt,
            "status": "passed",
            "model": backend.model,
            "schema_pass": True,
            "acceptance": summary,
            "elapsed_seconds": round(time.monotonic() - started, 2),
            "call_count": backend.call_count,
            "report_file": "report.md",
        }
        write_success(output_dir, result, receipt)
        print(json.dumps(receipt, ensure_ascii=False))
        return 0
    except Exception as exc:
        receipt = {
            **base_receipt,
            "status": "failed",
            "model": backend.model,
            "elapsed_seconds": round(time.monotonic() - started, 2),
            "call_count": backend.call_count,
            "error": sanitized_error(exc),
        }
        write_failure(output_dir, receipt)
        print(json.dumps(receipt, ensure_ascii=False), file=sys.stderr)
        return 1


def make_backend(name: str, model: str | None) -> AudienceBackend:
    if name == "openai":
        return OpenAIBackend(model=model)
    if name == "antigravity":
        return AntigravityBackend(model=model or "Gemini 3.1 Pro (High)")
    raise ValueError(f"Unsupported backend: {name}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--backend", choices=["openai", "antigravity"], default="openai")
    parser.add_argument("--model", default=None)
    args = parser.parse_args()
    return run_smoke(args.input, args.output, make_backend(args.backend, args.model))


if __name__ == "__main__":
    raise SystemExit(main())

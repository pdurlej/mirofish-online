#!/usr/bin/env python3
"""Run the MiroFish full-simulator risk ladder as nondestructive spikes.

The harness writes only sanitized artifacts under the selected output directory.
It does not write to Neo4j, start OASIS, mutate services, or expose routes.
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
SCRIPTS_DIR = ROOT / "scripts"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from app.utils.llm_client import LLMClient, validate_json_schema  # noqa: E402
from audience_panel_smoke import load_input  # noqa: E402


RATING_VALUES = ["green", "yellow", "red"]


GRAPH_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["nodes", "edges", "decision_useful_edges", "graph_value_summary"],
    "properties": {
        "nodes": {
            "type": "array",
            "minItems": 8,
            "items": {
                "type": "object",
                "required": ["id", "label", "type", "why_it_matters"],
                "properties": {
                    "id": {"type": "string", "minLength": 2},
                    "label": {"type": "string", "minLength": 2},
                    "type": {"type": "string", "minLength": 2},
                    "why_it_matters": {"type": "string", "minLength": 8},
                },
            },
        },
        "edges": {
            "type": "array",
            "minItems": 8,
            "items": {
                "type": "object",
                "required": ["source", "target", "relationship", "decision_relevance"],
                "properties": {
                    "source": {"type": "string", "minLength": 2},
                    "target": {"type": "string", "minLength": 2},
                    "relationship": {"type": "string", "minLength": 4},
                    "decision_relevance": {"type": "string", "minLength": 12},
                },
            },
        },
        "decision_useful_edges": {
            "type": "array",
            "minItems": 3,
            "items": {"type": "string", "minLength": 12},
        },
        "graph_value_summary": {"type": "string", "minLength": 80},
    },
}


PERSONA_DELTA_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["graph_personas", "meaningful_deltas", "delta_summary"],
    "properties": {
        "graph_personas": {
            "type": "array",
            "minItems": 8,
            "items": {
                "type": "object",
                "required": ["name", "perspective", "why_graph_made_it_better"],
                "properties": {
                    "name": {"type": "string", "minLength": 2},
                    "perspective": {"type": "string", "minLength": 8},
                    "why_graph_made_it_better": {"type": "string", "minLength": 12},
                },
            },
        },
        "meaningful_deltas": {
            "type": "array",
            "minItems": 3,
            "items": {"type": "string", "minLength": 12},
        },
        "delta_summary": {"type": "string", "minLength": 80},
    },
}


SIMULATION_DELTA_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["debate_turns", "interaction_insights", "simulation_value_summary"],
    "properties": {
        "debate_turns": {
            "type": "array",
            "minItems": 16,
            "items": {
                "type": "object",
                "required": ["persona", "turn", "response_to"],
                "properties": {
                    "persona": {"type": "string", "minLength": 2},
                    "turn": {"type": "string", "minLength": 12},
                    "response_to": {"type": "string", "minLength": 4},
                },
            },
        },
        "interaction_insights": {
            "type": "array",
            "minItems": 2,
            "items": {"type": "string", "minLength": 12},
        },
        "simulation_value_summary": {"type": "string", "minLength": 80},
    },
}


OASIS_REALITY_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["rating", "rationale", "required_work_before_live_oasis"],
    "properties": {
        "rating": {"type": "string", "enum": RATING_VALUES},
        "rationale": {"type": "string", "minLength": 80},
        "required_work_before_live_oasis": {
            "type": "array",
            "minItems": 1,
            "items": {"type": "string", "minLength": 8},
        },
    },
}


REPORT_COMPARISON_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": [
        "winner",
        "rating",
        "why",
        "unique_full_path_insights",
        "recommendation",
    ],
    "properties": {
        "winner": {"type": "string", "enum": ["tiny_panel", "full_path", "mixed"]},
        "rating": {"type": "string", "enum": RATING_VALUES},
        "why": {"type": "string", "minLength": 80},
        "unique_full_path_insights": {
            "type": "array",
            "items": {"type": "string", "minLength": 12},
        },
        "recommendation": {"type": "string", "minLength": 80},
    },
}


SPIKES = [
    "graph_value",
    "persona_delta",
    "simulation_delta",
    "oasis_reality",
    "report_comparison",
]


class SpikeFailure(Exception):
    """Raised when a spike cannot produce a valid sanitized result."""


class Backend(Protocol):
    name: str
    model: str
    call_count: int

    def generate(self, task: str, schema: dict[str, Any], prompt: str) -> dict[str, Any]:
        """Generate structured JSON for a spike."""


@dataclass
class OpenAIBackend:
    model: str = "deepseek-v4-pro"
    reasoning_effort: str = "medium"
    name: str = "openai"
    call_count: int = 0

    def generate(self, task: str, schema: dict[str, Any], prompt: str) -> dict[str, Any]:
        client = LLMClient(model=self.model)
        self.call_count += 1
        messages = [
            {
                "role": "system",
                "content": (
                    "Return only valid JSON. Treat this as a product-value spike, "
                    "not a prediction engine."
                ),
            },
            {"role": "user", "content": prompt},
        ]
        return client.chat_schema(
            task=task,
            schema=schema,
            messages=messages,
            temperature=0.2,
            max_tokens=8192,
            reasoning_effort=self.reasoning_effort,
        )


@dataclass
class AntigravityBackend:
    model: str = "Gemini 3.1 Pro (High)"
    timeout_seconds: int = 300
    name: str = "antigravity"
    call_count: int = 0

    def generate(self, task: str, schema: dict[str, Any], prompt: str) -> dict[str, Any]:
        self.call_count += 1
        full_prompt = (
            "Return only valid JSON matching this JSON Schema. No markdown.\n"
            f"JSON Schema:\n{json.dumps(schema, ensure_ascii=False)}\n\n"
            f"Task:\n{prompt}"
        )
        try:
            result = subprocess.run(
                ["agy", "--model", self.model, "--print", full_prompt],
                cwd=ROOT,
                check=False,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=self.timeout_seconds,
            )
        except subprocess.TimeoutExpired as exc:
            raise SpikeFailure(
                f"antigravity timeout after {self.timeout_seconds}s"
            ) from exc

        if result.returncode != 0:
            raise SpikeFailure(
                "antigravity command failed "
                f"(code={result.returncode}, stderr_chars={len(result.stderr)})"
            )
        try:
            parsed = LLMClient._parse_json_response(result.stdout.strip())
        except json.JSONDecodeError as exc:
            raise SpikeFailure(
                f"antigravity returned invalid JSON (chars={len(result.stdout)}, error={exc.msg})"
            ) from exc
        validation_error = validate_json_schema(parsed, schema)
        if validation_error:
            path, message = validation_error
            raise SpikeFailure(f"schema validation failed (path={path}, error={message})")
        return parsed


@dataclass
class FakeBackend:
    name: str = "fake"
    model: str = "fake-model"
    call_count: int = 0

    def generate(self, task: str, schema: dict[str, Any], prompt: str) -> dict[str, Any]:
        self.call_count += 1
        _ = (schema, prompt)
        return fake_result(task)


def fake_result(task: str) -> dict[str, Any]:
    if task == "graph_value":
        return {
            "nodes": [
                {
                    "id": f"node-{index}",
                    "label": f"Node {index}",
                    "type": "concept",
                    "why_it_matters": "This node matters to the product decision.",
                }
                for index in range(8)
            ],
            "edges": [
                {
                    "source": f"node-{index}",
                    "target": f"node-{(index + 1) % 8}",
                    "relationship": "influences",
                    "decision_relevance": "This edge clarifies whether the full path adds value.",
                }
                for index in range(8)
            ],
            "decision_useful_edges": [
                "Graph edge reveals a non-obvious risk.",
                "Graph edge reveals a useful audience segment.",
                "Graph edge reveals a dependency between quality and trust.",
            ],
            "graph_value_summary": "The graph offers enough structure to test persona generation but not enough to prove full simulation value alone.",
        }
    if task == "persona_delta":
        return {
            "graph_personas": [
                {
                    "name": f"Graph Persona {index}",
                    "perspective": "specific graph-derived product perspective",
                    "why_graph_made_it_better": "The graph connected this persona to a sharper decision risk.",
                }
                for index in range(8)
            ],
            "meaningful_deltas": [
                "Graph persona captures a governance buyer not present in tiny panel.",
                "Graph persona captures a platform owner incentive.",
                "Graph persona captures developer-tool adoption friction.",
            ],
            "delta_summary": "Graph-derived personas add concrete subgroups, but the improvement still needs simulation evidence.",
        }
    if task == "simulation_delta":
        return {
            "debate_turns": [
                {
                    "persona": f"Persona {index % 8}",
                    "turn": "This participant responds to a prior objection with a specific tradeoff.",
                    "response_to": f"Persona {(index - 1) % 8}",
                }
                for index in range(16)
            ],
            "interaction_insights": [
                "A platform PM and governance PM jointly reframe the topic around accountability.",
                "A general PM rejects harness language until the risk is translated into launch confidence.",
            ],
            "simulation_value_summary": (
                "The debate adds some interaction value, mostly by forcing vocabulary changes "
                "and surfacing the accountability gap between ordinary PMs and AI system owners."
            ),
        }
    if task == "oasis_reality":
        return {
            "rating": "yellow",
            "rationale": "OASIS is plausible but should not be live-run until the lightweight debate path proves repeated value.",
            "required_work_before_live_oasis": [
                "Define deterministic seed and max rounds.",
                "Add sanitized receipt writer.",
                "Prove provider errors become partial artifacts.",
            ],
        }
    if task == "report_comparison":
        return {
            "winner": "mixed",
            "rating": "yellow",
            "why": "The full path adds some framing value, but the tiny panel remains cheaper and more reliable.",
            "unique_full_path_insights": ["Interaction clarified vocabulary risk."],
            "recommendation": (
                "Continue only with the graph/persona/debate path for one more bounded proof; "
                "do not invest in live OASIS until this narrower path repeatedly beats the tiny panel."
            ),
        }
    raise ValueError(f"Unknown fake task: {task}")


def topic_text(payload: dict[str, str]) -> str:
    return (
        f"Topic summary:\n{payload.get('topic_summary', '')}\n\n"
        f"Audience hypothesis:\n{payload.get('audience_hypothesis', '')}\n\n"
        f"Decision question:\n{payload.get('decision_question', '')}\n\n"
        f"Operator context:\n{payload.get('operator_context_optional', '')}\n"
    )


def prompt_for(task: str, payload: dict[str, str], prior: dict[str, Any]) -> str:
    base = topic_text(payload)
    if task == "graph_value":
        return (
            "Generate a decision-useful concept graph without writing to any database.\n\n"
            f"{base}\n"
            "Acceptance: 8+ nodes, 8+ edges, and 3 edges that help the decision."
        )
    if task == "persona_delta":
        return (
            "Generate graph-derived personas and explain how they improve over a tiny audience panel.\n\n"
            f"{base}\nGraph value result:\n{json.dumps(prior.get('graph_value', {}), ensure_ascii=False)}"
        )
    if task == "simulation_delta":
        return (
            "Run a lightweight written debate with 8 personas and 2 rounds. "
            "Identify insights caused by interaction, not solo analysis.\n\n"
            f"{base}\nPersona delta result:\n{json.dumps(prior.get('persona_delta', {}), ensure_ascii=False)}"
        )
    if task == "oasis_reality":
        return (
            "Assess whether a live OASIS/CAMEL run is worth doing next. "
            "Do not pretend a live run happened. Rate readiness green/yellow/red.\n\n"
            f"{base}\nSimulation delta result:\n{json.dumps(prior.get('simulation_delta', {}), ensure_ascii=False)}"
        )
    if task == "report_comparison":
        return (
            "Compare tiny audience panel value with graph/persona/debate and OASIS readiness. "
            "Decide whether full simulator should continue.\n\n"
            f"{base}\nPrior spike results:\n{json.dumps(prior, ensure_ascii=False)}"
        )
    raise ValueError(f"Unknown spike task: {task}")


def schema_for(task: str) -> dict[str, Any]:
    return {
        "graph_value": GRAPH_SCHEMA,
        "persona_delta": PERSONA_DELTA_SCHEMA,
        "simulation_delta": SIMULATION_DELTA_SCHEMA,
        "oasis_reality": OASIS_REALITY_SCHEMA,
        "report_comparison": REPORT_COMPARISON_SCHEMA,
    }[task]


def acceptance_for(task: str, result: dict[str, Any]) -> dict[str, Any]:
    if task == "graph_value":
        return {
            "passed": (
                len(result.get("nodes", [])) >= 8
                and len(result.get("edges", [])) >= 8
                and len(result.get("decision_useful_edges", [])) >= 3
            ),
            "nodes": len(result.get("nodes", [])),
            "edges": len(result.get("edges", [])),
            "decision_useful_edges": len(result.get("decision_useful_edges", [])),
        }
    if task == "persona_delta":
        return {
            "passed": (
                len(result.get("graph_personas", [])) >= 8
                and len(result.get("meaningful_deltas", [])) >= 3
            ),
            "graph_personas": len(result.get("graph_personas", [])),
            "meaningful_deltas": len(result.get("meaningful_deltas", [])),
        }
    if task == "simulation_delta":
        return {
            "passed": (
                len(result.get("debate_turns", [])) >= 16
                and len(result.get("interaction_insights", [])) >= 2
            ),
            "debate_turns": len(result.get("debate_turns", [])),
            "interaction_insights": len(result.get("interaction_insights", [])),
        }
    if task == "oasis_reality":
        return {
            "passed": result.get("rating") in ["green", "yellow"],
            "rating": result.get("rating"),
            "required_work_items": len(result.get("required_work_before_live_oasis", [])),
        }
    if task == "report_comparison":
        return {
            "passed": result.get("rating") in RATING_VALUES,
            "rating": result.get("rating"),
            "winner": result.get("winner"),
            "unique_full_path_insights": len(result.get("unique_full_path_insights", [])),
        }
    raise ValueError(f"Unknown spike task: {task}")


def sanitized_error(exc: Exception) -> dict[str, str]:
    return {"type": type(exc).__name__, "message": str(exc)[:240]}


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text.rstrip() + "\n", encoding="utf-8")


def run_spike(task: str, backend: Backend, payload: dict[str, str], prior: dict[str, Any], outdir: Path) -> dict[str, Any]:
    started = time.monotonic()
    spike_dir = outdir / task
    prompt = prompt_for(task, payload, prior)
    receipt: dict[str, Any] = {
        "spike": task,
        "backend": backend.name,
        "model": backend.model,
        "input_chars": sum(len(value) for value in payload.values()),
        "prompt_chars": len(prompt),
    }
    try:
        result = backend.generate(task, schema_for(task), prompt)
        validation_error = validate_json_schema(result, schema_for(task))
        if validation_error:
            path, message = validation_error
            raise SpikeFailure(f"schema validation failed (path={path}, error={message})")
        acceptance = acceptance_for(task, result)
        receipt.update(
            {
                "status": "passed" if acceptance.get("passed") else "failed",
                "schema_pass": True,
                "acceptance": acceptance,
                "elapsed_seconds": round(time.monotonic() - started, 2),
                "call_count": backend.call_count,
            }
        )
        write_json(spike_dir / "result.json", result)
        write_json(spike_dir / "receipt.json", receipt)
        return {"receipt": receipt, "result": result}
    except Exception as exc:
        receipt.update(
            {
                "status": "failed",
                "schema_pass": False,
                "elapsed_seconds": round(time.monotonic() - started, 2),
                "call_count": backend.call_count,
                "error": sanitized_error(exc),
            }
        )
        write_json(spike_dir / "receipt.json", receipt)
        return {"receipt": receipt, "result": None}


def final_rating(receipts: list[dict[str, Any]]) -> str:
    by_spike = {receipt["spike"]: receipt for receipt in receipts}
    comparison = by_spike.get("report_comparison", {})
    if comparison.get("status") != "passed":
        return "red"
    comparison_rating = (comparison.get("acceptance") or {}).get("rating")
    if comparison_rating == "green":
        return "green"
    if comparison_rating == "yellow":
        return "yellow"
    return "red"


def recommendation_text(rating: str, receipts: list[dict[str, Any]]) -> str:
    passed = [receipt["spike"] for receipt in receipts if receipt.get("status") == "passed"]
    failed = [receipt["spike"] for receipt in receipts if receipt.get("status") != "passed"]
    if rating == "green":
        next_step = "Continue toward a full simulator proof with a tiny live OASIS run."
    elif rating == "yellow":
        next_step = "Continue only with the graph/persona/debate path; keep OASIS deferred."
    else:
        next_step = "Stop full simulator work and productize the simpler Audience Panel."
    return (
        f"# Full Simulator Spike Recommendation\n\n"
        f"Rating: **{rating}**\n\n"
        f"Passed spikes: {', '.join(passed) or 'none'}\n\n"
        f"Failed spikes: {', '.join(failed) or 'none'}\n\n"
        f"Recommendation: {next_step}\n"
    )


def make_backend(name: str, model: str, reasoning_effort: str) -> Backend:
    if name == "fake":
        return FakeBackend()
    if name == "openai":
        return OpenAIBackend(model=model, reasoning_effort=reasoning_effort)
    if name == "antigravity":
        return AntigravityBackend(model=model)
    raise ValueError(f"Unsupported backend: {name}")


def run_ladder(input_path: Path, output_dir: Path, backend: Backend) -> int:
    payload = load_input(input_path)
    output_dir.mkdir(parents=True, exist_ok=True)
    prior: dict[str, Any] = {}
    receipts: list[dict[str, Any]] = []
    for task in SPIKES:
        outcome = run_spike(task, backend, payload, prior, output_dir)
        receipts.append(outcome["receipt"])
        if outcome["result"] is not None:
            prior[task] = outcome["result"]
    rating = final_rating(receipts)
    summary = {
        "rating": rating,
        "backend": backend.name,
        "model": backend.model,
        "spikes": receipts,
    }
    write_json(output_dir / "summary.json", summary)
    write_text(output_dir / "recommendation.md", recommendation_text(rating, receipts))
    print(json.dumps({"rating": rating, "output_dir": str(output_dir), "spikes": len(receipts)}, ensure_ascii=False))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--backend", choices=["openai", "antigravity", "fake"], default="openai")
    parser.add_argument("--model", default="deepseek-v4-pro")
    parser.add_argument("--reasoning-effort", default="medium", choices=["low", "medium", "high"])
    args = parser.parse_args()
    return run_ladder(args.input, args.output, make_backend(args.backend, args.model, args.reasoning_effort))


if __name__ == "__main__":
    raise SystemExit(main())

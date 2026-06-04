from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace


ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = ROOT / "scripts" / "audience_panel_smoke.py"


def load_smoke_module():
    spec = importlib.util.spec_from_file_location("audience_panel_smoke", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def valid_result() -> dict:
    return {
        "personas": [
            {
                "name": f"Persona {index}",
                "perspective": "specific audience perspective",
                "incentive": "clear incentive for judging this idea",
                "likely_objection": "concrete objection to the idea",
            }
            for index in range(8)
        ],
        "objections": [
            {
                "objection": f"Concrete objection {index}",
                "why_it_matters": "This changes whether Piotr should invest time.",
                "severity": "medium",
            }
            for index in range(8)
        ],
        "non_generic_insights": [
            "This tool must prove decision impact before UI polish.",
            "Audience critique matters more than simulation theater.",
            "The first smoke should bypass the brittle graph pipeline.",
        ],
        "decision_tests": [
            "Run one topic and mark whether the next action changed.",
            "Check if objections are specific to this topic.",
            "Compare model routes only after one complete report exists.",
            "Record cost before any repeated usage.",
            "Stop if the report requires manual prompt debugging.",
        ],
        "final_recommendation": "narrow",
        "report_markdown": "# Report\n\n" + ("This is a concrete product critique. " * 40),
    }


class FakeBackend:
    name = "fake"
    model = "fake-model"
    call_count = 0

    def __init__(self, result):
        self.result = result

    def generate(self, _payload):
        self.call_count += 1
        return self.result


def write_private_input(tmp_path: Path) -> Path:
    input_path = tmp_path / "input.json"
    input_path.write_text(
        json.dumps(
            {
                "topic_summary": "SECRET_PRIVATE_TOPIC should not leak",
                "audience_hypothesis": "private audience",
                "decision_question": "Should this continue?",
                "operator_context_optional": "private context",
            }
        ),
        encoding="utf-8",
    )
    return input_path


def test_smoke_runner_writes_report_and_sanitized_receipt(tmp_path):
    smoke = load_smoke_module()
    input_path = write_private_input(tmp_path)
    output_dir = tmp_path / "out"

    status = smoke.run_smoke(input_path, output_dir, FakeBackend(valid_result()))

    assert status == 0
    assert (output_dir / "report.md").exists()
    receipt = json.loads((output_dir / "receipt.json").read_text(encoding="utf-8"))
    assert receipt["status"] == "passed"
    assert receipt["schema_pass"] is True
    assert receipt["acceptance"]["personas"] == 8
    assert "SECRET_PRIVATE_TOPIC" not in json.dumps(receipt)


def test_smoke_runner_fails_minimums_without_leaking_private_input(tmp_path):
    smoke = load_smoke_module()
    input_path = write_private_input(tmp_path)
    output_dir = tmp_path / "out"
    bad = valid_result()
    bad["personas"] = bad["personas"][:1]

    status = smoke.run_smoke(input_path, output_dir, FakeBackend(bad))

    assert status == 1
    receipt_text = (output_dir / "receipt.json").read_text(encoding="utf-8")
    receipt = json.loads(receipt_text)
    assert receipt["status"] == "failed"
    assert receipt["schema_pass"] is False
    assert "$.personas" in receipt["error"]["message"]
    assert "SECRET_PRIVATE_TOPIC" not in receipt_text


def test_antigravity_backend_parses_valid_json(monkeypatch):
    smoke = load_smoke_module()
    payload = {
        "topic_summary": "topic",
        "audience_hypothesis": "audience",
        "decision_question": "question",
        "operator_context_optional": "context",
    }

    def fake_run(*_args, **_kwargs):
        return SimpleNamespace(
            returncode=0,
            stdout=json.dumps(valid_result()),
            stderr="",
        )

    monkeypatch.setattr(subprocess, "run", fake_run)

    result = smoke.AntigravityBackend().generate(payload)

    assert result["final_recommendation"] == "narrow"


def test_antigravity_backend_error_does_not_include_stderr(monkeypatch):
    smoke = load_smoke_module()

    def fake_run(*_args, **_kwargs):
        return SimpleNamespace(
            returncode=7,
            stdout="",
            stderr="SECRET_PRIVATE_TOPIC should not leak",
        )

    monkeypatch.setattr(subprocess, "run", fake_run)

    try:
        smoke.AntigravityBackend().generate({})
    except smoke.SmokeFailure as exc:
        message = str(exc)
    else:
        raise AssertionError("Expected SmokeFailure")

    assert "SECRET_PRIVATE_TOPIC" not in message
    assert "stderr_chars=" in message


def test_smoke_module_does_not_import_heavy_mirofish_pipeline():
    code = f"""
import importlib.util
import sys
from pathlib import Path
path = Path({str(SCRIPT_PATH)!r})
spec = importlib.util.spec_from_file_location("audience_panel_smoke_probe", path)
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)
print("app.storage.ner_extractor" in sys.modules)
print("app.services.report_agent" in sys.modules)
"""
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=ROOT / "backend",
        check=True,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    assert result.stdout.splitlines() == ["False", "False"]

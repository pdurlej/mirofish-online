from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = ROOT / "scripts" / "full_simulator_spikes.py"


def load_spikes_module():
    spec = importlib.util.spec_from_file_location("full_simulator_spikes", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def write_private_input(tmp_path: Path) -> Path:
    input_path = tmp_path / "input.json"
    input_path.write_text(
        json.dumps(
            {
                "topic_summary": "SECRET_PRIVATE_TOPIC should not leak",
                "audience_hypothesis": "private audience",
                "decision_question": "Should full simulator continue?",
                "operator_context_optional": "private context",
            }
        ),
        encoding="utf-8",
    )
    return input_path


def test_fake_ladder_writes_sanitized_summary(tmp_path):
    spikes = load_spikes_module()
    output_dir = tmp_path / "out"

    status = spikes.run_ladder(
        write_private_input(tmp_path),
        output_dir,
        spikes.FakeBackend(),
    )

    assert status == 0
    summary_text = (output_dir / "summary.json").read_text(encoding="utf-8")
    summary = json.loads(summary_text)
    assert summary["rating"] == "yellow"
    assert len(summary["spikes"]) == 5
    assert all(receipt["status"] == "passed" for receipt in summary["spikes"])
    assert "SECRET_PRIVATE_TOPIC" not in summary_text
    assert (output_dir / "recommendation.md").exists()


def test_graph_acceptance_rejects_too_few_edges():
    spikes = load_spikes_module()
    result = spikes.fake_result("graph_value")
    result["edges"] = result["edges"][:2]

    acceptance = spikes.acceptance_for("graph_value", result)

    assert acceptance["passed"] is False
    assert acceptance["edges"] == 2


def test_persona_delta_rejects_no_meaningful_delta():
    spikes = load_spikes_module()
    result = spikes.fake_result("persona_delta")
    result["meaningful_deltas"] = []

    acceptance = spikes.acceptance_for("persona_delta", result)

    assert acceptance["passed"] is False
    assert acceptance["meaningful_deltas"] == 0


def test_simulation_delta_requires_interaction_insights():
    spikes = load_spikes_module()
    result = spikes.fake_result("simulation_delta")
    result["interaction_insights"] = ["only one interaction-derived insight"]

    acceptance = spikes.acceptance_for("simulation_delta", result)

    assert acceptance["passed"] is False
    assert acceptance["interaction_insights"] == 1


def test_failed_spike_receipt_does_not_leak_input(tmp_path):
    spikes = load_spikes_module()

    class BadBackend:
        name = "bad"
        model = "bad-model"
        call_count = 0

        def generate(self, _task, _schema, _prompt):
            self.call_count += 1
            raise RuntimeError("provider failed")

    output_dir = tmp_path / "out"
    status = spikes.run_ladder(write_private_input(tmp_path), output_dir, BadBackend())

    assert status == 0
    summary_text = (output_dir / "summary.json").read_text(encoding="utf-8")
    assert "SECRET_PRIVATE_TOPIC" not in summary_text
    assert "provider failed" in summary_text


def test_fake_mode_does_not_import_live_oasis_or_report_agent():
    code = f"""
import importlib.util
import json
import sys
from pathlib import Path
path = Path({str(SCRIPT_PATH)!r})
spec = importlib.util.spec_from_file_location("full_simulator_spikes_probe", path)
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)
print("app.services.report_agent" in sys.modules)
print("camel" in sys.modules)
print("camel_oasis" in sys.modules)
"""
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=ROOT / "backend",
        check=True,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    assert result.stdout.splitlines() == ["False", "False", "False"]

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from scripts import rs2000_lifecycle as lifecycle  # noqa: E402


FIXTURE = Path(__file__).parent / "fixtures" / "rs2000_lifecycle_contract.json"
ENV_FILE = ROOT / "deploy" / "rs2000" / ".env.example"


def completed(command: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(command, 0, stdout="", stderr="")


def test_start_orders_dependencies_model_check_app_and_resume(monkeypatch):
    commands: list[list[str]] = []
    controls: list[str] = []

    def fake_run(command: list[str]):
        commands.append(command)
        return completed(command)

    def fake_probe(url: str):
        if url.endswith("/api/tags"):
            return {"models": [{"name": "nomic-embed-text:latest"}]}
        if url.endswith("/health/ready"):
            return {"status": "ready"}
        return {"status": "ok"}

    monkeypatch.setattr(lifecycle, "run_command", fake_run)
    monkeypatch.setattr(lifecycle, "running_services", lambda _env: set())
    monkeypatch.setattr(lifecycle, "probe_json", fake_probe)
    monkeypatch.setattr(lifecycle, "probe_http", lambda _url: True)
    monkeypatch.setattr(
        lifecycle,
        "control",
        lambda _env, action: controls.append(action) or {"success": True},
    )

    lifecycle.start_stack(
        ENV_FILE,
        wait_seconds=0,
        embedding_model="nomic-embed-text",
    )

    compose_actions = [command[-2:] for command in commands]
    assert compose_actions == [
        ["start", "neo4j"],
        ["start", "embedding-ollama"],
        ["start", "mirofish"],
    ]
    assert controls == ["resume"]
    assert not any("pull" in command for command in commands)


def test_failed_start_rolls_back_only_services_started_by_this_run(monkeypatch):
    commands: list[list[str]] = []

    monkeypatch.setattr(
        lifecycle,
        "run_command",
        lambda command: commands.append(command) or completed(command),
    )
    monkeypatch.setattr(
        lifecycle,
        "running_services",
        lambda _env: {"neo4j"},
    )
    monkeypatch.setattr(lifecycle, "probe_http", lambda _url: True)
    monkeypatch.setattr(lifecycle, "probe_json", lambda _url: None)

    with pytest.raises(lifecycle.LifecycleError, match="embedding model"):
        lifecycle.start_stack(
            ENV_FILE,
            wait_seconds=0,
            embedding_model="nomic-embed-text",
        )

    assert [command[-2:] for command in commands] == [
        ["start", "neo4j"],
        ["start", "embedding-ollama"],
        ["stop", "embedding-ollama"],
    ]


def test_stop_drains_refuses_busy_and_never_stops_services(monkeypatch):
    controls: list[str] = []
    commands: list[list[str]] = []

    def fake_control(_env: Path, action: str):
        controls.append(action)
        if action == "status":
            return {"success": True, "lifecycle": {"idle": False}}
        return {"success": True, "lifecycle": {"draining": True}}

    monkeypatch.setattr(lifecycle, "control", fake_control)
    monkeypatch.setattr(
        lifecycle,
        "run_command",
        lambda command: commands.append(command) or completed(command),
    )

    with pytest.raises(lifecycle.LifecycleError, match="timed out"):
        lifecycle.stop_stack(ENV_FILE, wait_seconds=0)

    assert controls == ["drain", "status", "resume"]
    assert commands == []


def test_stop_orders_app_ollama_neo4j_after_idle(monkeypatch):
    commands: list[list[str]] = []
    controls: list[str] = []

    def fake_control(_env: Path, action: str):
        controls.append(action)
        return {"success": True, "lifecycle": {"idle": True}}

    monkeypatch.setattr(lifecycle, "control", fake_control)
    monkeypatch.setattr(
        lifecycle,
        "run_command",
        lambda command: commands.append(command) or completed(command),
    )

    lifecycle.stop_stack(ENV_FILE, wait_seconds=0)

    assert controls == ["drain", "status"]
    assert [command[-2:] for command in commands] == [
        ["stop", "mirofish"],
        ["stop", "embedding-ollama"],
        ["stop", "neo4j"],
    ]


def test_cli_has_no_force_path():
    args = lifecycle.build_parser().parse_args(["stop"])
    assert args.wait_seconds == 900
    assert not hasattr(args, "force")


def test_control_uses_application_virtualenv(monkeypatch):
    seen: list[list[str]] = []

    def fake_run(command: list[str]):
        seen.append(command)
        return subprocess.CompletedProcess(
            command,
            0,
            stdout='{"success": true, "lifecycle": {"idle": true}}',
            stderr="",
        )

    monkeypatch.setattr(lifecycle, "run_command", fake_run)

    lifecycle.control(ENV_FILE, "status")

    assert lifecycle.APP_PYTHON in seen[0]
    assert seen[0][-2:] == [lifecycle.APP_CONTROL, "status"]


def test_volume_and_model_metadata_contract_is_preserved():
    contract = json.loads(FIXTURE.read_text())
    compose_text = lifecycle.COMPOSE_FILE.read_text()
    env_text = lifecycle.EXAMPLE_ENV_FILE.read_text()
    script_text = Path(lifecycle.__file__).read_text()

    for volume in contract["persistent_volumes"]:
        assert volume in compose_text
    assert (
        f"EMBEDDING_MODEL={contract['default_embedding_model']}"
        in env_text
    )
    for action in contract["forbidden_compose_actions"]:
        assert f'"{action}"' not in script_text

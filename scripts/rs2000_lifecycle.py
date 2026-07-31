#!/usr/bin/env python3
"""Operator-driven start/stop lifecycle for the dedicated RS2000 stack."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Callable


ROOT = Path(__file__).resolve().parents[1]
COMPOSE_FILE = ROOT / "deploy" / "rs2000" / "docker-compose.cloud-smoke.yml"
DEFAULT_ENV_FILE = ROOT / "deploy" / "rs2000" / ".env"
EXAMPLE_ENV_FILE = ROOT / "deploy" / "rs2000" / ".env.example"
APP_CONTROL = "/app/backend/app/lifecycle.py"
APP_PYTHON = "/app/backend/.venv/bin/python"


class LifecycleError(Exception):
    """A sanitized lifecycle failure suitable for operator output."""


def run_command(command: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=ROOT,
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )


def compose_command(env_file: Path, *args: str) -> list[str]:
    return [
        "docker",
        "compose",
        "--env-file",
        str(env_file),
        "-f",
        str(COMPOSE_FILE),
        *args,
    ]


def run_compose(env_file: Path, *args: str) -> str:
    result = run_command(compose_command(env_file, *args))
    if result.returncode != 0:
        raise LifecycleError(f"compose {' '.join(args[:2])} failed")
    return result.stdout


def running_services(env_file: Path) -> set[str]:
    output = run_compose(
        env_file,
        "ps",
        "--status",
        "running",
        "--services",
    )
    return {line.strip() for line in output.splitlines() if line.strip()}


def control(env_file: Path, action: str) -> dict[str, Any]:
    output = run_compose(
        env_file,
        "exec",
        "-T",
        "mirofish",
        APP_PYTHON,
        APP_CONTROL,
        action,
    )
    try:
        payload = json.loads(output)
    except json.JSONDecodeError as exc:
        raise LifecycleError("application lifecycle control returned invalid JSON") from exc
    if not payload.get("success"):
        raise LifecycleError(f"application lifecycle {action} refused")
    return payload


def probe_json(url: str) -> dict[str, Any] | None:
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "mirofish-rs2000-lifecycle/1"},
    )
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            if not 200 <= response.status < 300:
                return None
            payload = json.loads(response.read().decode("utf-8"))
            return payload if isinstance(payload, dict) else None
    except (
        urllib.error.URLError,
        TimeoutError,
        ConnectionError,
        UnicodeDecodeError,
        json.JSONDecodeError,
    ):
        return None


def probe_http(url: str) -> bool:
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "mirofish-rs2000-lifecycle/1"},
    )
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            return 200 <= response.status < 500
    except (urllib.error.URLError, TimeoutError, ConnectionError):
        return False


def wait_for(
    description: str,
    predicate: Callable[[], bool],
    wait_seconds: int,
) -> None:
    deadline = time.monotonic() + max(wait_seconds, 0)
    while True:
        if predicate():
            return
        if time.monotonic() >= deadline:
            raise LifecycleError(f"timed out waiting for {description}")
        time.sleep(min(2.0, max(deadline - time.monotonic(), 0.0)))


def configured_model_present(payload: dict[str, Any], model: str) -> bool:
    configured = model.removesuffix(":latest")
    return any(
        str(item.get("name") or item.get("model") or "").removesuffix(":latest")
        == configured
        for item in payload.get("models") or []
        if isinstance(item, dict)
    )


def start_stack(
    env_file: Path,
    *,
    wait_seconds: int,
    embedding_model: str,
) -> None:
    api_port = os.environ.get("MIROFISH_API_PORT", "15001")
    running_before = running_services(env_file)
    started: list[str] = []

    def start_service(service: str) -> None:
        if service not in running_before:
            started.append(service)
        run_compose(env_file, "start", service)

    try:
        start_service("neo4j")
        wait_for(
            "Neo4j health",
            lambda: probe_http("http://127.0.0.1:17474"),
            wait_seconds,
        )

        start_service("embedding-ollama")

        def embedding_ready() -> bool:
            payload = probe_json("http://127.0.0.1:11435/api/tags")
            return bool(payload and configured_model_present(payload, embedding_model))

        wait_for(
            f"configured embedding model {embedding_model}",
            embedding_ready,
            wait_seconds,
        )

        start_service("mirofish")
        wait_for(
            "application liveness",
            lambda: (
                probe_json(f"http://127.0.0.1:{api_port}/health/live") is not None
            ),
            wait_seconds,
        )
        control(env_file, "resume")
        wait_for(
            "application readiness",
            lambda: (
                probe_json(f"http://127.0.0.1:{api_port}/health/ready") or {}
            ).get("status")
            == "ready",
            wait_seconds,
        )
    except LifecycleError:
        for service in reversed(started):
            try:
                run_compose(env_file, "stop", service)
            except LifecycleError:
                pass
        raise


def stop_stack(env_file: Path, *, wait_seconds: int) -> None:
    running = running_services(env_file)
    if "mirofish" in running:
        control(env_file, "drain")
        try:
            wait_for(
                "in-process work to become idle",
                lambda: bool(
                    (control(env_file, "status").get("lifecycle") or {}).get(
                        "idle"
                    )
                ),
                wait_seconds,
            )
        except LifecycleError:
            try:
                control(env_file, "resume")
            except LifecycleError:
                pass
            raise

    for service in ("mirofish", "embedding-ollama", "neo4j"):
        if service in running:
            run_compose(env_file, "stop", service)


def status(env_file: Path) -> dict[str, Any]:
    try:
        payload = control(env_file, "status")
    except LifecycleError:
        return {
            "schema": "mirofish.rs2000-lifecycle.v0",
            "application_reachable": False,
        }
    return {
        "schema": "mirofish.rs2000-lifecycle.v0",
        "application_reachable": True,
        "lifecycle": payload["lifecycle"],
    }


def default_env_file() -> Path:
    return DEFAULT_ENV_FILE if DEFAULT_ENV_FILE.exists() else EXAMPLE_ENV_FILE


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--env-file",
        type=Path,
        default=default_env_file(),
        help="Compose environment file; values are never printed",
    )
    subparsers = parser.add_subparsers(dest="action", required=True)

    status_parser = subparsers.add_parser("status")
    status_parser.add_argument("--json", action="store_true")

    start_parser = subparsers.add_parser("start")
    start_parser.add_argument("--wait-seconds", type=int, default=180)
    start_parser.add_argument(
        "--embedding-model",
        default=os.environ.get("EMBEDDING_MODEL", "nomic-embed-text"),
    )

    stop_parser = subparsers.add_parser("stop")
    stop_parser.add_argument("--wait-seconds", type=int, default=900)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        if args.action == "status":
            payload = status(args.env_file)
            if args.json:
                print(json.dumps(payload, sort_keys=True))
            else:
                state = "reachable" if payload["application_reachable"] else "stopped"
                print(f"MiroFish lifecycle: {state}")
            return 0
        if args.action == "start":
            start_stack(
                args.env_file,
                wait_seconds=args.wait_seconds,
                embedding_model=args.embedding_model,
            )
            print("MiroFish lifecycle: ready")
            return 0
        stop_stack(args.env_file, wait_seconds=args.wait_seconds)
        print("MiroFish lifecycle: stopped")
        return 0
    except LifecycleError as exc:
        print(f"MiroFish lifecycle failed: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

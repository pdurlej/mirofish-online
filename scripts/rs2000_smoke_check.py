#!/usr/bin/env python3
"""Validate the RS2000 private smoke profile without printing secrets.

Default mode renders Docker Compose and checks the intended exposure shape:
only host-local published ports, Traefik pointed at the UI port, Neo4j memory
bounded to 2 GiB, and no raw backend/Neo4j/Ollama service exposed via Traefik.

Runtime mode adds localhost HTTP probes, but still never starts or mutates the
stack. It is meant for an operator-approved private RS2000 smoke run.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
COMPOSE_FILE = ROOT / "deploy" / "rs2000" / "docker-compose.cloud-smoke.yml"
ENV_FILE = ROOT / "deploy" / "rs2000" / ".env.example"
LOCALHOST = {"127.0.0.1", "localhost"}
FORBIDDEN_TRAEFIK_PORTS = {"5001", "7474", "7687", "11434"}


class CheckFailure(Exception):
    """Raised when the smoke profile violates a safety invariant."""


def run_json(command: list[str]) -> dict[str, Any]:
    result = subprocess.run(
        command,
        cwd=ROOT,
        check=True,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    return json.loads(result.stdout)


def compose_config() -> dict[str, Any]:
    return run_json(
        [
            "docker",
            "compose",
            "--env-file",
            str(ENV_FILE),
            "-f",
            str(COMPOSE_FILE),
            "config",
            "--format",
            "json",
        ]
    )


def require(condition: bool, message: str) -> None:
    if not condition:
        raise CheckFailure(message)


def published_ports(service: dict[str, Any]) -> list[dict[str, Any]]:
    return service.get("ports") or []


def validate_host_local_ports(services: dict[str, Any]) -> None:
    for service_name, service in services.items():
        for port in published_ports(service):
            host_ip = port.get("host_ip")
            target = port.get("target")
            require(
                host_ip in LOCALHOST,
                f"{service_name} target {target} is published on non-local host_ip {host_ip!r}",
            )


def validate_traefik_shape(services: dict[str, Any]) -> None:
    mirofish = services["mirofish"]
    labels = mirofish.get("labels") or {}

    require(
        labels.get("traefik.http.services.mirofish-online.loadbalancer.server.port") == "3000",
        "Traefik must target the UI service port 3000 only",
    )
    require(
        labels.get("traefik.http.routers.mirofish-online.tls.certresolver") == "le",
        "Traefik TLS certresolver must match the platform resolver 'le'",
    )
    for key, value in labels.items():
        if key.startswith("traefik.http.services.") and str(value) in FORBIDDEN_TRAEFIK_PORTS:
            raise CheckFailure(f"Traefik label {key} exposes forbidden raw service port {value}")

    for service_name, service in services.items():
        networks = service.get("networks") or {}
        if service_name == "mirofish":
            require("platform-proxy" in networks, "mirofish must join platform-proxy for UI routing")
        else:
            require(
                "platform-proxy" not in networks,
                f"{service_name} must not join platform-proxy",
            )


def validate_neo4j_memory(services: dict[str, Any]) -> None:
    neo4j = services["neo4j"]
    env = neo4j.get("environment") or {}
    require(str(neo4j.get("mem_limit")) == str(2 * 1024 * 1024 * 1024), "Neo4j mem_limit must be 2 GiB")
    require(env.get("NEO4J_server_memory_heap_max__size") == "1g", "Neo4j heap max must be 1g")
    require(env.get("NEO4J_server_memory_pagecache_size") == "512m", "Neo4j pagecache must be 512m")


def validate_required_services(services: dict[str, Any]) -> None:
    required = {"mirofish", "neo4j", "embedding-ollama"}
    missing = sorted(required - set(services))
    require(not missing, f"Missing required services: {', '.join(missing)}")


def validate_compose(config: dict[str, Any]) -> list[str]:
    services = config.get("services") or {}
    validate_required_services(services)
    validate_host_local_ports(services)
    validate_traefik_shape(services)
    validate_neo4j_memory(services)
    return [
        "compose renders as JSON",
        "required services exist",
        "all published ports are host-local",
        "Traefik routes UI port 3000 only",
        "Traefik uses the platform TLS certresolver le",
        "Neo4j memory limit is bounded to 2 GiB",
        "Neo4j/Bolt/backend/Ollama are not joined to platform-proxy",
    ]


def http_probe(url: str) -> None:
    request = urllib.request.Request(url, headers={"User-Agent": "mirofish-smoke-check/1"})
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            require(200 <= response.status < 500, f"{url} returned unexpected status {response.status}")
    except urllib.error.URLError as exc:
        raise CheckFailure(f"{url} probe failed: {exc}") from exc


def validate_runtime() -> list[str]:
    ui_port = os.environ.get("MIROFISH_UI_PORT", "13000")
    api_port = os.environ.get("MIROFISH_API_PORT", "15001")
    http_probe(f"http://127.0.0.1:{ui_port}/")
    http_probe(f"http://127.0.0.1:{api_port}/health")
    return [
        f"UI answered on 127.0.0.1:{ui_port}",
        f"backend health answered on 127.0.0.1:{api_port}",
    ]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--runtime",
        action="store_true",
        help="also probe already-running localhost services; does not start containers",
    )
    args = parser.parse_args()

    try:
        checks = validate_compose(compose_config())
        if args.runtime:
            checks.extend(validate_runtime())
    except CheckFailure as exc:
        print(f"RS2000 smoke check failed: {exc}", file=sys.stderr)
        return 1

    print("RS2000 smoke check passed:")
    for check in checks:
        print(f"- {check}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

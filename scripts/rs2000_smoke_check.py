#!/usr/bin/env python3
"""Validate the RS2000 private smoke profile without printing secrets.

Default mode renders Docker Compose and checks the intended exposure shape:
only host-local published ports, Traefik pointed at the unified application
port, Neo4j memory bounded to 2 GiB, and no raw Neo4j/Ollama service exposed
via Traefik.

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


def validate_memory_limits(services: dict[str, Any]) -> None:
    expected = {
        "mirofish": 2 * 1024 * 1024 * 1024,
        "neo4j": 2 * 1024 * 1024 * 1024,
        "embedding-ollama": 1536 * 1024 * 1024,
    }
    for name, limit in expected.items():
        require(
            str(services[name].get("mem_limit")) == str(limit),
            f"{name} mem_limit must be {limit} bytes",
        )

    neo4j = services["neo4j"]
    env = neo4j.get("environment") or {}
    require(env.get("NEO4J_server_memory_heap_max__size") == "1g", "Neo4j heap max must be 1g")
    require(env.get("NEO4J_server_memory_pagecache_size") == "512m", "Neo4j pagecache must be 512m")


def volume_sources(service: dict[str, Any]) -> set[str]:
    return {
        str(mount.get("source"))
        for mount in service.get("volumes") or []
        if isinstance(mount, dict) and mount.get("type") == "volume"
    }


def validate_lifecycle_shape(services: dict[str, Any]) -> None:
    mirofish = services["mirofish"]
    neo4j = services["neo4j"]
    embedding = services["embedding-ollama"]
    dependencies = mirofish.get("depends_on") or {}
    environment = mirofish.get("environment") or {}

    require(
        environment.get("MIROFISH_START_DRAINED") == "true",
        "mirofish must start drained until the operator readiness gate resumes it",
    )
    require(
        str(environment.get("FLASK_PORT")) == "3000",
        "mirofish must serve the SPA and API from internal port 3000",
    )
    require(
        len(published_ports(mirofish)) == 1
        and {str(port.get("target")) for port in published_ports(mirofish)} == {"3000"},
        "the host-local MiroFish entry point must target internal port 3000",
    )
    healthcheck = mirofish.get("healthcheck") or {}
    healthcheck_command = " ".join(str(part) for part in healthcheck.get("test") or [])
    require(
        "127.0.0.1:3000/health/live" in healthcheck_command,
        "mirofish liveness check must use the unified application port 3000",
    )
    require(bool(mirofish.get("healthcheck")), "mirofish must have a liveness healthcheck")
    require(bool(embedding.get("healthcheck")), "embedding-ollama must have a healthcheck")
    require(
        (dependencies.get("neo4j") or {}).get("condition") == "service_healthy",
        "mirofish must wait for healthy Neo4j",
    )
    require(
        (dependencies.get("embedding-ollama") or {}).get("condition") == "service_healthy",
        "mirofish must wait for healthy embedding-ollama",
    )
    require(bool(mirofish.get("stop_grace_period")), "mirofish needs a graceful stop period")
    require(bool(neo4j.get("stop_grace_period")), "Neo4j needs a graceful stop period")


def validate_persistent_volumes(services: dict[str, Any]) -> None:
    require(
        volume_sources(services["neo4j"]) == {"neo4j_data", "neo4j_logs"},
        "Neo4j data and logs must remain named volumes",
    )
    require(
        volume_sources(services["embedding-ollama"]) == {"embedding_ollama_data"},
        "Ollama model metadata must remain on a named volume",
    )


def validate_required_services(services: dict[str, Any]) -> None:
    required = {"mirofish", "neo4j", "embedding-ollama"}
    missing = sorted(required - set(services))
    require(not missing, f"Missing required services: {', '.join(missing)}")


def validate_compose(config: dict[str, Any]) -> list[str]:
    services = config.get("services") or {}
    validate_required_services(services)
    validate_host_local_ports(services)
    validate_traefik_shape(services)
    validate_memory_limits(services)
    validate_lifecycle_shape(services)
    validate_persistent_volumes(services)
    return [
        "compose renders as JSON",
        "required services exist",
        "all published ports are host-local",
        "Traefik routes the unified application port 3000 only",
        "Traefik uses the platform TLS certresolver le",
        "MiroFish, Neo4j, and embedding Ollama have explicit memory limits",
        "Neo4j/Bolt/Ollama are not joined to platform-proxy",
        "application starts drained and waits for healthy dependencies",
        "Neo4j and Ollama use persistent named volumes",
    ]


def http_probe(url: str) -> None:
    request = urllib.request.Request(url, headers={"User-Agent": "mirofish-smoke-check/1"})
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            require(200 <= response.status < 500, f"{url} returned unexpected status {response.status}")
    except urllib.error.URLError as exc:
        raise CheckFailure(f"{url} probe failed: {exc}") from exc


def validate_runtime() -> list[str]:
    api_port = os.environ.get("MIROFISH_API_PORT", "15001")
    http_probe(f"http://127.0.0.1:{api_port}/")
    http_probe(f"http://127.0.0.1:{api_port}/health/live")
    http_probe(f"http://127.0.0.1:{api_port}/health/ready")
    return [
        f"UI, liveness, and readiness answered on 127.0.0.1:{api_port}",
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

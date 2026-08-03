"""Error responses must stay client-safe.

Stack traces name filesystem paths, module layout, and local variables. They
belong in the server log, never in a JSON body an unauthenticated caller reads.
"""

from __future__ import annotations

from pathlib import Path


API_DIR = Path(__file__).resolve().parents[1] / "app" / "api"


def test_no_api_module_returns_a_traceback_in_its_response_body():
    offenders = []
    for module in sorted(API_DIR.glob("*.py")):
        for lineno, line in enumerate(module.read_text(encoding="utf-8").splitlines(), 1):
            if '"traceback"' in line and "format_exc" in line:
                offenders.append(f"{module.name}:{lineno}")

    assert offenders == [], (
        "API responses must not carry stack traces; log them with "
        f"logger.exception() instead. Offending lines: {offenders}"
    )


def test_background_task_records_do_not_store_stack_traces():
    graph_api = (API_DIR / "graph.py").read_text(encoding="utf-8")

    assert "error=traceback.format_exc()" not in graph_api
    assert "import traceback" not in graph_api

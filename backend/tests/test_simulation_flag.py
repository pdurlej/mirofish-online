"""MIROFISH_ENABLE_SIMULATION decides which lanes exist.

The audience lane is the product: 113 live runs in production. The document-graph
and simulation lanes are the inherited fork, and production shows what they were
used for -- one Entity node, five Episodes, one Graph, then abandoned. They are
the larger half of the API surface and no test covers their behaviour, so they
are off unless asked for.

Assertions are on registration and url_map rather than on handlers, because the
handlers reach Neo4j.
"""

from __future__ import annotations

from app import create_app
from app.config import Config

SIMULATOR_PREFIXES = ("/api/graph", "/api/simulation", "/api/report")


class SimulationOn(Config):
    MIROFISH_ENABLE_SIMULATION = True


def _rules(app) -> list[str]:
    return [str(rule.rule) for rule in app.url_map.iter_rules()]


def test_flag_off_leaves_only_the_audience_lane():
    app = create_app()

    assert sorted(app.blueprints) == ["audience"]
    assert not [
        rule
        for rule in _rules(app)
        if rule.startswith(SIMULATOR_PREFIXES)
    ]

    client = app.test_client()
    assert client.get("/api/audience/personas").status_code == 200
    # GET falls through to the SPA catch-all, which aborts 404 for /api paths.
    assert client.get("/api/simulation/list").status_code == 404
    # A mutating method gets 405, not 404: the catch-all only accepts GET, so
    # Werkzeug rejects the method before the route's own abort(404) can run.
    # Worth pinning, because it is what silently defanged the traversal tests.
    assert client.post("/api/simulation/create").status_code == 405


def test_flag_on_registers_the_inherited_lanes():
    app = create_app(SimulationOn)

    assert sorted(app.blueprints) == ["audience", "graph", "report", "simulation"]
    for prefix in SIMULATOR_PREFIXES:
        assert [rule for rule in _rules(app) if rule.startswith(prefix)], prefix

    # The audience lane is unaffected either way.
    assert create_app().test_client().get("/api/audience/personas").status_code == 200


def test_the_flag_is_off_by_default():
    assert Config.MIROFISH_ENABLE_SIMULATION is False

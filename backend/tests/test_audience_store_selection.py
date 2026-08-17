"""Audience storage selection must be a decision, not a side effect of failure."""

from __future__ import annotations

from app import create_app
from app.api import audience as audience_api
from app.audience import InMemoryAudienceGraphStore, Neo4jAudienceGraphStore
from app.config import Config


class _StubStorage:
    """Truthy stand-in for an initialized Neo4jStorage."""

    def health_check(self) -> bool:
        return True


def test_memory_store_is_chosen_even_when_neo4j_initialized_successfully(monkeypatch):
    monkeypatch.setattr(Config, "MIROFISH_AUDIENCE_STORE", "memory")
    app = create_app()
    app.extensions["neo4j_storage"] = _StubStorage()

    with app.app_context():
        assert isinstance(audience_api._get_store(), InMemoryAudienceGraphStore)


def test_auto_store_still_prefers_neo4j_when_it_is_available(monkeypatch):
    monkeypatch.setattr(Config, "MIROFISH_AUDIENCE_STORE", "auto")
    app = create_app()
    app.extensions["neo4j_storage"] = _StubStorage()

    with app.app_context():
        assert isinstance(audience_api._get_store(), Neo4jAudienceGraphStore)


def test_auto_store_falls_back_to_memory_without_neo4j(monkeypatch):
    monkeypatch.setattr(Config, "MIROFISH_AUDIENCE_STORE", "auto")
    app = create_app()
    app.extensions["neo4j_storage"] = None

    with app.app_context():
        assert isinstance(audience_api._get_store(), InMemoryAudienceGraphStore)

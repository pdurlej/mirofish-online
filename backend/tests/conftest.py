"""Test isolation for the audience lane.

Without this the suite is only green by accident. ``create_app`` builds a real
``Neo4jStorage``, whose constructor reaches ``NERExtractor() -> LLMClient()`` and
raises when ``LLM_API_KEY`` is unset, so ``app.extensions['neo4j_storage']``
lands on ``None`` and the API quietly falls back to the in-process store.

On a machine that does have ``LLM_API_KEY`` exported the same code path succeeds,
``_get_store()`` returns a ``Neo4jAudienceGraphStore``, and the tests write fake
runs into the operator's own research graph while waiting on network timeouts.
Measured before this fixture existed: one audience API test took over 100
seconds and then failed.

Two notes on the mechanics, both learned the hard way:

* Clearing ``os.environ`` does nothing here. ``Config`` reads every value once,
  while the class body executes, so isolation has to patch ``Config``
  attributes. ``tests/test_llm_client.py`` already does it that way.
* This is the only ``pytest.fixture`` in the suite, which otherwise uses plain
  helper functions. The deviation is deliberate: the thing being isolated is
  module-level global state, not repeated setup, and every test that calls
  ``create_app()`` needs it whether or not the author remembered.
"""

from __future__ import annotations

import pytest

from app.audience import InMemoryAudienceGraphStore
from app.config import Config


class _UnavailableStorage:
    """Stand-in for ``Neo4jStorage`` that never opens a connection."""

    def health_check(self) -> bool:
        return False

    def close(self) -> None:
        return None


@pytest.fixture(autouse=True)
def isolated_audience_store(monkeypatch):
    """Demand the in-process store and keep every test's graph empty."""
    from app import storage
    from app.api import audience as audience_api

    # Explicit beats accidental: the API returns the in-process store because it
    # was asked to, not because Neo4j blew up on the way in.
    monkeypatch.setattr(Config, "MIROFISH_AUDIENCE_STORE", "memory")
    monkeypatch.setattr(storage, "Neo4jStorage", _UnavailableStorage)
    monkeypatch.setattr(audience_api, "_STORE", InMemoryAudienceGraphStore())
    yield

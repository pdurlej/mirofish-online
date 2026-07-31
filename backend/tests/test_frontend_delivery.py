from __future__ import annotations

import app as app_module
from app import create_app


def test_production_frontend_serves_assets_and_spa_routes(monkeypatch, tmp_path):
    frontend_dist = tmp_path / "dist"
    assets = frontend_dist / "assets"
    assets.mkdir(parents=True)
    (frontend_dist / "index.html").write_text(
        "<html><body>CONTROLLED_FRONTEND</body></html>",
        encoding="utf-8",
    )
    (assets / "app.js").write_text("window.MIROFISH = true", encoding="utf-8")
    monkeypatch.setattr(app_module, "FRONTEND_DIST", frontend_dist)

    client = create_app().test_client()

    assert b"CONTROLLED_FRONTEND" in client.get("/").data
    assert b"CONTROLLED_FRONTEND" in client.get("/audience/graph").data
    assert client.get("/assets/app.js").data == b"window.MIROFISH = true"


def test_frontend_fallback_does_not_mask_backend_or_missing_asset_routes(
    monkeypatch,
    tmp_path,
):
    frontend_dist = tmp_path / "dist"
    frontend_dist.mkdir()
    (frontend_dist / "index.html").write_text(
        "<html><body>CONTROLLED_FRONTEND</body></html>",
        encoding="utf-8",
    )
    monkeypatch.setattr(app_module, "FRONTEND_DIST", frontend_dist)

    client = create_app().test_client()

    assert client.get("/api/does-not-exist").status_code == 404
    assert client.get("/health/does-not-exist").status_code == 404
    assert client.get("/internal/does-not-exist").status_code == 404
    assert client.get("/assets/does-not-exist.js").status_code == 404

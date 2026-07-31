from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
DOCKERFILE = ROOT / "Dockerfile"


def test_runtime_image_excludes_node_and_vite_servers():
    dockerfile = DOCKERFILE.read_text(encoding="utf-8")
    runtime = dockerfile.split("FROM python:3.11-slim AS runtime", maxsplit=1)[1]

    assert "FROM node:22-slim AS frontend-build" in dockerfile
    assert "npm run build" in dockerfile
    assert "COPY --from=frontend-build /build/frontend/dist ./frontend/dist/" in runtime
    assert "node" not in runtime.lower()
    assert "npm" not in runtime.lower()
    assert "vite" not in runtime.lower()


def test_runtime_uses_one_gunicorn_process_for_the_in_process_queue():
    dockerfile = DOCKERFILE.read_text(encoding="utf-8")
    runtime = dockerfile.split("FROM python:3.11-slim AS runtime", maxsplit=1)[1]

    assert 'EXPOSE 3000' in runtime
    assert '"/app/backend/.venv/bin/gunicorn"' in runtime
    assert '"--bind", "0.0.0.0:3000"' in runtime
    assert '"--workers", "1"' in runtime
    assert '"--no-control-socket"' in runtime
    assert '"app:create_app()"' in runtime
    assert 'npm run dev' not in runtime

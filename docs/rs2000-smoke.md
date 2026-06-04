# RS2000 Smoke Profile

This fork is intended to become Piotr's private, Tailnet-only MiroFish variant:
cloud LLM inference, local graph storage, and no paid Zep dependency.

## Decisions

- Repository name: `pdurlej/mirofish-online`.
- Runtime target: RS2000.
- Exposure: `mirofish.pdurlej.com` behind Tailnet/Traefik allowlist only.
- LLM: Ollama Cloud / ProCloud through the OpenAI-compatible API.
- First model: `qwen3.5:cloud`; `qwen3.5:397b-cloud` is a later quality/cost comparison.
- Graph store: Neo4j Community for the first smoke, with memory limits.
- Embeddings: local lightweight Ollama sidecar for `nomic-embed-text`, because the current code calls Ollama `/api/embed` directly.
- Backups: no initial backup for uploads/graph state until product value is proven.

## Non-goals

- No public exposure of Neo4j Browser/Bolt, backend API, or UI.
- No local large LLM on RS2000.
- No Postgres graph-storage adapter until the smoke proves product value.
- No platform canonical module until the standalone smoke is useful.

## Local checkout

```bash
git clone https://github.com/pdurlej/mirofish-online.git /Users/pd/Developer/mirofish-online
cd /Users/pd/Developer/mirofish-online
```

## RS2000 smoke env

Render `.env` from Infisical or create a local throwaway file from:

```bash
cp deploy/rs2000/.env.example .env
```

Never commit `.env`.

Required secret-backed values:

- `LLM_API_KEY`
- `OPENAI_API_KEY` with the same value as `LLM_API_KEY`
- `NEO4J_PASSWORD`
- `SECRET_KEY`

## Start smoke stack

```bash
docker compose -f deploy/rs2000/docker-compose.cloud-smoke.yml up -d neo4j embedding-ollama
docker exec mirofish-online-embedding-ollama ollama pull nomic-embed-text
docker compose -f deploy/rs2000/docker-compose.cloud-smoke.yml up -d --build mirofish
```

The smoke compose binds host ports to `127.0.0.1` only:

- UI: `127.0.0.1:13000`
- backend API: `127.0.0.1:15001`
- Neo4j Browser: `127.0.0.1:17474`
- Neo4j Bolt: `127.0.0.1:17687`
- embedding Ollama: `127.0.0.1:11435`

## Health checks

```bash
curl -fsS http://127.0.0.1:15001/health
curl -fsS http://127.0.0.1:13000/
docker ps --filter name=mirofish-online --format 'table {{.Names}}\t{{.Status}}'
```

## Platform integration gate

Only after a useful smoke result, add the canonical `platform` repo trace:

- `modules/mirofish-online/module.yaml`
- `modules/mirofish-online/runbook.md`
- `compose/apps/compose.yaml` service slice or a documented external-compose module
- `docs/infisical/key-map.md` entry for `/home-platform/apps/mirofish-online`
- `state/reports/mirofish-online-smoke-YYYY-MM-DD.md`

Keep the first module lifecycle as `experiment`, not `active`.

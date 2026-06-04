# MiroFish Online RS2000 Technical Smoke Receipt

## Scope

- Date: 2026-06-04
- Commit: `ec6a278`
- Environment: private RS2000 / Tailnet-allowlisted Traefik route
- Operator-visible URL: `https://mirofish.pdurlej.com/`
- Model configured: `qwen3.5:cloud`
- Max rounds configured: `8`

## Technical Result

- UI health: pass, `http://127.0.0.1:13000/` returned `200` on RS2000.
- Backend health: pass, `http://127.0.0.1:15001/health` returned `200` on RS2000.
- Compose status: pass; `mirofish`, `neo4j`, and `embedding-ollama` were running.
- Neo4j memory limit: pass; compose smoke gate verifies 2 GiB container limit, 1 GiB heap max, and 512 MiB page cache.
- Public exposure check: pass for safety; raw API, Neo4j Browser, Bolt, and embedding Ollama are host-local only.
- Tailnet route check: guarded; `mirofish.pdurlej.com` returned `403` from non-allowlisted public paths, proving the route is not openly public.
- Secrets/redaction check: pass; no tokens, `.env`, auth headers, or private values were committed or pasted.

## Operational Notes

- Runtime `.env` was rendered on RS2000 with the Ollama Cloud key from Infisical and local throwaway smoke secrets for Flask/Neo4j.
- Compose runtime commands must use `--env-file .env`; otherwise interpolation rejects the required `NEO4J_PASSWORD`.
- The first Docker build is heavy. CAMEL/torch pulled CUDA-sized dependencies, producing a large image/build-cache footprint. Optimize the Dockerfile or dependency set only if the product smoke shows value.
- Vite logs `spawn xdg-open ENOENT` because the dev server tries to open a browser inside the container. This did not block UI/API health.

## Product Result

- Topic: not run yet.
- Report generated: no.
- Runtime duration: technical smoke only.
- Approximate LLM cost: none from product run; only `/v1/models` key validation was performed.
- Most useful insight: technical launch path is viable, but operator access needs a Tailnet DNS/split-horizon path or SSH tunnel because public DNS plus `ts-allowlist` correctly blocks normal public-Wi-Fi source IPs.
- Most useless behavior: Docker image is much heavier than expected for a smoke due to inherited dependency choices.
- Decision changed: yes; next step should run the first product smoke, but do not weaken the allowlist to make browser access convenient.

## Decision

`continue`

## Notes

No secrets, raw `.env`, auth headers, private transcripts, or full generated reports are included in this receipt.

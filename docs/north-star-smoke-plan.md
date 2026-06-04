# MiroFish Online North Star Smoke Plan

## North Star

MiroFish Online should help Piotr test podcast, writing, product-management,
and strategy ideas before spending real operator time on them.

The product promise is not "run an agent swarm". The promise is:

> Given one real idea, MiroFish Online produces an overnight audience simulation
> report that changes Piotr's next decision: publish, rewrite, narrow, abandon,
> or ask a better question.

## Definition Of Done For The First Useful Smoke

The first useful smoke is complete when all of the following are true:

1. `mirofish.pdurlej.com` is reachable only from the Tailnet path.
2. The app runs on RS2000 with cloud LLM inference and local graph storage.
3. Neo4j and the embedding sidecar stay within explicit resource limits.
4. No Zep Cloud, paid subscription, public Neo4j, public backend API, or local
   heavyweight LLM is required.
5. One real Piotr topic is uploaded or entered.
6. A bounded simulation runs with low `OASIS_DEFAULT_MAX_ROUNDS`.
7. The run produces a report with at least one useful operator-facing insight.
8. The result is captured in a short smoke receipt: what was tested, what
   worked, what failed, approximate cost, and whether to continue.

Useful means the report affects a decision. A technically green run with a bland
report is not product success.

## Operating Principles

- Use existing open-source code before building custom systems.
- Avoid Zep Cloud lock-in and avoid recurring SaaS commitments until value is
  proven.
- Prefer cloud LLMs for heavy reasoning; RS2000 should not host large local
  models for this path.
- Keep the first stack private, disposable, and non-canonical until the product
  value is clear.
- Make the smoke observable enough that a later agent can continue without
  guessing what happened.
- Do not add backups for MiroFish data until the data is proven worth keeping.

## Stage 0 — Repository Preparation

Goal: make the fork understandable and safe to iterate.

Already established:

- GitHub fork: `pdurlej/mirofish-online`.
- Local checkout: `/Users/pd/Developer/mirofish-online`.
- Upstream fetch remote: `nikmcfly/MiroFish-Offline`.
- Upstream push disabled locally.
- Draft PR #1 carries the initial RS2000 smoke profile.

Exit criteria:

- README explains the fork's purpose.
- RS2000 smoke profile exists without secrets.
- Compose config renders without starting services.

## Stage 1 — Runtime Configuration Shape

Goal: separate the platform-specific runtime shape from upstream defaults.

Tasks:

1. Keep upstream `docker-compose.yml` intact as the generic baseline.
2. Use `deploy/rs2000/docker-compose.cloud-smoke.yml` for Piotr's smoke.
3. Keep `.env` out of git and render it from Infisical or local operator input.
4. Use Ollama Cloud / ProCloud for LLM calls:
   - primary smoke model: `qwen3.5:cloud`;
   - quality comparison candidate: `qwen3.5:397b-cloud`.
5. Keep local embedding through `nomic-embed-text` because current code calls
   Ollama `/api/embed` directly.
6. Bind host ports to `127.0.0.1` only.
7. Limit Neo4j memory:
   - heap initial: `512m`;
   - heap max: `1g`;
   - pagecache: `512m`;
   - container memory limit: `2g`.

Exit criteria:

- `docker compose --env-file deploy/rs2000/.env.example -f deploy/rs2000/docker-compose.cloud-smoke.yml config --quiet` passes.
- No secret values appear in git, logs, README, or PR bodies.

## Stage 2 — RS2000 Private Smoke Deployment

Goal: start the stack on RS2000 without public exposure.

Tasks:

1. Create or render the runtime `.env` on RS2000.
2. Pull the lightweight embedding model:
   `docker exec mirofish-online-embedding-ollama ollama pull nomic-embed-text`.
3. Start Neo4j and embedding Ollama.
4. Build and start `mirofish`.
5. Confirm backend `/health` and UI root respond on localhost.
6. Confirm no service is listening publicly except through approved Traefik
   routing.

Exit criteria:

- Containers are up and healthy enough for a manual UI run.
- Neo4j Browser/Bolt are not publicly reachable.
- Backend API is not publicly reachable.
- Any Tailnet route uses `ts-allowlist@file` or an equivalent private ingress
  control.

## Stage 3 — First Product Smoke

Goal: test one real idea, not the framework in the abstract.

Input format:

- One real topic from Piotr.
- A short audience hypothesis: who should care and what reaction matters.
- A decision question: what should Piotr decide after reading the report?

Recommended first run:

- `OASIS_DEFAULT_MAX_ROUNDS=5-10`.
- One simulation at a time.
- Prefer `qwen3.5:cloud` for the first run.
- Retry once with `qwen3.5:397b-cloud` only if the first report is structurally
  useful but too shallow.

Exit criteria:

- Upload/input succeeds.
- Simulation completes or fails with an actionable error.
- Report is generated or the failure is narrow enough to fix.
- Cost/time rough estimate is captured.

## Stage 4 — Smoke Receipt

Goal: decide whether this deserves more work.

Create `docs/smoke-receipts/YYYY-MM-DD-first-rs2000-smoke.md` after the first
run. Do not include private topic text if it should stay private; summarize.

Receipt template:

```markdown
# First RS2000 Smoke Receipt

## Input
- Topic summary:
- Audience hypothesis:
- Decision question:

## Runtime
- Model:
- Rounds:
- Approx duration:
- Approx token/cost note:

## Result
- Report generated: yes/no
- Most useful insight:
- Most wrong or useless behavior:
- Operator decision changed: yes/no

## Technical Findings
- UI:
- Backend:
- Neo4j:
- Embeddings:
- Privacy/exposure:

## Decision
- Continue / pause / abandon:
- Next smallest useful change:
```

Exit criteria:

- Receipt exists.
- Decision is explicit: continue, pause, or abandon.

## Stage 5 — Productization Gate

Only proceed if the first smoke changes Piotr's decision or clearly shows a
path to doing so.

Possible next paths:

1. **Keep Neo4j** if it works and operational cost is low.
2. **Add OpenRouter/OpenAI-compatible embedding adapter** if local embeddings
   are too weak or operationally annoying.
3. **Write `PostgresGraphStorage` spike** only if Neo4j becomes the actual pain.
4. **Create platform canonical module** only if the app becomes recurring value.

Platform module gate requires:

- `modules/mirofish-online/module.yaml` in `platform`.
- `modules/mirofish-online/runbook.md` in `platform`.
- Infisical key-map entry for `/home-platform/apps/mirofish-online`.
- Tailnet-only route documented.
- Basic smoke evidence captured.

## Risks And Stop Conditions

Stop or pause if any of these happen:

- The report is generic and does not change a decision.
- Cloud model cost is materially higher than expected for one useful run.
- Neo4j memory pressure harms RS2000.
- Tailnet-only exposure cannot be proven.
- The app requires broad upstream rewrites before one useful smoke.
- Any secret appears in logs, docs, PRs, screenshots, or fixtures.

## Delegation Notes

- Codex owns runtime shape, repo changes, smoke discipline, and final synthesis.
- Gemini 3.5 Flash can help with mechanical UI/API smoke scripts or small docs,
  but not architecture decisions.
- DeepSeek V4/GLM/Kimi can be used as advisory reviewers for the smoke receipt,
  especially if the first report is borderline useful.

## Immediate Next Tasks

1. Merge the RS2000 smoke-profile PR.
2. Prepare a runtime `.env` source from Infisical or operator-provided local
   values, without committing secrets.
3. Start the private smoke stack on RS2000.
4. Run one real topic through the UI.
5. Write the smoke receipt and decide whether to continue.

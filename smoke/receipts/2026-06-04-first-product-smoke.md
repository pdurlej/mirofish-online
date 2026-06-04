# First Product Smoke: MiroFish Online Investment Question

Date: 2026-06-04
Environment: private RS2000 smoke stack
Exposure: Tailnet/allowlist only; backend, Neo4j, Bolt, and embedding Ollama stayed host-local/private
Decision: pause

## Product Question

Should Piotr invest in MiroFish Online as a private audience-simulation tool for podcast, writing, product, and strategy ideas?

## Result

The smoke produced useful engineering evidence but did not produce a useful product report.

MiroFish Online is not ready for deeper product investment yet. The private stack can start, generate an ontology, build a minimal graph, prepare one persona, and run a bounded 5-round simulation. The value-carrying report stage failed on both the default cloud model and the one-time quality retry model.

## What Worked

- RS2000 private stack was reachable locally:
  - UI: `127.0.0.1:13000`
  - API health: `127.0.0.1:15001/health`
- Public exposure remained blocked by the platform Tailnet allowlist.
- Neo4j stayed bounded at 2 GiB and was not exposed publicly.
- Local embedding Ollama stayed private.
- Ollama Cloud auth was corrected in runtime:
  - `LLM_BASE_URL=https://ollama.com/v1`
  - default model restored to `qwen3.5:cloud` after the retry
- Ontology generation completed after PR #7:
  - 10 entity types
  - 10 edge types
- Graph build completed technically:
  - nodes: 1
  - edges: 0
- Simulation completed:
  - max rounds: 5
  - actions: 6

## What Failed

- `qwen3.5:cloud` produced repeated empty JSON responses during graph NER extraction.
- The graph was too thin for a meaningful audience simulation: one node and zero edges.
- Report generation failed at section generation with provider-side 500.
- A one-time retry on `qwen3.5:397b-cloud` failed at the same report stage.
- The run did not produce a product-quality report that should influence the investment decision.

## Product Read

This is a pause, not an abandon.

The concept still matches the need: private audience simulation for ideas before spending operator attention. The current stack, however, is not yet reliable enough to justify several days of product hardening. The weakest points are not RS2000 capacity or Neo4j. The weak points are model compatibility, JSON-mode reliability, and the report agent.

## Cost And Time

Provider usage was not measured by the smoke runner. No secret or provider usage payload was printed.

Observed operator-relevant cost:
- one full ontology/graph/simulation attempt on `qwen3.5:cloud`
- one report-only retry on `qwen3.5:397b-cloud`
- substantial wall-clock time spent in NER retries

## Private Runtime Artifacts

Raw private artifacts were left on RS2000 only and were not committed:

- `/tmp/mirofish-product-smoke/summary.json`
- `/tmp/mirofish-product-smoke/summary-397b.json`

No raw private report was committed.

## Recommendation

Pause productization until one narrow follow-up proves the report path can produce a useful artifact from a tiny fixture.

Suggested next implementation step:

1. Add a dedicated "tiny smoke mode" that bypasses the heavy graph/NER path or constrains it to a deterministic 3-5 entity fixture.
2. Add report-agent provider-error handling that returns a useful partial receipt instead of a failed task only.
3. Re-run the product question only after the tiny smoke can generate a report reliably.

Do not add backups, public exposure, or deeper RS2000 integration until a useful report exists.

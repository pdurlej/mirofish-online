# Live Audience E2E Smoke — 2026-06-04

This receipt records the first deployed live Audience Graph wave after moving
from fake contract runs to real model-backed 20-person runs.

## Result

- Status: passed
- Runtime: RS2000, private route / localhost API smoke
- Mode: live
- Run count: 3
- Elapsed: 200.82 seconds
- Raw topics stored in this receipt: no
- Pricing: unknown; token usage recorded

## Runs

| Title | Decision | Reactions | Similar Topics | Tokens | Failure Rate | Reliability |
|---|---:|---:|---:|---:|---:|---|
| AI harnesses for product managers | narrow | 19 | 3 | 14,841 | 0.05 | yellow |
| Private Audience Graph for Produkt w Praktyce | publish | 17 | 2 | 12,426 | 0.15 | yellow |
| Audience segment conflict as podcast material | narrow | 19 | 1 | 13,883 | 0.05 | yellow |

## Evidence

- `npm run check` passed before deploy.
- GitHub checks passed on PRs #15, #16, #17, and #18.
- RS2000 smoke check passed after deploy.
- Neo4j after smoke contained:
  - `AudienceRun`: 11
  - `AudienceReaction`: 213
  - `AudiencePersona`: 20
- History API returned recent runs with token, reliability, decision, and
  similarity metadata.

## Product Read

The system is usable enough to continue as a private audience graph, but it is
not yet green for fully unattended high-confidence product decisions.

Current recommendation: continue with the DeepSeek-backed live path, keep
broader model routing in measured triage, and improve reliability/cost reporting
before treating GLM/Kimi/Minimax as default persona models.

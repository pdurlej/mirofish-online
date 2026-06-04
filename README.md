# MiroFish Online

MiroFish Online is Piotr Durlej's private synthetic-audience graph for content
and product thinking. It is a fork of
[`nikmcfly/MiroFish-Offline`](https://github.com/nikmcfly/MiroFish-Offline),
but the current product direction is narrower and more practical:

> Test podcast, LinkedIn, blog, Twitter/X, and product ideas against a stable
> 20-person synthetic audience, then remember the reactions as a private graph.

The goal is not to be a generic chatbot or a heavy OASIS-first simulator. The
goal is to change Piotr's next action: publish, rewrite, narrow, abandon, turn
into a podcast, turn into a post, or save for later.

## Current Direction

- **Private Audience Graph** for Piotr's public audience and product ideas.
- **20 canonical synthetic personas** with stable identities and segments.
- **Neo4j graph memory** for topics, reactions, objections, recommendations,
  and similarity between previous ideas.
- **Cloud model ensemble** through an OpenAI-compatible endpoint, with local
  graph storage. This is not advertised as free or fully offline.
- **Tailnet-first deployment** on RS2000 at `mirofish.pdurlej.com`.

This is an optimum for a solo operator without a very strong local GPU: private
graph and UI locally, model inference through cloud APIs, and explicit cost /
reliability receipts per run.

## What Works Now

- Private `/audience` UI flow.
- Fake contract run for testing graph writes without spending model budget.
- Live audience run path with 20 personas, model attribution, token usage,
  reliability metadata, and Neo4j persistence.
- History of previous topic runs and similarity edges.
- RS2000 smoke checks for private deployment shape.

## What Is Deferred

- OASIS/CAMEL full simulation.
- Zep Cloud.
- Public multi-user SaaS exposure.
- Backup commitment for MiroFish graph data.
- Postgres adapter.

OASIS remains a future North Star for cases where the argument between audience
segments is itself useful, for example as a podcast format. It is not the core
runtime path for this phase.

## Local Checks

```bash
npm run check
```

Useful focused checks:

```bash
cd backend && uv run pytest
python3 scripts/model_inventory.py --json
python3 scripts/rs2000_smoke_check.py
```

## Deployment Shape

The RS2000 deployment keeps externally risky services private:

- UI exposed through the existing private route.
- Backend API same-origin through the UI path.
- Neo4j HTTP/Bolt bound locally/private only.
- Embedding Ollama sidecar is local/private.
- Cloud LLM keys stay in runtime secrets, never in repo artifacts.

## North Star

See [`docs/north-star.md`](docs/north-star.md) for the canonical product
direction.

## Upstream Heritage

This fork inherits ideas and code from MiroFish / MiroFish-Offline:

- multi-agent simulation concepts;
- Neo4j graph memory direction;
- OASIS/CAMEL simulation lineage;
- AGPL-3.0 license.

The public upstream is broader. This fork is intentionally narrower: Piotr's
private audience graph first, full simulation later only if it proves its value.

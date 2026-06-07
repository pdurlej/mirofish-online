# MiroFish Online

**Private Audience Graph for content and product thinking.**

MiroFish Online is Piotr Durlej's operator tool for testing podcast, LinkedIn,
blog, Twitter/X, and product ideas against a stable synthetic audience. Each run
collects structured reactions, objections, channel fit, cost metadata, and a
recommended next action, then stores the result in a Neo4j graph so later ideas
can be compared against earlier ones.

The product question is deliberately simple:

> Did this change the next move: publish, rewrite, narrow, abandon, record a
> podcast, write a post, or save the idea for later?

MiroFish is not a generic chatbot and not an OASIS-first simulation lab. The
current core is a practical private audience graph with memory.

## Current Product Surface

- `/audience` runs a topic through a 20-person synthetic audience and returns a
  decision-oriented report.
- `/audience/graph` renders the global topic graph: clusters, semantic-similarity
  edges, channel filters, search, and run drill-down.
- Run receipts expose model attribution, token usage, latency, failures,
  low-quality response counts, and reliability grade.
- Topic history shows overlap with earlier ideas so repeated themes become
  visible instead of disappearing into one-off model output.

## Why It Exists

Piotr repeatedly tests ideas for a similar audience. A single critique can be
useful, but the compounding value is memory:

- which topics keep returning;
- which audience segments care;
- which personas object;
- which channel fits best;
- which ideas are too broad, too early, or too similar to previous work.

The audience graph is meant to make product and content decisions faster,
sharper, and less dependent on guessing in isolation.

## Architecture

| Layer | Current implementation |
| --- | --- |
| Frontend | Vue 3 + Vite + Vue Router |
| Graph UI | D3 force graph |
| API | Flask backend |
| Graph memory | Neo4j |
| Embeddings | Local Ollama embedding service |
| LLM runtime | OpenAI-compatible cloud endpoint |
| Deployment | RS2000 app-only Docker Compose profile |

The useful split is: private graph memory and operator UI on Piotr's
infrastructure, cloud LLM inference when the run needs stronger models, and
explicit receipts so quality and cost are visible.

## What Works Now

- 20 stable synthetic personas for Piotr's audience.
- Fake contract runs for testing graph writes without spending model budget.
- Live audience runs with model attribution, structured responses, token usage,
  and reliability metadata.
- Semantic and lexical similarity between topics.
- Topic clusters and branch membership.
- Reviewer memory for related topics.
- Global D3 graph view for inspecting the topic map.
- RS2000 smoke checks for private deployment shape.

## Local Development

Install dependencies:

```bash
npm run setup:all
```

Run the app locally:

```bash
npm run dev
```

Run the full quality gate:

```bash
npm run check
```

Useful focused checks:

```bash
cd backend && uv run pytest tests/test_audience_graph.py tests/test_audience_api.py
npm run build --prefix frontend
python3 scripts/rs2000_smoke_check.py
```

## Deployment Shape

The production profile is intentionally narrow:

- UI and API are deployed as the `mirofish` app service.
- Neo4j, backend internals, embedding service, and provider credentials are not
  exposed as public services.
- Cloud LLM keys stay in runtime secrets and are never committed to repo
  artifacts.
- The RS2000 smoke profile checks that the app shape stays private and bounded.

App-only deploys use the RS2000 Docker Compose profile under `deploy/rs2000/`.
No destructive data operation or infrastructure change is required for ordinary
frontend/backend releases.

## Non-Goals For This Phase

- Public multi-user SaaS.
- Generic market research automation.
- OASIS/CAMEL as the default runtime path.
- Raw prompt or provider-output storage in UI receipts.
- A backup commitment before the graph proves repeated value.
- A Postgres adapter.

OASIS-style full simulation remains a future lane for cases where the argument
between audience segments is itself useful. It is not the core product path
right now.

## Product North Star

See [`docs/north-star.md`](docs/north-star.md) for the canonical product
direction and success criteria.

## Upstream Heritage

This repository is a focused fork of
[`nikmcfly/MiroFish-Offline`](https://github.com/nikmcfly/MiroFish-Offline).
It keeps the AGPL-3.0 license and inherits parts of the original graph-memory
and simulation direction, but the active product is narrower:

> Piotr's private audience graph first; broad simulation lab later only if it
> proves decision-making value.

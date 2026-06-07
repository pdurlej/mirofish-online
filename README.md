# MiroFish Online

**Synthetic audience graph for content, product, and startup idea validation.**

MiroFish Online helps creators, product teams, founders, and independent
operators test ideas against a reusable synthetic audience. Each run collects
structured reactions, objections, channel fit, cost metadata, and a recommended
next action, then stores the result in a Neo4j graph so future ideas can be
compared against earlier ones.

The product question is deliberately simple:

> Did this change the next move: publish, rewrite, narrow, abandon, record,
> ship, research further, or save the idea for later?

MiroFish is not a generic chatbot and not an OASIS-first simulation lab. The
current core is a practical audience-memory system: stable personas, structured
receipts, topic similarity, clusters, and a global idea graph.

## Who It Is For

- Content creators who want to pressure-test podcast, newsletter, blog,
  YouTube, LinkedIn, or X/Twitter ideas before publishing.
- Product managers and product leaders who want fast audience critique before
  committing to a framing, discovery question, or roadmap narrative.
- Founders and startup teams who want a repeatable way to compare positioning,
  market, pricing, feature, and go-to-market ideas.
- Solo operators who want a self-hosted decision-support tool rather than another
  one-off chat transcript.

## Current Product Surface

- `/audience` runs a topic through a stable synthetic audience and returns a
  decision-oriented report.
- `/audience/graph` renders the global topic graph: clusters, semantic-similarity
  edges, channel filters, search, and run drill-down.
- Run receipts expose model attribution, token usage, latency, failures,
  low-quality response counts, and reliability grade.
- Topic history shows overlap with earlier ideas so repeated themes become
  visible instead of disappearing into one-off model output.

## Why It Exists

People repeatedly test ideas for similar audiences. A single critique can be
useful, but the compounding value is memory:

- which topics keep returning;
- which audience segments care;
- which personas object;
- which channel or use case fits best;
- which ideas are too broad, too early, too generic, or too similar to previous
  work.

The audience graph is meant to make content, product, and business decisions
faster, sharper, and less dependent on guessing in isolation.

## Architecture

| Layer | Current implementation |
| --- | --- |
| Frontend | Vue 3 + Vite + Vue Router |
| Graph UI | D3 force graph |
| API | Flask backend |
| Graph memory | Neo4j |
| Embeddings | Local Ollama embedding service |
| LLM runtime | OpenAI-compatible provider |
| Deployment | Docker Compose-capable host |

The useful split is: local graph memory and product UI, cloud or self-hosted LLM
inference depending on the operator's setup, and explicit receipts so quality
and cost are visible.

## What Works Now

- Stable synthetic personas for audience testing.
- Fake contract runs for testing graph writes without spending model budget.
- Live audience runs with model attribution, structured responses, token usage,
  and reliability metadata.
- Semantic and lexical similarity between topics.
- Topic clusters and branch membership.
- Reviewer memory for related topics.
- Global D3 graph view for inspecting the topic map.
- Docker Compose smoke checks for a self-hosted deployment shape.

## Infrastructure Requirements

MiroFish is designed for a small self-hosted deployment, not a large SaaS platform.
A practical setup needs:

- Node.js 18+ for frontend tooling;
- Python 3.11+ with `uv` for the backend;
- Neo4j for graph memory;
- an embedding service, currently local Ollama embeddings;
- an OpenAI-compatible LLM endpoint for live audience runs;
- Docker Compose for the deployment profile.

Any VPS, home server, or cloud VM that can run Docker Compose,
Neo4j, and the backend/frontend app can work. The repository includes one
Docker Compose deployment profile, but that profile is an example, not a product
requirement.

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
npm run check:smoke
```

## Deployment Shape

The recommended production shape is intentionally narrow:

- UI and API are deployed as the application service.
- Neo4j, backend internals, embedding service, and provider credentials should
  not be exposed as public services.
- LLM provider keys should stay in runtime secrets and never be committed to repo
  artifacts.
- Smoke checks should verify that the app is reachable while graph storage and
  model internals remain private.

Ordinary frontend/backend releases should not require destructive graph
operations, credential changes, or network-boundary changes.

## Non-Goals For This Phase

- Public multi-user SaaS.
- Generic market research automation.
- OASIS/CAMEL as the default runtime path.
- Raw prompt or provider-output storage in UI receipts.
- A backup commitment before the graph proves repeated value in a given
  deployment.
- A Postgres adapter.

OASIS-style full simulation remains a future lane for cases where the argument
between audience segments is itself useful. It is not the core product path
right now.

## Product North Star

See [`docs/north-star.md`](docs/north-star.md) for the product direction and
success criteria.

## Upstream Heritage

This repository is a focused fork of
[`nikmcfly/MiroFish-Offline`](https://github.com/nikmcfly/MiroFish-Offline).
It keeps the AGPL-3.0 license and inherits parts of the original graph-memory
and simulation direction, but the active product is narrower:

> Audience graph first; broad simulation lab later only if it proves
> decision-making value.

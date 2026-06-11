# MiroFish Online

MiroFish Online is a synthetic audience graph for testing content, product, and
market ideas before committing to a bigger bet. It helps creators, product
teams, founders, and operators ask a stable set of LLM-backed personas:

> Is this idea worth publishing, rewriting, narrowing, saving for later, or
> dropping?

Each run collects structured reactions, objections, channel fit, decision
recommendations, cost/reliability metadata, and similarity links to previous
topics. The result is stored in Neo4j and visualized as an audience memory graph
so repeated ideas can form branches instead of disappearing into one-off chats.

## Who It Is For

- Content creators validating podcast, newsletter, blog, LinkedIn, or X/Twitter
  ideas.
- Product managers and product teams testing strategy, discovery, pricing,
  AI-feature, and go-to-market topics.
- Founders and startup operators looking for structured pushback before writing,
  building, or pitching.
- Solo operators who want repeatable synthetic feedback without turning every
  question into a bespoke prompt-engineering session.

## What It Does

- Runs ideas against a stable synthetic audience with persona-level attribution.
- Produces reactions, objections, insights, channel scores, and a recommended
  next action.
- Stores topics, reactions, objections, recommendations, clusters, and
  similarity edges in Neo4j.
- Shows a global D3 audience graph for clusters, related topics, and emerging
  branches.
- Tracks model usage, reliability, low-quality responses, retries, and fallback
  behavior in a sanitized receipt.
- Supports cloud LLM inference through an OpenAI-compatible API and local graph
  storage.

## Current Product Lane

MiroFish Online is intentionally narrower than a full social simulation engine.
The primary workflow is:

1. Submit a topic, draft, or product question.
2. Get structured feedback from a synthetic audience.
3. See how this topic connects to earlier runs.
4. Decide the next move: publish, rewrite, narrow, abandon, turn into a longer
   format, or save for later.

Full OASIS/CAMEL-style simulation remains a future lane. The current focus is a
reliable audience graph and useful reports.

## Architecture

- **Frontend:** Vue + Vite, with D3 for the global audience graph.
- **Backend:** Flask API.
- **Graph storage:** Neo4j.
- **Embeddings:** local lightweight embedding service for topic similarity.
- **LLM calls:** OpenAI-compatible provider endpoint, configurable by runtime
  environment.
- **Deployment:** Docker Compose profile with host-local/private service
  bindings by default.

Privacy depends on how you deploy the app and which model provider you use.
The graph can remain local/private, while LLM inference may still leave your
environment if configured for a cloud provider.

## What Works Now

- Audience run API and UI.
- Fake run path for contract testing without model spend.
- Live LLM-backed audience run path.
- Neo4j persistence for topics, personas, reactions, objections,
  recommendations, similarity edges, and clusters.
- History view with similar-topic summaries.
- Global audience graph view at `/audience/graph`.
- Channel-fit scoring and next-action recommendations.
- Sanitized model receipts with reliability, retry, and token/cost metadata.
- Synthetic research snapshot importer for controlled large-batch experiments.

## Local Checks

```bash
npm run check
```

Useful focused checks:

```bash
cd backend && uv run pytest
python3 scripts/model_inventory.py --json
```

The repository includes a Docker Compose smoke profile for a private host. Treat
it as an example and adapt hostnames, networks, secrets, and routing to your own
environment.

## Deployment Notes

A typical private deployment keeps risky services off the public internet:

- The UI is exposed through your chosen private or authenticated route.
- Backend API calls are same-origin through the UI path.
- Neo4j HTTP/Bolt stay bound to local/private interfaces.
- Embedding services stay local/private.
- Provider keys stay in runtime secrets, never in repo artifacts.

Do not expose Neo4j, provider credentials, or internal model endpoints publicly.

## Upstream Heritage

This project inherits ideas and code from MiroFish / MiroFish-Offline, including
multi-agent simulation concepts, graph memory direction, Neo4j storage, and
OASIS/CAMEL simulation lineage. This fork focuses first on synthetic audience
research and a practical topic-memory graph.

## License

AGPL-3.0.

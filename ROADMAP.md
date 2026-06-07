# MiroFish Online Roadmap

MiroFish Online is currently optimized for one repeatable workflow:

> Test an idea against a stable synthetic audience, remember the result in a
> graph, and use that memory to decide the next move.

This roadmap is intentionally narrower than the upstream MiroFish-Offline
roadmap. Full simulation remains interesting, but the active product path is the
synthetic audience graph.

## Current State

- `/audience` live and fake audience runs.
- 20 stable audience personas.
- Structured reactions, objections, insights, recommendation, and receipts.
- Token usage, model attribution, latency, failure, and reliability metadata.
- Neo4j persistence for runs, topics, personas, reactions, objections, insights,
  recommendations, similarity edges, and topic clusters.
- Hybrid lexical/semantic similarity between topics.
- Reviewer memory across related topics.
- `/audience/graph` global graph view with clusters, filters, search, and run
  drill-down.
- Docker Compose deployment profile and smoke checks.

## Near Term

### Graph Usefulness

- [ ] Improve global graph visual hierarchy for dense production data.
- [ ] Highlight selected node neighborhoods and dim unrelated branches.
- [ ] Add useful hover previews for topics and edges.
- [ ] Improve cluster labels and branch naming.
- [ ] Add "why connected" explanations for the strongest similarity edges.

### Audience Quality

- [ ] Detect repeated or overly generic objections across personas.
- [ ] Mark mass repetition as lower reliability, even when schema validation
      passes.
- [ ] Tune Polish prompts for Polish product/content topics.
- [ ] Add deliberate high-quality retry for low-quality persona responses.
- [ ] Keep retry cost visible in receipts.

### Operator Workflow

- [ ] Make next-action recommendations more concrete for podcast vs LinkedIn vs
      blog vs product-research use.
- [ ] Add a compact "what changed my mind" section to run reports.
- [ ] Improve history navigation between graph, run detail, and related topics.
- [ ] Add saved-for-later / revisit markers for topics.

## Mid Term

### Graph Memory

- [ ] Track topic branches over time, not just pairwise similarity.
- [ ] Show overlap with previous AI, product discovery, pricing, and governance
      themes.
- [ ] Let the graph explain when a new idea is fresh, derivative, or a better
      angle on an older topic.
- [ ] Add non-destructive export of sanitized graph snapshots.

### Model Reliability

- [ ] Compare DeepSeek Flash, DeepSeek Pro, GLM, Kimi, Minimax, and Qwen on
      concrete usefulness, not only schema compliance.
- [ ] Add per-model quality summaries across runs.
- [ ] Add red-team reruns for high-stakes or ambiguous topics.

## Deferred

- Public multi-user SaaS.
- Generic market research platform.
- Postgres adapter.
- Backup commitment before repeated value is proven.
- OASIS/CAMEL as the primary runtime path.
- Full transcript storage for prompts or provider outputs.

## Long-Term Bet

MiroFish should become a reusable thinking map for content, product, and startup
work: a place where repeated topic tests build memory, show branches, reveal
audience fatigue, and make the next move clearer.

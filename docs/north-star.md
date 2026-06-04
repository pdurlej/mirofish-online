# MiroFish Online North Star

MiroFish Online is Piotr Durlej's private audience graph for content and
product thinking.

The product should help Piotr decide what to do next with ideas for Produkt w
Praktyce, LinkedIn, blog posts, Twitter/X threads, and product experiments.
It is not a generic chatbot. It is not an OASIS-first simulation lab. It is a
private synthetic audience with memory.

## Product Bet

Piotr repeatedly tests ideas against similar audiences. A one-shot critique is
useful, but repeated critiques become more valuable when they accumulate memory:

- which audience segments care;
- which personas object;
- which themes repeat;
- which angles are fresh;
- which topics overlap too much with earlier work;
- which channel fits the idea best.

The core product bet is that a durable graph of synthetic audience reactions can
make content and product decisions faster, sharper, and less dependent on the
operator guessing in isolation.

## Success Metric

The primary success metric is:

> How often did MiroFish change Piotr's next action?

Useful outcomes include:

- publish;
- rewrite;
- narrow;
- abandon;
- turn into a podcast;
- turn into a LinkedIn post;
- turn into a blog post;
- turn into a Twitter/X thread;
- save for later;
- ask a better question.

If MiroFish only produces plausible prose, it fails. If it changes the next
decision, it works.

## Amazing Outcomes

Examples of outcomes the product should eventually make routine:

- "This is a podcast, not a LinkedIn post."
- "This overlaps too much with your earlier AI agents topic; use this new angle
  instead."
- "Generalist PMs will not care about this framing, but AI platform PMs and
  enterprise governance PMs will."
- "The idea is good, but the audience needs a concrete operator story before the
  concept lands."
- "This is product research, not public content yet."
- "Do not publish this now; it needs a sharper conflict."

## First Audience

The first canonical audience is Piotr Durlej's public audience, with segment
filters for:

- Produkt w Praktyce;
- LinkedIn;
- blog readers;
- Twitter/X;
- product managers;
- AI/platform/devtools builders;
- solo operators;
- enterprise/governance buyers;
- skeptical generalists.

The first version should use 20 stable synthetic personas. Their reactions
should be stored as structured graph data, not as raw private prompt transcripts.

## Non-Goals

The first product version intentionally does not:

- expose the service publicly;
- back up MiroFish data before repeated value is proven;
- add a Postgres adapter;
- make OASIS/CAMEL the primary path;
- store raw private prompts, headers, API keys, or provider errors in receipts;
- try to be a generic market research platform.

## Operating Principle

Start with the smallest flow that proves repeated value:

1. Piotr submits a topic or rough draft.
2. MiroFish runs the canonical 20-person audience.
3. It records structured reactions in Neo4j.
4. It returns a channel recommendation, objections, overlap, and next action.
5. Later runs become better because the graph remembers previous topics.

When in doubt, optimize for one question:

> Did this make Piotr's next content or product decision better?

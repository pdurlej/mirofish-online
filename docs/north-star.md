# MiroFish Online North Star

MiroFish Online is a synthetic audience graph for content, product, and startup
idea validation.

The product should help creators, product teams, founders, and independent
operators decide what to do next with podcast, writing, social-content,
positioning, roadmap, pricing, and product-discovery ideas. It is not a generic
chatbot. It is not an OASIS-first simulation lab. It is an audience memory
system.

## Product Bet

People repeatedly test ideas against similar audiences. A one-shot critique is
useful, but repeated critiques become more valuable when they accumulate memory:

- which audience segments care;
- which personas object;
- which themes repeat;
- which angles are fresh;
- which topics overlap too much with earlier work;
- which channel fits the idea best.

The core product bet is that a durable graph of synthetic audience reactions can
make content, product, and business decisions faster, sharper, and less
dependent on guessing in isolation.

## Success Metric

The primary success metric is:

> How often did MiroFish change the next action?

Useful outcomes include:

- publish;
- rewrite;
- narrow;
- abandon;
- turn into a podcast;
- turn into a LinkedIn post;
- turn into a blog post;
- turn into a Twitter/X thread;
- turn into a product-discovery question;
- turn into a startup positioning test;
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

The first canonical audience is a product-and-content audience, with segment
filters for:

- podcast listeners;
- LinkedIn readers;
- blog/newsletter readers;
- Twitter/X readers;
- product managers;
- AI/platform/devtools builders;
- founders and solo operators;
- enterprise/governance buyers;
- skeptical generalists.

The first version should use 20 stable synthetic personas. Their reactions
should be stored as structured graph data, not as raw private prompt transcripts.

## Non-Goals

The first product version intentionally does not:

- operate as a public multi-user SaaS;
- require a backup commitment before repeated value is proven;
- add a Postgres adapter;
- make OASIS/CAMEL the primary path;
- store raw private prompts, headers, API keys, or provider errors in receipts;
- try to be a generic market research platform.

## Operating Principle

Start with the smallest flow that proves repeated value:

1. A user submits a topic or rough draft.
2. MiroFish runs the canonical 20-person audience.
3. It records structured reactions in Neo4j.
4. It returns a channel recommendation, objections, overlap, and next action.
5. Later runs become better because the graph remembers previous topics.

When in doubt, optimize for one question:

> Did this make the next content, product, or business decision better?

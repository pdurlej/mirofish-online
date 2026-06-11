# MiroFish Online North Star

MiroFish Online is a synthetic audience graph for testing content, product, and
market ideas against a stable set of LLM-backed personas.

The product should help an operator decide what to do next with an idea:

- publish;
- rewrite;
- narrow;
- abandon;
- turn into a longer format;
- save for later.

## Product Thesis

Most LLM feedback tools behave like one-off critics. They can produce useful
comments, but they do not remember how similar topics performed before, which
audience segments objected, or where a recurring branch of thinking is forming.

MiroFish should behave more like a reusable audience memory:

1. Run an idea against a stable synthetic audience.
2. Capture reactions, objections, channel fit, and recommended next action.
3. Store the run in a graph.
4. Compare future ideas against earlier topics.
5. Show clusters and branches that help an operator see what is emerging.

## Primary Users

- content creators;
- product managers;
- founders;
- startup operators;
- product teams;
- consultants or experts who publish thought leadership;
- solo operators validating ideas before spending time on them.

## Success Criteria

MiroFish is useful when it changes the next move. A report is successful if it
helps the operator confidently choose one of:

- publish as-is;
- rewrite around a stronger objection;
- narrow the target audience;
- change the channel;
- develop into a podcast/blog/product experiment;
- save for later;
- abandon.

## Current Product Lane

The current lane is not a full social simulator. It is a practical audience
graph:

- stable personas;
- structured reactions and objections;
- channel-fit scoring;
- reliability and cost receipts;
- topic similarity;
- clusters and branches;
- global graph visualization.

OASIS/CAMEL-style simulation remains a future lane for cases where interaction
between audience segments is itself the product insight.

## Quality Bar

Schema-valid output is not enough. A run should be treated as low quality if:

- many personas return generic objections;
- responses do not reference the actual topic;
- objections are repeated or interchangeable;
- reliability is green despite fallback/generic output;
- the recommendation does not change a realistic next action.

Useful output is specific, differentiated, and decision-oriented.

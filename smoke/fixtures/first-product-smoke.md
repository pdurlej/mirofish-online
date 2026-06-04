# First Product Smoke Input

## Question

Should Piotr invest in MiroFish Online as a private audience-simulation tool
for podcast, writing, product, and strategy ideas?

## Intended Use

Use this as the first bounded topic after the private RS2000 technical smoke is
green. The run should help decide whether MiroFish Online is worth developing
further, not whether every underlying implementation detail is already good.

## Constraints

- One run at a time.
- `OASIS_DEFAULT_MAX_ROUNDS=5-10`.
- Default model: `qwen3.5:cloud`.
- Optional single retry: `qwen3.5:397b-cloud` if the first report is
  structurally useful but too shallow.
- Do not include private transcripts, secrets, raw headers, or `.env` content
  in committed receipts.

## Decision The Report Must Support

- `continue`: useful enough to spend another implementation cycle.
- `pause`: technically works, but product value is unclear.
- `abandon`: not worth adapting before a better upstream/tool appears.

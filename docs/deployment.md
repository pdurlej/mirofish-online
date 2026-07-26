# Deployment Guide

MiroFish Online can use local or hosted model infrastructure. The correct deployment shape depends on your privacy requirements, hardware, and provider choices.

## Service Boundaries

The application expects four components:

1. the MiroFish web application and Flask API;
2. Neo4j 5 for audience memory;
3. an Ollama-compatible embedding endpoint;
4. an OpenAI-compatible chat endpoint.

The chat and embedding endpoints may be separate services. Keep Neo4j and internal model endpoints on private interfaces unless you have added an explicit authentication and network policy layer.

## Runtime Configuration

Copy `.env.example` to `.env` and configure:

- `LLM_API_KEY`, `LLM_BASE_URL`, and `LLM_MODEL_NAME`;
- `NEO4J_URI`, `NEO4J_USER`, and `NEO4J_PASSWORD`;
- `EMBEDDING_BASE_URL` and `EMBEDDING_MODEL`;
- `OPENAI_API_KEY` and `OPENAI_API_BASE_URL` only when the optional OASIS/CAMEL path is used.

Use your deployment platform's secret store for credentials. Do not bake `.env` into an image or commit it to source control.

## Compose

The repository includes a Compose smoke profile used to verify the application stack. Treat it as a reference:

- adjust CPU/GPU configuration to match the host;
- replace example credentials;
- review every published port;
- provide your own ingress and authentication policy;
- keep persistent Neo4j storage outside disposable application containers.

Render the checked-in profile before adapting it:

```bash
npm run check:compose
```

## Preflight

Before the first real audience run:

```bash
npm run check
```

Then verify:

- the health endpoint is reachable through the intended route;
- Neo4j and embedding endpoints are not unintentionally public;
- the configured chat provider matches your data-handling expectations;
- logs and receipts do not include credentials or raw provider errors;
- persistent graph data has an explicit retention and backup decision.

## Rollback

Application releases are designed to be rolled back by rebuilding the previous source revision. Graph evolution should remain additive and versioned; do not delete legacy relationships or Neo4j volumes as part of an application rollback.

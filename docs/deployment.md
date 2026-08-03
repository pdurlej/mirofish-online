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

- adjust CPU/GPU configuration to match the host — `docker-compose.yml` runs
  Ollama on CPU, and `docker-compose.gpu.yml` is an opt-in override that adds an
  NVIDIA device reservation (it requires the NVIDIA Container Toolkit);
- replace example credentials;
- review every published port;
- provide your own ingress and authentication policy;
- keep persistent Neo4j storage outside disposable application containers.

Render the checked-in profile before adapting it:

```bash
npm run check:compose
```

The production image uses a multi-stage build. Node and Vite compile the Vue
application in the build stage only; the final image serves the generated SPA
and API from one Gunicorn process. Local development remains split between the
Vite dev server on port 3000 and Flask on port 5001.

## RS2000 On-Demand Lifecycle

The dedicated RS2000 stack is operator-driven. It does not use an inactivity
timer and it never removes containers or volumes as part of normal lifecycle
management.

Check the count-only state:

```bash
npm run lifecycle:status
```

Start dependencies first, confirm the configured embedding model is already
present, then make the application ready:

```bash
npm run lifecycle:start
```

Drain new mutating requests, wait for all tracked work to become idle, then
stop the application, embedding Ollama, and Neo4j:

```bash
npm run lifecycle:stop
```

`stop` refuses to continue while audience runs, graph tasks, simulation
processes, monitors, graph-memory updaters, or API requests are active. There
is no force mode. If the idle wait expires, the script attempts a
readiness-gated resume before returning the refusal. The control endpoints
reject non-loopback callers and are invoked only through `docker compose exec`;
the repository does not add a new HTTP authentication scheme.

The lifecycle path observes state with `docker compose ps`, controls the
application through `exec`, and mutates service state only with `start` and
`stop`. A failed start rolls back only services that were not already running.
Provisioning and image replacement are separate rollout operations. Never use
`down -v` for lifecycle or rollback: `neo4j_data`, `neo4j_logs`, and
`embedding_ollama_data` are persistent recovery boundaries.

## Preflight

Before the first real audience run:

```bash
npm run check
```

Then verify:

- `/health/live` and `/health/ready` are reachable through the intended route;
- readiness fails closed when Neo4j or the configured Ollama model is absent;
- Neo4j and embedding endpoints are not unintentionally public;
- the configured chat provider matches your data-handling expectations;
- logs and receipts do not include credentials or raw provider errors;
- persistent graph data has an explicit retention and backup decision.

## Rollback

Application releases are designed to be rolled back by rebuilding the previous source revision. Graph evolution should remain additive and versioned; do not delete legacy relationships or Neo4j volumes as part of an application rollback.

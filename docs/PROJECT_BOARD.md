# WaveMind GitHub Project Board

Use this as the canonical GitHub Projects layout for public roadmap work.

## Views

1. **Roadmap**
   - Group by `area`.
   - Sort by `priority`, then milestone.
2. **Benchmarks**
   - Filter: `label:benchmark`.
   - Track dataset, baseline systems, metric, and current result.
3. **Production**
   - Filter: `label:production` or `label:observability`.
   - Track risk, rollout status, and documentation status.
4. **Integrations**
   - Filter: `label:integration`.
   - Track target framework, adapter status, example status, and tests.

## Fields

| Field | Type | Values |
|---|---|---|
| Status | Single select | Backlog, Ready, In progress, Review, Done |
| Area | Single select | Indexing, Observability, Benchmarks, Integration, Docs, Security |
| Priority | Single select | P0, P1, P2, P3 |
| Release | Text | v2.1, v2.2, v3.0 |
| Evidence | Text | Benchmark result, test path, or docs link |

## Starter Issues

Create these as public issues and add them to the board:

| Title | Labels | Priority |
|---|---|---|
| Add OpenTelemetry traces to FastAPI and core memory operations | production, observability | P0 |
| Persist FAISS index snapshots and validate reloads | indexing, faiss | P0 |
| Run service-mode Qdrant and pgvector benchmark profiles | benchmark, qdrant, pgvector | P1 |
| Promote LlamaIndex/CrewAI/AutoGen/LangGraph adapters from examples to package APIs | integration | P1 |
| Publish benchmark report thread for HN/Reddit/LocalLLaMA | benchmark, documentation | P2 |

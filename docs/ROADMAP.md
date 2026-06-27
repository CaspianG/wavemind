# WaveMind Roadmap

WaveMind is an early dynamic-memory engine. The current core is intentionally
local-first: SQLite for durable state, vector search for candidates, and a
wave-field layer for hotness, decay, TTL, priority, namespaces, and graph
dynamics.

This roadmap is the path from a useful local library to a memory layer that can
handle larger systems, attract contributors, and become credible in production.

## Current Position

Today WaveMind is strongest when the memory set is small to medium and memory
policy matters more than raw vector-database scale:

- SQLite is the source of truth for text, metadata, vectors, TTL, recall state,
  tags, and namespaces.
- NumPy exact search is reliable but linear.
- Annoy exists as an ANN option, but current recall still needs tuning.
- FAISS and pgvector are exposed as explicit optional candidate-index backends.
- Namespace sharding is available for local multi-tenant SQLite deployments.
- Dynamic policy already covers hot memory, stale suppression, corrections,
  TTL, and namespace isolation.
- SQLite audit events and a Prometheus-compatible `/metrics` endpoint now cover
  the first observability layer.
- API key roles and opt-in rate limiting are available for FastAPI deployments.
- Public retrieval evidence exists for LoCoMo, LongMemEval, and BEIR/SciFact,
  but full answer-quality evaluation is still the next proof step.

The short-term engineering target is simple: keep WaveMind's dynamic-memory
advantage while moving candidate search and filtering to production-grade
indexes.

## Technical Scaling

### 1. Candidate Indexing

Target architecture:

```text
SQLite / Postgres source of truth
        |
        v
ANN candidate index: FAISS, pgvector/HNSW, Qdrant service, or Annoy
        |
        v
WaveMind top-k memory re-ranker
        |
        v
small scoped recall set
```

Priorities:

- Add a FAISS-first index path for local and single-node production use.
- Keep SQLite as the durable local source of truth.
- Keep pgvector as an optional candidate-index backend and add a separate
  Postgres source-of-truth backend when multi-tenant storage needs it.
- Support external vector services such as Qdrant for larger deployments.
- Rebuild and persist ANN indexes safely after batch imports or recovery.
- Keep the wave-field layer as a top-k re-ranker, not a full-scan scorer.

### 2. Namespace And Tenant Scale

WaveMind should scale by isolating memory early:

- shard by namespace, tenant, user, project, or agent;
- use `ShardedWaveMind` for local namespace-level SQLite sharding;
- keep namespace filters inside candidate generation where possible;
- support per-namespace quotas and retention policy;
- expose migration tools for moving one namespace between databases;
- keep deletion and TTL behavior auditable.

Initial target: 100k to 1M memories on one node before horizontal clustering.

### 3. Performance

The next performance work is not just "make vector search faster." The dynamic
memory policy also needs to become cheaper:

- rerank only the top candidate window;
- cache hot namespaces and hot query patterns;
- batch recall feedback updates;
- run decay, graph edge updates, and consolidation in background jobs;
- compress or quantize embeddings where quality allows it;
- benchmark p50, p95, p99 latency separately for candidate search, reranking,
  SQLite writes, and feedback updates.

Potential infrastructure:

- Redis for hot-memory and query caches;
- Celery, RQ, Temporal, or a simple built-in worker for background tasks;
- OpenTelemetry spans for profiling production requests;
- expand Prometheus-compatible metrics for latency, recall feedback, TTL expiry,
  and index health.

### 4. Field And Graph Memory

The long-term research direction is to move from "vector search plus memory
state" toward a stronger field model:

- memory-to-memory excitation for related facts;
- inhibition for newer facts that correct or conflict with stale facts;
- decay curves that can be measured and tuned;
- consolidation that can form higher-level memory nodes;
- graph export/import and inspection tools;
- optional integrations with graph databases for enterprise knowledge graphs.

The current `MemoryFieldGraph` is a discrete memory graph, not a continuous
mathematical field. The goal is to make its behavior more explicit, testable,
and useful before making larger claims.

## Benchmark And Proof Roadmap

WaveMind should be evaluated on several different benchmark classes. They prove
different things and should not be mixed together.

| benchmark class | Examples | What it proves |
|---|---|---|
| Agent memory | LoCoMo, LongMemEval, LongMemEval-V2, LMEB | Long-horizon recall, updates, temporal consistency, evidence retrieval. |
| RAG answer quality | RAGBench, HotpotQA, Natural Questions | Whether retrieved memory improves final answers. |
| Retrieval quality | BEIR, MTEB Retrieval, MIRACL | Whether WaveMind preserves same-embedding retrieval quality. |
| Vector index scale | ANN-Benchmarks, VectorDBBench-style curves | Recall/latency/throughput at large vector counts. |
| Product regressions | Dynamic memory, TTL, correction, stale suppression | Whether the core memory-policy value stays intact. |

Near-term benchmark priorities:

- Finish LoCoMo and LongMemEval answer generation, not retrieval only.
- Compare against static vector retrieval, Chroma, Qdrant, Mem0-style memory,
  Zep-style memory, and LangGraph persistent memory patterns where possible.
- Add service-mode Qdrant and FAISS baselines for fair latency curves.
- Add MIRACL Russian to prove multilingual retrieval behavior.
- Add RAGBench once answer generation and citation/fidelity metrics are stable.
- Keep every published result backed by a checked-in JSON artifact and a command
  that can reproduce it.

## Community Roadmap

The community will grow if the project is easy to understand, easy to run, and
easy to improve.

Priorities:

- examples gallery for LangChain, LangGraph, CrewAI, AutoGen, OpenClaw,
  LlamaIndex, namespace sharding, custom Python loops, and HTTP-only use;
- clear `good first issue` and `help wanted` labels;
- GitHub Discussions for support and design proposals;
- benchmark scripts that contributors can run locally;
- Docker images for the API server and sidecar mode;
- release automation and release checklist;
- support and security policy docs;
- Helm chart for Kubernetes deployments after the server path is stable;
- short technical posts explaining stale memory, corrections, namespaces,
  dynamic priority, and benchmark methodology.

Community-facing rule: do not claim a win unless the benchmark is reproducible
from the repository.

## Enterprise Direction

The strongest enterprise positioning is not "another vector database." It is:

> WaveMind is the memory-behavior layer above retrieval. It decides what should
> still matter, what should fade, what should be isolated, and what should be
> forgotten.

Promising production use cases:

- enterprise agent platforms;
- customer support and CRM memory;
- developer agents with project and decision memory;
- research assistants with source-aware memory;
- trading and market-research agents after proper backtesting;
- legal, healthcare, and compliance-heavy workflows after provenance and
  access-control hardening.

Enterprise requirements:

- authentication and authorization;
- role-based access control;
- encryption at rest and in transit;
- audit logs for remember, query, recall feedback, and forget;
- backup, restore, and point-in-time recovery;
- data residency controls;
- SSO/OAuth integration;
- SLOs for latency, throughput, and durability;
- monitoring, alerting, and tracing;
- migration tools between SQLite, Postgres, and external vector backends.

## Milestones

### Short Term: 1 To 3 Months

- FAISS candidate index with persisted rebuilds.
- Postgres source-of-truth prototype on top of the initial pgvector candidate
  index.
- LoCoMo and LongMemEval answer-quality runs with a local or configured LLM.
- Service-mode Qdrant latency baseline.
- Better README examples for non-agent use cases.
- Integration examples for LangGraph, LlamaIndex, CrewAI, and AutoGen.

### Medium Term: 3 To 6 Months

- Graph memory v2 with incremental edge updates.
- Background worker for decay, consolidation, graph updates, and backups.
- Docker image and Helm chart for API/sidecar deployment.
- Observability: Prometheus metrics and OpenTelemetry tracing.
- Multi-encoder support: local sentence-transformers, OpenAI-compatible APIs,
  and application-provided embeddings.
- Community benchmark dashboard generated from checked-in result JSON.

### Longer Term

- Horizontal namespace sharding.
- Clustered deployment mode.
- Enterprise auth, RBAC, audit log, and encryption.
- Hosted managed service.
- Multi-modal memory for images, audio, and structured events.
- Production-grade graph/field memory with measurable excitation,
  inhibition, decay, and consolidation behavior.

## Non-Goals For Now

- Do not position WaveMind as a full replacement for Pinecone, Weaviate,
  Qdrant, Milvus, or Chroma on static large-scale RAG.
- Do not claim leaderboard results without official datasets, reproducible
  commands, and checked-in result artifacts.
- Do not hide latency limits. Dynamic memory must earn its cost by improving
  recall quality, stale suppression, correction handling, or context size.

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
- PostgreSQL is available as an explicit source-of-truth backend for
  multi-tenant deployments that need managed database operations.
- NumPy exact search is reliable but linear.
- Quantized int8 search is available as an explicit compression experiment, but
  the current kernel is not yet a latency win over NumPy exact search.
- Annoy exists as an ANN option, but current recall still needs tuning.
- FAISS, pgvector, and Qdrant are exposed as explicit optional
  candidate-index backends.
- FAISS can persist a validated index snapshot and id map for single-node
  deployments where startup rebuild time matters.
- A Docker-backed production index profile now compares persisted FAISS,
  service-mode Qdrant, and PostgreSQL/pgvector on the same generated vectors.
- A service-backed production load profile now includes tuned 100000-vector and
  1M-vector Qdrant runs. Qdrant reaches `recall@10 1.000`, p99 `21.26 ms` at
  100k, and tuned 1M recall reaches `0.984`; the remaining blocker is stable
  sub-100 ms p99 at 1M.
- pgvector now exposes HNSW `m`, `ef_construction`, and `ef_search` controls.
  The checked-in profile uses `ef_search=400`, which improves 50000-vector
  recall but still misses the production recall target.
- Candidate indexes expose health snapshots, count/id drift checks, HTTP/CLI
  rebuild operations, and Prometheus-compatible index-health metrics.
- `wavemind scale-plan`, `WaveMind.scale_plan()`, and `GET /scale-plan` are
  available as deployment guardrails: they map current and target memory counts
  to a scale tier, status, recommended index, warnings, and concrete actions.
- Namespace sharding is available for local multi-tenant SQLite deployments.
- Deterministic cluster placement planning is available through
  `build_cluster_plan()` and `wavemind cluster-plan`, including replica sets,
  node/zone-loss simulation, read/write quorum reporting, and a Kubernetes
  StatefulSet manifest skeleton.
- `HotMemoryCache`, `query_with_cache()`, `CachePrewarmWorker`, and
  `MemoryMaintenanceWorker` provide the first worker/cache primitives for hot
  namespaces, query-audit-driven cache prewarm, TTL purge, field
  consolidation, concept consolidation, and index-health repair loops.
- Structured payload helpers cover image captions, audio transcripts, tables,
  and events while preserving modality metadata in the same memory API.
- `benchmarks/scale_readiness_benchmark.py` now checks 1M-memory simulated
  namespace placement, quorum-replicated runtime behavior, active-active
  namespace delta sync, service-mode distributed namespace sharding with
  primary-loss recall, checksummed replicated snapshot/restore with offsite and
  portable-archive verification, S3-compatible object-store upload,
  latest-archive metadata, remote download, retention verification, and a
  deterministic object-store disaster-recovery drill, query-audit cache
  prewarm, hot-cache behavior, and structured-payload retrieval.
- Dynamic policy already covers hot memory, stale suppression, corrections,
  TTL, and namespace isolation.
- Field self-consolidation is available through `WaveMind.consolidate_concepts()`,
  `wavemind consolidate`, and `POST /consolidate`: active graph clusters can
  become durable concept memories with source-memory provenance.
- SQLite audit events, a Prometheus-compatible `/metrics` endpoint,
  process-local API latency/failure metrics, optional OpenTelemetry traces, and
  local Prometheus/OTEL Collector alert examples now cover the first
  observability layer.
- API key roles and opt-in rate limiting are available for FastAPI deployments.
- SQLite backup, timestamped retention, restore, admin-only HTTP backup,
  replicated snapshot/restore, offsite-mirrored snapshot jobs, and verified
  `.tar.gz` snapshot archives with S3-compatible upload, latest-archive lookup,
  restore-from-latest support, remote download verification, object-store
  disaster-recovery drills, and object-store retention are available as the
  first durability layer.
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
- Keep pgvector as an optional candidate-index backend and harden the separate
  Postgres source-of-truth backend for multi-tenant storage.
- Support external vector services such as Qdrant for larger deployments.
  The 100k service-mode Qdrant benchmark is checked in and healthy; the 1M
  service-mode run is checked in but not production-grade yet because default
  recall is too low.
- Rebuild and persist ANN indexes safely after batch imports or recovery. The
  first persisted FAISS snapshot path and production profile are implemented;
  production still needs Linux/container FAISS at 100k/1M and deeper latency
  traces.
- Tune the quantized int8 path so lower memory footprint does not increase query
  latency on common embedding dimensions.
- Keep the wave-field layer as a top-k re-ranker, not a full-scan scorer.

### 2. Namespace And Tenant Scale

WaveMind should scale by isolating memory early:

- shard by namespace, tenant, user, project, or agent;
- use `ShardedWaveMind` for local namespace-level SQLite sharding;
- keep namespace filters inside candidate generation where possible;
- support per-namespace quotas and retention policy;
- expose migration tools for moving one namespace between databases;
- keep deletion and TTL behavior auditable.
- use deterministic cluster placement to plan primary/replica ownership before
  a namespace is migrated to another node.

Initial target: 100k to 1M memories on one node before horizontal clustering.

### 3. Performance

The next performance work is not just "make vector search faster." The dynamic
memory policy also needs to become cheaper:

- rerank only the top candidate window;
- cache hot namespaces and hot query patterns;
- batch recall feedback updates;
- run decay, graph edge updates, and consolidation in background jobs;
- keep maintenance jobs deterministic so Celery/RQ/Temporal wrappers can call
  the same `MemoryMaintenanceWorker.run_once()` path in production;
- compress or quantize embeddings where quality allows it;
- benchmark p50, p95, p99 latency separately for candidate search, reranking,
  SQLite writes, and feedback updates.
- run `wavemind scale-plan --target-memories <N> --fail-on action_required`
  before import or deployment growth so the index choice is explicit instead of
  accidental.

Potential infrastructure:

- Redis for hot-memory/query caches and scheduled query-audit prewarm jobs;
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
- consolidation that can form higher-level memory nodes. The first version is
  implemented as extractive, auditable concept memories without an LLM call;
  the next step is scheduled/background consolidation and better merge policy;
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
- Add service-mode Qdrant, pgvector, and persisted-FAISS baselines for fair
  latency curves.
- Add MIRACL Russian to prove multilingual retrieval behavior.
- Add RAGBench once answer generation and citation/fidelity metrics are stable.
- Keep every published result backed by a checked-in JSON artifact and a command
  that can reproduce it.

## Community Roadmap

The community will grow if the project is easy to understand, easy to run, and
easy to improve.

Priorities:

- examples gallery and package adapters for LangChain, LangGraph, CrewAI,
  AutoGen, OpenClaw, LlamaIndex, namespace sharding, custom Python loops, and
  HTTP-only use;
- clear `good first issue` and `help wanted` labels;
- GitHub Discussions for support and design proposals;
- benchmark scripts that contributors can run locally;
- Docker images for the API server and sidecar mode;
- release automation, generated release-note categories, labels spec, and
  release checklist;
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
- backup, restore, and point-in-time recovery. SQLite backup/restore and
  replicated snapshot/restore, offsite-mirrored snapshot jobs, and portable
  snapshot archives with S3-compatible upload, latest-archive lookup, remote
  download verification, object-store disaster-recovery drills, and retention
  are implemented; point-in-time recovery, real multi-region cloud
  disaster-recovery drills, and network-service consensus remain future work;
- data residency controls;
- SSO/OAuth integration;
- SLOs for latency, throughput, and durability;
- monitoring, alerting, and tracing;
- migration tools between SQLite, Postgres, and external vector backends.

## Milestones

### Short Term: 1 To 3 Months

- Larger service-mode benchmark profiles for persisted FAISS, Qdrant, and
  further-tuned pgvector.
- Harden the new Postgres source-of-truth backend with migration tooling,
  service-mode benchmarks, and operational docs.
- LoCoMo and LongMemEval answer-quality runs with a local or configured LLM.
- Service-mode Qdrant latency baseline beyond the checked-in 50000-vector
  profile.
- Better README examples for non-agent use cases.
- Harden integration adapters for LangGraph, LlamaIndex, CrewAI, and AutoGen.

### Medium Term: 3 To 6 Months

- Graph memory v2 with incremental edge updates.
- Background worker for decay, consolidation, graph updates, and scheduled
  backups.
- Docker image and Helm chart for API/sidecar deployment.
- Observability: richer Prometheus metrics, trace dashboards, and durable
  latency histograms beyond the current process-local API latency gauges.
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

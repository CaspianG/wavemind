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
- A service-backed production load profile now includes tuned 100000-vector
  Qdrant and 1M-vector persisted FAISS runs. Qdrant reaches `recall@10 1.000`,
  p99 `21.26 ms` at 100k with a checked-in estimate of `$1.39` per 1M queries.
  Persisted FAISS reaches `recall@10 1.000`, p99 `57.71 ms` at 1M, and an
  estimated `$4.17` per 1M queries with 6 replicas for 100 qps. The older tuned
  1M Qdrant load profile reaches `recall@10 0.984` but misses the p99 gate at
  `137.86 ms`; the newer streaming 1M Qdrant profile passes with `recall@10
  1.000`, p99 `26.37 ms`, safe upsert chunks, wait-after-build, and 100 warmup
  queries.
- The streaming compressed FAISS IVF-PQ profile now has a checked-in 10M run:
  target recall@10 `0.990`, p99 `60.13 ms`, and valid SLO/cost status.
- The streaming runner now also has real service smokes for Qdrant and
  PostgreSQL/pgvector. Qdrant reaches target recall@10 `1.000`, p99 `17.90 ms`
  over 1000 vectors / 20 queries; pgvector reaches target recall@10 `1.000`,
  p99 `7.62 ms` over the same smoke shape. The tuned streaming 1M Qdrant service
  run reaches target recall@10 `1.000`, p99 `26.37 ms`, and valid SLO/cost
  status in `benchmarks/production_streaming_load_qdrant_1m_tuned_results.json`.
  The sharded Qdrant service smoke now runs against two real Qdrant services,
  reaches target recall@10 `1.000`, p99 `16.02 ms`, and records id routing plus
  parallel fanout merge in
  `benchmarks/production_streaming_load_qdrant_sharded_smoke_results.json`.
  Checked 10M plan-only contracts live in
  `benchmarks/production_streaming_load_qdrant_10m_plan.json`,
  `benchmarks/production_streaming_load_qdrant_sharded_10m_plan.json`, and
  `benchmarks/production_streaming_load_pgvector_10m_plan.json`. These plans are
  not completed 10M benchmarks; they are exact service-backed run contracts,
  including a horizontal Qdrant fanout path for multi-node storage. The same
  runner now emits resumable checkpoint paths for large-N ingest, and
  `benchmarks/production_streaming_load_qdrant_sharded_100m_plan.json` is the
  checked preflight contract for a future 100M sharded Qdrant service run.
- `.github/workflows/production-streaming-load.yml` is the manual large-N
  runner for those contracts. It can restore a prior checkpoint artifact, run
  Qdrant, sharded Qdrant, pgvector, or FAISS IVF-PQ profiles on a sized runner,
  upload checkpoint/result artifacts, and optionally commit refreshed benchmark
  and strict-evidence reports after a real service run.
- `benchmarks/ingest_production_streaming_artifact.py` is the maintainer-side
  promotion gate for those large-N artifacts. It validates downloaded
  `production-streaming-load-results` artifacts before they become checked-in
  evidence, rejects smoke files or mismatched engine/size/SLO rows, copies only
  recognized 10M/50M/100M result JSON files, and can refresh the public
  leaderboard/readiness/evidence artifacts from the accepted result.
- `benchmarks/production_readiness_gate.py` turns checked-in artifacts into a
  production verdict. The current WaveMind core gate is `1.000` (`36/36` pass,
  `0` action required, `0` fail). Live Zep competitor evidence is tracked
  separately because a missing commercial competitor credential should not block
  WaveMind's own production readiness verdict.
- `benchmarks/production_evidence_gate.py` is the stricter production-claim
  boundary. It does not let local loopback evidence unlock remote service-node,
  active-active, managed-serverless, 10M service, 50M, or 100M scale claims.
  The current strict gate is intentionally `action_required` until real remote
  and large-service artifacts are committed. `wavemind production-evidence
  --strict` exposes the same gate as an operator/release preflight.
- `wavemind memory-os-plan` is now the read-only scheduler preflight for the
  adaptive Memory OS worker set. It turns stats and query-audit traffic into
  concrete cadences, worker counts, Redis/shared-cache requirements,
  distributed-lock requirements, and commands for prewarm, predictive prefetch,
  consolidation, adaptive forgetting, maintenance, and architecture-advice
  loops without mutating memory state.
- `POST /feedback` and `wavemind feedback` now expose explicit useful/not-useful
  recall signals. They update priority/hotness, persist state, emit audit
  events, and invalidate API cache entries for the affected namespace, so agent
  feedback can become an operational memory signal instead of a Studio-only UI
  action.
- `benchmarks/vectordbbench_dataset.py` exports a VectorDBBench custom dataset
  with `train.parquet`, `test.parquet`, `neighbors.parquet`, and
  `scalar_labels.parquet`. This makes the public vector-database benchmark path
  runner-ready without claiming an official VectorDBBench leaderboard score yet.
- The scale-readiness profile now includes sustained mixed HTTP cluster load
  across 4 real localhost API nodes: quorum writes, normal queries, node
  failover queries, replicated deletes, missing-replica repair, and p99
  operation latency are all checked by the readiness gate.
- The same scale-readiness profile now includes sustained active-active mesh
  sync across 3 independent regions and 3 namespaces: 18 writes, 90 region-pair
  syncs, cursor tracking, tombstone propagation, field-only hotness sync,
  actor-watermarked field-state CRDT convergence with missing/lag diagnostics,
  final no-op imports `0`, convergence `1.000`, delete suppression `1.000`,
  and success `1.000`.
- `benchmarks/local_http_cluster_smoke.py` is now a standalone CI gate for the
  same service-mode path. It starts 4 real localhost API processes with isolated
  SQLite stores, uses RF=3 and quorum-sized `read_fanout=1`, and currently
  passes with success `1.000`, failover hit `1.000`, delete suppression `1.000`,
  one repaired replica, post-load cluster health `true`, degraded nodes `0`,
  and p99 `348.83 ms`.
- `benchmarks/http_cluster_load_benchmark.py` is the remote service-node runner
  for the same mixed workload. It takes real `--node id=https://host` API URLs
  or a repeatable `--nodes-file deploy/cluster/external-http-cluster.sample.json`
  manifest, emits `slo_pass`, and is the next deployment gate before any
  external-cluster production claim. The production readiness gate now tracks
  the optional checked-in external run as non-gating evidence and rejects sample
  or fixture sources.
- `.github/workflows/external-http-cluster-load.yml` can run that remote
  service-node profile from GitHub Actions using either newline/comma-separated
  nodes or `nodes_manifest_json`, upload the result, and optionally commit
  refreshed leaderboard artifacts once a real deployment is available.
- `benchmarks/local_http_active_active_smoke.py` is also the remote
  active-active region runner when used with repeated `--region id=https://host`
  arguments or a repeatable
  `--regions-file deploy/cluster/external-http-active-active.sample.json`
  manifest. It writes `benchmarks/external_http_active_active_results.json`,
  validates convergence, delete propagation, cursor idempotency, final no-op
  sync, p99, and `slo_pass`, and is tracked as non-gating external evidence
  until a real regional deployment artifact is committed.
- `.github/workflows/external-http-active-active.yml` can run that remote
  region profile from GitHub Actions using either newline/comma-separated
  regions or `regions_manifest_json`, upload the result, and optionally commit
  refreshed leaderboard/readiness artifacts once real regions are available.
- `.github/workflows/serverless-observed-telemetry.yml` can run the serverless
  observed-telemetry contract from GitHub Actions against deployed HTTP/HTTPS
  API node URLs, upload `deploy/serverless/observed-telemetry.remote.json`, and
  optionally commit refreshed leaderboard/readiness artifacts. The
  scale-readiness profile prefers this remote artifact over loopback telemetry
  when it exists.
- The scale-readiness profile now includes a deterministic 100M-memory capacity
  envelope: 32768 namespace buckets, 128 nodes, 8 zones, replication factor 3,
  node/zone-loss availability `1.000`, bounded placement skew, and bounded
  per-node storage. This is capacity planning evidence, not a 100M latency
  benchmark.
- pgvector now exposes HNSW `m`, `ef_construction`, `ef_search`, iterative-scan
  controls, scan bounds, and an explicit exact-search mode for recall audits.
  The checked-in HNSW profile uses `ef_search=400`, which improves
  50000-vector recall but still misses the production recall target; exact mode
  is available to separate pgvector approximation loss from WaveMind ranking.
  The benchmark runners now expose `pgvector-exact` and
  `pgvector-iterative` as named engines, so pgvector can be tuned under the
  same SLO/cost gate instead of being tracked as one opaque failing backend.
  The checked-in service-backed tuning artifact now shows 50000-vector
  `pgvector-exact` at recall@10 `1.000` / p99 `76.98 ms` and
  `pgvector-iterative` at recall@10 `0.970` / p99 `55.19 ms`
  in `benchmarks/production_pgvector_tuning_results.json`.
- Candidate indexes expose health snapshots, count/id drift checks, HTTP/CLI
  rebuild operations, and Prometheus-compatible index-health metrics.
- `wavemind scale-plan`, `WaveMind.scale_plan()`, and `GET /scale-plan` are
  available as deployment guardrails: they map current and target memory counts
  to a scale tier, status, recommended index, warnings, and concrete actions.
- `wavemind advise`, `advise_memory_architecture()`, and
  `GET /architecture/advice` turn live stats plus target scale into an operator
  checklist for ANN/service index selection, sharding, cache, DR drills,
  observability, load tests, replication capacity, read-quorum/fanout tuning,
  and multimodal readiness.
- `MemoryOSWorker`, `POST /memory-os/run`, and `wavemind memory-os` can now
  embed that architecture-advisor output into the same adaptive maintenance
  report that handles hot-query prewarm, priority prediction, adaptive
  forgetting, TTL cleanup, and concept consolidation. The readiness gate now
  fails if the checked-in Memory OS profile does not emit production-scale
  service-index, namespace-sharding, production-controls, load-test, and
  multimodal-readiness advice.
- `RedisMemoryOSLock`, `wavemind memory-os --lock-required`, and
  `/memory-os/run` lock fields add a Redis-backed single-flight guard for
  production Memory OS cycles. This prevents overlapping consolidation,
  forgetting, and prewarm mutations when CronJobs, retries, or multiple
  operators target the same namespace.
- Namespace sharding is available for local multi-tenant SQLite deployments.
- Deterministic cluster placement planning is available through
  `build_cluster_plan()` and `wavemind cluster-plan`, including replica sets,
  node/zone-loss simulation, read/write quorum reporting, a Kubernetes
  StatefulSet manifest skeleton, and a scheduled repair CronJob manifest.
- Cluster autoscale planning is available through
  `build_cluster_autoscale_plan()`, `wavemind cluster-autoscale-plan`, and
  `POST /cluster-autoscale-plan`: it maps target memories, replication factor,
  per-node capacity, and headroom into required node count, future nodes,
  bounded per-node load, and namespace movement actions.
- Control-plane config safety is available through `ControlPlaneConsensus` and
  `wavemind control-plane-consensus`: cluster membership/operator changes can
  be guarded by a majority leadership lease, monotonic terms, monotonic config
  revisions, stale-leader rejection, stale-revision rejection, and
  minority-partition rejection. This is a deterministic Raft-like safety
  preflight for config changes, not a full networked Raft log.
- A first Helm chart is available in `deploy/helm/wavemind`: StatefulSet,
  normal/headless Services, optional auth Secret wiring, persistent per-pod
  storage, scheduled `cluster-repair` CronJob, and opt-in Memory OS CronJobs
  that call `/memory-os/plan` before `/memory-os/run`.
- GitHub Actions builds and publishes the official
  `ghcr.io/caspiang/wavemind` container image for `main` and version tags, and
  `full-check` validates Helm lint/template rendering.
- `deploy/operator` and `wavemind operator-*` commands provide the first
  Kubernetes operator-style control plane: a `WaveMindCluster` CRD, RBAC,
  operator Deployment, sample custom resource, deterministic reconciliation
  renderer, and an in-cluster loop that applies Services, StatefulSet, and
  repair CronJob resources.
- The `WaveMindCluster` CRD now exposes a `status` subresource. `wavemind
  operator-status`, `operator_status()`, and the in-cluster operator loop can
  produce and patch Kubernetes-style conditions for resources, capacity,
  autoscaling, scheduled repair, and control-plane safety. The production
  readiness gate now requires status phase `Ready`, `ControlPlaneReady`, and all
  operator readiness conditions before the operator criterion passes.
- The `WaveMindCluster` CRD now includes `spec.controlPlane.consensus`. Operator
  status embeds the same majority leader lease/config revision safety profile
  used by the standalone `wavemind control-plane-consensus` gate, so production
  config changes are blocked unless stale leaders, stale revisions, and
  minority partitions are rejected.
- The `WaveMindCluster` CRD is capacity-aware: `spec.autoscaling.targetMemories`
  plus `maxMemoriesPerNode` and `headroom` use the autoscale planner during
  reconciliation, raising StatefulSet replicas and HPA min/max replicas and
  annotating resources with calculated capacity targets.
- `deploy/serverless` and `wavemind serverless-sample` provide the first
  serverless deployment planner: a Knative scale-to-zero Service plus a valid
  KEDA Deployment/Service/ScaledObject profile. The profile requires external
  Postgres for source-of-truth state, external Qdrant for candidate search,
  Redis for shared hot-query cache, and API keys from Kubernetes Secrets.
- `WaveMindServerlessSpec.operational_profile()` and the scale-readiness gate
  now check deterministic serverless operating assumptions: target request
  rate, required replicas, burst capacity, external state, scale-to-zero safety,
  cold-start budget, and estimated monthly compute cost.
- `ServerlessObservedTelemetry` and `wavemind serverless-sample
  --operational-profile --observed-telemetry <json>` define the real-cluster
  telemetry contract. The profile now fails when observed RPS, p99,
  cold-start, error-rate, scale-out lag, max replicas, or cost miss the target.
  `benchmarks/serverless_observed_telemetry_benchmark.py` now checks in measured
  loopback telemetry from a balanced pool of real local WaveMind HTTP API
  replicas with warmed hot-query cache. It records measured pool RPS,
  per-replica RPS, cold start, p95/p99, error rate, and the max-scale horizontal
  capacity estimate. The same runner now also accepts repeated `--node`
  HTTP/HTTPS API URLs, `--api-key`, `--seed-mode`, and an external cold-start
  metric, so remote Knative/KEDA or managed serverless nodes can produce the
  same telemetry contract. This is still not a real Knative/KEDA claim until a
  remote artifact is checked in.
- `HotMemoryCache`, `QueryVectorCache`, their Redis-backed variants,
  `query_with_cache()`, `query_with_vector_cache()`, `CachePrewarmWorker`, and
  `MemoryMaintenanceWorker` provide the first worker/cache primitives for hot
  namespaces, encoded query vectors, query-audit-driven cache prewarm,
  predictive prefetch, TTL purge, field consolidation, concept consolidation,
  architecture-advice reporting, and index-health repair loops.
- Structured payload helpers cover image captions, audio transcripts, video
  transcripts/scenes, 3D asset descriptors, tables, events, and knowledge graph
  triples while preserving modality metadata in the same memory API. The first
  `CrossModalMemoryLayer` adds deterministic shared descriptor embeddings,
  persisted cross-modal vectors, target-modality routing,
  provenance-preserving recall across all seven payload types, and a strict
  precomputed-vector path for externally computed CLIP/audio/video/3D
  embeddings. `SentenceTransformersCrossModalEncoder` adds an optional
  CLIP-style local image/text backend without making sentence-transformers or
  Pillow mandatory for the base install. `S3AssetStore` adds verified
  content-addressed object-store manifests for large media assets, so
  multimodal memories can carry sha256, byte-size, media-type, and verification
  provenance without storing binary payloads in SQLite or Postgres.
- `benchmarks/scale_readiness_benchmark.py` now checks 1M-memory simulated
  namespace placement, control-plane majority lease/config revision safety,
  quorum-replicated runtime behavior, cursor-based
  active-active namespace delta sync, sustained active-active mesh sync,
  field-only hotness delta sync, actor-watermarked field-state CRDT sync with
  missing/lag diagnostics,
  service-mode distributed namespace sharding with
  primary-loss recall, missing-replica repair, real HTTP shard transport,
  concurrent namespace traffic, and tombstone-aware delete
  repair, anti-entropy background repair through `DistributedRepairWorker`
  and `wavemind cluster-repair`, Kubernetes CronJob generation for scheduled
  repair, checksummed replicated snapshot/restore with offsite and
  portable-archive verification, S3-compatible object-store upload,
  latest-archive metadata, remote download, retention verification, and a
  deterministic object-store disaster-recovery drill, query-audit cache
  prewarm, predictive prefetch, query-vector cache, Redis-compatible shared rate limiting, hot-cache
  behavior, API cache mutation safety, structured-payload retrieval,
  cross-modal target-modality/provenance checks, external precomputed-vector
  compatibility checks, and object-store-backed asset manifest verification.
- Dynamic policy already covers hot memory, stale suppression, corrections,
  TTL, and namespace isolation.
- Field self-consolidation is available through `WaveMind.consolidate_concepts()`,
  `wavemind consolidate`, and `POST /consolidate`: active graph clusters can
  become durable concept memories with source-memory provenance.
- SQLite audit events, a Prometheus-compatible `/metrics` endpoint,
  process-local API latency/failure metrics, optional OpenTelemetry traces, and
  local Prometheus/OTEL Collector alert examples now cover the first
  observability layer.
- API key roles, opt-in in-process rate limiting, and Redis-compatible shared
  rate limiting are available for FastAPI deployments.
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
  The 100k service-mode Qdrant benchmark is checked in and healthy; the tuned
  1M streaming Qdrant service run now passes recall/p99 after safe chunks,
  wait-after-build, and warmup. The next promotion step is the same tuned
  profile at 10M on sized hardware.
- Rebuild and persist ANN indexes safely after batch imports or recovery. The
  first persisted FAISS snapshot path and production profile are implemented,
  including a 1M-vector checked-in load result that passes recall and p99.
  Production still needs Linux/container repeat runs and deeper latency traces.
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
- keep long 10M/50M/100M streaming benchmark runs checkpointed so interrupted
  service ingest can resume from completed batches.
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
- weekly benchmark refresh that regenerates the matrix/report/leaderboard and
  SVG summary, validates freshness, writes a machine-readable artifact audit,
  uploads review artifacts, and deploys a GitHub Pages living leaderboard
  without scheduled bot commits to `main`;
- `full-check` and release workflows block stale or unsynchronized public
  benchmark artifacts with the same 8-day freshness gate;
- Docker images for the API server and sidecar mode;
- release automation, generated release-note categories, labels spec, and
  release checklist;
- support and security policy docs;
- harden the Kubernetes operator-style control plane from renderer/loop into a
  documented production controller, then add managed/serverless deployment
  options after real cluster feedback;
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
  SQLite point-in-time recovery through an append-only mutation journal are
  implemented. Replicated snapshot/restore, offsite-mirrored snapshot jobs, and
  portable snapshot archives with S3-compatible upload, latest-archive lookup,
  remote download verification, object-store disaster-recovery drills, and
  retention are also implemented. `wavemind postgres-pitr-plan` and
  `benchmarks/postgres_pitr_plan.json` add a database-native Postgres PITR
  runbook/preflight with WAL archiving, streaming base backup, restore target,
  replay verification, promotion, and secret-safe environment placeholders.
  Real managed-Postgres PITR drill evidence, real multi-region cloud
  disaster-recovery drills, and network-service consensus remain future work;
- data residency controls;
- SSO/OAuth integration;
- SLOs for latency, throughput, and durability;
- monitoring, alerting, and tracing;
- migration tools between SQLite, Postgres, and external vector backends.

## Milestones

### Short Term: 1 To 3 Months

- Larger service-mode benchmark profiles for persisted FAISS, Qdrant, and
  further-tuned pgvector, with SLO and cost gates tracked for every checked-in
  production result.
- Keep the production readiness gate at `1.000` while repeating larger
  service-backed runs. Mem0, LangGraph, and a GraphRAG-style static graph
  baseline already have checked-in local adapter results; a live Zep service
  adapter run remains external evidence to add when `ZEP_API_URL` or
  `ZEP_API_KEY` is configured.
- Use the checked-in `benchmarks/production_streaming_load_50m_plan.json`
  preflight to run the next 50M target-recall profile, then add the resulting
  `production_streaming_load_ivfpq_50m_results.json` artifact. Use the same
  runner for Qdrant/pgvector 10M service-backed profiles so large-N profiles do
  not hold the full vector corpus or exact-neighbor matrix in RAM. The
  pgvector 10M service-backed profile now has a checked preflight contract;
  the next step is producing `production_streaming_load_pgvector_10m_results.json`
  from a real sized PostgreSQL service.
- Harden the new Postgres source-of-truth backend with migration tooling,
  service-mode benchmarks, and operational docs.
- LoCoMo and LongMemEval answer-quality runs with a local or configured LLM.
- Service-mode Qdrant streaming now has a real smoke, a real two-node sharded
  smoke, a tuned 1M passing run, and single-service plus sharded 10M preflight
  contracts; the next step is producing
  `production_streaming_load_qdrant_10m_results.json` on sized Qdrant storage
  and `production_streaming_load_qdrant_sharded_10m_results.json` on multiple
  Qdrant service nodes.
- Service-mode Qdrant latency baseline beyond the checked-in 50000-vector
  profile.
- Better README examples for non-agent use cases.
- Harden integration adapters for LangGraph, LlamaIndex, CrewAI, and AutoGen.

### Medium Term: 3 To 6 Months

- Graph memory v2 with incremental edge updates.
- Background worker for decay, consolidation, graph updates, and scheduled
  backups.
- Harden the Knative/KEDA serverless path by replacing the checked-in loopback
  telemetry with real-cluster p95/p99/cold-start/error-rate/scale-out
  telemetry, then add managed-control-plane docs.
- Observability: richer Prometheus metrics, trace dashboards, and durable
  latency histograms beyond the current process-local API latency gauges.
- Multi-encoder support: local sentence-transformers, OpenAI-compatible APIs,
  and application-provided embeddings.
- Multimodal encoders: the optional sentence-transformers backend now covers
  CLIP-style local image/text retrieval; next are benchmarked audio embeddings,
  video scene embeddings, and 3D descriptors behind the same
  `CrossModalMemoryLayer` and `PrecomputedCrossModalEncoder` contracts.
- Community benchmark dashboard generated from checked-in result JSON, backed by
  the weekly freshness/audit gate.
- Strict production-evidence dashboard/report that stays separate from the core
  readiness score and lists the exact remote or large-scale run needed for each
  blocked claim.

### Longer Term

- Horizontal namespace sharding.
- Clustered deployment mode.
- Enterprise auth, RBAC, audit log, and encryption.
- Hosted managed service.
- Production-grade multimodal memory beyond deterministic descriptors:
  benchmarked CLIP image/text runs, audio/video/3D encoders, larger public
  retrieval tests, and encoder health monitoring.
- Production-grade graph/field memory with measurable excitation,
  inhibition, decay, and consolidation behavior.

## Non-Goals For Now

- Do not position WaveMind as a full replacement for Pinecone, Weaviate,
  Qdrant, Milvus, or Chroma on static large-scale RAG.
- Do not claim leaderboard results without official datasets, reproducible
  commands, and checked-in result artifacts.
- Do not hide latency limits. Dynamic memory must earn its cost by improving
  recall quality, stale suppression, correction handling, or context size.

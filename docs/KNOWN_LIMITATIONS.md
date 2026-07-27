# Known Limitations And Claim Boundaries

WaveMind publishes limitations because a memory system is only useful when its
operators know which behavior is measured, which topology is admitted, and
which claims remain locked. This document is the detailed source; the root
README keeps only the decisions most users need before installation.

## Local Retrieval And Indexes

- Optimal capacity on the current NumPy exact index is up to 1000 records.
- At 5000 records, one-word `precision@1` is currently 0.72 with the hash
  encoder; many misses are ambiguous queries where another sentence containing
  the same word ranks first.
- For `N > 5000`, the NumPy exact index is still reliable but scales linearly.
  Annoy is faster at 50000 vectors in the local curve, but current recall is
  only `0.730`; the `quantized` backend reaches `0.934` recall@10 with int8
  storage and int32-safe scoring, but is still slower than NumPy on this
  workload. Use FAISS or a production vector service before claiming
  large-scale ANN quality.
- Run `wavemind scale-plan --target-memories <N>` before growing a deployment.
  It is a guardrail, not a benchmark replacement: it tells you when NumPy is no
  longer the right candidate index and which checks to run next.
- `sentence-transformers/paraphrase-multilingual-mpnet-base-v2` requires about
  420 MB of model files. Benchmark runners cache embeddings so retrieval
  latency is measured separately from model encoding latency.
- The `quantized` backend is an explicit int8 candidate-index experiment. It
  reduces vector precision, stores the local candidate matrix compactly, uses
  an int32 accumulator to avoid dot-product overflow, and must be benchmarked
  per workload before use.
- The Qdrant backend is a candidate-index backend. WaveMind rebuilds it from
  SQLite on load/build, so large service-mode deployments still need a measured
  rebuild strategy and index-health monitoring.
- The persisted FAISS backend validates a snapshot against current memory ids
  and avoids unnecessary FAISS rebuilds when the snapshot matches. FAISS itself
  is a single-node flat-index path; use `ReplicatedWaveMind` or external
  database/service replication when that is not enough.

## Benchmark Interpretation

- The Chroma comparison currently uses shared precomputed hash embeddings to
  isolate retrieval/ranking behavior; semantic model comparisons should be run
  separately.
- The BEIR SciFact run uses the hash encoder to isolate index/retrieval
  behavior. It is not a semantic embedding leaderboard result.
- On BEIR SciFact, WaveMind and Qdrant match on hash-encoder `nDCG@10`, while
  Chroma is much faster. The next index milestone is FAISS/Annoy candidate
  generation plus WaveMind top-k re-ranking.
- The LoCoMo results are retrieval-only evidence results, not final
  answer-quality scores. The sentence-transformers run is stronger than the
  hash run, but still needs answer generation and faithfulness checks.
- In the 200-fact agent benchmark, Chroma is faster on average while WaveMind is
  slightly higher at `precision@3`.
- The dynamic benchmark currently compares WaveMind against a static Chroma
  baseline. Chroma and Qdrant can implement similar behavior with extra
  application-layer metadata policy, deletes, filters, and reinforcement logic.
- The synthetic long-term memory evidence benchmark is useful for regression
  and product-shape proof, but public claims should lean on LoCoMo and
  LongMemEval instead.
- The main LongMemEval evidence result is retrieval-only. The checked-in Ollama
  answer-generation comparison includes WaveMind, Chroma static, and Qdrant
  static over 50 questions, but it is still not a full LongMemEval
  leaderboard-equivalent score.
- The production cost model is an engineering estimate from checked-in
  benchmark parameters: required replicas, target QPS, replica hourly cost,
  vector storage, and payload storage. It is not a cloud-provider bill and must
  be recalibrated for real hardware.
- MTEB, MIRACL, LMEB, official VectorDBBench, and RAGBench are listed as the
  public benchmark roadmap, not as completed results.
- Local Ollama answer generation works with `qwen2.5:0.5b` and
  `qwen2.5:1.5b`; WaveMind leads the checked-in Chroma/Qdrant smoke comparison,
  but answer quality is still limited by small-model reasoning and should be
  rerun with stronger local or API models before making product claims.
- Public benchmark adapters require optional datasets, heavier dependencies, or
  running services. They are intentionally outside the minimal
  `pip install wavemind` path.

## Dynamic Memory Performance

- `MemoryFieldGraph` is a discrete graph over stored memories, not a continuous
  mathematical field. Its current build path should be optimized with
  incremental edge updates before large production use.
- Dynamic memory is slower than static Chroma in the current local benchmark:
  25.26 ms vs 1.75 ms average query latency on this machine.
- Current WaveMind-only dynamic checks keep `precision@1` at 1.00 through 5000
  memories, but average latency is around 48-54 ms. The next optimization target
  is field and re-ranking latency, not basic recall quality.

## Distributed And Production Evidence

- Kubernetes operator reconciliation has durable Lease/etcd-backed leader
  election with CAS and failover between operator replicas. The separate
  `ControlPlaneConsensus` profile remains a deterministic config-safety guard,
  not an implementation of a replicated Raft log for the WaveMind data plane.
- The checked Kubernetes network drill writes `256` deterministic memories
  through four pod-DNS API nodes in three worker zones, physically pauses one
  kind worker, detects the unreachable replica, preserves `1.00` quorum recall,
  and returns to `1.00` recall with no failed nodes after recovery. This is real
  non-loopback CI evidence, but it is still ephemeral kind evidence rather than
  remote multi-region production admission. See
  `benchmarks/kubernetes_cluster_network_smoke_results.json` and its traceable
  [GitHub Actions run](https://github.com/CaspianG/wavemind/actions/runs/29165761261).
- The checked active-active Kubernetes drill uses three separate replicated
  region APIs with persistent volumes in three worker zones. During a physical
  zone-B worker pause, regions A and C continue writes and delete propagation at
  `1.00` convergence; the recovered region converges without resurrecting the
  deleted memory and the final sync is a no-op. This remains ephemeral kind
  evidence rather than independent remote-region admission. See
  `benchmarks/kubernetes_active_active_region_smoke_results.json` and its
  [GitHub Actions run](https://github.com/CaspianG/wavemind/actions/runs/29165761261).
- pgvector is a candidate-index backend. PostgreSQL source-of-truth storage is
  available separately. A Postgres-native PITR runbook/preflight exists through
  `wavemind postgres-pitr-plan` and `benchmarks/postgres_pitr_plan.json`;
  migrations, real managed-Postgres PITR drill evidence, and larger service
  benchmark profiles still need more real deployment coverage.
- Qdrant baselines in the public reports use embedded local mode unless a row is
  explicitly marked service-backed. Qdrant itself warns that local mode is not
  recommended above 20000 points; use the `qdrant-service` profiles before
  making production latency claims.
- The tuned 1M Qdrant streaming result depends on safe upsert chunking,
  `30` seconds wait-after-build, and `100` warmup queries. The cold 1M run misses
  the p99 SLO, so production Qdrant claims must specify warmup and tuning.
- The Qdrant streaming path has real single-service and four-service sharded
  10M artifacts. These prove the tested local service topology and SLO, not
  multi-host or multi-region deployment.
- The pgvector streaming path has a real four-service 10M artifact with
  recall@10 `0.975` and p99 `87.66 ms`. It proves the checked GitHub-hosted
  isolated-service topology; it does not prove independent multi-host or
  multi-region production.

## Multimodal Evidence

- The checked real-encoder artifact covers 1000 public text/image/audio/video/3D
  assets and 200 independent queries with pinned SentenceTransformers, CLIP,
  CLAP, and OpenShape PointBERT revisions. Three exact-SHA runs reach macro,
  cross-modal, and mixed precision@1 `0.925`, persisted/reload parity `1.000`,
  retrieval p99 `48.64 ms`, and zero errors.
- `wavemind multimodal-admission` is `admitted` for that exact source SHA,
  model set, public-suite revision, and local MinIO lifecycle. It does not prove
  universal quality on unrelated domains, remote object-store SLOs, GPU
  performance, or independently hosted production behavior.
- Deterministic descriptors and externally precomputed vectors remain useful
  development/integration paths, but neither is accepted as real-encoder
  evidence.

## Current Claim Boundary

The admitted Production Memory OS topology and its remote soak are valid
checked evidence. Remote multi-region active-active, managed serverless,
100M service operation, and universal-domain multimodal quality remain locked
until their own admission artifacts pass. The pinned local multimodal suite is
admitted only within the boundaries above.

Use the [living dashboard](https://caspiang.github.io/wavemind/),
[Benchmark Guide](BENCHMARKS.md), and
[Scale And Production](SCALE_AND_PRODUCTION.md) for the current machine-readable
status.

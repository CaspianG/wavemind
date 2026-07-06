# WaveMind Public Benchmark Brief

This is the human-readable benchmark report for launch posts. It summarizes
checked-in benchmark artifacts only. It is not an official leaderboard and it
does not claim WaveMind is a faster static vector database than Chroma, Qdrant,
FAISS, or pgvector.

## Short Readout

WaveMind is strongest when memory behavior matters:

- stale facts should be suppressed;
- newer corrections should outrank older facts;
- temporary facts should expire;
- namespaces should prevent cross-user leakage;
- repeated recall should reinforce useful memories.

Static vector search is still faster in several retrieval-only cases. The
current evidence says WaveMind is a dynamic memory layer, not a replacement for
purpose-built vector databases.

## Checked-In Result Summary

| benchmark | result | artifact | reproduce |
|---|---|---|---|
| Agent coherence and token savings | On a 500-memory long user-history task simulation, WaveMind reaches `task success 0.92`, stale error rate `0.00`, context saved `0.93`, `9` coherent turns, and `2.98 ms` average query latency; Static vector reaches `0.33` task success and stale error rate `0.73`; Chroma static reaches `0.42` task success and stale error rate `0.18`. | `benchmarks/agent_coherence_results.json` | `python benchmarks/agent_coherence_benchmark.py --memories 500 --engines wavemind static chroma --output benchmarks/agent_coherence_results.json` |
| Dynamic memory policy | WaveMind reaches `precision@1 1.00` and `stale suppression 1.00`; Chroma static reaches `precision@1 0.57` and `stale suppression 0.00`. | `benchmarks/dynamic_memory_results.json` | `python benchmarks/dynamic_memory_benchmark.py --engines wavemind chroma --memories 200 --output benchmarks/dynamic_memory_results.json` |
| LoCoMo evidence retrieval | WaveMind sentence reaches `evidence_recall@5 0.547`; Chroma sentence reaches `0.407`; Qdrant sentence reaches `0.409`. | `benchmarks/locomo_sentence_evidence_results.json` | `python benchmarks/locomo_memory_benchmark.py --engines wavemind-sentence chroma-sentence qdrant-sentence --output benchmarks/locomo_sentence_evidence_results.json` |
| LongMemEval evidence retrieval | WaveMind reaches `evidence_recall@5 0.782`; Chroma static reaches `0.518`; Qdrant static reaches `0.520`. | `benchmarks/longmemeval_evidence_results.json` | `python benchmarks/longmemeval_memory_benchmark.py --engines wavemind chroma qdrant --output benchmarks/longmemeval_evidence_results.json` |
| LongMemEval answer smoke | With local Ollama `qwen2.5:1.5b`, WaveMind reaches `token_f1 0.333`; Chroma static and Qdrant static reach `0.170`. | `benchmarks/longmemeval_answer_qwen25_1_5b_50_results.json` | `python benchmarks/longmemeval_answer_benchmark.py --dataset benchmarks/data/longmemeval_s_cleaned.json --provider ollama --model qwen2.5:1.5b --engines wavemind chroma qdrant --limit-queries 50 --output benchmarks/longmemeval_answer_qwen25_1_5b_50_results.json` |
| BEIR SciFact retrieval | WaveMind reaches `nDCG@10 0.354`; Chroma reaches `0.350`; Qdrant reaches `0.354`. Chroma is much faster on this static retrieval path. | `benchmarks/open_retrieval_scifact_results.json` | `python benchmarks/open_retrieval_benchmark.py --dataset scifact --engines wavemind chroma qdrant --output benchmarks/open_retrieval_scifact_results.json` |
| NoMIRACL Russian retrieval | WaveMind reaches `nDCG@10 0.434`; Chroma reaches `0.435`; Qdrant reaches `0.433`. Chroma is faster. | `benchmarks/nomiracl_russian_results.json` | `python benchmarks/nomiracl_russian_benchmark.py --engines wavemind chroma qdrant --output benchmarks/nomiracl_russian_results.json` |
| Production index profile | At 50000 vectors, persisted FAISS and Qdrant service both reach `recall@10 1.000`; pgvector with `ef_search=400` reaches `0.811`. | `benchmarks/production_index_profile_results.json` | `docker compose -f examples/production-index-profile/docker-compose.yml run --rm benchmark` |
| Production load profile | At 100000 vectors, Qdrant service reaches `recall@10 1.000`, avg `10.28 ms`, p99 `21.26 ms`, passes the SLO gate (`recall >= 0.95`, `p99 <= 100 ms`, `100 qps`, 3 replicas, HPA max 24), and estimates `$1.39` per 1M queries with `$365.02` monthly target cost. At 1M vectors over 100 queries, persisted FAISS reaches `recall@10 1.000`, avg `39.12 ms`, p99 `57.71 ms`, and estimates `$4.17` per 1M queries with 6 replicas for 100 qps. Tuned Qdrant at 1M reaches `0.984`, avg `82.57 ms`, p99 `137.86 ms`, so its service path still needs tail-latency tuning. | `benchmarks/production_load_qdrant_100k_tuned_results.json`, `benchmarks/production_load_faiss_1m_results.json`, `benchmarks/production_load_qdrant_1m_tuned_results.json` | `python benchmarks/production_load_benchmark.py --sizes 1000000 --engines faiss-persisted` |
| Production streaming load runner | Memory-bounded runner for 10M/50M profiles. The checked-in 10M compressed FAISS IVF-PQ run reaches target recall@10 `0.990`, p99 `60.13 ms`, and valid SLO/cost status; the 100k IVF-PQ smoke reaches `0.960`, p99 `1.10 ms`; the 10k numpy smoke reaches `1.000`, p99 `0.98 ms`. | `benchmarks/production_streaming_load_ivfpq_10m_results.json`, `benchmarks/production_streaming_load_ivfpq_100k_results.json`, `benchmarks/production_streaming_load_smoke_results.json` | `python benchmarks/production_streaming_load_benchmark.py --sizes 10000000 --engines faiss-ivfpq-persisted --output benchmarks/production_streaming_load_ivfpq_10m_results.json` |
| Scale readiness profile | Deterministic 1M-memory simulation: namespace placement survives node loss and zone loss at `1.000`; cluster autoscale planning maps a 10M target to `50` required nodes, `46` additional nodes, target max node load `678711`, and headroom pass `true`; Kubernetes `StatefulSet`, `HorizontalPodAutoscaler`, repair `CronJob`, and operator-style `WaveMindCluster` reconciliation are generated for `4096` namespaces; the capacity-aware operator maps a 10M target to `34` StatefulSet/HPA replicas with target max node load `678711` and status phase `Ready`; Knative/KEDA serverless planning has `scale_to_zero=true`, `max_scale=64`, external Postgres/Qdrant/Redis wiring, and a valid KEDA Deployment target; the serverless operational profile checks `3200` RPS, `4` required replicas, `64000` burst RPS, `1220 ms` cold-start total, `$81.76` modeled monthly compute cost, and an observed-telemetry contract with fixture source `scale-readiness-fixture`, observed p99 `300 ms`, error rate `0.001`, and `observed_slo_pass=true`; service-mode distributed sharding, real HTTP transport, sustained HTTP cluster load, anti-entropy repair, Redis/shared caches, Memory OS adaptive prewarm/forgetting/consolidation plus production architecture advice, cursor-based active-active delta sync, field-only hotness sync, CRDT field-state merge, object-store DR drills, image/audio/video/3D/table/event/graph structured payloads, cross-modal target-modality precision@1 `1.000`, persisted vector rate `1.000`, precomputed external-vector precision@1 `1.000`, provenance rate `1.000`, and the 100M capacity envelope all remain covered by the same artifact. | `benchmarks/scale_readiness_results.json` | `python benchmarks/scale_readiness_benchmark.py --simulated-memories 1000000 --output benchmarks/scale_readiness_results.json` |
| Local HTTP cluster smoke | 4 real localhost API nodes with isolated SQLite stores, RF=3, `read_fanout=1`, workers `4`: success `1.000`, failover hit `1.000`, delete suppression `1.000`, repaired replicas `1`, health `true`, degraded nodes `0`, p99 `348.83 ms`, SLO `true`. | `benchmarks/local_http_cluster_smoke_results.json` | `python benchmarks/local_http_cluster_smoke.py --nodes 4 --replication-factor 3 --read-fanout 1 --namespace-count 4 --memories-per-namespace 2 --workers 4 --timeout 3 --fail-on-slo --output benchmarks/local_http_cluster_smoke_results.json` |
| External HTTP cluster load runner | Runner-ready benchmark for real WaveMind API-node deployments. It accepts repeated `--node id=https://host` arguments or a repeatable `--nodes-file deploy/cluster/external-http-cluster.sample.json` manifest and checks quorum writes, normal queries, simulated node failover queries, missing-replica repair, replicated forget, delete suppression, p99, and `slo_pass`. `.github/workflows/external-http-cluster-load.yml` runs the same profile from GitHub Actions using newline/comma/semicolon-separated node input or `nodes_manifest_json`, uploads the artifact, and can commit refreshed results when `commit_results=true`. No fake remote result is checked in; the production gate tracks a missing external result as non-gating evidence until a real deployment exists. | optional `benchmarks/http_cluster_load_results.json` | `python benchmarks/http_cluster_load_benchmark.py --nodes-file deploy/cluster/external-http-cluster.sample.json --replication-factor 3 --read-quorum 1 --read-fanout 1 --fail-on-slo` |
| Production readiness gate | Current WaveMind core gate score is `1.000`: `28/28` criteria pass, `0` require action, `0` fail. Live Zep competitor evidence is tracked separately and remains pending until a real service is configured. | `benchmarks/production_readiness_results.json`, `benchmarks/PRODUCTION_READINESS.md` | `python benchmarks/production_readiness_gate.py --output benchmarks/production_readiness_results.json --markdown-output benchmarks/PRODUCTION_READINESS.md` |
| VectorDBBench custom dataset | Runner-ready custom dataset export for official VectorDBBench flows: `train.parquet`, `test.parquet`, `neighbors.parquet`, and `scalar_labels.parquet` with 10000 vectors, 100 queries, 128 dimensions, and cosine neighbors. | `benchmarks/vectordbbench_dataset_manifest.json` | `python benchmarks/vectordbbench_dataset.py --vectors 10000 --queries 100 --dim 128 --top-k 10 --output-dir state/vectordbbench-wavemind --manifest benchmarks/vectordbbench_dataset_manifest.json` |
| Memory competitor adapter profile | WaveMind reaches `precision@1 0.80`, `precision@3 1.00`, stale suppression `1.00`; Mem0 runs locally with Qdrant + FastEmbed and reaches `0.80`, `1.00`, stale suppression `0.60`; LangGraph persistent SQLite reaches `0.80`, `1.00`, stale suppression `1.00`; GraphRAG-style static graph reaches `1.00`, `1.00`, stale suppression `1.00` on this small static graph scenario; Zep has live adapter paths for the current `zep-cloud` Graph API and legacy/OSS-compatible `zep-python`, and remains skipped until `ZEP_API_URL` or `ZEP_API_KEY` points at a real service. | `benchmarks/memory_competitor_results.json` | `python benchmarks/memory_competitor_benchmark.py --engines wavemind mem0 zep langgraph graphrag` |

The generated matrix view is in `benchmarks/BENCHMARK_REPORT.md`; the compact
leaderboard view is in `benchmarks/BENCHMARK_LEADERBOARD.md`.
The production readiness gate is in `benchmarks/PRODUCTION_READINESS.md`.
`benchmarks/benchmark_artifact_audit.json` records the latest freshness and
synchronization check for the generated benchmark artifacts.
The weekly leaderboard workflow refreshes these artifacts, and `full-check` plus
the release workflow block stale or unsynchronized public benchmark artifacts
with `benchmarks/validate_benchmark_artifacts.py --max-age-days 8`.

## What This Proves

WaveMind has credible early evidence for dynamic agent memory:

- it can outperform static vector retrieval when facts update, expire, or
  conflict;
- it can retrieve more labeled long-memory evidence on LoCoMo and LongMemEval
  with the checked-in benchmark settings;
- it can preserve same-embedding retrieval quality on public retrieval datasets
  such as BEIR/SciFact and NoMIRACL Russian.

## What This Does Not Prove Yet

This report does not prove:

- an official LoCoMo, LongMemEval, MTEB, MIRACL, RAGBench, or VectorDBBench
  leaderboard score;
- that WaveMind is faster than Chroma for static vector retrieval;
- that the current local answer-generation smoke run is a full answer-quality
  benchmark;
- that the scale-readiness profile itself is a 10M-vector database load test;
- that the 10M compressed FAISS IVF-PQ profile is exact-neighbor recall or a
  Qdrant/pgvector 10M service comparison. It is a target-recall profile over a
  compressed persisted FAISS index;
- that pgvector is already a recommended production candidate index for
  WaveMind. The current profile improves recall but still misses the production
  target;
- that the current 1M Qdrant service profile has a stable sub-100 ms p99 SLO.
  Tuned Qdrant now reaches `recall@10 0.984` over 100 queries, but p99 is still
  `137.86 ms`. The 1M production gate is currently closed by persisted FAISS,
  while Qdrant/pgvector remain tuning targets.

## Launch Post: Hacker News

Title:

```text
Show HN: WaveMind benchmark report, dynamic memory vs static vector retrieval
```

Post:

```text
I have been building WaveMind, an MIT-licensed local-first dynamic memory layer
for apps and agents.

The benchmark report is now checked into the repo. The short version:

- On dynamic memory policy, WaveMind reaches precision@1 1.00 and stale
  suppression 1.00; a static Chroma baseline reaches precision@1 0.57 and stale
  suppression 0.00.
- On LongMemEval evidence retrieval, WaveMind reaches evidence_recall@5 0.782;
  Chroma static reaches 0.518 and Qdrant static reaches 0.520.
- On BEIR/SciFact static retrieval, WaveMind is at retrieval-quality parity but
  Chroma is much faster. This is a real limitation.
- On the production index profile at 50000 vectors, persisted FAISS and Qdrant
  service both reach recall@10 1.000. pgvector is improved but not ready as the
  recommended candidate index.
- On the 100000-vector production load profile, Qdrant service reaches
  recall@10 1.000, avg 10.28 ms, and p99 21.26 ms. On the 1M persisted FAISS
  run, recall reaches 1.000 over 100 queries with p99 57.71 ms. The tuned 1M
  Qdrant run is recall-credible but still above the p99 SLO.

I am not claiming this replaces vector databases. WaveMind is a memory-behavior
layer: TTL, hotness, corrections, namespaces, priority, audit, backups, and
explicit forgetting around vector candidate search.

All results have checked-in JSON artifacts and reproduction commands.
```

## Launch Post: Reddit

Title:

```text
I benchmarked my open-source dynamic memory layer against static vector retrieval
```

Post:

```text
I am building WaveMind, an MIT-licensed local-first memory layer for agents and
apps. I finally put together a checked-in benchmark report instead of just
describing the idea.

The main thing I wanted to test: when memory changes over time, does a dynamic
memory layer help compared with plain vector retrieval?

Current results:

- Dynamic memory policy: WaveMind precision@1 1.00, stale suppression 1.00;
  Chroma static precision@1 0.57, stale suppression 0.00.
- LongMemEval evidence retrieval: WaveMind evidence_recall@5 0.782; Chroma
  static 0.518; Qdrant static 0.520.
- LoCoMo sentence evidence retrieval: WaveMind 0.547; Chroma 0.407; Qdrant
  0.409.
- BEIR/SciFact static retrieval: quality is roughly at parity, but Chroma is
  much faster. I am not hiding that.
- Production load: Qdrant service is strong at 100k vectors. Persisted FAISS
  now closes the 1M recall/p99 gate with recall@10 1.000 and p99 57.71 ms.
  Tuned 1M Qdrant remains above the p99 SLO and needs tail-latency work.

The conclusion is not "WaveMind is a better vector DB." It is not. The
conclusion is narrower: if you need TTL, corrections, hotness, namespaces,
stale-fact suppression, audit, and local source-of-truth storage, a dynamic
memory layer can beat static vector retrieval on memory-shaped workloads.

The repo includes JSON result artifacts and commands for reproduction. I would
like feedback on the benchmark design, especially from people building
long-running agents or local-first RAG tools.
```

## Launch Post: X Thread

1.

```text
I published a checked-in benchmark report for WaveMind.

WaveMind is an open-source dynamic memory layer for apps/agents. The question:
can memory policy beat plain vector retrieval when facts update, expire, or
conflict?
```

2.

```text
Dynamic memory policy:

WaveMind:
precision@1 1.00
stale suppression 1.00

Chroma static:
precision@1 0.57
stale suppression 0.00

This is the strongest current signal.
```

3.

```text
LongMemEval evidence retrieval:

WaveMind evidence_recall@5: 0.782
Chroma static: 0.518
Qdrant static: 0.520

This is retrieval-only, not a full official answer-quality leaderboard.
```

4.

```text
Static retrieval reality check:

On BEIR/SciFact, WaveMind is around retrieval-quality parity, but Chroma is much
faster.

So the claim is not "better vector DB". The claim is "memory behavior layer".
```

5.

```text
Production index profile at 50k vectors:

WaveMind persisted FAISS recall@10: 1.000, avg 3.52 ms
Qdrant service recall@10: 1.000, avg 4.41 ms
pgvector recall@10: 0.811, avg 10.95 ms

pgvector still needs tuning.
```

6.

```text
Production load:

100k Qdrant service:
recall@10 1.000
avg 10.28 ms
p99 21.26 ms
cost $1.39 / 1M queries

1M persisted FAISS:
recall@10 1.000
avg 39.12 ms
p99 57.71 ms
cost $4.17 / 1M queries

1M Qdrant service tuned:
recall@10 0.984
avg 82.57 ms
p99 137.86 ms

1M Qdrant EF sweep best recall point:
hnsw_ef 2048
recall@10 0.977
avg 64.76 ms
p99 103.77 ms

The 1M production gate is now closed by persisted FAISS. Qdrant is still
recall-credible at 1M, but needs tail-latency work before it clears the same
p99 SLO.
```

7.

```text
The full report includes checked-in JSON artifacts and reproduction commands.

WaveMind is MIT licensed, local-first, installable with:

pip install wavemind

Repo: https://github.com/CaspianG/wavemind
```

## Follow-Up Issues To Open From Feedback

Convert real launch feedback into issues using these categories:

- benchmark methodology;
- missing baseline;
- unclear install path;
- misleading README copy;
- integration request;
- performance bottleneck;
- docs/example gap.

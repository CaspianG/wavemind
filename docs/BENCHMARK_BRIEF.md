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
| Agent coherence and token savings | On a 500-memory long user-history task simulation, WaveMind reaches `task success 0.92`, stale error rate `0.00`, context saved `0.93`, `9` coherent turns, and `2.65 ms` average query latency; WaveMind + Memory OS keeps the same task success while proving `1` hot query, `1` prewarmed query, `4` predictive-prefetch warmed queries, `5` priority predictions, and cache hit rate `0.24`; Static vector reaches `0.33` task success and stale error rate `0.73`; Chroma static reaches `0.33` task success and stale error rate `0.45`. | `benchmarks/agent_coherence_results.json` | `python benchmarks/agent_coherence_benchmark.py --memories 500 --engines wavemind wavemind-memory-os static chroma --output benchmarks/agent_coherence_results.json` |
| Agent impact leaderboard | Aggregates checked-in behavioral evidence across `6` benchmark groups: agent coherence, dynamic-memory policy, long-term memory evidence, LoCoMo sentence evidence, LongMemEval evidence, and LongMemEval answer quality. WaveMind currently has `6/6` primary wins over the best non-WaveMind baseline inside each artifact, average primary lift `0.370`, average context saved `0.719`, and average stale-safety score `1.000`. | `benchmarks/agent_impact_results.json`, `benchmarks/AGENT_IMPACT.md` | `python benchmarks/agent_impact_leaderboard.py --output benchmarks/agent_impact_results.json --markdown-output benchmarks/AGENT_IMPACT.md` |
| Structured memory report | Pulls the structured/multimodal row out of the larger scale-readiness artifact into a dedicated public report. It covers `7` modalities (image, audio, table, event, video, 3D, graph), structured precision@1 `1.000`, cross-modal precision@1 `1.000`, persisted vector rate `1.000`, provenance `1.000`, precomputed-vector precision@1 `1.000`, temporal event precision@1 `1.000`, knowledge-graph precision@1 `1.000`, graph path precision@1 `1.000`, and all gate checks passing. | `benchmarks/structured_memory_results.json`, `benchmarks/STRUCTURED_MEMORY.md` | `python benchmarks/structured_memory_report.py --output benchmarks/structured_memory_results.json --markdown-output benchmarks/STRUCTURED_MEMORY.md` |
| Memory OS intelligence report | Pulls adaptive-worker evidence out of scale readiness, agent coherence, staging canary, admission, and policy-bundle artifacts into one public report. It currently has `35/35` gate checks passing: hot-query prewarm, transition-learned predictive prefetch, priority learning, adaptive forgetting, concept consolidation, Redis cross-worker coordination, agent context savings, canary admission, staging policy-bundle promotion, and strict production admission boundaries. Production Memory OS automation is still plan-only until real shared Redis, distributed lock, runtime env, and large-scale evidence pass. | `benchmarks/memory_os_intelligence_results.json`, `benchmarks/MEMORY_OS_INTELLIGENCE.md` | `python benchmarks/memory_os_intelligence_report.py --output benchmarks/memory_os_intelligence_results.json --markdown-output benchmarks/MEMORY_OS_INTELLIGENCE.md` |
| Cluster autoscale report | Pulls cluster/operator evidence out of scale readiness into a dedicated public report. It currently has `53/53` gate checks passing: shard placement, node/zone loss availability, autoscale planning, rebalance checkpoints, Kubernetes operator reconciliation, quorum safety, HTTP sharding, active-active convergence, CRDT field-state behavior, and a deterministic 100M capacity envelope. Real 10M/50M/100M latency and recall claims still require strict remote service artifacts. | `benchmarks/cluster_autoscale_results.json`, `benchmarks/CLUSTER_AUTOSCALE.md` | `python benchmarks/cluster_autoscale_report.py --output benchmarks/cluster_autoscale_results.json --markdown-output benchmarks/CLUSTER_AUTOSCALE.md` |
| Dynamic memory policy | WaveMind reaches `precision@1 1.00` and `stale suppression 1.00`; Chroma static reaches `precision@1 0.57` and `stale suppression 0.00`. | `benchmarks/dynamic_memory_results.json` | `python benchmarks/dynamic_memory_benchmark.py --engines wavemind chroma --memories 200 --output benchmarks/dynamic_memory_results.json` |
| LoCoMo evidence retrieval | WaveMind sentence reaches `evidence_recall@5 0.547`; Chroma sentence reaches `0.407`; Qdrant sentence reaches `0.409`. | `benchmarks/locomo_sentence_evidence_results.json` | `python benchmarks/locomo_memory_benchmark.py --engines wavemind-sentence chroma-sentence qdrant-sentence --output benchmarks/locomo_sentence_evidence_results.json` |
| LongMemEval evidence retrieval | WaveMind reaches `evidence_recall@5 0.782`; Chroma static reaches `0.518`; Qdrant static reaches `0.520`. | `benchmarks/longmemeval_evidence_results.json` | `python benchmarks/longmemeval_memory_benchmark.py --engines wavemind chroma qdrant --output benchmarks/longmemeval_evidence_results.json` |
| LongMemEval answer smoke | With local Ollama `qwen2.5:1.5b`, WaveMind reaches `token_f1 0.333`; Chroma static and Qdrant static reach `0.170`. | `benchmarks/longmemeval_answer_qwen25_1_5b_50_results.json` | `python benchmarks/longmemeval_answer_benchmark.py --dataset benchmarks/data/longmemeval_s_cleaned.json --provider ollama --model qwen2.5:1.5b --engines wavemind chroma qdrant --limit-queries 50 --output benchmarks/longmemeval_answer_qwen25_1_5b_50_results.json` |
| BEIR SciFact retrieval | WaveMind reaches `nDCG@10 0.354`; Chroma reaches `0.350`; Qdrant reaches `0.354`. Chroma is much faster on this static retrieval path. | `benchmarks/open_retrieval_scifact_results.json` | `python benchmarks/open_retrieval_benchmark.py --dataset scifact --engines wavemind chroma qdrant --output benchmarks/open_retrieval_scifact_results.json` |
| NoMIRACL Russian retrieval | WaveMind reaches `nDCG@10 0.434`; Chroma reaches `0.435`; Qdrant reaches `0.433`. Chroma is faster. | `benchmarks/nomiracl_russian_results.json` | `python benchmarks/nomiracl_russian_benchmark.py --engines wavemind chroma qdrant --output benchmarks/nomiracl_russian_results.json` |
| Production index profile | At 50000 vectors, persisted FAISS and Qdrant service both reach `recall@10 1.000`; pgvector with `ef_search=400` reaches `0.811`. | `benchmarks/production_index_profile_results.json` | `docker compose -f examples/production-index-profile/docker-compose.yml run --rm benchmark` |
| Production pgvector tuning profile | At 50000 vectors on real PostgreSQL/pgvector, baseline HNSW reaches `recall@10 0.834`; exact mode reaches `1.000` with p99 `76.98 ms`; iterative HNSW reaches `0.970` with p99 `55.19 ms`; Qdrant service reaches `1.000` with p99 `17.84 ms`. | `benchmarks/production_pgvector_tuning_results.json` | `python benchmarks/ann_index_curve_benchmark.py --sizes 10000 50000 --dim 128 --queries 100 --top-k 10 --engines qdrant-service pgvector pgvector-exact pgvector-iterative --output benchmarks/production_pgvector_tuning_results.json` |
| Production load profile | At 100000 vectors, Qdrant service reaches `recall@10 1.000`, avg `10.28 ms`, p99 `21.26 ms`, passes the SLO gate (`recall >= 0.95`, `p99 <= 100 ms`, `100 qps`, 3 replicas, HPA max 24), and estimates `$1.39` per 1M queries with `$365.02` monthly target cost. At 1M vectors over 100 queries, persisted FAISS reaches `recall@10 1.000`, avg `39.12 ms`, p99 `57.71 ms`, and estimates `$4.17` per 1M queries with 6 replicas for 100 qps. The older tuned Qdrant 1M load profile reaches `0.984`, avg `82.57 ms`, p99 `137.86 ms`; the newer streaming 1M Qdrant profile closes that p99 gap after safe upsert chunking, wait-after-build, and warmup. | `benchmarks/production_load_qdrant_100k_tuned_results.json`, `benchmarks/production_load_faiss_1m_results.json`, `benchmarks/production_load_qdrant_1m_tuned_results.json`, `benchmarks/production_streaming_load_qdrant_1m_tuned_results.json` | `python benchmarks/production_load_benchmark.py --sizes 1000000 --engines faiss-persisted` |
| Production streaming load runner | Memory-bounded runner for 10M/50M/100M profiles. Strict checked results include 50M FAISS IVF-PQ at recall@10 `0.9705`, p99 `73.11 ms`; single-service 10M Qdrant at `0.975`, `43.27 ms`; four-service 10M sharded Qdrant at `0.9925`, `71.28 ms`; and four-service 10M pgvector at `0.975`, `87.66 ms`. The pgvector run uses exact 2.5M-per-shard placement, zero misplaced rows, namespace routing, and the `ivfflat-fine-production` profile. The checked-in 100M sharded Qdrant plan remains a resumable service-run contract, not a completed benchmark. | `benchmarks/production_streaming_load_qdrant_smoke_results.json`, `benchmarks/production_streaming_load_ivfpq_50m_results.json`, `benchmarks/production_streaming_load_qdrant_10m_results.json`, `benchmarks/production_streaming_load_qdrant_sharded_10m_results.json`, `benchmarks/production_streaming_load_pgvector_10m_results.json`, `benchmarks/production_streaming_load_qdrant_sharded_100m_plan.json` | `.github/workflows/production-streaming-load.yml`; `python benchmarks/production_streaming_load_benchmark.py --plan-only --runner-storage-root state/production-runs --disk-free-gb 0 --sizes 10000000 --engines pgvector-service --output benchmarks/production_streaming_load_pgvector_10m_plan.json --planned-result-output benchmarks/production_streaming_load_pgvector_10m_results.json`; `gh workflow run production-streaming-load.yml -f engine=pgvector-service -f size=10000000 -f provision_pgvector_shards=true -f pgvector_shard_count=4 -f pgvector_profile=ivfflat-fine-production` |

Supporting scale-admission artifacts preserve the intermediate and resumable
contracts used to reach those strict results:
`benchmarks/production_streaming_load_qdrant_1m_results.json`,
`benchmarks/production_streaming_load_qdrant_sharded_smoke_results.json`,
`benchmarks/production_streaming_load_qdrant_10m_plan.json`,
`benchmarks/production_streaming_load_qdrant_sharded_10m_plan.json`,
`benchmarks/production_streaming_load_pgvector_smoke_results.json`, and
`benchmarks/production_streaming_load_50m_plan.json`.
They include the two-service sharded Qdrant smoke that preceded the four-service
10M run and the completed pgvector 10M candidate-index SLO.
The local sharded-service admission path starts with
`docker compose -f examples/qdrant-sharded-streaming/docker-compose.yml up -d`
before running the corresponding streaming profile.

Rebuild the checked plans without allocating the target vector payload:

```bash
python benchmarks/production_streaming_load_benchmark.py --plan-only --runner-storage-root state/production-runs --disk-free-gb 0 --sizes 10000000 --engines qdrant-service --planned-result-output benchmarks/production_streaming_load_qdrant_10m_results.json
python benchmarks/production_streaming_load_benchmark.py --plan-only --runner-storage-root state/production-runs --disk-free-gb 0 --sizes 10000000 --engines qdrant-sharded-service --planned-result-output benchmarks/production_streaming_load_qdrant_sharded_10m_results.json
python benchmarks/production_streaming_load_benchmark.py --plan-only --runner-storage-root state/production-runs --disk-free-gb 0 --sizes 10000000 --engines pgvector-service --planned-result-output benchmarks/production_streaming_load_pgvector_10m_results.json
```
| Production scale run planner | One operator command now plans the next large-N benchmark wave across 10M Qdrant, 10M sharded Qdrant, 10M pgvector, 50M FAISS IVF-PQ, and 100M sharded Qdrant. The checked-in plan totals `180000000` target memories and includes required env, command env examples, runner storage root, checkpoint paths, output artifacts, local runner storage, application storage, SLO capacity envelopes, monthly budget, cost per 1M memories, compute cost per 1M queries, plan-only Pareto frontier, and blockers. It is a preflight contract, not completed latency/recall evidence. | `benchmarks/production_scale_run_plan.json` | `wavemind production-scale-plan --disk-free-gb 0 --runner-storage-root state/production-runs --write-artifact --output benchmarks/production_scale_run_plan.json --json` |
| Cost-efficiency frontier | The generated cost report ranks `20` measured production-load rows and `5` planned large-N rows by recall, p99, SLO, compute cost, monthly cost, and memory count. The current measured frontier includes the tuned 1M Qdrant streaming profile, 1M/10M FAISS IVF-PQ streaming profiles, and the 100k Qdrant profile; the planned frontier includes `faiss-ivfpq-50m` and `qdrant-sharded-100m`. Planned rows are cost/capacity contracts only and do not unlock production latency or recall claims. | `benchmarks/cost_efficiency_results.json`, `benchmarks/COST_EFFICIENCY.md` | `python benchmarks/cost_efficiency_leaderboard.py --output benchmarks/cost_efficiency_results.json --markdown-output benchmarks/COST_EFFICIENCY.md` |
| Scale readiness profile | Deterministic 1M-memory simulation: namespace placement survives node loss and zone loss at `1.000`; cluster autoscale planning maps a 10M target to `50` required nodes, `46` additional nodes, target max node load `678711`, and headroom pass `true`; Kubernetes `StatefulSet`, `HorizontalPodAutoscaler`, repair `CronJob`, and operator-style `WaveMindCluster` reconciliation are generated for `4096` namespaces; the capacity-aware operator maps a 10M target to `34` StatefulSet/HPA replicas with target max node load `678711`, status phase `Ready`, `MemoryOSReady=true`, Redis required/configured, and an operator-rendered Memory OS CronJob that calls `/memory-os/plan` before `/memory-os/run`, applies planned distributed-lock requirements, and blocks mutation when Redis is missing; Knative/KEDA serverless planning has `scale_to_zero=true`, external Postgres/Qdrant/Redis wiring, and a valid KEDA Deployment target; the serverless operational profile checks `3200` RPS, `4` required replicas, `256000` burst RPS, `1220 ms` modeled cold-start total, `$81.76` modeled monthly compute cost, and loopback API-replica observed telemetry with `37328.613` estimated max-scale RPS, `4` measured replicas, p99 `17.039 ms`, error rate `0.0`, and `observed_slo_pass=true`; service-mode distributed sharding, real HTTP transport, sustained HTTP cluster load p99 `389.98 ms`, batch write request reduction `24 -> 4`, batch forget+tombstone request reduction `24 -> 8`, batch query request reduction `8 -> 3`, failover batch request reduction `8 -> 2`, anti-entropy repair, Redis/shared caches, explicit useful/not-useful recall feedback, batch recall feedback handler p99 `1.209 ms`, Memory OS adaptive prewarm, transition-learned predictive prefetch, execution-plan safety (`safe_to_run=true`, Redis + lock env, singleton mutating tasks, worker-pool `cache-prewarm`), policy manifest decisions for prefetch/priority/forgetting/consolidation/scale/coordination, forgetting/consolidation plus production architecture advice, API cache invalidation on remember/feedback/feedback-batch/forget, cursor-based active-active delta sync, sustained active-active sync across 3 regions / 3 namespaces / 18 writes / 90 pair syncs with convergence `1.000`, delete suppression `1.000`, success `1.000`, and final no-op imports `0`, field-only hotness sync, actor-watermarked CRDT field-state merge with health/missing/lag diagnostics, object-store DR drills, SQLite point-in-time recovery journal full replay plus checkpoint replay, image/audio/video/3D/table/event/graph structured payloads, cross-modal target-modality precision@1 `1.000`, persisted vector rate `1.000`, precomputed external-vector precision@1 `1.000`, external encoder contract target/global precision@1 `1.000` / `1.000`, normalized finite vector rate `1.000`, provenance rate `1.000`, separation margin `0.811`, temporal event precision@1 `1.000`, temporal persistence `1.000`, temporal provenance `1.000`, knowledge-graph direct/two-hop/three-hop/predicate precision `1/1/1/1`, graph path precision@1 `1.000`, graph persistence `1.000`, graph provenance `1.000`, and the 100M weighted rendezvous capacity envelope all remain covered by the same artifact, including distinct replica rate `1.000`, zone-spread rate `1.000`, replica-load skew `1.094`, and a 128-to-160-node scale-out movement audit with target replica skew `1.082`. | `benchmarks/scale_readiness_results.json` | `python benchmarks/scale_readiness_benchmark.py --simulated-memories 1000000 --output benchmarks/scale_readiness_results.json` |
| Postgres PITR runbook/preflight | Secret-safe database-native Postgres PITR plan: WAL archiving, streaming `pg_basebackup`, restore target config, `recovery.signal`, replay verification, promotion, 72-hour retention contract, and missing-env reporting without embedding DSNs or secrets. This is a runbook/preflight artifact, not a completed managed-Postgres restore drill. | `benchmarks/postgres_pitr_plan.json` | `python benchmarks/postgres_pitr_plan.py --output benchmarks/postgres_pitr_plan.json`; `wavemind postgres-pitr-plan --json` |
| Local HTTP cluster smoke | 4 real localhost API nodes with isolated SQLite stores, RF=3, `read_fanout=1`, workers `4`: success `1.000`, failover hit `1.000`, delete suppression `1.000`, repaired replicas `1`, health `true`, degraded nodes `0`, p99 `348.83 ms`, SLO `true`. | `benchmarks/local_http_cluster_smoke_results.json` | `python benchmarks/local_http_cluster_smoke.py --nodes 4 --replication-factor 3 --read-fanout 1 --namespace-count 4 --memories-per-namespace 2 --workers 4 --timeout 3 --fail-on-slo --output benchmarks/local_http_cluster_smoke_results.json` |
| External HTTP active-active loopback | 3 real localhost API regions passed into the external URL-based active-active runner, 16 namespaces: convergence `1.000`, delete suppression `1.000`, success `1.000`, final no-op imports `0`, p99 `349.21 ms`, SLO `true`. This proves the external-runner transport contract without claiming remote Kubernetes/serverless evidence. | `benchmarks/external_http_active_active_loopback_results.json` | `python benchmarks/external_http_active_active_loopback.py --regions 3 --replicas-per-region 3 --namespace-count 16 --timeout 3 --fail-on-slo --output benchmarks/external_http_active_active_loopback_results.json` |
| External HTTP cluster load runner | Runner-ready benchmark for real WaveMind API-node deployments. It accepts repeated `--node id=https://host` arguments or a repeatable `--nodes-file deploy/cluster/external-http-cluster.sample.json` manifest and checks quorum writes, normal queries, simulated node failover queries, missing-replica repair, replicated forget, delete suppression, p99, and `slo_pass`. `.github/workflows/external-http-cluster-load.yml` runs the same profile from GitHub Actions using newline/comma/semicolon-separated node input or `nodes_manifest_json`, uploads the artifact, and can commit refreshed results when `commit_results=true`. No fake remote result is checked in; the production gate tracks a missing external result as non-gating evidence until a real deployment exists. | optional `benchmarks/http_cluster_load_results.json` | `python benchmarks/http_cluster_load_benchmark.py --nodes-file deploy/cluster/external-http-cluster.sample.json --replication-factor 3 --read-quorum 1 --read-fanout 1 --fail-on-slo` |
| External HTTP active-active runner | Runner-ready benchmark for real WaveMind API regions. It accepts repeated `--region id=https://host` arguments or a repeatable `--regions-file deploy/cluster/external-http-active-active.sample.json` manifest and checks namespace-delta export/import, convergence, delete propagation, cursor idempotency, final no-op sync, p99, and `slo_pass`. `.github/workflows/external-http-active-active.yml` runs the same profile from GitHub Actions using newline/comma/semicolon-separated region input or `regions_manifest_json`, uploads the artifact, and can commit refreshed results when `commit_results=true`. No fake remote region result is checked in; the production gate tracks a missing external result as non-gating evidence until a real regional deployment exists. | optional `benchmarks/external_http_active_active_results.json` | `python benchmarks/local_http_active_active_smoke.py --regions-file deploy/cluster/external-http-active-active.sample.json --namespace-count 16 --fail-on-slo --output benchmarks/external_http_active_active_results.json` |
| Production readiness gate | Current WaveMind core gate score is `1.000`: `39/39` criteria pass, `0` require action, `0` fail. Live Zep competitor evidence is tracked separately and remains pending until a real service is configured. | `benchmarks/production_readiness_results.json`, `benchmarks/PRODUCTION_READINESS.md` | `python benchmarks/production_readiness_gate.py --output benchmarks/production_readiness_results.json --markdown-output benchmarks/PRODUCTION_READINESS.md` |
| Strict production evidence gate | Hard claim boundary for remote service-node load, external active-active regions, managed/serverless telemetry, 10M Qdrant/pgvector service runs, 50M FAISS, and 100M remote service-backed load. It is allowed to be `action_required` while core readiness is green, because local loopback evidence must not unlock remote production claims. | `benchmarks/production_evidence_results.json`, `benchmarks/PRODUCTION_EVIDENCE.md` | `wavemind production-evidence --strict`; `python benchmarks/production_evidence_gate.py --output benchmarks/production_evidence_results.json --markdown-output benchmarks/PRODUCTION_EVIDENCE.md` |
| Production evidence preflight | Operator prerequisite check for strict production evidence jobs. It verifies remote endpoint env, service index env, FAISS storage paths, plan artifacts, disk headroom, and exact output-producing commands before expensive remote/large-N jobs are launched. | `benchmarks/production_evidence_preflight_results.json`, `benchmarks/PRODUCTION_EVIDENCE_PREFLIGHT.md` | `wavemind production-evidence-preflight --write-artifacts`; `wavemind production-evidence-preflight --fail-on-action-required` |
| Production evidence environment contract | Secret-safe operator map for strict production evidence variables. It joins required/recommended env, GitHub Actions secret names, workflow inputs, artifacts, claims, and `.env.example` placeholders without serializing credential values. | `benchmarks/production_evidence_env_contract.json`, `benchmarks/PRODUCTION_EVIDENCE_ENV.md`, `deploy/cluster/production-evidence.env.example` | `wavemind production-evidence-env --write-artifacts`; `wavemind production-evidence-env --fail-on-missing` |
| Production evidence dispatch plan | Secret-safe GitHub Actions launch contract for strict production evidence. It joins the strict evidence gate, preflight state, workflow names, required env/secrets, safe `commit_results=false` launch commands, publish commands, download commands, and ingest commands. This is a launch/review contract, not a passing benchmark. | `benchmarks/production_evidence_dispatch_results.json`, `benchmarks/PRODUCTION_EVIDENCE_DISPATCH.md` | `wavemind production-evidence-dispatch --write-artifacts`; `wavemind production-evidence-dispatch --fail-on-action-required` |
| Strict evidence readiness runbook | Operator checklist for the remaining strict evidence gaps. It joins strict evidence, preflight, dispatch, scale plans, scale gaps, release claims, and leaderboard freshness into one machine-readable report with blocker category, locked claim, safe dispatch command, download command, ingest command, strict validation command, and refresh command for every remote/10M/50M/100M requirement. It does not unlock claims by itself. | `benchmarks/strict_evidence_readiness_results.json`, `benchmarks/STRICT_EVIDENCE_READINESS.md` | `python benchmarks/strict_evidence_readiness_report.py --output benchmarks/strict_evidence_readiness_results.json --markdown-output benchmarks/STRICT_EVIDENCE_READINESS.md` |
| Production evidence ingest gate | Maintainer review path for downloaded remote/large-N artifacts. It validates remote HTTP cluster, active-active, managed/serverless, Qdrant, sharded Qdrant, pgvector, FAISS IVF-PQ, and 100M result files through the same strict production evidence rules before copying them into the repo and refreshing reports. It rejects loopback/local active-active artifacts even if they are renamed to the strict output filename. | `wavemind/production_evidence_ingest.py`, `benchmarks/ingest_production_evidence_artifacts.py`, `tests/test_production_evidence_ingest.py` | `wavemind ingest-production-evidence --artifact-dir state/large-run --refresh`; `python benchmarks/ingest_production_evidence_artifacts.py --artifact-dir state/large-run --dry-run` |
| Production evidence bundle | Operator-facing status contract that combines strict evidence, preflight, readiness, artifact audit, claim boundaries, and exact next actions. | `benchmarks/production_evidence_bundle_results.json`, `benchmarks/PRODUCTION_EVIDENCE_BUNDLE.md` | `wavemind production-evidence-bundle --write-artifacts`; `wavemind production-evidence-bundle --strict` |
| Release claims contract | Compact release-facing claim manifest for GitHub Releases and launch posts. It separates `core_release_ready` library claims from strict remote, managed-serverless, 50M, and 100M production claims that remain locked until real evidence artifacts pass. | `benchmarks/release_claims_results.json`, `benchmarks/RELEASE_CLAIMS.md` | `wavemind release-claims --write-artifacts --fail-on-blocked`; `wavemind release-claims --strict` |
| Scale gap matrix | Large-N proof gap contract that joins the 10M/50M/100M run plan with strict evidence, preflight state, missing env, exact commands, and nearest checked baselines. It currently shows `0/5` strict large-N profiles complete, `180000000` planned target memories, and 10M as the nearest checked baseline. | `benchmarks/scale_gap_results.json`, `benchmarks/SCALE_GAP.md` | `wavemind scale-gap --write-artifacts`; `wavemind scale-gap --fail-on-action-required` |
| Production admission gate | Deployment-facing gate for a requested memory count and engine. It maps the deployment request to the required strict evidence profile and fails with `--fail-on-blocked` until that artifact passes. Plan-only output can guide operators, but it never admits production traffic. The same check can protect API startup with `wavemind serve --require-production-admission`, so blocked 10M/50M/100M deployments exit before binding a port. | `benchmarks/production_admission_results.json`, `benchmarks/PRODUCTION_ADMISSION.md` | `wavemind production-admission --target-memories 100000000 --engine qdrant-sharded-service --fail-on-blocked`; `wavemind serve --require-production-admission --production-target-memories 100000000 --production-engine qdrant-sharded-service` |
| Active-active admission gate | Deployment-facing gate for remote multi-region active-active rollout. It joins strict evidence and preflight state for `external_http_active_active`, publishes missing env/artifact blockers, and never lets local/loopback active-active evidence unlock the remote production claim. | `benchmarks/active_active_admission_results.json`, `benchmarks/ACTIVE_ACTIVE_ADMISSION.md` | `wavemind active-active-admission --allow-plan-only --write-artifacts`; `wavemind active-active-admission --fail-on-blocked` |
| Serverless admission gate | Deployment-facing gate for managed/serverless rollout. It joins strict evidence and preflight state for `serverless_remote_telemetry`, publishes missing env/artifact blockers, and never lets loopback telemetry unlock the hosted/serverless production claim. | `benchmarks/serverless_admission_results.json`, `benchmarks/SERVERLESS_ADMISSION.md` | `wavemind serverless-admission --allow-plan-only --write-artifacts`; `wavemind serverless-admission --fail-on-blocked` |
| External multimodal evidence runner | Runner-ready path from a real external multimodal manifest to the artifact required by admission. The manifest must include externally computed shared-space vectors, precomputed query vectors, `s3://` asset URIs, verified sha256/byte-size metadata, encode p95 values, and target relevance labels. | `benchmarks/multimodal_external_encoder_results.json` when a real external manifest is supplied | `wavemind multimodal-external-evidence --manifest external_multimodal_manifest.json --write-artifacts --output benchmarks/multimodal_external_encoder_results.json`; no checked production artifact is included without real external evidence. |
| Multimodal admission gate | Deployment-facing gate for production multimodal memory claims. It requires the structured-memory contract plus real external image/audio/video/3D encoder evidence, object-store-backed assets, vector persistence, provenance, p99 query latency, encode p95, and error-rate thresholds. | `benchmarks/multimodal_admission_results.json`, `benchmarks/MULTIMODAL_ADMISSION.md` | `wavemind multimodal-admission --allow-plan-only --write-artifacts`; `wavemind multimodal-admission --fail-on-blocked` |
| Memory OS canary | Staging proof that representative query-audit traffic can drive Memory OS hot-query prewarm, predictive prefetch, priority learning, TTL cleanup, and scheduler admission. It is a worker/admission contract check, not remote production evidence. | `benchmarks/memory_os_canary_results.json`, `benchmarks/MEMORY_OS_CANARY.md` | `wavemind memory-os-canary --target-memories 100000 --namespace-count 64 --deployment staging --write-artifacts --fail-on-action-required` |
| Memory OS policy evolution | Multi-cycle Memory OS proof that repeated policy gaps are carried forward into later scheduler plans. Current checked artifact passes `12/12` checks with `3` cycles, decision coverage `1.000`, `2` repeated-required cycles, `4` history suggestions, `2` escalation actions, scheduler escalation `scale-policy`, `16` prewarm warms, `30` predictive-prefetch warms, and `14` priority predictions. | `benchmarks/memory_os_policy_evolution_results.json`, `benchmarks/MEMORY_OS_POLICY_EVOLUTION.md` | `wavemind memory-os-evolution --cycles 3 --write-artifacts --fail-on-action-required` |
| Memory OS policy bundle | Operator-facing runtime policy manifest generated from canary, policy-evolution, and admission artifacts. It emits enabled task ids, required Redis/lock env, observability metrics, Kubernetes/CronJob patch data, and explicit staging/production promotion gates. Current checked status is `staging_ready`, with production still locked while admission is `plan_only`. | `benchmarks/memory_os_policy_bundle_results.json`, `benchmarks/MEMORY_OS_POLICY_BUNDLE.md` | `wavemind memory-os-policy-bundle --write-artifacts --fail-on-action-required` |
| Memory OS admission gate | Deployment-facing gate for adaptive workers. It checks hot-query audit signal, Redis/shared-cache wiring, distributed lock wiring, singleton/idempotent state mutation, policy coverage, and strict architecture boundaries before Memory OS workers become production automation. | `benchmarks/memory_os_admission_results.json`, `benchmarks/MEMORY_OS_ADMISSION.md` | `wavemind memory-os-admission --target-memories 10000000 --namespace-count 4096 --deployment production --allow-plan-only --write-artifacts`; `wavemind memory-os-admission --target-memories 10000000 --namespace-count 4096 --deployment production --fail-on-blocked` |
| VectorDBBench custom dataset | Runner-ready custom dataset export for official VectorDBBench flows: `train.parquet`, `test.parquet`, `neighbors.parquet`, and `scalar_labels.parquet` with 10000 vectors, 100 queries, 128 dimensions, and cosine neighbors. | `benchmarks/vectordbbench_dataset_manifest.json` | `python benchmarks/vectordbbench_dataset.py --vectors 10000 --queries 100 --dim 128 --top-k 10 --output-dir state/vectordbbench-wavemind --manifest benchmarks/vectordbbench_dataset_manifest.json` |
| Memory competitor adapter profile | WaveMind reaches `precision@1 0.80`, `precision@3 1.00`, stale suppression `1.00`; Mem0 runs locally with Qdrant + FastEmbed and reaches `0.80`, `1.00`, stale suppression `0.60`; LangGraph persistent SQLite reaches `0.80`, `1.00`, stale suppression `1.00`; GraphRAG-style static graph reaches `1.00`, `1.00`, stale suppression `1.00` on this small static graph scenario; Zep has live adapter paths for the current `zep-cloud` Graph API and legacy/OSS-compatible `zep-python`, and remains skipped until `ZEP_API_URL` or `ZEP_API_KEY` points at a real service. | `benchmarks/memory_competitor_results.json` | `python benchmarks/memory_competitor_benchmark.py --engines wavemind mem0 zep langgraph graphrag` |

The generated matrix view is in `benchmarks/BENCHMARK_REPORT.md`; the compact
leaderboard view is in `benchmarks/BENCHMARK_LEADERBOARD.md`.
The agent-impact view is in `benchmarks/AGENT_IMPACT.md`.
The Memory OS intelligence view is in `benchmarks/MEMORY_OS_INTELLIGENCE.md`.
The cluster autoscale view is in `benchmarks/CLUSTER_AUTOSCALE.md`.
The production readiness gate is in `benchmarks/PRODUCTION_READINESS.md`.
The strict production evidence gate is in `benchmarks/PRODUCTION_EVIDENCE.md`.
The strict evidence dispatch plan is in
`benchmarks/PRODUCTION_EVIDENCE_DISPATCH.md`.
The strict evidence environment contract is in
`benchmarks/PRODUCTION_EVIDENCE_ENV.md`.
The strict evidence readiness runbook is in
`benchmarks/STRICT_EVIDENCE_READINESS.md`.
The combined operator evidence bundle is in
`benchmarks/PRODUCTION_EVIDENCE_BUNDLE.md`.
The release-safe public claim manifest is in `benchmarks/RELEASE_CLAIMS.md`.
The large-N scale gap matrix is in `benchmarks/SCALE_GAP.md`.
The cost-efficiency frontier is in `benchmarks/COST_EFFICIENCY.md`.
`benchmarks/benchmark_artifact_audit.json` records the latest freshness and
synchronization check for the generated benchmark artifacts.
`docs/data/leaderboard-status.json` is the compact machine-readable public
status contract for the GitHub Pages dashboard: publication workflow, Pages
deployment contract, publishability, artifact freshness, production readiness,
strict production claim boundaries, production evidence dispatch state,
production evidence bundle status, and cost-efficiency frontier status. It
also exposes agent-quality lift and the active Memory OS policy manifest so
external dashboards can track behavioral quality and self-management decisions
without parsing Markdown.
The weekly leaderboard workflow refreshes these artifacts, uploads them for
maintainer review, and deploys `docs/benchmark-dashboard.html` plus the
machine-readable JSON evidence as a GitHub Pages living leaderboard instead of
pushing scheduled bot commits to `main`. The `publication_contract` section
records the cron schedule, expected refresh profile, Pages actions, artifact
review policy, and claim policy in JSON.
`full-check` plus the release workflow block stale or unsynchronized public
benchmark artifacts with `benchmarks/validate_benchmark_artifacts.py
--max-age-days 8`. Remote
serverless telemetry can be refreshed through
`.github/workflows/serverless-observed-telemetry.yml`; when a real remote
artifact is checked in, scale-readiness prefers it over loopback telemetry.
Large-N streaming service runs can be executed through
`.github/workflows/production-streaming-load.yml`, which uploads checkpoint and
result artifacts and can commit refreshed benchmark/evidence reports after a
real 10M/50M/100M run. The safer maintainer flow is to keep
`commit_results=false`, download the `production-streaming-load-results`
artifact, and run
`python benchmarks/ingest_production_streaming_artifact.py --artifact-dir state/large-run --refresh`.
That gate only accepts strict large-N result filenames, the expected engine and
vector count, recall at or above `0.95`, p99 at or below `100 ms`, and valid
SLO/cost rows before it refreshes the public leaderboard and evidence reports.

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
- that the 10M/50M compressed FAISS IVF-PQ profiles are exact-neighbor recall.
  They are target-recall profiles over compressed persisted FAISS indexes;
- that the Qdrant 1M streaming path is safe without warmup. The cold run misses
  the p99 SLO; the checked-in passing result uses safe upsert chunks,
  wait-after-build, and 100 warmup queries;
- that the completed pgvector 10M candidate-index SLO proves PostgreSQL HA. The
  four service processes ran on one ephemeral GitHub host; independent-node
  failover and managed PostgreSQL recovery remain separate evidence;
- that Qdrant is safe at 1M without warmup. The older tuned 1M Qdrant load
  profile reaches `recall@10 0.984` over 100 queries but p99 is still
  `137.86 ms`; the passing streaming result uses safe upsert chunks,
  wait-after-build, and 100 warmup queries.

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
  run, recall reaches 1.000 over 100 queries with p99 57.71 ms. The older tuned
  1M Qdrant load run is recall-credible but above the p99 SLO; the newer
  streaming 1M Qdrant run passes with recall@10 1.000 and p99 26.37 ms after
  chunking and warmup.

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
  closes the 1M recall/p99 gate with recall@10 1.000 and p99 57.71 ms. The
  streaming 1M Qdrant profile now also passes with recall@10 1.000 and p99
  26.37 ms after safe chunks, wait-after-build, and warmup.

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
pgvector iterative tuning recall@10: 0.970, p99 55.19 ms
pgvector exact recall@10: 1.000, p99 76.98 ms

pgvector now has a measured tuning path, but still needs 100k/1M load proof.
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

1M Qdrant service streaming tuned:
recall@10 1.000
avg 16.16 ms
p99 26.37 ms

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

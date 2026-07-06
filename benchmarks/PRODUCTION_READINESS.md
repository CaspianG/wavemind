# WaveMind Production Readiness Gate

This gate is generated from checked-in benchmark artifacts. It is a readiness
verdict, not a marketing claim.

| metric | value |
|---|---:|
| overall status | `pass` |
| readiness score | `1.000` |
| passed criteria | `20` |
| action required | `0` |
| failed criteria | `0` |
| total criteria | `20` |

| criterion | status | evidence | next step |
|---|---|---|---|
| Checked-in benchmark artifacts are synchronized | `pass` | audit status pass, generated_at 2026-07-06T07:05:37Z | Keep the benchmark refresh workflow green and block stale artifacts before release. |
| 100k service-backed load profile passes SLO and cost gate | `pass` | recall 1.0, p99 21.25629998045042 ms, cost $1.39/1M queries | Keep the 100k profile green while adding persisted FAISS and pgvector service runs. |
| 1M service-backed load profile meets recall and p99 SLO | `pass` | WaveMind faiss-persisted: recall 1.0, p99 57.71490000188351 ms, SLO scale_required | Keep FAISS 1M green in CI-capable benchmark environments and continue tuning Qdrant/pgvector service paths. |
| 1M load result has enough query depth for a production claim | `pass` | current tuned 1M profile uses 100 queries | Keep 100+ query depth for all checked-in 1M production profiles. |
| Namespace placement survives node and zone loss | `pass` | node loss 1.0, zone loss 1.0, namespaces 4096 | Validate the same placement under live multi-node service load. |
| Kubernetes operator bundle includes HPA and repair job | `pass` | CRD True, HPA True, repair True | Run a real Kubernetes smoke deploy and collect HPA behavior under load. |
| Serverless plan externalizes state and validates KEDA target | `pass` | Postgres True, Qdrant True, Redis True | Run service-backed KEDA/Knative load tests instead of manifest-only checks. |
| Hot cache and query-audit prewarm work | `pass` | hit rate 0.92, prewarm hit True, p99 0.002600019797682762 ms | Keep local cache prewarm green while Redis carries multi-worker production cache evidence. |
| Query-vector cache avoids repeated encoder work | `pass` | local encode calls 1, local hit rate 0.995, Redis shared True, Redis encode calls 1 | Add service-mode vector-cache load evidence with a sentence-transformer encoder. |
| Redis-compatible shared cache and Memory OS prewarm work | `pass` | shared True, prewarm hit True, Memory OS warmed 2, Memory OS hit True, invalidation True | Keep the real Redis multi-process API load workflow green. |
| API cache does not serve stale memory after mutations | `pass` | cached True, remember invalidation True, remember stale prevented True, forget invalidation True, forget stale prevented True | Keep the real Redis multi-process API load workflow green. |
| Real Redis multi-process API load passes SLO | `pass` | workflow True, workers 2, success_rate 1.0, p99 71.7594539700039 ms, stale prevented True | Refresh redis_api_load_results.json from the CI artifact on every release candidate. |
| Memory OS worker prewarms, consolidates, and cleans up | `pass` | hot queries 2, prewarm 2, expired 1, concepts 1, priority predictions 2, forgetting demotions 3 | Keep usage-pattern priority prediction and adaptive forgetting green under Redis-backed service deployments. |
| Distributed sharding repairs replicas and tombstones stale deletes | `pass` | repair 1, tombstone deleted 1, anti-entropy repaired 1 | Keep the algorithm profile and real HTTP shard profile in sync. |
| HTTP shard transport handles failover, repair, and tombstones | `pass` | proxy bypass True, failover True, repair 1, tombstone deleted 1, concurrent hit rate 1.0 | Extend the same HTTP shard profile to remote service nodes and sustained load. |
| Runtime replica quorum survives node loss | `pass` | recall after loss True, repair copied 1, p99 1.4322000206448138 ms, concurrent hit rate 1.0 | Extend the same replicated runtime profile to remote service nodes and sustained load. |
| Active-active sync and field-state CRDT converge | `pass` | delta sync True, CRDT idempotent True | Run active-active sync against independent persistent stores. |
| Snapshots, archives, offsite mirror, and object-store DR verify | `pass` | archive True, object-store DR True, restored files 3 | Repeat the drill with real S3-compatible storage and larger SQLite/Postgres dumps. |
| Structured and multimodal payload retrieval works | `pass` | modalities image, audio, table, event, precision@1 1.0 | Add real CLIP/audio embedding backends and larger multimodal retrieval tests. |
| 10M-vector production load profile passes recall, p99, and cost gate | `pass` | WaveMind faiss-ivfpq-persisted streaming: recall 0.99, p99 60.12930005090311 ms, cost valid_slo | Keep the 10M compressed FAISS IVF-PQ profile green and repeat with Qdrant/pgvector service profiles when larger service hardware is available. |

## Non-Gating External Evidence

External competitor services are tracked separately from WaveMind production readiness.
Missing commercial API credentials should not turn a core WaveMind readiness gate red.

| evidence | status | result | next step |
|---|---|---|---|
| Mem0, Zep, and LangGraph adapter evidence | `action_required` | skipped: Zep | Configure ZEP_API_URL or ZEP_API_KEY for a real Zep service and check in the live Zep adapter result. |

# WaveMind Production Readiness Gate

This gate is generated from checked-in benchmark artifacts. It is a readiness
verdict, not a marketing claim.

| metric | value |
|---|---:|
| overall status | `action_required` |
| readiness score | `0.933` |
| passed criteria | `14` |
| action required | `1` |
| failed criteria | `0` |
| total criteria | `15` |

| criterion | status | evidence | next step |
|---|---|---|---|
| Checked-in benchmark artifacts are synchronized | `pass` | audit status pass, generated_at 2026-07-06T02:17:10Z | Keep the benchmark refresh workflow green and block stale artifacts before release. |
| 100k service-backed load profile passes SLO and cost gate | `pass` | recall 1.0, p99 21.25629998045042 ms, cost $1.39/1M queries | Keep the 100k profile green while adding persisted FAISS and pgvector service runs. |
| 1M service-backed load profile meets recall and p99 SLO | `pass` | WaveMind faiss-persisted: recall 1.0, p99 57.71490000188351 ms, SLO scale_required | Keep FAISS 1M green in CI-capable benchmark environments and continue tuning Qdrant/pgvector service paths. |
| 1M load result has enough query depth for a production claim | `pass` | current tuned 1M profile uses 100 queries | Keep 100+ query depth for all checked-in 1M production profiles. |
| Namespace placement survives node and zone loss | `pass` | node loss 1.0, zone loss 1.0, namespaces 4096 | Validate the same placement under live multi-node service load. |
| Kubernetes operator bundle includes HPA and repair job | `pass` | CRD True, HPA True, repair True | Run a real Kubernetes smoke deploy and collect HPA behavior under load. |
| Serverless plan externalizes state and validates KEDA target | `pass` | Postgres True, Qdrant True, Redis True | Run service-backed KEDA/Knative load tests instead of manifest-only checks. |
| Hot cache and query-audit prewarm work | `pass` | hit rate 0.92, prewarm hit True, p99 0.0021739999951364553 ms | Back the cache with Redis in a service-mode benchmark. |
| Distributed sharding repairs replicas and tombstones stale deletes | `pass` | repair 1, tombstone deleted 1, anti-entropy repaired 1 | Run the same repair flow against real HTTP shard clients. |
| Runtime replica quorum survives node loss | `pass` | recall after loss True, repair copied 1, p99 0.7203679999960855 ms | Measure the same path under concurrent writes and reads. |
| Active-active sync and field-state CRDT converge | `pass` | delta sync True, CRDT idempotent True | Run active-active sync against independent persistent stores. |
| Snapshots, archives, offsite mirror, and object-store DR verify | `pass` | archive True, object-store DR True, restored files 3 | Repeat the drill with real S3-compatible storage and larger SQLite/Postgres dumps. |
| Structured and multimodal payload retrieval works | `pass` | modalities image, audio, table, event, precision@1 1.0 | Add real CLIP/audio embedding backends and larger multimodal retrieval tests. |
| Mem0, Zep, and LangGraph adapters have real configured results | `action_required` | skipped: Zep | Configure ZEP_API_URL or ZEP_API_KEY for a real Zep service and check in the live Zep adapter result. |
| 10M-vector production load profile passes recall, p99, and cost gate | `pass` | WaveMind faiss-ivfpq-persisted streaming: recall 0.99, p99 60.12930005090311 ms, cost valid_slo | Keep the 10M compressed FAISS IVF-PQ profile green and repeat with Qdrant/pgvector service profiles when larger service hardware is available. |

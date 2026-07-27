# Scale And Production

This guide contains the detailed deployment and evidence material moved from the project README.

## Scale Readiness

WaveMind now includes an explicit scale preflight:

```sh
wavemind scale-plan --target-memories 50000
```

For JSON output in CI or deployment checks:

```sh
wavemind --db ./state/wavemind.sqlite3 scale-plan --target-memories 50000 --json
```

To fail a deployment preflight when the plan needs action:

```sh
wavemind --db ./state/wavemind.sqlite3 scale-plan --target-memories 50000 --fail-on action_required --json
```

If you only want a plan for a future size without loading optional index
packages:

```sh
wavemind --index faiss scale-plan --current-memories 10000 --target-memories 50000 --json
```

The scale plan reports:

| field | meaning |
|---|---|
| `tier` | `small`, `medium`, `large-local`, `production-service`, or `million-plus`. |
| `status` | `ok`, `watch`, `action_required`, or `architecture_required`. |
| `recommended_index` | The candidate-index class to use before growth. |
| `warnings` | Why the current path may fail at the target size. |
| `actions` | Concrete setup, benchmark, rebuild, and index-health steps. |

The same scale preflight is available over HTTP:

```sh
curl "http://127.0.0.1:8000/scale-plan?target_memories=50000"
```

For large production benchmark runs, generate the run contract before starting
heavy ingest:

```sh
wavemind production-scale-plan --json
```

The checked-in deterministic artifact is:

```sh
wavemind production-scale-plan \
  --disk-free-gb 0 \
  --runner-storage-root state/production-runs \
  --write-artifact \
  --output benchmarks/production_scale_run_plan.json \
  --json
```

It covers the next large-N profiles without claiming unfinished benchmark
results:

| profile | engine | target memories | required env | output artifact |
|---|---|---:|---|---|
| `qdrant-10m` | `qdrant-service` | 10000000 | `WAVEMIND_QDRANT_URL` | `benchmarks/production_streaming_load_qdrant_10m_results.json` |
| `qdrant-sharded-10m` | `qdrant-sharded-service` | 10000000 | `WAVEMIND_QDRANT_URLS` | `benchmarks/production_streaming_load_qdrant_sharded_10m_results.json` |
| `pgvector-10m` | `pgvector-service` | 10000000 | `WAVEMIND_PGVECTOR_DSNS` | `benchmarks/production_streaming_load_pgvector_10m_results.json` |
| `faiss-ivfpq-50m` | `faiss-ivfpq-persisted` | 50000000 | `WAVEMIND_FAISS_IVFPQ_PATH` | `benchmarks/production_streaming_load_ivfpq_50m_results.json` |
| `qdrant-sharded-100m` | `qdrant-sharded-service` | 100000000 | `WAVEMIND_QDRANT_URLS` | `benchmarks/production_streaming_load_qdrant_sharded_100m_results.json` |

Each profile includes exact command, checkpoint path, runner storage root,
required environment, local runner storage estimate, application storage
estimate, SLO capacity envelope, and cost envelope. Use
`--runner-storage-root /mnt/fast/wavemind-runs` or
`WAVEMIND_PRODUCTION_RUNNER_ROOT` to keep checkpoints, resumable ingest state,
and local FAISS indexes off a small system disk. The cost envelope includes
target monthly budget, budget headroom, monthly cost per 1M memories, compute
cost per 1M queries, and machine-readable cost blockers. Override the profile
budget gates with `--monthly-budget-usd`, `--max-cost-per-1m-memories-usd`, and
`--max-compute-cost-per-1m-queries-usd` when planning a specific cluster. A
profile stays `action_required` until the service/index backend, runner storage
requirements, and cost gates are satisfied. The artifact is a preflight
contract, not latency or recall evidence.

The same artifact also computes a plan-only Pareto frontier across capacity,
recall target, p99 target, monthly cost per 1M memories, and compute cost per 1M
queries. This helps choose which large-N run should be prioritized first, while
keeping the claim boundary explicit: the frontier is planning guidance until the
matching output artifact is produced by a real run.

For a concrete operator checklist, use the architecture advisor:

```sh
wavemind advise --target-memories 2000000 --namespace-count 4096 --deployment production --replication-factor 3 --read-quorum 1 --read-fanout 1 --json
```

It combines live `stats()`, `scale-plan`, p99 targets, namespace count,
replication settings, and multimodal needs into actionable recommendations:
candidate index, sharding, cache, DR drill, observability, and external cluster
load checks. For latency-sensitive hot paths, keep `read_fanout` near
`read_quorum`; wider fanout reads more replicas and should be justified by the
HTTP cluster load benchmark. The same advice is available through HTTP:

```sh
curl "http://127.0.0.1:8000/architecture/advice?target_memories=2000000&namespace_count=4096&deployment=production&replication_factor=3&read_quorum=1&read_fanout=1"
```

Use `--fail-on action_required` in CI when a deployment must not proceed until
the required architecture work is done.

For production load tests, use the same SLO and cost gates that power the
checked-in benchmark report:

```python
from wavemind import (
    ProductionCostTarget,
    ProductionSLOTarget,
    estimate_production_cost,
    evaluate_production_slo,
)

target = ProductionSLOTarget(target_recall_at_k=0.95, target_p99_ms=100, target_qps=100)
result = evaluate_production_slo(
    engine="faiss-persisted",
    recall_at_k=1.0,
    avg_latency_ms=39.12,
    p99_latency_ms=57.71,
    target=target,
)
print(result.status, result.blocking_reasons)

cost = estimate_production_cost(
    result,
    memory_count=1_000_000,
    vector_dim=128,
    target=ProductionCostTarget(
        replica_hourly_cost_usd=0.25,
        monthly_budget_usd=1500.0,
        max_cost_per_1m_memories_usd=500.0,
        max_compute_cost_per_1m_queries_usd=10.0,
    ),
)
print(
    cost.cost_status,
    cost.required_replicas,
    cost.monthly_total_cost_per_1m_memories_usd,
    cost.compute_cost_per_1m_queries_usd,
)
```

Rule of thumb:

| target memories | recommended path |
|---:|---|
| up to 1000 | SQLite + NumPy exact index. |
| 1000 to 5000 | NumPy can work, but benchmark real queries. |
| 5000 to 50000 | Persisted FAISS for local single-node, or Qdrant service. |
| 50000 to 1M | Service-backed candidate index, namespace sharding, measured p95/p99. |
| above 1M | External vector database plus WaveMind as the memory-policy layer. |

Scale readiness profile:

```sh
python benchmarks/scale_readiness_benchmark.py --simulated-memories 1000000
```

Checked-in result:

| profile | result |
|---|---:|
| Cluster planner | 4096 namespaces, 4 nodes, replication factor 2, node-loss availability `1.000`, zone-loss availability `1.000`, write quorum `2`, Kubernetes `StatefulSet` + repair `CronJob` covering `4096` namespaces. |
| Cluster autoscaler | 10M target memories, RF=3, current nodes `4`, required nodes `50`, additional nodes `46`, target max node load `678711`, headroom pass `true`, full namespace rebalance plan `ready`: `4094` moves, `82` rolling batches, write quorum `2`, checkpoint/repair/validation required for every batch. |
| Control-plane consensus | Majority leadership lease blocks stale leaders, stale revisions, and minority config commits; membership change advances voters `3 -> 5`, term `1 -> 2`, final config revision `2`. |
| Kubernetes operator | CRD + operator deployment `true`, reconciled `StatefulSet`, `HorizontalPodAutoscaler`, rebalance `ConfigMap`, repair `CronJob`, and Memory OS `CronJob`; 10M capacity target raises StatefulSet/HPA to `34` replicas with target max node load `678711`, publishes a full rolling rebalance plan with `4048` moves and `81` batches, CPU+memory metrics, production admission target `10000000`, status phase `Ready`, and resources/capacity/autoscaling/rebalance/repair/Memory OS/production-admission/control-plane conditions `true`. The operator-rendered Memory OS job calls `/memory-os/plan` before `/memory-os/run`, applies planned distributed-lock requirements, and blocks mutation when Redis is required but missing. |
| Kubernetes serverless lifecycle | Three stateless API replicas across three kind zones use PVC-backed PostgreSQL, Qdrant, and Redis. Two scale-to-zero cycles restore all `24/24` memories, cross-replica write visibility is `3/3` in `1130.69 ms`, delete suppression is `3/3` in `915.03 ms`, and a 120-request burst passes with p99 `1461.46 ms` and zero errors. |
| Kubernetes PostgreSQL/Qdrant DR | A checksummed `pg_dump` archive (`1,016,635` bytes) is restored after source state services stop into fresh PVCs in an independent namespace. Recall is `24/24`, the initially empty Qdrant index rebuilds exactly to `24/24`, recall remains `24/24` after recovery API pod replacement, and the restore completes in `20.45 s`. |
| Hot cache | 2000 lookups, hit rate `0.920`, p99 lookup `0.003 ms`, query-audit prewarm warmed `1` hot query, prewarm hit `true`. |
| Query-vector cache | 200 repeated queries, one local encoder call, local hit rate `0.995`, Redis-compatible cache shared across workers `true`; FastAPI service path reuses the encoded query vector and exposes cache hit/miss metrics. |
| API batch query | FastAPI `/query/batch` answers 100 recall queries in 1 HTTP request instead of 100, preserves vector-cache reuse with one encoder call and batch hit rate `0.990`, and exposes batch/cache metrics. |
| Shared rate limiter | Redis-compatible fixed-window limiter, 2 workers, 4 allowed requests, 1 limited request, shared enforcement `true`. |
| Redis hot cache | Redis-compatible shared cache is visible across workers, query-audit prewarm warms `1` hot query, Memory OS warms `2` observed hot queries plus `6` predictive queries, learns the observed `budget recall -> risk limits` transition, applies `8` useful/not-useful recall feedback events, demotes cold memories, emits typed self-improvement suggestions plus a policy manifest with `6` decisions, cross-worker hit `true`, namespace invalidation `true`, production architecture advice `architecture_required`. |
| API cache mutation safety | FastAPI shared cache invalidates on `/remember`, `/feedback`, and `/forget`, preventing stale cached recall after memory mutations and after rejected recall feedback. |
| Batch feedback | FastAPI `/feedback/batch` accepts multiple recall signals in one request, rejects wrong-namespace items, writes audit events, updates positive/negative priority, and invalidates the affected namespace cache once. |
| Distributed sharding | 3 service nodes, replication factor 2, write quorum 2, writes `2`, recall after primary loss `true`, service-mode repair copied `1` missing record, recall after repair `true`, replicated forget deletes `2`, service-mode tombstone suppression before repair `true`, tombstone repair deleted `1` stale replica record, suppression after repair `true`, anti-entropy worker repaired `1` missing record and deleted `1` stale tombstone record, query-after-primary-loss `0.84 ms`. |
| Distributed HTTP sharding | 3 real localhost API nodes, proxy bypass `true`, quorum writes `2`, recall after primary loss `true`, HTTP repair copied `1` missing record, recall after repair `true`, tombstone repair deleted `1` stale API record, suppression after repair `true`, concurrent writes `12`, concurrent query hit rate `1.000`. |
| Sustained HTTP cluster load | 4 real localhost API nodes, RF=3, 8 quorum writes through one distributed batch, 8 normal queries, 8 failover queries, 4 deletes through one distributed batch, write HTTP requests reduced `24 -> 4`, forget+tombstone HTTP requests reduced `24 -> 8`, query HTTP requests reduced `8 -> 3`, failover query HTTP requests reduced `8 -> 2`, success rate `1.000`, failover hit rate `1.000`, delete suppression `1.000`, repair copied `1` missing replica, p99 operation `389.98 ms`. |
| Local HTTP cluster health | Post-load `/stats` probe reports health `true`, healthy nodes `4`, degraded nodes `0`, unavailable nodes `0`. |
| Replicated runtime | 3 physical WaveMind stores, replication factor 3, write quorum 2, node-loss recall `true`, repair copied `1` missing record, tombstone repair deleted `1` stale record, concurrent writes `12`, concurrent query hit rate `1.000`, p99 query-after-loss `1.34 ms`. |
| Active-active delta sync | 2 regions, bidirectional convergence `true`, full sync imported `6` records, cursor-based incremental sync exported `1` new record and imported `3` replicas, field-only hotness delta exported `0` records and `1` field key, stale import suppressed after delete `true`, tombstone convergence `true`, sync `114.70 ms`. |
| Sustained active-active sync | 3 independent regions, 3 namespaces, 18 writes, 5 mesh sync cycles, 90 region-pair syncs, cursor count `18`, records imported `108`, tombstones imported `6`, deleted records `6`, field keys exported `348`, final no-op imported `0`, convergence `1.000`, delete suppression `1.000`, success `1.000`, failed pairs `0`. |
| HTTP active-active service-region sync | 3 FastAPI service-boundary regions, 2 namespaces, 6 writes, 4 sync cycles, 48 export/import pair calls through `/namespace-delta/export` and `/namespace-delta/import`, cursor count `12`, records imported `36`, tombstones imported `6`, deleted records `6`, final no-op imported `0`, convergence `1.000`, delete suppression `1.000`, success `1.000`, failed pairs `0`. |
| Real HTTP active-active service-region smoke | 3 real localhost API region processes, each serving a replicated runtime, 2 namespaces, 6 writes, 3 sync cycles, 36 export/import pair calls, cursor count `12`, records imported `36`, tombstones imported `6`, deleted records `6`, final no-op imported `0`, convergence `1.000`, delete suppression `1.000`, success `1.000`, failed pairs `0`, p99 operation `347.58 ms`, SLO `true`. |
| Field-state CRDT | 3 regions, commutative convergence `true`, idempotent re-merge `true`, tombstone-wins `true`, top-key convergence `true`, actor watermark convergence `true`, watermark actors `3`, health `pass`, missing actor detection `true`, lag detection `true`, max watermark `100.0`, merge `0.13 ms`. |
| Replicated snapshot job | 3 replica files, manifest checksum validation `true`, offsite mirror validation `true`, portable archive validation `true`, S3-compatible upload validation `true`, latest remote archive metadata validation `true`, remote archive download validation `true`, object-store DR drill `true`, object-store retention pruned `2`, archive restore `64.13 ms`. |
| Structured payloads | image/audio/video/3D/table/event/graph retrieval through the standard memory API, precision@1 `1.000`; cross-modal target-modality retrieval over persisted payload vectors, precision@1 `1.000`, vector persistence `1.000`, provenance rate `1.000`, embedding dim `64`; strict external/precomputed vectors for image/audio/video/3D, precision@1 `1.000`, vector persistence `1.000`; external encoder contract over image/audio/table/event/video/3D/graph payloads passes with target precision@1 `1.000`, global precision@1 `1.000`, normalized finite persisted vectors `1.000`, provenance `1.000`, and separation margin `0.811`; temporal event retrieval covers actor filters, interval overlap, around-time reranking, recency reranking, persistence, and provenance with precision@1 `1.000`; knowledge-graph memory covers entity/predicate filters, 2-hop/3-hop traversal, persistence, and provenance with precision@1 `1.000`, path precision@1 `1.000`. |
| 100M capacity envelope | 100000000 target memories, 32768 deterministic namespace buckets, weighted rendezvous zone-aware placement, 128 nodes, 8 zones, replication factor 3, node-loss availability `1.000`, zone-loss availability `1.000`, distinct replica rate `1.000`, zone-spread rate `1.000`, replica-load skew `1.094`, max storage per node `5.81 GB`; scale-out audit from 128 to 160 nodes adds `32` nodes, moves `0.492` of replica sets, keeps target replica skew `1.082`, and keeps target zone-spread `1.000`; valid capacity plan `true`. |

This profile validates routing, cluster autoscale planning, full rolling
rebalance planning, control-plane majority lease/config revision safety,
Kubernetes deployment, HPA autoscaling, operator status conditions including
`RebalancePlanned`, `MemoryOSReady`, `ProductionAdmissionReady`, and
`ControlPlaneReady`, and scheduled repair
manifest generation, service-mode distributed namespace sharding, real HTTP
shard transport, sustained mixed HTTP cluster load, replica
repair and tombstone-aware delete repair, plus a reusable anti-entropy repair
worker, quorum-replicated runtime behavior, query-audit cache prewarm,
query-vector cache, Redis-compatible shared rate limiting,
Redis-compatible shared cache behavior, Memory OS shared prewarm, explicit useful/not-useful recall feedback, batch feedback updates, transition-learned predictive prefetch, typed self-improvement suggestions, machine-readable policy decisions for prefetch/priority/forgetting/consolidation/scale/coordination, production architecture advice, and namespace
invalidation, API cache mutation safety on remember/feedback/feedback-batch/forget, cursor-based active-active namespace
delta sync, sustained active-active mesh sync, HTTP service-region
active-active sync, real multi-process active-active service-region smoke,
field-only hotness delta sync,
field-state CRDT convergence with actor watermarks plus missing/lag diagnostics,
replicated snapshot/restore, structured payload handling,
deterministic cross-modal payload retrieval, external precomputed-vector
compatibility, and provenance,
and a 100M-memory capacity-planning envelope,
including verified offsite, archive, object-store latest lookup, object-store
download, object-store retention, and a disaster recovery drill that restores
the latest object-store archive, disables the restored primary replica, and
confirms recall still works from the remaining replicas.
It is not a 10M-vector load test. Real 100k, 1M, and 10M latency claims should
come from service-backed FAISS/Qdrant/pgvector load tests on production-like
hardware.

Local HTTP cluster smoke:

```sh
python benchmarks/local_http_cluster_smoke.py \
  --nodes 4 \
  --replication-factor 3 \
  --read-fanout 1 \
  --namespace-count 4 \
  --memories-per-namespace 2 \
  --workers 4 \
  --timeout 3 \
  --fail-on-slo
```

This starts 4 real localhost WaveMind API processes with isolated SQLite files,
runs the same service-mode workload through HTTP, and fails if quorum writes,
queries, simulated node failover, missing-replica repair, replicated forget, or
delete suppression regress. The checked-in run reaches success `1.000`,
failover hit `1.000`, delete suppression `1.000`, repaired replicas `1`, and
p99 `257.13 ms`.

Local HTTP active-active service-region smoke:

```sh
python benchmarks/local_http_active_active_smoke.py \
  --regions 3 \
  --replicas-per-region 3 \
  --namespace-count 2 \
  --timeout 3 \
  --fail-on-slo
```

This starts 3 real localhost WaveMind API region processes. Each region serves a
replicated local runtime through FastAPI, then the runner exchanges namespace
deltas through `/namespace-delta/export` and `/namespace-delta/import`. The
checked-in run reaches convergence `1.000`, delete suppression `1.000`, pair
sync success `1.000`, final no-op imports `0`, p99 operation `347.58 ms`, and
SLO `true`.

External URL-based active-active loopback:

```sh
python benchmarks/external_http_active_active_loopback.py \
  --regions 3 \
  --replicas-per-region 3 \
  --namespace-count 16 \
  --timeout 3 \
  --fail-on-slo
```

This starts 3 real localhost WaveMind API regions, passes their URLs into the
same external active-active runner used for remote deployments, and verifies the
URL-based transport contract. The checked-in run reaches convergence `1.000`,
delete suppression `1.000`, success `1.000`, final no-op imports `0`, p99
operation `349.21 ms`, and SLO `true`. It proves the external-runner contract,
not remote Kubernetes/serverless operation.

External HTTP active-active regions:

```sh
python benchmarks/local_http_active_active_smoke.py \
  --region us-east=https://us-east.example.com \
  --region eu-west=https://eu-west.example.com \
  --region ap-south=https://ap-south.example.com \
  --deployment-id staging-active-active-2026-07-07 \
  --environment staging \
  --source k8s-service \
  --namespace-count 16 \
  --fail-on-slo \
  --output benchmarks/external_http_active_active_results.json
```

The same profile is available as the manual GitHub Actions workflow
`external-http-active-active`. It is intentionally tracked as non-gating
external evidence until a real remote artifact is committed; the local service
smoke above is not treated as proof of remote Kubernetes/serverless operation.

External HTTP cluster load:

```sh
python benchmarks/http_cluster_load_benchmark.py \
  --nodes-file deploy/cluster/external-http-cluster.sample.json \
  --replication-factor 3 \
  --read-quorum 1 \
  --read-fanout 1 \
  --namespace-count 32 \
  --memories-per-namespace 8 \
  --workers 8 \
  --batch-query-size 24 \
  --fail-on-slo
```

This runs the same mixed workload against user-supplied API nodes: quorum
writes, normal queries, simulated node failover queries, missing-replica repair,
replicated forget, delete suppression, external `/query/batch` recall, p99
latency, and an explicit SLO verdict. Online query p99 and bulk lifecycle batch
p99 are reported separately so ingestion cost cannot be mistaken for recall
latency.
Use this before claiming that a deployment is production-ready outside the
local readiness smoke profile.
`deploy/cluster/external-http-cluster.sample.json` defines the repeatable node
manifest shape with deployment id, environment, source, node URLs, and zones.
Core readiness can pass without this artifact, but the strict production gate
only accepts it with non-loopback node addresses, a full Git commit SHA, a
traceable workflow run, and target-specific admission. Kind evidence additionally
requires a SHA-256-linked physical worker-failure artifact over the same pod DNS
endpoints.

The same external-cluster profile can be started from GitHub Actions via
`.github/workflows/external-http-cluster-load.yml`. Paste one `id=https://host`
node per line, comma-separated, or semicolon-separated, or paste the node
manifest JSON into `nodes_manifest_json`. Optionally set the `WAVEMIND_API_KEY`
repository secret, and set `commit_results=true` only when the run should
refresh the public benchmark artifacts in `main`.

Cluster placement planning:

```sh
wavemind cluster-plan \
  --namespace-count 4096 \
  --node node-a=10.0.0.1:8000 \
  --node node-b=10.0.0.2:8000 \
  --node node-c=10.0.0.3:8000 \
  --replication-factor 2 \
  --kubernetes \
  --repair-cronjob \
  --repair-api-key-secret wavemind-api-key \
  --json
```

This uses deterministic rendezvous placement so each namespace has a primary
and replica set. The emitted Kubernetes StatefulSet manifest is a deployment
starting point, and the optional repair CronJob runs scheduled service-mode
anti-entropy repair against the same node and namespace plan. Runtime quorum
replication is available through `ReplicatedWaveMind`; cluster membership and
operator config changes can be guarded with the deterministic
`ControlPlaneConsensus` / `wavemind control-plane-consensus` majority lease
preflight. Remote production services should still wrap that contract in a
durable operator/control-plane store.

Control-plane safety preflight:

```sh
wavemind control-plane-consensus --json
```

This deterministic profile verifies the operator-side invariants that prevent
split-brain config changes: majority leadership lease, stale-leader rejection,
stale revision rejection, minority partition rejection, and monotonic config
revisions.

Helm deployment:

```sh
helm install wavemind ./deploy/helm/wavemind
```

For authenticated API nodes, create a Secret and reference it:

```sh
kubectl create secret generic wavemind-auth --from-literal=admin-key="$WAVEMIND_ADMIN_KEY"
helm upgrade --install wavemind ./deploy/helm/wavemind \
  --set auth.enabled=true \
  --set auth.existingSecret=wavemind-auth
```

The chart deploys a StatefulSet, normal and headless Services, optional auth
Secret wiring, a scheduled `cluster-repair` CronJob, and optional Memory OS
CronJobs that call `/memory-os/plan` before `/memory-os/run`. It uses
`ghcr.io/caspiang/wavemind` by default; set `image.repository` when deploying
from a private registry. Production images include the PostgreSQL, Qdrant,
Redis, FAISS, S3, and OpenTelemetry dependencies. The chart can inject
`WAVEMIND_POSTGRES_DSN`, `WAVEMIND_QDRANT_URL`, Qdrant API credentials, and
`WAVEMIND_REDIS_URL` from existing Kubernetes Secrets; selecting PostgreSQL or
Qdrant without its backend Secret fails Helm rendering instead of silently
starting with SQLite or NumPy. See `deploy/helm/wavemind/README.md` for the
secret-backed command. The Memory OS CronJob applies the returned plan before
mutation: planned distributed-lock requirements are ORed into `/memory-os/run`,
and a Redis-required plan fails early if `runtime.redisUrl` is missing.

```sh
helm upgrade --install wavemind ./deploy/helm/wavemind \
  --set memoryOs.enabled=true \
  --set runtime.auditQueries=1 \
  --set runtime.redisUrl=redis://redis.default.svc.cluster.local:6379/0
```

With `memoryOs.strictPlan=true`, the Memory OS job fails before mutation when
the plan reports `architecture_required`.

Remote three-region staging can be prepared through `deploy/remote`. Its
inventory requires unique SSH hosts, public URLs, regions, and zones; live
attestation hashes `/etc/machine-id` and rejects multiple aliases for the same
physical host. The deployer starts PostgreSQL + Qdrant + Redis + WaveMind on
each host, checks loopback and public health, and emits the manifest consumed by
the external active-active benchmark. Deployment alone does not unlock the
claim: strict admission still requires measured convergence and failure/recovery
artifacts.

For strict production admission, route the container through `wavemind serve`
and require checked evidence before the API opens port `8000`:

```sh
helm upgrade --install wavemind ./deploy/helm/wavemind \
  --set productionAdmission.enabled=true \
  --set productionAdmission.targetMemories=100000000 \
  --set productionAdmission.engine=qdrant-sharded-service
```

This wires `WAVEMIND_REQUIRE_PRODUCTION_ADMISSION=1`,
`WAVEMIND_PRODUCTION_TARGET_MEMORIES`, `WAVEMIND_PRODUCTION_ENGINE`, and
`WAVEMIND_PRODUCTION_ADMISSION_ROOT` into the StatefulSet. If the required
strict-evidence artifact is missing or rejected, `wavemind serve` exits before
binding the HTTP port, so a Kubernetes rollout cannot silently bypass the
production evidence gate.

Operator-style deployment:

```sh
wavemind operator-bundle --namespace wavemind-system --json | kubectl apply -f -
kubectl apply -f deploy/operator/wavemindcluster.sample.json
wavemind operator-reconcile --file deploy/operator/wavemindcluster.sample.json --out wavemind-resources.json
wavemind operator-status --file deploy/operator/wavemindcluster.sample.json --ready-replicas 3 --json
kubectl apply -f wavemind-resources.json
```

`deploy/operator` contains the `WaveMindCluster` custom resource path. The
bundle installs the CRD with a status subresource, RBAC, operator Deployment,
and a sample cluster. The reconciler renders the concrete Service, headless
Service, StatefulSet, HPA, rebalance ConfigMap, repair CronJob, and Memory OS
CronJob resources. The Memory OS job calls `/memory-os/plan` before
`/memory-os/run`, applies planned distributed-lock requirements, and exits
before mutation when Redis is required but `spec.cache.redisUrl` is missing.
`wavemind operator-status` turns the custom resource plus observed
replicas/memory/node health into Kubernetes-style conditions for resources,
capacity, autoscaling, rolling rebalance planning, repair, Memory OS scheduling,
and control-plane safety. `spec.controlPlane.consensus` is enabled by default
and requires majority leader lease/config revision safety before the cluster is
reported ready. `wavemind operator-loop` can run in-cluster to keep resources
applied and patch the `WaveMindCluster.status` subresource when the Kubernetes
client supports it.

The generated operator Deployment runs two replicas with rolling updates and
cross-node anti-affinity. Runtime reconciliation is protected by a durable
Kubernetes Lease stored through the API server/etcd: only the pod holding the
Lease applies resources or patches status, renewals use `resourceVersion` CAS,
and an expired holder can be replaced with an audited transition counter.
The `kubernetes-operator-smoke` workflow exercises that path in a real
four-node kind cluster by deleting the leader and a data pod, then verifying
Lease takeover, post-failover reconcile, StatefulSet scaling, and API recovery.
It is CI evidence, not a substitute for the required remote-cluster artifact.
The checked-in result passed all `14/14` checks, including PDB/topology
protection and a CR-driven rolling upgrade that replaced all four data pods,
and links back to the exact
[GitHub Actions run](https://github.com/CaspianG/wavemind/actions/runs/29054900969).

The operator exposes the same production admission contract through
`spec.productionAdmission`. Explicitly enable it with:

```sh
wavemind operator-sample \
  --production-admission \
  --production-admission-target-memories 100000000 \
  --production-admission-engine qdrant-sharded-service \
  --json
```

For capacity targets at or above `10000000` memories, the reconciler also
auto-injects the admission environment into the rendered StatefulSet and reports
`ProductionAdmissionReady` in operator status.

The operator also accepts capacity targets. Add this to `spec.autoscaling` and
the reconciler will raise the StatefulSet replicas and HPA min/max replicas to
fit the target under the requested per-node headroom:

```json
{
  "enabled": true,
  "targetMemories": 10000000,
  "maxMemoriesPerNode": 1000000,
  "headroom": 0.7,
  "rebalance": {
    "batchSize": 50,
    "maxNodeMovesPerBatch": 50,
    "previewBatches": 3
  }
}
```

Rendered resources include `memory.wavemind.ai/capacity-*` annotations with the
calculated replica count and target max node load. They also include
`memory.wavemind.ai/rebalance-*` annotations plus a bounded
`<cluster>-rebalance-plan` ConfigMap with full-plan status, move count, batch
count, quorum, checkpoint/repair/validation requirements, and a preview of early
batches.

The same planner is available over HTTP as `POST /cluster-plan`.

Cluster autoscale planning:

```sh
wavemind cluster-autoscale-plan \
  --namespace-count 4096 \
  --node node-a=https://wm-a.internal \
  --node node-b=https://wm-b.internal \
  --node node-c=https://wm-c.internal \
  --replication-factor 3 \
  --target-memories 10000000 \
  --max-memories-per-node 1000000 \
  --headroom 0.70 \
  --zone zone-a --zone zone-b --zone zone-c \
  --max-moves 4096 \
  --rebalance-plan \
  --rebalance-batch-size 50 \
  --rebalance-max-node-moves-per-batch 50 \
  --json
```

This calculates the required node count for the target memory volume, adds
future nodes with deterministic names and addresses, checks the target max
per-node memory load against the headroom limit, and can emit a rolling
rebalance plan. The rebalance plan groups namespace moves into bounded batches,
tracks read/write quorum, blocks drain-node target violations, and marks every
batch as requiring a source/target checkpoint, cluster repair, and validation
before the next batch. The HTTP surface is `POST /cluster-autoscale-plan`.

Serverless deployment:

```sh
wavemind serverless-sample --namespace wavemind-system --max-scale 256 --out deploy/serverless/wavemind-serverless.sample.json
wavemind serverless-sample --readiness
wavemind serverless-sample --operational-profile --max-scale 256 --target-concurrency 80
wavemind serverless-sample --operational-profile --max-scale 256 --target-concurrency 80 --observed-telemetry deploy/serverless/observed-telemetry.loopback.json
python benchmarks/serverless_observed_telemetry_benchmark.py --node https://wm-a.example --node https://wm-b.example --api-key "$WAVEMIND_API_KEY" --seed-mode first --external-cold-start-ms 900 --output deploy/serverless/observed-telemetry.remote-candidate.json
```

`deploy/serverless` contains a stateless API worker plan with two profiles: a
Knative scale-to-zero `Service`, and a KEDA `Deployment`/`Service`/CPU
`ScaledObject` profile where the autoscaler targets the generated Deployment
and keeps one warm replica. It is
intentionally stricter than local mode: Postgres is required as the source of
truth, Qdrant is used as the external candidate index, Redis is used for shared
hot-query cache, and API keys are read from Kubernetes Secrets. This path is the
current foundation for Knative scale-to-zero and managed/serverless
deployments; CPU-based KEDA handles scale-out, not zero-to-one activation. It
is not a claim that WaveMind has a hosted control plane yet.

The scale-readiness gate also runs a deterministic serverless operational
profile: 3200 requests/second, 80 ms average request time, 320 ms warm p99,
900 ms modeled cold start, 4 required replicas, 256000 burst RPS capacity,
cold-start budget pass, and estimated monthly compute cost `$81.76`. The
checked-in observed telemetry is generated by
`benchmarks/serverless_observed_telemetry_benchmark.py`: it starts a balanced
pool of real local WaveMind HTTP API replicas, seeds and warms the hot-query
cache on each replica, measures pool RPS, per-replica RPS, p95/p99/error
rate/cold start, and multiplies measured per-replica throughput by
`max_scale=256` for the Knative/KEDA horizontal capacity estimate. This is
loopback evidence, not a real-cluster performance claim. The same runner also
accepts repeated `--node https://...` URLs, `--api-key`, `--seed-mode first`,
and `--external-cold-start-ms` so the identical telemetry JSON contract can be
run against real Knative/KEDA, Kubernetes, or managed serverless API nodes
before publishing managed serverless numbers.

Maintenance workers:

```sh
wavemind maintenance --namespace user:42 --consolidate-steps 10 --consolidate-concepts --json
wavemind memory-os-plan --namespace user:42 --deployment production --target-memories 2000000 --namespace-count 4096 --cache-mode auto --json
wavemind cluster-admission --deployment production --min-nodes 4 --namespace-count 32 --replication-factor 3 --read-quorum 1 --read-fanout 1 --batch-query-size 24 --allow-plan-only --write-artifacts --json
wavemind active-active-admission --deployment production --min-regions 3 --namespace-count 16 --allow-plan-only --write-artifacts --json
wavemind serverless-admission --deployment production --target-rps 3200 --target-p99-ms 500 --max-scale 256 --allow-plan-only --write-artifacts --json
wavemind multimodal-external-evidence --manifest path/to/external_multimodal_manifest.json --write-artifacts --output benchmarks/multimodal_precomputed_contract_results.json --markdown-output benchmarks/MULTIMODAL_EXTERNAL_EVIDENCE.md --json
wavemind multimodal-admission --deployment production --fail-on-blocked --write-artifacts --json
wavemind memory-os-canary --target-memories 100000 --namespace-count 64 --deployment staging --write-artifacts --json
wavemind memory-os-evolution --cycles 3 --write-artifacts --json
wavemind memory-os-admission --target-memories 10000000 --namespace-count 4096 --deployment production --allow-plan-only --write-artifacts --json
wavemind memory-os-policy-bundle --write-artifacts --json
wavemind memory-os --namespace user:42 --redis-url redis://localhost:6379/0 --lock-required --min-frequency 2 --max-hot-queries 32 --json
wavemind cluster-health --node node-a=https://wm-a.internal --node node-b=https://wm-b.internal --node node-c=https://wm-c.internal --replication-factor 3 --read-quorum 1 --read-fanout 1 --api-key "$WAVEMIND_API_KEY" --fail-on-degraded --json
wavemind cluster-repair --node node-a=https://wm-a.internal --node node-b=https://wm-b.internal --node node-c=https://wm-c.internal --namespace user:42 --replication-factor 3 --write-quorum 2 --read-quorum 1 --read-fanout 1 --api-key "$WAVEMIND_API_KEY" --json
wavemind cluster-plan --namespace-count 4096 --node node-a=https://wm-a.internal --node node-b=https://wm-b.internal --node node-c=https://wm-c.internal --replication-factor 3 --repair-cronjob --repair-api-key-secret wavemind-api-key --json
wavemind replicated-snapshot --root ./state/replicas --node node-a --node node-b --node node-c --out ./backups/replicated --offsite ./offsite/replicated --archive ./archives/replicated --s3 s3://my-bucket/wavemind/prod --keep-last 7 --s3-keep-last 30 --json
wavemind replicated-drill --from s3://my-bucket/wavemind/prod --to ./state/drill-restore --query "short support replies" --expect-text "Tenant A prefers short support replies." --json
```

The first command runs one deterministic memory pass: expired-memory purge,
optional field/concept consolidation, and index-health repair. The `memory-os`
command is the adaptive worker: it reads query audit events, identifies hot
queries, warms Redis/local cache, generates predictive neighbor queries from
the top recalled memories, learns observed follow-up transitions such as
`budget recall -> risk limits`, predicts bounded priority boosts from usage
patterns, demotes cold unused memories with bounded adaptive forgetting, purges
expired memories, consolidates active clusters into durable concept memories,
checks index health, and returns operator-facing recommendations plus typed
self-improvement suggestions with ids, severity, actions, and evidence for
Studio/operator dashboards. It also emits a policy manifest that turns runtime
signals into explicit decisions for prefetch, priority learning, adaptive
forgetting, consolidation, scale, and distributed coordination. When given
production targets such as `--target-memories`, `--namespace-count`,
`--deployment production`, and `--multimodal`, it also embeds the same
architecture-advisor output used by release readiness gates: service-index,
namespace-sharding, production-controls, replication capacity, load-test, and
multimodal-readiness actions. In production, use `--lock-required` with
`--redis-url` so CronJob retries or multiple workers cannot run overlapping
consolidation, forgetting, and prewarm cycles for the same namespace. The
cluster-health command probes every
WaveMind API node, exposes healthy/degraded/unavailable circuit state, and can
fail deployment preflight when any node is degraded. The cluster-repair command runs service-mode
anti-entropy repair across WaveMind API nodes:
missing replica records are copied back, and tombstoned stale records are
deleted instead of resurrected. The cluster-plan command emits a Kubernetes CronJob
for that repair loop. The snapshot command creates a verified replicated snapshot,
mirrors it to an offsite path,
writes a portable `.tar.gz` archive, verifies that archive, can upload it to an
S3-compatible object store, verify newest-archive metadata, run an object-store
disaster-recovery drill, and apply local and object-store retention. Production
deployments can call these commands from cron, systemd, Kubernetes CronJobs,
Celery, RQ, or Temporal.

The `memory-os-plan` command and `GET /memory-os/insights` endpoint are the
read-only scheduler preflight for that worker set. They inspect current stats,
audited query traffic, and previous Memory OS policy outcomes without mutating
memory, then emit concrete task cadences, worker counts, Redis/shared-cache
requirements, distributed-lock requirements, and exact commands for
`memory-os`, `cache-prewarm`, consolidation, forgetting, maintenance, and
architecture-advice loops. The insights endpoint additionally returns
dashboard-ready typed suggestions with ids, severity, action text, and evidence
for Studio and operator consoles. In production mode the planner automatically
promotes `--cache-mode auto` to Redis when QPS, namespace count, memory count,
hot query volume, or repeated prefetch policy gaps require cross-worker cache
sharing. Plans also include `policy_manifest`, `policy_history`,
`policy_escalation_ids`, and `policy_auto_adjustments`, so operators can see
when repeated Memory OS gaps changed cadence, priority, cache mode, or lock
requirements. Production `memory-os` commands emitted by the planner include
`--lock-required` whenever the plan requires a distributed single-flight lock.
`wavemind cluster-admission` is the deployment-facing gate for remote
service-node cluster rollout. It joins the strict `external_http_cluster`
evidence requirement with cluster-node preflight state and writes
`benchmarks/cluster_admission_results.json` plus
`benchmarks/CLUSTER_ADMISSION.md`. `--fail-on-blocked` stops deploys until real
external HTTP service nodes have passed quorum writes, recall, failover,
repair, delete suppression, batch query, and p99 SLO checks; local loopback
HTTP-cluster profiles remain development evidence only.
`wavemind active-active-admission` is the deployment-facing gate for remote
multi-region active-active rollout. It joins the strict
`external_http_active_active` evidence requirement with active-active preflight
state and writes `benchmarks/active_active_admission_results.json` plus
`benchmarks/ACTIVE_ACTIVE_ADMISSION.md`. `--fail-on-blocked` stops deploys
until real external HTTP regions have passed convergence, tombstone,
final-noop, and p99 SLO checks; `--allow-plan-only` keeps the operator report
useful without admitting production traffic.
`wavemind serverless-admission` is the matching gate for managed/serverless
rollout. It joins the strict `serverless_remote_telemetry` evidence requirement
with the remote-node preflight state and writes
`benchmarks/serverless_admission_results.json` plus
`benchmarks/SERVERLESS_ADMISSION.md`. `--fail-on-blocked` stops deploys until
real deployed API nodes have produced remote telemetry for p99 latency,
cold-start budget, error rate, and scale-out capacity.
`wavemind multimodal-external-evidence` turns a real external multimodal
manifest into `benchmarks/multimodal_precomputed_contract_results.json`: assets
must already have external shared-space vectors, `s3://` object-store metadata,
verified sha256/byte-size provenance, and precomputed query vectors. This is a
storage/integration contract and cannot unlock real-encoder admission.
`wavemind multimodal-admission` is the deployment-facing gate for production
multimodal claims. It uses the checked structured-memory report as the API
contract and only admits when the real local benchmark proves pinned
text/image/audio/video/3D encoder quality, object-store-backed assets, object
verification, vector persistence, provenance, leakage protection,
per-modality/bidirectional precision, repeated verdicts, and retrieval/encoding
SLOs. The checked 1000-asset/200-query, three-run artifact is admitted with
macro/cross-modal/mixed precision@1 `0.925`, parity `1.000`, retrieval p99
`48.64 ms`, and zero errors. This is exact-SHA and suite-bounded evidence, not a
universal-domain claim.
`wavemind memory-os-admission` is the stricter deployment gate for the same
worker set: it checks hot-query audit signal, Redis/shared-cache wiring,
distributed lock wiring, singleton/idempotent mutations, policy coverage, and
strict architecture boundaries before Memory OS workers become production
automation. It writes `benchmarks/memory_os_admission_results.json` and
`benchmarks/MEMORY_OS_ADMISSION.md`; `--fail-on-blocked` makes CI/deploys stop
until the worker set is really admitted.
`wavemind memory-os-canary` is the staging proof for that gate: it seeds
representative memories and query-audit traffic, runs one Memory OS cycle,
checks prewarm, predictive prefetch, priority learning, TTL cleanup, and then
verifies that scheduler admission passes when Redis/cache and lock wiring are
declared. It writes `benchmarks/memory_os_canary_results.json` and
`benchmarks/MEMORY_OS_CANARY.md`. This is a staging canary, not remote
Kubernetes, real Redis, or 10M/100M production evidence.
`wavemind memory-os-evolution` is the multi-cycle proof for that same worker
loop. It replays representative query-audit traffic across several Memory OS
cycles, verifies that repeated required policy gaps become history-backed
suggestions and scheduler escalations, and checks that stable OK policies,
hot-query prewarm, predictive prefetch, priority learning, and required worker
tasks remain active. It writes
`benchmarks/memory_os_policy_evolution_results.json` and
`benchmarks/MEMORY_OS_POLICY_EVOLUTION.md`. This is deterministic local/staging
policy evidence; it does not unlock unattended production automation without
remote Redis, distributed lock, runtime environment, and strict large-scale
evidence.
`wavemind memory-os-policy-bundle` connects those artifacts to runtime. It
reads the checked canary, policy-evolution, and admission reports, then emits
`benchmarks/memory_os_policy_bundle_results.json` and
`benchmarks/MEMORY_OS_POLICY_BUNDLE.md`: a deterministic operator policy
manifest with enabled Memory OS tasks, required Redis/lock environment,
observability metrics, Kubernetes/CronJob patch data, and explicit promotion
gates. Current checked-in evidence is staging-promotable but keeps production
locked while `memory-os-admission` is `plan_only`.

Hot-cache options:

| cache | use case |
|---|---|
| `HotMemoryCache` | in-process local API/server cache. |
| `RedisHotMemoryCache` | shared cache for multiple API workers. Install with `pip install "wavemind[redis]"`. |
| `QueryVectorCache` | in-process cache for encoded query vectors when the encoder is expensive. |
| `RedisQueryVectorCache` | shared encoded-query-vector cache across API workers. |

API cache can be enabled with:

```sh
WAVEMIND_CACHE_CAPACITY=512 WAVEMIND_CACHE_TTL_SECONDS=60 wavemind serve
```

For multiple API workers, use a shared Redis cache:

```sh
WAVEMIND_REDIS_URL=redis://localhost:6379/0 WAVEMIND_AUDIT_QUERIES=1 wavemind serve
```

For repeated natural-language queries with a semantic encoder, cache encoded
query vectors separately from full query results:

```sh
WAVEMIND_VECTOR_CACHE_CAPACITY=1024 WAVEMIND_VECTOR_CACHE_TTL_SECONDS=300 wavemind serve
WAVEMIND_VECTOR_CACHE_REDIS_URL=redis://localhost:6379/0 wavemind serve
```

To verify the live multi-process cache path, including Redis-backed batch query
recall, shared query-vector cache hits, and batch recall feedback invalidation,
against a real Redis service:

```sh
python benchmarks/redis_api_load_benchmark.py --redis-url redis://localhost:6379/0 --workers 2 --requests 40 --batch-size 12 --fail-on-slo
```

For production workers, enable query audit and prewarm the cache from repeated
real queries:

```sh
WAVEMIND_AUDIT_QUERIES=1 WAVEMIND_CACHE_CAPACITY=512 wavemind serve
wavemind --audit-queries query "budget preference" --namespace demo
curl -X POST http://127.0.0.1:8000/cache/prewarm -H "x-api-key: $WAVEMIND_ADMIN_KEY" -d '{"min_frequency":2,"max_queries":32}'
wavemind cache-prewarm --redis-url redis://localhost:6379/0 --min-frequency 2 --max-queries 32
```

The same path is available in Python through `CachePrewarmWorker`. The CLI can
also run with a process-local cache for diagnostics, but production prewarm
should use Redis so warmed entries survive the worker process. Query audit
stores query text, so keep it opt-in for deployments with stricter privacy
requirements.

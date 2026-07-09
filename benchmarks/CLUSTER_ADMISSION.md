# WaveMind Cluster Admission

This is the deployment-facing gate for remote service-node cluster
rollouts. It admits production traffic only when real external HTTP
service nodes have passed quorum writes, recall, failover, repair,
delete suppression, batch query, and p99 SLO evidence. Local loopback
profiles stay useful for development, but do not unlock this gate.

| metric | value |
|---|---:|
| status | `plan_only` |
| admitted | `False` |
| deployment | `production` |
| min nodes | `4` |
| namespace count | `32` |
| memories per namespace | `8` |
| replication factor | `3` |
| read quorum | `1` |
| read fanout | `1` |
| batch query size | `24` |
| p99 SLO ms | `1000.0` |
| strict evidence | `action_required` |
| requested evidence | `fail` |
| preflight | `action_required` |
| required artifact | `benchmarks/http_cluster_load_results.json` |

## Required Evidence

| requirement | status | artifact | evidence |
|---|---|---|---|
| External HTTP service-node load | `action_required` | `benchmarks/http_cluster_load_results.json` | nodes 4, deployment loopback-2026-07-07-batch-query, environment local-loopback, source loopback-api-processes, namespaces 32, success 1.0, failover 1.0, p99 531.5410000039265 ms, batch query True, batch HTTP 24 -> 1, batch p99 401.61139995325357 ms |

## Requested Evidence

| status | min nodes | namespaces | RF | read quorum | read fanout | batch size | p99 SLO ms | evidence |
|---|---:|---:|---:|---:|---:|---:|---:|---|
| `fail` | `4` | `32` | `3` | `1` | `1` | `24` | `1000.0` | nodes 4, deployment loopback-2026-07-07-batch-query, environment local-loopback, source loopback-api-processes, namespaces 32, success 1.0, failover 1.0, p99 531.5410000039265 ms, batch query True, batch HTTP 24 -> 1, batch p99 401.61139995325357 ms; issues: environment must be a real remote/staging/production deployment, source must identify a real remote run, not a sample or loopback |

## Preflight

| status | required env | missing env | evidence |
|---|---|---|---|
| `action_required` | `WAVEMIND_CLUSTER_NODES, WAVEMIND_CLUSTER_NODES_MANIFEST_JSON` | `WAVEMIND_CLUSTER_NODES, WAVEMIND_CLUSTER_NODES_MANIFEST_JSON` | 0 URLs configured |

## Issues

- external_http_cluster is not admitted: strict_status=action_required
- external_http_cluster artifact does not satisfy requested rollout: requested_evidence_status=fail
- environment must be a real remote/staging/production deployment
- source must identify a real remote run, not a sample or loopback

## Next Actions

- Do not admit remote production cluster traffic yet; run the external HTTP cluster workflow against real service nodes first.
- `gh workflow run external-http-cluster-load.yml -f nodes="node-a=https://wm-a.example.com,node-b=https://wm-b.example.com,node-c=https://wm-c.example.com,node-d=https://wm-d.example.com" -f replication_factor=3 -f read_quorum=1 -f read_fanout=1 -f batch_query_size=24 -f fail_on_slo=true -f commit_results=true`

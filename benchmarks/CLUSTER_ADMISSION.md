# WaveMind Cluster Admission

This is the deployment-facing gate for non-loopback Kubernetes or external
service-node rollouts. It admits traffic only when the exact requested node
URLs match evidence that passed quorum writes, recall, failover, repair,
delete suppression, batch query, and p99 SLO checks. Local loopback profiles
stay useful for development, but do not unlock this gate.

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
| strict evidence | `pass` |
| requested evidence | `pass` |
| preflight | `action_required` |
| required artifact | `benchmarks/http_cluster_load_results.json` |

## Required Evidence

| requirement | status | artifact | evidence |
|---|---|---|---|
| Non-loopback Kubernetes or external HTTP service-node load | `pass` | `benchmarks/http_cluster_load_results.json` | nodes 4, deployment github-actions-30264903065-wavemind-ci-wavemind-system, environment kubernetes-kind-non-loopback-ci, source kubernetes-pod-dns-physical-node-drill, namespaces 32, success 1.0, failover 1.0, query p99 85.72988783000763 ms, lifecycle batch p99 7909.665061999987 ms, batch query True, batch HTTP 24 -> 1, batch p99 171.8241359999979 ms |

## Requested Evidence

| status | min nodes | namespaces | RF | read quorum | read fanout | batch size | p99 SLO ms | evidence |
|---|---:|---:|---:|---:|---:|---:|---:|---|
| `pass` | `4` | `32` | `3` | `1` | `1` | `24` | `1000.0` | nodes 4, deployment github-actions-30264903065-wavemind-ci-wavemind-system, environment kubernetes-kind-non-loopback-ci, source kubernetes-pod-dns-physical-node-drill, namespaces 32, success 1.0, failover 1.0, query p99 85.72988783000763 ms, lifecycle batch p99 7909.665061999987 ms, batch query True, batch HTTP 24 -> 1, batch p99 171.8241359999979 ms |

## Preflight

| status | required env | missing env | evidence |
|---|---|---|---|
| `action_required` | `WAVEMIND_CLUSTER_NODES, WAVEMIND_CLUSTER_NODES_MANIFEST_JSON` | `WAVEMIND_CLUSTER_NODES, WAVEMIND_CLUSTER_NODES_MANIFEST_JSON` | 0 URLs configured |

## Issues

- external HTTP cluster preflight is not ready; provide target node URLs or a node manifest before admitting the rollout.
- requested cluster node URLs do not match the node_addresses in strict evidence
- cluster node requires at least 4 URLs

## Next Actions

- Do not admit remote production cluster traffic yet; run the external HTTP cluster workflow against real service nodes first.
- `gh workflow run external-http-cluster-load.yml -f nodes="node-a=https://wm-a.example.com,node-b=https://wm-b.example.com,node-c=https://wm-c.example.com,node-d=https://wm-d.example.com" -f replication_factor=3 -f read_quorum=1 -f read_fanout=1 -f batch_query_size=24 -f fail_on_slo=true -f commit_results=true`

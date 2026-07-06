# External HTTP Cluster Load

This directory holds repeatable node manifests for real WaveMind API-node load
tests. It does not contain benchmark results or secrets.

Run the external cluster benchmark from a manifest:

```sh
python benchmarks/http_cluster_load_benchmark.py \
  --nodes-file deploy/cluster/external-http-cluster.sample.json \
  --replication-factor 3 \
  --read-quorum 1 \
  --read-fanout 1 \
  --namespace-count 32 \
  --memories-per-namespace 8 \
  --workers 8 \
  --fail-on-slo
```

The manifest fields are:

- `deployment_id`: stable identifier for the tested deployment.
- `environment`: `staging`, `production`, or another operator-defined scope.
- `source`: where the nodes came from, for example `kubernetes-service`.
- `nodes[].id`: stable node id.
- `nodes[].url`: public or private WaveMind API base URL.
- `nodes[].zone`: availability zone or region label.

The benchmark writes `benchmarks/http_cluster_load_results.json`. That result is
treated as external evidence by the production readiness gate. It must come from
real API nodes; sample or fixture sources are rejected by the validator.

# WaveMind Kubernetes Operator

WaveMind can be deployed through the Helm chart or through the operator-style
control plane in this directory.

The operator path uses a `WaveMindCluster` custom resource:

```sh
wavemind operator-bundle --namespace wavemind-system --json | kubectl apply -f -
kubectl apply -f deploy/operator/wavemindcluster.sample.json
wavemind operator-reconcile --file deploy/operator/wavemindcluster.sample.json --out wavemind-resources.json
kubectl apply -f wavemind-resources.json
```

`operator-bundle` emits the CRD, RBAC, operator Deployment, and a sample custom
resource. `operator-reconcile` renders the concrete Kubernetes resources for a
cluster: normal Service, headless Service, StatefulSet, optional HPA, and
scheduled repair CronJob. When a capacity target is configured, it also renders
a bounded `ConfigMap` named `<cluster>-rebalance-plan` with rolling namespace
rebalance metadata and preview batches.

Production control-plane safety is part of the custom resource. By default,
`spec.controlPlane.consensus.enabled` is true. Operator status only reports the
cluster as ready when the consensus preflight proves that config changes require
a majority leader lease, monotonic config revisions, stale-leader rejection,
stale-revision rejection, and minority-partition rejection:

```json
{
  "spec": {
    "controlPlane": {
      "consensus": {
        "enabled": true,
        "leaseTtlSeconds": 30.0,
        "configRevision": 0
      }
    }
  }
}
```

The generated status includes a `ControlPlaneReady` condition and a
`status.controlPlane.profile` object with the deterministic safety evidence.

Capacity autoscaling is part of the custom resource. When
`spec.autoscaling.targetMemories` is set, the reconciler uses WaveMind's
cluster autoscale planner to raise the StatefulSet replica count and HPA
min/max replicas until the target memory volume fits under the configured
per-node headroom:

```json
{
  "spec": {
    "replicationFactor": 3,
    "namespaceCount": 4096,
    "autoscaling": {
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
  }
}
```

The rendered resources include `memory.wavemind.ai/capacity-*` annotations with
the calculated replica count, target memory volume, headroom, and expected max
node load. The rebalance ConfigMap includes a JSON summary with move count,
batch count, read/write quorum, full-plan status, checkpoint/repair/validation
requirements, and a bounded preview of early batches so it stays safe for
Kubernetes object size limits.

The in-cluster operator container runs:

```sh
wavemind operator-loop --namespace wavemind-system
```

The loop lists `WaveMindCluster` resources and applies the reconciled Services,
StatefulSet, HPA, rebalance ConfigMap, and repair CronJob with Kubernetes
server-side apply. Operator status includes `RebalancePlanned` and only reports
ready when the plan is full and every batch requires checkpoint, repair, and
validation.

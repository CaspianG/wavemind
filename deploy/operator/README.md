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
scheduled repair CronJob.

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
      "headroom": 0.7
    }
  }
}
```

The rendered resources include `memory.wavemind.ai/capacity-*` annotations with
the calculated replica count, target memory volume, headroom, and expected max
node load.

The in-cluster operator container runs:

```sh
wavemind operator-loop --namespace wavemind-system
```

The loop lists `WaveMindCluster` resources and applies the reconciled Services,
StatefulSet, HPA, and repair CronJob with Kubernetes server-side apply.

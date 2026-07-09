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
cluster: normal Service, headless Service, StatefulSet, optional HPA, scheduled
repair CronJob, and optional Memory OS CronJob. When a capacity target is
configured, it also renders a bounded `ConfigMap` named
`<cluster>-rebalance-plan` with rolling namespace rebalance metadata and preview
batches.

The operator Deployment runs two replicas by default. Kubernetes
`coordination.k8s.io/v1` Lease leader election keeps followers read-only and
allows a new pod to take over after the current lease expires. Lease updates use
`metadata.resourceVersion` compare-and-swap through the Kubernetes API, so two
operator replicas cannot reconcile the cluster concurrently. The Lease is
durable in the Kubernetes control plane rather than pod memory, and the bundle
includes Lease RBAC, pod identity through the downward API, rolling-update
settings, and cross-node anti-affinity.

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
This config-change profile is separate from runtime operator leader election:
the profile checks majority/revision invariants, while the Kubernetes Lease
ensures only one live operator replica can apply those decisions.

Production Memory OS scheduling is also part of the custom resource:

```json
{
  "spec": {
    "cache": {
      "redisUrl": "redis://redis.wavemind-system.svc.cluster.local:6379/0"
    },
    "memoryOs": {
      "enabled": true,
      "schedule": "*/10 * * * *",
      "targetMemories": 10000000,
      "cacheMode": "auto",
      "strictPlan": true,
      "runOnAllReplicas": false
    }
  }
}
```

The rendered `<cluster>-memory-os` CronJob calls `/memory-os/plan` before
`/memory-os/run`, applies planned distributed-lock requirements, and exits
before mutation if the plan requires Redis but `spec.cache.redisUrl` is missing.
Operator status includes a `MemoryOSReady` condition plus
`status.memoryOs.redisRequired` and `status.memoryOs.redisConfigured`, so unsafe
multi-replica Memory OS scheduling is visible before it mutates cluster state.

Production admission is the API startup guard for large clusters. When
`spec.autoscaling.targetMemories` reaches 10M or more, the reconciler injects
`WAVEMIND_REQUIRE_PRODUCTION_ADMISSION=1` into the StatefulSet automatically.
You can also configure it explicitly:

```json
{
  "spec": {
    "productionAdmission": {
      "enabled": true,
      "targetMemories": 100000000,
      "engine": "qdrant-sharded-service",
      "deployment": "production",
      "evidenceRoot": "/evidence"
    }
  }
}
```

The API pod starts through `wavemind serve`; if the matching strict evidence
artifact is missing or failing under `evidenceRoot`, the process exits before
binding port 8000. Operator status includes `ProductionAdmissionReady` and
`status.productionAdmission`, so rollout controllers can see whether the guard
is configured.

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
wavemind operator-loop \
  --namespace wavemind-system \
  --holder-identity "$POD_NAME" \
  --lease-name wavemind-operator \
  --lease-duration-seconds 60
```

The loop lists `WaveMindCluster` resources and applies the reconciled Services,
StatefulSet, HPA, rebalance ConfigMap, repair CronJob, and Memory OS CronJob
with Kubernetes server-side apply. Operator status includes `RebalancePlanned`
and `MemoryOSReady`, and only reports ready when the plan is full, every
rebalance batch requires checkpoint/repair/validation, and production Memory OS
scheduling has the required Redis/shared-lock configuration.

Every patched `WaveMindCluster.status` also records `operatorLeader`, including
the holder identity, Lease resource version, transition count, and
`kubernetes-lease-etcd` backend. A follower reports the current holder and does
not apply resources or patch status.

The repository includes a real multi-node Kubernetes CI drill in
`.github/workflows/kubernetes-operator-smoke.yml`. It installs the operator into
a four-node kind cluster, deletes the current Lease holder, waits for follower
takeover, scales the StatefulSet through the new leader, replaces a data pod,
and verifies API recovery. This is stronger than an in-process simulation, but
it remains ephemeral CI evidence and does not unlock remote production
admission.
The latest checked-in artifact passed `9/9` checks in
[run 29053524619](https://github.com/CaspianG/wavemind/actions/runs/29053524619)
and records its source commit and workflow URL for auditability.

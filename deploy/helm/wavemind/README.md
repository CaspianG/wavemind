# WaveMind Helm Chart

This chart deploys WaveMind API nodes as a StatefulSet and adds a scheduled
anti-entropy repair CronJob for namespace-replicated clusters. Optional
Memory OS CronJobs can run the production scheduler preflight and adaptive
memory worker against the API nodes. Optional HorizontalPodAutoscaler support
can scale the API StatefulSet when metrics-server is available.

The chart uses the official GitHub Container Registry image by default. Override
`image.repository` and `image.tag` when using a private registry.

```sh
helm install wavemind ./deploy/helm/wavemind
```

For API authentication, create a Kubernetes Secret and reference it:

```sh
kubectl create secret generic wavemind-auth --from-literal=admin-key="$WAVEMIND_ADMIN_KEY"
helm upgrade --install wavemind ./deploy/helm/wavemind \
  --set auth.enabled=true \
  --set auth.existingSecret=wavemind-auth
```

The repair CronJob calls `wavemind cluster-repair` against the StatefulSet
pod DNS names. Set `repair.namespaceCount` or `repair.namespaces` to match the
tenant namespace plan used by your application.

Enable Memory OS scheduling for production memory maintenance:

```sh
helm upgrade --install wavemind ./deploy/helm/wavemind \
  --set memoryOs.enabled=true \
  --set runtime.auditQueries=1 \
  --set runtime.redisUrl=redis://redis.default.svc.cluster.local:6379/0 \
  --set memoryOs.targetMemories=2000000 \
  --set memoryOs.namespaceCount=4096
```

The Memory OS CronJob calls `/memory-os/plan` first. With
`memoryOs.strictPlan=true`, the job fails before mutation when the API reports
`architecture_required`. If the plan is acceptable, it calls `/memory-os/run`
on every StatefulSet replica by default.

Enable autoscaling for production clusters:

```sh
helm upgrade --install wavemind ./deploy/helm/wavemind \
  --set autoscaling.enabled=true \
  --set autoscaling.minReplicas=3 \
  --set autoscaling.maxReplicas=24 \
  --set resources.requests.cpu=500m \
  --set resources.requests.memory=1Gi
```

CPU and memory utilization-based HPA needs container resource requests. Without
requests, Kubernetes can render the HPA but cannot calculate utilization.

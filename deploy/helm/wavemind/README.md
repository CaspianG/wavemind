# WaveMind Helm Chart

This chart deploys WaveMind API nodes as a StatefulSet and adds a scheduled
anti-entropy repair CronJob for namespace-replicated clusters. Optional
Memory OS CronJobs can run the production scheduler preflight and adaptive
memory worker against the API nodes. Optional HorizontalPodAutoscaler support
can scale the API StatefulSet when metrics-server is available.

The chart uses the official GitHub Container Registry image by default. Override
`image.repository` and `image.tag` when using a private registry.
The API container starts through `wavemind serve`, so the same production
admission guard used by CI and release gates can block unproven large-scale
deployments before the pod binds its HTTP port.

For a production backend, create Secrets for PostgreSQL, Qdrant, and Redis.
The chart reads connection details through `secretKeyRef`; credentials do not
need to appear in Helm values or release history:

```sh
kubectl create secret generic wavemind-postgres \
  --from-literal=dsn="$WAVEMIND_POSTGRES_DSN"
kubectl create secret generic wavemind-qdrant \
  --from-literal=url="$WAVEMIND_QDRANT_URL" \
  --from-literal=api-key="$WAVEMIND_QDRANT_API_KEY"
kubectl create secret generic wavemind-redis \
  --from-literal=url="$WAVEMIND_REDIS_URL"

helm upgrade --install wavemind ./deploy/helm/wavemind \
  --set runtime.store=postgres \
  --set runtime.index=qdrant \
  --set backends.postgres.enabled=true \
  --set backends.postgres.existingSecret=wavemind-postgres \
  --set backends.qdrant.enabled=true \
  --set backends.qdrant.existingSecret=wavemind-qdrant \
  --set backends.qdrant.apiKeyEnabled=true \
  --set backends.redis.enabled=true \
  --set backends.redis.existingSecret=wavemind-redis
```

Helm rendering fails when `runtime.store=postgres` or
`runtime.index=qdrant` is selected without the corresponding backend and
Secret. This keeps a production release from silently falling back to local
SQLite or NumPy state.

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
on every StatefulSet replica by default. The CronJob also reads the returned
task plan before mutation: if the planned `memory-os` task requires a
distributed lock, `lock_required` is passed to `/memory-os/run` even when the
static chart value is false. If the plan promotes `cache_mode` to Redis but
`runtime.redisUrl` is not configured, the job exits before mutation.

For shared-state production deployments, enable the Redis-backed single-flight
lock and run one Memory OS cycle per namespace:

```sh
helm upgrade --install wavemind ./deploy/helm/wavemind \
  --set memoryOs.enabled=true \
  --set runtime.redisUrl=redis://redis.default.svc.cluster.local:6379/0 \
  --set memoryOs.runOnAllReplicas=false \
  --set memoryOs.lockRequired=true
```

The CronJob passes a pod-scoped idempotency key together with `lock_required`,
`lock_ttl_seconds`, and `lock_prefix`. The Redis lease is renewed while the
cycle is active and released with an atomic ownership check. Completed job
receipts prevent a Kubernetes retry from applying consolidation, forgetting,
or priority changes twice. A receipt that is still marked `running` is treated
as in-doubt and fails closed; it is not replayed automatically. The production
chart retains receipts for seven days so an operator can inspect a hard-crash
case before manually clearing or replaying it.

Pause Memory OS mutations without disabling recall:

```sh
helm upgrade wavemind ./deploy/helm/wavemind \
  --reuse-values \
  --set memoryOs.emergencyStop=true
```

Use `memoryOs.suspend=true` to suspend future CronJob schedules. The emergency
stop exits an already-created job before `/memory-os/plan` or `/memory-os/run`.
Set both values back to `false` only after the failed canary or admission gate
has been reviewed.

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

For 10M, 50M, or 100M memory targets, enable the startup admission guard and
mount the strict evidence bundle at `productionAdmission.evidenceRoot`:

```sh
helm upgrade --install wavemind ./deploy/helm/wavemind \
  --set productionAdmission.enabled=true \
  --set productionAdmission.targetMemories=100000000 \
  --set productionAdmission.engine=qdrant-sharded-service \
  --set productionAdmission.evidenceRoot=/evidence
```

If the matching strict evidence artifact is missing or failing, the API exits
before opening port 8000. This prevents a Kubernetes rollout from advertising
100M-scale readiness before the checked production evidence exists.

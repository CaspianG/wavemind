# WaveMind Helm Chart

This chart deploys WaveMind API nodes as a StatefulSet and adds a scheduled
anti-entropy repair CronJob for namespace-replicated clusters.

The chart does not assume a public container registry. Build and push an image
for your environment, or use a local image in a local Kubernetes cluster.

```sh
helm install wavemind ./deploy/helm/wavemind \
  --set image.repository=registry.example.com/wavemind \
  --set image.tag=2.4.1
```

For API authentication, create a Kubernetes Secret and reference it:

```sh
kubectl create secret generic wavemind-auth --from-literal=admin-key="$WAVEMIND_ADMIN_KEY"
helm upgrade --install wavemind ./deploy/helm/wavemind \
  --set image.repository=registry.example.com/wavemind \
  --set image.tag=2.4.1 \
  --set auth.enabled=true \
  --set auth.existingSecret=wavemind-auth
```

The repair CronJob calls `wavemind cluster-repair` against the StatefulSet
pod DNS names. Set `repair.namespaceCount` or `repair.namespaces` to match the
tenant namespace plan used by your application.


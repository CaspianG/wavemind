# WaveMind Serverless Deployment

This profile is for stateless WaveMind API workers on Knative/KEDA-compatible
clusters.

It is intentionally different from the stateful `WaveMindCluster` operator:

- Postgres is required as the memory source of truth.
- Qdrant or another external service should be used as the candidate index.
- Redis should be used for shared hot-query cache across scaled workers.
- Pod-local SQLite is not used because serverless workers may scale to zero or
  move between nodes.

Generate a sample bundle:

```sh
wavemind serverless-sample --namespace wavemind-system --max-scale 64 --out deploy/serverless/wavemind-serverless.sample.json
```

Inspect readiness assumptions:

```sh
wavemind serverless-sample --readiness
```

Required secrets:

```sh
kubectl create secret generic wavemind-postgres \
  --from-literal=dsn='postgresql://user:password@postgres:5432/wavemind'

kubectl create secret generic wavemind-qdrant \
  --from-literal=url='http://qdrant:6333'

kubectl create secret generic wavemind-redis \
  --from-literal=url='redis://redis:6379/0'

kubectl create secret generic wavemind-auth \
  --from-literal=api-keys='change-me'
```

The generated bundle contains two deployment profiles:

- a Knative `Service` with scale-to-zero annotations and concurrency target;
- a KEDA `Deployment`, Kubernetes `Service`, and `ScaledObject` where
  `scaleTargetRef` points at the generated Deployment;
- environment variables for Postgres, Qdrant, Redis, and API keys.

Use one profile in a real cluster. The bundled sample keeps both profiles in one
file so operators can compare Knative scale-to-zero and KEDA policy-driven
autoscaling without hand-writing manifests.

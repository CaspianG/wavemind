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

Run the operational preflight from the CLI:

```sh
wavemind serverless-sample --operational-profile --max-scale 64 --target-concurrency 80
```

Run the same profile with observed load-test telemetry:

```sh
wavemind serverless-sample --operational-profile --observed-telemetry deploy/serverless/observed-telemetry.sample.json
```

Measure observed telemetry from already-deployed API nodes:

```sh
python benchmarks/serverless_observed_telemetry_benchmark.py \
  --node https://wm-a.example \
  --node https://wm-b.example \
  --api-key "$WAVEMIND_API_KEY" \
  --seed-mode first \
  --external-cold-start-ms 900 \
  --output deploy/serverless/observed-telemetry.remote.json
```

The scale-readiness benchmark also runs a deterministic operational profile for
this serverless shape. It checks:

- external Postgres, Qdrant, Redis, and API-key wiring;
- scale-to-zero safety for stateless workers;
- required replicas for a target request rate;
- burst capacity against `maxScale` and `targetConcurrency`;
- cold-start budget;
- estimated monthly compute cost.
- optional observed p99, cold-start, error-rate, scale-out, capacity, and cost
  telemetry from a real Knative/KEDA load test.

Current checked-in profile: 3200 requests/second, 80 ms average request time,
320 ms warm p99, 900 ms cold start, 4 required warm replicas, 64000 burst RPS
capacity, and an estimated `$81.76` monthly compute cost at the modeled active
fraction. The checked-in observed telemetry is a loopback API-replica capacity
estimate, not a live Knative/KEDA load test. Replace it with a remote
`observed-telemetry.remote.json` generated from deployed API nodes, or with
exported k6, Prometheus, or load-generator metrics, before making a live
serverless SLO claim.

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

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
cluster: normal Service, headless Service, StatefulSet, and scheduled repair
CronJob.

The in-cluster operator container runs:

```sh
wavemind operator-loop --namespace wavemind-system
```

The loop lists `WaveMindCluster` resources and applies the reconciled Services,
StatefulSet, and repair CronJob with Kubernetes server-side apply.

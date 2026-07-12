# Remote Production Lab

This deployment path provisions the same isolated WaveMind stack on at least three independently attested Linux hosts. Each region runs PostgreSQL as the
source of truth, Qdrant for candidates, Redis for coordination/cache, and the
production WaveMind image. It exists to produce real remote active-active and
failure-recovery evidence, not to relabel local containers as regions.

1. Copy `inventory.example.json` outside the repository and replace the sample
   hosts and URLs. Region IDs, SSH hosts, public URLs, regions, zones, and
   `/etc/machine-id` identities must all be unique.
2. Ensure the SSH aliases use pinned host keys and non-interactive key auth.
3. Run attestation before deployment:

```sh
python deploy/remote/remote_lab.py attest \
  --inventory state/remote-inventory.json \
  --output state/remote-attestation.json
```

Attestation checks SSH reachability, Docker, CPU, memory, free disk, and unique
machine identities. Raw `/etc/machine-id` values are hashed before they enter
the artifact.

Deploy with secrets supplied only through the process environment:

```sh
export WAVEMIND_REMOTE_API_KEY='...'
export WAVEMIND_REMOTE_POSTGRES_PASSWORD='...'
python deploy/remote/remote_lab.py deploy \
  --inventory state/remote-inventory.json \
  --output state/remote-deployment.json \
  --manifest-output state/active-active-regions.json
```

The deployer writes `.env` through SSH stdin with `umask 077`, starts Compose
with `--wait`, and verifies each host through its loopback health endpoint.
Run `probe` next to verify the public endpoints. Only then run the external
active-active benchmark:

```sh
python benchmarks/local_http_active_active_smoke.py \
  --regions-file state/active-active-regions.json \
  --namespace-count 16 \
  --fail-on-slo \
  --output state/external_http_active_active_results.json
```

Deployment and attestation are not active-active proof by themselves. Strict
admission still requires measured convergence, delete suppression, idempotent
final sync, latency, outage, and recovery artifacts.

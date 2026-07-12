# Remote Qdrant 100M Lab

This lab turns eight or more independently hosted Linux machines into a
measured Qdrant shard topology for the strict WaveMind 100M benchmark. It does
not claim 100M readiness from a plan, a local container, or a synthetic capacity
estimate.

Each host must have a unique `/etc/machine-id`, a unique zone, Docker, at least
16 GB RAM, and enough free disk for its share of the target. For the default
100M x 128 profile, the current safety floor is 35 GB per shard across eight
hosts. At least three regions are required.

Qdrant binds only to `127.0.0.1` on every host. The benchmark runner reaches
the shards through pinned SSH tunnels with strict host-key checking, so the
Qdrant API is never exposed publicly.

```sh
python deploy/remote-scale/remote_scale_lab.py plan \
  --inventory state/remote-scale-inventory.json \
  --output state/remote-scale/plan.json

python deploy/remote-scale/remote_scale_lab.py attest \
  --inventory state/remote-scale-inventory.json \
  --output state/remote-scale/attestation.json

python deploy/remote-scale/remote_scale_lab.py deploy \
  --inventory state/remote-scale-inventory.json \
  --output state/remote-scale/deployment.json
```

The GitHub workflow performs plan, attestation, deployment, tunnel validation,
the resumable 100M benchmark, strict SLO validation, and artifact ingestion.
It closes every persistent SSH control tunnel in an `always()` step. A manual
CLI tunnel session can be closed with `remote_scale_lab.py close-tunnels` using
the same inventory and working directory.
The claim remains locked unless the final benchmark reaches recall@10 >= 0.95,
p99 <= 100 ms, and `cost_status=valid_slo` with GitHub run provenance.

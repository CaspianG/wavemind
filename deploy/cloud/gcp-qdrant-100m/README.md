# GCP Qdrant 100M Evidence Lab

This Terraform root creates eight independent Qdrant shard hosts in eight
zones across four GCP regions. It exists only to supply the strict
`remote-qdrant-100m-lab.yml` workflow with physically attested capacity.

The default `e2-standard-4` hosts satisfy the 16 GB RAM floor, and 100 GB disks
leave room above the 35 GB free-disk floor. Qdrant is never exposed by a
firewall: the deployer binds it to `127.0.0.1`, and the durable benchmark runner
uses pinned SSH tunnels.

Applying this module creates eight billable VMs, disks, and static addresses
across four regions. Review regional quotas, estimated multi-day cost, budget
alerts, and teardown procedure before apply. Provisioning and attestation do
not unlock the 100M claim; the measured run must still reach recall@10 >= 0.95,
p99 <= 100 ms, and the strict cost gate with matching GitHub provenance.

```sh
cd deploy/cloud/gcp-qdrant-100m
cp terraform.tfvars.example terraform.tfvars
terraform init
terraform plan -out wavemind-100m.tfplan
terraform apply wavemind-100m.tfplan
```

After first boot:

1. Review `terraform output -json remote_scale_inventory`.
2. Run the emitted `known_hosts_command` and verify every fingerprint through
   the GCP serial console.
3. Store the reviewed inventory, private key, pinned known-host lines, and an
   isolated Qdrant API key in the secrets consumed by
   `.github/workflows/remote-qdrant-100m-lab.yml`.
4. Register a separate durable self-hosted runner with enough disk/runtime for
   the resumable multi-day job; do not run it on a production application host.
5. Run `action=attest`, then `action=evidence`. Preserve checkpoint artifacts
   so interrupted runs can resume without rebuilding completed vectors.

The module never receives a private key or Qdrant API key, and no rule exposes
port 6333 publicly. Set `deletion_protection=false` only in a reviewed teardown
plan after all evidence artifacts have been downloaded and validated.

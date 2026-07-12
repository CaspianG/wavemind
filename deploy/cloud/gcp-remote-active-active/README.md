# GCP Remote Active-Active Evidence Lab

This Terraform root creates three independent GCE hosts in three regions for
the strict WaveMind active-active and physical region-failure workflow. It does
not create benchmark results and does not unlock a production claim by itself.

Each host has a separate machine identity, zone, static address, and persistent
Docker volumes. The startup script installs Docker Engine and Compose. The
existing `deploy/remote/remote_lab.py` deployer then installs PostgreSQL,
Qdrant, Redis, and WaveMind on every host and physically stops one regional API
during the recovery drill.

## Apply

Applying this module creates billable Google Cloud VMs, disks, and addresses.
Use an isolated project with a budget alert and no user production data.

```sh
cd deploy/cloud/gcp-remote-active-active
cp terraform.tfvars.example terraform.tfvars
terraform init
terraform plan -out wavemind-regions.tfplan
terraform apply wavemind-regions.tfplan
```

The module never receives an SSH private key. Put only its matching public key
in `terraform.tfvars`. After first boot:

1. Review `terraform output -json remote_lab_inventory`.
2. Run the emitted `known_hosts_command` and verify all fingerprints through
   the GCP serial console before trusting them.
3. Store the reviewed JSON, private key, and pinned known-host lines in the
   GitHub secrets named by `.github/workflows/remote-production-lab.yml`.
4. Add isolated `WAVEMIND_REMOTE_API_KEY` and
   `WAVEMIND_REMOTE_POSTGRES_PASSWORD` secrets.
5. Run the workflow first with `action=attest`, then `action=evidence`.
6. Download and review the evidence bundle before ingesting it.

The default API firewall is not implicit: `api_source_ranges` must be supplied.
Prefer a stable self-hosted runner CIDR. A temporary public CIDR is acceptable
only for an ephemeral API-key-protected evidence lab and must be removed after
the run. SSH access rejects `0.0.0.0/0` entirely.

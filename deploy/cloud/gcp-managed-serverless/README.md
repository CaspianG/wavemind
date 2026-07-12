# GCP Managed Serverless Evidence Infrastructure

This Terraform root provisions the dedicated infrastructure required by
`.github/workflows/managed-serverless-cloud-run.yml`. It is intentionally
separate from application production traffic.

It creates:

- a Cloud Run v2 service with `min_instance_count = 0` and bounded scale-out;
- runtime and evidence service accounts with separate least-privilege roles;
- GitHub OIDC Workload Identity Federation restricted to
  `CaspianG/wavemind` on `refs/heads/main`;
- IAM-protected invocation for the evidence identity only;
- Secret Manager bindings for PostgreSQL, Qdrant, Redis, and WaveMind API keys;
- an Artifact Registry repository for immutable digest-pinned images.

The module does not create databases or secret values. Supply existing
production-shaped PostgreSQL, Qdrant, and Redis endpoints through Secret
Manager. Do not point this evidence service at user production data.

```sh
cd deploy/cloud/gcp-managed-serverless
cp terraform.tfvars.example terraform.tfvars
terraform init
terraform plan -out wavemind-managed.tfplan
terraform apply wavemind-managed.tfplan
```

After apply, put the two identity outputs into GitHub Actions secrets:

- `WAVEMIND_GCP_WORKLOAD_IDENTITY_PROVIDER`
- `WAVEMIND_GCP_SERVICE_ACCOUNT`

Put the three `github_repository_variables` outputs into GitHub repository
variables. Add one benchmark API key from the `WAVEMIND_API_KEYS` secret as the
GitHub secret `WAVEMIND_API_KEY`. The evidence workflow uses the Google identity
token in `Authorization` and the WaveMind key in `X-API-Key`.

Applying this module creates billable Google Cloud resources. Review the plan,
quotas, IAM bindings, database isolation, and budget alerts before apply.

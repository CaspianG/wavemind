from pathlib import Path

import yaml


ROOT = Path("deploy/cloud/gcp-managed-serverless")


def _read(name: str) -> str:
    return (ROOT / name).read_text(encoding="utf-8")


def test_terraform_module_pins_provider_and_immutable_image():
    versions = _read("versions.tf")
    variables = _read("variables.tf")

    assert 'required_version = ">= 1.10.0, < 2.0.0"' in versions
    assert 'version = "~> 7.39"' in versions
    assert "@sha256:[0-9a-f]{64}" in variables
    assert "immutable Artifact Registry sha256 digest" in variables
    assert "latest" not in _read("terraform.tfvars.example")


def test_terraform_module_enforces_scale_to_zero_and_external_state():
    main = _read("main.tf")
    variables = _read("variables.tf")

    assert main.count("min_instance_count = 0") >= 2
    assert "max_instance_count = var.max_instances" in main
    assert 'name  = "WAVEMIND_STORE"' in main
    assert 'value = "postgres"' in main
    assert 'name  = "WAVEMIND_INDEX"' in main
    assert 'value = "qdrant"' in main
    assert "value_source" in main
    assert "secret_key_ref" in main
    for name in (
        "WAVEMIND_POSTGRES_DSN",
        "WAVEMIND_QDRANT_URL",
        "WAVEMIND_REDIS_URL",
        "WAVEMIND_API_KEYS",
    ):
        assert name in variables


def test_terraform_oidc_trust_is_repository_and_main_scoped():
    main = _read("main.tf")
    variables = _read("variables.tf")

    assert 'default     = "CaspianG/wavemind"' in variables
    assert 'default     = "refs/heads/main"' in variables
    assert "assertion.repository == '${var.github_repository}'" in main
    assert "assertion.ref == '${var.github_ref}'" in main
    assert 'issuer_uri = "https://token.actions.githubusercontent.com"' in main
    assert 'role               = "roles/iam.workloadIdentityUser"' in main
    assert "google_service_account.evidence.email" in main


def test_terraform_iam_is_least_privilege_and_never_public():
    main = _read("main.tf")

    assert '"roles/monitoring.viewer"' in main
    assert '"roles/run.viewer"' in main
    assert 'role     = "roles/run.invoker"' in main
    assert 'role      = "roles/secretmanager.secretAccessor"' in main
    assert "allUsers" not in main
    assert "allAuthenticatedUsers" not in main
    assert "roles/owner" not in main
    assert "roles/editor" not in main


def test_terraform_workflow_formats_initializes_and_validates():
    workflow_path = Path(".github/workflows/terraform-validate.yml")
    workflow = workflow_path.read_text(encoding="utf-8")
    parsed = yaml.safe_load(workflow)

    assert "hashicorp/setup-terraform@v4" in workflow
    assert 'terraform_version: "1.15.3"' in workflow
    assert "terraform fmt -check -recursive" in workflow
    assert "terraform init -backend=false -input=false" in workflow
    assert "terraform validate -no-color" in workflow
    assert "deploy/cloud/gcp-managed-serverless" in workflow
    assert "deploy/cloud/gcp-remote-active-active" in workflow
    assert "deploy/cloud/gcp-qdrant-100m" in workflow
    assert parsed["permissions"]["contents"] == "read"


def test_terraform_state_and_credentials_are_not_committable():
    gitignore = Path(".gitignore").read_text(encoding="utf-8")
    workflow = Path(".github/workflows/managed-serverless-cloud-run.yml").read_text(
        encoding="utf-8"
    )
    readme = _read("README.md")

    for pattern in (".terraform/", "*.tfstate", "*.tfplan", "terraform.tfvars"):
        assert pattern in gitignore
    assert "credentials_json" not in workflow
    assert "creates billable Google Cloud resources" in readme


def test_terraform_module_is_discoverable_without_overclaiming_provisioning():
    public_docs = [
        Path("README.md").read_text(encoding="utf-8"),
        Path("docs/ROADMAP.md").read_text(encoding="utf-8"),
        Path("docs/BENCHMARK_BRIEF.md").read_text(encoding="utf-8"),
    ]

    for document in public_docs:
        assert "deploy/cloud/gcp-managed-serverless" in document
        assert "billable" in document

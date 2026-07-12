from pathlib import Path


ROOT = Path("deploy/cloud/gcp-qdrant-100m")


def _read(name: str) -> str:
    return (ROOT / name).read_text(encoding="utf-8")


def test_qdrant_100m_iac_pins_provider_and_capacity_floor():
    versions = _read("versions.tf")
    variables = _read("variables.tf")

    assert 'required_version = ">= 1.10.0, < 2.0.0"' in versions
    assert 'version = "~> 7.39"' in versions
    assert "length(var.shards) >= 8" in variables
    assert "length(distinct([for config in values(var.shards) : config.region])) >= 3" in variables
    assert "target_vectors >= 100000000" in variables
    assert '"e2-standard-4"' in variables
    assert "boot_disk_size_gb >= 60" in variables


def test_qdrant_100m_iac_uses_eight_unique_zones_across_four_regions():
    variables = _read("variables.tf")

    for shard in range(8):
        assert f"shard-{shard}" in variables
    for region in ("europe-west1", "us-east1", "asia-south1", "europe-central2"):
        assert region in variables
    assert "length(distinct([for config in values(var.shards) : config.zone])) == length(var.shards)" in variables


def test_qdrant_100m_iac_exposes_only_restricted_ssh():
    main = _read("main.tf")
    variables = _read("variables.tf")

    assert 'resource "google_compute_firewall" "ssh"' in main
    assert 'ports    = ["22"]' in main
    assert "6333" not in main
    assert "source_ranges = var.ssh_source_ranges" in main
    assert '!contains(var.ssh_source_ranges, "0.0.0.0/0")' in variables
    assert 'resource "google_compute_firewall" "qdrant"' not in main


def test_qdrant_100m_iac_creates_hardened_independent_hosts():
    main = _read("main.tf")

    assert 'resource "google_compute_instance" "shard"' in main
    assert 'resource "google_compute_address" "shard"' in main
    assert "for_each = var.shards" in main
    assert "block-project-ssh-keys" in main
    assert "enable_secure_boot          = true" in main
    assert "enable_vtpm                 = true" in main
    assert "enable_integrity_monitoring = true" in main
    assert "deletion_protection       = var.deletion_protection" in main


def test_qdrant_100m_iac_outputs_strict_remote_scale_inventory():
    outputs = _read("outputs.tf")

    assert 'schema         = "wavemind.remote_qdrant_scale_lab.v1"' in outputs
    assert 'environment    = "staging"' in outputs
    assert 'source         = "gcp-compute-terraform"' in outputs
    assert 'provider' in outputs and '"gcp"' in outputs
    assert "target_vectors = var.target_vectors" in outputs
    assert "vector_dim     = var.vector_dim" in outputs
    assert "remote_scale_inventory_json" in outputs
    assert "known_hosts_command" in outputs


def test_qdrant_100m_iac_never_accepts_runtime_secrets():
    combined = "\n".join(
        _read(name) for name in ("main.tf", "variables.tf", "terraform.tfvars.example")
    ).lower()

    assert "private_key" not in combined
    assert "qdrant_api_key" not in combined
    assert ":latest" not in combined
    assert "ssh_public_key" in combined


def test_qdrant_100m_docs_preserve_measured_claim_boundary():
    module_readme = _read("README.md")
    compact_readme = " ".join(module_readme.split())
    public_docs = [
        Path("README.md").read_text(encoding="utf-8"),
        Path("docs/ROADMAP.md").read_text(encoding="utf-8"),
        Path("docs/BENCHMARK_BRIEF.md").read_text(encoding="utf-8"),
    ]

    assert "creates eight billable VMs" in module_readme
    assert "do not unlock the 100M claim" in compact_readme
    assert "Qdrant is never exposed" in module_readme
    for document in public_docs:
        assert "deploy/cloud/gcp-qdrant-100m" in document


def test_qdrant_100m_iac_provisions_dedicated_durable_runner():
    main = _read("main.tf")
    variables = _read("variables.tf")
    outputs = _read("outputs.tf")

    assert 'resource "google_compute_instance" "runner"' in main
    assert 'resource "google_compute_address" "runner"' in main
    assert 'default     = "n2-standard-8"' in variables
    assert "runner_disk_size_gb >= 100" in variables
    assert "custom_label = \"self-hosted-large\"" in outputs
    assert "runner_known_hosts_command" in outputs
    assert "deletion_protection       = var.deletion_protection" in main


def test_qdrant_100m_runner_archive_is_pinned_and_verified():
    variables = _read("variables.tf")
    startup = _read("runner-startup.sh.tftpl")

    assert 'default     = "2.335.1"' in variables
    assert "4ef2f25285f0ae4477f1fe1e346db76d2f3ebf03824e2ddd1973a2819bf6c8cf" in variables
    assert "sha256sum --check --strict" in startup
    assert "actions-runner-linux-x64-${runner_version}.tar.gz" in startup
    assert "--disableupdate" in startup


def test_qdrant_100m_runner_tokens_are_post_apply_only_and_cleanup_is_explicit():
    terraform_text = "\n".join(
        _read(name) for name in ("main.tf", "variables.tf", "outputs.tf", "terraform.tfvars.example")
    )
    startup = _read("runner-startup.sh.tftpl")
    module_readme = _read("README.md")

    assert "GITHUB_RUNNER_TOKEN" not in terraform_text
    assert "GITHUB_RUNNER_REMOVE_TOKEN" not in terraform_text
    assert "register-wavemind-runner" in startup
    assert "remove-wavemind-runner" in startup
    assert "config.sh\" remove --token" in startup
    assert "actions/runners/registration-token" in module_readme
    assert "actions/runners/remove-token" in module_readme
    assert "stale offline runner" in module_readme

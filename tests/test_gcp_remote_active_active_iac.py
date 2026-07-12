from pathlib import Path


ROOT = Path("deploy/cloud/gcp-remote-active-active")


def _read(name: str) -> str:
    return (ROOT / name).read_text(encoding="utf-8")


def test_remote_iac_pins_provider_and_requires_three_unique_regions():
    versions = _read("versions.tf")
    variables = _read("variables.tf")

    assert 'required_version = ">= 1.10.0, < 2.0.0"' in versions
    assert 'version = "~> 7.39"' in versions
    assert "length(var.regions) >= 3" in variables
    assert variables.count("length(distinct(") >= 2
    for region in ("europe-west1", "us-east1", "asia-south1"):
        assert region in variables


def test_remote_iac_creates_independent_hardened_hosts():
    main = _read("main.tf")

    assert 'resource "google_compute_instance" "region"' in main
    assert 'resource "google_compute_address" "region"' in main
    assert "for_each = var.regions" in main
    assert "block-project-ssh-keys" in main
    assert "enable_secure_boot          = true" in main
    assert "enable_vtpm                 = true" in main
    assert "enable_integrity_monitoring = true" in main
    assert "deletion_protection       = var.deletion_protection" in main
    assert "metadata_startup_script" in main


def test_remote_iac_restricts_ssh_and_requires_explicit_api_ingress():
    main = _read("main.tf")
    variables = _read("variables.tf")

    assert 'resource "google_compute_firewall" "ssh"' in main
    assert 'resource "google_compute_firewall" "api"' in main
    assert "source_ranges = var.ssh_source_ranges" in main
    assert "source_ranges = var.api_source_ranges" in main
    assert '!contains(var.ssh_source_ranges, "0.0.0.0/0")' in variables
    assert 'variable "api_source_ranges"' in variables
    assert 'variable "ssh_source_ranges"' in variables


def test_remote_iac_never_accepts_private_key_or_mutable_image():
    variables = _read("variables.tf")
    main = _read("main.tf")
    example = _read("terraform.tfvars.example")

    assert 'variable "ssh_public_key"' in variables
    assert "private_key" not in variables.lower()
    assert "private_key" not in main.lower()
    assert "ssh_private" not in example.lower()
    assert "sha-[0-9a-f]{7,64}" in variables
    assert ":latest" not in example


def test_remote_iac_outputs_strict_inventory_contract():
    outputs = _read("outputs.tf")

    assert 'schema        = "wavemind.remote_production_lab.v1"' in outputs
    assert 'environment   = "staging"' in outputs
    assert 'source        = "gcp-compute-terraform"' in outputs
    assert 'provider   = "gcp"' in outputs
    assert "remote_lab_inventory_json" in outputs
    assert "known_hosts_command" in outputs
    assert "public_url = \"http://${google_compute_address.region[id].address}:8000\"" in outputs


def test_remote_iac_bootstrap_installs_docker_compose_and_ready_marker():
    startup = _read("startup.sh.tftpl")

    assert "docker-ce" in startup
    assert "docker-compose-plugin" in startup
    assert "systemctl enable --now docker" in startup
    assert "docker compose version" in startup
    assert "/var/lib/wavemind-bootstrap/ready" in startup


def test_remote_iac_docs_preserve_paid_execution_claim_boundary():
    module_readme = _read("README.md")
    public_docs = [
        Path("README.md").read_text(encoding="utf-8"),
        Path("docs/ROADMAP.md").read_text(encoding="utf-8"),
        Path("docs/BENCHMARK_BRIEF.md").read_text(encoding="utf-8"),
    ]

    assert "creates billable Google Cloud" in module_readme
    assert "does not unlock a production claim" in module_readme
    for document in public_docs:
        assert "deploy/cloud/gcp-remote-active-active" in document

import json
import os
import subprocess
import sys
from pathlib import Path

from wavemind.production_evidence_env import (
    PRODUCTION_EVIDENCE_ENV_SCHEMA,
    build_production_evidence_env_contract,
    render_production_evidence_env_example,
    render_production_evidence_env_markdown,
)


def _ready_env(tmp_path):
    return {
        "WAVEMIND_CLUSTER_NODES": ",".join(
            [
                "node-a=https://wm-a.staging.internal",
                "node-b=https://wm-b.staging.internal",
                "node-c=https://wm-c.staging.internal",
                "node-d=https://wm-d.staging.internal",
            ]
        ),
        "WAVEMIND_REMOTE_LAB_INVENTORY_JSON": json.dumps(_remote_inventory()),
        "WAVEMIND_REMOTE_SSH_PRIVATE_KEY": "test-private-key",
        "WAVEMIND_REMOTE_SSH_KNOWN_HOSTS": "test-known-hosts",
        "WAVEMIND_REMOTE_API_KEY": "test-remote-api-key",
        "WAVEMIND_REMOTE_POSTGRES_PASSWORD": "test-postgres-password",
        "WAVEMIND_SERVERLESS_NODES": "https://wm-a.staging.internal,https://wm-b.staging.internal",
        "WAVEMIND_QDRANT_URL": "http://qdrant.staging.internal:6333",
        "WAVEMIND_QDRANT_URLS": "http://qdrant-a.staging.internal:6333,http://qdrant-b.staging.internal:6333",
        "WAVEMIND_PGVECTOR_DSNS": ",".join(
            f"postgresql://user:pass@postgres-{index}.staging.internal:5432/wavemind"
            for index in range(4)
        ),
        "WAVEMIND_FAISS_IVFPQ_PATH": str(tmp_path / "wavemind-faiss-ivfpq-50m.faiss"),
        "WAVEMIND_FAISS_IVFPQ_FREE_GB": "8",
        "WAVEMIND_API_KEY": "test-key",
    }


def _remote_inventory():
    return {
        "schema": "wavemind.remote_production_lab.v1",
        "deployment_id": "wm-regions-2026-07",
        "environment": "staging",
        "source": "independent-cloud-vms",
        "image": "ghcr.io/caspiang/wavemind:sha-0123456789abcdef",
        "regions": [
            {
                "id": f"region-{index}",
                "ssh_host": f"wavemind-{index}",
                "public_url": f"https://wm-{index}.staging.internal",
                "region": f"region-{index}",
                "zone": f"zone-{index}",
                "provider": f"provider-{index}",
            }
            for index in range(3)
        ],
    }


def test_production_evidence_env_contract_maps_missing_variables():
    root = Path(__file__).resolve().parents[1]
    payload = build_production_evidence_env_contract(root, env={})

    assert payload["schema"] == PRODUCTION_EVIDENCE_ENV_SCHEMA
    assert payload["overall_status"] == "action_required"
    assert payload["summary"]["required_env_count"] >= 8
    assert "WAVEMIND_QDRANT_URL" in payload["summary"]["missing_required_env"]
    assert "WAVEMIND_API_KEY" in payload["summary"]["recommended_missing_env"]

    by_name = {row["name"]: row for row in payload["variables"]}
    cluster_nodes = by_name["WAVEMIND_CLUSTER_NODES"]
    assert cluster_nodes["status"] == "missing"
    assert "external_http_cluster" in cluster_nodes["used_by"]
    assert "external-http-cluster-load.yml" in cluster_nodes["workflows"]
    assert "benchmarks/http_cluster_load_results.json" in cluster_nodes["artifacts"]
    assert "gh secret set WAVEMIND_CLUSTER_NODES" in cluster_nodes["github_secret_command"]
    assert by_name["WAVEMIND_PGVECTOR_DSNS"]["kind"] == "postgres-dsn-list"
    assert by_name["WAVEMIND_REMOTE_LAB_INVENTORY_JSON"]["status"] == "missing"
    assert by_name["WAVEMIND_REMOTE_SSH_PRIVATE_KEY"]["required"] is True

    assert all(check["pass"] for check in payload["checks"])


def test_production_evidence_env_contract_ready_does_not_serialize_secret_values(tmp_path):
    root = Path(__file__).resolve().parents[1]
    payload = build_production_evidence_env_contract(root, env=_ready_env(tmp_path))

    assert payload["overall_status"] == "ready"
    assert payload["summary"]["missing_required_env"] == []

    serialized = json.dumps(payload, ensure_ascii=False)
    assert "postgres-0.staging.internal" not in serialized
    assert "qdrant.staging.internal" not in serialized
    assert "wm-a.staging.internal" not in serialized
    assert "test-key" not in serialized
    assert "test-private-key" not in serialized
    assert "test-remote-api-key" not in serialized
    assert "gho_" not in serialized
    assert "ghp_" not in serialized


def test_production_evidence_env_markdown_and_env_example_are_operator_facing():
    root = Path(__file__).resolve().parents[1]
    payload = build_production_evidence_env_contract(root, env={})

    markdown = render_production_evidence_env_markdown(payload)
    env_example = render_production_evidence_env_example(payload)

    assert "# WaveMind Production Evidence Environment Contract" in markdown
    assert "GitHub Secrets" in markdown
    assert "WAVEMIND_QDRANT_URL" in markdown
    assert "values are not serialized" in markdown
    assert "Do not commit real values" in env_example
    assert "WAVEMIND_QDRANT_URL=https://qdrant-10m.staging.example.com:6333" in env_example


def test_cli_production_evidence_env_writes_artifacts(tmp_path):
    project_root = Path(__file__).resolve().parents[1]
    output = tmp_path / "production_evidence_env_contract.json"
    markdown = tmp_path / "PRODUCTION_EVIDENCE_ENV.md"
    env_example = tmp_path / "production-evidence.env.example"
    env = os.environ.copy()
    env["PYTHONPATH"] = str(project_root) + os.pathsep + env.get("PYTHONPATH", "")

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "wavemind",
            "production-evidence-env",
            "--root",
            str(project_root),
            "--write-artifacts",
            "--output",
            str(output),
            "--markdown-output",
            str(markdown),
            "--env-output",
            str(env_example),
        ],
        cwd=project_root,
        env=env,
        text=True,
        encoding="utf-8",
        capture_output=True,
        check=True,
    )

    payload = json.loads(output.read_text(encoding="utf-8"))
    assert "status: action_required" in result.stdout
    assert payload["schema"] == PRODUCTION_EVIDENCE_ENV_SCHEMA
    assert "# WaveMind Production Evidence Environment Contract" in markdown.read_text(
        encoding="utf-8"
    )
    assert "WAVEMIND_QDRANT_URL=" in env_example.read_text(encoding="utf-8")


def test_cli_production_evidence_env_can_fail_on_missing():
    project_root = Path(__file__).resolve().parents[1]
    env = os.environ.copy()
    env["PYTHONPATH"] = str(project_root) + os.pathsep + env.get("PYTHONPATH", "")

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "wavemind",
            "production-evidence-env",
            "--root",
            str(project_root),
            "--fail-on-missing",
            "--json",
        ],
        cwd=project_root,
        env=env,
        text=True,
        encoding="utf-8",
        capture_output=True,
    )

    payload = json.loads(result.stdout)
    assert result.returncode == 2
    assert payload["overall_status"] == "action_required"

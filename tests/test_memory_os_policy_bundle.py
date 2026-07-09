import json
import subprocess
import sys
from pathlib import Path

from wavemind.memory_os_policy_bundle import (
    MEMORY_OS_POLICY_BUNDLE_SCHEMA,
    build_memory_os_policy_bundle,
    render_memory_os_policy_bundle_markdown,
    run_memory_os_policy_bundle,
)


def _load_fixture(name: str) -> dict:
    project_root = Path(__file__).resolve().parents[1]
    return json.loads((project_root / "benchmarks" / name).read_text(encoding="utf-8"))


def test_memory_os_policy_bundle_promotes_staging_but_locks_production():
    payload = run_memory_os_policy_bundle(root=Path(__file__).resolve().parents[1])

    assert payload["schema"] == MEMORY_OS_POLICY_BUNDLE_SCHEMA
    assert payload["status"] == "staging_ready"
    assert payload["ok"] is True
    assert payload["summary"]["staging_promotable"] is True
    assert payload["summary"]["production_promotable"] is False
    assert payload["summary"]["production_locked"] is True
    assert "hot-query-signal" in payload["summary"]["production_blocker_ids"]
    assert payload["runtime_policy"]["production_auto_enable"] is False
    assert payload["runtime_policy"]["safety"]["production_admission_required"] is True
    assert "WAVEMIND_REDIS_URL" in payload["runtime_policy"]["required_runtime_env"]
    assert "WAVEMIND_MEMORY_OS_LOCK_REDIS_URL" in payload["runtime_policy"]["required_runtime_env"]
    assert payload["kubernetes_patch"]["spec"]["productionAutoEnable"] is False


def test_memory_os_policy_bundle_allows_production_only_when_admission_is_admitted():
    canary = _load_fixture("memory_os_canary_results.json")
    evolution = _load_fixture("memory_os_policy_evolution_results.json")
    admission = _load_fixture("memory_os_admission_results.json")
    admission["status"] = "admitted"
    admission["admitted"] = True
    admission["summary"]["blocker_ids"] = []
    admission["summary"]["blocker_count"] = 0

    payload = build_memory_os_policy_bundle(
        canary=canary,
        evolution=evolution,
        admission=admission,
    )

    assert payload["status"] == "production_ready"
    assert payload["summary"]["production_promotable"] is True
    assert payload["summary"]["production_locked"] is False
    production_admission = [
        item for item in payload["checks"] if item["id"] == "production-admission"
    ][0]
    assert production_admission["status"] == "pass"


def test_memory_os_policy_bundle_markdown_includes_runtime_patch():
    payload = run_memory_os_policy_bundle(root=Path(__file__).resolve().parents[1])

    markdown = render_memory_os_policy_bundle_markdown(payload)

    assert "# WaveMind Memory OS Policy Bundle" in markdown
    assert "staging promotable" in markdown
    assert "production auto-enable" in markdown
    assert "WAVEMIND_MEMORY_OS_PRODUCTION_ADMISSION_REQUIRED" in markdown
    assert "MemoryOSPolicyBundle" in markdown


def test_memory_os_policy_bundle_cli_writes_artifacts(tmp_path):
    project_root = Path(__file__).resolve().parents[1]
    output = tmp_path / "memory_os_policy_bundle_results.json"
    markdown = tmp_path / "MEMORY_OS_POLICY_BUNDLE.md"

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "wavemind",
            "memory-os-policy-bundle",
            "--write-artifacts",
            "--output",
            str(output),
            "--markdown-output",
            str(markdown),
            "--json",
        ],
        cwd=project_root,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0
    stdout_payload = json.loads(result.stdout)
    file_payload = json.loads(output.read_text(encoding="utf-8"))
    assert stdout_payload["status"] == "staging_ready"
    assert file_payload["schema"] == MEMORY_OS_POLICY_BUNDLE_SCHEMA
    assert "WaveMind Memory OS Policy Bundle" in markdown.read_text(encoding="utf-8")


def test_memory_os_policy_bundle_cli_fail_gate_passes_when_staging_ready():
    project_root = Path(__file__).resolve().parents[1]

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "wavemind",
            "memory-os-policy-bundle",
            "--fail-on-action-required",
            "--json",
        ],
        cwd=project_root,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0
    assert json.loads(result.stdout)["status"] == "staging_ready"

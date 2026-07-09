import json
import subprocess
import sys
from pathlib import Path

from wavemind.multimodal_admission import (
    evaluate_multimodal_admission,
    render_multimodal_admission_markdown,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _write_structured_report(root: Path) -> None:
    source = PROJECT_ROOT / "benchmarks" / "structured_memory_results.json"
    target = root / "benchmarks" / "structured_memory_results.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(source.read_text(encoding="utf-8"), encoding="utf-8")


def _write_external_multimodal_evidence(
    root: Path,
    *,
    payload_count: int = 2_000,
    query_count: int = 500,
    query_p99_ms: float = 120.0,
    precision_at_1: float = 0.94,
    cross_modal_precision_at_1: float = 0.93,
) -> Path:
    artifact = root / "benchmarks" / "multimodal_external_encoder_results.json"
    artifact.parent.mkdir(parents=True, exist_ok=True)
    artifact.write_text(
        json.dumps(
            {
                "schema": "wavemind.multimodal_external_encoder_benchmark.v1",
                "source": "github-actions-external-multimodal-encoder",
                "deployment": "staging",
                "environment": "staging",
                "node_mode": "external",
                "object_store": "s3",
                "embedding_backends": [
                    "clip",
                    "audio-encoder",
                    "video-encoder",
                    "3d-encoder",
                ],
                "modalities": ["image", "audio", "video", "3d", "table", "event", "graph"],
                "modality_count": 7,
                "payload_count": payload_count,
                "query_count": query_count,
                "metrics": {
                    "precision_at_1": precision_at_1,
                    "cross_modal_precision_at_1": cross_modal_precision_at_1,
                    "target_modality_routing_rate": 0.99,
                    "vector_persistence_rate": 1.0,
                    "provenance_rate": 1.0,
                    "object_store_verified_rate": 1.0,
                    "dimension_match_rate": 1.0,
                    "finite_vector_rate": 1.0,
                    "normalized_vector_rate": 1.0,
                    "query_p99_ms": query_p99_ms,
                    "payload_encode_p95_ms": 75.0,
                    "query_encode_p95_ms": 35.0,
                    "error_rate": 0.0,
                },
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return artifact


def test_multimodal_admission_blocks_without_external_evidence():
    payload = evaluate_multimodal_admission(PROJECT_ROOT, allow_plan_only=False)

    assert payload["schema"] == "wavemind.multimodal_admission.v1"
    assert payload["status"] == "blocked"
    assert payload["admitted"] is False
    assert payload["claim_boundary"] == "external_multimodal_encoder_evidence_required"
    assert payload["structured_contract"]["status"] == "pass"
    assert payload["required_evidence"]["id"] == "external_multimodal_encoder"
    assert payload["required_evidence"]["status"] == "action_required"
    assert payload["required_evidence"]["artifact"] == (
        "benchmarks/multimodal_external_encoder_results.json"
    )
    assert payload["summary"]["requested_evidence_status"] == "action_required"
    assert any("requested_evidence_status=action_required" in item for item in payload["issues"])


def test_multimodal_admission_allows_plan_only_reporting():
    payload = evaluate_multimodal_admission(PROJECT_ROOT, allow_plan_only=True)

    assert payload["status"] == "plan_only"
    assert payload["admitted"] is False
    assert payload["summary"]["structured_status"] == "pass"
    assert payload["summary"]["structured_pass"] is True
    assert payload["next_actions"]


def test_multimodal_admission_admits_matching_external_evidence(tmp_path):
    _write_structured_report(tmp_path)
    _write_external_multimodal_evidence(tmp_path)

    payload = evaluate_multimodal_admission(
        tmp_path,
        min_modalities=7,
        min_payloads=1000,
        min_queries=200,
        min_precision_at_1=0.90,
        min_cross_modal_precision_at_1=0.90,
        max_query_p99_ms=250.0,
        max_encode_p95_ms=100.0,
    )

    assert payload["status"] == "admitted"
    assert payload["admitted"] is True
    assert payload["summary"]["structured_status"] == "pass"
    assert payload["summary"]["requested_evidence_status"] == "pass"
    assert payload["requested_evidence"]["status"] == "pass"
    assert payload["issues"] == []


def test_multimodal_admission_blocks_small_or_slow_external_evidence(tmp_path):
    _write_structured_report(tmp_path)
    _write_external_multimodal_evidence(
        tmp_path,
        payload_count=100,
        query_count=20,
        query_p99_ms=900.0,
        precision_at_1=0.70,
        cross_modal_precision_at_1=0.60,
    )

    payload = evaluate_multimodal_admission(
        tmp_path,
        min_payloads=1000,
        min_queries=200,
        min_precision_at_1=0.90,
        min_cross_modal_precision_at_1=0.90,
        max_query_p99_ms=250.0,
        allow_plan_only=True,
    )

    assert payload["status"] == "plan_only"
    assert payload["admitted"] is False
    assert payload["summary"]["requested_evidence_status"] == "fail"
    assert "payload_count must be >= 1000" in payload["requested_evidence"]["issues"]
    assert "query_count must be >= 200" in payload["requested_evidence"]["issues"]
    assert "query_p99_ms must be <= 250.000" in payload["requested_evidence"]["issues"]
    assert "precision_at_1 must be >= 0.900" in payload["requested_evidence"]["issues"]


def test_multimodal_admission_markdown_documents_boundary():
    payload = evaluate_multimodal_admission(PROJECT_ROOT, allow_plan_only=True)
    markdown = render_multimodal_admission_markdown(payload)

    assert "# WaveMind Multimodal Admission" in markdown
    assert "production-ready" in markdown
    assert "benchmarks/multimodal_external_encoder_results.json" in markdown
    assert "external encoder run" in markdown
    assert "Requested Evidence" in markdown


def test_multimodal_admission_cli_writes_artifacts(tmp_path):
    output = tmp_path / "multimodal.json"
    markdown_output = tmp_path / "multimodal.md"

    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "wavemind",
            "multimodal-admission",
            "--root",
            str(PROJECT_ROOT),
            "--allow-plan-only",
            "--write-artifacts",
            "--output",
            str(output),
            "--markdown-output",
            str(markdown_output),
            "--json",
        ],
        cwd=PROJECT_ROOT,
        text=True,
        encoding="utf-8",
        capture_output=True,
        check=True,
    )

    stdout_payload = json.loads(completed.stdout)
    file_payload = json.loads(output.read_text(encoding="utf-8"))
    assert stdout_payload["status"] == "plan_only"
    assert file_payload["schema"] == "wavemind.multimodal_admission.v1"
    assert file_payload["status"] == "plan_only"
    assert markdown_output.read_text(encoding="utf-8").startswith(
        "# WaveMind Multimodal Admission"
    )


def test_multimodal_admission_cli_fail_on_blocked_exits_nonzero():
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "wavemind",
            "multimodal-admission",
            "--root",
            str(PROJECT_ROOT),
            "--fail-on-blocked",
            "--json",
        ],
        cwd=PROJECT_ROOT,
        text=True,
        encoding="utf-8",
        capture_output=True,
        check=False,
    )

    payload = json.loads(completed.stdout)
    assert completed.returncode == 2
    assert payload["status"] == "blocked"
    assert payload["admitted"] is False

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
    source_type: str = "real_public_assets",
    image_backend: str = "open-clip",
) -> Path:
    artifact = root / "benchmarks" / "multimodal_external_encoder_results.json"
    artifact.parent.mkdir(parents=True, exist_ok=True)
    modalities = ["text", "image", "audio", "video", "3d"]
    modality_metrics = {
        modality: {
            "asset_count": 200,
            "query_count": 40,
            "precision_at_1": 0.92,
            "encode_p95_ms": {
                "text": 90.0,
                "image": 180.0,
                "audio": 600.0,
                "video": 1_500.0,
                "3d": 800.0,
            }[modality],
            "encoder_backend": (
                image_backend
                if modality in {"text", "image", "video", "3d"}
                else "laion-clap"
            ),
            "model_revision": "0123456789abcdef",
            "shared_space_ids": (
                ["clip-space", "clap-space"]
                if modality == "text"
                else ["clap-space"]
                if modality == "audio"
                else ["clip-space"]
            ),
        }
        for modality in modalities
    }
    pairs = []
    for other, space in (
        ("image", "clip-space"),
        ("audio", "clap-space"),
        ("video", "clip-space"),
        ("3d", "clip-space"),
    ):
        pairs.extend(
            [
                {
                    "query_modality": "text",
                    "target_modality": other,
                    "query_count": 25,
                    "precision_at_1": 0.92,
                    "shared_space_id": space,
                },
                {
                    "query_modality": other,
                    "target_modality": "text",
                    "query_count": 25,
                    "precision_at_1": 0.91,
                    "shared_space_id": space,
                },
            ]
        )
    artifact.write_text(
        json.dumps(
            {
                "schema": "wavemind.multimodal_encoder_benchmark.v2",
                "source": "local-open-source-multimodal-benchmark",
                "source_sha": "a" * 40,
                "deployment": "local-evidence",
                "environment": "local",
                "asset_source": source_type,
                "object_store": "minio-s3-compatible",
                "object_store_backend": "minio",
                "dataset": {
                    "name": "public-multimodal-suite",
                    "revision": "2026-07-pinned",
                    "license": "mixed-public-licenses",
                    "asset_source": source_type,
                    "manifest_sha256": "b" * 64,
                    "ground_truth_sha256": "c" * 64,
                },
                "environment_fingerprint": {
                    "python": "3.11.9",
                    "platform": "windows-amd64",
                    "hardware": "cpu-test-profile",
                    "dependency_lock_sha256": "d" * 64,
                },
                "modalities": modalities,
                "modality_count": len(modalities),
                "payload_count": payload_count,
                "query_count": query_count,
                "shared_spaces": {
                    "clip-space": {
                        "modalities": ["text", "image", "video", "3d"],
                    },
                    "clap-space": {
                        "modalities": ["text", "audio"],
                    },
                },
                "modality_metrics": modality_metrics,
                "cross_modal_pairs": pairs,
                "lifecycle": {
                    "object_store_backend": "minio",
                    "object_store_pass": True,
                    "ingest_pass": True,
                    "checksum_pass": True,
                    "reload_pass": True,
                    "persistence_pass": True,
                    "namespace_isolation_pass": True,
                    "ttl_pass": True,
                    "physical_delete_pass": True,
                    "tombstone_pass": True,
                    "backup_restore_pass": True,
                    "orphan_cleanup_pass": True,
                },
                "leakage_checks": {
                    "pass": True,
                    "filename_leakage": False,
                    "caption_leakage": False,
                    "id_leakage": False,
                    "metadata_leakage": False,
                },
                "repeatability": {
                    "run_count": 3,
                    "stable_verdict": True,
                    "verdicts": ["pass", "pass", "pass"],
                },
                "evidence_files": {
                    "per_query": {
                        "path": "benchmarks/multimodal_per_query.jsonl",
                        "sha256": "e" * 64,
                    },
                    "per_asset": {
                        "path": "benchmarks/multimodal_per_asset.jsonl",
                        "sha256": "f" * 64,
                    },
                },
                "metrics": {
                    "macro_precision_at_1": precision_at_1,
                    "cross_modal_precision_at_1": cross_modal_precision_at_1,
                    "mixed_multimodal_precision_at_1": 0.91,
                    "persisted_vector_parity": 1.0,
                    "retrieval_p99_ms": query_p99_ms,
                    "query_p99_ms": 5_000.0,
                    "batch_throughput_assets_per_second": 12.5,
                    "error_rate": 0.0,
                },
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return artifact


def test_multimodal_admission_blocks_without_external_evidence(tmp_path):
    _write_structured_report(tmp_path)
    payload = evaluate_multimodal_admission(tmp_path, allow_plan_only=False)

    assert payload["schema"] == "wavemind.multimodal_admission.v2"
    assert payload["status"] == "blocked"
    assert payload["admitted"] is False
    assert payload["claim_boundary"] == (
        "real_multimodal_encoder_and_lifecycle_evidence_required"
    )
    assert payload["structured_contract"]["status"] == "pass"
    assert payload["required_evidence"]["id"] == "real_multimodal_encoder"
    assert payload["required_evidence"]["status"] == "action_required"
    assert payload["required_evidence"]["artifact"] == (
        "benchmarks/multimodal_external_encoder_results.json"
    )
    assert payload["summary"]["requested_evidence_status"] == "action_required"
    assert any("requested_evidence_status=action_required" in item for item in payload["issues"])


def test_multimodal_admission_allows_plan_only_reporting(tmp_path):
    _write_structured_report(tmp_path)
    payload = evaluate_multimodal_admission(tmp_path, allow_plan_only=True)

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
        min_modalities=5,
        min_payloads=1000,
        min_queries=200,
        min_precision_at_1=0.90,
        min_cross_modal_precision_at_1=0.90,
        max_query_p99_ms=250.0,
    )

    assert payload["status"] == "admitted"
    assert payload["admitted"] is True
    assert payload["schema"] == "wavemind.multimodal_admission.v2"
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
    assert (
        "retrieval_p99_ms must be <= 250.000"
        in payload["requested_evidence"]["issues"]
    )
    assert "macro precision_at_1 must be >= 0.900" in payload["requested_evidence"]["issues"]


def test_multimodal_admission_rejects_descriptor_or_synthetic_shortcuts(tmp_path):
    _write_structured_report(tmp_path)
    _write_external_multimodal_evidence(
        tmp_path,
        source_type="synthetic",
        image_backend="descriptor-hash",
    )

    payload = evaluate_multimodal_admission(tmp_path)

    assert payload["status"] == "blocked"
    assert payload["admitted"] is False
    issues = payload["requested_evidence"]["issues"]
    assert "asset_source must identify real or publicly licensed assets" in issues
    assert any("image backend must be real" in issue for issue in issues)


def test_multimodal_admission_rejects_incompatible_shared_space(tmp_path):
    _write_structured_report(tmp_path)
    artifact = _write_external_multimodal_evidence(tmp_path)
    evidence = json.loads(artifact.read_text(encoding="utf-8"))
    evidence["cross_modal_pairs"][0]["shared_space_id"] = "clap-space"
    artifact.write_text(json.dumps(evidence, indent=2) + "\n", encoding="utf-8")

    payload = evaluate_multimodal_admission(tmp_path)

    assert payload["status"] == "blocked"
    assert any(
        "text_to_image must use one explicit compatible shared space" in issue
        for issue in payload["requested_evidence"]["issues"]
    )


def test_multimodal_admission_markdown_documents_boundary():
    payload = evaluate_multimodal_admission(PROJECT_ROOT, allow_plan_only=True)
    markdown = render_multimodal_admission_markdown(payload)

    assert "# WaveMind Multimodal Admission" in markdown
    assert "production-ready" in markdown
    assert "benchmarks/multimodal_external_encoder_results.json" in markdown
    assert "local open-source encoder run" in markdown
    assert "Local MinIO is valid" in markdown
    assert "Requested Evidence" in markdown


def test_checked_repository_multimodal_admission_is_admitted():
    payload = evaluate_multimodal_admission(PROJECT_ROOT)

    assert payload["status"] == "admitted"
    assert payload["admitted"] is True
    assert payload["summary"]["requested_evidence_status"] == "pass"
    assert payload["issues"] == []


def test_multimodal_admission_cli_writes_artifacts(tmp_path):
    root = tmp_path / "root"
    _write_structured_report(root)
    output = tmp_path / "multimodal.json"
    markdown_output = tmp_path / "multimodal.md"

    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "wavemind",
            "multimodal-admission",
            "--root",
            str(root),
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
    assert file_payload["schema"] == "wavemind.multimodal_admission.v2"
    assert file_payload["status"] == "plan_only"
    assert markdown_output.read_text(encoding="utf-8").startswith(
        "# WaveMind Multimodal Admission"
    )


def test_multimodal_admission_cli_fail_on_blocked_exits_nonzero(tmp_path):
    root = tmp_path / "root"
    _write_structured_report(root)
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "wavemind",
            "multimodal-admission",
            "--root",
            str(root),
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

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from wavemind import (
    EXTERNAL_MULTIMODAL_SCHEMA,
    evaluate_multimodal_admission,
    render_external_multimodal_evidence_markdown,
    run_external_multimodal_evidence,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _one_hot(index: int, dim: int = 7) -> list[float]:
    return [1.0 if item == index else 0.0 for item in range(dim)]


def _manifest(tmp_path: Path, *, object_store: str = "s3") -> Path:
    modalities = ["image", "audio", "video", "3d", "table", "event", "graph"]
    manifest = {
        "schema": "wavemind.multimodal_external_manifest.v1",
        "source": "external-encoder-ci",
        "deployment": "staging",
        "environment": "staging",
        "object_store": object_store,
        "object_store_verification_mode": "manifest",
        "encoder_name": "external-fixture-clip-audio-video-3d",
        "vector_dim": 7,
        "encoder_metrics": {
            "payload_encode_p95_ms": 42.0,
            "query_encode_p95_ms": 18.0,
        },
        "assets": [
            {
                "id": f"{modality}-asset",
                "modality": modality,
                "uri": f"{object_store}://wavemind-assets/external/{modality}.bin",
                "text": f"{modality} production payload",
                "vector": _one_hot(index),
                "verified": True,
                "total_bytes": 128 + index,
                "sha256": f"{index:064x}",
                "media_type": "application/octet-stream",
            }
            for index, modality in enumerate(modalities)
        ],
        "queries": [
            {
                "id": f"query-{modality}",
                "text": f"find the {modality} production payload",
                "target_asset_id": f"{modality}-asset",
                "target_modality": modality,
                "vector": _one_hot(index),
            }
            for index, modality in enumerate(modalities)
        ],
    }
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return path


def _copy_structured_report(root: Path) -> None:
    source = PROJECT_ROOT / "benchmarks" / "structured_memory_results.json"
    target = root / "benchmarks" / "structured_memory_results.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(source.read_text(encoding="utf-8"), encoding="utf-8")


def test_external_multimodal_evidence_runner_generates_admission_artifact(tmp_path):
    manifest = _manifest(tmp_path)

    payload = run_external_multimodal_evidence(manifest)

    assert payload["schema"] == EXTERNAL_MULTIMODAL_SCHEMA
    assert payload["status"] == "pass"
    assert payload["source"] == "external-encoder-ci"
    assert payload["deployment"] == "staging"
    assert payload["environment"] == "staging"
    assert payload["object_store"] == "s3"
    assert payload["object_store_verification_mode"] == "manifest"
    assert payload["modality_count"] == 7
    assert payload["payload_count"] == 7
    assert payload["query_count"] == 7
    assert payload["metrics"]["precision_at_1"] == 1.0
    assert payload["metrics"]["precision_at_3"] == 1.0
    assert payload["metrics"]["cross_modal_precision_at_1"] == 1.0
    assert payload["metrics"]["target_modality_routing_rate"] == 1.0
    assert payload["metrics"]["vector_persistence_rate"] == 1.0
    assert payload["metrics"]["provenance_rate"] == 1.0
    assert payload["metrics"]["object_store_verified_rate"] == 1.0
    assert payload["metrics"]["dimension_match_rate"] == 1.0
    assert payload["metrics"]["finite_vector_rate"] == 1.0
    assert payload["metrics"]["normalized_vector_rate"] == 1.0
    assert payload["metrics"]["payload_encode_p95_ms"] == 42.0
    assert payload["metrics"]["query_encode_p95_ms"] == 18.0
    assert payload["metrics"]["error_rate"] == 0.0
    assert payload["errors"] == []


def test_external_multimodal_evidence_unblocks_admission_when_thresholds_match(tmp_path):
    manifest = _manifest(tmp_path)
    output = tmp_path / "benchmarks" / "multimodal_external_encoder_results.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(run_external_multimodal_evidence(manifest), indent=2) + "\n",
        encoding="utf-8",
    )
    _copy_structured_report(tmp_path)

    admission = evaluate_multimodal_admission(
        tmp_path,
        min_modalities=7,
        min_payloads=7,
        min_queries=7,
        min_precision_at_1=0.90,
        min_cross_modal_precision_at_1=0.90,
        max_query_p99_ms=250.0,
        max_encode_p95_ms=100.0,
    )

    assert admission["status"] == "admitted"
    assert admission["admitted"] is True
    assert admission["summary"]["requested_evidence_status"] == "pass"


def test_external_multimodal_evidence_fails_without_object_store(tmp_path):
    manifest = _manifest(tmp_path, object_store="file")

    payload = run_external_multimodal_evidence(manifest)

    assert payload["status"] == "fail"
    assert payload["metrics"]["object_store_verified_rate"] == 0.0
    assert "all assets must use s3:// object-store URIs" in payload["errors"]
    assert "manifest.object_store must identify an s3-compatible object store" in payload["errors"]


def test_external_multimodal_evidence_markdown_documents_metrics(tmp_path):
    payload = run_external_multimodal_evidence(_manifest(tmp_path))

    markdown = render_external_multimodal_evidence_markdown(payload)

    assert "# WaveMind External Multimodal Evidence" in markdown
    assert "object-store verified" in markdown
    assert "cross-modal precision@1" in markdown
    assert "`wavemind multimodal-admission`" in markdown


def test_external_multimodal_evidence_cli_writes_artifacts(tmp_path):
    output = tmp_path / "external.json"
    markdown_output = tmp_path / "external.md"

    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "wavemind",
            "multimodal-external-evidence",
            "--manifest",
            str(_manifest(tmp_path)),
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
    assert stdout_payload["status"] == "pass"
    assert file_payload["schema"] == EXTERNAL_MULTIMODAL_SCHEMA
    assert markdown_output.read_text(encoding="utf-8").startswith(
        "# WaveMind External Multimodal Evidence"
    )


def test_external_multimodal_evidence_cli_fail_on_error_exits_nonzero(tmp_path):
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "wavemind",
            "multimodal-external-evidence",
            "--manifest",
            str(_manifest(tmp_path, object_store="file")),
            "--fail-on-error",
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
    assert payload["status"] == "fail"

from pathlib import Path

from wavemind.evidence import attach_artifact_integrity
from wavemind.safe_retrieval_admission import (
    evaluate_safe_retrieval_admission,
    render_safe_retrieval_markdown,
    validate_safe_retrieval_artifact,
)


ROOT = Path(__file__).resolve().parents[1]
DATASET = ROOT / "benchmarks" / "data" / "safe_product_retrieval_v2_heldout.json"


def test_safe_retrieval_admission_passes_frozen_controls() -> None:
    report = evaluate_safe_retrieval_admission(DATASET, project_root=ROOT)

    assert report["status"] == "admitted"
    assert report["metrics"]["false_memory_injection_rate"] <= 0.02
    assert report["metrics"]["namespace_leakage"] == 0
    assert report["metrics"]["unverified_injection"] == 0
    assert report["metrics"]["relevant_recall_ratio"] >= 0.95
    assert len(report["source_sha"]) == 40
    assert report["integrity"]["algorithm"] == "sha256"


def test_safe_retrieval_report_discloses_metrics_and_provenance() -> None:
    report = evaluate_safe_retrieval_admission(DATASET, project_root=ROOT)
    markdown = render_safe_retrieval_markdown(report)

    assert "False memory injection" in markdown
    assert "Namespace leakage" in markdown
    assert report["dataset_revision"] in markdown
    assert report["source_sha"] in markdown


def test_safe_retrieval_validator_rejects_wrong_sha_and_tampering() -> None:
    report = evaluate_safe_retrieval_admission(DATASET, project_root=ROOT)
    assert validate_safe_retrieval_artifact(
        report,
        project_root=ROOT,
        expected_source_sha=report["source_sha"],
    ) == []

    wrong_sha = dict(report)
    wrong_sha["source_sha"] = "0" * 40
    wrong_sha = attach_artifact_integrity(wrong_sha)
    assert "safe retrieval source SHA mismatch" in validate_safe_retrieval_artifact(
        wrong_sha,
        project_root=ROOT,
        expected_source_sha=report["source_sha"],
    )

    tampered = dict(report)
    tampered["metrics"] = dict(report["metrics"])
    tampered["metrics"]["false_memory_injection_rate"] = 0.5
    errors = validate_safe_retrieval_artifact(
        tampered,
        project_root=ROOT,
        expected_source_sha=report["source_sha"],
    )
    assert "artifact payload digest mismatch" in errors
    assert "false memory injection exceeds 2 percent" in errors

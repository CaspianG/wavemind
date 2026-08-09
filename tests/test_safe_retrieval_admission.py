from pathlib import Path

from wavemind.safe_retrieval_admission import (
    evaluate_safe_retrieval_admission,
    render_safe_retrieval_markdown,
)


ROOT = Path(__file__).resolve().parents[1]
DATASET = ROOT / "benchmarks" / "data" / "safe_product_retrieval_v1.json"


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

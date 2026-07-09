import json
import subprocess
import sys
from pathlib import Path


def test_structured_memory_report_generates_gate_artifacts(tmp_path):
    output = tmp_path / "structured_memory_results.json"
    markdown_output = tmp_path / "STRUCTURED_MEMORY.md"
    project_root = Path(__file__).resolve().parents[1]

    subprocess.run(
        [
            sys.executable,
            "benchmarks/structured_memory_report.py",
            "--output",
            str(output),
            "--markdown-output",
            str(markdown_output),
        ],
        cwd=project_root,
        text=True,
        encoding="utf-8",
        capture_output=True,
        check=True,
    )

    payload = json.loads(output.read_text(encoding="utf-8"))
    markdown = markdown_output.read_text(encoding="utf-8")

    assert payload["schema"] == "wavemind.structured_memory_report.v1"
    assert payload["source_file"] == "benchmarks/scale_readiness_results.json"
    assert payload["summary"]["status"] == "pass"
    assert payload["summary"]["modality_count"] == 7
    assert payload["summary"]["modalities"] == [
        "image",
        "audio",
        "table",
        "event",
        "video",
        "3d",
        "graph",
    ]
    assert payload["summary"]["precision_at_1"] == 1.0
    assert payload["summary"]["cross_modal_precision_at_1"] == 1.0
    assert payload["summary"]["cross_modal_vectors_persisted_rate"] == 1.0
    assert payload["summary"]["cross_modal_provenance_rate"] == 1.0
    assert payload["summary"]["precomputed_vector_precision_at_1"] == 1.0
    assert payload["summary"]["precomputed_vector_persisted_rate"] == 1.0
    assert payload["summary"]["encoder_contract_ok"] is True
    assert payload["summary"]["encoder_contract_margin"] >= (
        payload["summary"]["encoder_contract_min_required_margin"]
    )
    assert payload["summary"]["temporal_event_precision_at_1"] == 1.0
    assert payload["summary"]["temporal_event_persistence_rate"] == 1.0
    assert payload["summary"]["temporal_event_provenance_rate"] == 1.0
    assert payload["summary"]["knowledge_graph_precision_at_1"] == 1.0
    assert payload["summary"]["knowledge_graph_path_precision_at_1"] == 1.0
    assert payload["summary"]["knowledge_graph_persistence_rate"] == 1.0
    assert payload["summary"]["knowledge_graph_provenance_rate"] == 1.0
    assert payload["summary"]["cross_modal_avg_latency_ms"] < 5.0
    assert payload["summary"]["temporal_event_avg_latency_ms"] < 5.0
    assert payload["summary"]["knowledge_graph_avg_latency_ms"] < 5.0
    assert payload["summary"]["asset_manifest_verified"] is True
    assert len(payload["checks"]) >= 19
    assert all(check["pass"] for check in payload["checks"])
    assert "production multimodal model quality" in payload["claim_boundary"]
    assert "# WaveMind Structured Memory Report" in markdown
    assert "Knowledge-graph precision@1" in markdown


def test_checked_in_structured_memory_report_is_fresh_and_passing():
    project_root = Path(__file__).resolve().parents[1]
    payload = json.loads(
        (project_root / "benchmarks/structured_memory_results.json").read_text(
            encoding="utf-8"
        )
    )
    markdown = (project_root / "benchmarks/STRUCTURED_MEMORY.md").read_text(
        encoding="utf-8"
    )

    assert payload["summary"]["status"] == "pass"
    assert payload["summary"]["modality_count"] == 7
    assert payload["summary"]["cross_modal_precision_at_1"] == 1.0
    assert payload["summary"]["knowledge_graph_path_precision_at_1"] == 1.0
    assert "Run the same contract on real CLIP/audio/video/3D production encoders" in markdown

import json
import subprocess
import sys
from pathlib import Path


def test_leaderboard_status_renderer_writes_public_contract(tmp_path):
    output = tmp_path / "leaderboard-status.json"
    project_root = Path(__file__).resolve().parents[1]

    subprocess.run(
        [
            sys.executable,
            "benchmarks/render_leaderboard_status.py",
            "--output",
            str(output),
        ],
        cwd=project_root,
        text=True,
        encoding="utf-8",
        capture_output=True,
        check=True,
    )

    payload = json.loads(output.read_text(encoding="utf-8"))

    assert payload["schema"] == "wavemind.leaderboard_status.v1"
    assert payload["public_url"] == "https://caspiang.github.io/wavemind/"
    assert payload["publishing_status"] == "publishable_with_claim_limits"
    assert payload["benchmark_matrix"]["schema"] == "wavemind.benchmark_matrix.v1"
    assert payload["benchmark_matrix"]["implemented_count"] >= 20
    assert payload["benchmark_matrix"]["runner_ready_count"] >= 1
    assert payload["benchmark_matrix"]["planned_count"] >= 1
    assert payload["artifact_audit"]["status"] == "pass"
    assert payload["production_readiness"]["overall_status"] == "pass"
    assert payload["production_readiness"]["readiness_score"] == 1.0
    assert payload["strict_production_evidence"]["overall_status"] == "action_required"
    assert payload["strict_production_evidence"]["summary"]["total_requirements"] == 8
    assert payload["strict_production_evidence"]["action_required"]
    assert payload["production_evidence_bundle"]["schema"] == (
        "wavemind.production_evidence_bundle.v1"
    )
    assert payload["production_evidence_bundle"]["claim_status"] == "claims_limited"
    assert payload["production_evidence_bundle"]["next_action_count"] == 8
    assert payload["production_evidence_bundle"]["production_scale_run_contract"]["status"] == "available"
    assert payload["release_claims"]["schema"] == "wavemind.release_claims.v1"
    assert payload["release_claims"]["release_status"] == "core_release_ready"
    assert payload["release_claims"]["claim_status"] == "claims_limited"
    assert payload["release_claims"]["summary"]["allowed_claim_count"] >= 1
    assert payload["release_claims"]["summary"]["locked_claim_count"] >= 1
    assert any(
        row["claim"] == "10M-100M service-backed production scale"
        for row in payload["release_claims"]["locked_claims"]
    )
    assert payload["production_scale_run_plan"]["schema"] == "wavemind.production_scale_run_plan.v1"
    assert payload["production_scale_run_plan"]["total_profiles"] == 5
    assert payload["production_scale_run_plan"]["target_memories_total"] == 180_000_000
    assert "qdrant-sharded-100m" in payload["production_scale_run_plan"]["profiles"]
    assert {
        "external_http_active_active",
        "qdrant_sharded_10m_service",
        "hundred_million_remote_load",
    }.issubset(
        {entry["id"] for entry in payload["strict_production_evidence"]["action_required"]}
    )
    assert "benchmarks/benchmark_matrix_results.json" in payload["source_files"]
    assert "benchmarks/production_evidence_results.json" in payload["source_files"]
    assert "benchmarks/production_evidence_bundle_results.json" in payload["source_files"]
    assert "benchmarks/release_claims_results.json" in payload["source_files"]
    assert "benchmarks/production_scale_run_plan.json" in payload["source_files"]
    assert payload["load_errors"] == []


def test_checked_in_leaderboard_status_is_present_and_machine_readable():
    payload = json.loads(
        Path("docs/data/leaderboard-status.json").read_text(encoding="utf-8")
    )

    assert payload["schema"] == "wavemind.leaderboard_status.v1"
    assert payload["publishing_status"] in {
        "publishable",
        "publishable_with_claim_limits",
    }
    assert payload["artifact_audit"]["status"] == "pass"
    assert payload["production_readiness"]["overall_status"] == "pass"
    assert payload["production_evidence_bundle"]["claim_status"] in {
        "claims_limited",
        "claims_unlocked",
    }
    assert payload["release_claims"]["release_status"] in {
        "core_release_ready",
        "full_production_claims_ready",
    }
    assert payload["production_scale_run_plan"]["schema"] == "wavemind.production_scale_run_plan.v1"

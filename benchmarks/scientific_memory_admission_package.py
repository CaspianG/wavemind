from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path
from typing import Any, Mapping

from wavemind.evidence import (
    attach_artifact_integrity,
    file_sha256,
    validate_artifact_integrity,
)


SCHEMA = "wavemind.scientific_memory_admission_package.v1"


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _record(path: Path, root: Path) -> dict[str, Any]:
    resolved = path.resolve()
    return {
        "path": (
            resolved.relative_to(root).as_posix()
            if resolved.is_relative_to(root)
            else str(resolved)
        ),
        "bytes": resolved.stat().st_size,
        "sha256": file_sha256(resolved),
    }


def build_package_manifest(root: Path, source_sha: str) -> dict[str, Any]:
    benchmarks = root / "benchmarks"
    development_path = benchmarks / "scientific_development_evidence_results.json"
    development = _load(development_path)
    errors = validate_artifact_integrity(development)
    if errors or development.get("status") != "failed_experiment":
        raise ValueError("terminal development evidence is missing or invalid")
    state_path = benchmarks / "scientific_state_bench_prepared_dev_results.json"
    state = _load(state_path)
    protocol_path = benchmarks / "scientific_memory_protocol_v1.json"
    evidence_paths = [
        protocol_path,
        benchmarks / "scientific_official_runner_manifest_v1.json",
        benchmarks / "scientific_memoryagentbench_baseline_dev_raw.jsonl",
        benchmarks / "scientific_memoryagentbench_baseline_dev_results.json",
        benchmarks / "scientific_memoryagentbench_causal_multicluster_dev_raw.jsonl",
        benchmarks / "scientific_memoryagentbench_causal_multicluster_dev_results.json",
        benchmarks / "scientific_memoryagentbench_graph_multicluster_dev_raw.jsonl",
        benchmarks / "scientific_memoryagentbench_graph_multicluster_dev_results.json",
        benchmarks / "scientific_memops_candidate_dev_results.json",
        benchmarks / "scientific_memops_graph_candidate_dev_results.json",
        state_path,
        development_path,
        benchmarks / "scientific_memoryagentbench_candidate_failed_attempts.jsonl",
        benchmarks / "scientific_memoryagentbench_baseline_failed_attempts.jsonl",
    ]
    external_raw = [
        Path(candidate["memops"]["raw_path"])
        for candidate in development["candidates"].values()
    ]
    if not all(path.is_file() for path in [*evidence_paths, *external_raw]):
        raise FileNotFoundError("scientific admission evidence file is missing")
    candidate_results = {
        candidate_id: {
            "status": "failed_experiment",
            "advance_to_validation": evidence["advance_to_validation"],
            "memoryagentbench_paired_uplift": evidence["memoryagentbench"][
                "paired_cluster_bootstrap"
            ],
            "memops_observed_mean_effect": evidence["memops"]["observed_mean_effect"],
            "memops_confidence_interval_status": evidence["memops"][
                "confidence_interval_status"
            ],
            "production_case_count": (
                evidence["memoryagentbench"]["production_case_count"]
                + evidence["memops"]["production_case_count"]
            ),
            "promoted_memory_ids": sorted(
                set(evidence["memoryagentbench"]["promoted_memory_ids"])
                | set(evidence["memops"]["promoted_memory_ids"])
            ),
            "false_verified_promotions": (
                evidence["memoryagentbench"]["false_verified_promotions"]
                + evidence["memops"]["false_verified_promotions"]
            ),
        }
        for candidate_id, evidence in development["candidates"].items()
    }
    return attach_artifact_integrity(
        {
            "schema": SCHEMA,
            "source_sha": source_sha,
            "protocol_digest": development["protocol_digest"],
            "status": "failed_experiment",
            "admitted": False,
            "candidate_results": candidate_results,
            "official_upstreams": {
                "memoryagentbench": "fe1735de8cf8b9908e1e3d3b5612afc815698062",
                "memops": "312af65e2c7b6d1b70f062ffa8b4cde32aaf6f35",
                "state-bench": state["official_upstream"]["sha"],
                "longmemeval-v2": "2cc8c540bdb87fe6761629b585e727e1c4704520",
            },
            "held_out_execution": {
                "three_reproducible_runs_completed": False,
                "state_bench_official_execution_completed": False,
                "longmemeval_v2_full_451_completed": False,
                "validation_or_final_rows_touched": False,
                "reason": (
                    "Both preregistered candidates failed bounded development; "
                    "no passed development gate exists, so held-out execution is "
                    "forbidden rather than missing-at-random."
                ),
            },
            "evidence_files": [_record(path, root) for path in evidence_paths],
            "external_retained_raw_files": [
                _record(path, root) for path in external_raw
            ],
            "reproduction": {
                "python": "scientific-env/Scripts/python.exe",
                "commands": [
                    "python -m pytest tests/test_scientific_*.py -q",
                    (
                        "python benchmarks/scientific_development_evidence.py "
                        "--output <fresh-output.json>"
                    ),
                    (
                        "python benchmarks/scientific_memory_admission_package.py "
                        "--output-dir <fresh-directory>"
                    ),
                ],
            },
            "claim_boundary": (
                "The frozen scientific candidates are not admitted. Public WaveField "
                "descriptions and WaveMind Connect remain unchanged; no SOTA or "
                "revolutionary claim is allowed."
            ),
        }
    )


def _markdown(manifest: Mapping[str, Any]) -> str:
    rows = []
    for candidate_id, result in manifest["candidate_results"].items():
        interval = result["memoryagentbench_paired_uplift"]
        rows.append(
            f"| `{candidate_id}` | failed_experiment | "
            f"{interval['mean_difference']:.3f} "
            f"[{interval['ci_lower']:.3f}, {interval['ci_upper']:.3f}] | "
            f"{result['memops_observed_mean_effect']:.3f} |"
        )
    return "\n".join(
        [
            "# Scientific Memory Admission",
            "",
            "Status: **failed_experiment** (not admitted).",
            "",
            f"Exact package source SHA: `{manifest['source_sha']}`  ",
            f"Frozen protocol digest: `{manifest['protocol_digest']}`",
            "",
            "| Candidate | Decision | MAB mean [95% CI] | MemOps mean |",
            "|---|---:|---:|---:|",
            *rows,
            "",
            "STATE-Bench was prepared but not executed because official credentials "
            "were absent. LongMemEval-V2 451 and held-out validation remained "
            "untouched because no development gate passed. The missing three-run "
            "admission evidence is therefore an enforced stop-rule outcome.",
            "",
            f"> {manifest['claim_boundary']}",
            "",
        ]
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Package failed scientific admission.")
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    output = args.output_dir.resolve()
    if output.exists():
        raise FileExistsError(f"scientific admission package is retained: {output}")
    source_sha = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=root, text=True, encoding="utf-8"
    ).strip()
    manifest = build_package_manifest(root, source_sha)
    output.mkdir(parents=True)
    (output / "manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    (output / "README.md").write_text(_markdown(manifest), encoding="utf-8")
    print(json.dumps(manifest, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

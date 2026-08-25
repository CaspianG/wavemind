from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any, Sequence


OPENED_UNIT_IDS = (
    "Long_Range_Understanding:0100:cd66eabd2f070a38",
    "Long_Range_Understanding:0102:951f75cd34e22188",
    "Long_Range_Understanding:0103:0f57134e5ed36d75",
    "Long_Range_Understanding:0104:720f3ad635ebebf1",
    "Long_Range_Understanding:0106:9132aca9b3be661d",
)
MODEL = "mistral:7b"
MODEL_DIGEST = "f974a74358d62a017b37c6f424fcdf2744ca02926c4f952513ddf474b2fa5091"


def _require_exact_clean(path: Path, expected_sha: str) -> None:
    sha = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=path, text=True, encoding="utf-8"
    ).strip()
    status = subprocess.check_output(
        ["git", "status", "--porcelain=v1"],
        cwd=path,
        text=True,
        encoding="utf-8",
    ).strip()
    if sha != expected_sha or status:
        raise RuntimeError("diagnostic requires its clean exact candidate checkout")


def _write_jsonl(path: Path, rows: Sequence[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as stream:
        for row in rows:
            stream.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")))
            stream.write("\n")


def run(args: argparse.Namespace) -> dict[str, Any]:
    candidate_root = args.candidate_repository.resolve()
    _require_exact_clean(candidate_root, args.candidate_sha)
    sys.path.insert(0, str(candidate_root))
    from wavemind.evidence import (
        attach_artifact_integrity,
        file_sha256,
        validate_artifact_integrity,
    )
    from wavemind.evaluation_statistics import paired_cluster_bootstrap
    from wavemind.scientific_memoryagentbench import (
        NativeOllamaCaller,
        load_development_units,
        run_scientific_candidate_development,
    )
    from wavemind.scientific_runtime import ScientificCandidateMode

    manifest = json.loads(args.split_manifest.read_text(encoding="utf-8"))
    if validate_artifact_integrity(manifest):
        raise RuntimeError("MemoryAgentBench split manifest integrity failed")
    selected = [
        unit for unit in manifest["units"] if unit.get("unit_id") in OPENED_UNIT_IDS
    ]
    if {unit["unit_id"] for unit in selected} != set(OPENED_UNIT_IDS):
        raise RuntimeError("opened diagnostic unit is missing")
    if any(unit.get("split") != "development" for unit in selected):
        raise RuntimeError("diagnostic attempted a non-development unit")

    units = load_development_units(
        dataset_root=args.dataset_root,
        split_manifest=manifest,
        family="Long_Range_Understanding",
        unit_ids=OPENED_UNIT_IDS,
    )
    if any(unit.source != "detective_qa" for unit in units):
        raise RuntimeError("opened diagnostic source changed")
    rows, summary = run_scientific_candidate_development(
        official_repository=args.official_repository,
        units=units,
        caller=NativeOllamaCaller(args.ollama_endpoint, context_window=32768),
        model=MODEL,
        scratch_dir=args.scratch_dir,
        max_queries_per_context=1,
        token_budget=8192,
        source_sha=args.candidate_sha,
        candidate_mode=ScientificCandidateMode.EVIDENCE_CONTRACTED_QUERY_AGENT,
    )
    _write_jsonl(args.raw_output, rows)
    interval = paired_cluster_bootstrap(
        [
            {
                "cluster": str(row["case_id"]).rsplit(":q", 1)[0],
                "control": 0.0,
                "candidate": float(row["paired_effect"]),
            }
            for row in rows
        ],
        cluster_key="cluster",
        baseline_key="control",
        treatment_key="candidate",
        repeats=2000,
        seed=17,
        confidence_level=0.95,
    )
    artifact = attach_artifact_integrity(
        {
            "schema": "wavemind.memoryagentbench_opened_diagnostic.v11",
            "phase": "opened-development-diagnostic",
            "status": "diagnostic_only",
            "candidate_source_sha": args.candidate_sha,
            "candidate_mode": ScientificCandidateMode.EVIDENCE_CONTRACTED_QUERY_AGENT.value,
            "model": {"id": MODEL, "digest": MODEL_DIGEST, "context_window": 32768},
            "source_split": "development",
            "unit_ids": list(OPENED_UNIT_IDS),
            "case_count": len(rows),
            "paired_effect_values": [float(row["paired_effect"]) for row in rows],
            "paired_cluster_bootstrap": interval,
            "intervention_coverage": sum(
                bool(row["intervention_present"]) for row in rows
            )
            / len(rows),
            "production_case_count": int(summary["production_case_count"]),
            "promoted_memory_ids": sorted(summary["promoted_memory_ids"]),
            "raw_output": {
                "path": args.raw_output.resolve()
                .relative_to(Path.cwd().resolve())
                .as_posix(),
                "bytes": args.raw_output.stat().st_size,
                "sha256": file_sha256(args.raw_output),
            },
            "final_split_touched": False,
            "claim_boundary": (
                "Previously opened development evidence only. This diagnostic may "
                "inform v11 design but is not a gate or admission result."
            ),
        }
    )
    with args.artifact.open("w", encoding="utf-8", newline="\n") as stream:
        json.dump(artifact, stream, indent=2, ensure_ascii=False)
        stream.write("\n")
    return artifact


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--candidate-repository", type=Path, required=True)
    parser.add_argument("--candidate-sha", required=True)
    parser.add_argument("--official-repository", type=Path, required=True)
    parser.add_argument("--dataset-root", type=Path, required=True)
    parser.add_argument("--split-manifest", type=Path, required=True)
    parser.add_argument("--scratch-dir", type=Path, required=True)
    parser.add_argument("--raw-output", type=Path, required=True)
    parser.add_argument("--artifact", type=Path, required=True)
    parser.add_argument("--ollama-endpoint", default="http://127.0.0.1:11435")
    return parser.parse_args(argv)


def main() -> int:
    artifact = run(parse_args())
    print(json.dumps({
        "status": artifact["status"],
        "paired_effect_values": artifact["paired_effect_values"],
        "paired_cluster_bootstrap": artifact["paired_cluster_bootstrap"],
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

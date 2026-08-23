from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from wavemind.evidence import repository_commit
from wavemind.scientific_memoryagentbench import (
    NativeOllamaCaller,
    build_candidate_development_artifact,
    load_development_units,
    run_scientific_candidate_development,
    write_raw_results,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Pair the preregistered causal memory candidate with no-memory on "
            "a frozen MemoryAgentBench development slice"
        )
    )
    parser.add_argument("--official-root", type=Path, required=True)
    parser.add_argument("--dataset-root", type=Path, required=True)
    parser.add_argument(
        "--split-manifest",
        type=Path,
        default=ROOT / "benchmarks" / "memoryagentbench_split_manifest_results.json",
    )
    parser.add_argument(
        "--protocol",
        type=Path,
        default=ROOT / "benchmarks" / "scientific_memory_protocol_v1.json",
    )
    parser.add_argument("--family", default="Conflict_Resolution")
    parser.add_argument("--unit-id", action="append", default=[])
    parser.add_argument("--max-contexts", type=int, default=1)
    parser.add_argument("--max-queries", type=int, default=3)
    parser.add_argument("--token-budget", type=int, default=8192)
    parser.add_argument("--model", default="mistral:7b")
    parser.add_argument("--model-digest", required=True)
    parser.add_argument("--ollama-endpoint", default="http://localhost:11435")
    parser.add_argument("--context-window", type=int, default=32768)
    parser.add_argument("--failed-attempt-file", type=Path, action="append", default=[])
    parser.add_argument("--reuse-existing-output", action="store_true")
    parser.add_argument("--evidence-source-sha", default=None)
    parser.add_argument(
        "--scratch-dir",
        type=Path,
        default=ROOT / "benchmarks" / "scientific_memoryagentbench_candidate_scratch",
    )
    parser.add_argument(
        "--raw-output",
        type=Path,
        default=ROOT / "benchmarks" / "scientific_memoryagentbench_candidate_dev_raw.jsonl",
    )
    parser.add_argument(
        "--artifact",
        type=Path,
        default=ROOT / "benchmarks" / "scientific_memoryagentbench_candidate_dev_results.json",
    )
    args = parser.parse_args(argv)

    split_manifest = json.loads(args.split_manifest.read_text(encoding="utf-8"))
    protocol = json.loads(args.protocol.read_text(encoding="utf-8"))
    units = load_development_units(
        dataset_root=args.dataset_root,
        split_manifest=split_manifest,
        family=args.family,
        unit_ids=tuple(args.unit_id) or None,
        max_contexts=args.max_contexts,
    )
    source_sha = args.evidence_source_sha or repository_commit(ROOT)
    if args.evidence_source_sha and not args.reuse_existing_output:
        raise ValueError("--evidence-source-sha requires --reuse-existing-output")
    if args.reuse_existing_output:
        rows = [
            json.loads(line)
            for line in args.raw_output.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        selected = sorted(
            {
                memory_id
                for row in rows
                for memory_id in row["selected_memory_ids"]
            }
        )
        promoted = sorted(
            {
                memory_id
                for row in rows
                for memory_id, lifecycle in row["lifecycle_after"].items()
                if lifecycle == "production"
            }
        )
        summary = {
            "candidate_id": "causal-utility-controller-v1",
            "control_id": "no-memory",
            "paired_metric": "substring_exact_match",
            "paired_effects": [float(row["paired_effect"]) for row in rows],
            "verified_receipt_count": sum(
                row["receipt_digest"] is not None for row in rows
            ),
            "production_case_count": sum(
                row["candidate_phase"] == "production" for row in rows
            ),
            "selected_memory_ids": selected,
            "promoted_memory_ids": promoted,
            "false_verified_promotions": 0,
        }
        raw_path = args.raw_output.resolve()
    else:
        caller = NativeOllamaCaller(
            args.ollama_endpoint,
            context_window=args.context_window,
        )
        rows, summary = run_scientific_candidate_development(
            official_repository=args.official_root,
            units=units,
            caller=caller,
            model=args.model,
            scratch_dir=args.scratch_dir,
            max_queries_per_context=args.max_queries,
            token_budget=args.token_budget,
            source_sha=source_sha,
        )
        raw_path = write_raw_results(args.raw_output, rows)
    artifact = build_candidate_development_artifact(
        source_sha=source_sha,
        protocol_digest=protocol["protocol_digest"],
        official_repository=args.official_root,
        dataset_root=args.dataset_root,
        model=args.model,
        model_digest=args.model_digest,
        context_window=args.context_window,
        token_budget=args.token_budget,
        units=units,
        raw_results_file=raw_path,
        summary=summary,
        failed_attempt_files=args.failed_attempt_file,
    )
    args.artifact.parent.mkdir(parents=True, exist_ok=True)
    args.artifact.write_text(
        json.dumps(artifact, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(artifact, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

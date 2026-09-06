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
    load_development_units,
)
from wavemind.scientific_memoryagentbench_baselines import (
    append_failed_attempt,
    build_baseline_matrix_artifact,
    run_baseline_matrix_development,
    summarize_raw_baseline_rows,
    write_raw_baseline_rows,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Execute the exact frozen real-baseline matrix on a bounded "
            "MemoryAgentBench development slice"
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
    parser.add_argument("--top-k", type=int, default=10)
    parser.add_argument("--seed", type=int, default=17)
    parser.add_argument("--model", default="mistral:7b")
    parser.add_argument("--model-digest", required=True)
    parser.add_argument("--ollama-endpoint", default="http://localhost:11435")
    parser.add_argument("--context-window", type=int, default=32768)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--reuse-existing-output", action="store_true")
    parser.add_argument("--evidence-source-sha", default=None)
    parser.add_argument(
        "--scratch-root",
        type=Path,
        default=(ROOT / "benchmarks" / "scientific_memoryagentbench_baseline_scratch"),
    )
    parser.add_argument(
        "--raw-output",
        type=Path,
        default=(
            ROOT / "benchmarks" / "scientific_memoryagentbench_baseline_dev_raw.jsonl"
        ),
    )
    parser.add_argument(
        "--artifact",
        type=Path,
        default=(
            ROOT
            / "benchmarks"
            / "scientific_memoryagentbench_baseline_dev_results.json"
        ),
    )
    parser.add_argument(
        "--failed-attempt-file",
        type=Path,
        default=(
            ROOT
            / "benchmarks"
            / "scientific_memoryagentbench_baseline_failed_attempts.jsonl"
        ),
    )
    args = parser.parse_args(argv)

    source_sha = args.evidence_source_sha or repository_commit(ROOT)
    if args.evidence_source_sha and not args.reuse_existing_output:
        raise ValueError("--evidence-source-sha requires --reuse-existing-output")
    split_manifest = json.loads(args.split_manifest.read_text(encoding="utf-8"))
    protocol = json.loads(args.protocol.read_text(encoding="utf-8"))
    units = load_development_units(
        dataset_root=args.dataset_root,
        split_manifest=split_manifest,
        family=args.family,
        unit_ids=tuple(args.unit_id) or None,
        max_contexts=args.max_contexts,
    )
    try:
        if args.reuse_existing_output:
            rows = [
                json.loads(line)
                for line in args.raw_output.read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
            summary = summarize_raw_baseline_rows(rows)
            raw_path = args.raw_output.resolve()
        else:
            caller = NativeOllamaCaller(
                args.ollama_endpoint,
                context_window=args.context_window,
            )
            rows, summary = run_baseline_matrix_development(
                project_root=ROOT,
                protocol=protocol,
                official_repository=args.official_root,
                units=units,
                caller=caller,
                model=args.model,
                scratch_dir=args.scratch_root / args.run_id,
                max_queries_per_context=args.max_queries,
                token_budget=args.token_budget,
                top_k=args.top_k,
                seed=args.seed,
            )
            raw_path = write_raw_baseline_rows(args.raw_output, rows)
        failed_files = (
            (args.failed_attempt_file,) if args.failed_attempt_file.is_file() else ()
        )
        artifact = build_baseline_matrix_artifact(
            project_root=ROOT,
            source_sha=source_sha,
            protocol=protocol,
            official_repository=args.official_root,
            dataset_root=args.dataset_root,
            model=args.model,
            model_digest=args.model_digest,
            context_window=args.context_window,
            token_budget=args.token_budget,
            top_k=args.top_k,
            seed=args.seed,
            units=units,
            raw_results_file=raw_path,
            summary=summary,
            failed_attempt_files=failed_files,
        )
    except Exception as exc:
        append_failed_attempt(
            args.failed_attempt_file,
            source_sha=source_sha,
            stage=(
                "reuse-and-package"
                if args.reuse_existing_output
                else "execute-and-package"
            ),
            error=exc,
        )
        raise
    args.artifact.parent.mkdir(parents=True, exist_ok=True)
    args.artifact.write_text(
        json.dumps(artifact, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(artifact, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

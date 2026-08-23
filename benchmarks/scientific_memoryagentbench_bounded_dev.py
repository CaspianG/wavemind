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
    build_bounded_development_artifact,
    load_development_units,
    run_official_bm25_development,
    write_raw_results,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Run a frozen MemoryAgentBench development slice through the "
            "official formatter, BM25 agent, and native scorer"
        )
    )
    parser.add_argument("--official-root", type=Path, required=True)
    parser.add_argument("--dataset-root", type=Path, required=True)
    parser.add_argument(
        "--split-manifest",
        type=Path,
        default=ROOT / "benchmarks" / "memoryagentbench_split_manifest_results.json",
    )
    parser.add_argument("--family", default="Conflict_Resolution")
    parser.add_argument("--unit-id", action="append", default=[])
    parser.add_argument("--max-contexts", type=int, default=1)
    parser.add_argument("--max-queries", type=int, default=3)
    parser.add_argument("--model", default="mistral:7b")
    parser.add_argument("--model-digest", required=True)
    parser.add_argument("--ollama-endpoint", default="http://localhost:11435")
    parser.add_argument("--context-window", type=int, default=32768)
    parser.add_argument(
        "--scratch-dir",
        type=Path,
        default=ROOT / "benchmarks" / "scientific_memoryagentbench_scratch",
    )
    parser.add_argument(
        "--raw-output",
        type=Path,
        default=ROOT / "benchmarks" / "scientific_memoryagentbench_bounded_dev_raw.jsonl",
    )
    parser.add_argument(
        "--artifact",
        type=Path,
        default=ROOT / "benchmarks" / "scientific_memoryagentbench_bounded_dev_results.json",
    )
    args = parser.parse_args(argv)

    split_manifest = json.loads(args.split_manifest.read_text(encoding="utf-8"))
    units = load_development_units(
        dataset_root=args.dataset_root,
        split_manifest=split_manifest,
        family=args.family,
        unit_ids=tuple(args.unit_id) or None,
        max_contexts=args.max_contexts,
    )
    caller = NativeOllamaCaller(
        args.ollama_endpoint,
        context_window=args.context_window,
    )
    rows, metrics, case_ids = run_official_bm25_development(
        official_repository=args.official_root,
        units=units,
        caller=caller,
        model=args.model,
        scratch_dir=args.scratch_dir,
        max_queries_per_context=args.max_queries,
    )
    raw_path = write_raw_results(args.raw_output, rows)
    artifact = build_bounded_development_artifact(
        source_sha=repository_commit(ROOT),
        official_repository=args.official_root,
        dataset_root=args.dataset_root,
        model=args.model,
        model_digest=args.model_digest,
        context_window=args.context_window,
        units=units,
        case_ids=case_ids,
        raw_results_file=raw_path,
        metrics=metrics,
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

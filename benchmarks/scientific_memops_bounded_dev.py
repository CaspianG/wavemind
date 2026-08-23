from __future__ import annotations

import argparse
import json
import runpy
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from wavemind.evidence import repository_commit
from wavemind.scientific_memops import (
    NativeOllamaCaller,
    build_bounded_dev_artifact,
    require_exact_upstream_sha,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Run an exact-SHA official MemOps bounded-development slice with "
            "a native Ollama transport"
        )
    )
    parser.add_argument("--upstream-root", type=Path, required=True)
    parser.add_argument("--upstream-sha", required=True)
    parser.add_argument("--adjacent-input-dir", type=Path, required=True)
    parser.add_argument("--longitudinal-input-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--artifact", type=Path, required=True)
    parser.add_argument("--model", default="mistral:7b")
    parser.add_argument("--model-digest", required=True)
    parser.add_argument(
        "--judge-model",
        default=None,
        help="Local development judge model; defaults to --model.",
    )
    parser.add_argument("--ollama-endpoint", default="http://localhost:11435")
    parser.add_argument("--context-window", type=int, default=32768)
    parser.add_argument("--max-questions", type=int, default=6)
    parser.add_argument("--question-offset", type=int, default=0)
    parser.add_argument("--top-k", type=int, default=3)
    parser.add_argument("--top-k-context", type=int, default=1)
    parser.add_argument("--failed-attempt-file", type=Path, action="append", default=[])
    args = parser.parse_args(argv)

    require_exact_upstream_sha(args.upstream_root, args.upstream_sha)
    runner_path = args.upstream_root / "5-test_operation_metrics.py"
    if not runner_path.is_file():
        raise FileNotFoundError(runner_path)
    module = runpy.run_path(str(runner_path))
    run_pipeline = module.get("run_pipeline")
    if not callable(run_pipeline):
        raise RuntimeError("official MemOps run_pipeline entrypoint is missing")

    caller = NativeOllamaCaller(
        args.ollama_endpoint,
        context_window=args.context_window,
    )
    summary = run_pipeline(
        adjacent_input_dir=args.adjacent_input_dir,
        longitudinal_input_dir=args.longitudinal_input_dir,
        output_dir=args.output_dir,
        top_k=args.top_k,
        top_k_context=args.top_k_context,
        model=args.model,
        call_llm=caller,
        parser_call_llm=caller,
        mutation_call_llm=caller,
        show_progress=True,
        rag_workers=1,
        max_questions=args.max_questions,
        question_offset=args.question_offset,
        rag_methods=("rag_vanilla",),
        rag_retrieval_units=("turn",),
        adjacent_models=(),
        long_context_models=(),
        no_context_models=(),
        run_adjacent=False,
    )
    evaluator_path = args.upstream_root / "5.5-evaluate_operation_metrics.py"
    if not evaluator_path.is_file():
        raise FileNotFoundError(evaluator_path)
    evaluator_module = runpy.run_path(str(evaluator_path))
    evaluate_pipeline = evaluator_module.get("run_pipeline")
    if not callable(evaluate_pipeline):
        raise RuntimeError("official MemOps evaluation entrypoint is missing")
    evaluation_dir = args.output_dir / "evaluation"
    evaluation_summary = evaluate_pipeline(
        input_file=Path(summary["all_methods_output"]),
        output_dir=evaluation_dir,
        judge_model=args.judge_model or args.model,
        call_llm=caller,
        show_progress=True,
        eval_workers=1,
        evidence_dirs=(args.adjacent_input_dir,),
    )
    result_rows = [
        json.loads(line)
        for line in Path(summary["all_methods_output"])
        .read_text(encoding="utf-8")
        .splitlines()
        if line.strip()
    ]
    case_ids = [str(row["question_id"]) for row in result_rows]
    split_ids = sorted(
        {
            Path(str(row["source_file"])).stem
            for row in result_rows
        }
    )
    combined_summary = {
        "generation": summary,
        "evaluation": evaluation_summary,
    }
    output_files = [
        Path(summary["all_methods_output"]),
        Path(args.output_dir) / "summary.json",
        *[Path(path) for path in summary["retrieval_outputs"].values()],
        Path(evaluation_summary["output_file"]),
        evaluation_dir / "summary.json",
    ]
    artifact = build_bounded_dev_artifact(
        source_sha=repository_commit(ROOT),
        memops_sha=args.upstream_sha,
        model=args.model,
        model_digest=args.model_digest,
        context_window=args.context_window,
        endpoint_kind="ollama-native-api/local-development-only",
        split_unit_ids=split_ids,
        case_ids=case_ids,
        output_files=output_files,
        failed_attempt_files=args.failed_attempt_file,
        summary=combined_summary,
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

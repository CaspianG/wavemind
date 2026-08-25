from __future__ import annotations

import argparse
import copy
import json
import runpy
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from wavemind.evidence import canonical_json_bytes, repository_commit, sha256_bytes
from wavemind.scientific_memory import (
    CanaryArm,
    MemoryLifecycle,
    VerificationDecision,
    VerifierKind,
    VerifierResult,
)
from wavemind.scientific_memops import (
    NativeOllamaCaller,
    ScientificMemOpsRetriever,
    build_candidate_dev_artifact,
    require_exact_upstream_sha,
)
from wavemind.scientific_runtime import ScientificCandidateMode


def _write_jsonl(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
        encoding="utf-8",
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run sequential proof-carrying candidate development on MemOps"
    )
    parser.add_argument("--upstream-root", type=Path, required=True)
    parser.add_argument("--upstream-sha", required=True)
    parser.add_argument("--adjacent-input-dir", type=Path, required=True)
    parser.add_argument("--longitudinal-input-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--artifact", type=Path, required=True)
    parser.add_argument("--protocol-digest", required=True)
    parser.add_argument("--model", default="mistral:7b")
    parser.add_argument("--model-digest", required=True)
    parser.add_argument("--ollama-endpoint", default="http://localhost:11435")
    parser.add_argument("--context-window", type=int, default=32768)
    parser.add_argument("--max-cases", type=int, default=5)
    parser.add_argument("--max-subjects", type=int, default=0)
    parser.add_argument("--max-cases-per-subject", type=int, default=0)
    parser.add_argument(
        "--candidate-mode",
        choices=(
            ScientificCandidateMode.CAUSAL.value,
            ScientificCandidateMode.GRAPH.value,
            ScientificCandidateMode.STATE_RECONCILER.value,
            ScientificCandidateMode.HIERARCHICAL_RECONCILER.value,
            ScientificCandidateMode.EFFICIENT_HIERARCHICAL_RECONCILER.value,
            ScientificCandidateMode.ATOMIC_BATCH_RECONCILER.value,
            ScientificCandidateMode.OPERATION_AWARE_TOMBSTONE_RECONCILER.value,
            ScientificCandidateMode.QUERY_SLICED_OPERATION_RECONCILER.value,
            ScientificCandidateMode.PHRASE_ALIGNED_QUERY_SLICED_RECONCILER.value,
        ),
        default=ScientificCandidateMode.CAUSAL.value,
    )
    parser.add_argument("--token-budget", type=int, default=2048)
    parser.add_argument("--top-k-context", type=int, default=1)
    args = parser.parse_args(argv)
    if args.max_cases < 0 or args.max_subjects < 0 or args.max_cases_per_subject < 0:
        parser.error("case and subject limits must be non-negative")

    require_exact_upstream_sha(args.upstream_root, args.upstream_sha)
    source_sha = repository_commit(ROOT)
    generation = runpy.run_path(str(args.upstream_root / "5-test_operation_metrics.py"))
    evaluation = runpy.run_path(
        str(args.upstream_root / "5.5-evaluate_operation_metrics.py")
    )
    caller = NativeOllamaCaller(
        args.ollama_endpoint,
        context_window=args.context_window,
    )
    mode = ScientificCandidateMode(args.candidate_mode)
    candidate_id = mode.value
    raw_rows: list[dict[str, object]] = []
    paired_effects: list[float] = []
    production_case_count = 0
    verified_receipt_count = 0
    promoted_memory_ids: set[str] = set()
    case_ids: list[str] = []

    evidence_payloads = {
        path.name: json.loads(path.read_text(encoding="utf-8"))
        for path in sorted(args.adjacent_input_dir.glob("*.json"))
    }
    with tempfile.TemporaryDirectory(prefix="wavemind-memops-candidate-") as temp_dir:
        stop = False
        for subject_index, path in enumerate(
            sorted(args.longitudinal_input_dir.glob("*.json"))
        ):
            if args.max_subjects and subject_index >= args.max_subjects:
                break
            payload = generation["enrich_payload_with_gold_fields"](
                json.loads(path.read_text(encoding="utf-8")),
                evidence_payloads.get(path.name),
            )
            corpus = generation["build_session_corpus"](payload, path.name)
            entries = generation["build_retrieval_entries_for_payload"](
                payload,
                source_file_name=path.name,
                evidence_source_path=str(
                    (args.adjacent_input_dir / path.name).resolve()
                ),
                top_k=20,
                evaluation_setting="longitudinal_operation",
                corpus=corpus,
                evaluation_method=candidate_id,
                retrieval_mode=f"scientific-{mode.value}",
                retriever_name=candidate_id,
                answer_model=args.model,
                retrieval_unit="session",
            )
            db_path = Path(temp_dir) / f"{path.stem}.db"
            with ScientificMemOpsRetriever(
                db_path,
                corpus=corpus,
                mode=mode,
            ) as retriever:
                subject_case_count = 0
                for entry in entries:
                    if args.max_cases and len(case_ids) >= args.max_cases:
                        stop = True
                        break
                    if (
                        args.max_cases_per_subject
                        and subject_case_count >= args.max_cases_per_subject
                    ):
                        break
                    case_id = str(entry["question_id"])
                    production_items, production_recall = retriever.retrieve(
                        str(entry["question"]),
                        token_budget=args.token_budget,
                        top_k_context=args.top_k_context,
                        evaluation_only=False,
                    )
                    if production_recall.abstained:
                        ranked_items, treatment_recall = retriever.retrieve(
                            str(entry["question"]),
                            token_budget=args.token_budget,
                            top_k_context=args.top_k_context,
                            evaluation_only=True,
                        )
                        candidate_phase = "shadow"
                    else:
                        ranked_items = production_items
                        treatment_recall = production_recall
                        candidate_phase = "production"
                        production_case_count += 1

                    treatment_entry = copy.deepcopy(entry)
                    treatment_entry["retrieval_results"].update(
                        {
                            "ranked_items": ranked_items,
                            "retriever": candidate_id,
                            "top_k": len(ranked_items),
                            "metrics": generation["retrieval_metrics"](
                                ranked_items,
                                set(entry["answer_session_ids"]),
                            ),
                        }
                    )
                    treatment_entry["candidate_phase"] = candidate_phase
                    control_entry = copy.deepcopy(entry)
                    control_entry["evaluation_method"] = "no-memory"
                    control_entry["context_mode"] = "no_context"
                    control_entry["retrieval_mode"] = "none"
                    control_entry["retrieval_results"].update(
                        {
                            "ranked_items": [],
                            "retriever": "no-memory",
                            "top_k": 0,
                            "metrics": {},
                        }
                    )
                    treatment_answer = generation["run_gpt_rag"](
                        [treatment_entry],
                        model=args.model,
                        top_k_context=args.top_k_context,
                        call_llm=caller,
                        show_progress=False,
                        rag_workers=1,
                    )[0]
                    control_answer = generation["run_gpt_rag"](
                        [control_entry],
                        model=args.model,
                        top_k_context=args.top_k_context,
                        call_llm=caller,
                        show_progress=False,
                        rag_workers=1,
                    )[0]
                    treatment_eval = evaluation["evaluate_entry"](
                        treatment_answer,
                        judge_model=args.model,
                        call_llm=caller,
                        evidence_dirs=(args.adjacent_input_dir,),
                    )
                    control_eval = evaluation["evaluate_entry"](
                        control_answer,
                        judge_model=args.model,
                        call_llm=caller,
                        evidence_dirs=(args.adjacent_input_dir,),
                    )
                    treatment_score = float(treatment_eval["answer_score"])
                    control_score = float(control_eval["answer_score"])
                    effect = treatment_score - control_score
                    paired_effects.append(effect)
                    evidence_digest = sha256_bytes(
                        canonical_json_bytes(
                            {
                                "treatment": treatment_eval,
                                "control": control_eval,
                            }
                        )
                    )
                    receipt_digest = None
                    if not treatment_recall.abstained:
                        receipt_digest = retriever.runtime.record_verified_influence(
                            treatment_recall,
                            receipt_id=f"memops-{case_id}",
                            task_id="memops-bounded-development",
                            case_id=case_id,
                            action={"hypothesis": treatment_answer["hypothesis"]},
                            verifier_result=VerifierResult(
                                verifier_kind=VerifierKind.TEST,
                                verifier_id=(
                                    "MemTensor/MemOps/5.5-evaluate_operation_metrics.py"
                                ),
                                verifier_run_id=f"{source_sha}:{case_id}",
                                decision=VerificationDecision.VERIFIED,
                                treatment_outcome=treatment_score,
                                control_outcome=control_score,
                                evidence_uri=f"memops://{args.upstream_sha}/{case_id}",
                                evidence_sha256=evidence_digest,
                            ),
                            safe_for_randomization=True,
                            canary_arm=CanaryArm.MEMORY,
                        )
                        verified_receipt_count += 1
                    lifecycle = {
                        memory_id: state.lifecycle.value
                        for memory_id, state in (
                            (
                                memory_id,
                                retriever.runtime.event_log.memory_state(memory_id),
                            )
                            for memory_id in treatment_recall.selected_memory_ids
                        )
                    }
                    promoted_memory_ids.update(
                        memory_id
                        for memory_id, value in lifecycle.items()
                        if value == MemoryLifecycle.PRODUCTION.value
                    )
                    case_ids.append(case_id)
                    subject_case_count += 1
                    raw_rows.append(
                        {
                            "case_id": case_id,
                            "candidate_phase": candidate_phase,
                            "selected_memory_ids": list(
                                treatment_recall.selected_memory_ids
                            ),
                            "paired_effect": effect,
                            "receipt_digest": receipt_digest,
                            "lifecycle_after": lifecycle,
                            "treatment": treatment_eval,
                            "control": control_eval,
                        }
                    )
                    _write_jsonl(args.output_dir / "raw_pairs.jsonl", raw_rows)
            if stop:
                break

    raw_output = args.output_dir / "raw_pairs.jsonl"
    artifact = build_candidate_dev_artifact(
        source_sha=source_sha,
        protocol_digest=args.protocol_digest,
        memops_sha=args.upstream_sha,
        candidate_id=candidate_id,
        model=args.model,
        model_digest=args.model_digest,
        context_window=args.context_window,
        raw_output_file=raw_output,
        case_ids=case_ids,
        paired_effects=paired_effects,
        verified_receipt_count=verified_receipt_count,
        false_verified_promotions=0,
        production_case_count=production_case_count,
        promoted_memory_ids=sorted(promoted_memory_ids),
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

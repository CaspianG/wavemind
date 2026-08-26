from __future__ import annotations

import argparse
import copy
import json
import runpy
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Mapping

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from wavemind.evaluation_statistics import paired_cluster_bootstrap
from wavemind.evidence import (
    attach_artifact_integrity,
    canonical_json_bytes,
    file_sha256,
    repository_commit,
    sha256_bytes,
)
from wavemind.scientific_memory import MemoryLifecycle
from wavemind.scientific_memops import (
    NativeOllamaCaller,
    ScientificMemOpsRetriever,
    require_exact_upstream_sha,
)
from wavemind.scientific_runtime import ScientificCandidateMode


PROTOCOL_PATH = ROOT / "benchmarks" / "scientific_memory_protocol_v10.json"
CANDIDATE_MODE = ScientificCandidateMode.OPERATION_TRACE_STRICT_OUTPUT_AGENT
ARTIFACT_SCHEMA = "wavemind.scientific_memops_v10_development.v1"
CLUSTER_GATE_KEY = "minimum_independent_subject_clusters_per_family"
CI_GATE_KEY = "paired_subject_cluster_bootstrap_ci_lower_strictly_greater_than"
QUESTION_SELECTION = "first"
CANDIDATE_ID_OVERRIDE: str | None = None
ARTIFACT_PHASE = "bounded-development"
DIAGNOSTIC_ONLY = False
TRAJECTORY_SEQUENCE_COVERAGE = False
UPDATE_SEQUENCE_COVERAGE = False
TRAJECTORY_OPERATION_ONLY_SEQUENCE_COVERAGE = False
OPERATION_TRACE_SEQUENCE_COVERAGE = False
OPERATION_TRACE_OPERATION_ONLY_SEQUENCE_COVERAGE = False
CANDIDATE_DISAMBIGUATION_QUERY_OPTIONS = False
CANDIDATE_DISAMBIGUATION_SEQUENCE_COVERAGE = False
CANDIDATE_DISAMBIGUATION_OPERATION_ONLY_SEQUENCE_COVERAGE = False
CANDIDATE_MODE_BY_OPERATION: dict[str, ScientificCandidateMode] = {}


def _select_entries(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not entries:
        return []
    if QUESTION_SELECTION == "first":
        return entries[:1]
    if QUESTION_SELECTION in {"causal-discrimination-v1", "causal-discrimination-v6"}:
        priority = {
            "CandidateDisambiguation": 0,
            "StateTrajectory": 1,
            "OperationApplication": 2,
            "StateTransition": 3,
            "TargetBinding": 4,
            "OperationTrace": 5,
        }
        return [
            min(
                entries,
                key=lambda entry: (
                    priority.get(str(entry.get("evaluation_type")), 99),
                    str(entry.get("question_id", "")),
                ),
            )
        ]
    if QUESTION_SELECTION == "causal-application-v2":
        priority = {
            "OperationApplication": 0,
            "StateTrajectory": 1,
            "StateTransition": 2,
            "TargetBinding": 3,
            "CandidateDisambiguation": 4,
            "OperationTrace": 5,
        }
        return [
            min(
                entries,
                key=lambda entry: (
                    priority.get(str(entry.get("evaluation_type")), 99),
                    str(entry.get("question_id", "")),
                ),
            )
        ]
    if QUESTION_SELECTION == "state-verification-v3":
        priority = {
            "StateTransition": 0,
            "StateTrajectory": 1,
            "TargetBinding": 2,
            "OperationApplication": 3,
            "CandidateDisambiguation": 4,
            "OperationTrace": 5,
        }

        def key(entry: Mapping[str, Any]) -> tuple[int, int, str]:
            question_id = str(entry.get("question_id", ""))
            digits = "".join(character for character in question_id if character.isdigit())
            question_number = int(digits) if digits else -1
            return (
                priority.get(str(entry.get("evaluation_type")), 99),
                -question_number,
                question_id,
            )

        return [min(entries, key=key)]
    if QUESTION_SELECTION == "state-verification-v4":
        priority = {
            "StateTransition": 0,
            "CandidateDisambiguation": 1,
            "StateTrajectory": 2,
            "TargetBinding": 3,
            "OperationApplication": 4,
            "OperationTrace": 5,
        }

        def key(entry: Mapping[str, Any]) -> tuple[int, int, str]:
            question_id = str(entry.get("question_id", ""))
            digits = "".join(character for character in question_id if character.isdigit())
            question_number = int(digits) if digits else 999
            return (
                priority.get(str(entry.get("evaluation_type")), 99),
                question_number,
                question_id,
            )

        return [min(entries, key=key)]
    if QUESTION_SELECTION == "memory-dependence-v5":
        priority = {
            "OperationTrace": 0,
            "StateTrajectory": 1,
            "TargetBinding": 2,
            "OperationApplication": 3,
            "StateTransition": 4,
            "CandidateDisambiguation": 5,
        }

        def key(entry: Mapping[str, Any]) -> tuple[int, int, str]:
            question_id = str(entry.get("question_id", ""))
            digits = "".join(character for character in question_id if character.isdigit())
            question_number = int(digits) if digits else 999
            return (
                priority.get(str(entry.get("evaluation_type")), 99),
                question_number,
                question_id,
            )

        return [min(entries, key=key)]
    if QUESTION_SELECTION == "operation-adaptive-v7":
        operation_type = str(entries[0].get("operation_type", ""))
        if operation_type == "Update":
            priority = {
                "OperationApplication": 0,
                "CandidateDisambiguation": 1,
                "TargetBinding": 2,
                "OperationTrace": 3,
            }
        elif operation_type == "TrajectoryOps":
            priority = {
                "OperationTrace": 0,
                "StateTrajectory": 1,
                "OperationApplication": 2,
                "TargetBinding": 3,
            }
        else:
            priority = {
                "CandidateDisambiguation": 0,
                "OperationApplication": 1,
                "StateTransition": 2,
                "TargetBinding": 3,
                "OperationTrace": 4,
            }
        return [
            min(
                entries,
                key=lambda entry: (
                    priority.get(str(entry.get("evaluation_type")), 99),
                    str(entry.get("question_id", "")),
                ),
            )
        ]
    raise RuntimeError(f"unknown MemOps question selection: {QUESTION_SELECTION}")


def _retrieval_query(entry: Mapping[str, Any]) -> str:
    question = str(entry["question"])
    if (
        CANDIDATE_DISAMBIGUATION_QUERY_OPTIONS
        and str(entry.get("evaluation_type")) == "CandidateDisambiguation"
    ):
        options = [str(option).strip() for option in entry.get("candidate_options", [])]
        options = [option for option in options if option]
        if options:
            return question + "\nCandidate options: " + " | ".join(options)
    return question


def _candidate_mode_for_entry(entry: Mapping[str, Any]) -> ScientificCandidateMode:
    return CANDIDATE_MODE_BY_OPERATION.get(
        str(entry.get("operation_type", "")),
        CANDIDATE_MODE,
    )


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
        encoding="utf-8",
    )


def _require_clean_exact_source(expected_sha: str) -> str:
    actual_sha = repository_commit(ROOT)
    if actual_sha != expected_sha:
        raise RuntimeError(
            f"candidate source SHA mismatch: expected {expected_sha}, got {actual_sha}"
        )
    dirty = subprocess.check_output(
        ["git", "status", "--porcelain"],
        cwd=ROOT,
        text=True,
        encoding="utf-8",
    ).strip()
    if dirty:
        raise RuntimeError("candidate worktree must be clean before benchmark execution")
    return actual_sha


def _subject_id(path: Path) -> str:
    return path.stem.split("_", 1)[0]


def _build_entries(
    *,
    family: str,
    path: Path,
    adjacent_input_dir: Path,
    generation: Mapping[str, Any],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    adjacent_path = adjacent_input_dir / path.name
    adjacent_payload = json.loads(adjacent_path.read_text(encoding="utf-8"))
    if family == "memops_adjacent_operation":
        payload = adjacent_payload
        corpus = generation["build_session_corpus"](payload, path.name)
        entries = generation["build_adjacent_entries_for_payload"](
            payload,
            source_file_name=path.name,
            evidence_source_path=str(adjacent_path.resolve()),
            answer_model="mistral:7b",
        )
        return corpus, _select_entries(entries)
    payload = generation["enrich_payload_with_gold_fields"](
        json.loads(path.read_text(encoding="utf-8")),
        adjacent_payload,
    )
    corpus = generation["build_session_corpus"](payload, path.name)
    entries = generation["build_retrieval_entries_for_payload"](
        payload,
        source_file_name=path.name,
        evidence_source_path=str(adjacent_path.resolve()),
        top_k=20,
        evaluation_setting="longitudinal_operation",
        corpus=corpus,
        evaluation_method=CANDIDATE_MODE.value,
        retrieval_mode=f"scientific-{CANDIDATE_MODE.value}",
        retriever_name=CANDIDATE_MODE.value,
        answer_model="mistral:7b",
        retrieval_unit="session",
    )
    return corpus, _select_entries(entries)


def _no_memory_entry(entry: Mapping[str, Any]) -> dict[str, Any]:
    result = copy.deepcopy(entry)
    result["evaluation_method"] = "no-memory"
    result["context_mode"] = "no_context"
    result["retrieval_mode"] = "none"
    result["retrieval_results"].update(
        {
            "ranked_items": [],
            "retriever": "no-memory",
            "top_k": 0,
            "metrics": {},
        }
    )
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run one frozen v10 MemOps development family/run"
    )
    parser.add_argument("--upstream-root", type=Path, required=True)
    parser.add_argument("--upstream-sha", required=True)
    parser.add_argument("--adjacent-input-dir", type=Path, required=True)
    parser.add_argument("--longitudinal-input-dir", type=Path, required=True)
    parser.add_argument("--family", required=True)
    parser.add_argument("--run-number", type=int, choices=(1, 2, 3), required=True)
    parser.add_argument("--expected-source-sha", required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--artifact", type=Path, required=True)
    parser.add_argument("--ollama-endpoint", default="http://127.0.0.1:11435")
    args = parser.parse_args(argv)

    protocol = json.loads(PROTOCOL_PATH.read_text(encoding="utf-8"))
    family_specs = protocol["frozen_development_gate"]["families"]
    if args.family not in family_specs:
        parser.error(f"family must be one of: {', '.join(sorted(family_specs))}")
    parameters = protocol["frozen_parameters"]
    subjects = tuple(family_specs[args.family]["subjects"])
    source_sha = _require_clean_exact_source(args.expected_source_sha)
    require_exact_upstream_sha(args.upstream_root, args.upstream_sha)
    generation = runpy.run_path(str(args.upstream_root / "5-test_operation_metrics.py"))
    evaluation = runpy.run_path(
        str(args.upstream_root / "5.5-evaluate_operation_metrics.py")
    )
    caller = NativeOllamaCaller(
        args.ollama_endpoint,
        context_window=int(parameters["context_window"]),
    )
    input_dir = (
        args.adjacent_input_dir
        if args.family == "memops_adjacent_operation"
        else args.longitudinal_input_dir
    )
    paths = [
        path
        for path in sorted(input_dir.glob("*.json"))
        if _subject_id(path) in subjects
    ]
    missing_subjects = sorted(set(subjects) - {_subject_id(path) for path in paths})
    if missing_subjects:
        raise RuntimeError(f"frozen subjects have no input files: {missing_subjects}")

    rows: list[dict[str, Any]] = []
    production_case_count = 0
    promoted_memory_ids: set[str] = set()
    with tempfile.TemporaryDirectory(prefix="wavemind-memops-v10-") as temp_dir:
        for path in paths:
            corpus, entries = _build_entries(
                family=args.family,
                path=path,
                adjacent_input_dir=args.adjacent_input_dir,
                generation=generation,
            )
            if not entries:
                continue
            entry = copy.deepcopy(entries[0])
            case_candidate_mode = _candidate_mode_for_entry(entry)
            entry["evaluation_method"] = case_candidate_mode.value
            entry["retrieval_mode"] = f"scientific-{case_candidate_mode.value}"
            case_id = str(entry["question_id"])
            retrieval_query = _retrieval_query(entry)
            sequence_coverage = (
                TRAJECTORY_SEQUENCE_COVERAGE
                and path.stem.endswith("_trajectory_ops")
            ) or (
                UPDATE_SEQUENCE_COVERAGE and path.stem.endswith("_update")
            ) or (
                OPERATION_TRACE_SEQUENCE_COVERAGE
                and str(entry.get("evaluation_type")) == "OperationTrace"
            ) or (
                CANDIDATE_DISAMBIGUATION_SEQUENCE_COVERAGE
                and str(entry.get("evaluation_type")) == "CandidateDisambiguation"
            )
            sequence_operation_only = (
                TRAJECTORY_OPERATION_ONLY_SEQUENCE_COVERAGE
                and path.stem.endswith("_trajectory_ops")
            ) or (
                OPERATION_TRACE_OPERATION_ONLY_SEQUENCE_COVERAGE
                and str(entry.get("evaluation_type")) == "OperationTrace"
            ) or (
                CANDIDATE_DISAMBIGUATION_OPERATION_ONLY_SEQUENCE_COVERAGE
                and str(entry.get("evaluation_type")) == "CandidateDisambiguation"
            )
            db_path = Path(temp_dir) / f"{path.stem}.db"
            with ScientificMemOpsRetriever(
                db_path,
                corpus=corpus,
                mode=case_candidate_mode,
            ) as retriever:
                production_items, production_recall = retriever.retrieve(
                    retrieval_query,
                    token_budget=int(parameters["token_budget"]),
                    top_k_context=int(parameters["top_k_context"]),
                    evaluation_only=False,
                    sequence_coverage=sequence_coverage,
                    sequence_operation_only=sequence_operation_only,
                )
                if production_recall.abstained:
                    ranked_items, treatment_recall = retriever.retrieve(
                        retrieval_query,
                        token_budget=int(parameters["token_budget"]),
                        top_k_context=int(parameters["top_k_context"]),
                        evaluation_only=True,
                        sequence_coverage=sequence_coverage,
                        sequence_operation_only=sequence_operation_only,
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
                        "retriever": case_candidate_mode.value,
                        "top_k": len(ranked_items),
                        "metrics": generation["retrieval_metrics"](
                            ranked_items,
                            set(entry["answer_session_ids"]),
                        ),
                    }
                )
                treatment_entry["candidate_phase"] = candidate_phase
                arms = {
                    "treatment": treatment_entry,
                    "control": _no_memory_entry(entry),
                }
                answer_order = (
                    ("control", "treatment")
                    if int(sha256_bytes(case_id.encode("utf-8"))[:2], 16) % 2 == 0
                    else ("treatment", "control")
                )
                answers: dict[str, dict[str, Any]] = {}
                if not ranked_items:
                    fallback = generation["run_gpt_rag"](
                        [arms["control"]],
                        model=str(parameters["answer_model"]),
                        top_k_context=int(parameters["top_k_context"]),
                        call_llm=caller,
                        show_progress=False,
                        rag_workers=1,
                    )[0]
                    answers = {
                        "treatment": copy.deepcopy(fallback),
                        "control": fallback,
                    }
                    fallback_score = evaluation["evaluate_entry"](
                        fallback,
                        judge_model=str(parameters["judge_model"]),
                        call_llm=caller,
                        evidence_dirs=(args.adjacent_input_dir,),
                    )
                    scored = {
                        "treatment": copy.deepcopy(fallback_score),
                        "control": fallback_score,
                    }
                else:
                    for arm in answer_order:
                        answers[arm] = generation["run_gpt_rag"](
                            [arms[arm]],
                            model=str(parameters["answer_model"]),
                            top_k_context=int(parameters["top_k_context"]),
                            call_llm=caller,
                            show_progress=False,
                            rag_workers=1,
                        )[0]
                    scored = {
                        arm: evaluation["evaluate_entry"](
                            answers[arm],
                            judge_model=str(parameters["judge_model"]),
                            call_llm=caller,
                            evidence_dirs=(args.adjacent_input_dir,),
                        )
                        for arm in ("treatment", "control")
                    }
                treatment_score = float(scored["treatment"]["answer_score"])
                control_score = float(scored["control"]["answer_score"])
                lifecycle = {
                    memory_id: retriever.runtime.event_log.memory_state(
                        memory_id
                    ).lifecycle.value
                    for memory_id in treatment_recall.selected_memory_ids
                }
                promoted_memory_ids.update(
                    memory_id
                    for memory_id, state in lifecycle.items()
                    if state == MemoryLifecycle.PRODUCTION.value
                )
                rows.append(
                    {
                        "case_id": case_id,
                        "subject_id": _subject_id(path),
                        "source_file": path.name,
                        "family": args.family,
                        "run_number": args.run_number,
                        "answer_order": list(answer_order),
                        "candidate_phase": candidate_phase,
                        "intervention_present": bool(ranked_items),
                        "selected_memory_ids": list(
                            treatment_recall.selected_memory_ids
                        ),
                        "lifecycle_after": lifecycle,
                        "treatment_score": treatment_score,
                        "control_score": control_score,
                        "paired_effect": treatment_score - control_score,
                        "treatment": scored["treatment"],
                        "control": scored["control"],
                        "evidence_sha256": sha256_bytes(
                            canonical_json_bytes(scored)
                        ),
                    }
                )
                _write_jsonl(args.output_dir / "raw_pairs.jsonl", rows)

    represented_subjects = sorted({row["subject_id"] for row in rows})
    if represented_subjects != sorted(subjects):
        raise RuntimeError(
            "not every frozen subject produced a scored row: "
            f"expected {sorted(subjects)}, got {represented_subjects}"
        )
    statistics = paired_cluster_bootstrap(
        rows,
        cluster_key="subject_id",
        baseline_key="control_score",
        treatment_key="treatment_score",
        repeats=int(parameters["bootstrap_repeats"]),
        seed=int(parameters["seed"]),
        confidence_level=float(parameters["confidence_level"]),
    )
    coverage = sum(bool(row["intervention_present"]) for row in rows) / len(rows)
    raw_path = (args.output_dir / "raw_pairs.jsonl").resolve()
    gate = protocol["frozen_development_gate"]
    gate_checks = {
        "minimum_independent_subject_clusters": (
            statistics["cluster_count"]
            >= gate[CLUSTER_GATE_KEY]
        ),
        "paired_subject_cluster_bootstrap_ci_lower_strictly_positive": (
            statistics["ci_lower"]
            > gate[CI_GATE_KEY]
        ),
        "mean_non_negative": statistics["mean_difference"] >= 0.0,
        "minimum_intervention_coverage": (
            coverage >= gate["minimum_intervention_coverage"]
        ),
        "no_production_cases": production_case_count == 0,
        "no_promoted_memories": not promoted_memory_ids,
    }
    artifact = attach_artifact_integrity(
        {
            "schema": ARTIFACT_SCHEMA,
            "phase": ARTIFACT_PHASE,
            "admission_eligible": False,
            "status": (
                "diagnostic_only"
                if DIAGNOSTIC_ONLY
                else "pass"
                if all(gate_checks.values())
                else "failed_development_gate"
            ),
            "source_sha": source_sha,
            "protocol_digest": protocol["protocol_digest"],
            "candidate_id": CANDIDATE_ID_OVERRIDE or CANDIDATE_MODE.value,
            "candidate_mode_by_operation": {
                operation_type: mode.value
                for operation_type, mode in sorted(CANDIDATE_MODE_BY_OPERATION.items())
            },
            "family": args.family,
            "evaluation_setting": family_specs[args.family]["evaluation_setting"],
            "run_number": args.run_number,
            "official_upstream": {
                "repository": "MemTensor/MemOps",
                "sha": args.upstream_sha,
                "runners": [
                    "5-test_operation_metrics.py:run_gpt_rag",
                    "5.5-evaluate_operation_metrics.py:evaluate_entry",
                ],
                "upstream_modified": False,
            },
            "model": {
                "answer": parameters["answer_model"],
                "judge": parameters["judge_model"],
                "digest": parameters["model_digest"],
                "context_window": parameters["context_window"],
            },
            "subjects": represented_subjects,
            "case_ids": [row["case_id"] for row in rows],
            "question_selection": QUESTION_SELECTION,
            "trajectory_sequence_coverage": TRAJECTORY_SEQUENCE_COVERAGE,
            "trajectory_operation_only_sequence_coverage": (
                TRAJECTORY_OPERATION_ONLY_SEQUENCE_COVERAGE
            ),
            "update_sequence_coverage": UPDATE_SEQUENCE_COVERAGE,
            "operation_trace_sequence_coverage": OPERATION_TRACE_SEQUENCE_COVERAGE,
            "operation_trace_operation_only_sequence_coverage": (
                OPERATION_TRACE_OPERATION_ONLY_SEQUENCE_COVERAGE
            ),
            "candidate_disambiguation_query_options": (
                CANDIDATE_DISAMBIGUATION_QUERY_OPTIONS
            ),
            "candidate_disambiguation_sequence_coverage": (
                CANDIDATE_DISAMBIGUATION_SEQUENCE_COVERAGE
            ),
            "candidate_disambiguation_operation_only_sequence_coverage": (
                CANDIDATE_DISAMBIGUATION_OPERATION_ONLY_SEQUENCE_COVERAGE
            ),
            "case_count": len(rows),
            "intervention_coverage": coverage,
            "statistics": statistics,
            "production_case_count": production_case_count,
            "promoted_memory_ids": sorted(promoted_memory_ids),
            "false_verified_promotions": 0,
            "gate_checks": gate_checks,
            "diagnostic_gate_pass": (
                all(gate_checks.values()) if DIAGNOSTIC_ONLY else None
            ),
            "gate_pass": all(gate_checks.values()) and not DIAGNOSTIC_ONLY,
            "final_split_touched": False,
            "raw_output": {
                "path": str(raw_path),
                "bytes": raw_path.stat().st_size,
                "sha256": file_sha256(raw_path),
            },
            "claim_boundary": (
                "Opened development evidence; diagnostic only, never a gate."
                if DIAGNOSTIC_ONLY
                else "Fresh development evidence only; not admission."
            ),
        }
    )
    args.artifact.parent.mkdir(parents=True, exist_ok=True)
    args.artifact.write_text(
        json.dumps(artifact, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(artifact, indent=2, ensure_ascii=False))
    return 0 if DIAGNOSTIC_ONLY or artifact["gate_pass"] else 2


if __name__ == "__main__":
    raise SystemExit(main())

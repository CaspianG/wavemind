from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from wavemind.evidence import attach_artifact_integrity, file_sha256


CANDIDATE_SOURCE_SHA = "2a55c83ef3d3e4a3c5d9dff4418258eacb378127"
FIXED_HARNESS_COMMIT = "303d06138fd205a36ea15473c13d0aa71fe4b150"
DEPENDENCY_PLAN_COMMIT = "0b1fe80a97e3e0fa3708b21e805b5bccb6ab5d36"
RUN_ROOT = ROOT / "benchmarks" / "scientific_longmemeval_v31_final"
MARKER = RUN_ROOT / "full_run_marker.json"
RUN_ARGS = RUN_ROOT / "candidate_web_small" / "run_args.json"
CONSOLE_LOG = RUN_ROOT / "continuation2_console.log"
HF_CACHE = Path.home() / ".cache" / "huggingface" / "hub" / "models--Qwen--Qwen3.5-9B"
OUTPUT = ROOT / "benchmarks" / "scientific_v31_longmem_infrastructure_failure_3.json"
PYTHON_PID = 15588


def _record(path: Path) -> dict[str, object]:
    return {
        "path": path.relative_to(ROOT).as_posix(),
        "bytes": path.stat().st_size,
        "sha256": file_sha256(path),
    }


def _cache_record(path: Path) -> dict[str, object]:
    return {
        "cache_relative_path": path.relative_to(HF_CACHE).as_posix(),
        "bytes": path.stat().st_size,
        "sha256": file_sha256(path),
    }


def _powershell_events(*, log_name: str, event_ids: tuple[int, ...]) -> list[dict[str, object]]:
    ids = ",".join(str(value) for value in event_ids)
    script = (
        "$OutputEncoding=[Text.Encoding]::UTF8;"
        "[Console]::OutputEncoding=[Text.Encoding]::UTF8;"
        f"$events=Get-WinEvent -FilterHashtable @{{LogName='{log_name}';"
        f"Id=@({ids});StartTime=[datetime]'2026-08-26T21:15:00';"
        "EndTime=[datetime]'2026-08-26T21:30:00'} | Sort-Object TimeCreated;"
        "@($events | Select-Object @{n='time_created';"
        "e={$_.TimeCreated.ToString('o')}},ProviderName,Id,RecordId,Message) | "
        "ConvertTo-Json -Depth 3 -Compress"
    )
    completed = subprocess.run(
        ["powershell.exe", "-NoProfile", "-Command", script],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8-sig",
    )
    payload = json.loads(completed.stdout)
    if isinstance(payload, dict):
        return [payload]
    return list(payload)


def main() -> int:
    marker = json.loads(MARKER.read_text(encoding="utf-8"))
    run_args = json.loads(RUN_ARGS.read_text(encoding="utf-8"))
    if marker.get("logical_full_run_count") != 1 or marker.get("status") == "completed":
        raise RuntimeError("OOM evidence is not from the incomplete logical run")
    if list(RUN_ROOT.rglob("per_question.jsonl")):
        raise RuntimeError("per-question outcomes exist before OOM evidence freeze")
    if list(RUN_ROOT.rglob("aggregated_metrics.json")):
        raise RuntimeError("aggregate outcomes exist before OOM evidence freeze")
    if not CONSOLE_LOG.is_file():
        raise RuntimeError("third continuation console log is missing")

    system_events = _powershell_events(log_name="System", event_ids=(2004,))
    resource_events = [
        row
        for row in system_events
        if row["ProviderName"] == "Microsoft-Windows-Resource-Exhaustion-Detector"
        and f"python.exe ({PYTHON_PID})" in str(row["Message"])
    ]
    allocations = []
    for row in resource_events:
        match = re.search(
            rf"python\.exe \({PYTHON_PID}\).*?(?:consumed )?([0-9]+) "
            r"(?:bytes|байт)",
            str(row["Message"]),
        )
        if match:
            allocations.append(int(match.group(1)))
    if len(resource_events) != 2 or allocations != [27802656768, 29787037696]:
        raise RuntimeError("Windows resource-exhaustion evidence changed")

    application_events = _powershell_events(
        log_name="Application", event_ids=(1000, 1001)
    )
    collateral_events = [
        row
        for row in application_events
        if "codex.exe" in str(row["Message"]).lower()
        or "telegram.exe" in str(row["Message"]).lower()
        or "openai.codex" in str(row["Message"]).lower()
    ]
    if not any("codex.exe" in str(row["Message"]).lower() for row in collateral_events):
        raise RuntimeError("Codex crash evidence is missing")

    snapshot_revision = (HF_CACHE / "refs" / "main").read_text(encoding="utf-8").strip()
    snapshot_root = HF_CACHE / "snapshots" / snapshot_revision
    cache_files = sorted(path for path in snapshot_root.rglob("*") if path.is_file())
    if snapshot_revision != "c202236235762e1c871ad0ccb60c8ee5ba337b9a":
        raise RuntimeError("Qwen tokenizer snapshot revision changed")

    payload = attach_artifact_integrity(
        {
            "schema": "wavemind.scientific_v31_longmem_infrastructure_failure.v3",
            "status": "infrastructure_failed_before_outcomes",
            "logical_run": "longmemeval_v2_small_full_v31",
            "logical_full_run_count": 1,
            "infrastructure_failure_sequence": 3,
            "candidate_source_sha": CANDIDATE_SOURCE_SHA,
            "fixed_harness_commit": FIXED_HARNESS_COMMIT,
            "dependency_continuation_plan_commit": DEPENDENCY_PLAN_COMMIT,
            "failure": {
                "stage": "candidate_web_small_parallel_prompt_build",
                "type": "WindowsVirtualMemoryExhaustion",
                "causal_diagnosis": (
                    "Four official prompt workers concurrently invoked the shared "
                    "candidate backend. Each recall held a large private working set; "
                    "Windows detected system commit exhaustion at 27.8 GB and then "
                    "29.8 GB allocated by the benchmark Python process."
                ),
                "python_pid": PYTHON_PID,
                "peak_observed_python_virtual_allocation_bytes": max(allocations),
                "python_traceback_emitted": False,
                "benchmark_process_present_after_app_restart": False,
                "supervising_codex_app_crashed": True,
                "candidate_or_threshold_failure": False,
                "scientific_gate_evaluated": False,
            },
            "windows_event_evidence": {
                "resource_exhaustion_events": resource_events,
                "collateral_application_events": collateral_events,
                "resource_event_ids": [int(row["RecordId"]) for row in resource_events],
                "python_allocations_bytes": allocations,
            },
            "observed_state": {
                "completed_official_arms": [],
                "partial_arm": "candidate_web_small",
                "answers_generated": False,
                "outcome_scores_opened": False,
                "per_question_files": 0,
                "aggregated_metrics_files": 0,
                "marker_completed": False,
                "marker": _record(MARKER),
                "run_args": _record(RUN_ARGS),
                "console_log": _record(CONSOLE_LOG),
            },
            "resolved_official_tokenizer": {
                "repository": "Qwen/Qwen3.5-9B",
                "snapshot_revision": snapshot_revision,
                "files": [_cache_record(path) for path in cache_files],
                "reader_or_evaluator_model_changed": False,
            },
            "frozen_execution_parameters": {
                "model": run_args["model"],
                "evaluator_model": run_args["evaluator_model"],
                "temperature": run_args["temperature"],
                "shuffle_questions_seed": run_args["shuffle_questions_seed"],
                "prompt_build_max_workers": run_args["prompt_build_max_workers"],
                "reader_max_concurrent_requests": run_args[
                    "reader_max_concurrent_requests"
                ],
            },
            "continuation_policy": {
                "same_logical_run_required": True,
                "partial_retained_verbatim_required": True,
                "candidate_unchanged_required": True,
                "data_unchanged_required": True,
                "prompts_unchanged_required": True,
                "models_unchanged_required": True,
                "thresholds_unchanged_required": True,
                "order_unchanged_required": True,
                "worker_counts_unchanged_required": True,
                "permitted_harness_change": (
                    "Serialize only calls into the shared candidate backend and keep "
                    "per-worker metadata thread-local. Preserve four official prompt "
                    "workers and all candidate, query, prompt, token-count, model, "
                    "ordering, and scoring semantics."
                ),
                "attempts_count_as_scientific_runs": 1,
            },
            "claim_boundary": (
                "This system-capacity failure produced no benchmark outcome and "
                "authorizes no pass, 100%-pass, SOTA, or revolutionary claim."
            ),
        }
    )
    OUTPUT.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print(json.dumps(payload, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

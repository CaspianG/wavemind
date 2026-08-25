from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

from scientific_longmemeval_v2_backend import (
    CANDIDATE_SOURCE_SHA,
    MEMORY_TYPE,
    OFFICIAL_REPOSITORY_SHA,
    register_backend,
    registration_fingerprint,
)


EXPECTED_QUESTION_COUNT = 451
EXPECTED_DOMAINS = ("web", "enterprise")
EXPECTED_TIER = "small"
MODEL = "mistral:7b"
MODEL_DIGEST = "f974a74358d62a017b37c6f424fcdf2744ca02926c4f952513ddf474b2fa5091"
PROTOCOL_DIGEST = "d140bd10012dc698656b211621be1fb851ae511294114a4b3d5cd73cbdfd2ebc"


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace(
        "+00:00", "Z"
    )


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while block := handle.read(1024 * 1024):
            digest.update(block)
    return digest.hexdigest()


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=True) + "\n",
        encoding="utf-8",
    )


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _git_sha(root: Path) -> str:
    return subprocess.check_output(
        ["git", "rev-parse", "HEAD"],
        cwd=root,
        text=True,
        encoding="utf-8",
    ).strip()


def _require_ollama(endpoint: str) -> None:
    import urllib.request

    request = urllib.request.Request(endpoint.rstrip("/") + "/api/tags")
    with urllib.request.urlopen(request, timeout=10.0) as response:
        payload = json.loads(response.read().decode("utf-8"))
    models = {
        str(row.get("name")): str(row.get("digest"))
        for row in payload.get("models", [])
    }
    if models.get(MODEL) != MODEL_DIGEST:
        raise RuntimeError(
            f"frozen Ollama model mismatch: expected {MODEL} at {MODEL_DIGEST}"
        )


def _arm_order(domain: str) -> tuple[str, str]:
    # Exactly one domain starts with each arm, preventing a global first-arm bias.
    return (
        ("candidate", "no_retrieval")
        if domain == "web"
        else ("no_retrieval", "candidate")
    )


def _completed_arm(output_dir: Path, expected_questions: int) -> bool:
    metrics = output_dir / "aggregated_metrics.json"
    raw = output_dir / "per_question.jsonl"
    if not metrics.is_file() or not raw.is_file():
        return False
    payload = json.loads(metrics.read_text(encoding="utf-8"))
    count = payload.get("overall", {}).get("count_all_questions")
    return int(count or 0) == expected_questions and len(_read_jsonl(raw)) == expected_questions


def _retain_partial(output_dir: Path, retained_root: Path) -> Path | None:
    if not output_dir.exists():
        return None
    retained_root.mkdir(parents=True, exist_ok=True)
    suffix = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    target = retained_root / f"{output_dir.name}-{suffix}"
    shutil.move(str(output_dir), str(target))
    return target


def _run_harness(
    *,
    harness_main: Any,
    domain: str,
    arm: str,
    runtime_dir: Path,
    data_root: Path,
    output_dir: Path,
    endpoint: str,
) -> None:
    config_path = runtime_dir / f"memory_config_{arm}.json"
    config = (
        {
            "memory_type": MEMORY_TYPE,
            "memory_params": {
                "scratch_root": str((output_dir.parent / "candidate-scratch").resolve())
            },
        }
        if arm == "candidate"
        else {"memory_type": "no_retrieval", "memory_params": {}}
    )
    _write_json(config_path, config)
    argv = [
        "evaluation.harness",
        "--domain",
        domain,
        "--questions-path",
        str(runtime_dir / f"questions_{domain}.json"),
        "--haystack-path",
        str(runtime_dir / f"haystack_{domain}.json"),
        "--trajectories-path",
        str(data_root / "trajectories.jsonl"),
        "--memory-config-path",
        str(config_path),
        "--output-dir",
        str(output_dir),
        "--model",
        MODEL,
        "--base-url",
        endpoint.rstrip("/") + "/v1",
        "--temperature",
        "0",
        "--top-p",
        "1",
        "--top-k",
        "20",
        "--max-completion-tokens",
        "512",
        "--memory-context-max-tokens",
        "8192",
        "--reader-max-concurrent-requests",
        "4",
        "--prompt-build-max-workers",
        "4",
        "--shuffle-questions-seed",
        "17",
        "--evaluator-model",
        MODEL,
        "--evaluator-base-url",
        endpoint.rstrip("/") + "/v1",
        "--evaluator-max-completion-tokens",
        "256",
        "--reader-disable-thinking",
    ]
    previous = sys.argv
    try:
        sys.argv = argv
        harness_main()
    finally:
        sys.argv = previous


def run(args: argparse.Namespace) -> dict[str, Any]:
    official_root = args.official_repository.resolve()
    candidate_root = args.candidate_repository.resolve()
    data_root = args.data_root.resolve()
    output_root = args.output_root.resolve()
    marker_path = output_root / "full_run_marker.json"
    if _git_sha(official_root) != OFFICIAL_REPOSITORY_SHA:
        raise RuntimeError("official LongMemEval-V2 SHA changed")
    if _git_sha(candidate_root) != CANDIDATE_SOURCE_SHA:
        raise RuntimeError("candidate SHA changed")
    _require_ollama(args.ollama_endpoint)
    required = [
        data_root / "questions.jsonl",
        data_root / "trajectories.jsonl",
        data_root / "haystacks" / "lme_v2_small.json",
    ]
    for path in required:
        if not path.is_file():
            raise FileNotFoundError(path)
    output_root.mkdir(parents=True, exist_ok=True)
    if marker_path.exists():
        marker = json.loads(marker_path.read_text(encoding="utf-8"))
        if marker.get("candidate_source_sha") != CANDIDATE_SOURCE_SHA:
            raise RuntimeError("existing full-run marker belongs to another candidate")
    else:
        marker = {
            "schema": "wavemind.longmemeval_v2_full_run_marker.v6",
            "logical_full_run_count": 1,
            "started_at": _utc_now(),
            "candidate_source_sha": CANDIDATE_SOURCE_SHA,
            "official_repository_sha": OFFICIAL_REPOSITORY_SHA,
            "protocol_digest": PROTOCOL_DIGEST,
            "tier": EXPECTED_TIER,
            "adapter_sha256": registration_fingerprint(),
            "dataset_files": [
                {
                    "path": str(path),
                    "bytes": path.stat().st_size,
                    "sha256": _sha256(path),
                }
                for path in required
            ],
            "continuation_policy": (
                "Infrastructure partials are retained and the unchanged deterministic "
                "arm may continue inside this single logical full run."
            ),
        }
        _write_json(marker_path, marker)

    register_backend(
        official_repository=official_root,
        candidate_repository=candidate_root,
    )
    from data.public_data import (
        load_questions,
        materialize_runtime_haystack,
        materialize_runtime_questions,
    )
    from evaluation import harness

    harness.NONSHARED_PARALLEL_MEMORY_TYPES.update({MEMORY_TYPE, "no_retrieval"})
    questions = load_questions(data_root)
    if len(questions) != EXPECTED_QUESTION_COUNT:
        raise RuntimeError(
            f"full LongMemEval-V2 requires {EXPECTED_QUESTION_COUNT} questions, "
            f"found {len(questions)}"
        )
    if {str(row.get("domain")) for row in questions} != set(EXPECTED_DOMAINS):
        raise RuntimeError("LongMemEval-V2 domain set mismatch")
    runtime_dir = output_root / "runtime_inputs"
    runtime_dir.mkdir(parents=True, exist_ok=True)
    counts: dict[str, int] = {}
    for domain in EXPECTED_DOMAINS:
        selected = materialize_runtime_questions(
            data_root=data_root,
            domain=domain,
            question_ids=None,
            limit=None,
            output_path=runtime_dir / f"questions_{domain}.json",
        )
        materialize_runtime_haystack(
            data_root=data_root,
            tier=EXPECTED_TIER,
            selected_questions=selected,
            output_path=runtime_dir / f"haystack_{domain}.json",
        )
        counts[domain] = len(selected)
    if sum(counts.values()) != EXPECTED_QUESTION_COUNT:
        raise RuntimeError("materialized question count mismatch")

    retained: list[str] = []
    for domain in EXPECTED_DOMAINS:
        for arm in _arm_order(domain):
            output_dir = output_root / f"{arm}_{domain}_{EXPECTED_TIER}"
            if _completed_arm(output_dir, counts[domain]):
                continue
            partial = _retain_partial(output_dir, output_root / "retained_partials")
            if partial is not None:
                retained.append(str(partial))
            _run_harness(
                harness_main=harness.main,
                domain=domain,
                arm=arm,
                runtime_dir=runtime_dir,
                data_root=data_root,
                output_dir=output_dir,
                endpoint=args.ollama_endpoint,
            )
            if not _completed_arm(output_dir, counts[domain]):
                raise RuntimeError(f"incomplete official arm: {domain}/{arm}")
    marker["completed_at"] = _utc_now()
    marker["question_counts"] = counts
    marker["retained_partials"] = retained
    marker["status"] = "completed"
    _write_json(marker_path, marker)
    return marker


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--official-repository", type=Path, required=True)
    parser.add_argument("--candidate-repository", type=Path, required=True)
    parser.add_argument("--data-root", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--ollama-endpoint", default="http://127.0.0.1:11435")
    return parser.parse_args(argv)


def main() -> int:
    payload = run(parse_args())
    print(json.dumps(payload, indent=2, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

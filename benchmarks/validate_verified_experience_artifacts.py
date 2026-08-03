from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
BENCHMARK_PATH = Path("benchmarks/verified_experience_results.json")
ADMISSION_PATH = Path("benchmarks/verified_experience_admission_results.json")
STATE_BENCH_PATH = Path("benchmarks/state_bench_agent_learning_adapter_results.json")
RUNTIME_FILES = (
    "benchmarks/verified_experience_benchmark.py",
    "wavemind/experience.py",
    "wavemind/experience_compiler.py",
    "wavemind/experience_runtime.py",
    "wavemind/memory_firewall.py",
)


class VerifiedExperienceArtifactError(RuntimeError):
    pass


def _load(root: Path, path: Path) -> dict[str, Any]:
    try:
        value = json.loads((root / path).read_text(encoding="utf-8"))
    except Exception as exc:
        raise VerifiedExperienceArtifactError(
            f"cannot read {path.as_posix()}: {exc}"
        ) from exc
    if not isinstance(value, dict):
        raise VerifiedExperienceArtifactError(
            f"{path.as_posix()} must contain a JSON object"
        )
    return value


def _canonical_artifact_sha256(path: Path) -> str:
    content = path.read_bytes().replace(b"\r\n", b"\n").replace(b"\r", b"\n")
    return hashlib.sha256(content).hexdigest()


def _git(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=root,
        text=True,
        encoding="utf-8",
        capture_output=True,
        check=False,
    )


def validate_verified_experience_artifacts(root: Path = PROJECT_ROOT) -> dict[str, Any]:
    root = Path(root)
    benchmark = _load(root, BENCHMARK_PATH)
    admission = _load(root, ADMISSION_PATH)
    state_bench = _load(root, STATE_BENCH_PATH)
    errors: list[str] = []
    source_sha = str(benchmark.get("source_sha") or "")
    _require(
        len(source_sha) == 40
        and all(char in "0123456789abcdef" for char in source_sha),
        "benchmark source_sha is invalid",
        errors,
    )
    _require(
        benchmark.get("status") == "pass",
        "verified-experience benchmark is not passing",
        errors,
    )
    _require(
        admission.get("status") == "admitted" and admission.get("admitted") is True,
        "verified-experience admission is not admitted",
        errors,
    )
    _require(
        admission.get("source_sha") == source_sha,
        "admission and benchmark source SHA differ",
        errors,
    )
    _require(
        state_bench.get("status") == "runner_ready",
        "STATE-Bench adapter is not runner-ready",
        errors,
    )
    _require(
        state_bench.get("source_sha") == source_sha,
        "STATE-Bench adapter and benchmark source SHA differ",
        errors,
    )
    protocol = (
        state_bench.get("official_protocol")
        if isinstance(state_bench.get("official_protocol"), dict)
        else {}
    )
    counts = (state_bench.get("training_data") or {}).get("file_counts", {})
    _require(
        protocol.get("repository") == "https://github.com/microsoft/STATE-Bench",
        "STATE-Bench repository provenance is missing",
        errors,
    )
    _require(
        _is_sha(protocol.get("repository_sha")),
        "STATE-Bench upstream SHA is missing",
        errors,
    )
    _require(
        counts == {"travel": 100, "customer_support": 100, "shopping_assistant": 100},
        "STATE-Bench train split counts changed",
        errors,
    )
    _require(
        protocol.get("top_k") == 3 and protocol.get("repeats") == 5,
        "STATE-Bench frozen protocol changed",
        errors,
    )
    _require(
        protocol.get("official_paid_model_run_performed") is False,
        "artifact falsely claims an official paid run",
        errors,
    )
    benchmark_hash = _canonical_artifact_sha256(root / BENCHMARK_PATH)
    _require(
        admission.get("artifact_sha256") == benchmark_hash,
        "admission artifact hash does not match benchmark bytes",
        errors,
    )
    _require(
        admission.get("artifact_hash_normalization") == "lf",
        "admission artifact hash normalization is not locked to LF",
        errors,
    )
    if _is_sha(source_sha):
        ancestor = _git(root, "merge-base", "--is-ancestor", source_sha, "HEAD")
        _require(
            ancestor.returncode == 0,
            "benchmark source SHA is not an ancestor of HEAD",
            errors,
        )
        changed = _git(
            root, "diff", "--quiet", source_sha, "HEAD", "--", *RUNTIME_FILES
        )
        _require(
            changed.returncode == 0,
            "runtime or frozen benchmark changed after the evaluated source SHA",
            errors,
        )
    checks = (
        benchmark.get("checks") if isinstance(benchmark.get("checks"), list) else []
    )
    _require(
        len(checks) == 10
        and all(
            item.get("passed") is True for item in checks if isinstance(item, dict)
        ),
        "embedded frozen gates are incomplete or failing",
        errors,
    )
    report = {
        "schema": "wavemind.verified_experience_artifact_validation.v1",
        "status": "pass" if not errors else "fail",
        "source_sha": source_sha,
        "runtime_files": list(RUNTIME_FILES),
        "errors": errors,
    }
    if errors:
        raise VerifiedExperienceArtifactError(json.dumps(report, indent=2))
    return report


def _is_sha(value: Any) -> bool:
    text = str(value or "")
    return len(text) == 40 and all(char in "0123456789abcdef" for char in text)


def _require(condition: bool, message: str, errors: list[str]) -> None:
    if not condition:
        errors.append(message)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=PROJECT_ROOT)
    args = parser.parse_args()
    try:
        report = validate_verified_experience_artifacts(args.root)
    except VerifiedExperienceArtifactError as exc:
        try:
            report = json.loads(str(exc))
        except json.JSONDecodeError:
            report = {"status": "fail", "errors": [str(exc)]}
        print(json.dumps(report, indent=2))
        return 1
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

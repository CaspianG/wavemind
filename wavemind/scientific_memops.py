from __future__ import annotations

import json
import subprocess
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from .evidence import attach_artifact_integrity, file_sha256


MEMOPS_BOUNDED_DEV_SCHEMA = "wavemind.memops_bounded_development.v1"


@dataclass(frozen=True)
class NativeOllamaCaller:
    """MemOps-compatible caller using Ollama's native HTTP API.

    This avoids OpenAI SDK/httpx transport behavior without changing the
    official MemOps runner. It is deliberately limited to bounded development
    evidence and is not an admission transport.
    """

    endpoint: str
    timeout_seconds: float = 300.0
    context_window: int = 32768

    def __call__(
        self,
        prompt: str,
        model: str,
        *,
        temperature: float = 0.0,
        max_tokens: int = 2048,
    ) -> dict[str, Any]:
        payload = {
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "stream": False,
            "options": {
                "temperature": float(temperature),
                "num_predict": int(max_tokens),
                "num_ctx": int(self.context_window),
            },
        }
        request = urllib.request.Request(
            self.endpoint.rstrip("/") + "/api/chat",
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(
                request,
                timeout=self.timeout_seconds,
            ) as response:
                result = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")[:500]
            raise RuntimeError(
                f"Ollama native API returned HTTP {exc.code}: {detail}"
            ) from exc
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            raise RuntimeError(f"Ollama native API request failed: {exc}") from exc

        message = result.get("message")
        content = message.get("content") if isinstance(message, Mapping) else None
        if not isinstance(content, str):
            raise RuntimeError("Ollama native API response has no message content")
        prompt_tokens = int(result.get("prompt_eval_count") or 0)
        completion_tokens = int(result.get("eval_count") or 0)
        return {
            "content": content,
            "model": str(result.get("model") or model),
            "usage": {
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "total_tokens": prompt_tokens + completion_tokens,
            },
        }


def exact_git_sha(repository: str | Path) -> str:
    return subprocess.check_output(
        ["git", "rev-parse", "HEAD"],
        cwd=Path(repository),
        text=True,
        encoding="utf-8",
    ).strip()


def require_exact_upstream_sha(repository: str | Path, expected_sha: str) -> None:
    actual_sha = exact_git_sha(repository)
    if actual_sha != expected_sha:
        raise RuntimeError(
            f"MemOps upstream SHA mismatch: expected {expected_sha}, got {actual_sha}"
        )


def build_bounded_dev_artifact(
    *,
    source_sha: str,
    memops_sha: str,
    model: str,
    model_digest: str,
    context_window: int,
    endpoint_kind: str,
    split_unit_ids: Sequence[str],
    case_ids: Sequence[str],
    output_files: Sequence[str | Path],
    failed_attempt_files: Sequence[str | Path],
    summary: Mapping[str, Any],
) -> dict[str, Any]:
    def file_rows(paths: Sequence[str | Path]) -> list[dict[str, Any]]:
        rows = []
        for raw_path in paths:
            path = Path(raw_path).resolve()
            if not path.is_file():
                raise FileNotFoundError(path)
            rows.append(
                {
                    "path": str(path),
                    "bytes": path.stat().st_size,
                    "sha256": file_sha256(path),
                }
            )
        return sorted(rows, key=lambda row: row["path"])

    payload = {
        "schema": MEMOPS_BOUNDED_DEV_SCHEMA,
        "phase": "bounded-development",
        "admission_eligible": False,
        "reason_not_admission_eligible": (
            "local Ollama transport and development split; official held-out "
            "credentials and locked admission models were not used"
        ),
        "source_sha": source_sha,
        "official_upstream": {
            "repository": "MemTensor/MemOps",
            "sha": memops_sha,
            "runners": [
                "5-test_operation_metrics.py:run_pipeline",
                "5.5-evaluate_operation_metrics.py:run_pipeline",
            ],
            "upstream_modified": False,
        },
        "model": {
            "id": model,
            "digest": model_digest,
            "context_window": int(context_window),
        },
        "transport": endpoint_kind,
        "split_unit_ids": sorted(set(split_unit_ids)),
        "case_ids": list(case_ids),
        "case_count": len(case_ids),
        "final_split_touched": False,
        "failed_attempts_retained": file_rows(failed_attempt_files),
        "outputs": file_rows(output_files),
        "official_summary": dict(summary),
    }
    return attach_artifact_integrity(payload)

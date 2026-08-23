from __future__ import annotations

import json

import pytest

from wavemind.evidence import file_sha256, validate_artifact_integrity
from wavemind.scientific_memops import (
    MEMOPS_BOUNDED_DEV_SCHEMA,
    NativeOllamaCaller,
    build_bounded_dev_artifact,
    require_exact_upstream_sha,
)


class _Response:
    def __init__(self, payload: dict[str, object]) -> None:
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return None

    def read(self) -> bytes:
        return json.dumps(self.payload).encode()


def test_native_ollama_caller_returns_memops_compatible_usage(monkeypatch):
    captured = {}

    def fake_urlopen(request, timeout):
        captured["payload"] = json.loads(request.data)
        captured["timeout"] = timeout
        return _Response(
            {
                "model": "mistral:7b",
                "message": {"content": '{"answer":"Portland"}'},
                "prompt_eval_count": 12,
                "eval_count": 4,
            }
        )

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    result = NativeOllamaCaller("http://localhost:11435")(
        "question",
        "mistral:7b",
        temperature=0.1,
        max_tokens=32,
    )

    assert result["content"] == '{"answer":"Portland"}'
    assert result["usage"] == {
        "prompt_tokens": 12,
        "completion_tokens": 4,
        "total_tokens": 16,
    }
    assert captured["payload"]["options"] == {
        "temperature": 0.1,
        "num_predict": 32,
        "num_ctx": 32768,
    }


def test_bounded_dev_artifact_retains_failures_and_forbids_admission(tmp_path):
    output = tmp_path / "output.jsonl"
    failed = tmp_path / "failed.jsonl"
    output.write_text('{"ok":true}\n', encoding="utf-8")
    failed.write_text('{"answer_error":"503"}\n', encoding="utf-8")

    payload = build_bounded_dev_artifact(
        source_sha="a" * 40,
        memops_sha="b" * 40,
        model="mistral:7b",
        model_digest="sha256:example",
        context_window=32768,
        endpoint_kind="ollama-native-api/local-development-only",
        split_unit_ids=("A04_remember", "A04_remember"),
        output_files=(output,),
        failed_attempt_files=(failed,),
        summary={"rag_entries": 1},
    )

    assert payload["schema"] == MEMOPS_BOUNDED_DEV_SCHEMA
    assert payload["phase"] == "bounded-development"
    assert payload["admission_eligible"] is False
    assert payload["final_split_touched"] is False
    assert payload["split_unit_ids"] == ["A04_remember"]
    assert payload["failed_attempts_retained"][0]["sha256"] == file_sha256(failed)
    assert validate_artifact_integrity(payload) == []


def test_exact_upstream_sha_rejects_mismatch(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "wavemind.scientific_memops.exact_git_sha",
        lambda repository: "a" * 40,
    )

    with pytest.raises(RuntimeError, match="upstream SHA mismatch"):
        require_exact_upstream_sha(tmp_path, "b" * 40)

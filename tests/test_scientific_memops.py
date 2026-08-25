from __future__ import annotations

import json

import pytest

from wavemind.evidence import file_sha256, validate_artifact_integrity
from wavemind.scientific_memops import (
    MEMOPS_BOUNDED_DEV_SCHEMA,
    MEMOPS_CANDIDATE_DEV_SCHEMA,
    NativeOllamaCaller,
    ScientificMemOpsRetriever,
    build_bounded_dev_artifact,
    build_candidate_dev_artifact,
    classify_memory_operation_dialogue,
    require_exact_upstream_sha,
)
from wavemind.scientific_runtime import ScientificCandidateMode


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
        case_ids=("A04_remember_q2",),
        output_files=(output,),
        failed_attempt_files=(failed,),
        summary={"rag_entries": 1},
    )

    assert payload["schema"] == MEMOPS_BOUNDED_DEV_SCHEMA
    assert payload["phase"] == "bounded-development"
    assert payload["admission_eligible"] is False
    assert payload["final_split_touched"] is False
    assert payload["split_unit_ids"] == ["A04_remember"]
    assert payload["case_ids"] == ["A04_remember_q2"]
    assert payload["case_count"] == 1
    assert payload["failed_attempts_retained"][0]["sha256"] == file_sha256(failed)
    assert validate_artifact_integrity(payload) == []


def test_exact_upstream_sha_rejects_mismatch(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "wavemind.scientific_memops.exact_git_sha",
        lambda repository: "a" * 40,
    )

    with pytest.raises(RuntimeError, match="upstream SHA mismatch"):
        require_exact_upstream_sha(tmp_path, "b" * 40)


def test_memops_adapter_abstains_in_production_and_allows_shadow(tmp_path):
    corpus = [
        {
            "corpus_id": "A04#session1",
            "text": "user: I live in Portland on Division Street.",
            "has_evidence": True,
            "gold_secret": "must never affect retrieval",
        },
        {
            "corpus_id": "A04#session2",
            "text": "user: I enjoy a plain pour-over coffee.",
            "has_evidence": False,
        },
    ]
    with ScientificMemOpsRetriever(
        tmp_path / "candidate.db",
        corpus=corpus,
        mode=ScientificCandidateMode.CAUSAL,
    ) as retriever:
        production_items, production_recall = retriever.retrieve(
            "Where do I live?",
            token_budget=100,
            top_k_context=1,
            evaluation_only=False,
        )
        shadow_items, shadow_recall = retriever.retrieve(
            "Where do I live?",
            token_budget=100,
            top_k_context=1,
            evaluation_only=True,
        )

    assert production_items == []
    assert production_recall.abstained is True
    assert len(shadow_items) == 1
    assert shadow_recall.evaluation_only is True
    assert shadow_recall.abstained is False
    assert "gold_secret" in shadow_items[0]
    assert "gold_secret" not in shadow_recall.contents[0]


def test_candidate_dev_artifact_is_explicitly_non_admission(tmp_path):
    raw = tmp_path / "raw_pairs.jsonl"
    raw.write_text('{"paired_effect":1.0}\n', encoding="utf-8")
    payload = build_candidate_dev_artifact(
        source_sha="a" * 40,
        protocol_digest="b" * 64,
        memops_sha="c" * 40,
        candidate_id="causal-utility-controller-v1",
        model="mistral:7b",
        model_digest="d" * 64,
        context_window=32768,
        raw_output_file=raw,
        case_ids=("case-1", "case-2"),
        paired_effects=(1.0, 0.0),
        verified_receipt_count=2,
        false_verified_promotions=0,
        production_case_count=0,
        promoted_memory_ids=(),
    )

    assert payload["schema"] == MEMOPS_CANDIDATE_DEV_SCHEMA
    assert payload["admission_eligible"] is False
    assert payload["paired_effect"]["mean"] == 0.5
    assert payload["paired_effect"]["positive_count"] == 1
    assert payload["verified_receipt_count"] == 2
    assert payload["false_verified_promotions"] == 0
    assert validate_artifact_integrity(payload) == []


def test_v6_filters_distractors_and_ranks_tombstone_before_memory(tmp_path):
    corpus = [
        {
            "corpus_id": "A04#session46",
            "session_index": 46,
            "text": "user: How can I practice mindfulness?\nassistant: Try breathing.",
            "gold_secret": "must not make a distractor eligible",
        },
        {
            "corpus_id": "A04#session4",
            "session_index": 4,
            "text": (
                "user: I live in Portland on Division Street. Can you keep that "
                "on file?\nassistant: Noted — Portland is your current city."
            ),
        },
        {
            "corpus_id": "A04#session15",
            "session_index": 15,
            "text": (
                "user: Please forget the Tucson detail; do not reference it.\n"
                "assistant: Done — I removed the previous city."
            ),
        },
    ]

    assert classify_memory_operation_dialogue(corpus[0]["text"]) == (False, False)
    assert classify_memory_operation_dialogue(corpus[1]["text"]) == (True, False)
    assert classify_memory_operation_dialogue(corpus[2]["text"]) == (True, True)

    with ScientificMemOpsRetriever(
        tmp_path / "v6.db",
        corpus=corpus,
        mode=ScientificCandidateMode.OPERATION_AWARE_TOMBSTONE_RECONCILER,
    ) as retriever:
        ranked, recall = retriever.retrieve(
            "Where do I live now?",
            token_budget=200,
            top_k_context=10,
            evaluation_only=True,
        )

        assert [item["corpus_id"] for item in ranked] == [
            "A04#session15",
            "A04#session4",
        ]
        assert recall.reason == (
            "evaluation-only operation evidence with mandatory tombstones"
        )
        assert retriever.runtime.retriever.store.count(namespace="scientific") == 0
        assert retriever.runtime.event_log.validate_chain() == []

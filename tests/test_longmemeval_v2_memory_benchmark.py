from __future__ import annotations

import json
import urllib.request
from pathlib import Path

import numpy as np
import pytest

from benchmarks.longmemeval_v2_memory_benchmark import (
    OllamaReader,
    PersistentCachedTextEncoder,
    V2Question,
    _encoder_metadata,
    _experience_query_intent,
    _resume_reranker_config,
    _stratified_question_sample,
    load_longmemeval_v2_small,
    _retrieval_query,
    _query_snippet,
    run_benchmark,
    score_response,
)
from wavemind.encoders import HashingTextEncoder, OllamaTextEncoder


class FixtureReader:
    model = "fixture-reader"
    vision_model = "fixture-vision-reader"
    supports_images = True

    def __init__(self):
        self.answer_calls = 0

    def answer(self, *, question, context):
        assert context
        self.answer_calls += 1
        return f"Evidence considered. \\boxed{{{question.answer}}}"

    def judge(self, *, evaluator, question, response):
        return question.answer.lower() in response.lower()


def test_encoder_metadata_records_reproducible_ollama_configuration():
    encoder = OllamaTextEncoder(
        model_name="qwen3-embedding:0.6b",
        base_url="http://127.0.0.1:11435/",
        vector_dim=1024,
        batch_size=16,
        query_instruction="retrieve relevant trajectory states",
    )

    assert _encoder_metadata(encoder) == {
        "kind": "ollama",
        "class": "OllamaTextEncoder",
        "vector_dim": 1024,
        "model": "qwen3-embedding:0.6b",
        "base_url": "http://127.0.0.1:11435",
        "batch_size": 16,
        "query_instruction": "retrieve relevant trajectory states",
        "normalized": True,
        "query_document_asymmetric": True,
    }
    assert _encoder_metadata(
        HashingTextEncoder(vector_dim=384, char_ngram_weight=0.0)
    ) == {
        "kind": "hash-token",
        "class": "HashingTextEncoder",
        "vector_dim": 384,
        "char_ngram_weight": 0.0,
    }


def test_legacy_resume_without_reranker_is_strictly_normalized_as_disabled():
    assert _resume_reranker_config({}) == {
        "enabled": False,
        "embedding": None,
        "candidate_window": 0,
        "rrf_weight": 0.0,
    }
    assert _resume_reranker_config(
        {
            "semantic_reranker": {
                "enabled": True,
                "embedding": {"kind": "fixture"},
                "candidate_window": 20,
                "rrf_weight": 0.7,
            }
        }
    ) == {
        "enabled": True,
        "embedding": {"kind": "fixture"},
        "candidate_window": 20,
        "rrf_weight": 0.7,
    }


def test_persistent_embedding_cache_resumes_without_reencoding(tmp_path):
    class CountingEncoder:
        vector_dim = 3
        batch_size = 2
        cache_key = "fixture-encoder-v1"

        def __init__(self):
            self.single_calls = 0
            self.batch_calls = 0

        def encode_vector(self, text):
            self.single_calls += 1
            return np.asarray([3.0, 4.0, 0.0], dtype=np.float32)

        def encode_vectors(self, texts):
            values = list(texts)
            self.batch_calls += 1
            return np.asarray(
                [[3.0, 4.0, 0.0] for _ in values],
                dtype=np.float32,
            )

    cache_path = tmp_path / "embeddings.sqlite3"
    first_base = CountingEncoder()
    first = PersistentCachedTextEncoder(first_base, cache_path)
    try:
        first_documents = first.encode_document_vectors(["alpha", "beta"])
        first_query = first.encode_query_vector("question")
        assert first_base.batch_calls == 1
        assert first_base.single_calls == 1
        assert first.stats()["writes"] == 3
    finally:
        first.close()

    second_base = CountingEncoder()
    second = PersistentCachedTextEncoder(second_base, cache_path)
    try:
        second_documents = second.encode_document_vectors(["alpha", "beta"])
        second_query = second.encode_query_vector("question")
        assert np.allclose(second_documents, first_documents)
        assert np.allclose(second_query, first_query)
        assert second_base.batch_calls == 0
        assert second_base.single_calls == 0
        assert second.stats()["entries"] == 3
        assert second.stats()["hits"] == 3
    finally:
        second.close()


def test_persistent_embedding_cache_keeps_completed_batches_after_failure(tmp_path):
    class FailingEncoder:
        vector_dim = 2
        batch_size = 2
        cache_key = "failing-encoder-v1"

        def __init__(self, fail_after=None):
            self.batch_calls = 0
            self.fail_after = fail_after

        def encode_vectors(self, texts):
            values = list(texts)
            self.batch_calls += 1
            if self.fail_after is not None and self.batch_calls > self.fail_after:
                raise RuntimeError("simulated transport timeout")
            return np.asarray(
                [[float(len(value)), 1.0] for value in values],
                dtype=np.float32,
            )

        def encode_vector(self, text):
            return self.encode_vectors([text])[0]

    cache_path = tmp_path / "resume.sqlite3"
    first_base = FailingEncoder(fail_after=1)
    first = PersistentCachedTextEncoder(first_base, cache_path)
    try:
        with pytest.raises(RuntimeError, match="simulated transport timeout"):
            first.encode_document_vectors(["one", "two", "three", "four"])
        assert first.stats()["entries"] == 2
    finally:
        first.close()

    resumed_base = FailingEncoder()
    resumed = PersistentCachedTextEncoder(resumed_base, cache_path)
    try:
        vectors = resumed.encode_document_vectors(
            ["one", "two", "three", "four"]
        )
        assert vectors.shape == (4, 2)
        assert resumed.stats()["hits"] == 2
        assert resumed.stats()["writes"] == 2
        assert resumed_base.batch_calls == 1
    finally:
        resumed.close()


def test_stratified_question_sample_is_reproducible_and_covers_strata():
    rows = [
        {
            "id": f"web-{index}",
            "domain": "web",
            "question_type": "procedure",
            "image": None,
        }
        for index in range(8)
    ]
    rows.extend(
        {
            "id": f"enterprise-{index}",
            "domain": "enterprise",
            "question_type": "static-environment",
            "image": "question.png",
        }
        for index in range(2)
    )

    first = _stratified_question_sample(rows, sample_size=4, seed=7)
    second = _stratified_question_sample(rows, sample_size=4, seed=7)

    assert [row["id"] for row in first] == [row["id"] for row in second]
    assert {row["domain"] for row in first} == {"web", "enterprise"}
    assert len(first) == 4


def test_query_snippet_keeps_relevant_windows_from_long_single_lines():
    text = (
        "irrelevant field " * 300
        + "Dell XPS largest SSD option costs an extra 300 dollars "
        + "unrelated footer " * 300
    )

    snippet = _query_snippet(
        text,
        "What is the extra amount for the largest Dell XPS SSD option?",
        max_chars=1200,
        chunk_chars=400,
        chunk_overlap=80,
    )

    assert "extra 300 dollars" in snippet
    assert len(snippet) <= 1200


def test_query_snippet_preserves_neighboring_ui_options():
    text = "\n".join(
        [
            "unrelated heading",
            "menuitem Edit personal filters",
            "menuitem Incident Mobile",
            "menuitem Incident Portal",
            "menuitem My Open Incidents",
            "unrelated footer",
        ]
    )

    snippet = _query_snippet(
        text,
        "filters incident portal open",
        max_chars=200,
    )

    assert "Incident Mobile" in snippet
    assert "Incident Portal" in snippet
    assert "My Open Incidents" in snippet


def test_retrieval_query_removes_answer_formatting_and_conversation_filler():
    query = _retrieval_query(
        "I am working with our ServiceNow portal. Which Filters contain "
        "Incident?\n\nMark your final answer in \\boxed{}."
    )

    assert query == "servicenow portal filters contain incident"


def test_experience_query_intent_is_feedback_free_and_conservative():
    assert (
        _experience_query_intent(
            "In our typical workflow, which form should I open?"
        )
        == "procedure"
    )
    assert (
        _experience_query_intent(
            'Which column header sits between "Price" and "Delivery time"?'
        )
        == "state"
    )


def _write_fixture(root: Path) -> None:
    (root / "haystacks").mkdir(parents=True)
    questions = [
        {
            "id": "q1",
            "domain": "web",
            "environment": "shop",
            "question_type": "procedure",
            "question": "Which button completes checkout?",
            "image": None,
            "answer": "Place order",
            "eval_function": (
                "norm_phrase_set_match|lower=true|normalize_hyphen=true|"
                "strip_punct=true|separators=,;|require_non_empty=true"
            ),
        },
        {
            "id": "q2",
            "domain": "enterprise",
            "environment": "service",
            "question_type": "static-environment",
            "question": "Which option is correct?",
            "image": "question.png",
            "answer": "B",
            "eval_function": "mc_choice_match|strip_chars=.|require_non_empty=true",
        },
    ]
    (root / "question.png").write_bytes(b"fixture-image")
    (root / "questions.jsonl").write_text(
        "".join(json.dumps(row) + "\n" for row in questions),
        encoding="utf-8",
    )
    trajectories = []
    web_ids = []
    enterprise_ids = []
    for index in range(100):
        for domain, ids in (
            ("web", web_ids),
            ("enterprise", enterprise_ids),
        ):
            trajectory_id = f"{domain}-{index}"
            ids.append(trajectory_id)
            trajectories.append(
                {
                    "id": trajectory_id,
                    "domain": domain,
                    "environment": "fixture",
                    "goal": "complete the fixture task",
                    "outcome": "success",
                    "states": [
                        {
                            "state_index": 0,
                            "url": "https://example.test",
                            "action": "click",
                            "thought": "follow the remembered workflow",
                            "accessibility_tree": (
                                "Place order button. Correct option B."
                            ),
                        }
                    ],
                }
            )
    (root / "trajectories.jsonl").write_text(
        "".join(json.dumps(row) + "\n" for row in trajectories),
        encoding="utf-8",
    )
    (root / "haystacks" / "lme_v2_small.json").write_text(
        json.dumps({"q1": web_ids, "q2": enterprise_ids}),
        encoding="utf-8",
    )


def test_loader_requires_complete_small_haystacks_and_pins_checksums(tmp_path):
    _write_fixture(tmp_path)

    dataset = load_longmemeval_v2_small(tmp_path)

    assert len(dataset.questions) == 2
    assert len(dataset.memories) == 200
    assert len(dataset.haystacks["q1"]) == 100
    assert dataset.haystacks["q1"][0] == "web-0"
    assert len(dataset.source_files["trajectories_sha256"]) == 64
    assert dataset.questions[1].image == str(
        (tmp_path / "question.png").resolve()
    )


def test_official_style_deterministic_scorers():
    reader = FixtureReader()
    phrase = V2Question(
        "q",
        "web",
        "shop",
        "procedure",
        "question",
        None,
        "Place order",
        "norm_phrase_set_match|separators=,;",
    )
    choice = V2Question(
        "q2",
        "web",
        "shop",
        "procedure",
        "question",
        None,
        "B",
        "mc_choice_match",
    )

    assert score_response(
        phrase,
        "Final: \\boxed{Place order}",
        reader=reader,
    )
    assert score_response(choice, "\\boxed{B}", reader=reader)
    assert not score_response(choice, "\\boxed{A}", reader=reader)


def test_memory_os_executes_inside_v2_runner_and_reuses_equal_answers(tmp_path):
    _write_fixture(tmp_path)
    reader = FixtureReader()
    checkpoint_rows = []
    work_dir = tmp_path / "generated" / "work"

    payload, rows = run_benchmark(
        tmp_path,
        reader=reader,
        top_k=3,
        work_dir=work_dir,
        on_row=checkpoint_rows.append,
    )
    results = {row["engine"]: row for row in payload["results"]}
    memory_os = results["WaveMind + Memory OS"]

    assert payload["schema"] == "wavemind.longmemeval_v2_small.v1"
    assert payload["scenario"]["queries"] == 2
    assert payload["scenario"]["question_images_supported"] is True
    assert payload["scenario"]["official_question_haystacks"] is True
    assert payload["scenario"]["isolated_ab_stores"] is True
    assert payload["retrieval"]["query_instruction_normalization"] is True
    assert payload["retrieval"]["lexical_idf_normalization"] is False
    assert payload["retrieval"]["diversity_metadata_key"] == "trajectory_id"
    assert payload["retrieval"]["candidate_top_k"] == 30
    assert payload["retrieval"]["memory_os_view"] == {
        "kind": "ordered_trajectory_experience",
        "input_tag": "trajectory-state",
        "output_tag": "trajectory-experience",
        "max_summary_chars": 4_800,
        "source_states_preserved": True,
        "shortlist_policy": "same_raw_top_k_as_core",
        "query_routing": "feedback_free_procedure_intent",
        "reader_evidence": "intent_selected_record",
        "answer_labels_used": False,
    }
    assert (
        memory_os["execution_mode"]
        == "memory_os_feedback_free_intent_routed_experience"
    )
    assert (
        memory_os["retrieval_view"]
        == "intent_routed_state_or_trajectory_experience"
    )
    assert memory_os["retrieval_tags"] == [
        "intent:procedure=trajectory-experience",
        "intent:state=trajectory-state",
    ]
    assert memory_os["reader_evidence_view"] == "retrieved_record"
    assert memory_os["trajectory_consolidation"]["created"] > 0
    assert (
        memory_os["trajectory_consolidation"]["provenance_coverage"]
        == 1.0
    )
    assert memory_os["trajectory_consolidation_ms"] > 0.0
    assert memory_os["worker_runs"] == 2
    assert memory_os["worker_errors"] == 0
    assert memory_os["maintenance_interval_queries"] == 32
    assert memory_os["candidate_top_k"] == 30
    assert memory_os["diversity_metadata_key"] == "trajectory_id"
    assert memory_os["max_results_per_diversity_group"] == 2
    assert memory_os["request_path_excludes_background_maintenance"] is True
    assert memory_os["end_to_end_p95_ms"] == memory_os["p95_latency_ms"]
    assert memory_os["maintenance_p95_ms"] > 0.0
    assert memory_os["maintenance_total_ms"] > 0.0
    assert memory_os["maintenance_amortized_ms_per_query"] > 0.0
    assert memory_os["retrieval_answer_recoverability"] == {
        "expected_answer_recoverable_rate": 1.0,
        "eligible_queries": 1,
        "category_rates": {"procedure": 1.0},
        "claim_boundary": (
            "Diagnostic label-presence check for deterministic phrase questions. "
            "It is not the official LongMemEval-V2 answer-quality score and is "
            "never used for admission."
        ),
    }
    assert memory_os["task_success_rate"] == 1.0
    assert memory_os["reused_answers"] == 1
    assert memory_os["generated_answers"] == 1
    assert reader.answer_calls == 3
    assert len(rows) == 4
    assert checkpoint_rows == rows
    assert all(row["context_sha256"] for row in rows)
    assert work_dir.is_dir()


def test_v2_runner_applies_explicit_semantic_top_window_reranker(tmp_path):
    class FixtureSemanticEncoder:
        vector_dim = 3

        def encode_vector(self, text):
            return np.asarray([1.0, 0.0, 0.0], dtype=np.float32)

        def encode_vectors(self, texts):
            return np.asarray(
                [
                    [1.0, float("Place order" in text), 0.0]
                    for text in texts
                ],
                dtype=np.float32,
            )

    _write_fixture(tmp_path)
    payload, _ = run_benchmark(
        tmp_path,
        semantic_reranker=FixtureSemanticEncoder(),
        semantic_rerank_k=5,
        semantic_rerank_weight=0.7,
        top_k=3,
        work_dir=tmp_path / "work",
    )
    results = {row["engine"]: row for row in payload["results"]}

    assert payload["semantic_reranker"] == {
        "enabled": True,
        "embedding": {
            "kind": "custom",
            "class": "FixtureSemanticEncoder",
            "vector_dim": 3,
        },
        "candidate_window": 5,
        "rrf_weight": 0.7,
        "cache": {"enabled": False},
    }
    assert results["WaveMind"]["semantic_reranker_enabled"] is True
    assert results["WaveMind"]["semantic_rerank_k"] == 5
    assert results["WaveMind"]["semantic_rerank_weight"] == 0.7
    assert results["WaveMind"]["retrieval_answer_recoverability"][
        "expected_answer_recoverable_rate"
    ] == 1.0


def test_v2_runner_resumes_only_matching_non_error_contexts(tmp_path):
    _write_fixture(tmp_path)
    first_reader = FixtureReader()
    first_payload, first_rows = run_benchmark(
        tmp_path,
        reader=first_reader,
        top_k=3,
        work_dir=tmp_path,
    )

    class NoCallReader(FixtureReader):
        def answer(self, *, question, context):
            raise AssertionError("matching checkpoint should avoid inference")

    resumed_payload, resumed_rows = run_benchmark(
        tmp_path,
        reader=NoCallReader(),
        top_k=3,
        work_dir=tmp_path,
        resume_rows=first_rows,
        resume_metadata={
            "used": True,
            "source_sha": first_payload["source_sha"],
            "rows": len(first_rows),
        },
    )

    assert resumed_payload["resume"]["used"] is True
    assert all(result["errors"] == 0 for result in resumed_payload["results"])
    assert all(result["generated_answers"] == 0 for result in resumed_payload["results"])
    assert len(resumed_rows) == 4


def test_ollama_reader_expands_context_only_for_images(tmp_path):
    image_path = tmp_path / "question.png"
    image_path.write_bytes(b"image")
    requests = []

    class Response:
        def __init__(self, body):
            self.body = body

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def read(self):
            return self.body

    class Opener:
        def open(self, request, timeout):
            assert isinstance(request, urllib.request.Request)
            payload = json.loads(request.data.decode("utf-8"))
            requests.append(payload)
            response = (
                json.dumps({"answer": "ok"})
                if "format" in payload
                else "\\boxed{ok}"
            )
            return Response(
                json.dumps({"response": response}).encode("utf-8")
            )

    reader = OllamaReader(
        model="fixture",
        vision_model="fixture-vision",
        image_context_window=4096,
        image_context_items=1,
        image_context_chars=1000,
    )
    reader._opener = Opener()
    reader._generate("text only")
    reader._generate("with image", image=str(image_path))
    answer = reader.answer(
        question=V2Question(
            "image-question",
            "web",
            "shop",
            "errors-gotchas",
            "What is visible?",
            str(image_path),
            "answer",
            "llm_gotchas_checker",
        ),
        context=[
            "first evidence " + ("middle " * 300) + " first evidence tail",
            "excluded evidence",
        ],
    )

    assert requests[0]["options"]["num_ctx"] == 8192
    assert requests[0]["think"] is False
    assert requests[1]["options"]["num_ctx"] == 4096
    assert answer == "\\boxed{ok}"
    image_prompt = requests[2]["prompt"]
    assert requests[2]["format"]["required"] == ["answer"]
    assert "precise benchmark evidence reader" in requests[2]["system"]
    assert "first evidence" in image_prompt
    assert "middle truncated for reader context budget" in image_prompt
    assert "first evidence tail" in image_prompt
    assert "excluded evidence" not in image_prompt

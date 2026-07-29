from __future__ import annotations

import json
import urllib.request
from pathlib import Path

from benchmarks.longmemeval_v2_memory_benchmark import (
    OllamaReader,
    V2Question,
    load_longmemeval_v2_small,
    _query_snippet,
    run_benchmark,
    score_response,
)


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

    payload, rows = run_benchmark(
        tmp_path,
        reader=reader,
        top_k=3,
        work_dir=tmp_path,
        on_row=checkpoint_rows.append,
    )
    results = {row["engine"]: row for row in payload["results"]}
    memory_os = results["WaveMind + Memory OS"]

    assert payload["schema"] == "wavemind.longmemeval_v2_small.v1"
    assert payload["scenario"]["queries"] == 2
    assert payload["scenario"]["question_images_supported"] is True
    assert payload["scenario"]["official_question_haystacks"] is True
    assert payload["scenario"]["isolated_ab_stores"] is True
    assert memory_os["execution_mode"] == "memory_os_direct_feedback_free"
    assert memory_os["worker_runs"] == 2
    assert memory_os["worker_errors"] == 0
    assert memory_os["maintenance_interval_queries"] == 32
    assert memory_os["task_success_rate"] == 1.0
    assert memory_os["reused_answers"] == 2
    assert memory_os["generated_answers"] == 0
    assert reader.answer_calls == 2
    assert len(rows) == 4
    assert checkpoint_rows == rows
    assert all(row["context_sha256"] for row in rows)


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
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def read(self):
            return b'{"response":"\\\\boxed{ok}"}'

    class Opener:
        def open(self, request, timeout):
            assert isinstance(request, urllib.request.Request)
            requests.append(json.loads(request.data.decode("utf-8")))
            return Response()

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
    reader.answer(
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
    assert requests[1]["options"]["num_ctx"] == 4096
    image_prompt = requests[2]["prompt"]
    assert "first evidence" in image_prompt
    assert "middle truncated for reader context budget" in image_prompt
    assert "first evidence tail" in image_prompt
    assert "excluded evidence" not in image_prompt

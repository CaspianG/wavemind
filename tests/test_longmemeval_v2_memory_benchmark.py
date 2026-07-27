from __future__ import annotations

import json
from pathlib import Path

from benchmarks.longmemeval_v2_memory_benchmark import (
    V2Question,
    load_longmemeval_v2_small,
    run_benchmark,
    score_response,
)


class FixtureReader:
    model = "fixture-reader"
    supports_images = True

    def answer(self, *, question, context):
        assert context
        return f"Evidence considered. \\boxed{{{question.answer}}}"

    def judge(self, *, evaluator, question, response):
        return question.answer.lower() in response.lower()


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

    payload, rows = run_benchmark(
        tmp_path,
        reader=FixtureReader(),
        top_k=3,
        work_dir=tmp_path,
    )
    results = {row["engine"]: row for row in payload["results"]}
    memory_os = results["WaveMind + Memory OS"]

    assert payload["schema"] == "wavemind.longmemeval_v2_small.v1"
    assert payload["scenario"]["queries"] == 2
    assert payload["scenario"]["question_images_supported"] is True
    assert memory_os["execution_mode"] == "memory_os_direct_feedback_free"
    assert memory_os["worker_runs"] == 2
    assert memory_os["worker_errors"] == 0
    assert memory_os["task_success_rate"] == 1.0
    assert len(rows) == 4
    assert all(row["context_sha256"] for row in rows)

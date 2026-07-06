import json
import os
import subprocess
import sys
from pathlib import Path


def write_longmemeval_fixture(path: Path) -> None:
    payload = [
        {
            "question_id": "q1",
            "question_type": "knowledge-update",
            "question": "What budget did Andrey finally choose?",
            "answer": "2000 dollars.",
            "question_date": "2026-01-20",
            "haystack_session_ids": ["s1", "s2"],
            "haystack_dates": ["2026-01-01", "2026-01-10"],
            "haystack_sessions": [
                [
                    {"role": "user", "content": "My old budget was 500 dollars."},
                    {"role": "assistant", "content": "I will remember the old budget."},
                ],
                [
                    {"role": "user", "content": "Update my tool budget to 2000 dollars.", "has_answer": True},
                    {"role": "assistant", "content": "Budget updated."},
                ],
            ],
            "answer_session_ids": ["s2"],
        }
    ]
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_answer_metrics_normalize_and_score_tokens():
    from benchmarks.longmemeval_answer_benchmark import (
        answer_grounded_in_context,
        clean_generated_answer,
        is_generated_abstention,
        normalize_answer,
        token_f1,
    )

    assert normalize_answer("Business Administration!") == "business administration"
    assert token_f1("Business Administration", "Business Administration") == 1.0
    assert token_f1("Administration", "Business Administration") > 0.0
    assert token_f1("crypto trader", "Business Administration") == 0.0
    assert clean_generated_answer("Answer: Business Administration") == "Business Administration"
    assert clean_generated_answer("<think>hidden</think>\nFinal Answer: 2000 dollars") == "2000 dollars"
    assert is_generated_abstention("I don't know.")
    assert answer_grounded_in_context(
        "Business Administration",
        ["user: I graduated with a degree in Business Administration."],
    )
    assert not answer_grounded_in_context("Summer Vibes", ["user: I studied Business Administration."])


def test_ollama_loopback_urls_bypass_system_proxy(monkeypatch):
    from benchmarks import longmemeval_answer_benchmark as bench

    opened = []

    class DummyResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return None

        def read(self):
            return b'{"models":[]}'

    def fake_open(target, timeout):
        opened.append((target, timeout))
        return DummyResponse()

    monkeypatch.setattr(bench._NO_PROXY_OPENER, "open", fake_open)

    assert bench.ollama_models("http://127.0.0.1:11434") == []
    assert opened and opened[0][0] == "http://127.0.0.1:11434/api/tags"


def test_compact_evidence_selects_question_relevant_lines():
    from benchmarks.longmemeval_answer_benchmark import compact_evidence

    contexts = [
        "\n".join(
            [
                "assistant: Here is unrelated setup text.",
                "user: I graduated with a degree in Business Administration.",
                "assistant: Congratulations on your degree.",
            ]
        )
    ]

    snippets = compact_evidence("What degree did I graduate with?", contexts)

    assert len(snippets) == 1
    assert "Business Administration" in snippets[0]


def test_longmemeval_answer_cli_extractive_mode(tmp_path):
    path = tmp_path / "longmemeval.json"
    output = tmp_path / "answer.json"
    write_longmemeval_fixture(path)
    project_root = Path(__file__).resolve().parents[1]
    env = os.environ.copy()
    env["PYTHONPATH"] = str(project_root) + os.pathsep + env.get("PYTHONPATH", "")

    subprocess.run(
        [
            sys.executable,
            "benchmarks/longmemeval_answer_benchmark.py",
            "--dataset",
            str(path),
            "--provider",
            "extractive",
            "--engines",
            "wavemind",
            "static",
            "--limit-queries",
            "1",
            "--top-k",
            "2",
            "--output",
            str(output),
        ],
        cwd=project_root,
        env=env,
        text=True,
        encoding="utf-8",
        capture_output=True,
        check=True,
    )

    payload = json.loads(output.read_text(encoding="utf-8"))

    assert payload["scenario"]["name"] == "longmemeval_answer_generation"
    assert payload["metrics"]["provider"] == "extractive"
    assert payload["metrics"]["engine"] == "WaveMind"
    assert payload["metrics"]["queries"] == 1
    assert "abstention_rate" in payload["metrics"]
    assert "grounded_answer_rate" in payload["metrics"]
    assert "unsupported_answer_rate" in payload["metrics"]
    assert [result["engine"] for result in payload["results"]] == ["WaveMind", "Static vector"]
    assert payload["examples"][0]["prediction"]
    assert "Static vector" in payload["examples_by_engine"]

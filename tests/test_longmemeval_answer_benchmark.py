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
    from benchmarks.longmemeval_answer_benchmark import normalize_answer, token_f1

    assert normalize_answer("Business Administration!") == "business administration"
    assert token_f1("Business Administration", "Business Administration") == 1.0
    assert token_f1("Administration", "Business Administration") > 0.0
    assert token_f1("crypto trader", "Business Administration") == 0.0


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
    assert payload["metrics"]["queries"] == 1
    assert payload["examples"][0]["prediction"]

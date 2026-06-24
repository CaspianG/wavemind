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
        },
        {
            "question_id": "q2_abs",
            "question_type": "single-session-user",
            "question": "What is Andrey's dog called?",
            "answer": "No answer.",
            "haystack_session_ids": ["s3"],
            "haystack_dates": ["2026-01-11"],
            "haystack_sessions": [[{"role": "user", "content": "I trade crypto."}]],
            "answer_session_ids": [],
        },
    ]
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_longmemeval_loader_supports_session_and_turn_granularity(tmp_path):
    from benchmarks.longmemeval_memory_benchmark import load_longmemeval_dataset

    path = tmp_path / "longmemeval.json"
    write_longmemeval_fixture(path)

    session_dataset = load_longmemeval_dataset(path, granularity="session")
    turn_dataset = load_longmemeval_dataset(path, granularity="turn")

    assert session_dataset.name == "longmemeval-session"
    assert len(session_dataset.queries) == 1
    assert len(session_dataset.memories) == 2
    assert session_dataset.queries[0].expected_evidence_ids == ("q1::s2",)
    assert turn_dataset.name == "longmemeval-turn"
    assert len(turn_dataset.memories) == 4
    assert turn_dataset.queries[0].expected_evidence_ids == ("q1::s2::turn-0001",)


def test_longmemeval_cli_writes_json(tmp_path):
    path = tmp_path / "longmemeval.json"
    output = tmp_path / "result.json"
    write_longmemeval_fixture(path)
    project_root = Path(__file__).resolve().parents[1]
    env = os.environ.copy()
    env["PYTHONPATH"] = str(project_root) + os.pathsep + env.get("PYTHONPATH", "")

    subprocess.run(
        [
            sys.executable,
            "benchmarks/longmemeval_memory_benchmark.py",
            "--dataset",
            str(path),
            "--engines",
            "wavemind",
            "static",
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

    assert payload["scenario"]["name"] == "longmemeval_evidence_retrieval"
    assert payload["scenario"]["queries"] == 1
    assert payload["scenario"]["granularity"] == "session"
    assert payload["results"][0]["engine"] == "WaveMind"

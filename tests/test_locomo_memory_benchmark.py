import json
import os
import subprocess
import sys
from pathlib import Path


def write_locomo_fixture(path: Path) -> None:
    payload = [
        {
            "sample_id": "sample-1",
            "conversation": {
                "session_1_date_time": "2023-01-01 10:00",
                "session_1": [
                    {
                        "dia_id": "D1:1",
                        "speaker": "speaker_a",
                        "text": "Hi, I am Andrey and I trade crypto breakouts.",
                    },
                    {
                        "dia_id": "D1:2",
                        "speaker": "speaker_b",
                        "text": "I will remember that you are a crypto trader.",
                    },
                ],
                "session_2_date_time": "2023-01-08 10:00",
                "session_2": [
                    {
                        "dia_id": "D2:1",
                        "speaker": "speaker_a",
                        "text": "My monthly tool budget is 2000 dollars.",
                    },
                    {
                        "dia_id": "D2:2",
                        "speaker": "speaker_b",
                        "text": "Budget noted for tools and subscriptions.",
                    },
                ],
                "speaker_a": "Andrey",
                "speaker_b": "Assistant",
            },
            "qa": [
                {
                    "question": "What does Andrey trade?",
                    "answer": "Crypto breakouts.",
                    "category": "single_hop",
                    "evidence": ["D1:1"],
                },
                {
                    "question": "What is Andrey's monthly tool budget?",
                    "answer": "2000 dollars.",
                    "category": "temporal",
                    "evidence": ["D2:1"],
                },
            ],
        }
    ]
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_locomo_loader_turns_evidence_ids_into_memory_dataset(tmp_path):
    from benchmarks.locomo_memory_benchmark import load_locomo_dataset

    locomo_path = tmp_path / "locomo.json"
    write_locomo_fixture(locomo_path)

    dataset = load_locomo_dataset(locomo_path)

    assert dataset.name == "locomo"
    assert len(dataset.memories) == 4
    assert len(dataset.queries) == 2
    assert dataset.memories[0].id == "sample-1::D1:1"
    assert dataset.memories[0].namespace == "locomo:sample-1"
    assert dataset.queries[0].expected_evidence_ids == ("sample-1::D1:1",)
    assert dataset.queries[1].category == "temporal"


def test_locomo_cli_writes_public_benchmark_json(tmp_path):
    locomo_path = tmp_path / "locomo.json"
    output = tmp_path / "locomo-result.json"
    write_locomo_fixture(locomo_path)
    project_root = Path(__file__).resolve().parents[1]
    env = os.environ.copy()
    env["PYTHONPATH"] = str(project_root) + os.pathsep + env.get("PYTHONPATH", "")

    subprocess.run(
        [
            sys.executable,
            "benchmarks/locomo_memory_benchmark.py",
            "--dataset",
            str(locomo_path),
            "--engines",
            "wavemind",
            "static",
            "--top-k",
            "3",
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

    assert payload["scenario"]["name"] == "locomo_evidence_retrieval"
    assert payload["scenario"]["dataset"] == str(locomo_path)
    assert payload["scenario"]["conversations"] == 1
    assert payload["scenario"]["memories"] == 4
    assert payload["scenario"]["queries"] == 2
    assert payload["results"][0]["engine"] == "WaveMind"
    assert "evidence_recall_at_k" in payload["results"][0]

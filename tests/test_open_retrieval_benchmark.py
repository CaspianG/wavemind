import json
import os
import subprocess
import sys
from pathlib import Path

from benchmarks.open_retrieval_benchmark import (
    compute_retrieval_metrics,
    load_beir_dataset,
    run_benchmark,
)


def write_beir_fixture(root: Path) -> Path:
    dataset = root / "mini-beir"
    qrels = dataset / "qrels"
    qrels.mkdir(parents=True)
    (dataset / "corpus.jsonl").write_text(
        "\n".join(
            [
                json.dumps({"_id": "doc-trading", "title": "Trading", "text": "Andrey trades crypto breakouts."}),
                json.dumps({"_id": "doc-budget", "title": "Budget", "text": "The tool budget is 2000 dollars."}),
                json.dumps({"_id": "doc-style", "title": "Style", "text": "The user prefers short practical answers."}),
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    (dataset / "queries.jsonl").write_text(
        "\n".join(
            [
                json.dumps({"_id": "q-trading", "text": "crypto breakout trader"}),
                json.dumps({"_id": "q-budget", "text": "tool budget dollars"}),
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    (qrels / "test.tsv").write_text(
        "query-id\tcorpus-id\tscore\n"
        "q-trading\tdoc-trading\t1\n"
        "q-budget\tdoc-budget\t1\n",
        encoding="utf-8",
    )
    return dataset


def test_load_beir_dataset_and_metrics(tmp_path):
    dataset = load_beir_dataset(write_beir_fixture(tmp_path))

    assert dataset.name == "mini-beir"
    assert len(dataset.documents) == 3
    assert len(dataset.queries) == 2
    assert dataset.qrels["q-trading"] == {"doc-trading": 1.0}

    metrics = compute_retrieval_metrics(
        dataset,
        rankings={
            "q-trading": ["doc-trading", "doc-budget"],
            "q-budget": ["doc-style", "doc-budget"],
        },
        latencies_ms=[1.0, 3.0],
        top_k=2,
        engine="fixture",
    )

    assert metrics.ndcg_at_k > 0.8
    assert metrics.recall_at_k == 1.0
    assert metrics.mrr_at_k == 0.75
    assert metrics.precision_at_1 == 0.5
    assert metrics.avg_latency_ms == 2.0


def test_open_retrieval_wavemind_runner_smoke(tmp_path):
    payload = run_benchmark(
        dataset_dir=write_beir_fixture(tmp_path),
        engines=["wavemind"],
        top_k=2,
    )

    assert payload["scenario"]["name"] == "open_retrieval_beir_format"
    assert payload["scenario"]["documents"] == 3
    assert payload["scenario"]["queries"] == 2
    assert payload["results"][0]["engine"] == "WaveMind"
    assert 0.0 <= payload["results"][0]["ndcg_at_k"] <= 1.0


def test_open_retrieval_cli_writes_json(tmp_path):
    dataset = write_beir_fixture(tmp_path)
    output = tmp_path / "open-retrieval-results.json"
    project_root = Path(__file__).resolve().parents[1]
    env = os.environ.copy()
    env["PYTHONPATH"] = str(project_root) + os.pathsep + env.get("PYTHONPATH", "")

    subprocess.run(
        [
            sys.executable,
            "benchmarks/open_retrieval_benchmark.py",
            "--dataset",
            str(dataset),
            "--engines",
            "wavemind",
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
    assert payload["scenario"]["dataset"] == "mini-beir"
    assert payload["results"][0]["engine"] == "WaveMind"

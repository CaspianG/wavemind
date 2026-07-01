import gzip
import json
import subprocess
import sys
from pathlib import Path


def write_nomiracl_fixture(root: Path) -> None:
    (root / "qrels").mkdir(parents=True)
    (root / "topics").mkdir(parents=True)
    (root / "topics" / "test.relevant.tsv").write_text(
        "q1\tКогда вышел мультфильм Король Лев?\n"
        "q2\tКакое расстояние до Гатчины?\n",
        encoding="utf-8",
    )
    (root / "qrels" / "test.relevant.tsv").write_text(
        "q1 Q0 d1 1\n"
        "q2 Q0 d2 1\n",
        encoding="utf-8",
    )
    with gzip.open(root / "corpus.jsonl.gz", "wt", encoding="utf-8") as handle:
        handle.write(json.dumps({"docid": "d1", "title": "Король Лев", "text": "Мультфильм вышел в 1994 году."}, ensure_ascii=False) + "\n")
        handle.write(json.dumps({"docid": "d2", "title": "Гатчина", "text": "Гатчина находится примерно в 45 километрах от Санкт-Петербурга."}, ensure_ascii=False) + "\n")
        handle.write(json.dumps({"docid": "d3", "title": "Отвлекающий документ", "text": "Этот текст не является релевантным ответом."}, ensure_ascii=False) + "\n")


def test_nomiracl_russian_loader_reads_relevant_subset(tmp_path):
    from benchmarks.nomiracl_russian_benchmark import load_nomiracl_russian_dataset

    write_nomiracl_fixture(tmp_path)
    dataset = load_nomiracl_russian_dataset(tmp_path, split="test")

    assert dataset.name == "nomiracl-russian-test.relevant"
    assert len(dataset.documents) == 3
    assert len(dataset.queries) == 2
    assert dataset.qrels["q1"] == {"d1": 1.0}
    assert "Король Лев" in dataset.documents[0].text

    limited = load_nomiracl_russian_dataset(tmp_path, split="test", limit_queries=1, limit_corpus=2)
    assert len(limited.queries) == 1
    assert len(limited.documents) == 2
    assert "d1" in {document.id for document in limited.documents}


def test_nomiracl_russian_cli_writes_result_json(tmp_path):
    write_nomiracl_fixture(tmp_path / "dataset")
    output = tmp_path / "result.json"
    project_root = Path(__file__).resolve().parents[1]

    subprocess.run(
        [
            sys.executable,
            "benchmarks/nomiracl_russian_benchmark.py",
            "--dataset",
            str(tmp_path / "dataset"),
            "--engines",
            "wavemind",
            "--top-k",
            "1",
            "--output",
            str(output),
        ],
        cwd=project_root,
        text=True,
        encoding="utf-8",
        capture_output=True,
        check=True,
    )

    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["scenario"]["name"] == "nomiracl_russian_relevant_retrieval"
    assert payload["scenario"]["queries"] == 2
    assert payload["results"][0]["engine"] == "WaveMind"

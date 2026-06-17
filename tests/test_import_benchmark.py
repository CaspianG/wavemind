import json

from wavemind import HashingTextEncoder, WaveMind
from wavemind.benchmark import BenchmarkCase, run_benchmark
from wavemind.importers import import_json, import_txt, segment_text


def make_mind(tmp_path):
    return WaveMind(
        db_path=tmp_path / "import.sqlite3",
        width=32,
        height=32,
        layers=2,
        encoder=HashingTextEncoder(vector_dim=64),
        score_threshold=0.05,
    )


def test_segment_text_respects_paragraph_boundaries():
    text = "First paragraph has useful context.\n\nSecond paragraph has another fact."
    chunks = segment_text(text, max_chars=80, overlap=0)

    assert chunks == [
        "First paragraph has useful context.",
        "Second paragraph has another fact.",
    ]


def test_batch_import_txt_and_json(tmp_path):
    mind = make_mind(tmp_path)

    txt_path = tmp_path / "notes.txt"
    txt_path.write_text("кошка любит окно.\n\nсобака любит двор.", encoding="utf-8")
    txt_ids = import_txt(txt_path, mind, namespace="docs", tags=["txt"], max_chars=80)

    json_path = tmp_path / "facts.json"
    json_path.write_text(
        json.dumps([
            {"text": "market breakout above resistance", "tags": ["market"]},
            "agent memory recall improves answers",
        ]),
        encoding="utf-8",
    )
    json_ids = import_json(json_path, mind, namespace="docs", tags=["json"])

    assert len(txt_ids) == 2
    assert len(json_ids) == 2
    assert mind.query("кошка", namespace="docs", tags=["txt"], top_k=1)[0].text == "кошка любит окно."
    assert mind.query("breakout", namespace="docs", tags=["market"], top_k=1)[0].text == "market breakout above resistance"


def test_benchmark_reports_precision_recall_latency_and_capacity(tmp_path):
    mind = make_mind(tmp_path)
    mind.remember("кошка сидит на подоконнике", namespace="bench")
    mind.remember("собака лает во дворе", namespace="bench")

    report = run_benchmark(
        mind,
        [
            BenchmarkCase(query="кошка", expected_text="кошка сидит на подоконнике", namespace="bench"),
            BenchmarkCase(query="собака", expected_text="собака лает во дворе", namespace="bench"),
        ],
        k=1,
    )

    assert report.precision_at_k == 1.0
    assert report.recall_at_k == 1.0
    assert report.capacity == 2
    assert report.avg_latency_ms >= 0.0


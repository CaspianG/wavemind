import json
import os
import subprocess
import sys
from pathlib import Path


def test_synthetic_long_memory_scenario_contains_dynamic_categories():
    from benchmarks.long_memory_evidence_benchmark import build_synthetic_dataset

    dataset = build_synthetic_dataset(memory_count=120)
    categories = {query.category for query in dataset.queries}

    assert len(dataset.memories) == 120
    assert len(dataset.queries) >= 8
    assert {"profile", "personalization", "correction", "ttl", "namespace"}.issubset(categories)
    assert any(memory.ttl_seconds == 0 for memory in dataset.memories)
    assert any(memory.priority > 1.0 for memory in dataset.memories)
    assert any(query.forbidden_evidence_ids for query in dataset.queries)


def test_metrics_reward_expected_evidence_and_stale_suppression():
    from benchmarks.long_memory_evidence_benchmark import EvidenceQuery, compute_evidence_metrics

    queries = [
        EvidenceQuery(
            id="q_current_city",
            text="Where does the user live now?",
            namespace="user-a",
            expected_evidence_ids=("new_city",),
            forbidden_evidence_ids=("old_city",),
            category="correction",
        ),
        EvidenceQuery(
            id="q_expired_token",
            text="Is blue-114 still valid?",
            namespace="user-a",
            expected_evidence_ids=(),
            forbidden_evidence_ids=("expired_token",),
            category="ttl",
        ),
    ]

    metrics = compute_evidence_metrics(
        queries=queries,
        rankings={
            "q_current_city": ["new_city", "old_city"],
            "q_expired_token": ["active_token"],
        },
        returned_texts={
            "q_current_city": ["The user lives in Lisbon.", "The user lived in Berlin."],
            "q_expired_token": ["The valid token is green-772."],
        },
        latencies_ms=[2.0, 4.0],
        full_context_tokens=100,
        top_k=2,
        engine="unit",
    )

    assert metrics.evidence_recall_at_k == 1.0
    assert metrics.precision_at_1 == 1.0
    assert metrics.stale_suppression == 0.5
    # A correction only fully succeeds when stale conflicting evidence is suppressed too.
    assert metrics.category_success["correction"] == 0.0
    assert metrics.category_success["ttl"] == 1.0
    assert metrics.avg_latency_ms == 3.0
    assert metrics.context_tokens_returned > 0
    assert metrics.context_budget_saved > 0.0


def test_long_memory_cli_writes_json_for_wavemind(tmp_path):
    output = tmp_path / "long-memory-result.json"
    project_root = Path(__file__).resolve().parents[1]
    env = os.environ.copy()
    env["PYTHONPATH"] = str(project_root) + os.pathsep + env.get("PYTHONPATH", "")

    subprocess.run(
        [
            sys.executable,
            "benchmarks/long_memory_evidence_benchmark.py",
            "--dataset",
            "synthetic",
            "--engines",
            "wavemind",
            "--memories",
            "80",
            "--top-k",
            "5",
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

    assert payload["scenario"]["name"] == "long_memory_evidence"
    assert payload["scenario"]["dataset"] == "synthetic"
    assert payload["scenario"]["memories"] == 80
    assert payload["results"][0]["engine"] == "WaveMind"
    assert "context_budget_saved" in payload["results"][0]
    assert "category_success" in payload["results"][0]

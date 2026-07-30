from __future__ import annotations

from benchmarks.longmemeval_v2_split_analysis import build_analysis


def _aggregate(*, development: bool) -> dict:
    query_count = 32 if development else 451
    return {
        "source_sha": "a" * 40,
        "scenario": {
            "dataset_repo": "example/dataset",
            "dataset_revision": "dataset-revision",
            "official_repo_revision": "official-revision",
            "queries": query_count,
            "question_selection": "stratified" if development else "full",
            "question_sample_seed": 20260728 if development else None,
            "full_small_run": not development,
            "official_question_haystacks": True,
            "isolated_ab_stores": True,
            "image_questions": 1,
            "image_questions_included": 1,
        },
        "dataset_checksums": {"questions_sha256": "q"},
        "errors": 0,
        "worker_errors": 0,
        "results": [
            {
                "engine": "WaveMind",
                "task_success_rate": 0.20,
                "context_tokens": 1000,
                "end_to_end_p95_ms": 100.0,
                "category_success": {
                    "a": 0.2,
                    "b": 0.2,
                    "c": 0.2,
                    "d": 0.2,
                },
            },
            {
                "engine": "WaveMind + Memory OS",
                "task_success_rate": 0.19,
                "context_tokens": 600,
                "end_to_end_p95_ms": 102.0,
                "category_success": {
                    "a": 0.3,
                    "b": 0.3,
                    "c": 0.3,
                    "d": 0.2,
                },
            },
        ],
    }


def _rows(count: int) -> list[dict]:
    rows = []
    for engine in ("WaveMind", "WaveMind + Memory OS"):
        for index in range(count):
            rows.append(
                {
                    "engine": engine,
                    "question_id": f"q{index:03}",
                    "category": "a" if index % 2 else "b",
                    "passed": engine == "WaveMind" or index % 4 == 0,
                    "error": "",
                }
            )
    return rows


def test_split_analysis_keeps_development_out_of_untouched_rows():
    payload = build_analysis(
        full_payload=_aggregate(development=False),
        full_rows=_rows(451),
        development_payload=_aggregate(development=True),
        development_rows=_rows(32),
        input_checksums={"full_results": "x"},
    )

    assert payload["status"] == "failed_experiment"
    assert payload["development_split"]["questions"] == 32
    assert payload["untouched419"]["questions"] == 419
    assert payload["untouched419"]["rows"] == 838
    assert payload["untouched419"]["development_overlap"] == 0
    assert payload["full451"]["comparison"]["context_saving"] == 0.4
    assert "full_memory_os_uplift" in payload["failed_checks"]
    assert "full_improved_categories" in payload["failed_checks"]
    assert payload["checks"][0]["status"] == "pass"

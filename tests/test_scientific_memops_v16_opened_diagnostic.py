from benchmarks import scientific_memops_v16_opened_diagnostic as diagnostic


def test_v16_opened_diagnostic_is_never_an_official_gate():
    assert diagnostic.runner.DIAGNOSTIC_ONLY is True
    assert diagnostic.runner.ARTIFACT_PHASE == "opened-development-diagnostic"
    assert diagnostic.runner.CLUSTER_GATE_KEY == (
        "minimum_independent_clusters_per_family"
    )
    assert diagnostic.runner.CI_GATE_KEY == (
        "paired_cluster_bootstrap_ci_lower_strictly_greater_than"
    )


def test_causal_application_selection_is_deterministic_and_gold_free():
    entries = [
        {"question_id": "q2", "evaluation_type": "OperationTrace", "gold": 1},
        {"question_id": "q10", "evaluation_type": "StateTrajectory", "gold": 2},
        {
            "question_id": "q8",
            "evaluation_type": "CandidateDisambiguation",
            "gold": 3,
        },
        {"question_id": "q10", "evaluation_type": "OperationApplication", "gold": 4},
    ]
    assert diagnostic.runner._select_entries(entries) == [entries[3]]
    changed_gold = [dict(entry, gold="changed") for entry in entries]
    assert diagnostic.runner._select_entries(changed_gold)[0]["question_id"] == "q10"

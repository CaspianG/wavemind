from __future__ import annotations

from dataclasses import replace

from wavemind import (
    FirewallVerdict,
    default_memory_red_team_cases,
    run_memory_safety_suite,
)


def test_default_memory_safety_suite_covers_structural_attacks_and_hard_admission():
    cases = default_memory_red_team_cases()
    payload = run_memory_safety_suite(cases=cases, source_sha="a" * 40)

    assert len(cases) == 400
    assert payload["summary"]["attack_case_count"] == 375
    assert payload["summary"]["safe_control_count"] == 25
    assert payload["summary"]["attack_failures"] == 0
    assert payload["summary"]["safe_control_failures"] == 0
    assert payload["summary"]["passed"] == 400
    assert payload["summary"]["attack_success_rate"] == 0.0
    assert payload["summary"]["benign_acceptance_rate"] == 1.0
    assert payload["summary"]["cross_namespace_leakage_count"] == 0
    assert payload["summary"]["untrusted_auto_promotions"] == 0
    assert payload["summary"]["rollback_parity"] == 1.0
    assert payload["summary"]["rollback_provenance"] == 1.0
    assert payload["summary"]["provenance_coverage"] == 1.0
    assert payload["admitted"] is True
    assert payload["status"] == "admitted"
    assert set(payload["categories"]) == {
        "delayed_payload",
        "indirect_injection",
        "malicious_correction",
        "multimodal_metadata_attack",
        "namespace_isolation",
        "poisoned_workflow",
        "prompt_injection",
        "protected_delete",
        "safe_control",
        "taint_propagation",
        "trust_escalation",
    }
    assert payload["rollback"]["case_count"] == 25
    assert payload["rollback"]["parity_passed"] == 25
    assert payload["rollback"]["provenance_passed"] == 25


def test_structural_attacks_are_contained_without_keyword_matches():
    payload = run_memory_safety_suite(source_sha="b" * 40)
    structural_categories = {
        "delayed_payload",
        "indirect_injection",
        "multimodal_metadata_attack",
        "poisoned_workflow",
    }
    rows = [
        row
        for row in payload["results"]
        if row["category"] in structural_categories
    ]

    assert len(rows) == 100
    assert all(row["passed"] for row in rows)
    assert all(row["actual_verdict"] == "quarantine" for row in rows)
    assert all("tainted_content" in row["reason_codes"] for row in rows)


def test_memory_safety_admission_fails_if_one_expected_control_is_missed():
    cases = list(default_memory_red_team_cases())
    cases[0] = replace(
        cases[0],
        expected_verdicts=(FirewallVerdict.ALLOW,),
    )

    payload = run_memory_safety_suite(cases=cases)

    assert payload["admitted"] is False
    assert payload["status"] == "blocked"
    assert payload["summary"]["attack_failures"] == 1

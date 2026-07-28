from __future__ import annotations

from dataclasses import replace

from wavemind import (
    FirewallVerdict,
    default_memory_red_team_cases,
    run_memory_safety_suite,
)


def test_default_memory_safety_suite_has_250_attacks_and_hard_admission():
    cases = default_memory_red_team_cases()
    payload = run_memory_safety_suite(cases=cases, source_sha="a" * 40)

    assert len(cases) == 275
    assert payload["summary"]["attack_case_count"] == 250
    assert payload["summary"]["safe_control_count"] == 25
    assert payload["summary"]["attack_failures"] == 0
    assert payload["summary"]["safe_control_failures"] == 0
    assert payload["summary"]["passed"] == 275
    assert payload["admitted"] is True
    assert payload["status"] == "admitted"
    assert set(payload["categories"]) == {
        "namespace_isolation",
        "prompt_injection",
        "protected_delete",
        "safe_control",
        "taint_propagation",
        "trust_escalation",
    }


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

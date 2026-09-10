from __future__ import annotations

import copy

import pytest

from wavemind.codeql_admission import (
    CODEQL_WORKFLOW_CATEGORIES,
    SAFE_PRODUCT_CATEGORIES,
    CodeQLAdmissionError,
    validate_codeql_admission,
    verify_codeql_results,
)


SHA = "5" * 40
REF = "refs/pull/121/merge"
REPOSITORY = "CaspianG/wavemind"


def _analysis(category, identifier, *, sha=SHA, ref=REF, error="", results_count=1):
    return {
        "id": identifier,
        "category": category,
        "commit_sha": sha,
        "ref": ref,
        "error": error,
        "results_count": results_count,
        "rules_count": 100,
    }


def _alert(
    number,
    severity,
    state,
    *,
    category=SAFE_PRODUCT_CATEGORIES[0],
    sha=SHA,
    ref=REF,
    instance_state=None,
    top_state=None,
):
    return {
        "number": number,
        "state": top_state,
        "_query_state": state,
        "rule": {"id": "py/test", "security_severity_level": severity},
        "most_recent_instance": {
            "state": instance_state or state,
            "ref": ref,
            "commit_sha": sha,
            "category": category,
        },
        "dismissed_at": "2026-09-10T20:05:15Z" if state == "dismissed" else None,
        "dismissed_reason": "false positive" if state == "dismissed" else None,
        "fixed_at": "2026-09-10T20:00:00Z" if state == "fixed" else None,
    }


class FakeGitHub:
    def __init__(self, analyses, alerts, *, links=None):
        self.analyses = analyses
        self.alerts = {
            state: [
                [
                    alert
                    for alert in page
                    if (
                        alert.get("_query_state")
                        or (alert.get("most_recent_instance") or {}).get("state")
                        or "open"
                    )
                    == state
                ]
                for page in alerts
            ]
            for state in ("open", "dismissed", "fixed")
        }
        self.links = list(links or [])
        self.urls = []

    def __call__(self, url, *, headers, timeout, max_body):
        self.urls.append(url)
        assert headers["Authorization"].startswith("Bearer ")
        assert 0 < timeout <= 30
        assert max_body <= 2_000_000
        if "analyses" in url:
            return self.analyses, {}
        state = next(
            value for value in ("open", "dismissed", "fixed") if f"state={value}" in url
        )
        pages = self.alerts[state]
        page = pages.pop(0) if pages else []
        headers = (
            {"Link": self.links.pop(0)}
            if state == "open" and self.links and pages
            else {}
        )
        return page, headers


def _verify(alert_pages, *, analyses=None, ref=REF):
    return verify_codeql_results(
        repository=REPOSITORY,
        ref=ref,
        sha=SHA,
        token="synthetic-token-not-for-output",
        fetch_json=FakeGitHub(
            analyses
            or [
                _analysis(SAFE_PRODUCT_CATEGORIES[0], 101),
                _analysis(SAFE_PRODUCT_CATEGORIES[1], 102),
            ],
            alert_pages,
        ),
        deadline_seconds=0,
    )


def test_successful_analyses_with_open_high_alert_are_rejected():
    report = _verify([[_alert(29, "high", "open")]])

    assert report["status"] == "blocked"
    assert report["admitted"] is False
    assert report["alerts"]["open_high"] == 1
    assert validate_codeql_admission(
        report, repository=REPOSITORY, ref=REF, sha=SHA
    ) == ["CodeQL result status is not admitted"]


def test_matching_results_pass_and_narrow_dismissal_is_counted_not_global_skip():
    report = _verify(
        [
            [
                _alert(
                    30,
                    "high",
                    "dismissed",
                    instance_state="open",
                    top_state="dismissed",
                ),
                _alert(31, "medium", "open"),
            ]
        ]
    )

    assert report["status"] == "admitted"
    assert report["alerts"] == {
        "total": 2,
        "open_high": 0,
        "open_critical": 0,
        "open_other": 1,
        "dismissed": 1,
        "fixed": 0,
    }
    assert (
        validate_codeql_admission(report, repository=REPOSITORY, ref=REF, sha=SHA) == []
    )


def test_other_workflow_results_for_ref_are_included():
    report = _verify(
        [[_alert(40, "low", "open", category=CODEQL_WORKFLOW_CATEGORIES[0])]]
    )

    assert report["alerts"]["open_other"] == 1
    assert report["alerts"]["total"] == 1


@pytest.mark.parametrize(
    "analyses",
    [
        [_analysis(SAFE_PRODUCT_CATEGORIES[0], 101)],
        [
            _analysis(SAFE_PRODUCT_CATEGORIES[0], 101, sha="4" * 40),
            _analysis(SAFE_PRODUCT_CATEGORIES[1], 102),
        ],
        [
            _analysis(SAFE_PRODUCT_CATEGORIES[0], 101, ref="refs/heads/main"),
            _analysis(SAFE_PRODUCT_CATEGORIES[1], 102),
        ],
        [
            _analysis(SAFE_PRODUCT_CATEGORIES[0], 101, error="failed extraction"),
            _analysis(SAFE_PRODUCT_CATEGORIES[1], 102),
        ],
    ],
)
def test_missing_stale_wrong_ref_and_error_analyses_fail_closed(analyses):
    with pytest.raises(CodeQLAdmissionError):
        _verify([[]], analyses=analyses)


def test_malformed_or_unknown_alert_state_and_severity_fail_closed():
    for alert in (
        {"number": 1},
        _alert(1, "future-severity", "open"),
        _alert(1, "recommendation", "open"),
        _alert(1, "high", "future-state"),
        _alert(1, "high", "open", sha="4" * 40),
    ):
        with pytest.raises(CodeQLAdmissionError):
            _verify([[alert]])


def test_alert_pagination_is_complete_and_bound_to_api_origin():
    github = FakeGitHub(
        [
            _analysis(SAFE_PRODUCT_CATEGORIES[0], 101),
            _analysis(SAFE_PRODUCT_CATEGORIES[1], 102),
        ],
        [[_alert(31, "low", "open")], [_alert(32, "medium", "open")]],
        links=[
            '<https://api.github.com/repos/CaspianG/wavemind/code-scanning/alerts?ref=refs%2Fpull%2F121%2Fmerge&state=open&per_page=100&page=2>; rel="next"'
        ],
    )

    report = verify_codeql_results(
        repository=REPOSITORY,
        ref=REF,
        sha=SHA,
        token="synthetic-token-not-for-output",
        fetch_json=github,
        deadline_seconds=0,
    )

    assert report["alerts"]["total"] == 2
    assert len(github.urls) == 5

    hostile = copy.deepcopy(github)
    hostile.alerts = {"open": [[]], "dismissed": [[]], "fixed": [[]]}
    hostile.links = ['<https://example.com/steal>; rel="next"']
    hostile.urls = []
    with pytest.raises(CodeQLAdmissionError):
        verify_codeql_results(
            repository=REPOSITORY,
            ref=REF,
            sha=SHA,
            token="synthetic-token-not-for-output",
            fetch_json=hostile,
            deadline_seconds=0,
        )


def test_timeout_and_rate_limit_fail_closed_without_secret_in_error():
    for failure in (
        TimeoutError("synthetic-token-not-for-output"),
        CodeQLAdmissionError("rate_limit"),
    ):

        def fail(*_args, **_kwargs):
            raise failure

        with pytest.raises(CodeQLAdmissionError) as error:
            verify_codeql_results(
                repository=REPOSITORY,
                ref=REF,
                sha=SHA,
                token="synthetic-token-not-for-output",
                fetch_json=fail,
                deadline_seconds=0,
            )
        assert "synthetic-token-not-for-output" not in str(error.value)


def test_release_tag_ref_is_supported():
    tag_ref = "refs/tags/v2.14.0"
    analyses = [
        _analysis(SAFE_PRODUCT_CATEGORIES[0], 1731978584, ref=tag_ref, results_count=0),
        _analysis(SAFE_PRODUCT_CATEGORIES[1], 1731977448, ref=tag_ref, results_count=0),
    ]

    report = _verify([[]], analyses=analyses, ref=tag_ref)

    assert report["status"] == "admitted"
    assert report["source"]["ref"] == tag_ref


def test_historical_analyses_on_same_ref_are_ignored_for_exact_sha():
    analyses = [
        _analysis(SAFE_PRODUCT_CATEGORIES[0], 99, sha="4" * 40),
        _analysis(SAFE_PRODUCT_CATEGORIES[0], 101),
        _analysis(SAFE_PRODUCT_CATEGORIES[1], 102),
    ]

    report = _verify([[_alert(29, "low", "open")]], analyses=analyses)

    assert {item["id"] for item in report["analyzed_configurations"]} == {101, 102}


def test_nonzero_analysis_with_silent_empty_alert_pages_fails_closed():
    with pytest.raises(CodeQLAdmissionError, match="missing_alert_results"):
        _verify([[]])

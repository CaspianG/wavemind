from __future__ import annotations

import copy
import io
import json
import urllib.request
from http.client import HTTPMessage

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
MAIN_SHA = "00192c3faed463e08e90a3e898fc84378b43a028"
MAIN_REF = "refs/heads/main"


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
    def __init__(self, analyses, alerts, *, links=None, link_header="Link"):
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
        self.link_header = link_header
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
            {self.link_header: self.links.pop(0)}
            if state == "open" and self.links
            else {}
        )
        return page, headers


def _verify(alert_pages, *, analyses=None, ref=REF, deadline_seconds=1):
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
        deadline_seconds=deadline_seconds,
        retry_seconds=0.001,
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
        "historical_fixed": 0,
    }
    assert (
        validate_codeql_admission(report, repository=REPOSITORY, ref=REF, sha=SHA) == []
    )


def test_other_workflow_results_for_ref_are_included():
    report = _verify(
        [[_alert(40, "low", "open", category=CODEQL_WORKFLOW_CATEGORIES[0])]],
        analyses=[
            _analysis(SAFE_PRODUCT_CATEGORIES[0], 101),
            _analysis(SAFE_PRODUCT_CATEGORIES[1], 102),
            _analysis(CODEQL_WORKFLOW_CATEGORIES[0], 103),
        ],
    )

    assert report["alerts"]["open_other"] == 1
    assert report["alerts"]["total"] == 1


def test_actual_standalone_categories_and_current_high_finding_are_included():
    assert CODEQL_WORKFLOW_CATEGORIES == (
        "/language:python",
        "/language:javascript-typescript",
    )
    analyses = [
        _analysis(
            "/language:python",
            1747684683,
            sha=MAIN_SHA,
            ref=MAIN_REF,
            results_count=4,
        ),
        _analysis(
            SAFE_PRODUCT_CATEGORIES[0],
            1747684203,
            sha=MAIN_SHA,
            ref=MAIN_REF,
            results_count=4,
        ),
        _analysis(
            SAFE_PRODUCT_CATEGORIES[1],
            1747683240,
            sha=MAIN_SHA,
            ref=MAIN_REF,
            results_count=0,
        ),
        _analysis(
            "/language:javascript-typescript",
            1747678341,
            sha=MAIN_SHA,
            ref=MAIN_REF,
            results_count=0,
        ),
    ]
    github = FakeGitHub(
        analyses,
        [
            [
                _alert(
                    29,
                    "high",
                    "open",
                    category="/language:python",
                    sha=MAIN_SHA,
                    ref=MAIN_REF,
                )
            ]
        ],
    )

    report = verify_codeql_results(
        repository=REPOSITORY,
        ref=MAIN_REF,
        sha=MAIN_SHA,
        token="synthetic-token-not-for-output",
        fetch_json=github,
        deadline_seconds=1,
        retry_seconds=0.001,
    )

    assert report["status"] == "blocked"
    assert report["alerts"]["open_high"] == 1
    assert {item["category"] for item in report["analyzed_configurations"]} == {
        *SAFE_PRODUCT_CATEGORIES,
        *CODEQL_WORKFLOW_CATEGORIES,
    }


def test_real_shaped_historical_fixed_findings_are_labeled_and_counted():
    historical_sha = "e71f1b3304b2101badcdcead5cbe90134441f098"
    analyses = [
        _analysis(
            SAFE_PRODUCT_CATEGORIES[0],
            1747684203,
            sha=MAIN_SHA,
            ref=MAIN_REF,
            results_count=1,
        ),
        _analysis(
            SAFE_PRODUCT_CATEGORIES[1],
            1747683240,
            sha=MAIN_SHA,
            ref=MAIN_REF,
            results_count=0,
        ),
    ]
    fixed = _alert(
        22,
        "high",
        "fixed",
        sha=historical_sha,
        ref=MAIN_REF,
        top_state="fixed",
    )
    standalone_fixed = _alert(
        12,
        "high",
        "fixed",
        category="/language:python",
        sha="c30205ed389057bc695488655a3f8650ba8e5277",
        ref=MAIN_REF,
    )
    current = _alert(
        23,
        "low",
        "dismissed",
        sha=MAIN_SHA,
        ref=MAIN_REF,
        instance_state="dismissed",
        top_state="dismissed",
    )
    github = FakeGitHub(analyses, [[fixed, standalone_fixed, current]])

    report = verify_codeql_results(
        repository=REPOSITORY,
        ref=MAIN_REF,
        sha=MAIN_SHA,
        token="synthetic-token-not-for-output",
        fetch_json=github,
        deadline_seconds=1,
        retry_seconds=0.001,
    )

    assert report["alerts"]["historical_fixed"] == 2
    assert "fixed" not in report["alerts"]
    assert report["alerts"]["dismissed"] == 1


@pytest.mark.parametrize(
    "fixed",
    [
        _alert(22, "high", "fixed", sha="not-a-sha", ref=MAIN_REF, top_state="fixed"),
        _alert(22, "high", "fixed", sha="4" * 40, ref=REF, top_state="fixed"),
        _alert(
            22,
            "high",
            "fixed",
            sha="4" * 40,
            ref=MAIN_REF,
            instance_state="open",
            top_state="fixed",
        ),
        _alert(22, "high", "fixed", sha="4" * 40, ref=MAIN_REF, top_state="open"),
        _alert(
            22,
            "high",
            "fixed",
            sha="4" * 40,
            ref=MAIN_REF,
            category="unknown/category",
            top_state="fixed",
        ),
    ],
)
def test_malformed_or_contradictory_historical_fixed_findings_fail(fixed):
    analyses = [
        _analysis(SAFE_PRODUCT_CATEGORIES[0], 101, sha=MAIN_SHA, ref=MAIN_REF),
        _analysis(SAFE_PRODUCT_CATEGORIES[1], 102, sha=MAIN_SHA, ref=MAIN_REF),
    ]
    github = FakeGitHub(analyses, [[fixed]])

    with pytest.raises(CodeQLAdmissionError):
        verify_codeql_results(
            repository=REPOSITORY,
            ref=MAIN_REF,
            sha=MAIN_SHA,
            token="synthetic-token-not-for-output",
            fetch_json=github,
            deadline_seconds=0.01,
            retry_seconds=0.001,
        )


def test_historical_fixed_alone_cannot_mask_missing_current_results():
    analyses = [
        _analysis(SAFE_PRODUCT_CATEGORIES[0], 101, sha=MAIN_SHA, ref=MAIN_REF),
        _analysis(SAFE_PRODUCT_CATEGORIES[1], 102, sha=MAIN_SHA, ref=MAIN_REF),
    ]
    fixed = _alert(
        22,
        "high",
        "fixed",
        sha="e71f1b3304b2101badcdcead5cbe90134441f098",
        ref=MAIN_REF,
        top_state="fixed",
    )
    github = FakeGitHub(analyses, [[fixed]])

    with pytest.raises(CodeQLAdmissionError, match="missing_alert_results"):
        verify_codeql_results(
            repository=REPOSITORY,
            ref=MAIN_REF,
            sha=MAIN_SHA,
            token="synthetic-token-not-for-output",
            fetch_json=github,
            deadline_seconds=0.01,
            retry_seconds=0.001,
        )


def test_current_finding_requires_its_category_to_have_a_current_analysis():
    analyses = [
        _analysis(SAFE_PRODUCT_CATEGORIES[0], 101, sha=MAIN_SHA, ref=MAIN_REF),
        _analysis(SAFE_PRODUCT_CATEGORIES[1], 102, sha=MAIN_SHA, ref=MAIN_REF),
    ]
    standalone = _alert(
        29,
        "high",
        "open",
        category="/language:python",
        sha=MAIN_SHA,
        ref=MAIN_REF,
    )

    with pytest.raises(CodeQLAdmissionError, match="malformed_alert"):
        verify_codeql_results(
            repository=REPOSITORY,
            ref=MAIN_REF,
            sha=MAIN_SHA,
            token="synthetic-token-not-for-output",
            fetch_json=FakeGitHub(analyses, [[standalone]]),
            deadline_seconds=1,
            retry_seconds=0.001,
        )


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
        deadline_seconds=1,
    )

    assert report["alerts"]["total"] == 2
    assert len(github.urls) == 5

    hostile = copy.deepcopy(github)
    hostile.alerts = {"open": [[]], "dismissed": [[]], "fixed": [[]]}
    hostile.links = ['<https://example.com/steal>; rel="next"']
    hostile.urls = []
    with pytest.raises(CodeQLAdmissionError, match="invalid_pagination"):
        verify_codeql_results(
            repository=REPOSITORY,
            ref=REF,
            sha=SHA,
            token="synthetic-token-not-for-output",
            fetch_json=hostile,
            deadline_seconds=1,
        )


def test_lowercase_link_cannot_hide_later_high_alert():
    github = FakeGitHub(
        [
            _analysis(SAFE_PRODUCT_CATEGORIES[0], 101),
            _analysis(SAFE_PRODUCT_CATEGORIES[1], 102),
        ],
        [[_alert(31, "low", "open")], [_alert(32, "high", "open")]],
        links=[
            '<https://api.github.com/repos/CaspianG/wavemind/code-scanning/alerts?ref=refs%2Fpull%2F121%2Fmerge&state=open&per_page=100&page=2>; rel="next"'
        ],
        link_header="link",
    )

    report = verify_codeql_results(
        repository=REPOSITORY,
        ref=REF,
        sha=SHA,
        token="synthetic-token-not-for-output",
        fetch_json=github,
        deadline_seconds=1,
    )

    assert report["status"] == "blocked"
    assert report["alerts"]["open_high"] == 1


def test_terminal_prev_and_first_links_terminate_without_error():
    terminal = (
        "<https://api.github.com/repos/CaspianG/wavemind/code-scanning/"
        "alerts?ref=refs%2Fpull%2F121%2Fmerge&state=open&per_page=100&page=1>; "
        'rel="first", <https://api.github.com/repos/CaspianG/wavemind/code-scanning/'
        "alerts?ref=refs%2Fpull%2F121%2Fmerge&state=open&per_page=100&page=1>; "
        'rel="prev"'
    )
    github = FakeGitHub(
        [
            _analysis(SAFE_PRODUCT_CATEGORIES[0], 101),
            _analysis(SAFE_PRODUCT_CATEGORIES[1], 102),
        ],
        [[_alert(31, "low", "open")]],
        links=[terminal],
    )

    report = verify_codeql_results(
        repository=REPOSITORY,
        ref=REF,
        sha=SHA,
        token="synthetic-token-not-for-output",
        fetch_json=github,
        deadline_seconds=1,
    )

    assert report["status"] == "admitted"
    assert report["alerts"]["total"] == 1


@pytest.mark.parametrize(
    "link",
    [
        "not-a-link-header",
        '<https://api.github.com/repos/CaspianG/wavemind/code-scanning/alerts?page=2>; rel="next", '
        '<https://api.github.com/repos/CaspianG/wavemind/code-scanning/alerts?page=3>; rel="next"',
    ],
)
def test_malformed_and_duplicate_next_relations_fail_closed(link):
    from wavemind.codeql_admission import _next_page

    with pytest.raises(CodeQLAdmissionError, match="invalid_pagination"):
        _next_page(
            link,
            REPOSITORY,
            "https://api.github.com/repos/CaspianG/wavemind/code-scanning/alerts"
            "?ref=refs%2Fpull%2F121%2Fmerge&state=open&per_page=100",
        )


def test_production_transport_rejects_redirect_before_forwarding_authorization(
    monkeypatch,
):
    forwarded = []

    class Response(io.BytesIO):
        headers = {}

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

    def unsafe_urlopen(request, *, timeout):
        redirected = urllib.request.Request(
            "https://example.com/steal",
            headers=dict(request.header_items()),
            method="GET",
        )
        forwarded.append(redirected.get_header("Authorization"))
        return Response(b"[]")

    class SyntheticOpener:
        def __init__(self, handler):
            self.handler = handler

        def open(self, request, *, timeout):
            self.handler.redirect_request(
                request,
                None,
                302,
                "redirect",
                {},
                "https://example.com/steal",
            )
            raise AssertionError("redirect policy unexpectedly returned")

    monkeypatch.setattr(urllib.request, "urlopen", unsafe_urlopen)
    monkeypatch.setattr(
        urllib.request,
        "build_opener",
        lambda handler: SyntheticOpener(handler),
    )

    with pytest.raises(CodeQLAdmissionError, match="api_failure"):
        from wavemind.codeql_admission import fetch_github_json

        fetch_github_json(
            "https://api.github.com/repos/CaspianG/wavemind/code-scanning/alerts",
            headers={"Authorization": "Bearer synthetic-token-not-for-output"},
            timeout=1,
            max_body=1024,
        )
    assert forwarded == []


def test_production_httpmessage_headers_reach_admission_and_preserve_pagination(
    monkeypatch,
):
    analyses = [
        _analysis(SAFE_PRODUCT_CATEGORIES[0], 101, results_count=0),
        _analysis(SAFE_PRODUCT_CATEGORIES[1], 102, results_count=0),
    ]
    next_url = (
        "https://api.github.com/repos/CaspianG/wavemind/code-scanning/alerts"
        "?ref=refs%2Fpull%2F121%2Fmerge&state=open&per_page=100&page=2"
    )
    bodies_and_headers = [
        (analyses, []),
        ([_alert(31, "low", "open")], [("link", f'<{next_url}>; rel="next"')]),
        ([_alert(32, "high", "open")], []),
        ([], []),
        ([], []),
    ]

    class Response(io.BytesIO):
        def __init__(self, payload, fields):
            body = json.dumps(payload).encode("utf-8")
            super().__init__(body)
            self.headers = HTTPMessage()
            self.headers.add_header("Content-Length", str(len(body)))
            for name, value in fields:
                self.headers.add_header(name, value)

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

    class InMemoryOpener:
        def __init__(self):
            self.urls = []

        def open(self, request, *, timeout):
            self.urls.append(request.full_url)
            payload, fields = bodies_and_headers.pop(0)
            return Response(payload, fields)

    opener = InMemoryOpener()
    monkeypatch.setattr(urllib.request, "build_opener", lambda _handler: opener)

    report = verify_codeql_results(
        repository=REPOSITORY,
        ref=REF,
        sha=SHA,
        token="synthetic-token-not-for-output",
        deadline_seconds=1,
    )

    assert report["status"] == "blocked"
    assert report["alerts"]["open_high"] == 1
    assert len(opener.urls) == 5
    assert bodies_and_headers == []

    bodies_and_headers.append(
        (
            analyses,
            [
                ("Link", f'<{next_url}>; rel="next"'),
                ("link", f'<{next_url}>; rel="next"'),
            ],
        )
    )
    with pytest.raises(CodeQLAdmissionError, match="invalid_pagination"):
        verify_codeql_results(
            repository=REPOSITORY,
            ref=REF,
            sha=SHA,
            token="synthetic-token-not-for-output",
            deadline_seconds=1,
        )
    assert bodies_and_headers == []


def test_one_deadline_caps_each_request_and_rejects_successful_late_responses(
    monkeypatch,
):
    from wavemind import codeql_admission

    now = [10.0]
    timeouts = []

    def clock():
        return now[0]

    def late_fetch(url, *, headers, timeout, max_body):
        timeouts.append(timeout)
        now[0] += 0.06
        if "analyses" in url:
            return [
                _analysis(SAFE_PRODUCT_CATEGORIES[0], 101, results_count=0),
                _analysis(SAFE_PRODUCT_CATEGORIES[1], 102, results_count=0),
            ], {}
        return [], {}

    monkeypatch.setattr(codeql_admission.time, "monotonic", clock)

    with pytest.raises(CodeQLAdmissionError, match="deadline_exceeded"):
        verify_codeql_results(
            repository=REPOSITORY,
            ref=REF,
            sha=SHA,
            token="synthetic-token-not-for-output",
            fetch_json=late_fetch,
            deadline_seconds=0.1,
            retry_seconds=0.01,
        )
    assert timeouts
    assert all(0 < timeout <= 0.1 for timeout in timeouts)


def test_shared_deadline_decreases_across_pages_and_stops_after_late_page(
    monkeypatch,
):
    from wavemind import codeql_admission

    now = [20.0]
    calls = []
    next_url = (
        "https://api.github.com/repos/CaspianG/wavemind/code-scanning/analyses"
        "?ref=refs%2Fpull%2F121%2Fmerge&per_page=100&page=2"
    )

    def clock():
        return now[0]

    def paged_fetch(url, *, headers, timeout, max_body):
        calls.append((url, timeout))
        if len(calls) == 1:
            now[0] += 0.03
            return [_analysis(SAFE_PRODUCT_CATEGORIES[0], 101)], {
                "Link": f'<{next_url}>; rel="next"'
            }
        now[0] += 0.08
        return [_analysis(SAFE_PRODUCT_CATEGORIES[1], 102)], {}

    monkeypatch.setattr(codeql_admission.time, "monotonic", clock)

    with pytest.raises(CodeQLAdmissionError, match="deadline_exceeded"):
        verify_codeql_results(
            repository=REPOSITORY,
            ref=REF,
            sha=SHA,
            token="synthetic-token-not-for-output",
            fetch_json=paged_fetch,
            deadline_seconds=0.1,
            retry_seconds=0.01,
        )

    assert len(calls) == 2
    assert calls[1][1] < calls[0][1]
    assert calls[0][1] == pytest.approx(0.1)


def test_shared_deadline_decreases_across_retry_and_stops_after_late_result(
    monkeypatch,
):
    from wavemind import codeql_admission

    now = [30.0]
    calls = []

    def clock():
        return now[0]

    def advance_sleep(seconds):
        now[0] += seconds

    def retrying_fetch(url, *, headers, timeout, max_body):
        calls.append((url, timeout))
        if len(calls) == 1:
            now[0] += 0.03
            return [], {}
        now[0] += 0.04
        return [
            _analysis(SAFE_PRODUCT_CATEGORIES[0], 101, results_count=0),
            _analysis(SAFE_PRODUCT_CATEGORIES[1], 102, results_count=0),
        ], {}

    monkeypatch.setattr(codeql_admission.time, "monotonic", clock)
    monkeypatch.setattr(codeql_admission.time, "sleep", advance_sleep)

    with pytest.raises(CodeQLAdmissionError, match="deadline_exceeded"):
        verify_codeql_results(
            repository=REPOSITORY,
            ref=REF,
            sha=SHA,
            token="synthetic-token-not-for-output",
            fetch_json=retrying_fetch,
            deadline_seconds=0.1,
            retry_seconds=0.04,
        )

    assert len(calls) == 2
    assert calls[1][1] < calls[0][1]
    assert calls[0][1] == pytest.approx(0.1)


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
                deadline_seconds=1,
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
        _verify([[]], deadline_seconds=0.01)


def _offline_http_pages(monkeypatch, pages):
    """Replace only network I/O; retain JSON decoding and real urllib headers."""
    urls = []

    class Response(io.BytesIO):
        def __init__(self, payload, link):
            body = json.dumps(payload).encode("utf-8")
            super().__init__(body)
            self.headers = HTTPMessage()
            self.headers.add_header("Content-Length", str(len(body)))
            if link is not None:
                self.headers.add_header("Link", link)

    class Opener:
        def open(self, request, *, timeout):
            urls.append(request.full_url)
            return Response(*pages.pop(0))

    monkeypatch.setattr(urllib.request, "build_opener", lambda _handler: Opener())
    return urls


@pytest.mark.parametrize("repository_id", ["1272624457", "987654321"])
def test_observed_numeric_main_links_reconstruct_pinned_requests(
    monkeypatch, repository_id
):
    # Rejecting GitHub's numeric path breaks admission; following it changes authority.
    numeric = f"https://api.github.com/repositories/{repository_id}/code-scanning/"
    named = "https://api.github.com/repos/CaspianG/wavemind/code-scanning/"
    query = "ref=refs%2Fheads%2Fmain&per_page=100"
    current_sha = "f8e0a167fe85b88c7a6c8f3a144294344507bc4a"
    analyses = [
        _analysis(category, 201 + index, sha=current_sha, ref=MAIN_REF)
        for index, category in enumerate(
            (*SAFE_PRODUCT_CATEGORIES, *CODEQL_WORKFLOW_CATEGORIES)
        )
    ]
    analysis_next = f"{numeric}analyses?{query}&page=2"
    pages = [
        (analyses[:2], f'<{analysis_next}>; rel="next", <{analysis_next}>; rel="last"'),
        (
            analyses[2:],
            f'<{numeric}analyses?{query}&page=1>; rel="prev", '
            f'<{numeric}analyses?{query}&page=1>; rel="first"',
        ),
        ([], None),
        (
            [
                _alert(
                    30,
                    "high",
                    "dismissed",
                    sha=current_sha,
                    ref=MAIN_REF,
                    top_state="dismissed",
                    instance_state="open",
                )
            ],
            f'<{numeric}alerts?ref=refs%2Fheads%2Fmain&state=dismissed&per_page=100&page=2>; rel="next"',
        ),
        ([], None),
        (
            [
                _alert(
                    29, "high", "fixed", sha="4" * 40, ref=MAIN_REF, top_state="fixed"
                )
            ],
            f'<{numeric}alerts?ref=refs%2Fheads%2Fmain&state=fixed&per_page=100&page=2>; rel="next"',
        ),
        (
            [
                _alert(
                    31,
                    "high",
                    "fixed",
                    sha="3" * 40,
                    ref=MAIN_REF,
                    category="/language:python",
                    top_state="fixed",
                )
            ],
            f'<{numeric}alerts?ref=refs%2Fheads%2Fmain&state=fixed&per_page=100&page=1>; rel="prev"',
        ),
    ]
    urls = _offline_http_pages(monkeypatch, pages)

    report = verify_codeql_results(
        repository=REPOSITORY,
        ref=MAIN_REF,
        sha=current_sha,
        token="synthetic-token-not-for-output",
        deadline_seconds=1,
    )

    assert report["status"] == "admitted"
    assert report["alerts"] == {
        "total": 3,
        "open_high": 0,
        "open_critical": 0,
        "open_other": 0,
        "dismissed": 1,
        "historical_fixed": 2,
    }
    assert {item["id"] for item in report["analyzed_configurations"]} == {
        201,
        202,
        203,
        204,
    }
    assert (
        validate_codeql_admission(
            report, repository=REPOSITORY, ref=MAIN_REF, sha=current_sha
        )
        == []
    )
    assert urls == [
        f"{named}analyses?{query}",
        f"{named}analyses?{query}&page=2",
        f"{named}alerts?ref=refs%2Fheads%2Fmain&state=open&per_page=100",
        f"{named}alerts?ref=refs%2Fheads%2Fmain&state=dismissed&per_page=100",
        f"{named}alerts?ref=refs%2Fheads%2Fmain&state=dismissed&per_page=100&page=2",
        f"{named}alerts?ref=refs%2Fheads%2Fmain&state=fixed&per_page=100",
        f"{named}alerts?ref=refs%2Fheads%2Fmain&state=fixed&per_page=100&page=2",
    ]
    assert pages == []


def test_numeric_alert_pagination_cannot_hide_later_high_finding(monkeypatch):
    pages = [
        (
            [
                _analysis(category, index + 1)
                for index, category in enumerate(
                    (*SAFE_PRODUCT_CATEGORIES, *CODEQL_WORKFLOW_CATEGORIES)
                )
            ],
            None,
        ),
        (
            [_alert(31, "low", "open")],
            "<https://api.github.com/repositories/1272624457/code-scanning/alerts"
            '?ref=refs%2Fpull%2F121%2Fmerge&state=open&per_page=100&page=2>; rel="next"',
        ),
        ([_alert(32, "high", "open", category="/language:python")], None),
        ([], None),
        ([], None),
    ]
    urls = _offline_http_pages(monkeypatch, pages)

    report = verify_codeql_results(
        repository=REPOSITORY,
        ref=REF,
        sha=SHA,
        token="synthetic-token-not-for-output",
        deadline_seconds=1,
    )

    assert report["status"] == "blocked"
    assert report["alerts"]["open_high"] == 1
    assert report["alerts"]["total"] == 2
    assert urls[2] == (
        "https://api.github.com/repos/CaspianG/wavemind/code-scanning/alerts"
        "?ref=refs%2Fpull%2F121%2Fmerge&state=open&per_page=100&page=2"
    )
    assert pages == []


@pytest.mark.parametrize(
    "path",
    [
        "/repos/CaspianG/wavemind/code-scanning/alerts",
        "/repositories/1272624457/code-scanning/alerts",
    ],
)
@pytest.mark.parametrize(
    "query",
    [
        "ref=refs%2Fheads%2Fmain&state=open&per_page=100&page=2",
        "ref=refs%2Fpull%2F121%2Fmerge&state=fixed&per_page=100&page=2",
        "ref=refs%2Fpull%2F121%2Fmerge&state=open&per_page=10&page=2",
        "ref=refs%2Fpull%2F121%2Fmerge&state=open&per_page=100&page=2&extra=1",
        "ref=refs%2Fpull%2F121%2Fmerge&state=open&per_page=100&page=2&page=3",
        "ref=refs%2Fpull%2F121%2Fmerge&state=open&state=open&per_page=100&page=2",
        "ref=refs%2Fpull%2F121%2Fmerge&state=open&per_page=100&page=2&%70age=2",
        "ref=refs%2Fpull%2F121%2Fmerge&state=open&per_page=100&page=0",
        "ref=refs%2Fpull%2F121%2Fmerge&state=open&per_page=100&page=-1",
        "ref=refs%2Fpull%2F121%2Fmerge&state=open&per_page=100&page=01",
        "ref=refs%2Fpull%2F121%2Fmerge&state=open&per_page=100&page=1",
        "ref=refs%2Fpull%2F121%2Fmerge&state=open&per_page=100&page=3",
        "ref=refs%2Fpull%2F121%2Fmerge&state=open&per_page=100&page=101",
        "ref=refs%2Fpull%2F121%2Fmerge&state=open&per_page=100&page=2.0",
        "ref=refs%2Fpull%2F121%2Fmerge&state=open&per_page=100&page=",
        "ref=refs%2Fpull%2F121%2Fmerge&state=open&per_page=100",
        "page=2",
    ],
)
def test_pagination_rejects_changed_or_ambiguous_query_before_fetch(
    monkeypatch, path, query
):
    _assert_hostile_pagination(monkeypatch, f"https://api.github.com{path}?{query}")


@pytest.mark.parametrize(
    "target",
    [
        "http://api.github.com/repositories/1272624457/code-scanning/alerts",
        "https://evil.example/repositories/1272624457/code-scanning/alerts",
        "https://api.github.com:443/repositories/1272624457/code-scanning/alerts",
        "https://user@api.github.com/repositories/1272624457/code-scanning/alerts",
        "https://api.github.com/repos/other/repo/code-scanning/alerts",
        "https://api.github.com/repos/CaspianG/wavemind/code-scanning/analyses",
        "https://api.github.com/repositories/1272624457/code-scanning/analyses",
        "https://api.github.com/repos/CaspianG/wavemind/code-scanning/alerts/../analyses",
        "https://api.github.com/repos/CaspianG/wavemind/code-scanning/alerts/extra",
        "https://api.github.com/repositories/1272624457/code-scanning/%61lerts",
        "https://api.github.com/repositories/0/code-scanning/alerts",
        "https://api.github.com/repositories/0123/code-scanning/alerts",
        "https://api.github.com/repositories/-1/code-scanning/alerts",
        "https://api.github.com/repositories/123.0/code-scanning/alerts",
        "https://api.github.com/repositories/123/code-scanning//alerts",
        "https://api.github.com/repositories/123/code-scanning/alerts/",
    ],
)
def test_pagination_rejects_endpoint_or_origin_confusion_before_fetch(
    monkeypatch, target
):
    _assert_hostile_pagination(
        monkeypatch,
        f"{target}?ref=refs%2Fpull%2F121%2Fmerge&state=open&per_page=100&page=2",
    )


def _assert_hostile_pagination(monkeypatch, target):
    pages = [
        (
            [
                _analysis(SAFE_PRODUCT_CATEGORIES[0], 1, results_count=0),
                _analysis(SAFE_PRODUCT_CATEGORIES[1], 2, results_count=0),
            ],
            None,
        ),
        ([], f'<{target}>; rel="next"'),
        ([], None),
        ([], None),
        ([], None),
    ]
    urls = _offline_http_pages(monkeypatch, pages)
    with pytest.raises(CodeQLAdmissionError, match="invalid_pagination"):
        verify_codeql_results(
            repository=REPOSITORY,
            ref=REF,
            sha=SHA,
            token="synthetic-token-not-for-output",
            deadline_seconds=1,
        )
    assert len(urls) == 2


@pytest.mark.parametrize("suffix", ["#fragment", "#", "\n", "\t"])
def test_pagination_rejects_fragment_and_control_characters(monkeypatch, suffix):
    _assert_hostile_pagination(
        monkeypatch,
        "https://api.github.com/repos/CaspianG/wavemind/code-scanning/alerts"
        "?ref=refs%2Fpull%2F121%2Fmerge&state=open&per_page=100&page=2" + suffix,
    )


def test_numeric_pagination_loop_is_rejected_before_repeated_fetch(monkeypatch):
    link = (
        "<https://api.github.com/repositories/1272624457/code-scanning/analyses"
        '?ref=refs%2Fpull%2F121%2Fmerge&per_page=100&page=2>; rel="next"'
    )
    pages = [([], link), ([], link)]
    urls = _offline_http_pages(monkeypatch, pages)
    with pytest.raises(CodeQLAdmissionError, match="invalid_pagination"):
        verify_codeql_results(
            repository=REPOSITORY,
            ref=REF,
            sha=SHA,
            token="synthetic-token-not-for-output",
            deadline_seconds=1,
        )
    assert len(urls) == 2


def test_numeric_pagination_is_bounded_to_100_pages(monkeypatch):
    pages = [
        (
            [],
            (
                "<https://api.github.com/repositories/1272624457/code-scanning/analyses"
                f'?ref=refs%2Fpull%2F121%2Fmerge&per_page=100&page={page + 1}>; rel="next"'
            ),
        )
        for page in range(1, 101)
    ]
    urls = _offline_http_pages(monkeypatch, pages)
    with pytest.raises(
        CodeQLAdmissionError, match="pagination_limit|invalid_pagination"
    ):
        verify_codeql_results(
            repository=REPOSITORY,
            ref=REF,
            sha=SHA,
            token="synthetic-token-not-for-output",
            deadline_seconds=5,
        )
    assert len(urls) == 100

"""Source-bound admission for completed GitHub CodeQL analyses and alerts."""

from __future__ import annotations

import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Mapping

from .evidence import attach_artifact_integrity, validate_artifact_integrity


SAFE_PRODUCT_CATEGORIES = (
    ".github/workflows/safe-product.yml:sast/language:python",
    ".github/workflows/safe-product.yml:sast/language:javascript-typescript",
)
CODEQL_WORKFLOW_CATEGORIES = (
    ".github/workflows/codeql.yml:analyze/language:python",
    ".github/workflows/codeql.yml:analyze/language:javascript-typescript",
)
SCHEMA = "wavemind.codeql_admission.v1"
API_ORIGIN = "https://api.github.com"
MAX_BODY_BYTES = 2_000_000
REQUEST_TIMEOUT_SECONDS = 15
KNOWN_SEVERITIES = {
    "critical",
    "high",
    "medium",
    "low",
    "warning",
    "note",
    "error",
}
KNOWN_STATES = {"open", "dismissed", "fixed"}
REPOSITORY_RE = re.compile(r"[A-Za-z0-9_.-]{1,100}/[A-Za-z0-9_.-]{1,100}")
REF_RE = re.compile(
    r"refs/(?:heads|tags)/[A-Za-z0-9._/-]{1,240}|refs/pull/[1-9][0-9]*/merge"
)
SHA_RE = re.compile(r"[0-9a-f]{40}")


class CodeQLAdmissionError(RuntimeError):
    """Sanitized, fail-closed CodeQL verification failure."""


def _validated_inputs(repository: str, ref: str, sha: str, token: str) -> None:
    if not isinstance(repository, str) or not REPOSITORY_RE.fullmatch(repository):
        raise CodeQLAdmissionError("invalid_repository")
    if not isinstance(ref, str) or not REF_RE.fullmatch(ref):
        raise CodeQLAdmissionError("invalid_ref")
    if ".." in ref or "//" in ref or ref.endswith(("/", ".", ".lock")):
        raise CodeQLAdmissionError("invalid_ref")
    if not isinstance(sha, str) or not SHA_RE.fullmatch(sha):
        raise CodeQLAdmissionError("invalid_sha")
    if not isinstance(token, str) or not token or len(token) > 4096:
        raise CodeQLAdmissionError("missing_token")


def fetch_github_json(
    url: str, *, headers: Mapping[str, str], timeout: float, max_body: int
) -> tuple[object, Mapping[str, str]]:
    """Fetch one pinned GitHub API page without exposing remote response bodies."""
    try:
        request = urllib.request.Request(url, headers=dict(headers), method="GET")
        with urllib.request.urlopen(request, timeout=timeout) as response:
            length = response.headers.get("Content-Length")
            if length is not None and int(length) > max_body:
                raise CodeQLAdmissionError("response_too_large")
            body = response.read(max_body + 1)
            if len(body) > max_body:
                raise CodeQLAdmissionError("response_too_large")
            value = json.loads(body.decode("utf-8"))
            return value, dict(response.headers.items())
    except CodeQLAdmissionError:
        raise
    except urllib.error.HTTPError as error:
        code = "rate_limit" if error.code in {403, 429} else "api_failure"
        raise CodeQLAdmissionError(code) from None
    except (urllib.error.URLError, TimeoutError, OSError):
        raise CodeQLAdmissionError("api_failure") from None
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError):
        raise CodeQLAdmissionError("malformed_response") from None


def _next_page(link: str | None, repository: str) -> str | None:
    if not link:
        return None
    next_urls = []
    for item in link.split(","):
        match = re.fullmatch(r'\s*<([^>]+)>\s*;\s*rel="([^"]+)"\s*', item)
        if match and match.group(2) == "next":
            next_urls.append(match.group(1))
    if len(next_urls) != 1:
        raise CodeQLAdmissionError("invalid_pagination")
    url = next_urls[0]
    parsed = urllib.parse.urlsplit(url)
    prefix = f"/repos/{repository}/code-scanning/"
    if (
        parsed.scheme != "https"
        or parsed.netloc != "api.github.com"
        or parsed.username is not None
        or parsed.fragment
        or not parsed.path.startswith(prefix)
    ):
        raise CodeQLAdmissionError("invalid_pagination")
    return url


def _pages(
    url: str,
    *,
    repository: str,
    token: str,
    fetch_json: Callable,
) -> list[dict]:
    headers = {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {token}",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "wavemind-codeql-admission",
    }
    values: list[dict] = []
    seen = set()
    for _ in range(100):
        if url in seen:
            raise CodeQLAdmissionError("invalid_pagination")
        seen.add(url)
        try:
            page, response_headers = fetch_json(
                url,
                headers=headers,
                timeout=REQUEST_TIMEOUT_SECONDS,
                max_body=MAX_BODY_BYTES,
            )
        except CodeQLAdmissionError:
            raise
        except (TimeoutError, OSError):
            raise CodeQLAdmissionError("api_failure") from None
        except Exception:
            raise CodeQLAdmissionError("malformed_response") from None
        if not isinstance(page, list) or not all(
            isinstance(item, dict) for item in page
        ):
            raise CodeQLAdmissionError("malformed_response")
        values.extend(page)
        if len(values) > 10_000:
            raise CodeQLAdmissionError("response_limit")
        url = _next_page(response_headers.get("Link"), repository)
        if url is None:
            return values
    raise CodeQLAdmissionError("pagination_limit")


def _analysis_configurations(analyses: list[dict], *, ref: str, sha: str) -> list[dict]:
    selected: dict[str, dict] = {}
    known = set(SAFE_PRODUCT_CATEGORIES) | set(CODEQL_WORKFLOW_CATEGORIES)
    for analysis in analyses:
        category = analysis.get("category")
        if analysis.get("ref") != ref:
            raise CodeQLAdmissionError("stale_analysis")
        if analysis.get("commit_sha") != sha:
            continue
        if category not in known:
            continue
        if (
            type(analysis.get("id")) is not int
            or analysis["id"] <= 0
            or type(analysis.get("results_count")) is not int
            or analysis["results_count"] < 0
            or type(analysis.get("rules_count")) is not int
            or analysis["rules_count"] < 0
        ):
            raise CodeQLAdmissionError("malformed_analysis")
        prior = selected.get(category)
        if prior is None or analysis["id"] > prior["id"]:
            selected[category] = analysis
    if not set(SAFE_PRODUCT_CATEGORIES) <= set(selected):
        raise CodeQLAdmissionError("missing_analysis")
    configurations = []
    for category in sorted(selected):
        analysis = selected[category]
        if analysis.get("error") not in {None, ""}:
            raise CodeQLAdmissionError("analysis_error")
        configurations.append(
            {
                "id": analysis["id"],
                "category": category,
                "results_count": analysis["results_count"],
                "rules_count": analysis["rules_count"],
            }
        )
    return configurations


def _alert_counts(alerts: list[dict], *, ref: str, sha: str) -> dict[str, int]:
    counts = {
        "total": 0,
        "open_high": 0,
        "open_critical": 0,
        "open_other": 0,
        "dismissed": 0,
        "fixed": 0,
    }
    known_categories = set(SAFE_PRODUCT_CATEGORIES) | set(CODEQL_WORKFLOW_CATEGORIES)
    numbers = set()
    for alert in alerts:
        number = alert.get("number")
        rule = alert.get("rule")
        instance = alert.get("most_recent_instance")
        if (
            type(number) is not int
            or number <= 0
            or number in numbers
            or not isinstance(rule, dict)
            or not isinstance(rule.get("id"), str)
            or not isinstance(instance, dict)
            or instance.get("ref") != ref
            or instance.get("commit_sha") != sha
            or instance.get("category") not in known_categories
        ):
            raise CodeQLAdmissionError("malformed_alert")
        numbers.add(number)
        severity = rule.get("security_severity_level")
        query_state = alert.get("_query_state")
        instance_state = instance.get("state")
        top_state = alert.get("state")
        if (
            severity not in KNOWN_SEVERITIES
            or query_state not in KNOWN_STATES
            or instance_state not in KNOWN_STATES
            or top_state not in {None, query_state}
        ):
            raise CodeQLAdmissionError("unknown_alert_value")
        counts["total"] += 1
        if query_state == "dismissed":
            if not isinstance(alert.get("dismissed_at"), str) or alert.get(
                "dismissed_reason"
            ) not in {"false positive", "won't fix", "used in tests"}:
                raise CodeQLAdmissionError("malformed_dismissal")
            counts["dismissed"] += 1
        elif query_state == "fixed":
            if not isinstance(alert.get("fixed_at"), str):
                raise CodeQLAdmissionError("malformed_fix")
            counts["fixed"] += 1
        elif severity == "critical":
            counts["open_critical"] += 1
        elif severity == "high":
            counts["open_high"] += 1
        else:
            counts["open_other"] += 1
    return counts


def verify_codeql_results(
    *,
    repository: str,
    ref: str,
    sha: str,
    token: str,
    fetch_json: Callable = fetch_github_json,
    deadline_seconds: float = 120,
    retry_seconds: float = 5,
) -> dict:
    _validated_inputs(repository, ref, sha, token)
    if not 0 <= deadline_seconds <= 600 or not 0 < retry_seconds <= 60:
        raise CodeQLAdmissionError("invalid_retry_policy")
    query = urllib.parse.urlencode({"ref": ref, "per_page": 100})
    analyses_url = f"{API_ORIGIN}/repos/{repository}/code-scanning/analyses?{query}"
    deadline = time.monotonic() + deadline_seconds
    while True:
        analyses = _pages(
            analyses_url,
            repository=repository,
            token=token,
            fetch_json=fetch_json,
        )
        try:
            configurations = _analysis_configurations(analyses, ref=ref, sha=sha)
            break
        except CodeQLAdmissionError as error:
            if str(error) != "missing_analysis" or time.monotonic() >= deadline:
                raise
            time.sleep(min(retry_seconds, max(0, deadline - time.monotonic())))
    expected_any_results = any(
        config["results_count"] > 0
        for config in configurations
        if config["category"] in SAFE_PRODUCT_CATEGORIES
    )
    while True:
        alerts = []
        for state in ("open", "dismissed", "fixed"):
            alert_query = urllib.parse.urlencode(
                {"ref": ref, "state": state, "per_page": 100}
            )
            state_alerts = _pages(
                f"{API_ORIGIN}/repos/{repository}/code-scanning/alerts?{alert_query}",
                repository=repository,
                token=token,
                fetch_json=fetch_json,
            )
            alerts.extend({**alert, "_query_state": state} for alert in state_alerts)
        if alerts or not expected_any_results:
            break
        if time.monotonic() >= deadline:
            raise CodeQLAdmissionError("missing_alert_results")
        time.sleep(min(retry_seconds, max(0, deadline - time.monotonic())))
    counts = _alert_counts(alerts, ref=ref, sha=sha)
    admitted = not counts["open_high"] and not counts["open_critical"]
    return attach_artifact_integrity(
        {
            "schema": SCHEMA,
            "status": "admitted" if admitted else "blocked",
            "admitted": admitted,
            "source": {"repository": repository, "ref": ref, "sha": sha},
            "analyzed_configurations": configurations,
            "alerts": counts,
        }
    )


def validate_codeql_admission(
    report: Mapping,
    *,
    repository: str,
    ref: str,
    sha: str,
) -> list[str]:
    errors = validate_artifact_integrity(report)
    if report.get("schema") != SCHEMA:
        errors.append("CodeQL result schema is invalid")
    if report.get("source") != {"repository": repository, "ref": ref, "sha": sha}:
        errors.append("CodeQL result source binding is invalid")
    configs = report.get("analyzed_configurations")
    if not isinstance(configs, list):
        errors.append("CodeQL analyzed configurations are missing")
        configs = []
    categories = {
        config.get("category")
        for config in configs
        if isinstance(config, Mapping)
        and type(config.get("id")) is int
        and type(config.get("results_count")) is int
        and type(config.get("rules_count")) is int
    }
    if not set(SAFE_PRODUCT_CATEGORIES) <= categories:
        errors.append("CodeQL required analyses are missing")
    counts = report.get("alerts")
    count_names = {
        "total",
        "open_high",
        "open_critical",
        "open_other",
        "dismissed",
        "fixed",
    }
    if (
        not isinstance(counts, Mapping)
        or set(counts) != count_names
        or any(
            type(counts[name]) is not int or counts[name] < 0 for name in count_names
        )
        or isinstance(counts, Mapping)
        and counts.get("total")
        != sum(counts.get(name, -1) for name in count_names - {"total"})
    ):
        errors.append("CodeQL alert counts are invalid")
    if report.get("status") != "admitted" or report.get("admitted") is not True:
        errors.append("CodeQL result status is not admitted")
    elif isinstance(counts, Mapping) and (
        counts.get("open_high") != 0 or counts.get("open_critical") != 0
    ):
        errors.append("CodeQL result admits blocking alerts")
    return errors

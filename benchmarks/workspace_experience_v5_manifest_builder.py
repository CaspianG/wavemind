from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CACHE_ROOT = Path("D:/wm-goal7-temp/repos")
DEFAULT_OUTPUT = ROOT / "benchmarks" / "workspace_experience_v5_manifest.json"
SCHEMA = "wavemind.workspace_experience_v5_manifest.v1"

REPOSITORIES: dict[str, dict[str, str]] = {
    "requests": {
        "name": "Requests",
        "remote": "https://github.com/psf/requests.git",
        "web": "https://github.com/psf/requests",
        "commit": "1f6589ec3a1ee910f9a65cc3ceac60b26677bc0e",
        "license": "Apache-2.0",
        "stack": "python",
    },
    "flask": {
        "name": "Flask",
        "remote": "https://github.com/pallets/flask.git",
        "web": "https://github.com/pallets/flask",
        "commit": "6a2f545bfd8ed31e19066a299296917e034aca58",
        "license": "BSD-3-Clause",
        "stack": "python",
    },
    "vite": {
        "name": "Vite",
        "remote": "https://github.com/vitejs/vite.git",
        "web": "https://github.com/vitejs/vite",
        "commit": "57fea001d154e7dd8d5d74d3082731f1dcfd31be",
        "license": "MIT",
        "stack": "javascript",
    },
}


REQUESTS_CASES = [
    ("api-surface-smoke", "src/requests/api.py", "python_py_compile", "API helper surface changes must compile before agent reuse", "API helper workspace issue"),
    ("session-pooling-smoke", "src/requests/sessions.py", "python_py_compile", "Session pooling edits need syntax verification before replay", "session pooling workspace issue"),
    ("adapter-transport-smoke", "src/requests/adapters.py", "python_py_compile", "Transport adapter changes require local compile verification", "adapter transport workspace issue"),
    ("model-body-smoke", "src/requests/models.py", "python_py_compile", "Prepared request model edits must pass module compile", "prepared model workspace issue"),
    ("cookie-policy-smoke", "src/requests/cookies.py", "python_py_compile", "Cookie policy changes need verified Python syntax", "cookie policy workspace issue"),
    ("auth-flow-smoke", "src/requests/auth.py", "python_py_compile", "Authentication helper edits require compile verification", "auth helper workspace issue"),
    ("utils-regression-smoke", "src/requests/utils.py", "python_py_compile", "Utility regression edits need compile verification", "utility regression workspace issue"),
    ("structure-case-smoke", "src/requests/structures.py", "python_py_compile", "Case-insensitive structure updates must compile", "structure case workspace issue"),
    ("exception-path-smoke", "src/requests/exceptions.py", "python_py_compile", "Exception taxonomy changes need syntax verification", "exception path workspace issue"),
    ("hook-dispatch-smoke", "src/requests/hooks.py", "python_py_compile", "Hook dispatch changes require compile verification", "hook dispatch workspace issue"),
    ("compat-layer-smoke", "src/requests/compat.py", "python_py_compile", "Compatibility layer edits must pass compile before reuse", "compat layer workspace issue"),
    ("help-metadata-smoke", "src/requests/help.py", "python_py_compile", "Environment help metadata edits need compile verification", "help metadata workspace issue"),
    ("status-map-smoke", "src/requests/status_codes.py", "python_py_compile", "Status code map edits require Python syntax verification", "status map workspace issue"),
    ("package-init-smoke", "src/requests/__init__.py", "python_py_compile", "Package init changes must compile before agent replay", "package init workspace issue"),
    ("test-requests-smoke", "tests/test_requests.py", "python_ast_parse", "Large request behavior tests need AST parse before selection", "request behavior test workspace issue"),
    ("test-utils-smoke", "tests/test_utils.py", "python_ast_parse", "Utility test edits need AST parse before replay", "utility test workspace issue"),
    ("project-metadata-toml", "pyproject.toml", "python_toml_parse", "Packaging metadata changes must parse as TOML", "packaging metadata workspace issue"),
    ("tox-config-parse", "tox.ini", "python_configparser_parse", "Tox environment edits must parse as INI", "tox config workspace issue"),
    ("ci-run-tests-yaml", ".github/workflows/run-tests.yml", "yaml_parse", "Test workflow changes need YAML parse verification", "test workflow workspace issue"),
    ("ci-codeql-yaml", ".github/workflows/codeql-analysis.yml", "yaml_parse", "CodeQL workflow changes need YAML parse verification", "codeql workflow workspace issue"),
]


FLASK_CASES = [
    ("app-lifecycle-smoke", "src/flask/app.py", "python_py_compile", "Application lifecycle edits must compile before reuse", "application lifecycle workspace issue"),
    ("blueprint-routing-smoke", "src/flask/blueprints.py", "python_py_compile", "Blueprint routing edits require compile verification", "blueprint routing workspace issue"),
    ("cli-runner-smoke", "src/flask/cli.py", "python_py_compile", "CLI runner changes need Python compile verification", "cli runner workspace issue"),
    ("config-loader-smoke", "src/flask/config.py", "python_py_compile", "Configuration loader edits must compile", "config loader workspace issue"),
    ("context-stack-smoke", "src/flask/ctx.py", "python_py_compile", "Request context stack edits require compile verification", "context stack workspace issue"),
    ("helper-layer-smoke", "src/flask/helpers.py", "python_py_compile", "Helper layer changes need syntax verification", "helper layer workspace issue"),
    ("json-provider-smoke", "src/flask/json/provider.py", "python_py_compile", "JSON provider edits must compile before replay", "json provider workspace issue"),
    ("logging-setup-smoke", "src/flask/logging.py", "python_py_compile", "Logging setup edits require compile verification", "logging setup workspace issue"),
    ("session-interface-smoke", "src/flask/sessions.py", "python_py_compile", "Session interface changes need compile verification", "session interface workspace issue"),
    ("signal-dispatch-smoke", "src/flask/signals.py", "python_py_compile", "Signal dispatch edits must compile", "signal dispatch workspace issue"),
    ("template-render-smoke", "src/flask/templating.py", "python_py_compile", "Template rendering edits need compile verification", "template render workspace issue"),
    ("testing-client-smoke", "src/flask/testing.py", "python_py_compile", "Testing client changes require compile verification", "testing client workspace issue"),
    ("view-dispatch-smoke", "src/flask/views.py", "python_py_compile", "View dispatch edits must compile", "view dispatch workspace issue"),
    ("typing-route-smoke", "src/flask/typing.py", "python_py_compile", "Public typing edits need compile verification", "typing route workspace issue"),
    ("test-basic-ast", "tests/test_basic.py", "python_ast_parse", "Core behavior test edits need AST parse before replay", "core behavior test workspace issue"),
    ("test-cli-ast", "tests/test_cli.py", "python_ast_parse", "CLI test edits must parse before selection", "cli test workspace issue"),
    ("project-metadata-toml", "pyproject.toml", "python_toml_parse", "Flask packaging metadata must parse as TOML", "flask packaging workspace issue"),
    ("precommit-yaml", ".pre-commit-config.yaml", "yaml_parse", "Pre-commit hook changes need YAML parse verification", "precommit workflow workspace issue"),
    ("ci-tests-yaml", ".github/workflows/tests.yaml", "yaml_parse", "CI tests workflow changes need YAML parse verification", "flask ci tests workspace issue"),
    ("docs-conf-compile", "docs/conf.py", "python_py_compile", "Documentation config edits must compile", "docs config workspace issue"),
]


VITE_CASES = [
    ("root-package-json", "package.json", "json_parse", "Root package metadata changes must parse as JSON", "root package workspace issue"),
    ("docs-package-json", "docs/package.json", "json_parse", "Docs package metadata changes need JSON parse verification", "docs package workspace issue"),
    ("scripts-tsconfig-json", "scripts/tsconfig.json", "json_parse", "Scripts TypeScript config must parse as JSON", "scripts tsconfig workspace issue"),
    ("react-template-package-json", "packages/create-vite/template-react/package.json", "json_parse", "React template package metadata must parse as JSON", "react package workspace issue"),
    ("workspace-yaml", "pnpm-workspace.yaml", "yaml_parse", "Workspace package map changes need YAML verification", "workspace package map issue"),
    ("ci-yaml", ".github/workflows/ci.yml", "yaml_parse", "Main CI workflow changes need YAML verification", "main ci workflow issue"),
    ("publish-yaml", ".github/workflows/publish.yml", "yaml_parse", "Publish workflow changes must parse as YAML", "publish workflow issue"),
    ("release-yaml", ".github/workflows/release-tag.yml", "yaml_parse", "Release tag workflow changes need YAML verification", "release workflow issue"),
    ("issue-template-yaml", ".github/ISSUE_TEMPLATE/bug_report.yml", "yaml_parse", "Bug report template changes need YAML verification", "bug template workflow issue"),
    ("eslint-config-syntax", "eslint.config.js", "node_syntax_check", "Lint rule setup edits require Node syntax verification", "lint rule workspace issue"),
    ("docs-banner-syntax", "docs/.vitepress/inlined-scripts/banner.js", "node_syntax_check", "Docs banner script edits require Node syntax verification", "docs banner workspace issue"),
    ("team-data-syntax", "docs/_data/team.js", "node_syntax_check", "Team data script changes need Node syntax verification", "team data workspace issue"),
    ("template-lit-element-syntax", "packages/create-vite/template-lit/src/my-element.js", "node_syntax_check", "Lit template element changes need syntax verification", "lit element workspace issue"),
    ("template-preact-config-syntax", "packages/create-vite/template-preact/vite.config.js", "node_syntax_check", "Preact starter setup changes need Node syntax verification", "preact starter workspace issue"),
    ("template-qwik-config-syntax", "packages/create-vite/template-qwik/vite.config.js", "node_syntax_check", "Qwik starter setup changes need Node syntax verification", "qwik starter workspace issue"),
    ("template-react-config-syntax", "packages/create-vite/template-react/vite.config.js", "node_syntax_check", "React starter setup changes need Node syntax verification", "react starter workspace issue"),
    ("template-solid-config-syntax", "packages/create-vite/template-solid/vite.config.js", "node_syntax_check", "Solid starter setup changes need Node syntax verification", "solid starter workspace issue"),
    ("template-svelte-config-syntax", "packages/create-vite/template-svelte/vite.config.js", "node_syntax_check", "Svelte starter setup changes need Node syntax verification", "svelte starter workspace issue"),
    ("template-vanilla-counter-syntax", "packages/create-vite/template-vanilla/src/counter.js", "node_syntax_check", "Vanilla counter script changes need Node syntax verification", "vanilla counter workspace issue"),
    ("template-vue-config-syntax", "packages/create-vite/template-vue/vite.config.js", "node_syntax_check", "Vue starter setup changes need Node syntax verification", "vue starter workspace issue"),
]


def build_manifest(cache_root: str | Path = DEFAULT_CACHE_ROOT) -> dict[str, Any]:
    root = Path(cache_root)
    cases: list[dict[str, Any]] = []
    for repo_id, definitions in (
        ("requests", REQUESTS_CASES),
        ("flask", FLASK_CASES),
        ("vite", VITE_CASES),
    ):
        for index, (slug, path, outcome_kind, title, symptom) in enumerate(definitions):
            split = "dev" if index % 2 == 0 else "heldout"
            cases.append(_positive_case(root, repo_id, index, slug, path, outcome_kind, title, symptom, split))
    for index in range(24):
        repo_id = ("requests", "flask", "vite")[index % 3]
        control_kind = ("unverified", "stale", "conflict", "wrong_workspace")[index % 4]
        split = "dev" if index % 2 == 0 else "heldout"
        cases.append(_control_case(repo_id, index, control_kind, split))
    payload: dict[str, Any] = {
        "schema": SCHEMA,
        "revision": "workspace-experience-v5-real-work-freeze-candidate-20260810",
        "repositories": REPOSITORIES,
        "cases": cases,
        "thresholds": {
            "task_success_lift_pp_min": 15.0,
            "repeated_known_error_reduction_min": 0.50,
            "context_reduction_min": 0.30,
            "false_procedure_injection_max": 0.01,
            "unverified_injection": 0,
            "workspace_namespace_leakage": 0,
            "mandatory_event_capture_min": 0.99,
            "cross_client_citation_state_parity": 1.00,
            "packet_selection_p95_ms_max": 100.0,
            "packet_selection_p99_ms_max": 250.0,
            "clean_onboarding_seconds_max": 300.0,
        },
        "success_criteria": "exact_case_procedure_and_executable_outcome",
        "claim_boundary": (
            "Local real-work workspace experience benchmark. It measures exact "
            "procedure selection and executable local outcomes; no universal model-quality claim."
        ),
        "sha256": "",
    }
    payload["sha256"] = _sha256({key: value for key, value in payload.items() if key != "sha256"})
    return payload


def _positive_case(
    cache_root: Path,
    repo_id: str,
    index: int,
    slug: str,
    source_path: str,
    outcome_kind: str,
    title: str,
    symptom: str,
    split: str,
) -> dict[str, Any]:
    repo = REPOSITORIES[repo_id]
    file_path = cache_root / repo_id / source_path
    if not file_path.exists():
        raise FileNotFoundError(file_path)
    case_id = f"{repo_id}-v5-{index:02d}-{slug}"
    procedure_id = f"proc-{repo_id}-{slug}"
    semantic_family = f"{repo_id}:{slug}"
    return {
        "case_id": case_id,
        "kind": "positive",
        "split": split,
        "repo": repo_id,
        "semantic_family": semantic_family,
        "source_family": semantic_family,
        "workflow_group": f"{repo_id}-{slug}",
        "task_type": slug.replace("-", "_"),
        "procedure_id": procedure_id,
        "procedure_title": title,
        "failure_symptom": symptom,
        "source_path": source_path,
        "source_url": f"{repo['web']}/blob/{repo['commit']}/{source_path}",
        "source_sha256": hashlib.sha256(file_path.read_bytes()).hexdigest(),
        "license": repo["license"],
        "query": f"An agent is about to handle this workspace procedure: {title}. Which verified packet applies?",
        "expected_behavior": "execute_verified_outcome",
        "expected_outcome": {
            "kind": outcome_kind,
            "path": source_path,
            "expected_exit_code": 0,
        },
        "distractor": {
            "kind": "unverified_failed_attempt",
            "procedure_id": f"raw-{repo_id}-{slug}-unverified",
            "text": (
                f"Unverified trace for {symptom}: skip the local verification and rely on previous "
                "agent text. This is intentionally not independently confirmed."
            ),
        },
    }


def _control_case(repo_id: str, index: int, control_kind: str, split: str) -> dict[str, Any]:
    target = f"{repo_id}:{control_kind}:{index:02d}"
    origin_repo = {"requests": "flask", "flask": "vite", "vite": "requests"}[repo_id]
    return {
        "case_id": f"control-v5-{index:02d}-{control_kind}-{repo_id}",
        "kind": control_kind,
        "split": split,
        "repo": repo_id,
        "origin_repo": origin_repo if control_kind == "wrong_workspace" else repo_id,
        "semantic_family": target,
        "source_family": target,
        "workflow_group": f"control-{control_kind}-{index:02d}",
        "task_type": f"control_{control_kind}",
        "query": f"Should a workspace packet be used for an {control_kind} evidence request {index:02d}?",
        "expected_behavior": "abstain",
    }


def write_manifest(
    output: str | Path = DEFAULT_OUTPUT,
    *,
    cache_root: str | Path = DEFAULT_CACHE_ROOT,
) -> dict[str, Any]:
    payload = build_manifest(cache_root)
    output_path = Path(output)
    output_path.write_text(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    return payload


def _sha256(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


if __name__ == "__main__":
    manifest = write_manifest()
    print(json.dumps({"schema": SCHEMA, "cases": len(manifest["cases"]), "sha256": manifest["sha256"]}, indent=2))

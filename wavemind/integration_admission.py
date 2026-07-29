from __future__ import annotations

import asyncio
import hashlib
import importlib.util
import json
import os
import platform
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from fastapi.testclient import TestClient

from .api import create_app
from .core import WaveMind
from .experience import (
    ExperienceKind,
    ExperienceRecord,
    ExperienceSource,
    ExperienceStatus,
    SQLiteExperienceStore,
    TrustClass,
)
from .experience_compiler import ExperienceCompiler
from .experience_portability import (
    export_experience_bundle,
    import_experience_bundle,
    import_mem0_json,
)
from .integrations.anthropic import (
    ANTHROPIC_MEMORY_TOOL,
    AnthropicMemoryHandler,
)
from .integrations.langgraph import make_experience_recall_node
from .integrations.mcp_experience import (
    ExperienceMCPAdapter,
    build_experience_mcp_server,
)
from .integrations.openai_agents import (
    WaveMindAgentsSession,
    make_experience_input_callback,
)
from .memory_firewall import FirewallContext, MemoryFirewall, MemoryFirewallPolicy


INTEGRATION_ADMISSION_SCHEMA = "wavemind.integration_admission.v1"
INTEGRATION_SUITE_REVISION = "trusted-agent-integrations-v1-20260730"
INTEGRATION_SUITE_FINGERPRINT = (
    "3b55e8d83bdcc3019a66ad9228a2a5a679b6ad84383746be648443f57785a82f"
)
PROJECT_ROOT = Path(__file__).resolve().parents[1]
_GIT_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
_REQUIRED_CASES = (
    "python-compiler-contract",
    "openai-agents-contract",
    "anthropic-memory-contract",
    "mcp-contract",
    "langgraph-contract",
    "http-memory-contract",
    "http-experience-contract",
    "provider-semantic-parity",
    "portable-bundle-parity",
    "mem0-import-idempotency",
    "typescript-packed-live-contract",
)
_REQUIRED_MODULES = (
    "agents.memory",
    "anthropic.types.beta",
    "langgraph.graph",
    "mcp.server.fastmcp",
)
_SUITE_CONTRACT = {
    "minimum_consecutive_runs": 3,
    "provider_surface_count": 5,
    "provider_semantic_parity": 1.0,
    "portable_bundle_parity": 1.0,
    "typescript_concurrent_explanations": 16,
    "skipped_mandatory_cases": 0,
}


def evaluate_integration_admission(
    *,
    source_sha: str | None = None,
    expected_source_sha: str | None = None,
    consecutive_runs: int = 3,
    project_root: str | Path = PROJECT_ROOT,
) -> dict[str, Any]:
    if consecutive_runs < _SUITE_CONTRACT["minimum_consecutive_runs"]:
        raise ValueError("integration admission requires at least three runs")
    root = Path(project_root).resolve()
    actual_source_sha = source_sha or _git_sha(root)
    environment = _environment()
    runs = [_run_suite(root, actual_source_sha) for _ in range(consecutive_runs)]
    suite_fingerprint = _suite_fingerprint()
    run_summaries = [
        {
            "run": index + 1,
            "status": run["status"],
            "verdict_fingerprint": _verdict_fingerprint(run),
            "case_count": len(run["cases"]),
            "passed": sum(int(case["passed"]) for case in run["cases"]),
            "total_seconds": run["total_seconds"],
        }
        for index, run in enumerate(runs)
    ]
    primary = runs[0]
    case_by_id = {case["id"]: case for case in primary["cases"]}
    provider_parity = case_by_id.get("provider-semantic-parity", {}).get(
        "evidence", {}
    )
    portable_parity = case_by_id.get("portable-bundle-parity", {}).get(
        "evidence", {}
    )
    typescript = case_by_id.get("typescript-packed-live-contract", {}).get(
        "evidence", {}
    )
    provider_modules = environment["provider_modules"]
    checks = [
        _check(
            "source-sha",
            bool(_GIT_SHA_RE.fullmatch(actual_source_sha))
            and (
                expected_source_sha is None
                or actual_source_sha == expected_source_sha
            ),
            actual_source_sha,
            expected_source_sha or "exact 40-character git SHA",
            "source SHA is missing or does not match the requested revision",
        ),
        _check(
            "frozen-suite",
            suite_fingerprint == INTEGRATION_SUITE_FINGERPRINT,
            {
                "revision": INTEGRATION_SUITE_REVISION,
                "fingerprint_sha256": suite_fingerprint,
                "case_count": len(_REQUIRED_CASES),
            },
            {
                "revision": INTEGRATION_SUITE_REVISION,
                "fingerprint_sha256": INTEGRATION_SUITE_FINGERPRINT,
                "case_count": len(_REQUIRED_CASES),
            },
            "integration suite changed without a revision update",
        ),
        _check(
            "required-cases",
            set(case_by_id) == set(_REQUIRED_CASES),
            sorted(case_by_id),
            sorted(_REQUIRED_CASES),
            "one or more mandatory integration cases are missing",
        ),
        _check(
            "official-provider-sdks",
            all(provider_modules.values()),
            provider_modules,
            "OpenAI Agents, Anthropic, MCP, and LangGraph SDKs installed",
            "one or more official provider SDKs are unavailable",
        ),
        _check(
            "all-contracts",
            all(case["passed"] for run in runs for case in run["cases"]),
            [
                {
                    "run": index + 1,
                    "failed": [
                        case["id"] for case in run["cases"] if not case["passed"]
                    ],
                }
                for index, run in enumerate(runs)
            ],
            "every mandatory case passes in every run",
            "one or more provider or SDK contracts failed",
        ),
        _check(
            "provider-semantic-parity",
            float(provider_parity.get("parity", 0.0))
            == _SUITE_CONTRACT["provider_semantic_parity"]
            and int(provider_parity.get("surface_count", 0))
            >= _SUITE_CONTRACT["provider_surface_count"],
            provider_parity,
            "1.00 citation parity across at least five provider surfaces",
            "provider surfaces returned different experience semantics",
        ),
        _check(
            "portable-bundle-parity",
            float(portable_parity.get("parity", 0.0))
            == _SUITE_CONTRACT["portable_bundle_parity"]
            and bool(portable_parity.get("idempotent")),
            portable_parity,
            "1.00 semantic parity and idempotent replay",
            "portable experience replay lost or duplicated state",
        ),
        _check(
            "typescript-public-package",
            bool(typescript.get("packed_install"))
            and bool(typescript.get("live_memory_lifecycle"))
            and bool(typescript.get("safe_retry"))
            and bool(typescript.get("mutation_not_retried"))
            and bool(typescript.get("cancellation"))
            and int(typescript.get("concurrent_explanations", 0))
            >= _SUITE_CONTRACT["typescript_concurrent_explanations"],
            typescript,
            "packed install plus live lifecycle, safe retry, cancellation, and concurrency",
            "the packed TypeScript SDK failed one or more runtime guarantees",
        ),
        _check(
            "deterministic-verdict",
            len({row["status"] for row in run_summaries}) == 1
            and len(
                {row["verdict_fingerprint"] for row in run_summaries}
            )
            == 1,
            run_summaries,
            "three or more identical consecutive verdicts",
            "consecutive integration runs produced different verdicts",
        ),
        _check(
            "no-skipped-cases",
            sum(len(run["skipped"]) for run in runs)
            == _SUITE_CONTRACT["skipped_mandatory_cases"],
            [run["skipped"] for run in runs],
            "zero skipped mandatory cases",
            "one or more mandatory integration cases were skipped",
        ),
    ]
    passed = sum(int(check["passed"]) for check in checks)
    issues = [check["issue"] for check in checks if not check["passed"]]
    admitted = passed == len(checks)
    return {
        "schema": INTEGRATION_ADMISSION_SCHEMA,
        "status": "admitted" if admitted else "blocked",
        "admitted": admitted,
        "evaluated_at": _utc_now(),
        "source_sha": actual_source_sha,
        "suite": {
            "revision": INTEGRATION_SUITE_REVISION,
            "fingerprint_sha256": suite_fingerprint,
        },
        "environment": environment,
        "consecutive_runs": run_summaries,
        "checks": checks,
        "summary": {
            "checks_passed": passed,
            "checks_total": len(checks),
            "case_count": len(primary["cases"]),
            "provider_parity": float(provider_parity.get("parity", 0.0)),
            "portable_parity": float(portable_parity.get("parity", 0.0)),
            "total_seconds": sum(run["total_seconds"] for run in runs),
            "blocker_count": len(issues),
        },
        "issues": issues,
        "skipped": [],
        "per_case": primary["cases"],
        "claim_boundary": (
            "Deterministic local contract and clean-package evidence for the "
            "pinned provider SDKs and HTTP runtime. It is not a certification "
            "of third-party hosted provider availability."
        ),
    }


def render_integration_admission_markdown(payload: dict[str, Any]) -> str:
    summary = payload["summary"]
    lines = [
        "# WaveMind Integration Admission",
        "",
        f"- Status: **{payload['status']}**",
        f"- Source SHA: `{payload['source_sha']}`",
        f"- Checks: **{summary['checks_passed']}/{summary['checks_total']}**",
        f"- Mandatory cases: **{summary['case_count']}**",
        f"- Provider semantic parity: **{summary['provider_parity']:.3f}**",
        f"- Portable bundle parity: **{summary['portable_parity']:.3f}**",
        "",
        "| Check | Status | Target |",
        "|---|---:|---|",
    ]
    for check in payload["checks"]:
        lines.append(
            f"| `{check['id']}` | `{check['status']}` | "
            f"{_compact(check['target'])} |"
        )
    lines.extend(["", "## Mandatory cases", "", "| Case | Status |", "|---|---:|"])
    for case in payload["per_case"]:
        lines.append(f"| `{case['id']}` | `{case['status']}` |")
    if payload["issues"]:
        lines.extend(["", "## Required actions", ""])
        lines.extend(f"- {issue}" for issue in payload["issues"])
    lines.extend(["", f"> {payload['claim_boundary']}", ""])
    return "\n".join(lines)


def _run_suite(root: Path, source_sha: str) -> dict[str, Any]:
    started = time.perf_counter()
    with tempfile.TemporaryDirectory(prefix="wavemind-integration-") as temp:
        cases = _provider_cases(Path(temp))
        cases.append(
            _capture_case(
                "typescript-packed-live-contract",
                lambda: _typescript_live_contract(root, Path(temp), source_sha),
            )
        )
    return {
        "status": (
            "admitted" if all(case["passed"] for case in cases) else "blocked"
        ),
        "cases": cases,
        "skipped": [],
        "total_seconds": time.perf_counter() - started,
    }


def _provider_cases(root: Path) -> list[dict[str, Any]]:
    store = SQLiteExperienceStore(root / "experience.db")
    mind = WaveMind(db_path=root / "memory.db")
    citations: dict[str, list[str]] = {}
    cases: list[dict[str, Any]] = []
    try:
        store.put(_seed_experience())
        compiler = ExperienceCompiler(
            store,
            MemoryFirewall(
                MemoryFirewallPolicy(
                    namespace="agent",
                    policy_id="integration-admission",
                )
            ),
        )

        def python_contract() -> dict[str, Any]:
            packet = compiler.compile_packet(
                "recover a failed deployment",
                namespace="agent",
                context=FirewallContext(namespace="agent", actor="python"),
                token_budget=200,
            )
            citations["python"] = list(packet.citations)
            return {
                "schema": packet.as_dict()["schema"],
                "citations": citations["python"],
            }

        cases.append(
            _capture_case("python-compiler-contract", python_contract)
        )

        def openai_contract() -> dict[str, Any]:
            agents_memory = __import__("agents.memory", fromlist=["Session"])
            session_path = root / "openai-session.db"
            session = WaveMindAgentsSession(
                "integration-session",
                db_path=session_path,
            )
            try:
                if not isinstance(session, agents_memory.Session):
                    raise AssertionError("session does not implement official protocol")
                asyncio.run(
                    session.add_items(
                        [{"role": "user", "content": "deployment failed"}]
                    )
                )
            finally:
                session.close()
            restarted = WaveMindAgentsSession(
                "integration-session",
                db_path=session_path,
            )
            try:
                persisted = asyncio.run(restarted.get_items())
            finally:
                restarted.close()
            callback = make_experience_input_callback(
                compiler,
                namespace="agent",
                token_budget=200,
            )
            result = asyncio.run(
                callback(
                    [],
                    [
                        {
                            "role": "user",
                            "content": "recover a failed deployment",
                        }
                    ],
                )
            )
            injected = result[-2]
            citations["openai"] = list(injected["metadata"]["citations"])
            if persisted != [
                {"role": "user", "content": "deployment failed"}
            ]:
                raise AssertionError("OpenAI session did not survive restart")
            return {
                "session_persisted": True,
                "ephemeral": injected["metadata"]["ephemeral"],
                "citations": citations["openai"],
            }

        cases.append(_capture_case("openai-agents-contract", openai_contract))

        def anthropic_contract() -> dict[str, Any]:
            beta = __import__("anthropic.types.beta", fromlist=["*"])
            annotations = beta.BetaMemoryTool20250818Param.__annotations__
            if not set(ANTHROPIC_MEMORY_TOOL) <= set(annotations):
                raise AssertionError("official Anthropic typed dict mismatch")
            handler = AnthropicMemoryHandler(
                str(root / "anthropic.db"),
                namespace="agent",
            )
            try:
                handler.execute(
                    "create",
                    "/memories/recovery.md",
                    file_text="Check health.\nRoll back.",
                )
                handler.execute(
                    "str_replace",
                    "/memories/recovery.md",
                    old_str="Check health.",
                    new_str="Check health and logs.",
                )
                viewed = handler.execute("view", "/memories/recovery.md")
                traversal_blocked = False
                try:
                    handler.execute("view", "/memories/../secrets")
                except ValueError:
                    traversal_blocked = True
                if not traversal_blocked:
                    raise AssertionError("Anthropic memory traversal was accepted")
                return {
                    "tool": ANTHROPIC_MEMORY_TOOL,
                    "content": viewed["content"],
                    "traversal_blocked": traversal_blocked,
                }
            finally:
                handler.close()

        cases.append(
            _capture_case("anthropic-memory-contract", anthropic_contract)
        )

        def mcp_contract() -> dict[str, Any]:
            adapter = ExperienceMCPAdapter(compiler)
            packet = adapter.call_tool(
                "compile_experience_packet",
                {
                    "query": "recover a failed deployment",
                    "namespace": "agent",
                    "token_budget": 200,
                },
            )
            citations["mcp"] = list(packet["citations"])
            server = build_experience_mcp_server(compiler)
            tools = asyncio.run(server.list_tools())
            names = sorted(tool.name for tool in tools)
            if names != ["compile_experience_packet", "expand_experience"]:
                raise AssertionError("official FastMCP tools differ")
            return {"tools": names, "citations": citations["mcp"]}

        cases.append(_capture_case("mcp-contract", mcp_contract))

        def langgraph_contract() -> dict[str, Any]:
            graph_module = __import__("langgraph.graph", fromlist=["*"])
            recall = make_experience_recall_node(
                compiler,
                namespace="agent",
                token_budget=200,
            )
            builder = graph_module.StateGraph(dict)
            builder.add_node("experience", recall)
            builder.add_edge(graph_module.START, "experience")
            builder.add_edge("experience", graph_module.END)
            graph = builder.compile()
            result = graph.invoke(
                {"input": "recover a failed deployment"}
            )
            citations["langgraph"] = list(
                result["experience_packet_data"]["citations"]
            )
            return {
                "compiled": True,
                "citations": citations["langgraph"],
            }

        cases.append(_capture_case("langgraph-contract", langgraph_contract))

        def http_memory_contract() -> dict[str, Any]:
            with TestClient(create_app(mind=mind, experience_store=store)) as client:
                remembered = client.post(
                    "/remember",
                    json={
                        "text": "The deployment uses a canary.",
                        "namespace": "agent",
                        "metadata": {
                            "provenance": {
                                "source": "integration",
                                "id": "memory-1",
                            }
                        },
                    },
                )
                memory_id = remembered.json()["id"]
                query = client.post(
                    "/query",
                    json={
                        "text": "deployment canary",
                        "namespace": "agent",
                        "top_k": 1,
                    },
                )
                feedback = client.post(
                    "/feedback",
                    json={
                        "id": memory_id,
                        "namespace": "agent",
                        "useful": True,
                    },
                )
                explanation = client.get(
                    f"/memories/{memory_id}/explain",
                    params={"namespace": "agent"},
                )
                forgotten = client.request(
                    "DELETE",
                    "/forget",
                    json={"id": memory_id, "namespace": "agent"},
                )
            if query.json()["results"][0]["id"] != memory_id:
                raise AssertionError("HTTP query did not return the stored memory")
            if explanation.json()["provenance"]["id"] != "memory-1":
                raise AssertionError("HTTP explanation lost provenance")
            return {
                "remembered": remembered.status_code == 200,
                "queried": query.status_code == 200,
                "feedback": feedback.json()["ok"],
                "explained": explanation.json()["schema"],
                "forgotten": forgotten.json()["deleted"],
            }

        cases.append(_capture_case("http-memory-contract", http_memory_contract))

        def http_experience_contract() -> dict[str, Any]:
            with TestClient(create_app(mind=mind, experience_store=store)) as client:
                packet = client.post(
                    "/experience/packet",
                    json={
                        "query": "recover a failed deployment",
                        "namespace": "agent",
                        "token_budget": 200,
                    },
                ).json()
                citations["http"] = list(packet["citations"])
                exported = client.post(
                    "/experience/export",
                    json={"namespace": "agent"},
                ).json()
                imported = client.post(
                    "/experience/import",
                    json={"bundle": exported},
                ).json()
            return {
                "citations": citations["http"],
                "bundle_parity": imported["parity"],
            }

        cases.append(
            _capture_case("http-experience-contract", http_experience_contract)
        )

        def semantic_parity() -> dict[str, Any]:
            expected = ["experience:exp_integration@v1"]
            matches = sum(value == expected for value in citations.values())
            required_surfaces = _SUITE_CONTRACT["provider_surface_count"]
            parity = matches / required_surfaces
            return {
                "parity": parity,
                "surface_count": len(citations),
                "citations": dict(sorted(citations.items())),
                "_passed": (
                    len(citations) == required_surfaces
                    and parity == _SUITE_CONTRACT["provider_semantic_parity"]
                ),
            }

        cases.append(
            _capture_case("provider-semantic-parity", semantic_parity)
        )

        def portable_contract() -> dict[str, Any]:
            target = SQLiteExperienceStore(root / "portable-target.db")
            try:
                bundle = export_experience_bundle(store, namespace="agent")
                first = import_experience_bundle(target, bundle)
                second = import_experience_bundle(target, bundle)
                return {
                    "parity": first.parity,
                    "idempotent": second.inserted_records == 0,
                    "records": first.record_count,
                    "_passed": first.exact
                    and second.exact
                    and second.inserted_records == 0,
                }
            finally:
                target.close()

        cases.append(
            _capture_case("portable-bundle-parity", portable_contract)
        )

        def mem0_contract() -> dict[str, Any]:
            imported = SQLiteExperienceStore(root / "mem0.db")
            try:
                payload = {
                    "results": [
                        {
                            "id": "preference-1",
                            "memory": "The user prefers concise replies.",
                            "metadata": {"type": "preference"},
                        }
                    ]
                }
                first = import_mem0_json(
                    imported,
                    payload,
                    namespace="agent",
                )
                second = import_mem0_json(
                    imported,
                    payload,
                    namespace="agent",
                )
                count = len(imported.list(namespace="agent"))
                return {
                    "same_id": first[0].id == second[0].id,
                    "record_count": count,
                    "_passed": first[0].id == second[0].id and count == 1,
                }
            finally:
                imported.close()

        cases.append(
            _capture_case("mem0-import-idempotency", mem0_contract)
        )
    finally:
        mind.close()
        store.close()
    return cases


def _typescript_live_contract(
    root: Path,
    temporary_root: Path,
    source_sha: str,
) -> dict[str, Any]:
    node = shutil.which("node")
    npm = shutil.which("npm.cmd" if os.name == "nt" else "npm")
    if node is None or npm is None:
        raise RuntimeError("Node.js and npm are required")
    sdk = root / "sdk" / "typescript"
    build = _run([npm, "run", "build"], cwd=sdk, timeout=120)
    if build.returncode != 0:
        raise RuntimeError(f"TypeScript build failed: {build.stderr.strip()}")
    packages = temporary_root / "packages"
    consumer = temporary_root / "consumer"
    packages.mkdir()
    consumer.mkdir()
    packed = _run(
        [npm, "pack", "--json", "--pack-destination", str(packages)],
        cwd=sdk,
        timeout=120,
    )
    if packed.returncode != 0:
        raise RuntimeError(f"npm pack failed: {packed.stderr.strip()}")
    tarball = packages / json.loads(packed.stdout)[0]["filename"]
    (consumer / "package.json").write_text(
        json.dumps(
            {
                "name": "wavemind-integration-admission",
                "private": True,
                "type": "module",
            }
        ),
        encoding="utf-8",
    )
    installed = _run(
        [npm, "install", "--ignore-scripts", str(tarball)],
        cwd=consumer,
        timeout=120,
    )
    if installed.returncode != 0:
        raise RuntimeError(f"packed SDK install failed: {installed.stderr.strip()}")

    port = _free_port()
    env = os.environ.copy()
    env["PYTHONPATH"] = os.pathsep.join(
        value
        for value in (str(root), env.get("PYTHONPATH", ""))
        if value
    )
    env["WAVEMIND_COMMIT_SHA"] = source_sha
    server = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "wavemind",
            "--db",
            str(temporary_root / "typescript-live.db"),
            "serve",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
        ],
        cwd=temporary_root,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
    )
    try:
        _wait_for_health(port, server)
        script = consumer / "live-contract.mjs"
        script.write_text(_typescript_contract_script(port), encoding="utf-8")
        result = _run([node, str(script)], cwd=consumer, timeout=120)
        if result.returncode != 0:
            raise RuntimeError(
                "TypeScript live contract failed: "
                + (result.stderr.strip() or result.stdout.strip())
            )
        payload = json.loads(result.stdout)
        return {
            "packed_install": True,
            **payload,
            "_passed": all(
                (
                    payload["live_memory_lifecycle"],
                    payload["safe_retry"],
                    payload["mutation_not_retried"],
                    payload["cancellation"],
                    payload["concurrent_explanations"] >= 16,
                )
            ),
        }
    finally:
        server.terminate()
        try:
            server.wait(timeout=10)
        except subprocess.TimeoutExpired:
            server.kill()
            server.wait(timeout=5)


def _typescript_contract_script(port: int) -> str:
    return f"""
import {{ WaveMindClient, WaveMindHTTPError }} from "@wavemind/http";

const baseUrl = "http://127.0.0.1:{port}";
const memory = new WaveMindClient({{ baseUrl, retryBaseDelayMs: 0 }});
const remembered = await memory.remember({{
  text: "The integration deployment uses a canary.",
  namespace: "integration",
  metadata: {{ provenance: {{ source: "typescript", id: "ts-1" }} }},
}});
const queried = await memory.query({{
  text: "integration deployment canary",
  namespace: "integration",
  top_k: 1,
}});
await memory.feedback({{
  id: remembered.id,
  namespace: "integration",
  useful: true,
}});
const explained = await memory.explainMemory(
  remembered.id,
  "integration",
);
const concurrent = await Promise.all(
  Array.from({{ length: 16 }}, () =>
    memory.explainMemory(remembered.id, "integration"),
  ),
);

let retryAttempts = 0;
const retrying = new WaveMindClient({{
  baseUrl,
  retryBaseDelayMs: 0,
  fetch: async (url, init) => {{
    retryAttempts += 1;
    if (retryAttempts === 1) {{
      return new Response(JSON.stringify({{ detail: "busy" }}), {{
        status: 503,
        headers: {{ "content-type": "application/json" }},
      }});
    }}
    return fetch(url, init);
  }},
}});
await retrying.query({{
  text: "integration deployment canary",
  namespace: "integration",
  top_k: 1,
}});

let mutationAttempts = 0;
const mutation = new WaveMindClient({{
  baseUrl,
  maxRetries: 4,
  retryBaseDelayMs: 0,
  fetch: async () => {{
    mutationAttempts += 1;
    return new Response(JSON.stringify({{ detail: "busy" }}), {{
      status: 503,
      headers: {{ "content-type": "application/json" }},
    }});
  }},
}});
try {{
  await mutation.remember({{ text: "must not duplicate" }});
}} catch (error) {{
  if (!(error instanceof WaveMindHTTPError)) throw error;
}}

let cancelled = false;
const controller = new AbortController();
const cancellable = new WaveMindClient({{
  baseUrl,
  fetch: async (_url, init) =>
    new Promise((_resolve, reject) => {{
      init.signal.addEventListener(
        "abort",
        () => reject(init.signal.reason),
        {{ once: true }},
      );
    }}),
}});
const pending = cancellable.query(
  {{ text: "cancel" }},
  {{ signal: controller.signal }},
);
controller.abort(new Error("cancelled by admission"));
try {{
  await pending;
}} catch (error) {{
  cancelled = String(error).includes("cancelled by admission");
}}

const forgotten = await memory.forget({{
  id: remembered.id,
  namespace: "integration",
}});
const after = await memory.query({{
  text: "integration deployment canary",
  namespace: "integration",
  top_k: 1,
}});
console.log(JSON.stringify({{
  live_memory_lifecycle:
    queried.results[0]?.id === remembered.id &&
    explained.schema === "wavemind.memory_explanation.v1" &&
    explained.provenance.id === "ts-1" &&
    forgotten.deleted === 1 &&
    after.results.length === 0,
  safe_retry: retryAttempts === 2,
  mutation_not_retried: mutationAttempts === 1,
  cancellation: cancelled,
  concurrent_explanations: concurrent.filter(
    (item) => item.id === remembered.id,
  ).length,
}}));
""".strip()


def _seed_experience() -> ExperienceRecord:
    return ExperienceRecord.create(
        id="exp_integration",
        kind=ExperienceKind.PROCEDURE,
        title="Recover a failed deployment",
        content="Inspect health and logs, then roll back the failing release.",
        namespace="agent",
        confidence=0.97,
        trust=TrustClass.VERIFIED_OPERATOR,
        status=ExperienceStatus.ACTIVE,
        source=ExperienceSource(
            provider="integration-admission",
            source_type="verified_run",
            source_id="run-1",
        ),
    )


def _capture_case(
    case_id: str,
    operation: Callable[[], dict[str, Any]],
) -> dict[str, Any]:
    try:
        evidence = operation()
        passed = bool(evidence.pop("_passed", True))
        return {
            "id": case_id,
            "passed": passed,
            "status": "pass" if passed else "action_required",
            "evidence": evidence,
            "issue": "" if passed else f"{case_id} did not meet its contract",
        }
    except Exception as exc:
        return {
            "id": case_id,
            "passed": False,
            "status": "action_required",
            "evidence": {
                "error_type": type(exc).__name__,
                "error": str(exc),
            },
            "issue": f"{case_id} failed: {type(exc).__name__}: {exc}",
        }


def _run(
    command: list[str],
    *,
    cwd: Path,
    timeout: float,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=cwd,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=timeout,
    )


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _wait_for_health(port: int, server: subprocess.Popen[str]) -> None:
    deadline = time.monotonic() + 30.0
    url = f"http://127.0.0.1:{port}/healthz"
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    while time.monotonic() < deadline:
        if server.poll() is not None:
            _, stderr = server.communicate(timeout=5)
            raise RuntimeError(f"WaveMind API stopped before health: {stderr}")
        try:
            with opener.open(url, timeout=1) as response:
                if response.status == 200:
                    return
        except OSError:
            time.sleep(0.1)
    raise TimeoutError("WaveMind API did not become healthy within 30 seconds")


def _environment() -> dict[str, Any]:
    provider_modules = {
        module: _module_available(module) for module in _REQUIRED_MODULES
    }
    payload = {
        "python": platform.python_version(),
        "implementation": platform.python_implementation(),
        "platform": platform.platform(),
        "node": _tool_version("node", "--version"),
        "npm": _tool_version(
            "npm.cmd" if os.name == "nt" else "npm",
            "--version",
        ),
        "provider_modules": provider_modules,
    }
    payload["fingerprint_sha256"] = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return payload


def _module_available(module: str) -> bool:
    try:
        return importlib.util.find_spec(module) is not None
    except (ImportError, ModuleNotFoundError, ValueError):
        return False


def _tool_version(executable: str, flag: str) -> str:
    path = shutil.which(executable)
    if path is None:
        return "missing"
    try:
        return subprocess.check_output(
            [path, flag],
            text=True,
            encoding="utf-8",
            timeout=10,
        ).strip()
    except (OSError, subprocess.SubprocessError):
        return "unavailable"


def _suite_fingerprint() -> str:
    raw = json.dumps(
        {
            "revision": INTEGRATION_SUITE_REVISION,
            "required_cases": _REQUIRED_CASES,
            "required_modules": _REQUIRED_MODULES,
            "contract": _SUITE_CONTRACT,
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    return hashlib.sha256(raw).hexdigest()


def _verdict_fingerprint(payload: dict[str, Any]) -> str:
    rows = [
        {
            "id": case["id"],
            "passed": case["passed"],
            "status": case["status"],
        }
        for case in payload["cases"]
    ]
    return hashlib.sha256(
        json.dumps(rows, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _git_sha(root: Path) -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            cwd=root,
            text=True,
            encoding="utf-8",
            timeout=10,
        ).strip()
    except (OSError, subprocess.SubprocessError):
        return ""


def _check(
    check_id: str,
    passed: bool,
    evidence: Any,
    target: Any,
    issue: str,
) -> dict[str, Any]:
    return {
        "id": check_id,
        "passed": bool(passed),
        "status": "pass" if passed else "action_required",
        "evidence": evidence,
        "target": target,
        "issue": "" if passed else issue,
    }


def _compact(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":")).replace(
        "|", "/"
    )


def _utc_now() -> str:
    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )

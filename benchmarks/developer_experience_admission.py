from __future__ import annotations

import argparse
import json
import os
import platform
import shutil
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from wavemind.onboarding import initialize_project, run_doctor


def _source_sha() -> str:
    return subprocess.check_output(
        ["git", "rev-parse", "HEAD"],
        cwd=PROJECT_ROOT,
        text=True,
        encoding="utf-8",
    ).strip()


def _run(
    command: list[str],
    *,
    cwd: Path,
    env: dict[str, str] | None = None,
    timeout: float = 60.0,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=cwd,
        env=env,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=timeout,
    )


def _check(
    check_id: str,
    passed: bool,
    evidence: Any,
    target: Any,
) -> dict[str, Any]:
    return {
        "id": check_id,
        "passed": bool(passed),
        "status": "pass" if passed else "action_required",
        "evidence": evidence,
        "target": target,
    }


def run_admission() -> dict[str, Any]:
    started = time.perf_counter()
    checks: list[dict[str, Any]] = []
    per_case: list[dict[str, Any]] = []
    with tempfile.TemporaryDirectory(prefix="wavemind-dx-admission-") as temp:
        root = Path(temp)
        projects: dict[str, Path] = {}
        manifests: dict[str, dict[str, Any]] = {}
        for template in ("python", "typescript", "mcp", "docker"):
            project = root / template
            case_started = time.perf_counter()
            payload = initialize_project(
                project,
                template=template,
                name=f"admission-{template}",
            )
            elapsed_ms = (time.perf_counter() - case_started) * 1000.0
            projects[template] = project
            manifests[template] = payload
            per_case.append(
                {
                    "case": f"init-{template}",
                    "passed": payload["status"] == "created",
                    "latency_ms": elapsed_ms,
                    "files": payload["files"],
                }
            )
        checks.append(
            _check(
                "starter-templates",
                set(projects) == {"python", "typescript", "mcp", "docker"},
                {
                    template: manifests[template]["files"]
                    for template in sorted(manifests)
                },
                "Python, TypeScript, MCP, and Docker starters",
            )
        )

        env = os.environ.copy()
        existing = env.get("PYTHONPATH")
        env["PYTHONPATH"] = (
            str(PROJECT_ROOT)
            if not existing
            else os.pathsep.join((str(PROJECT_ROOT), existing))
        )
        packet_runs: list[dict[str, Any]] = []
        for run_number in (1, 2):
            run_started = time.perf_counter()
            result = _run(
                [sys.executable, "app.py"],
                cwd=projects["python"],
                env=env,
            )
            elapsed_ms = (time.perf_counter() - run_started) * 1000.0
            packet = json.loads(result.stdout) if result.returncode == 0 else {}
            packet_runs.append(
                {
                    "run": run_number,
                    "returncode": result.returncode,
                    "latency_ms": elapsed_ms,
                    "schema": packet.get("schema"),
                    "item_count": len(packet.get("items") or []),
                    "citations": packet.get("citations") or [],
                    "stderr": result.stderr.strip(),
                }
            )
        first_packet_seconds = packet_runs[0]["latency_ms"] / 1000.0
        checks.append(
            _check(
                "first-experience-packet",
                (
                    packet_runs[0]["returncode"] == 0
                    and packet_runs[0]["schema"] == "wavemind.experience_packet.v1"
                    and packet_runs[0]["item_count"] == 1
                    and first_packet_seconds <= 300.0
                ),
                packet_runs[0],
                "one cited Experience Packet within 300 seconds",
            )
        )
        checks.append(
            _check(
                "persistent-idempotent-packet",
                (
                    packet_runs[1]["returncode"] == 0
                    and packet_runs[1]["item_count"] == 1
                    and packet_runs[1]["citations"] == packet_runs[0]["citations"]
                ),
                packet_runs,
                "second run returns the same single citation",
            )
        )

        doctor = run_doctor(projects["python"])
        checks.append(
            _check(
                "doctor",
                doctor["status"] == "pass"
                and doctor["summary"]["required_failed"] == 0,
                doctor["summary"],
                "all required diagnostics pass",
            )
        )

        unrelated = projects["python"] / "user-notes.txt"
        unrelated.write_text("preserve", encoding="utf-8")
        overwrite_blocked = False
        try:
            initialize_project(projects["python"], template="python")
        except FileExistsError:
            overwrite_blocked = True
        initialize_project(projects["python"], template="python", force=True)
        checks.append(
            _check(
                "safe-overwrite",
                overwrite_blocked
                and unrelated.read_text(encoding="utf-8") == "preserve",
                {
                    "overwrite_blocked": overwrite_blocked,
                    "unrelated_file_preserved": unrelated.exists(),
                },
                "default refusal and unrelated-file preservation with --force",
            )
        )

        python_compile = _run(
            [sys.executable, "-m", "py_compile", "app.py"],
            cwd=projects["python"],
        )
        mcp_compile = _run(
            [sys.executable, "-m", "py_compile", "experience_mcp.py"],
            cwd=projects["mcp"],
        )
        checks.append(
            _check(
                "python-mcp-syntax",
                python_compile.returncode == 0 and mcp_compile.returncode == 0,
                {
                    "python_returncode": python_compile.returncode,
                    "mcp_returncode": mcp_compile.returncode,
                },
                "both generated Python entrypoints compile",
            )
        )

        node = shutil.which("node")
        typescript_source = projects["typescript"] / "src" / "index.ts"
        module_source = projects["typescript"] / "starter-check.mjs"
        module_source.write_text(
            typescript_source.read_text(encoding="utf-8"),
            encoding="utf-8",
        )
        node_check = (
            _run([node, "--check", str(module_source)], cwd=projects["typescript"])
            if node
            else None
        )
        checks.append(
            _check(
                "typescript-syntax",
                node_check is not None and node_check.returncode == 0,
                {
                    "node": node or "missing",
                    "returncode": node_check.returncode if node_check else None,
                    "stderr": node_check.stderr.strip() if node_check else "",
                },
                "Node parses the generated ESM-compatible TypeScript starter",
            )
        )

        docker = shutil.which("docker")
        compose_check = (
            _run(
                [docker, "compose", "config", "--quiet"],
                cwd=projects["docker"],
            )
            if docker
            else None
        )
        checks.append(
            _check(
                "docker-compose-config",
                compose_check is not None and compose_check.returncode == 0,
                {
                    "docker": docker or "missing",
                    "returncode": (
                        compose_check.returncode if compose_check else None
                    ),
                    "stderr": compose_check.stderr.strip() if compose_check else "",
                },
                "generated one-command Docker starter has valid Compose config",
            )
        )

    passed = sum(check["passed"] for check in checks)
    return {
        "schema": "wavemind.developer_experience_admission.v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source_sha": _source_sha(),
        "status": "admitted" if passed == len(checks) else "blocked",
        "admitted": passed == len(checks),
        "environment": {
            "python": platform.python_version(),
            "platform": platform.platform(),
            "node": shutil.which("node"),
            "docker": shutil.which("docker"),
        },
        "summary": {
            "checks_passed": passed,
            "checks_total": len(checks),
            "first_packet_seconds": first_packet_seconds,
            "total_seconds": time.perf_counter() - started,
        },
        "checks": checks,
        "per_case": per_case,
        "claim_boundary": (
            "Local clean-project onboarding and syntax/configuration evidence. "
            "The generated Docker runtime is exercised separately by full-check CI."
        ),
    }


def render_markdown(payload: dict[str, Any]) -> str:
    summary = payload["summary"]
    lines = [
        "# WaveMind Developer Experience Admission",
        "",
        f"- Status: **{payload['status']}**",
        f"- Source SHA: `{payload['source_sha']}`",
        (
            f"- Checks: **{summary['checks_passed']}/"
            f"{summary['checks_total']}**"
        ),
        f"- First Experience Packet: **{summary['first_packet_seconds']:.3f}s**",
        "",
        "| Check | Status | Target |",
        "|---|---:|---|",
    ]
    for check in payload["checks"]:
        lines.append(
            f"| `{check['id']}` | `{check['status']}` | {check['target']} |"
        )
    lines.extend(["", f"> {payload['claim_boundary']}", ""])
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("benchmarks/developer_experience_admission_results.json"),
    )
    parser.add_argument(
        "--markdown-output",
        type=Path,
        default=Path("benchmarks/DEVELOPER_EXPERIENCE_ADMISSION.md"),
    )
    parser.add_argument("--fail-on-blocked", action="store_true")
    args = parser.parse_args()
    payload = run_admission()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    args.markdown_output.parent.mkdir(parents=True, exist_ok=True)
    args.markdown_output.write_text(
        render_markdown(payload),
        encoding="utf-8",
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 2 if args.fail_on_blocked and not payload["admitted"] else 0


if __name__ == "__main__":
    raise SystemExit(main())

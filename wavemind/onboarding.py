from __future__ import annotations

import json
import platform
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from . import __version__
from .encoders import HashingTextEncoder
from .experience import (
    ExperienceRecord,
    ExperienceSource,
    ExperienceStatus,
    SQLiteExperienceStore,
    TrustClass,
)
from .experience_compiler import ExperienceCompiler
from .memory_firewall import FirewallContext, MemoryFirewall, MemoryFirewallPolicy


PROJECT_SCHEMA = "wavemind.project.v1"
DOCTOR_SCHEMA = "wavemind.doctor.v1"
TEMPLATES = ("python", "typescript", "mcp", "docker")
_SAFE_NAME = re.compile(r"[^a-z0-9._-]+")


@dataclass(frozen=True)
class DoctorCheck:
    id: str
    status: str
    required: bool
    detail: str
    remediation: str = ""

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def _slug(value: str) -> str:
    normalized = _SAFE_NAME.sub("-", value.strip().lower()).strip("-._")
    if not normalized:
        raise ValueError("project name must contain a letter or number")
    return normalized[:80]


def _python_template(namespace: str) -> str:
    return f'''from __future__ import annotations

import json
from pathlib import Path

from wavemind import (
    ExperienceCompiler,
    ExperienceKind,
    ExperienceRecord,
    ExperienceSource,
    FirewallContext,
    MemoryFirewall,
    MemoryFirewallPolicy,
    SQLiteExperienceStore,
    TrustClass,
)


NAMESPACE = "{namespace}"
STATE_DIR = Path(__file__).resolve().parent / ".wavemind"
STATE_DIR.mkdir(exist_ok=True)

with SQLiteExperienceStore(STATE_DIR / "experience.sqlite3") as store:
    compiler = ExperienceCompiler(
        store,
        MemoryFirewall(MemoryFirewallPolicy(namespace=NAMESPACE)),
    )
    context = FirewallContext(namespace=NAMESPACE, actor="starter")
    experience_id = "starter-deploy-recovery"
    if store.get(experience_id) is None:
        record = ExperienceRecord.create(
            id=experience_id,
            namespace=NAMESPACE,
            kind=ExperienceKind.PROCEDURE,
            title="Recover a failed deployment",
            content="Check health and logs, then roll back the release if errors persist.",
            source=ExperienceSource(
                provider="starter",
                source_type="verified_trajectory",
                source_id="starter-run",
            ),
            confidence=0.9,
            trust=TrustClass.AGENT_GENERATED,
        )
        stored, _ = compiler.submit(record, context=context)
        for index in range(1, 4):
            compiler.review_candidate(
                stored.id,
                evidence_id=f"starter-success-{{index}}",
                successful=True,
                score=0.9,
                context=context,
            )

    packet = compiler.compile_packet(
        "How should I recover a failed deployment?",
        namespace=NAMESPACE,
        context=context,
        token_budget=220,
    )
    print(json.dumps(packet.as_dict(), indent=2))
'''


def _typescript_template(namespace: str) -> str:
    return f'''const baseUrl = process.env.WAVEMIND_URL ?? "http://127.0.0.1:8000";

const response = await fetch(`${{baseUrl}}/experience/packet`, {{
  method: "POST",
  headers: {{ "content-type": "application/json" }},
  body: JSON.stringify({{
    namespace: "{namespace}",
    query: "How should I recover a failed deployment?",
    token_budget: 220,
  }}),
}});

if (!response.ok) {{
  throw new Error(`WaveMind returned ${{response.status}}: ${{await response.text()}}`);
}}

console.log(JSON.stringify(await response.json(), null, 2));
'''


def _mcp_template(namespace: str) -> str:
    return f'''from __future__ import annotations

from pathlib import Path

from wavemind import ExperienceCompiler, MemoryFirewall, MemoryFirewallPolicy
from wavemind.experience import SQLiteExperienceStore
from wavemind.integrations.mcp_experience import build_experience_mcp_server


NAMESPACE = "{namespace}"
STATE_DIR = Path(__file__).resolve().parent / ".wavemind"
STATE_DIR.mkdir(exist_ok=True)
store = SQLiteExperienceStore(STATE_DIR / "experience.sqlite3")
compiler = ExperienceCompiler(
    store,
    MemoryFirewall(MemoryFirewallPolicy(namespace=NAMESPACE)),
)
server = build_experience_mcp_server(compiler)

try:
    server.run(transport="stdio")
finally:
    store.close()
'''


def _template_files(template: str, namespace: str) -> dict[str, str]:
    common = {
        ".gitignore": ".wavemind/\n.env\nnode_modules/\ndist/\n",
        ".env.example": "WAVEMIND_URL=http://127.0.0.1:8000\n",
    }
    if template == "python":
        return {
            **common,
            "app.py": _python_template(namespace),
            "requirements.txt": f"wavemind=={__version__}\n",
            "README.md": (
                "# WaveMind Python starter\n\n"
                "```bash\n"
                "python -m pip install -r requirements.txt\n"
                "python app.py\n"
                "```\n"
            ),
        }
    if template == "typescript":
        return {
            **common,
            "src/index.ts": _typescript_template(namespace),
            "package.json": json.dumps(
                {
                    "name": f"{namespace}-wavemind",
                    "private": True,
                    "type": "module",
                    "scripts": {
                        "build": "tsc -p tsconfig.json",
                        "start": "node dist/index.js",
                    },
                    "devDependencies": {"typescript": "5.9.3"},
                },
                indent=2,
            )
            + "\n",
            "tsconfig.json": json.dumps(
                {
                    "compilerOptions": {
                        "target": "ES2022",
                        "module": "NodeNext",
                        "moduleResolution": "NodeNext",
                        "outDir": "dist",
                        "strict": True,
                    },
                    "include": ["src/**/*.ts"],
                },
                indent=2,
            )
            + "\n",
            "README.md": (
                "# WaveMind TypeScript starter\n\n"
                "Start `wavemind serve`, then run:\n\n"
                "```bash\nnpm install\nnpm run build\nnpm start\n```\n"
            ),
        }
    if template == "mcp":
        return {
            **common,
            "experience_mcp.py": _mcp_template(namespace),
            "requirements.txt": f'wavemind[mcp]=={__version__}\n',
            "mcp.json": json.dumps(
                {
                    "mcpServers": {
                        "wavemind-experience": {
                            "command": sys.executable,
                            "args": ["experience_mcp.py"],
                        }
                    }
                },
                indent=2,
            )
            + "\n",
            "README.md": (
                "# WaveMind MCP starter\n\n"
                "Install `requirements.txt`, then point your MCP client at "
                "`mcp.json`.\n"
            ),
        }
    if template == "docker":
        return {
            **common,
            "Dockerfile": (
                "FROM python:3.11-slim\n"
                f"RUN python -m pip install --no-cache-dir wavemind=={__version__}\n"
                "WORKDIR /app\n"
                'CMD ["wavemind", "serve", "--host", "0.0.0.0", "--port", "8000"]\n'
            ),
            "compose.yaml": (
                "services:\n"
                "  wavemind:\n"
                "    build: .\n"
                "    ports:\n"
                '      - "${WAVEMIND_PORT:-8000}:8000"\n'
                "    volumes:\n"
                "      - ./data:/data\n"
                "    environment:\n"
                "      WAVEMIND_DB: /data/wavemind.sqlite3\n"
                "    healthcheck:\n"
                "      test:\n"
                "        - CMD\n"
                "        - python\n"
                "        - -c\n"
                "        - >-\n"
                "          import urllib.request;\n"
                "          urllib.request.urlopen('http://127.0.0.1:8000/stats')\n"
                "      interval: 2s\n"
                "      timeout: 2s\n"
                "      retries: 30\n"
                "    restart: unless-stopped\n"
            ),
            "README.md": (
                "# WaveMind Docker starter\n\n"
                "```bash\n"
                "docker compose up --build\n"
                "```\n"
            ),
        }
    raise ValueError(f"template must be one of: {', '.join(TEMPLATES)}")


def initialize_project(
    directory: str | Path,
    *,
    template: str = "python",
    name: str | None = None,
    force: bool = False,
) -> dict[str, Any]:
    if template not in TEMPLATES:
        raise ValueError(f"template must be one of: {', '.join(TEMPLATES)}")
    root = Path(directory).expanduser().resolve()
    project_name = _slug(name or root.name)
    root.mkdir(parents=True, exist_ok=True)
    files = _template_files(template, project_name)
    manifest_path = root / ".wavemind-project.json"
    targets = [root / relative for relative in files]
    targets.append(manifest_path)
    existing = [path for path in targets if path.exists()]
    if existing and not force:
        listed = ", ".join(path.relative_to(root).as_posix() for path in existing)
        raise FileExistsError(
            f"refusing to overwrite existing project files: {listed}; use --force"
        )
    for relative, content in files.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8", newline="\n")
    manifest = {
        "schema": PROJECT_SCHEMA,
        "name": project_name,
        "namespace": project_name,
        "template": template,
        "created_with": __version__,
        "files": sorted(files),
    }
    manifest_path.write_text(
        json.dumps(manifest, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return {
        "schema": PROJECT_SCHEMA,
        "status": "created",
        "root": str(root),
        "template": template,
        "name": project_name,
        "files": sorted([*files, ".wavemind-project.json"]),
        "next_command": _next_command(template),
    }


def _next_command(template: str) -> str:
    if template == "python":
        return "python app.py"
    if template == "typescript":
        return "npm install && npm run build && npm start"
    if template == "docker":
        return "docker compose up --build"
    return "python experience_mcp.py"


def _command_version(command: str, *args: str) -> str | None:
    executable = shutil.which(command)
    if executable is None:
        return None
    try:
        result = subprocess.run(
            [executable, *args],
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    output = (result.stdout or result.stderr).strip().splitlines()
    return output[0] if output else executable


def _experience_smoke() -> int:
    with SQLiteExperienceStore(":memory:") as store:
        namespace = "doctor"
        store.put(
            ExperienceRecord.create(
                id="doctor-smoke",
                namespace=namespace,
                kind="procedure",
                title="Doctor smoke",
                content="Use verified local evidence.",
                source=ExperienceSource(
                    provider="doctor",
                    source_type="self_test",
                ),
                trust=TrustClass.VERIFIED_OPERATOR,
                status=ExperienceStatus.ACTIVE,
            )
        )
        compiler = ExperienceCompiler(
            store,
            MemoryFirewall(MemoryFirewallPolicy(namespace=namespace)),
        )
        packet = compiler.compile_packet(
            "What evidence should I use?",
            namespace=namespace,
            context=FirewallContext(namespace=namespace, actor="doctor"),
            token_budget=96,
        )
        return len(packet.items)


def run_doctor(project: str | Path = ".") -> dict[str, Any]:
    root = Path(project).expanduser().resolve()
    checks: list[DoctorCheck] = []
    python_ok = sys.version_info >= (3, 10)
    checks.append(
        DoctorCheck(
            "python",
            "pass" if python_ok else "fail",
            True,
            platform.python_version(),
            "Install Python 3.10 or newer." if not python_ok else "",
        )
    )
    checks.append(DoctorCheck("wavemind", "pass", True, __version__))
    try:
        connection = sqlite3.connect(":memory:")
        connection.execute("select 1").fetchone()
        connection.close()
        checks.append(DoctorCheck("sqlite", "pass", True, sqlite3.sqlite_version))
    except sqlite3.Error as exc:
        checks.append(DoctorCheck("sqlite", "fail", True, str(exc)))
    if not root.exists() or not root.is_dir():
        checks.append(
            DoctorCheck(
                "project-directory",
                "fail",
                True,
                str(root),
                "Create the directory or pass --project with an existing directory.",
            )
        )
    else:
        try:
            with tempfile.TemporaryDirectory(prefix=".wavemind-doctor-", dir=root):
                pass
            checks.append(DoctorCheck("project-writable", "pass", True, str(root)))
        except OSError as exc:
            checks.append(
                DoctorCheck(
                    "project-writable",
                    "fail",
                    True,
                    str(exc),
                    "Grant write access to the project directory.",
                )
            )
    manifest_path = root / ".wavemind-project.json"
    if manifest_path.exists():
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            valid = (
                manifest.get("schema") == PROJECT_SCHEMA
                and manifest.get("template") in TEMPLATES
            )
            checks.append(
                DoctorCheck(
                    "project-manifest",
                    "pass" if valid else "fail",
                    True,
                    str(manifest_path),
                    "Run wavemind init again with --force." if not valid else "",
                )
            )
        except (OSError, json.JSONDecodeError) as exc:
            checks.append(
                DoctorCheck(
                    "project-manifest",
                    "fail",
                    True,
                    str(exc),
                    "Repair the JSON manifest or rerun wavemind init --force.",
                )
            )
    else:
        checks.append(
            DoctorCheck(
                "project-manifest",
                "warn",
                False,
                "not initialized",
                "Run wavemind init to create a starter project.",
            )
        )
    try:
        vector = HashingTextEncoder(vector_dim=32).encode_vector("doctor")
        checks.append(DoctorCheck("encoder", "pass", True, f"dimension={len(vector)}"))
    except Exception as exc:
        checks.append(DoctorCheck("encoder", "fail", True, str(exc)))
    try:
        packet_items = _experience_smoke()
        checks.append(
            DoctorCheck(
                "experience-packet",
                "pass" if packet_items == 1 else "fail",
                True,
                f"items={packet_items}",
            )
        )
    except Exception as exc:
        checks.append(DoctorCheck("experience-packet", "fail", True, str(exc)))
    node_version = _command_version("node", "--version")
    checks.append(
        DoctorCheck(
            "node",
            "pass" if node_version else "warn",
            False,
            node_version or "not installed",
        )
    )
    docker_cli = _command_version("docker", "--version")
    docker_engine = _command_version(
        "docker",
        "info",
        "--format",
        "{{.ServerVersion}}",
    )
    docker_ok = docker_cli is not None and docker_engine is not None
    checks.append(
        DoctorCheck(
            "docker",
            "pass" if docker_ok else "warn",
            False,
            (
                f"{docker_cli}; engine {docker_engine}"
                if docker_ok
                else (
                    f"{docker_cli}; engine unavailable"
                    if docker_cli
                    else "not installed"
                )
            ),
            "Start Docker Desktop or another Docker engine."
            if docker_cli and not docker_engine
            else "",
        )
    )
    try:
        import mcp  # noqa: F401

        mcp_detail = "installed"
        mcp_status = "pass"
    except ImportError:
        mcp_detail = "not installed"
        mcp_status = "warn"
    checks.append(
        DoctorCheck(
            "mcp",
            mcp_status,
            False,
            mcp_detail,
            'Install with: pip install "wavemind[mcp]"'
            if mcp_status == "warn"
            else "",
        )
    )
    failed = [check for check in checks if check.required and check.status == "fail"]
    return {
        "schema": DOCTOR_SCHEMA,
        "status": "pass" if not failed else "fail",
        "project": str(root),
        "checks": [check.as_dict() for check in checks],
        "summary": {
            "passed": sum(check.status == "pass" for check in checks),
            "warnings": sum(check.status == "warn" for check in checks),
            "failed": sum(check.status == "fail" for check in checks),
            "required_failed": len(failed),
        },
    }


def print_doctor(report: dict[str, Any]) -> None:
    for check in report["checks"]:
        marker = {"pass": "OK", "warn": "WARN", "fail": "FAIL"}[check["status"]]
        print(f"[{marker}] {check['id']}: {check['detail']}")
        if check["remediation"]:
            print(f"       {check['remediation']}")
    summary = report["summary"]
    print(
        f"doctor={report['status']} passed={summary['passed']} "
        f"warnings={summary['warnings']} failed={summary['failed']}"
    )

from __future__ import annotations

import json
import os
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
    created = False
    if store.get(experience_id) is None:
        created = True
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
    details = compiler.expand(
        (item.experience_id for item in packet.items),
        namespace=NAMESPACE,
        context=context,
    )
    remembered = store.get(experience_id)
    assert remembered is not None
    print(json.dumps({{
        "schema": "wavemind.onboarding.python.v1",
        "remember": {{
            "created": created,
            "experience_id": remembered.id,
        }},
        "recall": packet.as_dict(),
        "verification": {{
            "status": remembered.status.value,
            "evidence_ids": [f"starter-success-{{index}}" for index in range(1, 4)],
        }},
        "explain": [detail.__dict__ for detail in details],
        "persistence": {{
            "database": str(STATE_DIR / "experience.sqlite3"),
        }},
    }}, indent=2))
'''


def _typescript_template(namespace: str) -> str:
    return f'''import {{ WaveMindClient }} from "@wavemind/http";


// @ts-ignore - Node exposes process at runtime without requiring @types/node.
const runtimeEnv = globalThis.process?.env ?? {{}};
const baseUrl = runtimeEnv.WAVEMIND_URL ?? "http://127.0.0.1:8000";
const namespace = "{namespace}";
const text = "Production deployments use a canary before full rollout.";
const query = "How should production deployments roll out?";
const client = new WaveMindClient({{ baseUrl }});

let recalled = await client.query({{ text: query, namespace, top_k: 5 }});
let memory = recalled.results.find((item) => item.text === text);
let created = false;
if (memory === undefined) {{
  const remembered = await client.remember({{
    text,
    namespace,
    tags: ["deployment", "verified"],
    metadata: {{
      provenance: {{ source: "typescript-onboarding" }},
    }},
  }});
  created = true;
  recalled = await client.query({{ text: query, namespace, top_k: 5 }});
  memory = recalled.results.find((item) => item.id === remembered.id);
}}

if (memory === undefined) {{
  throw new Error("The remembered deployment fact was not recalled");
}}
const expectedId = runtimeEnv.WAVEMIND_EXPECT_ID;
if (expectedId !== undefined && memory.id !== Number(expectedId)) {{
  throw new Error(`Expected persisted memory ${{expectedId}}, received ${{memory.id}}`);
}}

const feedback = await client.feedback({{
  id: memory.id,
  namespace,
  useful: true,
  strength: 0.5,
  query,
  reason: "The onboarding verifier recalled the expected deployment fact",
}});
const explanation = await client.explainMemory(memory.id, namespace);

console.log(JSON.stringify({{
  schema: "wavemind.onboarding.typescript.v1",
  remember: {{ created, id: memory.id }},
  recall: {{ id: memory.id, text: memory.text, score: memory.score }},
  feedback,
  explain: explanation,
}}, null, 2));
'''


def _typescript_runner_template() -> str:
    return """import { spawn, spawnSync } from "node:child_process";
import { access, copyFile, lstat, mkdir, readFile, rm, unlink } from "node:fs/promises";
import net from "node:net";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";


const root = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const packageJson = JSON.parse(await readFile(resolve(root, "package.json"), "utf8"));
const dependency = packageJson.dependencies?.["@wavemind/http"];
if (typeof dependency !== "string" || !dependency.startsWith("file:")) {
  throw new Error("@wavemind/http must reference the repository-local package");
}
const sdkRoot = resolve(root, dependency.slice("file:".length));
const npmCli = process.env.npm_execpath;
if (!npmCli) {
  throw new Error("Run this flow through: npm run quickstart");
}

function run(command, args, options = {}) {
  const result = spawnSync(command, args, {
    cwd: options.cwd ?? root,
    env: { ...process.env, ...(options.env ?? {}) },
    encoding: "utf8",
    windowsHide: true,
  });
  if (result.status !== 0) {
    process.stderr.write(result.stdout ?? "");
    process.stderr.write(result.stderr ?? "");
    throw new Error(`${command} ${args.join(" ")} exited with ${result.status}`);
  }
  return result.stdout;
}

function runNpm(args, cwd) {
  run(process.execPath, [npmCli, ...args], { cwd });
}

async function prepareLocalSdk() {
  const compiler = resolve(sdkRoot, "node_modules", "typescript", "bin", "tsc");
  try {
    await access(compiler);
  } catch {
    runNpm(["ci"], sdkRoot);
  }
  try {
    await access(resolve(sdkRoot, "dist", "index.js"));
    await access(resolve(sdkRoot, "dist", "index.d.ts"));
  } catch {
    run(process.execPath, [compiler, "-p", resolve(sdkRoot, "tsconfig.json")], { cwd: sdkRoot });
  }
  const packageLink = resolve(root, "node_modules", "@wavemind", "http");
  try {
    const existing = await lstat(packageLink);
    if (existing.isSymbolicLink()) {
      await unlink(packageLink);
    } else {
      await rm(packageLink, { recursive: true, force: true });
    }
  } catch (error) {
    if (error?.code !== "ENOENT") throw error;
  }
  await mkdir(resolve(packageLink, "dist"), { recursive: true });
  await copyFile(resolve(sdkRoot, "package.json"), resolve(packageLink, "package.json"));
  await copyFile(resolve(sdkRoot, "dist", "index.js"), resolve(packageLink, "dist", "index.js"));
  await copyFile(resolve(sdkRoot, "dist", "index.d.ts"), resolve(packageLink, "dist", "index.d.ts"));
  run(process.execPath, [compiler, "-p", resolve(root, "tsconfig.json")], { cwd: root });
}

async function availablePort() {
  return new Promise((resolvePort, reject) => {
    const probe = net.createServer();
    probe.once("error", reject);
    probe.listen(0, "127.0.0.1", () => {
      const address = probe.address();
      if (address === null || typeof address === "string") {
        reject(new Error("Unable to allocate a local port"));
        return;
      }
      probe.close(() => resolvePort(address.port));
    });
  });
}

async function startServer(database) {
  const port = await availablePort();
  const python = process.env.PYTHON ?? (process.platform === "win32" ? "python" : "python3");
  const server = spawn(
    python,
    ["-m", "wavemind", "serve", "--host", "127.0.0.1", "--port", String(port)],
    {
      cwd: root,
      env: {
        ...process.env,
        WAVEMIND_DB: database,
        OPENBLAS_NUM_THREADS: "1",
        OMP_NUM_THREADS: "1",
        MKL_NUM_THREADS: "1",
      },
      stdio: ["ignore", "pipe", "pipe"],
      windowsHide: true,
    },
  );
  let diagnostics = "";
  server.stdout.on("data", (chunk) => { diagnostics += chunk.toString(); });
  server.stderr.on("data", (chunk) => { diagnostics += chunk.toString(); });
  const baseUrl = `http://127.0.0.1:${port}`;
  for (let attempt = 0; attempt < 120; attempt += 1) {
    if (server.exitCode !== null) {
      throw new Error(`WaveMind server exited before readiness:\n${diagnostics}`);
    }
    try {
      const response = await fetch(`${baseUrl}/stats`);
      if (response.ok) return { server, baseUrl };
    } catch {
      // The socket is expected to refuse connections while uvicorn starts.
    }
    await new Promise((resolveWait) => setTimeout(resolveWait, 100));
  }
  server.kill();
  throw new Error(`WaveMind server did not become ready:\n${diagnostics}`);
}

async function stopServer(server) {
  if (server.exitCode !== null) return;
  const exited = new Promise((resolveExit) => server.once("exit", resolveExit));
  server.kill();
  await Promise.race([
    exited,
    new Promise((_, reject) => setTimeout(() => reject(new Error("WaveMind server did not stop")), 5000)),
  ]);
}

function runClient(baseUrl, expectedId) {
  const env = { WAVEMIND_URL: baseUrl };
  if (expectedId !== undefined) env.WAVEMIND_EXPECT_ID = String(expectedId);
  return JSON.parse(run(process.execPath, [resolve(root, "dist", "index.js")], { env }));
}

await prepareLocalSdk();
await mkdir(resolve(root, ".wavemind"), { recursive: true });
const database = resolve(root, ".wavemind", "memory.sqlite3");

let active;
try {
  active = await startServer(database);
  const first = runClient(active.baseUrl);
  await stopServer(active.server);
  active = await startServer(database);
  const restarted = runClient(active.baseUrl, first.remember.id);
  console.log(JSON.stringify({
    schema: "wavemind.onboarding.typescript.restart.v1",
    first,
    restarted,
    persistence: {
      same_memory_id: first.remember.id === restarted.remember.id,
      server_restarted: true,
    },
  }, null, 2));
} finally {
  if (active !== undefined) await stopServer(active.server);
}
"""


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


def _mcp_verification_template(namespace: str) -> str:
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
from wavemind.integrations.mcp_experience import ExperienceMCPAdapter


NAMESPACE = "{namespace}"
STATE_DIR = Path(__file__).resolve().parent / ".wavemind"
STATE_DIR.mkdir(exist_ok=True)

with SQLiteExperienceStore(STATE_DIR / "experience.sqlite3") as store:
    compiler = ExperienceCompiler(
        store,
        MemoryFirewall(MemoryFirewallPolicy(namespace=NAMESPACE)),
    )
    context = FirewallContext(namespace=NAMESPACE, actor="mcp_onboarding")
    experience_id = "mcp-deploy-verification"
    created = False
    if store.get(experience_id) is None:
        created = True
        candidate, _ = compiler.submit(
            ExperienceRecord.create(
                id=experience_id,
                namespace=NAMESPACE,
                kind=ExperienceKind.PROCEDURE,
                title="Verify a deployment",
                content="Check service health after deployment and roll back on failure.",
                source=ExperienceSource(
                    provider="mcp",
                    source_type="verified_trajectory",
                    source_id="mcp-onboarding",
                ),
                confidence=0.9,
                trust=TrustClass.AGENT_GENERATED,
            ),
            context=context,
        )
        for index in range(1, 4):
            compiler.review_candidate(
                candidate.id,
                evidence_id=f"mcp-health-check-{{index}}",
                successful=True,
                score=0.95,
                context=context,
            )

    adapter = ExperienceMCPAdapter(compiler)
    packet = adapter.call_tool(
        "compile_experience_packet",
        {{
            "query": "How should I verify a deployment?",
            "namespace": NAMESPACE,
            "token_budget": 220,
            "top_k": 3,
        }},
    )
    explanation = adapter.call_tool(
        "expand_experience",
        {{
            "experience_ids": [item["experience_id"] for item in packet["items"]],
            "namespace": NAMESPACE,
        }},
    )
    remembered = store.get(experience_id)
    assert remembered is not None
    print(json.dumps({{
        "schema": "wavemind.onboarding.mcp.v1",
        "remember": {{"created": created, "experience_id": remembered.id}},
        "recall": packet,
        "verification": {{
            "status": remembered.status.value,
            "evidence_ids": [f"mcp-health-check-{{index}}" for index in range(1, 4)],
        }},
        "explain": explanation,
        "persistence": {{"database": str(STATE_DIR / "experience.sqlite3")}},
    }}, indent=2))
'''


def _typescript_sdk_dependency(root: Path) -> str:
    sdk_root = Path(__file__).resolve().parents[1] / "sdk" / "typescript"
    package_path = sdk_root / "package.json"
    if not package_path.is_file():
        raise RuntimeError(
            "TypeScript onboarding requires the repository-local sdk/typescript package"
        )
    try:
        selected = Path(os.path.relpath(sdk_root, start=root)).as_posix()
    except ValueError:
        selected = sdk_root.as_posix()
    return f"file:{selected}"


def _docker_verification_template(namespace: str) -> str:
    return f'''from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request


BASE_URL = os.environ.get("WAVEMIND_URL", "http://wavemind:8000")
API_KEY = os.environ.get("WAVEMIND_API_KEY", "local-quickstart-key")
NAMESPACE = "{namespace}"


def request(method: str, path: str, payload: dict | None = None) -> dict:
    body = None if payload is None else json.dumps(payload).encode("utf-8")
    call = urllib.request.Request(
        f"{{BASE_URL}}{{path}}",
        data=body,
        method=method,
        headers={{
            "Authorization": f"Bearer {{API_KEY}}",
            "Content-Type": "application/json",
        }},
    )
    with urllib.request.urlopen(call, timeout=10) as response:
        return json.loads(response.read().decode("utf-8"))


def wait_ready() -> None:
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        try:
            request("GET", "/healthz")
            return
        except (OSError, urllib.error.URLError):
            time.sleep(0.5)
    raise RuntimeError("WaveMind API did not become ready within 60 seconds")


wait_ready()
remembered = request("POST", "/remember", {{
    "text": "Verified Docker deployments persist memory across restarts.",
    "namespace": NAMESPACE,
    "idempotency_key": "docker-quickstart-memory",
    "metadata": {{"provenance": {{"source": "docker-onboarding"}}}},
}})
recalled = request("POST", "/query", {{
    "text": "How do verified Docker deployments retain memory?",
    "namespace": NAMESPACE,
    "top_k": 3,
}})
matches = [item for item in recalled["results"] if item["id"] == remembered["id"]]
if not matches:
    raise RuntimeError("remembered Docker memory was not recalled")
feedback = request("POST", "/feedback", {{
    "id": remembered["id"],
    "namespace": NAMESPACE,
    "useful": True,
    "strength": 0.5,
    "query": "How do verified Docker deployments retain memory?",
    "reason": "quickstart verification",
}})
explain = request(
    "GET",
    f"/memories/{{remembered['id']}}/explain?namespace={{NAMESPACE}}",
)
print(json.dumps({{
    "schema": "wavemind.onboarding.docker.v1",
    "remember": remembered,
    "recall": matches[0],
    "feedback": feedback,
    "explain": explain,
}}, indent=2))
'''


def _template_files(template: str, namespace: str, *, root: Path) -> dict[str, str]:
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
        sdk_dependency = _typescript_sdk_dependency(root)
        return {
            **common,
            "src/index.ts": _typescript_template(namespace),
            "scripts/quickstart.mjs": _typescript_runner_template(),
            "package.json": json.dumps(
                {
                    "name": f"{namespace}-wavemind",
                    "private": True,
                    "type": "module",
                    "scripts": {
                        "build": "tsc -p tsconfig.json",
                        "start": "node dist/index.js",
                        "quickstart": "node scripts/quickstart.mjs",
                    },
                    "dependencies": {"@wavemind/http": sdk_dependency},
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
                "From a Python environment with this WaveMind checkout installed, run:\n\n"
                "```bash\nnpm run quickstart\n```\n\n"
                "The command builds the repository-local `@wavemind/http` package, "
                "starts and stops the required server, and verifies SQLite state "
                "after a server restart.\n"
            ),
        }
    if template == "mcp":
        return {
            **common,
            "experience_mcp.py": _mcp_template(namespace),
            "verify_flow.py": _mcp_verification_template(namespace),
            "requirements.txt": f"wavemind[mcp]=={__version__}\n",
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
                "```bash\n"
                "python -m pip install -r requirements.txt\n"
                "python verify_flow.py\n"
                "```\n\n"
                "The verification flow persists recalled and expanded experience. "
                "Point your MCP client at `mcp.json` to use the same store.\n"
            ),
        }
    if template == "docker":
        return {
            **common,
            "verify_flow.py": _docker_verification_template(namespace),
            "Dockerfile": (
                "FROM python:3.11-slim\n"
                f"RUN python -m pip install --no-cache-dir wavemind=={__version__}\n"
                "WORKDIR /app\n"
                'CMD ["wavemind", "serve", "--host", "0.0.0.0", "--port", "8000", "--allow-public"]\n'
            ),
            "compose.yaml": (
                "services:\n"
                "  wavemind:\n"
                "    image: ${WAVEMIND_IMAGE:-wavemind-quickstart:local}\n"
                "    build: .\n"
                "    command: [\"wavemind\", \"serve\", \"--host\", \"0.0.0.0\", \"--port\", \"8000\", \"--allow-public\"]\n"
                "    ports:\n"
                '      - "127.0.0.1:${WAVEMIND_PORT:-8000}:8000"\n'
                "    volumes:\n"
                "      - ./data:/data\n"
                "    environment:\n"
                "      WAVEMIND_DB: /data/wavemind.sqlite3\n"
                "      WAVEMIND_EXPERIENCE_DB: /data/wavemind-experience.sqlite3\n"
                "      WAVEMIND_API_PRINCIPALS: >-\n"
                f'        {{"local-quickstart-key":{{"identity":"local-quickstart","role":"admin","namespace_prefixes":["{namespace}"]}}}}\n'
                "    healthcheck:\n"
                "      test:\n"
                "        - CMD\n"
                "        - python\n"
                "        - -c\n"
                "        - >-\n"
                "          import urllib.request;\n"
                "          request=urllib.request.Request('http://127.0.0.1:8000/stats?namespace="
                f"{namespace}',headers={{'Authorization':'Bearer local-quickstart-key'}});\n"
                "          urllib.request.urlopen(request)\n"
                "      interval: 2s\n"
                "      timeout: 2s\n"
                "      retries: 30\n"
                "    restart: unless-stopped\n"
                "  verify:\n"
                "    image: ${WAVEMIND_IMAGE:-wavemind-quickstart:local}\n"
                "    build: .\n"
                "    depends_on:\n"
                "      wavemind:\n"
                "        condition: service_healthy\n"
                "    environment:\n"
                "      WAVEMIND_URL: http://wavemind:8000\n"
                "      WAVEMIND_API_KEY: local-quickstart-key\n"
                "    volumes:\n"
                "      - ./verify_flow.py:/client/verify_flow.py:ro\n"
                "    command: [\"python\", \"/client/verify_flow.py\"]\n"
            ),
            "README.md": (
                "# WaveMind Docker starter\n\n"
                "```bash\n"
                "docker compose up -d --build\n"
                "docker compose run --rm verify\n"
                "docker compose restart wavemind\n"
                "docker compose run --rm verify\n"
                "```\n\n"
                "The second verification reuses the same memory ID after restart.\n"
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
    files = _template_files(template, project_name, root=root)
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
        return "npm run quickstart"
    if template == "docker":
        return "docker compose up --build"
    return "python verify_flow.py"


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

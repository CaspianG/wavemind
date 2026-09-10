# WaveMind

Keep a project's sources, decisions and work history under your control, so you
can continue with another assistant without rebuilding the context from scratch.
The local Brain preview lets you review facts, correct them, choose what each
agent may read, and export or delete your material.

For a personal move, keep the budget, deadline and reason for choosing a mover.
After the budget changes, the next client can request the corrected context and
see the unresolved question about who signs. For a company, keep each client's
instructions and results in a separate Brain, then grant an agent access to the
specific sources needed for that client's next task.

**D1 is a source preview for nonsecret pilot material.** It requires Python 3.10+
and a local browser; MCP also requires the optional MCP package. Storage is
plaintext. You enter and approve records yourself. WaveMind does not select an
account, connect an AI model, read your chats automatically or perform external
actions. Its usefulness to real people has not yet been measured.

[Start the preview](#quick-start) · [Personal guide / Личная память](docs/brain/personal.md)
· [Company guide / Для команды](docs/brain/teams.md) · [Agent contract](docs/brain/agent-contract.md)
· [Limits and evidence](docs/brain/limitations.md)

![Actual D1 owner interface showing a corrected project budget and an open question.](docs/assets/brain/personal-context.png)

Actual owner UI with synthetic nonsecret fixtures: corrected budget, cited facts
and partial coverage. This is an engineering demonstration, with no connected
model or measured user benefit. [Company screenshot](docs/assets/brain/company-context.png).

По-русски: храните выбранные документы, решения и результаты отдельно от одного
чата. Вы сами подтверждаете записи и выбираете источники для агента. После
исправления бюджета следующий запрос получает актуальное ограничение и открытые
вопросы. Это локальный исходный D1-прототип: нужен Python, данные не шифруются,
модель не подключена, польза для реальных пользователей пока не измерена.

![Context, receipt, external action, reported outcome, verification and the next request around persistent memory.](docs/assets/brain/owned-memory-loop-en.svg)

Explanatory diagram, not a product screenshot. Verifying a result does not
automatically admit a procedure. [HTML source](docs/assets/brain/owned-memory-loop-en.html)
· [Схема на русском](docs/assets/brain/owned-memory-loop.svg).

The published **2.14.0 library**, its Studio, container and
[legacy public site](https://caspiang.github.io/wavemind/) are separate from this
Brain source preview. A PyPI install or the existing Docker image does not
establish delivery of D1, a signed Windows installer, or a team deployment.
[Release facts](#verified-today) · [Research](#quantum-sensing-research)
· [Documentation](docs/README.md) · [Roadmap](docs/ROADMAP.md).

## Existing agent-memory library

The following library and benchmark sections describe the established runtime.
Brain's authenticated storage and agent contract are documented separately above.

The legacy `consolidate_concepts()` API, `wavemind consolidate` and
`POST /consolidate` turn active graph clusters into memories with source IDs.
This library consolidation path does not replace Brain's owner review.

Most agent memory stores what an agent **saw**. WaveMind reuses what independent
evidence says **worked**. A test, operator, tool or downstream state must verify
the outcome first; without valid evidence, a procedure is not promoted.

| Raw agent history | WaveMind verified experience |
|---|---|
| Stores text because it occurred | Promotes a procedure because its outcome was independently verified |
| Retrieves a similar fragment | Returns a small cited packet for the current task and environment |
| Lets corrections coexist as ambiguity | Reconciles conflicts and preserves what superseded what |
| Makes learned behavior hard to inspect | Keeps provenance, applicability, deletion, and rollback explicit |

Read the [plain-language explanation and evidence boundaries](docs/WHY_WAVEMIND.md) · [Dated market and product audit](docs/MARKET_AUDIT_2026-08-16.md).

## Built For Repeated Agent Work

| Team | Pain WaveMind targets | First useful result |
|---|---|---|
| Coding agents | Repeating a known repository, build, test, or tool failure | Replay one verified fix with repository and environment scope |
| Support and CRM agents | Reusing stale policy or leaking state between customers | Apply one independently verified resolution inside a customer namespace |
| Browser and operations agents | Repeating an obsolete navigation or runbook step | Reuse a cited procedure after an external-state check |
| Agent-platform teams | Rebuilding provenance, promotion, deletion, and rollback per framework | Share one governed Experience Packet contract across providers |
| Private workflows | Learning without a reviewable source or exit path | Keep verified experience local, inspectable, and reversible |

## What Makes It Different

Vector stores answer **what is similar?** Agent memory must also answer **what
still matters now?**

| Capability | What WaveMind adds |
|---|---|
| Adaptive recall | Hotness, decay, priority, TTL, feedback, and correction handling around vector candidates. |
| Durable state | SQLite by default; PostgreSQL, Redis coordination, and service-backed vector indexes for production paths. |
| Explicit control | Namespaces, provenance, audit events, backup/restore, inspection, and deliberate deletion. |
| Small integration surface | Python API, CLI, FastAPI, MCP, LangChain memory, and framework adapters. |
| Evidence-first releases | Public JSON artifacts, admission gates, reproducible commands, and locked claims when proof is missing. |

WaveMind complements FAISS, Qdrant, pgvector, Chroma, and other candidate indexes. It is the memory policy and lifecycle around retrieval, not another claim that one vector database should replace every other system.

## Verified Today

<!-- product-status:start -->
> WaveMind is the trust layer that lets agents learn from completed work without silently learning incorrect behavior.
>
> Canonical machine status: `docs/data/product-status.json`.

| Product truth | Status | Evidence |
|---|---|---|
| Brain D1 | `source_preview`; source-only; Python required, plaintext nonsecret pilot | [Local owner workflow](docs/brain/personal.md); exact-candidate D1 evidence required |
| Public release | `v2.14.0`; runtime source `e93954d40285` | PyPI package `wavemind` and `ghcr.io/caspiang/wavemind:2.14.0` |
| Current release | `v2.14.0` at `e93954d40285`; `published` | Upgrade admission `admitted_19_of_19`; GitHub Release, PyPI, and GHCR verified |
| Safe Product snapshot | `historical`, 18/18 checks at `92c539d0a069` | [`benchmarks/safe_product_admission_results.json`](benchmarks/safe_product_admission_results.json) |
| Current-source admission | Required per exact source SHA | [`.github/workflows/safe-product.yml`](.github/workflows/safe-product.yml) |
| TypeScript SDK | `@wavemind/http`, repository-local; npm claim disabled | Repository package only |

> Only an admitted exact-SHA workflow artifact may describe the current source as admitted.
<!-- product-status:end -->

The rows below are checked-in evidence snapshots. They remain useful and
auditable, but they do not become evidence for a newer source revision merely
because the repository moved forward.

| Proof | Checked-in evidence snapshot | Source |
|---|---|---|
| Production Memory OS | `admitted`, 13/13 requirements | [`memory_os_admission_results.json`](benchmarks/memory_os_admission_results.json) |
| Adaptive agent-memory advantage | Controlled adaptive slice passes, but the composite public gate remains `blocked` | [`agent_memory_advantage_admission_results.json`](benchmarks/agent_memory_advantage_admission_results.json) |
| Goal 4 generalization experiment | `failed_experiment`: full 451 quality uplift `-0.44 pp`; untouched 419 uplift `-1.19 pp`; context `-41.0%`; p95 `+1.59 ms` | [`goal4_quality_experiment_results.json`](benchmarks/goal4_quality_experiment_results.json) |
| Verified Agent Experience Runtime | `admitted`, 15/15 checks on 150 frozen stateful tasks across three domains; success `20%` -> `100%`; repeated errors `-100%`; context `-39.2%`; runtime p95 `6.12 ms` | [`verified_experience_admission_results.json`](benchmarks/verified_experience_admission_results.json) |
| Experienced Work Agent v1 | `admitted` only for its frozen local three-domain scenario: 12/12 checks; success `16.7%` -> `100%`; repeated errors `83.3%` -> `0%`; context `-40%` | [`experience_quality_admission_results.json`](benchmarks/experience_quality_admission_results.json) |
| Developer onboarding | `admitted`, 8/8 checks; Python, TypeScript, MCP, and Docker starters; first cited Experience Packet in `0.58s` | [`developer_experience_admission_results.json`](benchmarks/developer_experience_admission_results.json) |
| Memory safety | `admitted`, 10/10 checks; 375 attacks contained, 100% benign acceptance, zero cross-namespace leakage, rollback/provenance `1.00` | [`memory_safety_admission_results.json`](benchmarks/memory_safety_admission_results.json) |
| Provider integrations | `admitted`, 10/10 checks and 11/11 mandatory cases across Python, OpenAI Agents, Anthropic, MCP, LangGraph, HTTP, portable bundles, Mem0 import, and a clean TypeScript package; semantic parity `1.00` | [`integration_admission_results.json`](benchmarks/integration_admission_results.json) |
| Remote Redis/worker soak | 6 hours, 500/500 cycles, 2,500 attempts, zero failures or state corruption | [`memory_os_remote_worker_soak_results.json`](benchmarks/memory_os_remote_worker_soak_results.json) |
| LongMemEval-V2 protocol | Goal 4 completed a strict frozen 451-question experiment; it passed execution/context/latency controls but failed quality uplift, so no admission claim is made | [`failed experiment`](benchmarks/goal4_quality_experiment_results.json) / [`Memory OS run`](benchmarks/longmemeval_v2_small_memory_os_results.json) / [`strict smoke`](benchmarks/longmemeval_v2_frozen20_protocol_results.json) |
| Proof-carrying scientific selector | v32 performance-only validation passed exact selection on 240/240 frozen synthetic queries across three repeats; indexed p95 `0.151-0.156 s`, p95 speedup `9.72-10.09x` | [`v32 validation`](benchmarks/scientific_performance_v32_validation_results.json) / [`v31 failed admission`](benchmarks/scientific_v31_admission_outcome.json) |
| Core production readiness | `pass`, 39/39 criteria | [`production_readiness_results.json`](benchmarks/production_readiness_results.json) |
| Public package | PyPI and GitHub release `v2.14.0` | [PyPI](https://pypi.org/project/wavemind/) / [release](https://github.com/CaspianG/wavemind/releases/latest) |

Remote multi-region, managed serverless, 100M service evidence, and universal
multimodal admission remain explicitly gated. See
[Known Limitations](#known-limitations) and the
[evidence ledger](https://caspiang.github.io/wavemind/evidence/).

## Quick Start

For the Brain source preview, use a checkout that contains `wavemind/brain`.
In a project virtual environment, install that checkout and initialize a new
ordinary local profile outside the repository:

```sh
python -m pip install -e ".[mcp]"
python -m wavemind brain init --state-dir /absolute/local/brain-profile --owner-key-file /absolute/local/brain-owner.key
python -m wavemind brain serve --state-dir /absolute/local/brain-profile --token-file /absolute/local/brain-owner.key
```

Replace the example path with your selected local directory (on Windows,
`C:\WaveMindPilot\profile` is an example). `init` creates the explicitly selected
new owner-key file with private OS access and never prints the key. Keep that
plaintext key file private; `serve --token-file` reads it without placing the key
in a command argument or terminal transcript.
Open [the local owner UI](http://127.0.0.1:8000/brain), sign in with the same key,
select RU or EN and create a project. Preview an import before saving it.
The [personal guide](docs/brain/personal.md) covers setup, correction, access,
backup and errors. This is a developer launch, not a bundled installer.

For the published legacy library, the separate recall quick start is:

[Legacy terminal demonstration](docs/assets/wavemind-demo.gif) · [Demo script](docs/DEMO_SCRIPT.md).

```sh
python -m pip install wavemind
wavemind remember "Andrey is a trader" --namespace demo
wavemind query "What does Andrey do?" --namespace demo
```

Want to see and manage memory in a browser?

```sh
wavemind studio
```

Want the differentiated five-minute loop instead of a generic add/search demo?

```sh
wavemind init my-agent --template python
cd my-agent
python app.py
```

The starter runs a cold attempt, verifies it, promotes a bounded procedure, and
reuses a cited packet. Run `python examples/verified_experience_runtime.py` for
the explicit cold-run -> packet -> replay -> rollback path.

Use `--template typescript`, `--template mcp`, or `--template docker` for the
other starter paths. The Docker starter runs with
`docker compose up --build`. Diagnose Python, SQLite, local state, the encoder,
the Experience Compiler, and optional Node/Docker/MCP support with:

```sh
wavemind doctor --project .
```

By default, WaveMind creates `wavemind.sqlite3` in the current working
directory. That file is the local source of truth. Keep it out of git and back
it up like application state.

## Verified Agent Experience

The Agent Experience Runtime captures tool runs, accepts outcomes only from an
independent test, tool, environment, or operator, and keeps new procedures in
shadow until repeated evidence promotes them. At query time it can remain
silent or inject one compact, cited Experience Packet.

```sh
python examples/verified_experience_runtime.py
```

The example performs a real local cycle: a cold plan fails, the environment
verifies the result, independently verified executions activate a procedure,
and a held-out attempt succeeds using the cited procedure. The same lifecycle
is available through Python, HTTP, OpenAI Agents, Anthropic hooks, LangGraph,
MCP, TypeScript, and the Studio inspection views. See the
[runtime guide](docs/VERIFIED_EXPERIENCE_RUNTIME.md).

## CLI Cheat Sheet

Start here if you only want to use WaveMind from the terminal:

| Goal | Command |
|---|---|
| Show first-run help | `wavemind quickstart` |
| Create a runnable starter | `wavemind init my-agent --template python` |
| Diagnose the local environment | `wavemind doctor --project my-agent` |
| [Preview a safe package or Compose upgrade](docs/UPGRADE.md) | `wavemind upgrade --dry-run --json` |
| Store a memory | `wavemind remember "Andrey prefers short answers" --namespace user:42` |
| Search memory | `wavemind query "answer style" --namespace user:42` |
| Consolidate active patterns | `wavemind consolidate --namespace user:42 --seed "Rust compiler systems"` |
| Open local dashboard | `wavemind studio` |
| See stored state | `wavemind stats --namespace user:42` |
| Delete a namespace | `wavemind forget --namespace user:42` |
| Import notes | `wavemind import ./notes.txt --namespace project:alpha` |
| Use another database file | `wavemind --db ./state/memory.sqlite3 query "budget" --namespace user:42` |
| Start the HTTP API | `wavemind --db ./state/memory.sqlite3 serve --host 127.0.0.1 --port 8000` |

After this point, choose the integration path you need: Python, HTTP, LangChain, framework adapters, benchmarks, or production deployment.

## WaveMind Studio

WaveMind Studio is the built-in local dashboard. It runs on top of the same
FastAPI app and SQLite database as the CLI:

```sh
wavemind studio
```

It opens `http://127.0.0.1:8000/studio` and gives you:

| View | What it is for |
|---|---|
| Memory map | See field energy as a heatmap. |
| Namespace explorer | Inspect memories per user, project, agent, or tenant. |
| Live query tester | Test recall before wiring it into an app. |
| Feedback buttons | Mark recalled memories as useful or not useful. |
| Import/export | Import local files and export a namespace snapshot. |
| Backup | Create SQLite backups from the browser. |
| Conflict visualizer | Inspect correction groups when memories disagree. |
| Memory OS Insights | See read-only hot-query, policy, execution-plan, and architecture suggestions before running background workers. |

<img src="https://raw.githubusercontent.com/CaspianG/wavemind/main/docs/assets/wavemind-studio.png" alt="WaveMind Studio showing adaptive memory state, namespaces, TTL, feedback, and the memory-field heatmap" width="820">

For a server-safe local bind:

```sh
wavemind --db ./state/wavemind.sqlite3 studio --host 127.0.0.1 --port 8000
```

## Python Example

```python
from wavemind import WaveMind

memory = WaveMind(db_path="./state/wavemind.sqlite3")

memory.remember(
    "The user prefers short practical answers.",
    namespace="user:42",
    tags=["preference"],
)

hits = memory.query("How should I answer this user?", namespace="user:42", top_k=3)
for hit in hits:
    print(hit.score, hit.text)
```

The integration pattern is intentionally small:

1. Call `query()` before your app, agent, tool, or UI needs context.
2. Pass the returned memories into your prompt, screen, search result, or
   decision function.
3. Call `remember()` after something worth keeping happens.

Queries can also apply exact metadata filters. A collection value means
"match any", which is useful for tenant scopes, document sets, or benchmark
haystacks:

```python
hits = memory.query(
    "Which decision was approved?",
    namespace="team:research",
    metadata_filters={"document_id": ["report-17", "report-42"]},
)
```

## HTTP Example

The FastAPI server is included in the base install:

```sh
wavemind --db ./state/wavemind.sqlite3 serve --host 127.0.0.1 --port 8000
```

Then use WaveMind from any language:

```sh
curl -X POST http://127.0.0.1:8000/remember \
  -H "Content-Type: application/json" \
  -d "{\"text\":\"Andrey prefers short answers\",\"namespace\":\"user:42\",\"tags\":[\"preference\"]}"

curl -X POST http://127.0.0.1:8000/query \
  -H "Content-Type: application/json" \
  -d "{\"query\":\"How should I answer?\",\"namespace\":\"user:42\",\"top_k\":3}"

curl -X POST http://127.0.0.1:8000/feedback \
  -H "Content-Type: application/json" \
  -d "{\"id\":1,\"namespace\":\"user:42\",\"useful\":true,\"strength\":0.5,\"reason\":\"used in answer\"}"

curl -X POST http://127.0.0.1:8000/feedback/batch \
  -H "Content-Type: application/json" \
  -d "{\"namespace\":\"user:42\",\"items\":[{\"id\":1,\"useful\":true,\"strength\":0.5},{\"id\":2,\"useful\":false,\"strength\":0.25}]}"

curl -X POST http://127.0.0.1:8000/forget/batch \
  -H "Content-Type: application/json" \
  -d "{\"items\":[{\"text\":\"Andrey prefers short answers\",\"namespace\":\"user:42\"}]}"
```

The same feedback loop is available from the CLI:

```sh
wavemind --db ./state/wavemind.sqlite3 feedback --id 1 --namespace user:42 --strength 0.5 --reason "used in answer"
wavemind --db ./state/wavemind.sqlite3 feedback-batch --file feedback.json
```

## MCP Server

Give any MCP-compatible agent durable WaveMind tools:

```sh
python -m pip install "wavemind[mcp]"
wavemind-mcp --db ./state/agent-memory.sqlite3
```

Example client configuration:

```json
{
  "mcpServers": {
    "wavemind": {
      "command": "wavemind-mcp",
      "args": ["--db", "./state/agent-memory.sqlite3"]
    }
  }
}
```

The server exposes `remember`, `recall`, `feedback`, `forget`,
`inspect_memory`, `explain_memory`, and `manage_namespace`. It uses local
`stdio` by default, persists to SQLite across restarts, isolates every
operation by namespace, and supports idempotent writes and provenance.

See [MCP Integration](docs/MCP.md) for the tool contract, safety model,
streamable HTTP loopback mode, and tested behavior.

## Where Data Lives

WaveMind is local-first. The SQLite database stores memories, vectors, metadata,
namespaces, tags, TTL, hotness, priority, and audit events.

| runtime | Suggested database path |
|---|---|
| quick CLI experiment | `./wavemind.sqlite3` |
| Python app or agent | `./state/wavemind.sqlite3` |
| desktop app | user data directory, for example `%APPDATA%` or `~/.local/share` |
| server daemon | `/var/lib/wavemind/wavemind.sqlite3` |
| Docker | mounted volume, for example `/data/wavemind.sqlite3` |

Explicit path:

```sh
wavemind --db ./state/app_memory.sqlite3 remember "Andrey prefers short answers" --namespace user:42
wavemind --db ./state/app_memory.sqlite3 query "answer style" --namespace user:42
```

## Common Ways To Use It

| You are building... | Start with... |
|---|---|
| Python app | `from wavemind import WaveMind` |
| LangChain agent | `WaveMindMemory` from `wavemind.integrations.langchain` |
| LangGraph workflow | `make_recall_node()` and `make_persist_node()` |
| LlamaIndex pipeline | `WaveMindRetriever` |
| CrewAI or AutoGen loop | The adapters in `wavemind.integrations` |
| Node, Go, Ruby, PHP, or no-code app | `wavemind serve` and the HTTP API |
| Personal knowledge base | Store notes by project namespace and query locally |
| Support or CRM workflow | Customer issues, resolutions, preferences, corrections, TTL, and namespace isolation. See [`examples/customer_support_memory.py`](examples/customer_support_memory.py). |
| Research or analyst notebook | Findings, hypotheses, decisions, source metadata, TTL, and project isolation. See [`examples/research_notebook_memory.py`](examples/research_notebook_memory.py). |

For migrations from existing local vector memory, start with
[`docs/CHROMA_MIGRATION.md`](docs/CHROMA_MIGRATION.md). The guide has a tested
offline fixture at [`examples/chroma_migration.py`](examples/chroma_migration.py).

## Optional Embeddings

The base install is offline and keyless. Add sentence-transformers when you
need semantic embeddings:

```sh
python -m pip install "wavemind[sentence]"
wavemind --encoder sentence remember "Andrey is a trader" --namespace demo
wavemind --encoder sentence query "What does Andrey do?" --namespace demo
```

## Optional Index Backends

WaveMind separates durable state from candidate generation:

| index | Install | Notes |
|---|---|---|
| `numpy` | default | Exact cosine search, local, linear scan. |
| `quantized` | default | Local int8-compressed candidate index with int32-safe scoring. Useful for memory-footprint experiments; approximate recall and latency must still be measured per workload. |
| `annoy` | `pip install "wavemind[indexes]"` | Local ANN. Faster at larger N, but recall must be checked. |
| `faiss` / `faiss-persisted` | `pip install "wavemind[indexes]"` | Local FAISS, with an optional validated persisted snapshot. |
| `pgvector` | `pip install "wavemind[postgres]"` | PostgreSQL/pgvector service candidate index. |
| `qdrant` | `pip install "wavemind[indexes]"` | Qdrant service or local-mode candidate index. |

SQLite or PostgreSQL remains the source of truth. Missing service configuration
fails clearly instead of silently switching backends. See
[Embeddings And Index Backends](docs/INDEX_BACKENDS.md) for setup, tuning,
health checks, and persistence rules.

## Scale Readiness

WaveMind ships local and service-backed storage, namespace sharding, replication,
Kubernetes/operator manifests, serverless lifecycle checks, backup/restore
drills, and strict evidence gates. The current production evidence gate passes
`5/8` requirements; remote active-active, managed serverless telemetry, and a
real 100M sharded run remain explicitly locked.

The **Checked-in production 50000-vector point** covers
`WaveMind faiss-persisted`, `Qdrant service`, and pgvector tuning with
`WAVEMIND_PGVECTOR_EF_SEARCH=400`, `pgvector-exact`, and
`pgvector-iterative`.

Deployment references use `ghcr.io/caspiang/wavemind`. The
`deploy/cloud/gcp-managed-serverless` module creates billable Google Cloud
resources. `deploy/cloud/gcp-remote-active-active` also creates billable
infrastructure and does not unlock a production claim by itself.
`deploy/cloud/gcp-qdrant-100m` creates eight billable VMs; planning or applying
that module does not unlock the 100M claim without the measured artifact.

See [Scale And Production](docs/SCALE_AND_PRODUCTION.md) for deployment modes,
failure drills, strict claim boundaries, and exact reproduction commands. See
[Observability](docs/OBSERVABILITY.md) for metrics, traces, dashboards, and
alerts.

## Structured And Multimodal Memory

WaveMind supports typed image, audio, video, 3D, table, temporal-event, and
knowledge-graph payloads. The checked real-encoder suite uses pinned local
SentenceTransformers, CLIP, CLAP, and OpenShape PointBERT models over 1000
public assets and 200 independent queries. Its three exact-SHA runs all pass
the production admission gate:

| Metric | Checked result |
|---|---:|
| Macro / cross-modal / mixed precision@1 | `0.925 / 0.925 / 0.925` |
| Persisted / reload parity | `1.000 / 1.000` |
| Retrieval p99 | `48.64 ms` |
| Errors | `0` |

The suite covers text, image, audio, video, and 3D retrieval and verifies the
asset lifecycle against local S3-compatible MinIO. The separate
precomputed-vector path remains an integration contract only; it does not prove
encoder quality.

The production gate requires real local text, image, audio, video, and 3D
encoders over at least 1000 real or publicly licensed assets and 200 independent
queries. It also requires explicit compatible shared spaces, bidirectional
cross-modal checks, per-modality quality and encoding budgets, stable repeated
verdicts, and a verified S3-compatible lifecycle. Local MinIO is valid;
descriptor, filename, metadata, OCR-only, synthetic-vector, and precomputed
shortcuts are rejected as encoder evidence.

See [Multimodal And Storage](docs/MULTIMODAL_AND_STORAGE.md) for payload schemas,
cross-modal retrieval, temporal and graph queries, storage backends, object
lifecycles, backup/restore, and API details.

## HTTP API

Start the API with:

```sh
wavemind serve --host 127.0.0.1 --port 8000
```

The service exposes memory, feedback, lifecycle, health, metrics, cluster, and
Memory OS routes. Production deployments should enable authentication, rate
limits, TLS termination, durable storage, and monitoring. The complete route
reference is in [Multimodal And Storage](docs/MULTIMODAL_AND_STORAGE.md#http-api).

## Install From Source

For contributors installing from a local clone:

```sh
git clone https://github.com/CaspianG/wavemind.git
cd wavemind
python -m pip install -e ".[sentence]"
```

One-file setup scripts are also included in the repository:

```sh
sh install.sh
```

```bat
install.bat
```

## LangChain Memory

WaveMind includes package adapters for LangChain, LangGraph, LlamaIndex,
CrewAI, and AutoGen. The adapters preserve namespaces and use the same durable
memory API as the CLI and HTTP service.

See [Framework Integrations](docs/INTEGRATIONS.md) for complete examples,
OpenClaw/Hermes guidance, and custom agent loops.

## Benchmark

WaveMind publishes checked-in JSON and Markdown artifacts for dynamic-memory,
long-term-memory, indexing, scale, Memory OS, and production-evidence profiles.
The public leaderboard separates implemented, runner-ready, planned, local,
loopback, and production evidence.

| Evidence | Current checked result |
|---|---|
| Verified Agent Experience Runtime | `admitted`; 150 frozen tasks, 5 repeats, 95% CIs, success `0.20 -> 1.00`, context `-39.2%`, p95 `6.12 ms` |
| Proof-carrying scientific selector | v32 performance validation matched the reference on 240/240 frozen synthetic queries across three repeats; p95 speedup `9.72-10.09x`; v31 quality admission remains failed |
| STATE-Bench Agent Learning adapter | `runner_ready`; official `100 x 3` train split validated at an exact upstream SHA; official paid evaluation not run |
| Memory OS admission | `admitted`, 13/13 requirements |
| Agent-memory advantage admission | Controlled adaptive slice passes; composite public gate blocked on strict LongMemEval-V2 |
| Memory OS remote soak | 6 hours, 500 cycles, 2500 attempts, zero corruption |
| Real multimodal admission | `admitted`; 1000 assets, 200 queries, precision@1 `0.925`, retrieval p99 `48.64 ms` |
| Direct Memory OS public runs | LoCoMo 1977 queries; LongMemEval-S 470 queries; strict isolated LongMemEval-V2 frozen-20 smoke |
| Strict production evidence | 5/8 requirements |
| LongMemEval evidence retrieval | WaveMind recall@5 `0.782` |
| Real LoCoMo memory systems | WaveMind recall@5 `0.548`; Mem0 OSS `0.500`; Hindsight OSS `0.316` |
| Large-N profiles | 10M Qdrant, 10M sharded Qdrant, 10M pgvector, 50M FAISS |

These results do not claim universal vector-database leadership or completed
remote 100M/multi-region proof. See the full [Benchmark Guide](docs/BENCHMARKS.md),
[real public memory-system report](benchmarks/PUBLIC_MEMORY_COMPETITORS.md),
[public evidence ledger](https://caspiang.github.io/wavemind/evidence/), and
[Benchmark Brief](docs/BENCHMARK_BRIEF.md) for methods, commands, limitations,
and machine-readable artifacts. Contributors can use the
[benchmark directory map](benchmarks/README.md) to distinguish source,
protocols, raw records, results, and admission verdicts.

## Comparison

WaveMind governs verified experience and memory around candidate retrieval; it
does not replace dedicated vector databases. Keep Chroma, Qdrant, pgvector, or
FAISS where they fit, and add WaveMind when reuse needs evidence, scope,
correction, forgetting, and rollback. See the practical
[Chroma migration guide](docs/CHROMA_MIGRATION.md) and
[index backend guide](docs/INDEX_BACKENDS.md).

## Quantum Sensing Research

![Conceptual illustration: a transparent crystal on a copper mount, not a built sensor.](research/breakthrough/assets/quantum-sensing-concept.png)

Can control make a weak signal easier to read? Cover: conceptual illustration.
[Visual research guide](research/breakthrough/README.md) · [По-русски](research/breakthrough/START_HERE_RU.md).

![Frozen simulation: pulse compensation improves both methods; DRAG3 with RXY8 remains above DRAG3 with RS.](research/breakthrough/assets/pulse-comparison.svg)

Simulation only: the candidate does **not** beat the strongest known control.
This separate research track is not a proven breakthrough, built sensor or
library feature. [Results and limits](research/breakthrough/sensing_rs/RESULTS_V3_RU.md).

## Known Limitations

- Brain D1 uses plaintext local storage and synthetic engineering scenarios.
  Signed installation (D2), team deployment (D3), real user usefulness and frozen
  scientific comparison (D4) remain separate. Read [Brain limits](docs/brain/limitations.md).
- The default NumPy exact index is intended for local memory streams. Run
  `wavemind scale-plan` and move to FAISS, Qdrant, or pgvector before treating it
  as a large-N production index.
- Dynamic memory policy adds latency compared with static nearest-neighbor
  retrieval. The value is stale suppression, reinforcement, TTL, scoped recall,
  and consolidation rather than winning every pure ANN latency test.
- Direct feedback-free Memory OS is not a universal quality boost. On LoCoMo it
  is slightly below Core (`precision@1 0.2382` vs `0.2387`); on LongMemEval-S it
  matches Core. The controlled sequential benchmark remains the admitted uplift
  evidence.
- The earlier 451-question LongMemEval-V2 run proves execution coverage, but it
  predates official per-question haystack filtering and isolated A/B stores, so
  its `7.54% -> 9.09%` result is not accepted as Memory OS uplift. The strict
  frozen-20 rerun reaches `10%` for both Core and Memory OS with
  `qwen2.5:3b`; a full strict rerun and the `18%` quality target remain open.
- `MemoryFieldGraph` is a discrete graph over stored memories, not a continuous
  physics field.
- Production Memory OS is admitted for its documented remote Redis/worker
  topology. The broader cluster gate remains 5/8: remote multi-region, managed
  serverless telemetry, and 100M service evidence are not yet admitted.
- The checked real text/image/audio/video/3D suite is admitted for its pinned
  models, datasets, exact source SHA, and local MinIO topology. This is not a
  claim of universal cross-modal quality on unseen domains; precomputed vectors
  and descriptors still cannot unlock real-encoder admission.
- Large-N Qdrant and pgvector artifacts prove their stated GitHub-hosted service
  topologies, not independent multi-host or multi-region production.

Read the complete [Known Limitations And Claim Boundaries](docs/KNOWN_LIMITATIONS.md)
before publishing performance, scale, or multimodal claims.

## Roadmap

Full roadmap: [`docs/ROADMAP.md`](docs/ROADMAP.md).
Launch and positioning kit: [`docs/LAUNCH_KIT.md`](docs/LAUNCH_KIT.md).
Documentation map: [`docs/README.md`](docs/README.md).
Release history: [`CHANGELOG.md`](CHANGELOG.md).

Near-term priorities:
- admit task-native measurement validity before resuming product quality tuning;
- demonstrate paired generalizable benefit on an agent/workflow family and an independent memory family;
- combine fast FAISS, Qdrant, or pgvector retrieval with bounded WaveMind reranking;
- publish the already admitted safe one-command upgrade candidate before WaveMind Connect;
- complete multi-region and 100M scale claims only on matching infrastructure.

Longer-term direction:

Make verified experience improve real workflows without losing provenance,
scope, safety, correction, or rollback. Scale the lifecycle without changing
the application-level contract, and keep every public capability tied to an
artifact, gate, or locked claim boundary.

## Contributing

See [`CONTRIBUTING.md`](CONTRIBUTING.md) and
[`CODE_OF_CONDUCT.md`](CODE_OF_CONDUCT.md).

Useful contribution paths:

- add reproducible benchmark adapters and checked-in result JSON;
- improve FAISS, Qdrant, pgvector, or other candidate-index backends;
- add framework examples and improve TTL, corrections, namespaces, graph
  dynamics, and consolidation;
- harden production operations: backups, audit logs, metrics, tracing, and
  migration tools.

GitHub issue templates are included for bugs, features, benchmarks, and
integrations. Benchmark claims need a reproduction command and committed result
artifact before they are added to README.

## License
MIT. See [LICENSE](LICENSE).

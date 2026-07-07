<div align="center">

# WaveMind

**Local-first dynamic memory for apps, agents, notebooks, and tools.**

WaveMind stores memories in SQLite, finds relevant candidates with vector
search, then uses a wave-field priority layer to decide what still matters:
hot facts rise, stale facts fade, temporary facts expire, and namespaces keep
users or projects isolated.

![Python](https://img.shields.io/badge/python-3.10%2B-blue)
[![PyPI](https://img.shields.io/pypi/v/wavemind.svg)](https://pypi.org/project/wavemind/)
[![Tests](https://github.com/CaspianG/wavemind/actions/workflows/tests.yml/badge.svg)](https://github.com/CaspianG/wavemind/actions/workflows/tests.yml)
![License](https://img.shields.io/badge/license-MIT-green)

<img src="https://raw.githubusercontent.com/CaspianG/wavemind/main/docs/assets/wavemind-social-card.svg" alt="WaveMind dynamic memory overview" width="820">

<img src="https://raw.githubusercontent.com/CaspianG/wavemind/main/docs/assets/wavemind-demo.gif" alt="WaveMind dynamic memory terminal demo" width="820">

[Quick Start](#quick-start) |
[CLI](#cli-cheat-sheet) |
[Studio](#wavemind-studio) |
[Python Example](#python-example) |
[HTTP Example](#http-example) |
[Where Data Lives](#where-data-lives) |
[LangChain](#langchain-memory) |
[Chroma Migration](docs/CHROMA_MIGRATION.md) |
[Use Cases](docs/USE_CASES.md) |
[HTTP API](#http-api) |
[Benchmarks](#benchmark) |
[Benchmark Brief](docs/BENCHMARK_BRIEF.md) |
[Research Branches](#research-branches) |
[Roadmap](#roadmap) |
[Contributing](#contributing) |
[Limitations](#known-limitations)

</div>

## What Is WaveMind?

WaveMind is a dynamic memory engine you can embed in a product.

Use it when your app needs to remember things like user preferences, decisions,
corrections, notes, research snippets, support history, agent context, or
temporary facts.

The short version:

```text
normal vector search:  find the nearest text
WaveMind:              find the nearest useful memory
```

WaveMind is not trying to replace every vector database. It is the memory layer
around retrieval: persistence, namespaces, TTL, hotness, priority, decay,
explicit forgetting, audit events, and optional graph dynamics.

## 60-Second Version

| Question | Answer |
|---|---|
| What does it store? | Text memories, vectors, metadata, tags, TTL, priority, and recall state. |
| Where does it store data? | A local SQLite file by default; Postgres is available for production state. |
| How do I use it? | CLI, Python API, FastAPI HTTP server, LangChain memory, or framework adapters. |
| What is different from Chroma/Qdrant? | WaveMind adds memory policy: hotness, decay, TTL, correction handling, and scoped recall. |
| When should I not use it? | For huge static document search where a mature vector DB is already the right tool. |
| What is the simplest install? | `python -m pip install wavemind` |

## Why Use It?

| If you need... | WaveMind gives you... |
|---|---|
| Memory that survives restarts | One SQLite file stores text, vectors, metadata, TTL, and recall state. |
| Per-user or per-project recall | Namespaces and tags keep memories separated. |
| Temporary facts | `ttl_seconds` lets facts expire automatically. |
| Corrections and changing preferences | Newer or reinforced memories can outrank stale ones. |
| A simple integration path | Python API, CLI, FastAPI server, and LangChain memory class. |
| Production hygiene | Backups, audit log, API keys, rate limits, Prometheus metrics, and OpenTelemetry traces. |

## Quick Start

The shortest path from install to first recall:

```sh
python -m pip install wavemind
wavemind remember "Andrey is a trader" --namespace demo
wavemind query "What does Andrey do?" --namespace demo
```

Need a reminder after install?

```sh
wavemind quickstart
```

Want to see and manage memory in a browser?

```sh
wavemind studio
```

By default, WaveMind creates `wavemind.sqlite3` in the current working
directory. That file is the local source of truth. Keep it out of git and back
it up like application state.

## CLI Cheat Sheet

Start here if you only want to use WaveMind from the terminal:

| Goal | Command |
|---|---|
| Show first-run help | `wavemind quickstart` |
| Store a memory | `wavemind remember "Andrey prefers short answers" --namespace user:42` |
| Search memory | `wavemind query "answer style" --namespace user:42` |
| Consolidate active patterns | `wavemind consolidate --namespace user:42 --seed "Rust compiler systems"` |
| Open local dashboard | `wavemind studio` |
| See stored state | `wavemind stats --namespace user:42` |
| Delete a namespace | `wavemind forget --namespace user:42` |
| Import notes | `wavemind import ./notes.txt --namespace project:alpha` |
| Use another database file | `wavemind --db ./state/memory.sqlite3 query "budget" --namespace user:42` |
| Start the HTTP API | `wavemind --db ./state/memory.sqlite3 serve --host 127.0.0.1 --port 8000` |

After this point, choose the integration path you need: Python, HTTP, LangChain,
framework adapters, benchmarks, or production deployment.

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
```

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

## Minimal Agent Loop

```python
from wavemind import WaveMind

memory = WaveMind(db_path="./state/agent.sqlite3")

def run_turn(user_id: str, user_text: str) -> str:
    namespace = f"user:{user_id}"
    hits = memory.query(user_text, namespace=namespace, top_k=5, min_score=0.25)
    recalled = "\n".join(f"- {hit.text}" for hit in hits)

    answer = call_your_llm(f"Relevant memory:\n{recalled}\n\nUser: {user_text}")

    memory.remember(f"User said: {user_text}", namespace=namespace, tags=["conversation"])
    memory.remember(f"Assistant answered: {answer}", namespace=namespace, tags=["conversation"])
    return answer
```

## Terminal Demo

From a cloned repository:

```text
$ python examples/demo.py
[ok] Remembered: "Andrey is a trader who tracks market breakouts."
[ok] Remembered: "Andrey prefers short practical answers about product decisions."

Query: "Andrey trader preferences"
-> Result 1 (0.60): "Andrey is a trader who tracks market breakouts."
-> Result 2 (0.30): "Andrey prefers short practical answers about product decisions."
```

The demo is offline, keyless, and uses the built-in hash encoder.

To see the behavior that plain vector search does not provide:

```sh
python examples/dynamic_memory_demo.py
```

That demo shows corrected facts outranking stale facts, temporary memory
expiring, namespace isolation, and index-health reporting.

To see the same behavior in a practical support/CRM workflow:

```sh
python examples/customer_support_memory.py
```

That demo stores customer preferences, billing tickets, stale CRM data,
temporary discount codes, and separate customer namespaces.

To see source-aware research memory:

```sh
python examples/research_notebook_memory.py
```

That demo stores analyst findings, temporary hypotheses, decisions, source
metadata, and isolated project namespaces.

## How The Memory Field Works

```mermaid
flowchart LR
    A["Text, event, note, document, or agent turn"] --> S["remember()"]
    S --> D[("SQLite: text + metadata + vectors + memory state")]
    Q["query()"] --> K["k-NN candidate search"]
    D --> K
    K --> W["wave-field re-rank"]
    W --> R["small ranked recall set"]
    R --> P["app, search UI, prompt, API, or tool"]
    P --> F["recall feedback updates hotness / priority"]
    F --> D
    F --> C["consolidate active clusters"]
    C --> D
```

The wave field is the dynamic layer around stored memories. It is not a
replacement for embeddings; it is the policy that decides which candidate
memories should still matter.

| signal | Plain meaning | Effect |
|---|---|---|
| vector similarity | This text is semantically close to the query. | Gets into the candidate set. |
| hotness | This memory has been useful before. | Moves upward during recall. |
| decay | This memory has not mattered recently. | Slowly loses influence. |
| priority | The app says this fact is important. | Raises ranking even before repetition. |
| TTL | This fact is temporary. | Drops out after expiry. |
| namespace and tags | This belongs to one user/project/type. | Prevents cross-user or cross-topic leakage. |
| graph dynamics | Related memories can excite or inhibit each other. | Helps clusters and corrections behave like memory, not a flat list. |
| consolidation | Active clusters can become durable concept memories. | Turns repeated patterns into inspectable higher-level memories with provenance. |

Technically, the current `MemoryFieldGraph` is a discrete graph over stored
memories, not a continuous mathematical physics field. That honesty matters:
WaveMind is useful today as a dynamic memory engine, while the research path is
to make the field dynamics more explicit, measurable, and scalable.

Self-organization is now part of the core surface. `consolidate_concepts()`,
`wavemind consolidate`, and `POST /consolidate` can turn an active graph cluster
into a new stored memory such as `Consolidated memory: systems...` without an
LLM call. The generated memory keeps the source memory ids in metadata, so it is
auditable instead of being a hidden summary.

## Optional Embeddings

For sentence-transformer embeddings:

```sh
python -m pip install "wavemind[sentence]"
wavemind --encoder sentence remember "Andrey is a trader" --namespace demo
wavemind --encoder sentence query "What does Andrey do?" --namespace demo
```

## Optional Index Backends

The default index is NumPy exact search. It is simple and reliable for local
memory. For larger candidate generation, WaveMind also exposes optional index
backends:

| index | Install | Notes |
|---|---|---|
| `numpy` | default | Exact cosine search, local, linear scan. |
| `quantized` | default | Local int8-compressed candidate index. Useful for memory-footprint experiments; current kernel is approximate and not yet faster than NumPy. |
| `annoy` | `pip install "wavemind[indexes]"` | Local ANN. Faster at larger N, but recall must be checked. |
| `faiss` | `pip install "wavemind[indexes]"` | FAISS flat inner-product path where `faiss-cpu` is available. |
| `faiss-persisted` | `pip install "wavemind[indexes]"` | FAISS with an explicit persisted index snapshot and id map. |
| `pgvector` | `pip install "wavemind[postgres]"` | PostgreSQL/pgvector candidate index. SQLite can still remain the local source of truth. |
| `qdrant` | `pip install "wavemind[indexes]"` | Qdrant service/local-mode candidate index. SQLite remains the source of truth; Qdrant stores vectors. |

Persisted FAISS setup:

```sh
export WAVEMIND_FAISS_PATH="./state/wavemind.faiss"
wavemind --index faiss-persisted remember "Andrey is a trader" --namespace demo
wavemind --index faiss-persisted query "trader" --namespace demo
```

SQLite or Postgres remains the source of truth. The persisted FAISS files are a
candidate-index snapshot and are validated against the current memory ids on
load. If the snapshot does not match the stored memories, WaveMind rebuilds it.
You can also check and rebuild the candidate index explicitly:

```sh
wavemind --index faiss-persisted index-health --json
wavemind --index faiss-persisted rebuild-index
```

Index health compares durable memory ids against the candidate index. Local
indexes report exact missing/extra ids; service backends report exact ids when
the backend exposes an id scan and otherwise fall back to count-based health.

pgvector setup:

```sh
export WAVEMIND_PGVECTOR_DSN="postgresql://user:password@localhost:5432/wavemind"
wavemind --index pgvector remember "Andrey is a trader" --namespace demo
wavemind --index pgvector query "trader" --namespace demo
```

Optional pgvector environment variables:

- `WAVEMIND_PGVECTOR_TABLE` - table name, default `wavemind_vectors`.
- `WAVEMIND_PGVECTOR_COLLECTION` - collection key, default `default`.
- `WAVEMIND_PGVECTOR_CREATE_HNSW=1` - create an HNSW index using
  `vector_cosine_ops` when the installed pgvector version supports it.
- `WAVEMIND_PGVECTOR_HNSW_M` - optional HNSW graph degree for index creation.
- `WAVEMIND_PGVECTOR_HNSW_EF_CONSTRUCTION` - optional HNSW build accuracy setting.
- `WAVEMIND_PGVECTOR_EF_SEARCH` - optional per-query HNSW search depth. Increase
  it when pgvector is fast but recall is too low.
- `WAVEMIND_PGVECTOR_ITERATIVE_SCAN=strict_order|relaxed_order|off` - optional
  pgvector iterative HNSW scan mode for higher recall on newer pgvector builds.
- `WAVEMIND_PGVECTOR_MAX_SCAN_TUPLES` and
  `WAVEMIND_PGVECTOR_SCAN_MEM_MULTIPLIER` - optional HNSW scan bounds for
  production recall/latency tuning.
- `WAVEMIND_PGVECTOR_EXACT=1` - force an exact scan for recall audits and
  correctness-sensitive jobs. This is slower than HNSW, but it gives a direct
  way to separate index approximation loss from WaveMind ranking behavior.

If `WAVEMIND_PGVECTOR_DSN` is missing, WaveMind raises a clear error instead of
silently falling back to another index backend.
The pgvector table is created with the current encoder dimension, so use a
separate table when switching between different vector sizes.

Qdrant setup:

```sh
export WAVEMIND_QDRANT_URL="http://localhost:6333"
export WAVEMIND_QDRANT_COLLECTION="wavemind_vectors"
wavemind --index qdrant remember "Andrey is a trader" --namespace demo
wavemind --index qdrant query "trader" --namespace demo
```

For local experiments you can set `WAVEMIND_QDRANT_URL=":memory:"`, but
production latency and durability should be measured against a real Qdrant
service. If `WAVEMIND_QDRANT_URL` is missing, WaveMind raises a clear error
instead of silently falling back to another backend.

## Scale Readiness

WaveMind now includes an explicit scale preflight:

```sh
wavemind scale-plan --target-memories 50000
```

For JSON output in CI or deployment checks:

```sh
wavemind --db ./state/wavemind.sqlite3 scale-plan --target-memories 50000 --json
```

To fail a deployment preflight when the plan needs action:

```sh
wavemind --db ./state/wavemind.sqlite3 scale-plan --target-memories 50000 --fail-on action_required --json
```

If you only want a plan for a future size without loading optional index
packages:

```sh
wavemind --index faiss scale-plan --current-memories 10000 --target-memories 50000 --json
```

The scale plan reports:

| field | meaning |
|---|---|
| `tier` | `small`, `medium`, `large-local`, `production-service`, or `million-plus`. |
| `status` | `ok`, `watch`, `action_required`, or `architecture_required`. |
| `recommended_index` | The candidate-index class to use before growth. |
| `warnings` | Why the current path may fail at the target size. |
| `actions` | Concrete setup, benchmark, rebuild, and index-health steps. |

The same scale preflight is available over HTTP:

```sh
curl "http://127.0.0.1:8000/scale-plan?target_memories=50000"
```

For a concrete operator checklist, use the architecture advisor:

```sh
wavemind advise --target-memories 2000000 --namespace-count 4096 --deployment production --replication-factor 3 --read-quorum 1 --read-fanout 1 --json
```

It combines live `stats()`, `scale-plan`, p99 targets, namespace count,
replication settings, and multimodal needs into actionable recommendations:
candidate index, sharding, cache, DR drill, observability, and external cluster
load checks. For latency-sensitive hot paths, keep `read_fanout` near
`read_quorum`; wider fanout reads more replicas and should be justified by the
HTTP cluster load benchmark. The same advice is available through HTTP:

```sh
curl "http://127.0.0.1:8000/architecture/advice?target_memories=2000000&namespace_count=4096&deployment=production&replication_factor=3&read_quorum=1&read_fanout=1"
```

Use `--fail-on action_required` in CI when a deployment must not proceed until
the required architecture work is done.

For production load tests, use the same SLO and cost gates that power the
checked-in benchmark report:

```python
from wavemind import (
    ProductionCostTarget,
    ProductionSLOTarget,
    estimate_production_cost,
    evaluate_production_slo,
)

target = ProductionSLOTarget(target_recall_at_k=0.95, target_p99_ms=100, target_qps=100)
result = evaluate_production_slo(
    engine="faiss-persisted",
    recall_at_k=1.0,
    avg_latency_ms=39.12,
    p99_latency_ms=57.71,
    target=target,
)
print(result.status, result.blocking_reasons)

cost = estimate_production_cost(
    result,
    memory_count=1_000_000,
    vector_dim=128,
    target=ProductionCostTarget(replica_hourly_cost_usd=0.25),
)
print(cost.required_replicas, cost.compute_cost_per_1m_queries_usd)
```

Rule of thumb:

| target memories | recommended path |
|---:|---|
| up to 1000 | SQLite + NumPy exact index. |
| 1000 to 5000 | NumPy can work, but benchmark real queries. |
| 5000 to 50000 | Persisted FAISS for local single-node, or Qdrant service. |
| 50000 to 1M | Service-backed candidate index, namespace sharding, measured p95/p99. |
| above 1M | External vector database plus WaveMind as the memory-policy layer. |

Scale readiness profile:

```sh
python benchmarks/scale_readiness_benchmark.py --simulated-memories 1000000
```

Checked-in result:

| profile | result |
|---|---:|
| Cluster planner | 4096 namespaces, 4 nodes, replication factor 2, node-loss availability `1.000`, zone-loss availability `1.000`, write quorum `2`, Kubernetes `StatefulSet` + repair `CronJob` covering `4096` namespaces. |
| Cluster autoscaler | 10M target memories, RF=3, current nodes `4`, required nodes `50`, additional nodes `46`, target max node load `678711`, headroom pass `true`, namespace move sample `25` with `4069` omitted. |
| Control-plane consensus | Majority leadership lease blocks stale leaders, stale revisions, and minority config commits; membership change advances voters `3 -> 5`, term `1 -> 2`, final config revision `2`. |
| Kubernetes operator | CRD + operator deployment `true`, reconciled `StatefulSet`, `HorizontalPodAutoscaler`, and repair `CronJob`; 10M capacity target raises StatefulSet/HPA to `34` replicas with target max node load `678711`, CPU+memory metrics, status phase `Ready`, and resources/capacity/autoscaling/repair/control-plane conditions `true`. |
| Hot cache | 2000 lookups, hit rate `0.920`, p99 lookup `0.003 ms`, query-audit prewarm warmed `1` hot query, prewarm hit `true`. |
| Query-vector cache | 200 repeated queries, one local encoder call, local hit rate `0.995`, Redis-compatible cache shared across workers `true`. |
| Shared rate limiter | Redis-compatible fixed-window limiter, 2 workers, 4 allowed requests, 1 limited request, shared enforcement `true`. |
| Redis hot cache | Redis-compatible shared cache is visible across workers, query-audit prewarm warms `1` hot query, Memory OS warms `2` observed hot queries plus `5` predictive neighbor queries, demotes cold memories, cross-worker hit `true`, namespace invalidation `true`, production architecture advice `architecture_required`. |
| API cache mutation safety | FastAPI shared cache invalidates on `/remember` and `/forget`, preventing stale cached recall after memory mutations. |
| Distributed sharding | 3 service nodes, replication factor 2, write quorum 2, writes `2`, recall after primary loss `true`, service-mode repair copied `1` missing record, recall after repair `true`, replicated forget deletes `2`, service-mode tombstone suppression before repair `true`, tombstone repair deleted `1` stale replica record, suppression after repair `true`, anti-entropy worker repaired `1` missing record and deleted `1` stale tombstone record, query-after-primary-loss `0.84 ms`. |
| Distributed HTTP sharding | 3 real localhost API nodes, proxy bypass `true`, quorum writes `2`, recall after primary loss `true`, HTTP repair copied `1` missing record, recall after repair `true`, tombstone repair deleted `1` stale API record, suppression after repair `true`, concurrent writes `12`, concurrent query hit rate `1.000`. |
| Sustained HTTP cluster load | 4 real localhost API nodes, RF=3, 8 quorum writes, 8 normal queries, 8 failover queries, 4 deletes, success rate `1.000`, failover hit rate `1.000`, delete suppression `1.000`, repair copied `1` missing replica, p99 operation `189.25 ms`. |
| Local HTTP cluster health | Post-load `/stats` probe reports health `true`, healthy nodes `4`, degraded nodes `0`, unavailable nodes `0`. |
| Replicated runtime | 3 physical WaveMind stores, replication factor 3, write quorum 2, node-loss recall `true`, repair copied `1` missing record, tombstone repair deleted `1` stale record, concurrent writes `12`, concurrent query hit rate `1.000`, p99 query-after-loss `1.34 ms`. |
| Active-active delta sync | 2 regions, bidirectional convergence `true`, full sync imported `6` records, cursor-based incremental sync exported `1` new record and imported `3` replicas, field-only hotness delta exported `0` records and `1` field key, stale import suppressed after delete `true`, tombstone convergence `true`, sync `114.70 ms`. |
| Sustained active-active sync | 3 independent regions, 3 namespaces, 18 writes, 5 mesh sync cycles, 90 region-pair syncs, cursor count `18`, records imported `108`, tombstones imported `6`, deleted records `6`, field keys exported `348`, final no-op imported `0`, convergence `1.000`, delete suppression `1.000`, success `1.000`, failed pairs `0`. |
| HTTP active-active service-region sync | 3 FastAPI service-boundary regions, 2 namespaces, 6 writes, 4 sync cycles, 48 export/import pair calls through `/namespace-delta/export` and `/namespace-delta/import`, cursor count `12`, records imported `36`, tombstones imported `6`, deleted records `6`, final no-op imported `0`, convergence `1.000`, delete suppression `1.000`, success `1.000`, failed pairs `0`. |
| Real HTTP active-active service-region smoke | 3 real localhost API region processes, each serving a replicated runtime, 2 namespaces, 6 writes, 3 sync cycles, 36 export/import pair calls, cursor count `12`, records imported `36`, tombstones imported `6`, deleted records `6`, final no-op imported `0`, convergence `1.000`, delete suppression `1.000`, success `1.000`, failed pairs `0`, p99 operation `347.58 ms`, SLO `true`. |
| Field-state CRDT | 3 regions, commutative convergence `true`, idempotent re-merge `true`, tombstone-wins `true`, top-key convergence `true`, merge `0.13 ms`. |
| Replicated snapshot job | 3 replica files, manifest checksum validation `true`, offsite mirror validation `true`, portable archive validation `true`, S3-compatible upload validation `true`, latest remote archive metadata validation `true`, remote archive download validation `true`, object-store DR drill `true`, object-store retention pruned `2`, archive restore `64.13 ms`. |
| Structured payloads | image/audio/video/3D/table/event/graph retrieval through the standard memory API, precision@1 `1.000`, p99 `1.81 ms`; cross-modal target-modality retrieval over persisted payload vectors, precision@1 `1.000`, vector persistence `1.000`, provenance rate `1.000`, embedding dim `64`, p99 `4.03 ms`; strict external/precomputed vectors for image/audio/video/3D, precision@1 `1.000`, vector persistence `1.000`, p99 `2.36 ms`. |
| 100M capacity envelope | 100000000 target memories, 32768 deterministic namespace buckets, 128 nodes, 8 zones, replication factor 3, node-loss availability `1.000`, zone-loss availability `1.000`, replica-load skew `1.094`, max storage per node `5.81 GB`, valid capacity plan `true`. |

This profile validates routing, cluster autoscale planning, control-plane
majority lease/config revision safety, Kubernetes deployment, HPA autoscaling,
operator status conditions including `ControlPlaneReady`, and scheduled repair
manifest generation, service-mode distributed namespace sharding, real HTTP
shard transport, sustained mixed HTTP cluster load, replica
repair and tombstone-aware delete repair, plus a reusable anti-entropy repair
worker, quorum-replicated runtime behavior, query-audit cache prewarm,
query-vector cache, Redis-compatible shared rate limiting,
Redis-compatible shared cache behavior, Memory OS shared prewarm, predictive prefetch, production architecture advice, and namespace
invalidation, API cache mutation safety, cursor-based active-active namespace
delta sync, sustained active-active mesh sync, HTTP service-region
active-active sync, real multi-process active-active service-region smoke,
field-only hotness delta sync,
field-state CRDT convergence,
replicated snapshot/restore, structured payload handling,
deterministic cross-modal payload retrieval, external precomputed-vector
compatibility, and provenance,
and a 100M-memory capacity-planning envelope,
including verified offsite, archive, object-store latest lookup, object-store
download, object-store retention, and a disaster recovery drill that restores
the latest object-store archive, disables the restored primary replica, and
confirms recall still works from the remaining replicas.
It is not a 10M-vector load test. Real 100k, 1M, and 10M latency claims should
come from service-backed FAISS/Qdrant/pgvector load tests on production-like
hardware.

Local HTTP cluster smoke:

```sh
python benchmarks/local_http_cluster_smoke.py \
  --nodes 4 \
  --replication-factor 3 \
  --read-fanout 1 \
  --namespace-count 4 \
  --memories-per-namespace 2 \
  --workers 4 \
  --timeout 3 \
  --fail-on-slo
```

This starts 4 real localhost WaveMind API processes with isolated SQLite files,
runs the same service-mode workload through HTTP, and fails if quorum writes,
queries, simulated node failover, missing-replica repair, replicated forget, or
delete suppression regress. The checked-in run reaches success `1.000`,
failover hit `1.000`, delete suppression `1.000`, repaired replicas `1`, and
p99 `257.13 ms`.

Local HTTP active-active service-region smoke:

```sh
python benchmarks/local_http_active_active_smoke.py \
  --regions 3 \
  --replicas-per-region 3 \
  --namespace-count 2 \
  --timeout 3 \
  --fail-on-slo
```

This starts 3 real localhost WaveMind API region processes. Each region serves a
replicated local runtime through FastAPI, then the runner exchanges namespace
deltas through `/namespace-delta/export` and `/namespace-delta/import`. The
checked-in run reaches convergence `1.000`, delete suppression `1.000`, pair
sync success `1.000`, final no-op imports `0`, p99 operation `347.58 ms`, and
SLO `true`.

External HTTP active-active regions:

```sh
python benchmarks/local_http_active_active_smoke.py \
  --region us-east=https://us-east.example.com \
  --region eu-west=https://eu-west.example.com \
  --region ap-south=https://ap-south.example.com \
  --deployment-id staging-active-active-2026-07-07 \
  --environment staging \
  --source k8s-service \
  --namespace-count 16 \
  --fail-on-slo \
  --output benchmarks/external_http_active_active_results.json
```

The same profile is available as the manual GitHub Actions workflow
`external-http-active-active`. It is intentionally tracked as non-gating
external evidence until a real remote artifact is committed; the local service
smoke above is not treated as proof of remote Kubernetes/serverless operation.

External HTTP cluster load:

```sh
python benchmarks/http_cluster_load_benchmark.py \
  --nodes-file deploy/cluster/external-http-cluster.sample.json \
  --replication-factor 3 \
  --read-quorum 1 \
  --read-fanout 1 \
  --namespace-count 32 \
  --memories-per-namespace 8 \
  --workers 8 \
  --fail-on-slo
```

This runs the same mixed workload against user-supplied API nodes: quorum
writes, normal queries, simulated node failover queries, missing-replica repair,
replicated forget, delete suppression, p99 latency, and an explicit SLO verdict.
Use this before claiming that a deployment is production-ready outside the
local readiness smoke profile.
`deploy/cluster/external-http-cluster.sample.json` defines the repeatable node
manifest shape with deployment id, environment, source, node URLs, and zones.
The production readiness gate treats `benchmarks/http_cluster_load_results.json`
as non-gating external evidence and rejects sample/fixture sources.

The same external-cluster profile can be started from GitHub Actions via
`.github/workflows/external-http-cluster-load.yml`. Paste one `id=https://host`
node per line, comma-separated, or semicolon-separated, or paste the node
manifest JSON into `nodes_manifest_json`. Optionally set the `WAVEMIND_API_KEY`
repository secret, and set `commit_results=true` only when the run should
refresh the public benchmark artifacts in `main`.

Cluster placement planning:

```sh
wavemind cluster-plan \
  --namespace-count 4096 \
  --node node-a=10.0.0.1:8000 \
  --node node-b=10.0.0.2:8000 \
  --node node-c=10.0.0.3:8000 \
  --replication-factor 2 \
  --kubernetes \
  --repair-cronjob \
  --repair-api-key-secret wavemind-api-key \
  --json
```

This uses deterministic rendezvous placement so each namespace has a primary
and replica set. The emitted Kubernetes StatefulSet manifest is a deployment
starting point, and the optional repair CronJob runs scheduled service-mode
anti-entropy repair against the same node and namespace plan. Runtime quorum
replication is available through `ReplicatedWaveMind`; cluster membership and
operator config changes can be guarded with the deterministic
`ControlPlaneConsensus` / `wavemind control-plane-consensus` majority lease
preflight. Remote production services should still wrap that contract in a
durable operator/control-plane store.

Control-plane safety preflight:

```sh
wavemind control-plane-consensus --json
```

This deterministic profile verifies the operator-side invariants that prevent
split-brain config changes: majority leadership lease, stale-leader rejection,
stale revision rejection, minority partition rejection, and monotonic config
revisions.

Helm deployment:

```sh
helm install wavemind ./deploy/helm/wavemind
```

For authenticated API nodes, create a Secret and reference it:

```sh
kubectl create secret generic wavemind-auth --from-literal=admin-key="$WAVEMIND_ADMIN_KEY"
helm upgrade --install wavemind ./deploy/helm/wavemind \
  --set auth.enabled=true \
  --set auth.existingSecret=wavemind-auth
```

The chart deploys a StatefulSet, normal and headless Services, optional auth
Secret wiring, a scheduled `cluster-repair` CronJob, and optional Memory OS
CronJobs that call `/memory-os/plan` before `/memory-os/run`. It uses
`ghcr.io/caspiang/wavemind` by default; set `image.repository` when deploying
from a private registry.

```sh
helm upgrade --install wavemind ./deploy/helm/wavemind \
  --set memoryOs.enabled=true \
  --set runtime.auditQueries=1 \
  --set runtime.redisUrl=redis://redis.default.svc.cluster.local:6379/0
```

With `memoryOs.strictPlan=true`, the Memory OS job fails before mutation when
the plan reports `architecture_required`.

Operator-style deployment:

```sh
wavemind operator-bundle --namespace wavemind-system --json | kubectl apply -f -
kubectl apply -f deploy/operator/wavemindcluster.sample.json
wavemind operator-reconcile --file deploy/operator/wavemindcluster.sample.json --out wavemind-resources.json
wavemind operator-status --file deploy/operator/wavemindcluster.sample.json --ready-replicas 3 --json
kubectl apply -f wavemind-resources.json
```

`deploy/operator` contains the `WaveMindCluster` custom resource path. The
bundle installs the CRD with a status subresource, RBAC, operator Deployment,
and a sample cluster. The reconciler renders the concrete Service, headless
Service, StatefulSet, HPA, and repair CronJob resources. `wavemind
operator-status` turns the custom resource plus observed replicas/memory/node
health into Kubernetes-style conditions for resources, capacity, autoscaling,
repair, and control-plane safety. `spec.controlPlane.consensus` is enabled by
default and requires majority leader lease/config revision safety before the
cluster is reported ready. `wavemind operator-loop` can run in-cluster to keep
resources applied and patch the `WaveMindCluster.status` subresource when the
Kubernetes client supports it.

The operator also accepts capacity targets. Add this to `spec.autoscaling` and
the reconciler will raise the StatefulSet replicas and HPA min/max replicas to
fit the target under the requested per-node headroom:

```json
{
  "enabled": true,
  "targetMemories": 10000000,
  "maxMemoriesPerNode": 1000000,
  "headroom": 0.7
}
```

Rendered resources include `memory.wavemind.ai/capacity-*` annotations with the
calculated replica count and target max node load.

The same planner is available over HTTP as `POST /cluster-plan`.

Cluster autoscale planning:

```sh
wavemind cluster-autoscale-plan \
  --namespace-count 4096 \
  --node node-a=https://wm-a.internal \
  --node node-b=https://wm-b.internal \
  --node node-c=https://wm-c.internal \
  --replication-factor 3 \
  --target-memories 10000000 \
  --max-memories-per-node 1000000 \
  --headroom 0.70 \
  --zone zone-a --zone zone-b --zone zone-c \
  --json
```

This calculates the required node count for the target memory volume, adds
future nodes with deterministic names and addresses, checks the target max
per-node memory load against the headroom limit, and returns a bounded sample
of namespace moves. The HTTP surface is `POST /cluster-autoscale-plan`.

Serverless deployment:

```sh
wavemind serverless-sample --namespace wavemind-system --max-scale 256 --out deploy/serverless/wavemind-serverless.sample.json
wavemind serverless-sample --readiness
wavemind serverless-sample --operational-profile --max-scale 256 --target-concurrency 80
wavemind serverless-sample --operational-profile --max-scale 256 --target-concurrency 80 --observed-telemetry deploy/serverless/observed-telemetry.loopback.json
python benchmarks/serverless_observed_telemetry_benchmark.py --node https://wm-a.example --node https://wm-b.example --api-key "$WAVEMIND_API_KEY" --seed-mode first --external-cold-start-ms 900 --output deploy/serverless/observed-telemetry.remote.json
```

`deploy/serverless` contains a stateless API worker plan with two profiles: a
Knative scale-to-zero `Service`, and a KEDA `Deployment`/`Service`/`ScaledObject`
profile where the autoscaler targets the generated Deployment. It is
intentionally stricter than local mode: Postgres is required as the source of
truth, Qdrant is used as the external candidate index, Redis is used for shared
hot-query cache, and API keys are read from Kubernetes Secrets. This path is the
current foundation for scale-to-zero and managed/serverless deployments; it is
not a claim that WaveMind has a hosted control plane yet.

The scale-readiness gate also runs a deterministic serverless operational
profile: 3200 requests/second, 80 ms average request time, 320 ms warm p99,
900 ms modeled cold start, 4 required replicas, 256000 burst RPS capacity,
cold-start budget pass, and estimated monthly compute cost `$81.76`. The
checked-in observed telemetry is generated by
`benchmarks/serverless_observed_telemetry_benchmark.py`: it starts a balanced
pool of real local WaveMind HTTP API replicas, seeds and warms the hot-query
cache on each replica, measures pool RPS, per-replica RPS, p95/p99/error
rate/cold start, and multiplies measured per-replica throughput by
`max_scale=256` for the Knative/KEDA horizontal capacity estimate. This is
loopback evidence, not a real-cluster performance claim. The same runner also
accepts repeated `--node https://...` URLs, `--api-key`, `--seed-mode first`,
and `--external-cold-start-ms` so the identical telemetry JSON contract can be
run against real Knative/KEDA, Kubernetes, or managed serverless API nodes
before publishing managed serverless numbers.

Maintenance workers:

```sh
wavemind maintenance --namespace user:42 --consolidate-steps 10 --consolidate-concepts --json
wavemind memory-os-plan --namespace user:42 --deployment production --target-memories 2000000 --namespace-count 4096 --cache-mode auto --json
wavemind memory-os --namespace user:42 --redis-url redis://localhost:6379/0 --min-frequency 2 --max-hot-queries 32 --json
wavemind cluster-health --node node-a=https://wm-a.internal --node node-b=https://wm-b.internal --node node-c=https://wm-c.internal --replication-factor 3 --read-quorum 1 --read-fanout 1 --api-key "$WAVEMIND_API_KEY" --fail-on-degraded --json
wavemind cluster-repair --node node-a=https://wm-a.internal --node node-b=https://wm-b.internal --node node-c=https://wm-c.internal --namespace user:42 --replication-factor 3 --write-quorum 2 --read-quorum 1 --read-fanout 1 --api-key "$WAVEMIND_API_KEY" --json
wavemind cluster-plan --namespace-count 4096 --node node-a=https://wm-a.internal --node node-b=https://wm-b.internal --node node-c=https://wm-c.internal --replication-factor 3 --repair-cronjob --repair-api-key-secret wavemind-api-key --json
wavemind replicated-snapshot --root ./state/replicas --node node-a --node node-b --node node-c --out ./backups/replicated --offsite ./offsite/replicated --archive ./archives/replicated --s3 s3://my-bucket/wavemind/prod --keep-last 7 --s3-keep-last 30 --json
wavemind replicated-drill --from s3://my-bucket/wavemind/prod --to ./state/drill-restore --query "short support replies" --expect-text "Tenant A prefers short support replies." --json
```

The first command runs one deterministic memory pass: expired-memory purge,
optional field/concept consolidation, and index-health repair. The `memory-os`
command is the adaptive worker: it reads query audit events, identifies hot
queries, warms Redis/local cache, generates predictive neighbor queries from
the top recalled memories, predicts bounded priority boosts from usage
patterns, demotes cold unused memories with bounded adaptive forgetting, purges
expired memories, consolidates active clusters into durable concept memories,
checks index health, and returns operator-facing recommendations. When given
production targets such as `--target-memories`, `--namespace-count`,
`--deployment production`, and `--multimodal`, it also embeds the same
architecture-advisor output used by release readiness gates: service-index,
namespace-sharding, production-controls, replication capacity, load-test, and
multimodal-readiness actions. The cluster-health command probes every
WaveMind API node, exposes healthy/degraded/unavailable circuit state, and can
fail deployment preflight when any node is degraded. The cluster-repair command runs service-mode
anti-entropy repair across WaveMind API nodes:
missing replica records are copied back, and tombstoned stale records are
deleted instead of resurrected. The cluster-plan command emits a Kubernetes CronJob
for that repair loop. The snapshot command creates a verified replicated snapshot,
mirrors it to an offsite path,
writes a portable `.tar.gz` archive, verifies that archive, can upload it to an
S3-compatible object store, verify newest-archive metadata, run an object-store
disaster-recovery drill, and apply local and object-store retention. Production
deployments can call these commands from cron, systemd, Kubernetes CronJobs,
Celery, RQ, or Temporal.

The `memory-os-plan` command is the read-only scheduler preflight for that
worker set. It inspects current stats and audited query traffic without
mutating memory, then emits concrete task cadences, worker counts, Redis/shared
cache requirements, distributed-lock requirements, and exact commands for
`memory-os`, `cache-prewarm`, consolidation, forgetting, maintenance, and
architecture-advice loops. In production mode it automatically promotes
`--cache-mode auto` to Redis when QPS, namespace count, memory count, or hot
query volume require cross-worker cache sharing.

Hot-cache options:

| cache | use case |
|---|---|
| `HotMemoryCache` | in-process local API/server cache. |
| `RedisHotMemoryCache` | shared cache for multiple API workers. Install with `pip install "wavemind[redis]"`. |
| `QueryVectorCache` | in-process cache for encoded query vectors when the encoder is expensive. |
| `RedisQueryVectorCache` | shared encoded-query-vector cache across API workers. |

API cache can be enabled with:

```sh
WAVEMIND_CACHE_CAPACITY=512 WAVEMIND_CACHE_TTL_SECONDS=60 wavemind serve
```

For multiple API workers, use a shared Redis cache:

```sh
WAVEMIND_REDIS_URL=redis://localhost:6379/0 WAVEMIND_AUDIT_QUERIES=1 wavemind serve
```

For repeated natural-language queries with a semantic encoder, cache encoded
query vectors separately from full query results:

```sh
WAVEMIND_VECTOR_CACHE_CAPACITY=1024 WAVEMIND_VECTOR_CACHE_TTL_SECONDS=300 wavemind serve
WAVEMIND_VECTOR_CACHE_REDIS_URL=redis://localhost:6379/0 wavemind serve
```

To verify the live multi-process cache path against a real Redis service:

```sh
python benchmarks/redis_api_load_benchmark.py --redis-url redis://localhost:6379/0 --workers 2 --requests 40 --fail-on-slo
```

For production workers, enable query audit and prewarm the cache from repeated
real queries:

```sh
WAVEMIND_AUDIT_QUERIES=1 WAVEMIND_CACHE_CAPACITY=512 wavemind serve
wavemind --audit-queries query "budget preference" --namespace demo
curl -X POST http://127.0.0.1:8000/cache/prewarm -H "x-api-key: $WAVEMIND_ADMIN_KEY" -d '{"min_frequency":2,"max_queries":32}'
wavemind cache-prewarm --redis-url redis://localhost:6379/0 --min-frequency 2 --max-queries 32
```

The same path is available in Python through `CachePrewarmWorker`. The CLI can
also run with a process-local cache for diagnostics, but production prewarm
should use Redis so warmed entries survive the worker process. Query audit
stores query text, so keep it opt-in for deployments with stricter privacy
requirements.

## Structured And Multimodal Memory

WaveMind can store non-text memories as structured text plus metadata. This is
useful for product events, tables, call transcripts, images, videos, 3D assets,
and knowledge graphs while keeping the same query API.

```python
from wavemind import WaveMind, image_payload, remember_payload

memory = WaveMind()
remember_payload(
    memory,
    image_payload("s3://demo/chart.png", caption="enterprise revenue expansion chart"),
    namespace="research",
)
print(memory.query("enterprise expansion chart", namespace="research")[0].metadata)
```

For agent workflows that need one memory layer across payload types, use
`CrossModalMemoryLayer`. It stores typed payloads through WaveMind, keeps
provenance in metadata, and re-ranks by a shared deterministic descriptor
embedding so queries can target one modality without changing the underlying
storage.

```python
from wavemind import CrossModalMemoryLayer, WaveMind, audio_payload, image_payload

memory = WaveMind()
layer = CrossModalMemoryLayer(memory)

layer.remember(image_payload("s3://demo/chart.png", caption="Q2 revenue chart"), namespace="research")
layer.remember(audio_payload("s3://demo/call.wav", transcript="Customer asked about Q2 revenue"), namespace="research")

for result in layer.query("revenue chart", namespace="research", target_modality="image"):
    print(result.modality, result.score, result.provenance)
```

If your application already computes CLIP/audio/video/3D embeddings, use the
strict precomputed-vector path. WaveMind stores the vector with the payload and
requires a query vector at search time, so there is no hidden descriptor
fallback:

```python
from wavemind import CrossModalMemoryLayer, PrecomputedCrossModalEncoder, WaveMind, image_payload

memory = WaveMind()
layer = CrossModalMemoryLayer(
    memory,
    cross_modal_encoder=PrecomputedCrossModalEncoder(vector_dim=512, name="clip"),
)

layer.remember(
    image_payload(
        "s3://demo/chart.png",
        caption="Q2 revenue chart",
        metadata={"cross_modal_vector": image_clip_vector},
    ),
    namespace="research",
)
results = layer.query(
    "revenue chart",
    namespace="research",
    target_modality="image",
    query_vector=text_clip_vector,
)
```

For a built-in CLIP-style image/text backend, install the multimodal extra:

```sh
python -m pip install "wavemind[multimodal]"
```

```python
from wavemind import CrossModalMemoryLayer, SentenceTransformersCrossModalEncoder, WaveMind, image_payload

memory = WaveMind()
layer = CrossModalMemoryLayer(
    memory,
    cross_modal_encoder=SentenceTransformersCrossModalEncoder("clip-ViT-B-32"),
)

layer.remember(
    image_payload("chart.png", caption="Q2 revenue chart"),
    namespace="research",
)
results = layer.query("revenue chart", namespace="research", target_modality="image")
```

This backend loads local image files with Pillow and encodes text queries through
the same sentence-transformers model. Remote assets, audio, video, and 3D
payloads should either carry strong text descriptors or use the precomputed
vector path until dedicated perception backends are benchmarked.

Supported payload helpers:

| helper | use case |
|---|---|
| `image_payload()` | image URI plus caption or alt text |
| `audio_payload()` | audio URI plus transcript or summary |
| `video_payload()` | video URI plus transcript, scenes, duration, and summary |
| `asset3d_payload()` | 3D model URI plus labels, dimensions, and format |
| `table_payload()` | compact table preview with row count |
| `event_payload()` | structured product, user, or system event |
| `graph_payload()` | knowledge graph triples stored as queryable memory |

## Storage Backends

SQLite is the default source of truth. For multi-tenant production deployments,
WaveMind also exposes PostgreSQL as an explicit source-of-truth backend:

```sh
export WAVEMIND_STORE="postgres"
export WAVEMIND_POSTGRES_DSN="postgresql://user:password@localhost:5432/wavemind"
wavemind --store postgres remember "Andrey is a trader" --namespace user:andrey
wavemind --store postgres query "trader" --namespace user:andrey
```

Optional table environment variables:

- `WAVEMIND_POSTGRES_MEMORIES_TABLE`, default `wavemind_memories`.
- `WAVEMIND_POSTGRES_AUDIT_TABLE`, default `wavemind_audit_events`.

Postgres storage is separate from `pgvector`: Postgres storage keeps memories,
metadata, TTL, audit events, and vectors as durable application state; pgvector
is a candidate index backend for nearest-neighbor search. You can use SQLite
storage with pgvector, Postgres storage with NumPy/FAISS/Qdrant, or eventually
Postgres storage plus pgvector when you want both state and vector search inside
PostgreSQL.

## Backup And Restore

Exact one-file backup:

```sh
wavemind --db ./state/wavemind.sqlite3 backup --out ./backups/wavemind.sqlite3
```

Timestamped backups with retention:

```sh
wavemind --db ./state/wavemind.sqlite3 backup --out ./backups --prefix wavemind --keep-last 7
```

Restore into a new or replacement SQLite file:

```sh
wavemind restore --from ./backups/wavemind-20260630-120000.sqlite3 --to ./state/wavemind.sqlite3 --overwrite
```

The backup command uses SQLite's backup API, so it is safe to run while the
process is alive. Restore is intentionally an explicit command and refuses to
overwrite an existing database unless `--overwrite` is passed.
For Postgres storage, use database-native backup tooling such as `pg_dump`,
managed snapshots, or point-in-time recovery instead of WaveMind's SQLite file
backup command.

Replicated runtime snapshot/restore:

```python
from wavemind import HashingTextEncoder, ReplicatedSnapshotWorker, ReplicatedWaveMind

memory = ReplicatedWaveMind(
    root_path="./state/replicas",
    nodes=["node-a", "node-b", "node-c"],
    replication_factor=3,
    encoder=HashingTextEncoder(vector_dim=64),
)
memory.remember("Tenant A prefers short support replies.", namespace="tenant:a")

snapshot_job = ReplicatedSnapshotWorker(memory).run_once(
    destination="./backups/replicated",
    offsite_destination="./offsite/replicated",
    archive_destination="./archives/replicated",
    object_store_destination="s3://my-bucket/wavemind/prod",
    keep_last=7,
    object_store_keep_last=30,
)
assert snapshot_job.ok

restored, report = ReplicatedWaveMind.restore_snapshot_archive(
    snapshot_job.archive_path,
    "./state/restored-replicas",
    encoder=HashingTextEncoder(vector_dim=64),
)
```

The replicated snapshot job writes one SQLite backup per replica plus
`manifest.json` with SHA-256 checksums, replica metadata, quorum settings, and
node definitions. It can mirror the snapshot to a second path for offsite
backup, write a portable `.tar.gz` archive for object-store/offsite systems,
verify that archive, upload it to any S3-compatible object store through
`boto3`, list the newest remote archive, restore from the newest remote archive,
run a disaster-recovery drill from the newest or exact remote archive, and apply
`keep_last` retention locally, offsite, for archives, and explicitly for
object-store archives through `object_store_keep_last`.
Restore refuses to overwrite a non-empty root unless `overwrite=True` is passed.

Equivalent CLI:

```sh
wavemind replicated-snapshot \
  --root ./state/replicas \
  --node node-a --node node-b --node node-c \
  --out ./backups/replicated \
  --offsite ./offsite/replicated \
  --archive ./archives/replicated \
  --s3 s3://my-bucket/wavemind/prod \
  --keep-last 7 \
  --s3-keep-last 30 \
  --json

wavemind replicated-s3-archives \
  --s3 s3://my-bucket/wavemind/prod \
  --latest \
  --json

wavemind replicated-restore \
  --from ./archives/replicated/wavemind-replicated-20260705-120000.tar.gz \
  --to ./state/restored-replicas \
  --overwrite \
  --json

wavemind replicated-restore \
  --from s3://my-bucket/wavemind/prod \
  --latest \
  --to ./state/restored-replicas \
  --overwrite \
  --json

wavemind replicated-drill \
  --from s3://my-bucket/wavemind/prod \
  --to ./state/drill-restore \
  --query "short support replies" \
  --expect-text "Tenant A prefers short support replies." \
  --json
```

Install S3/R2/MinIO support with `pip install "wavemind[s3]"`. For
S3-compatible endpoints such as Cloudflare R2 or MinIO, pass
`--s3-endpoint-url` and optionally `--s3-region`.

## HTTP API

Run the local FastAPI server:

```sh
wavemind --db ./app_memory.sqlite3 serve --host 127.0.0.1 --port 8000
```

Store and query memory over HTTP:

```sh
curl -X POST http://127.0.0.1:8000/remember -H "Content-Type: application/json" -d "{\"text\":\"Andrey is a trader\",\"namespace\":\"demo\"}"
curl -X POST http://127.0.0.1:8000/query -H "Content-Type: application/json" -d "{\"query\":\"trader\",\"namespace\":\"demo\",\"top_k\":1}"
```

Operational endpoints:

```sh
curl http://127.0.0.1:8000/stats?namespace=demo
curl http://127.0.0.1:8000/audit?namespace=demo
curl http://127.0.0.1:8000/metrics
curl http://127.0.0.1:8000/observability
curl http://127.0.0.1:8000/index/health
curl "http://127.0.0.1:8000/scale-plan?target_memories=50000"
curl -X POST http://127.0.0.1:8000/index/rebuild
curl -X POST http://127.0.0.1:8000/consolidate -H "Content-Type: application/json" -d '{"namespace":"demo","seed_text":"Rust compiler systems","min_energy":0.01}'
curl -X POST http://127.0.0.1:8000/backup -H "Content-Type: application/json" -d '{"path":"./backups","keep_last":7}'
```

`/audit` returns mutation events such as `remember`, `forget`, `backup`, and
`consolidate_concept`. Query audit is opt-in with `WAVEMIND_AUDIT_QUERIES=1` because
writing an audit row for every query changes latency. `/metrics` returns a
Prometheus-compatible text payload without adding a required dependency.
`/index/health` reports source-of-truth versus candidate-index consistency.
`/index/rebuild` rebuilds the candidate index from stored active memories and
logs an `index_rebuild` audit event.

Full observability guide and local Prometheus/OTEL examples:
[`docs/OBSERVABILITY.md`](docs/OBSERVABILITY.md).

OpenTelemetry traces are optional and off by default:

```sh
pip install "wavemind[otel]"
export WAVEMIND_OTEL_ENABLED=1
export WAVEMIND_OTEL_SERVICE_NAME=wavemind-api
export WAVEMIND_OTEL_EXPORTER=otlp
export WAVEMIND_OTEL_ENDPOINT="http://localhost:4318/v1/traces"
wavemind --db ./app_memory.sqlite3 serve --host 127.0.0.1 --port 8000
```

Use `WAVEMIND_OTEL_EXPORTER=console` for local trace inspection. FastAPI
requests are instrumented, and core memory phases such as encode, index search,
graph propagation, reranking, load, and backup create spans when OpenTelemetry
is enabled.

Production API controls are opt-in:

```sh
export WAVEMIND_READ_KEYS="read-key"
export WAVEMIND_WRITE_KEYS="write-key"
export WAVEMIND_ADMIN_KEYS="admin-key"
export WAVEMIND_RATE_LIMIT_PER_MINUTE=120
export WAVEMIND_API_SERIALIZE_OPERATIONS=1
```

For multiple API workers, use a shared Redis rate-limit bucket:

```sh
export WAVEMIND_RATE_LIMIT_PER_MINUTE=120
export WAVEMIND_RATE_LIMIT_REDIS_URL=redis://localhost:6379/0
export WAVEMIND_RATE_LIMIT_REDIS_PREFIX=wavemind:rate
```

`WAVEMIND_API_SERIALIZE_OPERATIONS=1` is the default. It keeps one in-process
FastAPI worker from running concurrent operations through the same local
WaveMind/SQLite runtime. Set it to `0` only when the backing store and index
path are safe for concurrent in-process access.

Role behavior:

| role | Env var | Allows |
|---|---|---|
| read | `WAVEMIND_READ_KEYS` | `/query`, `/stats`, `/metrics`, `/index/health` |
| write | `WAVEMIND_WRITE_KEYS` | read actions plus `/remember` and `/import` |
| admin | `WAVEMIND_ADMIN_KEYS` or `WAVEMIND_API_KEYS` | all actions, including `/audit`, `/backup`, `/index/rebuild`, and `/forget` |

Keys are accepted through `Authorization: Bearer <key>` or `X-API-Key: <key>`.
If no key env vars are set, authentication is disabled for local development.

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

Install the optional integration:

```sh
pip install "wavemind[langchain]"
```

Use WaveMind as a drop-in LangChain memory object:

```python
from wavemind.integrations.langchain import WaveMindMemory

memory = WaveMindMemory(db_path="agent_memory.sqlite3")
# Replace: memory = ConversationBufferMemory()
```

Offline runnable example from a cloned repository:

```sh
python examples/langchain_memory.py
```

## Framework Integrations

WaveMind only needs two touch points in an agent, service, notebook, or app:

1. Before work happens, `query()` for relevant memory and pass the short result
   into the next step: a prompt, search screen, tool call, support workflow, or
   decision function.
2. After work happens, `remember()` durable facts, preferences, summaries,
   outcomes, corrections, or notes.

That makes it usable in more than LangChain:

| Use case | Integration style |
|---|---|
| LangChain agent | Use `WaveMindMemory` from `wavemind.integrations.langchain`. |
| LangGraph workflow | Use `make_recall_node()` and `make_persist_node()` from `wavemind.integrations.langgraph`. |
| LlamaIndex pipeline | Use `WaveMindRetriever` from `wavemind.integrations.llamaindex`. |
| CrewAI crew | Use `WaveMindCrewAITools` from `wavemind.integrations.crewai`. |
| AutoGen loop | Use `WaveMindAutoGenMemory` from `wavemind.integrations.autogen`. |
| Custom Python agent | Create one `WaveMind` instance and call `query()` before the LLM. |
| Node, Go, Ruby, PHP, or no-code app | Run `wavemind serve` and call the HTTP API. |
| Multi-user SaaS | Use `namespace="user:<id>"` or `namespace="tenant:<id>:agent:<id>"`. |
| Knowledge base or notebook | Store notes by project namespace and retrieve a small evidence set. |
| Support or CRM workflow | Store issues, preferences, resolutions, and corrections with tags. |
| Research workflow | Store observations with source metadata and expire temporary hypotheses. |
| Temporary context | Store with `ttl_seconds=...` so stale memory expires automatically. |
| Preference/profile memory | Store with tags such as `profile`, `preference`, `project`, `decision`. |
| Corrections/privacy | Use `forget()` or namespace deletion workflows. |

More examples: [`docs/USE_CASES.md`](docs/USE_CASES.md).
Migrating from a Chroma memory store: [`docs/CHROMA_MIGRATION.md`](docs/CHROMA_MIGRATION.md).

Framework examples in this repository:

| Framework / pattern | Example |
|---|---|
| LangChain memory | `examples/langchain_memory.py` |
| OpenAI/OpenRouter-style agent loop | `examples/agent_with_memory.py` |
| LangGraph hooks | `wavemind.integrations.langgraph`, `examples/framework_integrations.py` |
| LlamaIndex-style retriever | `wavemind.integrations.llamaindex`, `examples/llamaindex_retriever.py` |
| CrewAI-style tools | `wavemind.integrations.crewai`, `examples/framework_integrations.py` |
| AutoGen-style hooks | `wavemind.integrations.autogen`, `examples/framework_integrations.py` |
| Namespace sharding | `examples/sharded_memory.py` |

Run the dedicated offline LlamaIndex-style retriever example:

```sh
python examples/llamaindex_retriever.py
```

## OpenClaw Integration

[OpenClaw memory](https://docs.openclaw.ai/concepts/memory) is file-centered:
it writes durable memory into `MEMORY.md`, daily notes under `memory/`, and uses
tools such as `memory_search` / `memory_get`. OpenClaw's documented agent loop
also exposes hooks such as `before_prompt_build`, `agent_end`,
`message_received`, and `message_sent`.

The safest WaveMind integration is a sidecar, not a replacement:

- Keep OpenClaw's Markdown memory as the human-readable source of durable truth.
- Use WaveMind as the dynamic recall layer for hotness, TTL, namespaces, and
  correction-sensitive ranking.
- Store the SQLite file outside committed workspace files, for example
  `~/.openclaw/wavemind/<agent-id>.sqlite3`.
- Query WaveMind from `before_prompt_build` and inject a compact memory block
  with `prependContext`.
- Capture new durable summaries from `agent_end` or message hooks.

Sketch of the adapter logic:

```python
from pathlib import Path
from wavemind import WaveMind

db_path = Path.home() / ".openclaw" / "wavemind" / "main.sqlite3"
memory = WaveMind(db_path=db_path)

def before_prompt_build(agent_id: str, user_text: str) -> str:
    namespace = f"openclaw:{agent_id}"
    hits = memory.query(user_text, namespace=namespace, top_k=5, min_score=0.25)
    return "\n".join(f"- {hit.text}" for hit in hits)

def agent_end(agent_id: str, summary: str) -> None:
    namespace = f"openclaw:{agent_id}"
    memory.remember(summary, namespace=namespace, tags=["summary"], priority=1.5)
```

For a production OpenClaw plugin, translate that sketch into the documented
plugin hook surface: `before_prompt_build` for recall and `agent_end` /
`message_received` / `message_sent` for capture.

## Hermes and Custom Agent Loops

The public [HERMES Agent](https://github.com/aziksh-ospanov/HERMES) is a
LangChain / LangGraph mathematical-reasoning agent. Its README describes
`HermesReasoner` as a LangChain `BaseTool` and mentions an optional in-memory
embedding store for previously verified claims.

WaveMind fits there as a persistent memory layer around that loop:

- Recall previously verified claims before `HermesReasoner` is invoked.
- Store successfully verified claims with `tags=["verified-claim"]`.
- Scope by `user_id`, project, benchmark, or theorem namespace.
- Replace short-lived in-memory vector recall when the agent needs restarts,
  TTL, explicit forgetting, or cross-session reuse.

Generic Hermes-style loop:

```python
from wavemind import WaveMind

memory = WaveMind(db_path="./state/hermes_claims.sqlite3")

def verify_with_memory(user_id: str, problem: str) -> str:
    namespace = f"hermes:{user_id}"
    claims = memory.query(problem, namespace=namespace, tags=["verified-claim"], top_k=5)
    context = "\n".join(f"- {claim.text}" for claim in claims)

    result = call_hermes_reasoner(problem=problem, extra_context=context)

    if result.label == "CORRECT":
        memory.remember(result.claim, namespace=namespace, tags=["verified-claim"], priority=2.0)
    return result.text
```

For any other agent framework, the rule is the same: recall before the model,
capture after the turn, isolate users with namespaces, and use TTL for temporary
facts.

## Non-Agent Use Cases

WaveMind can store any small-to-medium memory stream where meaning, freshness,
and repeated use matter. It is useful when "show me the nearest text" is not
enough and the application needs "show me what is relevant now."

| Use case | Example |
|---|---|
| Support memory | Recall past user issues, plans, bugs, and resolutions. |
| Product research | Store interview snippets with `tags=["customer", "pain"]`. |
| Team knowledge | Remember project decisions and suppress expired decisions with TTL. |
| Personal assistant | Store preferences, routines, people, and recurring context. |
| Game/NPC memory | Give characters scoped memory that strengthens after repeated events. |
| Trading research | Store labeled OHLCV pattern notes before building a backtest layer. |
| Document notebook | Import text/PDF/JSON chunks and query by namespace/project. |
| Personal knowledge base | Keep decisions, recurring context, people, links, and notes searchable without sending them to a hosted vector DB. |

## Why Dynamic Memory

WaveMind is not positioned as "a faster Chroma." Chroma, Qdrant, Pinecone, and
Weaviate are vector databases: they store embeddings and return nearest
neighbors. That is the right tool for many static RAG workloads.

WaveMind is a dynamic memory layer. It still uses vector search first, but then
applies memory-specific signals that a plain vector store does not model by
default:

| memory behavior | Why it matters | WaveMind mechanism |
|---|---|---|
| Hot memories | Information that keeps being useful should become easier to recall again. | Wave-field hotness and priority updates. |
| Aging memories | Old low-value facts should fade instead of competing forever. | TTL and decay-aware scoring. |
| Scoped memory | One user, app, workspace, or project should not leak into another. | Namespaces and tags. |
| Explicit forgetting | Real systems need deletion, privacy cleanup, and correction workflows. | `forget()` plus SQLite persistence. |
| Stable restart behavior | A memory system must survive process restarts. | SQLite source of truth, reloadable indexes. |
| Vector plus memory rank | Semantic similarity is necessary but not sufficient for long-running memory. | k-NN candidates first, wave field as re-ranker. |

The current Chroma benchmark below is intentionally conservative: it compares
static retrieval on the same facts and the same hash embeddings. That benchmark
is useful, but it does not exercise WaveMind's main thesis: memory that changes
over time as software recalls, reinforces, ages, and forgets information.

The benchmark that should decide whether WaveMind is worth using is a dynamic
memory benchmark:

| scenario | What should happen |
|---|---|
| A fact, preference, or decision is used many times. | WaveMind should rank it higher than equally similar but unused facts. |
| A fact expires via TTL. | WaveMind should suppress it without requiring manual vector cleanup. |
| A user or system corrects an old fact. | WaveMind should prefer the newer or reinforced memory. |
| A query is ambiguous across namespaces. | WaveMind should return only the scoped user's memory. |
| A long history has many irrelevant facts. | WaveMind should preserve useful recall instead of treating all vectors equally. |

In short: static vector search answers "what is nearest?" Dynamic memory also
asks "what is still relevant, reinforced, scoped, and allowed to be remembered?"

## Research Branches

The main branch stays focused on the core WaveMind library: dynamic memory,
storage, indexes, APIs, integrations, and public memory benchmarks.

Experimental domains live in separate branches so they can move quickly without
overloading the main README:

| Branch | Scope |
|---|---|
| [`research/crypto-pattern-memory`](https://github.com/CaspianG/wavemind/tree/research/crypto-pattern-memory) | OHLCV pattern-memory research, historical analogue retrieval, and future backtest experiments. |

## Benchmark

WaveMind tracks benchmarks in two layers:

- **Implemented local checks** - fast, reproducible scripts that run from this repository and protect the core memory behavior.
- **Public benchmark roadmap** - external retrieval and memory benchmarks that should decide whether WaveMind is competitive outside hand-made demos.

Machine-readable benchmark matrix: `benchmarks/benchmark_matrix_results.json`.
Full generated benchmark report: [`benchmarks/BENCHMARK_REPORT.md`](benchmarks/BENCHMARK_REPORT.md).
Compact benchmark leaderboard: [`benchmarks/BENCHMARK_LEADERBOARD.md`](benchmarks/BENCHMARK_LEADERBOARD.md).
Living HTML dashboard: [`docs/benchmark-dashboard.html`](docs/benchmark-dashboard.html).
Production readiness gate: [`benchmarks/PRODUCTION_READINESS.md`](benchmarks/PRODUCTION_READINESS.md)
from `benchmarks/production_readiness_results.json`.
Strict production evidence gate: [`benchmarks/PRODUCTION_EVIDENCE.md`](benchmarks/PRODUCTION_EVIDENCE.md)
from `benchmarks/production_evidence_results.json`. This is the hard boundary
for remote multi-region, managed-serverless, 50M, and 100M scale claims.
Large-N service plans include resumable `--checkpoint-path` commands so
interrupted 10M/50M/100M ingest runs can continue from completed batches instead
of restarting from zero.
CLI preflight: `wavemind production-evidence --strict`.
Weekly benchmark refresh: `.github/workflows/benchmark-leaderboard.yml` reruns
the fast benchmark profiles, regenerates the benchmark matrix/report/leaderboard
`docs/assets/benchmark-summary.svg`, `docs/benchmark-dashboard.html`, the
production-readiness report, and the strict production-evidence report,
validates freshness with `benchmarks/validate_benchmark_artifacts.py`, writes
`benchmarks/benchmark_artifact_audit.json`, and commits changed benchmark artifacts
back to `main`.
`full-check` and the release workflow also run the same freshness gate with
`--max-age-days 8`, so stale or manually edited public benchmark artifacts block
normal CI and package releases.
External cluster benchmark refresh: `.github/workflows/external-http-cluster-load.yml`
runs `benchmarks/http_cluster_load_benchmark.py` against real API-node URLs or a
JSON node manifest and can commit `benchmarks/http_cluster_load_results.json`
plus refreshed leaderboard artifacts when `commit_results=true`.
External active-active refresh: `.github/workflows/external-http-active-active.yml`
runs `benchmarks/local_http_active_active_smoke.py` against real API-region URLs
or a JSON region manifest and can commit
`benchmarks/external_http_active_active_results.json` plus refreshed
leaderboard/readiness artifacts when `commit_results=true`.
Remote serverless telemetry refresh: `.github/workflows/serverless-observed-telemetry.yml`
runs `benchmarks/serverless_observed_telemetry_benchmark.py` against deployed
HTTP/HTTPS API node URLs, uploads `deploy/serverless/observed-telemetry.remote.json`,
and can commit the remote telemetry plus refreshed leaderboard/readiness
artifacts when `commit_results=true`. When that remote file exists,
`benchmarks/scale_readiness_benchmark.py` prefers it over the checked-in
loopback telemetry.

### Current Evidence Status

The compact leaderboard now carries an explicit evidence-status table:
[`benchmarks/BENCHMARK_LEADERBOARD.md`](benchmarks/BENCHMARK_LEADERBOARD.md).
Use that generated file for exact current numbers. This README keeps the
public claim boundaries stable:

| Claim area | Current public status | Source of truth | Not proven yet |
|---|---|---|---|
| Production readiness | WaveMind core readiness is gated by checked-in artifacts before release. | `benchmarks/production_readiness_results.json`, `benchmarks/PRODUCTION_READINESS.md` | Missing external competitor credentials should not be treated as WaveMind core failure, but they still limit competitor claims. |
| Strict production evidence | Remote service-node, active-active, serverless, 10M service, 50M, and 100M claims are separated into a hard evidence gate. | `benchmarks/production_evidence_results.json`, `benchmarks/PRODUCTION_EVIDENCE.md`, `benchmarks/production_evidence_gate.py`, `wavemind production-evidence --strict` | Current status remains action-required until real remote/service artifacts are committed. |
| 10M memory-scale profile | Checked-in compressed FAISS IVF-PQ streaming profile exists and is reported in the generated leaderboard. | `benchmarks/production_streaming_load_ivfpq_10m_results.json` | Not yet a completed 10M Qdrant/pgvector service comparison. |
| 50M memory-scale preflight | Checked-in plan-only artifact estimates local index/transient storage, application storage, required env, blockers, and exact resumable reproduction command with checkpointing. | `benchmarks/production_streaming_load_50m_plan.json` | Not a completed latency/recall benchmark until `production_streaming_load_ivfpq_50m_results.json` is produced by a real run. |
| pgvector tuning | Real PostgreSQL/pgvector service profile now separates baseline HNSW, exact recall floor, and iterative HNSW tuning. | `benchmarks/production_pgvector_tuning_results.json` | This is a 50k service-backed tuning profile, not yet the 100k/1M production load SLO artifact. |
| Qdrant streaming | Real Qdrant streaming smoke exists, a tuned 1M service run passes SLO after warmup/chunking, a real two-service sharded Qdrant smoke passes, and single-service plus horizontally sharded 10M/100M plan-only contracts are checked in. | `benchmarks/production_streaming_load_qdrant_smoke_results.json`, `benchmarks/production_streaming_load_qdrant_1m_results.json`, `benchmarks/production_streaming_load_qdrant_1m_tuned_results.json`, `benchmarks/production_streaming_load_qdrant_sharded_smoke_results.json`, `benchmarks/production_streaming_load_qdrant_10m_plan.json`, `benchmarks/production_streaming_load_qdrant_sharded_10m_plan.json`, `benchmarks/production_streaming_load_qdrant_sharded_100m_plan.json` | The 10M/100M Qdrant service results are not claimed until the matching result artifacts are produced by real runs. |
| pgvector streaming | Real PostgreSQL/pgvector streaming smoke exists, and a 10M plan-only service contract is checked in. | `benchmarks/production_streaming_load_pgvector_smoke_results.json`, `benchmarks/production_streaming_load_pgvector_10m_plan.json` | The 10M pgvector service result is not claimed until `production_streaming_load_pgvector_10m_results.json` is produced by a real run. |
| HTTP cluster load | Local multi-process API-node evidence exists; the external workflow can run the same contract against real API URLs. | `benchmarks/http_cluster_load_results.json`, `.github/workflows/external-http-cluster-load.yml` | Local loopback evidence is not a remote Kubernetes or multi-region production result. |
| HTTP active-active regions | Local multi-process API-region evidence exists; the external workflow can run the same namespace-delta contract against real regional API URLs. | `benchmarks/local_http_active_active_smoke_results.json`, `.github/workflows/external-http-active-active.yml` | Local active-active evidence is not a remote Kubernetes/serverless multi-region result until `benchmarks/external_http_active_active_results.json` is produced by a real run. |
| Serverless telemetry | Loopback replica telemetry exists; remote telemetry has a dedicated manual workflow and artifact path. | `deploy/serverless/observed-telemetry.loopback.json`, `.github/workflows/serverless-observed-telemetry.yml` | Loopback evidence is not a hosted managed-serverless claim until `observed-telemetry.remote.json` is committed. |
| Competitor adapters | Local Mem0/LangGraph/GraphRAG-style adapters run; optional Zep evidence is skipped until configured. | `benchmarks/memory_competitor_results.json` | Not a full independent Mem0/Zep/Letta leaderboard without live service credentials and public runner parity. |

Visual summary generated from the checked-in JSON results:

![WaveMind benchmark summary](docs/assets/benchmark-summary.svg)

Regenerate the matrix and chart locally:

```sh
python benchmarks/benchmark_registry.py --output benchmarks/benchmark_matrix_results.json
python benchmarks/render_benchmark_charts.py --output docs/assets/benchmark-summary.svg
```

The chart shows completed local measurements plus the public benchmark roadmap.
Planned public benchmarks stay out of the results section until the dataset,
engine, and result JSON are committed.

Status legend:

- `implemented` - script and checked-in result exist.
- `runner ready` - adapter exists, but the official public dataset result is not checked in yet.
- `planned` - benchmark is part of the public proof path, but no WaveMind result is claimed.

How to read the benchmark classes:

| class | Popular examples | What it answers for WaveMind |
|---|---|---|
| Retrieval / embeddings | BEIR, MTEB Retrieval, MIRACL | Does WaveMind preserve normal vector-search quality on public qrels? |
| Vector index / database | ANN-Benchmarks, VectorDBBench | Is the candidate index fast enough at scale? |
| Agent memory | LoCoMo, LongMemEval, LongMemEval-V2, LMEB | Does WaveMind retrieve the right evolving memory across long histories? |
| RAG quality | RAGBench | Does dynamic memory improve final context and answer quality? |

Current read:

| area | result | honest interpretation |
|---|---|---|
| Public agent-memory evidence | On official LoCoMo `locomo10.json`, WaveMind reaches `evidence_recall@5 0.386` with hash embeddings and `0.547` with sentence-transformers. Fair namespace-filtered Chroma reaches `0.257` / `0.407`; Qdrant reaches `0.263` / `0.409`. | WaveMind retrieves more labeled evidence. Chroma is still the fastest static vector-store baseline. Qdrant local payload filtering is much slower than service-mode Qdrant should be. |
| Public retrieval sanity check | On BEIR SciFact, WaveMind reaches `nDCG@10 0.354`, `Recall@10 0.482`; Qdrant matches that quality; Chroma reaches `0.350` / `0.467` with identical hash embeddings. | Same-embedding retrieval quality is close. Chroma is fastest at `1.79 ms`; Qdrant local is `17.71 ms`; WaveMind exact path is `117.02 ms`. |
| Public multilingual retrieval | On NoMIRACL Russian, sampled at 200 queries / 5000 compact candidate passages, WaveMind reaches `nDCG@10 0.434`, `Recall@10 0.516`, matching Qdrant and staying within `0.002` nDCG of Chroma on identical hash embeddings. | Russian same-embedding quality is at parity. Chroma is faster at `2.60 ms`; WaveMind is `10.22 ms`; Qdrant local is `18.86 ms`. |
| Static agent recall | WaveMind `precision@1` equals Chroma at `0.82`; WaveMind `precision@3` is `0.90` vs Chroma `0.88`. | Competitive quality, but Chroma is faster on the static vector-store path. |
| Agent coherence and token savings | On a 500-memory long user-history task simulation, WaveMind reaches `0.92` task success, `0.00` stale error rate, `0.93` context saved, `9` coherent turns, and `2.98 ms` average query latency. Static vector reaches `0.33` task success and `0.73` stale error rate; Chroma static reaches `0.42` task success and `0.18` stale error rate. | This measures agent behavior rather than nearest-neighbor retrieval: fewer stale facts, longer coherent task runs, and compact context. |
| Dynamic memory policy | WaveMind reaches `1.00` stale suppression; Chroma static is `0.00`. | This is the strongest current differentiation: hotness, TTL, corrections, and namespaces. |
| Field memory dynamics | Graph-enabled WaveMind reaches `1.00` `precision@1`, `1.00` stale suppression, `1.00` concept formation, and `1.00` durable concept consolidation vs static WaveMind at `0.20` / `0.20` / `0.00` / `0.00`. | This is still synthetic, but it is now a regression check for memory-to-memory excitation, conflict inhibition, decay, and self-organization into auditable concept memories. |
| Long-term evidence | WaveMind reaches `1.00` evidence recall@5, `1.00` precision@1, and `1.00` stale suppression on the synthetic long-memory evidence benchmark. | This is the first proof-shaped benchmark for agent memory: it measures whether stale/corrected/expired/cross-user facts stay out of retrieved evidence. |
| Capacity | Static `precision@1` is `0.94` at 5000 memories; dynamic policy keeps `1.00` on the current checks. | Quality is holding on these checks, but dynamic latency must be optimized. |
| LongMemEval full retrieval | On the official LongMemEval-S cleaned file, 470 non-abstention session-level questions, WaveMind reaches `evidence_recall@5 0.782` and `precision@1 0.696`; Chroma static reaches `0.518` / `0.355`; Qdrant static reaches `0.520` / `0.355`. | This is now the strongest public memory result in the repo. It is retrieval-only, not final answer quality. |
| LongMemEval 50-query smoke | On the first 50 non-abstention LongMemEval-S questions, WaveMind reaches `evidence_recall@5 0.920`, `precision@1 0.760`, and `MRR@5 0.827`; Chroma/Qdrant static reach `0.600`, `0.260`, and `0.385`. | This is the fast regression profile for checking current changes before rerunning the full LongMemEval profile. WaveMind wins on quality; latency still needs work. |
| ANN/index curve | At 50000 generated 128-d vectors, NumPy exact keeps `recall@10 1.000` at `6.49 ms`; quantized int8 keeps `0.934` at `24.92 ms`; Annoy is faster at `4.92 ms` but drops to `0.730` recall; Qdrant local keeps `1.000` recall at `43.49 ms`. | Current local scale boundary is clear: quantized search needs kernel work, Annoy needs tuning/FAISS, and Qdrant should be tested in service mode for a fair production comparison. |
| Production load | At 100000 generated 128-d vectors, service-mode Qdrant reaches `recall@10 1.000`, avg `10.28 ms`, p99 `21.26 ms`, passes the checked-in production SLO gate (`recall >= 0.95`, `p99 <= 100 ms`, `100 qps`, 3 replicas, HPA max 24), and estimates `$1.39` per 1M queries with `$365.02` monthly target cost. At 1M over 100 queries, persisted FAISS reaches `recall@10 1.000`, avg `39.12 ms`, p99 `57.71 ms`, and estimates `$4.17` per 1M queries with 6 replicas for 100 qps. The older 1M Qdrant tuned production-load profile reaches `recall@10 0.984`, avg `82.57 ms`, p99 `137.86 ms`; the newer streaming 1M Qdrant profile closes that p99 gap after safe upsert chunking, wait-after-build, and query warmup. | 100k Qdrant, 1M persisted FAISS, and the tuned 1M Qdrant streaming profile now pass recall/p99 production gates on the tested machine. The older Qdrant load profile stays checked in as evidence that cold/untuned service tails can fail. |
| pgvector tuning | On a real PostgreSQL/pgvector service at 50000 vectors, baseline HNSW reaches `recall@10 0.834`, exact mode reaches `1.000` with p99 `76.98 ms`, and iterative HNSW reaches `0.970` with p99 `55.19 ms`. Qdrant service remains the speed reference at `1.000` recall and p99 `17.84 ms`. | pgvector now has a measured production tuning path. Exact mode proves correctness; iterative scan passes the 50k recall/p99 gate and should be promoted into 100k/1M load profiles next. |
| Streaming production load | `benchmarks/production_streaming_load_benchmark.py` generates and inserts vectors in batches, stores only query source vectors outside the index, and measures target-recall, p99, SLO, and cost. The checked-in 10M compressed FAISS IVF-PQ run reaches target recall@10 `0.990`, p99 `60.13 ms`, and valid SLO/cost status; the real Qdrant service smoke reaches target recall@10 `1.000`, p99 `17.90 ms`; the cold 1M Qdrant streaming run reaches recall@10 `0.990` but fails p99 at `3013.98 ms`; the tuned 1M Qdrant run with safe upsert chunks, wait-after-build, and 100 warmup queries reaches recall@10 `1.000`, p99 `26.37 ms`, and valid SLO/cost status; the real two-service sharded Qdrant smoke reaches target recall@10 `1.000`, p99 `16.02 ms`; the real PostgreSQL/pgvector service smoke reaches target recall@10 `1.000`, p99 `7.62 ms`; the single-service Qdrant, horizontally sharded Qdrant, and pgvector 10M plan-only artifacts estimate `0.06 GB` local runner free space because storage is remote; the 50M FAISS IVF-PQ plan-only artifact estimates a `1.12 GB` compressed index, `119.209 GB` application storage, and the exact run command. | This is the first real 10M compressed production-scale artifact plus real Qdrant/pgvector service streaming evidence, real sharded Qdrant fanout smoke evidence, and checked Qdrant/pgvector/FAISS large-N run contracts. The 10M FAISS result is a compressed target-recall profile, not exact-neighbor recall; the 10M Qdrant single-service, 10M Qdrant sharded, 10M pgvector, and 50M FAISS plans are not completed benchmarks until their result JSON files are committed. |
| Scale readiness | Deterministic 1M-memory simulation validates 4096 namespace placements over 4 nodes with replication factor 2, node-loss availability `1.000`, zone-loss availability `1.000`, Kubernetes `StatefulSet`, `HorizontalPodAutoscaler`, repair `CronJob`, majority control-plane lease/config revision safety with stale-leader, stale-revision, and minority-commit rejection, operator-style `WaveMindCluster` reconciliation for `4096` namespaces, operator status phase `Ready` with resources/capacity/autoscaling/repair/control-plane conditions true, hot-cache hit rate `0.920`, query-audit prewarm warmed `1` query with prewarm hit `true`, query-vector cache local hit rate `0.995` with `1` encode call, Redis query-vector cache shared across workers `true`, shared Redis rate limiter allows `4` and limits `1` across 2 workers, Redis-compatible shared cache visible across workers, Memory OS Redis prewarm warmed `2` queries, predictive prefetch warmed `5` neighbor queries, Redis Memory OS demoted cold memories, Redis cross-worker hit `true`, Redis namespace invalidation `true`, Redis Memory OS architecture advice `architecture_required`, API cache invalidation on `/remember` and `/forget` prevents stale cached recall, Memory OS found `2` hot queries, warmed `2`, predictively warmed `5`, demoted cold memories, purged `1` expired memory, created `1` durable concept, and emitted production architecture advice for service-index, namespace-sharding, production-controls, replication-capacity, load-test, and multimodal readiness, service-mode distributed sharding recall after primary loss, service-mode repair copied `1` missing replica record with recall after repair `true`, real HTTP shard transport with proxy bypass `true`, HTTP repair copied `1` missing replica record, HTTP tombstone repair deleted `1` stale API record, concurrent HTTP writes `12`, concurrent query hit rate `1.000`, service-mode tombstone suppression before repair `true`, tombstone repair deleted `1` stale replica record, suppression after repair `true`, anti-entropy worker repaired `1` missing record and deleted `1` stale tombstone record, quorum-replicated runtime recall after node loss, missing-record repair, tombstone repair, concurrent runtime writes `12`, concurrent runtime query hit rate `1.000`, active-active namespace delta sync with cursor-based incremental record export and field-only hotness export, sustained active-active mesh sync across 3 independent regions and 3 namespaces with convergence `1.000`, delete suppression `1.000`, success `1.000`, 90 pair syncs, final no-op imports `0`, HTTP service-region active-active sync through FastAPI delta endpoints with convergence `1.000` and final no-op imports `0`, real local HTTP active-active service-region smoke with convergence `1.000`, delete suppression `1.000`, success `1.000`, and final no-op imports `0`, field-state CRDT convergence/idempotency/tombstone-wins, checksummed replicated snapshot/restore, offsite mirror verification, portable archive verification, S3-compatible upload/latest-metadata/download/retention verification, object-store DR drill `true`, structured payload precision@1 `1.000`, cross-modal target-modality precision@1 `1.000`, cross-modal vector persistence `1.000`, precomputed external-vector precision@1 `1.000`, precomputed vector persistence `1.000`, cross-modal provenance rate `1.000`, and a deterministic 100M-memory capacity envelope with 128 nodes, 8 zones, RF=3, node/zone-loss availability `1.000`, and valid capacity plan `true`. | This proves routing, control-plane split-brain protection for config changes, Kubernetes deployment/operator/HPA/repair manifests and status conditions, service-mode repair, real HTTP shard transport, service-boundary active-active delta sync, real multi-process active-active service-region sync, concurrent API safety for local WaveMind/SQLite nodes, concurrent replicated-runtime safety, tombstone-aware delete repair, anti-entropy background repair, query-vector cache, shared rate limiting, Memory OS adaptive prewarm/predictive prefetch/consolidation/forgetting/architecture advice, local and Redis-compatible cache prewarm, shared cache invalidation and mutation safety, structured and cross-modal payload retrieval, external precomputed-vector compatibility, distributed sharding, replicated-runtime, cursor-bounded namespace-delta sync, sustained active-active mesh convergence, distributed field-state convergence, offsite/archive/object-store backup lifecycle, restore-drill foundations, and 100M-scale placement/capacity planning. |
| Local HTTP cluster smoke | 4 real localhost API processes with isolated SQLite stores, RF=3, `read_fanout=1`, workers `4`: success `1.000`, failover hit `1.000`, delete suppression `1.000`, repaired replicas `1`, health `true`, degraded nodes `0`, p99 `348.83 ms`, SLO `true`. | This is the CI-friendly service-mode gate between in-process tests and remote external-node benchmarks. It catches HTTP transport, quorum, repair, delete-suppression, post-load node-health, and circuit-state regressions without needing external infrastructure. |
| Production readiness gate | Current WaveMind core gate score is `1.000`: `36/36` criteria pass, `0` require action, `0` fail. Live Zep competitor evidence is tracked separately and remains pending until a real `ZEP_API_URL` or `ZEP_API_KEY` is configured. | This keeps production claims honest without letting a missing commercial competitor credential block WaveMind's own readiness verdict. WaveMind has a real production foundation, a checked-in 10M compressed FAISS profile, a checked 50M run preflight, a measured pgvector tuning path, real Qdrant and pgvector streaming service smokes plus 10M preflights, a real two-service sharded Qdrant fanout smoke, a real tuned 1M Qdrant streaming SLO pass, a deterministic 100M capacity envelope, real local multi-process HTTP cluster smoke, real local multi-process active-active service-region smoke, VectorDBBench custom dataset export, architecture advisor preflight, cluster autoscale planning, and majority control-plane safety. |
| Memory competitor adapters | WaveMind reaches `precision@1 0.80`, `precision@3 1.00`, stale suppression `1.00`. Mem0 runs locally with Qdrant + FastEmbed and reaches `0.80`, `1.00`, stale suppression `0.60`. LangGraph persistent SQLite reaches `0.80`, `1.00`, stale suppression `1.00`. GraphRAG-style static graph reaches `1.00`, `1.00`, stale suppression `1.00` on this small static scenario. Zep has live adapter paths for the current `zep-cloud` Graph API and legacy/OSS-compatible `zep-python`; it is skipped only until `ZEP_API_URL` or `ZEP_API_KEY` points at a real Zep service. | This prevents fake competitor claims while still checking real installed competitors when they are available. |
| LongMemEval local answer generation | With the same local Ollama `qwen2.5:1.5b`, WaveMind reaches `exact_match 0.240`, `contains_answer 0.380`, `token_f1 0.333`, and `evidence_recall@5 0.920`; Chroma and Qdrant static both reach `0.120`, `0.160`, `0.170`, and `0.600`. | This is the first checked-in end-to-end answer benchmark against Chroma/Qdrant. It is still a 50-question lightweight smoke run, not a full LongMemEval leaderboard score. |

The serverless part of scale readiness now includes an operational preflight,
not only manifests: target load, required replicas, burst capacity,
scale-to-zero safety, cold-start budget, and modeled compute cost are checked
by the production gate.

### Real Benchmark Matrix

| benchmark | what it proves | status | baseline / competitor | target |
|---|---|---|---|---|
| Agent user-memory retrieval | Natural-language recall over 200 user facts. | implemented | Chroma | Match Chroma `precision@1`, beat `precision@3`, stay under 5 ms at 200 memories. |
| Agent coherence and token savings | Simulated agent tasks over long user history: task success, top-1 decision success, stale errors, coherent turns, and context saved. | implemented | Static vector / Chroma static | Prove WaveMind improves agent behavior, not only nearest-neighbor retrieval. |
| Dynamic memory policy | Hot memory, TTL, corrections, stale suppression, namespace isolation. | implemented | Chroma static | Keep `precision@1` and stale suppression at 1.00, cut avg latency below 10 ms at 1000 memories. |
| Field memory graph dynamics | Related memories excite each other, newer conflicting memories suppress stale facts, graph energy decays, and active clusters can become durable concept memories. | implemented | WaveMind static | Keep `precision@1`, stale suppression, concept formation, and concept consolidation at 1.00 while moving from synthetic checks to LoCoMo/LongMemEval evidence. |
| WaveMind capacity curve | How recall and latency change at 200 / 1000 / 5000 memories. | implemented | WaveMind-only today | Keep `precision@1 >= 0.95` at 5000 memories and dynamic latency below 20 ms. |
| Long-term memory evidence | Evidence retrieval from long histories with profile, preference, correction, TTL, namespace, and filler noise. | implemented | Static vector / Chroma / Qdrant | Keep this as a small regression test while public LoCoMo and LongMemEval runners carry the stronger evidence claims. |
| BEIR-style open retrieval runner | Public `corpus.jsonl`, `queries.jsonl`, `qrels/*.tsv` datasets with the same metrics for each engine. | implemented | WaveMind / Chroma / Qdrant | Use identical embeddings and report `nDCG@k`, `Recall@k`, `MRR@k`, `precision@1`, and latency. Current checked-in run: BEIR SciFact. |
| NoMIRACL Russian retrieval | Russian human-annotated multilingual relevance over compact candidate passages. | implemented | WaveMind / Chroma / Qdrant | Keep same-embedding `nDCG@10` at parity, then rerun with sentence-transformers and full MIRACL Russian when disk/service capacity allows it. |
| ANN/VectorDBBench-style local curve | Recall/latency tradeoff for candidate indexes on generated vectors. | implemented | NumPy exact / quantized int8 / Annoy / Qdrant local | Use this as the local engineering curve; official VectorDBBench custom-dataset execution is now runner-ready. |
| Production index profile | Docker-backed 50000-vector profile for persisted FAISS, Qdrant service, and PostgreSQL/pgvector HNSW. | implemented | FAISS / Qdrant service / pgvector | Keep service-mode candidate generation above `0.95` recall@10 and below 10 ms average query latency at 50000 vectors. |
| Production load profile | 100k and 1M service-backed candidate-index checks with p95/p99 latency plus an explicit SLO/cost gate for recall, p99, QPS, replicas, HPA capacity, storage, monthly target cost, and cost per 1M queries. | implemented | Qdrant service / pgvector HNSW / FAISS persisted | Keep 100k Qdrant and 1M persisted FAISS green while tuning Qdrant/pgvector for the same 1M p99 gate. |
| Qdrant 1M HNSW ef sweep | One 1M Qdrant collection queried with multiple `hnsw_ef` values and the same SLO gate. | implemented | Qdrant service | Keep the older sweep as a tail-latency regression baseline; the streaming 1M profile now proves the passing path with safe chunks, wait-after-build, and 100 warmup queries. |
| Production streaming load runner | Memory-bounded large-N runner that generates and inserts vectors in batches and measures target-recall, p99, SLO, and cost without storing the full corpus or exact-neighbor matrix in RAM. | implemented | FAISS persisted / FAISS IVF-PQ persisted / Qdrant service streaming / Qdrant sharded service streaming / pgvector streaming | Keep 10M compressed FAISS IVF-PQ above recall@10 `0.95` and p99 below `100 ms`, keep tuned 1M Qdrant streaming below p99 `100 ms`, keep the real Qdrant, sharded Qdrant, and pgvector service smokes green, then run single-service Qdrant, sharded Qdrant, pgvector, and 50M compressed FAISS profiles on sized hardware. |
| Scale readiness profile | Cluster placement, node/zone-loss simulation, quorum report, control-plane majority lease/config revision safety, Kubernetes StatefulSet, HPA, repair CronJob, CRD status subresource, operator readiness/capacity/autoscaling/repair/control-plane conditions, service-mode distributed namespace sharding, real HTTP shard transport, sustained mixed HTTP cluster load, replica repair, tombstone-aware delete repair, anti-entropy repair worker, query-vector cache, Redis-compatible shared rate limiting, Memory OS adaptive prewarm/predictive prefetch/consolidation/forgetting, replicated runtime, cursor-based active-active namespace delta sync, sustained active-active mesh sync, FastAPI service-region active-active sync, field-only hotness delta sync, field-state CRDT convergence, replicated snapshot/restore with offsite, archive, object-store latest-metadata/download/retention/DR-drill verification, query-audit cache prewarm, Redis-compatible shared hot-cache behavior, namespace invalidation, API cache mutation safety, and structured/multimodal/cross-modal payload retrieval with provenance and external precomputed-vector compatibility. | implemented | Mem0 / Zep / LangGraph persistent memory / GraphRAG target adapters | Keep quorum replication, control-plane split-brain rejection, distributed namespace routing, autoscaling manifests, operator status conditions, scheduled repair, service-mode repair, HTTP shard transport, sustained mixed cluster load, tombstone-aware delete repair, anti-entropy background repair, query-vector cache, shared rate limiting, Memory OS prewarm/predictive prefetch/consolidation/forgetting, cursor-bounded namespace-delta sync, sustained active-active mesh convergence, service-region active-active delta endpoints, field-state CRDT merge, repair, local and Redis cache prewarm, mutation-safe shared cache behavior, cross-modal provenance, precomputed-vector compatibility, offsite/archive/object-store backup lifecycle, restore drills, and 10M compressed load tests green. |
| Local HTTP cluster smoke | Starts real localhost API-node processes and runs the service-mode sustained mixed workload through HTTP with `read_fanout=1`, then probes `/stats` on every node for health/circuit state. | implemented | WaveMind local API nodes | Keep success, failover, repair, forget, delete suppression, and cluster health at 1.00; GitHub CI uses a 2000 ms p99 ceiling for runner variance while checked-in local evidence stays below 1000 ms. |
| Local HTTP active-active service-region smoke | Starts real localhost API region processes, each serving a replicated WaveMind runtime, then syncs namespace deltas through HTTP export/import endpoints. | implemented | WaveMind local replicated API regions | Keep convergence, delete suppression, and pair-sync success at 1.00, final no-op imports at 0, and p99 below 1500 ms in CI. |
| External HTTP cluster load runner | `benchmarks/http_cluster_load_benchmark.py` runs the sustained mixed workload against user-supplied WaveMind API node URLs and reports success rate, failover hit rate, delete suppression, repair count, p99, and `slo_pass`. | implemented | WaveMind remote service nodes | Check in the first real remote service-node artifact, then use it as the deployment gate for production clusters. |
| External HTTP active-active runner | Manual GitHub workflow and CLI path for user-supplied remote API regions. It writes `benchmarks/external_http_active_active_results.json` and validates convergence, delete propagation, cursor idempotency, final no-op sync, and p99. | implemented | WaveMind remote API regions | Check in a real remote Kubernetes/serverless active-active region artifact with convergence, delete suppression, and success at 1.00. |
| Production readiness gate | Machine-readable gate over production artifacts, with pass/action_required/fail criteria. | implemented | WaveMind-only gate | Reach `readiness_score 1.000` before claiming complete million-plus production readiness. |
| Memory competitor adapter profile | Dynamic-memory scenario wired for external memory frameworks. | implemented | Mem0 / Zep / LangGraph persistent memory | Report real competitor results only when their packages/services are explicitly configured. |
| [BEIR](https://github.com/beir-cellar/beir) | Standard zero-shot information retrieval quality. | planned | Chroma / Qdrant / FAISS | Stay within 0.02 `nDCG@10` on identical embeddings. |
| [MTEB Retrieval](https://github.com/embeddings-benchmark/mteb) | Separates encoder quality from retrieval-store quality. | planned | Chroma / Qdrant / FAISS | Prove WaveMind does not reduce same-embedding retrieval quality. |
| [MIRACL Russian](https://miracl.ai/) | Multilingual retrieval with Russian relevance judgments. | runner ready | Chroma / Qdrant / FAISS | NoMIRACL Russian compact run is implemented; full-corpus MIRACL Russian remains the next heavier profile. |
| [VectorDBBench](https://github.com/zilliztech/VectorDBBench) | Vector database insertion/search/filter/cost-performance benchmark. | runner ready | Chroma / Qdrant / Milvus / Weaviate / Pinecone / FAISS | WaveMind now exports a reproducible custom dataset (`train.parquet`, `test.parquet`, `neighbors.parquet`, `scalar_labels.parquet`) for official VectorDBBench runs. |
| [LoCoMo](https://arxiv.org/abs/2402.17753) | Long conversation memory, temporal consistency, multi-hop recall. Retrieval-only runner is implemented for official `locomo10.json`. | implemented | Static vector / Chroma / Qdrant | Improve answer generation accuracy on top of the stronger sentence-transformers evidence retrieval run. |
| [LongMemEval](https://arxiv.org/abs/2410.10813) | Long-term assistant memory with updates and abstention. | implemented retrieval + local Ollama answer smoke | Static vector / Chroma / Qdrant / Mem0-style memory | Add stronger LLM answer quality, abstention, and Chroma/Qdrant RAG answer baselines. |
| [LongMemEval-V2](https://arxiv.org/abs/2605.12493) | Web-agent memory: state recall, dynamic state, workflow gotchas. | planned | AgentRunbook-R / Chroma RAG / Qdrant RAG | Prove WaveMind can retrieve compact evidence from agent trajectories. |
| [LMEB](https://github.com/KaLM-Embedding/LMEB) | Long-horizon memory embedding tasks beyond normal passage retrieval. | planned | Embedding-only baselines / Chroma / Qdrant | Choose the default semantic encoder using memory-specific tasks. |
| [RAGBench](https://huggingface.co/datasets/rungalileo/ragbench) | Downstream RAG context and answer quality. | planned | Chroma RAG / Qdrant RAG / Pinecone RAG | Show whether stale-memory suppression improves context relevance. |

The planned rows are not claimed wins. They are the public evaluation path WaveMind needs before strong production claims.

### Open Retrieval Benchmarks

Many retrieval benchmarks use the same simple shape:

- `corpus.jsonl` - documents with `_id`, optional `title`, and `text`.
- `queries.jsonl` - queries with `_id` and `text`.
- `qrels/test.tsv` - judged relevance rows: `query-id`, `corpus-id`, `score`.

WaveMind includes a BEIR-style runner so the same downloaded dataset can be used
for WaveMind, Chroma, and Qdrant:

```sh
pip install -e ".[bench]"
python benchmarks/open_retrieval_benchmark.py --dataset ./benchmarks/data/scifact --engines wavemind chroma qdrant --top-k 10
```

That runner reports `nDCG@k`, `Recall@k`, `MRR@k`, `precision@1`, average
latency, and p95 latency. It intentionally uses the same WaveMind encoder for
all engines, so the comparison is about retrieval/index behavior rather than
which embedding model each project chooses by default.

Checked-in BEIR SciFact result:

5183 documents, 300 test queries, `HashingTextEncoder`, top-k 10.
This is a public retrieval sanity check, not the main agent-memory proof.
Full machine-readable result: `benchmarks/open_retrieval_scifact_results.json`.

| engine | nDCG@10 | Recall@10 | MRR@10 | precision@1 | avg latency | p95 latency |
|---|---:|---:|---:|---:|---:|---:|
| WaveMind | 0.354 | 0.482 | 0.317 | 0.240 | 117.02 ms | 256.57 ms |
| Chroma | 0.350 | 0.467 | 0.315 | 0.243 | 1.79 ms | 2.39 ms |
| Qdrant | 0.354 | 0.482 | 0.317 | 0.240 | 17.71 ms | 23.28 ms |

Read this result narrowly: WaveMind preserves same-embedding retrieval quality
on a real public dataset, but its current exact path is far slower than Chroma.
Qdrant local preserves the same ranking quality and is much faster than the
WaveMind NumPy exact path. The engineering target is a FAISS/Annoy candidate
index with WaveMind's dynamic field policy applied only as a top-k re-ranker.

### NoMIRACL Russian Retrieval

WaveMind includes a compact multilingual retrieval runner for
[NoMIRACL](https://huggingface.co/datasets/miracl/nomiracl), the negative-aware
MIRACL relevance dataset. The checked-in run uses Russian `test.relevant`
queries and the compact Russian candidate corpus. It is not a full-corpus
MIRACL run; it is a reproducible multilingual relevance benchmark small enough
to run on a local machine.

```sh
python benchmarks/nomiracl_russian_benchmark.py --download --dataset benchmarks/data/nomiracl-russian --engines wavemind chroma qdrant --top-k 10 --limit-queries 200 --limit-corpus 5000 --output benchmarks/nomiracl_russian_results.json
```

Checked-in NoMIRACL Russian result:

200 Russian queries, 5000 compact candidate passages,
`HashingTextEncoder`, top-k 10. Full machine-readable result:
`benchmarks/nomiracl_russian_results.json`.

| engine | nDCG@10 | Recall@10 | MRR@10 | precision@1 | avg latency | p95 latency |
|---|---:|---:|---:|---:|---:|---:|
| WaveMind | 0.434 | 0.516 | 0.489 | 0.410 | 10.22 ms | 15.53 ms |
| Chroma | 0.435 | 0.519 | 0.490 | 0.410 | 2.60 ms | 3.44 ms |
| Qdrant | 0.434 | 0.516 | 0.489 | 0.410 | 18.86 ms | 24.08 ms |

Read this as multilingual same-embedding parity, not as a claim that the hash
encoder is the best Russian semantic model. The next stronger run should use
`sentence-transformers` on the same NoMIRACL split, then full MIRACL Russian
when there is enough disk/service capacity.

### LoCoMo Evidence Retrieval

WaveMind now includes a retrieval-only runner for the public
[LoCoMo](https://github.com/snap-research/locomo) dataset. It treats LoCoMo
conversation turns as memories and LoCoMo QA `evidence` dialog IDs as relevance
labels. This measures the memory layer before any LLM answer-generation noise.

Run it on the official `locomo10.json` file:

```sh
mkdir -p benchmarks/data
curl -L https://raw.githubusercontent.com/snap-research/locomo/main/data/locomo10.json -o benchmarks/data/locomo10.json
python benchmarks/locomo_memory_benchmark.py --dataset benchmarks/data/locomo10.json --engines wavemind static chroma qdrant --top-k 5 --output benchmarks/locomo_evidence_results.json
```

Metrics reported:

- `evidence_recall@k` - whether the labeled LoCoMo evidence turns appear in the returned memory block.
- `precision@1` - whether the first returned memory is labeled evidence.
- `MRR@k` - how high the first relevant evidence turn appears.
- `context_budget_saved` - how much smaller the returned evidence block is than the full conversation memory.
- `avg_latency_ms` and `p95_latency_ms` - retrieval latency only.

If Chroma or Qdrant are not installed, use the baseline-only command:

```sh
python benchmarks/locomo_memory_benchmark.py --dataset benchmarks/data/locomo10.json --engines wavemind static --top-k 5
```

## Namespace Sharding And Replication

For multi-tenant local deployments, `ShardedWaveMind` routes namespaces across
multiple SQLite files:

```python
from wavemind import ShardedWaveMind

memory = ShardedWaveMind(root_path="./state/wavemind-shards", shard_count=16)
memory.remember("Tenant A prefers short support replies.", namespace="tenant:a")
memory.remember("Tenant B tracks trading research.", namespace="tenant:b")

print(memory.query("support replies", namespace="tenant:a", top_k=3))
print(memory.stats())
memory.close()
```

For HA-style local or service-mode deployments, `ReplicatedWaveMind` writes each
namespace to a deterministic replica set and enforces read/write quorum:

```python
from wavemind import ReplicatedSnapshotWorker, ReplicatedWaveMind

memory = ReplicatedWaveMind(
    root_path="./state/wavemind-replicas",
    nodes=[
        {"id": "node-a", "address": "10.0.0.1:8000", "zone": "zone-a"},
        {"id": "node-b", "address": "10.0.0.2:8000", "zone": "zone-b"},
        {"id": "node-c", "address": "10.0.0.3:8000", "zone": "zone-c"},
    ],
    replication_factor=3,
)

memory.remember("Tenant A prefers short support replies.", namespace="tenant:a")
print(memory.query("support replies", namespace="tenant:a", top_k=3))

memory.set_node_available("node-a", False)
print(memory.query("support replies", namespace="tenant:a", top_k=3))
memory.close()
```

The runtime uses separate durable stores per node, stable replica keys, operation
metadata, quorum writes, quorum reads, merged replica results, tombstone-aware
delete propagation, and `repair_namespace()` for recovered replicas. It is the
production foundation for namespace-level HA and eventual-consistency behavior;
for full consensus across independent network services, deploy WaveMind with
Postgres/Qdrant/ops-layer replication.

For multi-region active-active experiments, use cursor-based namespace delta
sync. The first call can transfer the full namespace; later calls use the
returned cursor and transfer only new records, tombstones, or field-state keys:

```python
from wavemind import sync_namespace_delta

region_a.remember("Tenant A billing preference.", namespace="tenant:a")
first = sync_namespace_delta(region_a, region_b, "tenant:a")

region_a.remember("Tenant A latency preference.", namespace="tenant:a")
next_page = sync_namespace_delta(
    region_a,
    region_b,
    "tenant:a",
    since=first.to_cursor,
)

region_a.forget(text="Tenant A billing preference.", namespace="tenant:a")
delete_sync = sync_namespace_delta(
    region_a,
    region_b,
    "tenant:a",
    since=next_page.to_cursor,
)
```

The delta contains active records plus tombstones. Import is idempotent and
tombstone-aware, so a stale region export cannot resurrect a deleted memory.
The replicated runtime also carries field-state CRDT deltas for active-active
hotness/suppression signals. Recall-only hotness changes can sync without
resending records:

```python
region_a.query("latency preference", namespace="tenant:a")
field_only = sync_namespace_delta(
    region_a,
    region_b,
    "tenant:a",
    since=delete_sync.to_cursor,
)
```

This lets regions converge on dynamic memory priority without double-counting
the same signal when a delta is replayed.

For more than two regions, `ActiveActiveSyncWorker` keeps per-pair cursors and
runs bounded mesh sync cycles across namespaces:

```python
from wavemind import ActiveActiveSyncWorker

worker = ActiveActiveSyncWorker(
    {
        "us-east": region_a,
        "eu-west": region_b,
        "ap-south": region_c,
    }
)
report = worker.run_once(["tenant:a", "tenant:b"], bidirectional=True)
assert report.ok
```

The checked-in scale-readiness profile exercises 3 independent regions, 3
namespaces, 18 writes, 90 region-pair syncs, tombstone propagation, field-only
hotness sync, and a final no-op sync that imports `0` records. This is still a
local independent-region profile, not a claim that remote production regions
have already been load-tested.

For operational recovery, `ReplicatedSnapshotWorker` creates a checksummed
replicated snapshot, verifies an optional offsite mirror, writes a verified
`.tar.gz` archive, can upload that archive to S3-compatible storage, and
`ReplicatedObjectStoreDrillWorker` can run a recovery drill from the newest or
exact remote archive:

```python
job = ReplicatedSnapshotWorker(memory).run_once(
    destination="./backups/replicated",
    offsite_destination="./offsite/replicated",
    archive_destination="./archives/replicated",
    object_store_destination="s3://my-bucket/wavemind/prod",
    keep_last=7,
)
restored, report = ReplicatedWaveMind.restore_snapshot_archive(
    job.archive_path,
    "./state/restored-replicas",
)
```

The checked-in scale-readiness profile verifies manifest checksums, verifies the
offsite mirror, verifies the portable archive, verifies S3-compatible object
upload metadata, downloads the latest remote archive, verifies its SHA-256
against object metadata, restores three replica files from that archive, then
disables the restored primary and confirms the memory is still recalled from the
remaining replicas.

Checked-in official LoCoMo retrieval result:

10 conversations, 5882 memory turns, 1977 evidence-labeled questions,
`HashingTextEncoder`, top-k 5. Full machine-readable result:
`benchmarks/locomo_evidence_results.json`.

| engine | evidence recall@5 | precision@1 | MRR@5 | avg latency | p95 latency |
|---|---:|---:|---:|---:|---:|
| WaveMind | 0.386 | 0.239 | 0.307 | 3.95 ms | 7.44 ms |
| Static vector | 0.263 | 0.133 | 0.189 | 1.94 ms | 3.87 ms |
| Chroma static | 0.257 | 0.129 | 0.185 | 7.03 ms | 9.74 ms |
| Qdrant static | 0.263 | 0.133 | 0.189 | 147.58 ms | 210.23 ms |

Checked-in semantic LoCoMo run:

Same official data, same engines, but with
`sentence-transformers/paraphrase-multilingual-mpnet-base-v2`. Full
machine-readable result: `benchmarks/locomo_sentence_evidence_results.json`.

| engine | evidence recall@5 | precision@1 | MRR@5 | avg latency | p95 latency |
|---|---:|---:|---:|---:|---:|
| WaveMind | 0.547 | 0.333 | 0.432 | 3.44 ms | 5.56 ms |
| Static vector | 0.409 | 0.219 | 0.305 | 1.25 ms | 2.05 ms |
| Chroma static | 0.407 | 0.218 | 0.304 | 4.97 ms | 6.30 ms |
| Qdrant static | 0.409 | 0.219 | 0.305 | 124.34 ms | 149.72 ms |

Read this as retrieval-only evidence quality, not full QA quality. It uses the
same embeddings for every engine inside each table. The sentence-transformers
run is the stronger evidence-quality number: WaveMind improves recall over
static vector-store retrieval, while Chroma remains the fastest retrieval
backend. The next LoCoMo step is answer generation and faithfulness with a local
LLM on top of retrieved evidence.

### LongMemEval Evidence Retrieval

WaveMind also includes a retrieval-only runner for the official
[LongMemEval](https://github.com/xiaowu0162/LongMemEval) format. It indexes each
question's long chat history and measures whether the expected evidence sessions
or turns are retrieved before answer generation.

Run the full session-level retrieval benchmark:

```sh
python benchmarks/longmemeval_memory_benchmark.py --dataset benchmarks/data/longmemeval_s_cleaned.json --engines wavemind static chroma qdrant --granularity session --top-k 5 --output benchmarks/longmemeval_evidence_results.json
```

Checked-in official LongMemEval-S retrieval result:

470 non-abstention questions from `longmemeval_s_cleaned.json`,
22419 session memories, `HashingTextEncoder`, top-k 5. Full machine-readable
result: `benchmarks/longmemeval_evidence_results.json`.

| engine | evidence recall@5 | precision@1 | MRR@5 | context saved | avg latency | p95 latency |
|---|---:|---:|---:|---:|---:|---:|
| WaveMind | 0.782 | 0.696 | 0.762 | 0.869 | 7.27 ms | 9.14 ms |
| Static vector | 0.520 | 0.355 | 0.464 | 0.890 | 0.08 ms | 0.10 ms |
| Chroma static | 0.518 | 0.355 | 0.464 | 0.890 | 15.96 ms | 18.68 ms |
| Qdrant static | 0.520 | 0.355 | 0.464 | 0.890 | 398.48 ms | 432.88 ms |

The Chroma and Qdrant baselines now use the same namespace/payload scope as
WaveMind. Qdrant is run in local embedded mode; the Qdrant client warns that
local mode is not recommended above 20000 points, so this latency should not be
read as a service-mode Qdrant result.

Answer-generation runner with local Ollama:

```sh
python benchmarks/longmemeval_answer_benchmark.py --dataset benchmarks/data/longmemeval_s_cleaned.json --provider ollama --model YOUR_LOCAL_MODEL --engines wavemind chroma qdrant --top-k 5 --output benchmarks/longmemeval_answer_results.json
```

Checked-in local answer-generation smoke runs:

50 non-abstention LongMemEval-S questions, compact retrieved evidence,
same `HashingTextEncoder`, same local Ollama model, top-k 5. Full machine-readable results:
`benchmarks/longmemeval_answer_qwen25_0_5b_50_results.json` and
`benchmarks/longmemeval_answer_qwen25_1_5b_50_results.json`.

| system | questions | evidence recall@5 | exact match | contains answer | token F1 | avg retrieval | avg generation |
|---|---:|---:|---:|---:|---:|---:|---:|
| WaveMind + Ollama `qwen2.5:0.5b` | 50 | 0.920 | 0.120 | 0.180 | 0.183 | 2.98 ms | 1428.20 ms |
| Chroma static + Ollama `qwen2.5:0.5b` | 50 | 0.600 | 0.100 | 0.120 | 0.126 | 4.10 ms | 1234.69 ms |
| Qdrant static + Ollama `qwen2.5:0.5b` | 50 | 0.600 | 0.100 | 0.120 | 0.126 | 63.80 ms | 893.48 ms |
| WaveMind + Ollama `qwen2.5:1.5b` | 50 | 0.920 | 0.240 | 0.380 | 0.333 | 2.00 ms | 2153.00 ms |
| Chroma static + Ollama `qwen2.5:1.5b` | 50 | 0.600 | 0.120 | 0.160 | 0.170 | 7.05 ms | 2082.38 ms |
| Qdrant static + Ollama `qwen2.5:1.5b` | 50 | 0.600 | 0.120 | 0.160 | 0.170 | 100.20 ms | 758.11 ms |

There is also an extractive smoke run that does not require a model:
`benchmarks/longmemeval_answer_extractive_20_results.json`. It is only a runner
check, not a meaningful final answer-quality benchmark. The Ollama runs are real
local LLM runs, but still lightweight smoke results rather than official
LongMemEval leaderboard scores.

### ANN Index Curve

WaveMind includes a local ANN/VectorDBBench-style curve for candidate indexes.
It generates normalized vectors, queries with noisy copies, and measures
`recall@10` against exact cosine neighbors.

```sh
python benchmarks/ann_index_curve_benchmark.py --sizes 1000 5000 10000 50000 --dim 128 --queries 100 --top-k 10 --engines numpy quantized annoy faiss qdrant-local --output benchmarks/ann_index_curve_results.json
```

Add `pgvector` to `--engines` when `WAVEMIND_PGVECTOR_DSN` points at a
PostgreSQL database with pgvector enabled. Use `pgvector-exact` for recall
audits and `pgvector-iterative` for the HNSW + filtered-collection tuning path
on pgvector builds that support iterative scans.
Add `qdrant-service` when `WAVEMIND_QDRANT_URL` points at a running Qdrant
service. Add `faiss-persisted` when `WAVEMIND_FAISS_PATH` points at the FAISS
snapshot file to validate persisted-index startup behavior.

VectorDBBench custom dataset export:

```sh
python benchmarks/vectordbbench_dataset.py --vectors 10000 --queries 100 --dim 128 --top-k 10 --output-dir state/vectordbbench-wavemind --manifest benchmarks/vectordbbench_dataset_manifest.json
```

This writes the standard custom-dataset files used by VectorDBBench:
`train.parquet`, `test.parquet`, `neighbors.parquet`, and
`scalar_labels.parquet`; the ground-truth file uses the `neighbors_id` column.
The parquet files are generated under `state/` so the
repository does not carry bulky binary benchmark data; the checked-in manifest
records the exact parameters and reproduction command.

Reproducible Docker production profile:

```sh
docker compose -f examples/production-index-profile/docker-compose.yml up -d qdrant postgres
docker compose -f examples/production-index-profile/docker-compose.yml run --rm benchmark
docker compose -f examples/production-index-profile/docker-compose.yml down
```

Checked-in 50000-vector point:

| engine | recall@10 | avg latency | p95 latency | build |
|---|---:|---:|---:|---:|
| WaveMind numpy | 1.000 | 6.49 ms | 6.41 ms | 744.7 ms |
| WaveMind quantized | 0.934 | 24.92 ms | 37.36 ms | 2088.7 ms |
| WaveMind annoy | 0.730 | 4.92 ms | 7.37 ms | 4090.1 ms |
| WaveMind faiss | skipped | - | - | - |
| Qdrant local | 1.000 | 43.49 ms | 59.68 ms | 17525.7 ms |

Checked-in production 50000-vector point:

| engine | recall@10 | avg latency | p95 latency | build |
|---|---:|---:|---:|---:|
| WaveMind faiss-persisted | 1.000 | 3.52 ms | 7.88 ms | 715.9 ms |
| Qdrant service | 1.000 | 4.41 ms | 5.93 ms | 12269.8 ms |
| WaveMind pgvector | 0.811 | 10.95 ms | 15.69 ms | 185048.9 ms |

Checked-in pgvector tuning 50000-vector point:

| engine | recall@10 | avg latency | p95 latency | p99 latency | build |
|---|---:|---:|---:|---:|---:|
| Qdrant service | 1.000 | 9.14 ms | 17.31 ms | 17.84 ms | 14786.2 ms |
| WaveMind pgvector | 0.834 | 14.52 ms | 19.59 ms | 21.08 ms | 200277.7 ms |
| WaveMind pgvector-exact | 1.000 | 55.72 ms | 66.91 ms | 76.98 ms | 211611.0 ms |
| WaveMind pgvector-iterative | 0.970 | 38.32 ms | 48.02 ms | 55.19 ms | 189784.3 ms |

Checked-in production load points:

```sh
python benchmarks/production_load_benchmark.py --sizes 100000 --dim 128 --queries 100 --top-k 10 --engines qdrant-service pgvector pgvector-exact pgvector-iterative faiss-persisted
python benchmarks/production_load_benchmark.py --sizes 1000000 --dim 128 --queries 100 --top-k 10 --engines qdrant-service --output benchmarks/production_load_qdrant_1m_tuned_results.json
python benchmarks/production_load_benchmark.py --sizes 1000000 --dim 128 --queries 100 --top-k 10 --engines faiss-persisted --output benchmarks/production_load_faiss_1m_results.json
```

| vectors | engine | recall@10 | avg latency | p95 latency | p99 latency | SLO | required replicas | autoscaled capacity | build |
|---:|---|---:|---:|---:|---:|---|---:|---:|---:|
| 100000 | Qdrant service | 1.000 | 10.28 ms | 18.97 ms | 21.26 ms | pass | 2 | 1635.0 qps | 27439.3 ms |
| 100000 | WaveMind pgvector | 0.736 | 17.76 ms | 23.48 ms | - | fail: recall | 3 | 945.9 qps | 455703.7 ms |
| 100000 | WaveMind faiss-persisted | skipped | - | - | - | skipped | - | - | - |
| 1000000 | WaveMind faiss-persisted | 1.000 | 39.12 ms | 45.29 ms | 57.71 ms | scale required | 6 | 429.5 qps | 20788.1 ms |
| 1000000 | Qdrant service tuned | 0.984 | 82.57 ms | 125.99 ms | 137.86 ms | fail: p99 | 12 | 203.5 qps | 441775.0 ms |
| 1000000 | Qdrant `hnsw_ef=2048` sweep point | 0.977 | 64.76 ms | 91.18 ms | 103.77 ms | fail: p99 | 10 | 259.4 qps | 451912.4 ms |

Read this as an engineering curve, not an official VectorDBBench result. Annoy
is faster than exact NumPy at 50000 vectors but loses too much recall with the
current settings. The new `quantized` backend compresses vectors and keeps
`0.934` recall@10 on this run, but the current Python/NumPy kernel is slower
than exact NumPy; it is a memory-footprint baseline, not a latency win yet.
FAISS persistence and service-mode Qdrant now both preserve exact recall at
50000 generated vectors. The checked-in pgvector/HNSW profile uses
`WAVEMIND_PGVECTOR_EF_SEARCH=400`, which improves recall materially but still
misses the `0.95` production target and is slower than the other two profiles.
The runner now has explicit `pgvector-exact` and `pgvector-iterative` engines:
use exact mode as the correctness floor, then use iterative HNSW scan to tune
the production latency/recall tradeoff without hiding approximation loss.
The 100k load profile shows Qdrant service is already viable for candidate
generation on the tested machine under the checked-in SLO gate. The 1M
persisted-FAISS profile passes recall and p99 with a 100-query run. The older
1M Qdrant load profile still records a p99 tail failure, but the newer
streaming 1M Qdrant run passes the same p99 target after safe upsert chunking,
wait-after-build, and 100 warmup queries.
If a required package, service, or environment variable is missing, the runner
marks that engine as `skipped` instead of silently falling back to another
backend.

### Memory Competitor Adapter Profile

WaveMind includes a small dynamic-memory adapter profile for Mem0, Zep,
LangGraph persistent memory, and a local GraphRAG-style static graph baseline.
It checks corrections, TTL, namespace isolation, and preference recall. Mem0,
LangGraph, and GraphRAG-style run in the checked-in profile; Zep is marked
`skipped` until a dedicated service/API key is configured.

```sh
python benchmarks/memory_competitor_benchmark.py --engines wavemind mem0 zep langgraph graphrag
```

For a live Zep run, install `zep-cloud` for the current Zep Cloud Graph API
or `zep-python` for a legacy/OSS-compatible Zep service, then set either
`ZEP_API_URL` or `ZEP_API_KEY`. The benchmark creates temporary graphs/sessions
and deletes them after the run.

| engine | precision@1 | precision@3 | stale suppression | avg latency |
|---|---:|---:|---:|---:|
| WaveMind | 0.80 | 1.00 | 1.00 | 3.09 ms |
| Mem0 | 0.80 | 1.00 | 0.60 | 9.99 ms |
| Zep | skipped | - | - | - |
| LangGraph persistent memory | 0.80 | 1.00 | 1.00 | 0.75 ms |
| GraphRAG static graph | 1.00 | 1.00 | 1.00 | 0.01 ms |

### Current Local Runs

Field memory dynamics benchmark:

13 memories, 5 conflicting-fact queries, deterministic local encoder.
This benchmark isolates the `MemoryFieldGraph`: related memories can spread
activation, newer conflicting memories inhibit stale facts, graph energy decays,
and active clusters can surface and persist concept memories.
Full machine-readable result: `benchmarks/field_memory_dynamics_results.json`.

| engine | precision@1 | precision@3 | stale suppression | concept formation | concept consolidation | decay ratio | avg latency |
|---|---:|---:|---:|---:|---:|---:|---:|
| WaveMind graph | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 0.81 | 0.82 ms |
| WaveMind static | 0.20 | 1.00 | 0.20 | 0.00 | 0.00 | 0.00 | 0.48 ms |

Run locally from a cloned repository:

```sh
python benchmarks/field_memory_dynamics_benchmark.py
```

Long-term memory evidence benchmark:

200 memories, 8 evidence queries, same `HashingTextEncoder` embeddings.
This benchmark asks a stricter agent-memory question than static retrieval:
did the system return the right evidence while suppressing stale, corrected,
expired, or cross-user evidence?
Full machine-readable result: `benchmarks/long_memory_evidence_results.json`.

| engine | evidence recall@5 | precision@1 | stale suppression | context saved | avg latency |
|---|---:|---:|---:|---:|---:|
| WaveMind | 1.00 | 1.00 | 1.00 | 0.87 | 6.10 ms |
| Static vector | 1.00 | 0.57 | 0.00 | 0.88 | 0.65 ms |

Run locally from a cloned repository:

```sh
python benchmarks/long_memory_evidence_benchmark.py --dataset synthetic --engines wavemind static --memories 200 --top-k 5
```

To compare the same normalized benchmark with Chroma or Qdrant, install the benchmark extras and include those engines:

```sh
pip install -e ".[bench]"
python benchmarks/long_memory_evidence_benchmark.py --dataset synthetic --engines wavemind chroma qdrant --memories 200 --top-k 5
```

Real Russian sentences from Tatoeba, 50 one-word queries, NumPy exact index.

| metric | hash | sentence-transformers |
|---|---:|---:|
| precision@1 | 1.00 | 1.00 |
| precision@3 | 1.00 | 1.00 |
| avg query | 0.49 ms | 52.84 ms |

Capacity check with the hash encoder:

| memories | precision@1 | precision@3 | avg query |
|---:|---:|---:|---:|
| 200 | 1.00 | 1.00 | 0.49 ms |
| 1000 | 0.88 | 1.00 | 1.50 ms |
| 5000 | 0.72 | 0.88 | 5.68 ms |

Run locally from a cloned repository:

```sh
python benchmarks/ru_sentences_benchmark.py --sentences 200 --queries 50 --encoder hash --index numpy
python benchmarks/ru_sentences_benchmark.py --sentences 200 --queries 50 --encoder sentence --index numpy
```

Agent-memory benchmark against Chroma:

200 Russian user facts, 50 natural-language questions, same precomputed `HashingTextEncoder` embeddings for WaveMind and Chroma.
Full machine-readable result: `benchmarks/agent_memory_results.json`.

This is a static retrieval benchmark. It measures baseline ranking and latency, not hotness, TTL, repeated recall, or memory aging.

| engine | precision@1 | precision@3 | avg latency |
|---|---:|---:|---:|
| WaveMind | 0.82 | 0.90 | 2.25 ms |
| Chroma | 0.82 | 0.88 | 0.93 ms |

WaveMind-only capacity checks from the current ranking path:

| scenario | memories | precision@1 | precision@3 | avg latency | p95 latency |
|---|---:|---:|---:|---:|---:|
| static agent facts | 200 | 0.96 | 0.98 | 4.05 ms | 8.18 ms |
| static agent facts | 1000 | 0.96 | 0.98 | 3.53 ms | 5.20 ms |
| static agent facts | 5000 | 0.94 | 0.98 | 13.71 ms | 17.20 ms |
| dynamic memory policy | 200 | 1.00 | 1.00 | 38.40 ms | 41.14 ms |
| dynamic memory policy | 1000 | 1.00 | 1.00 | 54.29 ms | 72.38 ms |
| dynamic memory policy | 5000 | 1.00 | 1.00 | 48.36 ms | 86.13 ms |

Machine-readable local capacity result: `benchmarks/wavemind_capacity_results.json`.
These capacity checks are WaveMind-only because the local restricted environment did not have Chroma installed.

Run locally from a cloned repository:

```sh
pip install -e ".[bench]"
python benchmarks/agent_memory_benchmark.py --engines wavemind chroma --facts 200 --queries 50
```

Dynamic agent-memory benchmark:

200 memories, 8 checks, same precomputed `HashingTextEncoder` embeddings.
This benchmark exercises hot memory, TTL, corrections, and namespace isolation.
WaveMind applies its built-in memory policy. `Chroma static` is a plain vector-store baseline without application-layer TTL, delete handling, namespace filters, or recall reinforcement.
Full machine-readable result: `benchmarks/dynamic_memory_results.json`.

| engine | precision@1 | precision@3 | stale suppression | avg latency |
|---|---:|---:|---:|---:|
| WaveMind | 1.00 | 1.00 | 1.00 | 25.26 ms |
| Chroma static | 0.57 | 1.00 | 0.00 | 1.75 ms |

Category success:

| behavior | WaveMind | Chroma static |
|---|---:|---:|
| hot memory | 1.00 | 0.50 |
| TTL | 1.00 | 0.00 |
| correction | 1.00 | 0.00 |
| namespace isolation | 1.00 | 0.00 |

Run locally from a cloned repository:

```sh
pip install -e ".[bench]"
python benchmarks/dynamic_memory_benchmark.py --engines wavemind chroma --memories 200
```

## Comparison

| feature | WaveMind | Chroma | Qdrant |
|---|---|---|---|
| Primary role | Dynamic memory engine | Embedding database | Production vector database |
| Local SQLite persistence | Yes | Yes | No, separate service/storage |
| HTTP API | FastAPI included | Included | Included |
| Audit log / metrics | SQLite audit events plus `/metrics` | App-layer only | App-layer / service metrics |
| Dynamic memory priority | Wave-field hotness, TTL, priority | Metadata/filter driven | Payload/filter driven |
| Built-in forgetting | TTL and explicit forget | Manual delete/filtering | Manual delete/filtering |
| Best fit | Small to medium memory streams with dynamic recall | Local RAG apps and prototypes | Large-scale vector search |
| Scale target today | Local exact mode for small streams; FAISS/Qdrant/pgvector plus replicated namespaces for production paths | Larger than WaveMind local exact mode | Production vector scale |

WaveMind is not trying to replace dedicated vector databases at scale. The intended product gap is dynamic priority: frequently used memories can become hotter while old or low-priority memories fade. For static RAG over large document collections, use a mature vector database. For memory that needs persistence, scoped recall, TTL, forgetting, and reinforcement, WaveMind is designed to sit above or beside the vector index.

If you already use Chroma for local memory, see the practical migration guide:
[`docs/CHROMA_MIGRATION.md`](docs/CHROMA_MIGRATION.md).

## Known Limitations

- Optimal capacity on the current NumPy exact index is up to 1000 records.
- At 5000 records, one-word `precision@1` is currently 0.72 with the hash encoder; many misses are ambiguous queries where another sentence containing the same word ranks first.
- For `N > 5000`, the NumPy exact index is still reliable but scales linearly. Annoy is faster at 50000 vectors in the local curve, but current recall is only `0.730`; the `quantized` backend reaches `0.934` recall@10 but is slower than NumPy on the current kernel. Use FAISS or a production vector service before claiming large-scale ANN quality.
- Run `wavemind scale-plan --target-memories <N>` before growing a deployment. It is a guardrail, not a benchmark replacement: it tells you when NumPy is no longer the right candidate index and which checks to run next.
- `sentence-transformers/paraphrase-multilingual-mpnet-base-v2` requires about 420 MB of model files. Benchmark runners cache embeddings so retrieval latency is measured separately from model encoding latency.
- The Chroma comparison currently uses shared precomputed hash embeddings to isolate retrieval/ranking behavior; semantic model comparisons should be run separately.
- The BEIR SciFact run uses the hash encoder to isolate index/retrieval behavior. It is not a semantic embedding leaderboard result.
- On BEIR SciFact, WaveMind and Qdrant match on hash-encoder `nDCG@10`, while Chroma is much faster. The next index milestone is FAISS/Annoy candidate generation plus WaveMind top-k re-ranking.
- The LoCoMo results are retrieval-only evidence results, not final answer-quality scores. The sentence-transformers run is stronger than the hash run, but still needs answer generation and faithfulness checks.
- In the 200-fact agent benchmark, Chroma is faster on average while WaveMind is slightly higher at `precision@3`.
- The dynamic benchmark currently compares WaveMind against a static Chroma baseline. Chroma and Qdrant can implement similar behavior with extra application-layer metadata policy, deletes, filters, and reinforcement logic.
- `MemoryFieldGraph` is a discrete graph over stored memories, not a continuous mathematical field. Its current build path should be optimized with incremental edge updates before large production use.
- pgvector is a candidate-index backend. PostgreSQL source-of-truth storage is
  also available separately, but migrations, PITR docs, and service benchmark
  profiles still need more real deployment coverage.
- The Qdrant backend is also a candidate-index backend. WaveMind rebuilds it
  from SQLite on load/build, so large service-mode deployments still need a
  measured rebuild strategy and index-health monitoring.
- The persisted FAISS backend validates a snapshot against current memory ids
  and avoids unnecessary FAISS rebuilds when the snapshot matches. FAISS itself
  is a single-node flat-index path; use `ReplicatedWaveMind` or external
  database/service replication when that is not enough.
- The current cross-modal layer supports deterministic descriptor embeddings,
  a strict precomputed-vector path for externally computed CLIP/audio/video/3D
  embeddings, and an optional sentence-transformers backend for CLIP-style local
  image/text retrieval. Audio, video, and 3D perception still require external
  embeddings or strong descriptors until dedicated backends are benchmarked.
- The `quantized` backend is an explicit int8 candidate-index experiment. It
  reduces vector precision and must be benchmarked per workload before use.
- The synthetic long-term memory evidence benchmark is useful for regression and product-shape proof, but public claims should lean on LoCoMo and LongMemEval instead.
- The main LongMemEval evidence result is retrieval-only. The checked-in Ollama answer-generation comparison now includes WaveMind, Chroma static, and Qdrant static over 50 questions, but it is still not a full LongMemEval leaderboard-equivalent score.
- Qdrant baselines in this README use embedded local mode. Qdrant itself warns that local mode is not recommended above 20000 points; use the `qdrant-service` benchmark profile before making production latency claims.
- The tuned 1M Qdrant streaming result depends on safe upsert chunking, `30` seconds wait-after-build, and `100` warmup queries. The cold 1M run misses the p99 SLO, so production Qdrant claims must specify warmup/tuning behavior.
- The Qdrant streaming path has a real service smoke, a real two-service sharded smoke, a tuned 1M passing run, and checked single-service plus sharded 10M preflight contracts. It is not a completed 10M Qdrant benchmark until `benchmarks/production_streaming_load_qdrant_10m_results.json` and `benchmarks/production_streaming_load_qdrant_sharded_10m_results.json` are produced by real runs.
- The pgvector streaming path has a real service smoke and a checked 10M preflight contract. It is not a completed 10M pgvector benchmark until `benchmarks/production_streaming_load_pgvector_10m_results.json` is produced by a real run.
- The production cost model is an engineering estimate from checked-in benchmark parameters: required replicas, target QPS, replica hourly cost, vector storage, and payload storage. It is not a cloud-provider bill and must be recalibrated for real hardware.
- MTEB, MIRACL, LMEB, official VectorDBBench, and RAGBench are listed as the public benchmark roadmap, not as completed results yet.
- Local Ollama answer generation now works with `qwen2.5:0.5b` and `qwen2.5:1.5b`; WaveMind leads the checked-in Chroma/Qdrant smoke comparison, but answer quality is still limited by small-model reasoning and should be rerun with stronger local/API models before making product claims.
- Public benchmark adapters require optional datasets, heavier dependencies, or running services. They are intentionally outside the minimal `pip install wavemind` path.
- Dynamic memory is slower than static Chroma in the current local benchmark: 25.26 ms vs 1.75 ms average query latency on this machine.
- Current WaveMind-only dynamic checks keep `precision@1` at 1.00 through 5000 memories, but average latency is around 48-54 ms. The next optimization target is field/re-ranking latency, not basic recall quality.

## Roadmap

Full roadmap: [`docs/ROADMAP.md`](docs/ROADMAP.md).
Launch and positioning kit: [`docs/LAUNCH_KIT.md`](docs/LAUNCH_KIT.md).

Near-term priorities:

- Service-mode Qdrant, pgvector, and persisted-FAISS benchmark runs on a real
  production-like machine, with SLO and cost gates checked into the repo.
- Migration tooling and operational docs for Postgres source-of-truth storage.
- Tune the new quantized int8 backend so compression does not cost more latency
  than exact NumPy on common workloads.
- Service-mode Qdrant and FAISS latency baselines using the explicit Qdrant
  backend, not only the standalone Qdrant benchmark baseline.
- LoCoMo and LongMemEval answer-quality evaluation, not retrieval only.
- Harden framework adapters: LangGraph, LlamaIndex, CrewAI, AutoGen,
  OpenClaw, and HTTP-only sidecar use.
- Faster dynamic re-ranking through smaller candidate windows, caching, and
  background updates.
- Better production operations: OpenTelemetry and replicated offsite snapshot
  jobs with verified portable archives, S3-compatible upload, latest-archive
  lookup, restore from latest, object-store DR drill, and object-store retention are
  implemented; richer latency histograms, index-health metrics, alerting
  examples, real cloud disaster-recovery drills, and Postgres PITR runbooks are
  next.

Longer-term direction:

- scale from thousands of memories to 100k-1M on one node;
- keep SQLite as the local source of truth while adding Postgres and external
  vector backends for production;
- evolve `MemoryFieldGraph` from a regression-tested graph into a stronger
  field-memory model with excitation, inhibition, decay, and consolidation;
- expand the built-in multimodal backend beyond CLIP-style local image/text
  retrieval into benchmarked audio/video/3D encoders while keeping the same
  provenance-preserving payload API;
- build enterprise features only after benchmarked retrieval, latency, and
  answer-quality evidence are solid.

## Contributing

Contributing guide: [`CONTRIBUTING.md`](CONTRIBUTING.md).

Useful contribution paths:

- add reproducible benchmark adapters and checked-in result JSON;
- improve FAISS, Qdrant, pgvector, or other candidate-index backends;
- add examples for LangGraph, LlamaIndex, CrewAI, AutoGen, OpenClaw, and
  HTTP-only sidecar deployments;
- improve dynamic memory behavior around TTL, corrections, namespaces, graph
  excitation/inhibition, and consolidation;
- harden production operations: backups, audit logs, metrics, tracing, and
  migration tools.

GitHub issue templates are included for bugs, features, benchmarks, and
integrations. Benchmark claims need a reproduction command and committed result
artifact before they are added to README.

## License

MIT. See [LICENSE](LICENSE).

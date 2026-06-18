# WaveMind is persistent dynamic memory for AI agents: vector search first, wave-field priority second, SQLite as the source of truth.

![Python](https://img.shields.io/badge/python-3.10%2B-blue)
[![Tests](https://github.com/CaspianG/wavemind/actions/workflows/tests.yml/badge.svg)](https://github.com/CaspianG/wavemind/actions/workflows/tests.yml)
![License](https://img.shields.io/badge/license-MIT-green)

## Terminal Demo

From a cloned repository:

```text
$ python examples/demo.py
✓ Remembered: "Andrey is a trader who tracks market breakouts."
✓ Remembered: "Andrey prefers short practical answers about AI agents."

Query: "Andrey trader agent"
→ Result 1 (0.60): "Andrey is a trader who tracks market breakouts."
→ Result 2 (0.30): "Andrey prefers short practical answers about AI agents."
```

The demo is offline, keyless, and uses the built-in hash encoder.

## Quick Start

Install from PyPI and create your first local memory:

```sh
python -m pip install wavemind
wavemind remember "Andrey is a trader" --namespace demo
wavemind query "trader" --namespace demo
```

What happens here:

- `remember` writes the text and its vector pattern into a local SQLite database.
- By default, the database file is `wavemind.sqlite3` in your current working directory.
- `--namespace demo` keeps this memory separate from other users, agents, or projects.
- `query` reads from the same SQLite file and returns the closest remembered texts.

## Optional Embeddings

For sentence-transformer embeddings:

```sh
python -m pip install "wavemind[sentence]"
wavemind --encoder sentence remember "Andrey is a trader" --namespace demo
wavemind --encoder sentence query "What does Andrey do?" --namespace demo
```

## Data Location

For an explicit database path, put global options before the command:

```sh
wavemind --db ./agent_memory.sqlite3 remember "Andrey is a trader" --namespace demo
wavemind --db ./agent_memory.sqlite3 query "trader" --namespace demo
```

WaveMind is local-first. One SQLite file is the source of truth for texts,
metadata, vectors, namespaces, tags, TTL, and recall state. For real agents,
prefer an explicit path under your application's state directory:

```python
from wavemind import WaveMind

memory = WaveMind(db_path="./state/wavemind.sqlite3")
memory.remember("The user prefers short answers.", namespace="user:42", tags=["preference"])
```

Useful storage patterns:

| runtime | Suggested database path |
|---|---|
| local CLI experiment | `./wavemind.sqlite3` |
| Python app or agent | `./state/wavemind.sqlite3` |
| OpenClaw sidecar | `~/.openclaw/wavemind/<agent-id>.sqlite3` |
| server daemon | `/var/lib/wavemind/wavemind.sqlite3` |
| Docker | mounted volume, for example `/data/wavemind.sqlite3` |

Keep the SQLite file out of git. Back it up like any other application state.

## HTTP API

Run the local FastAPI server:

```sh
wavemind --db ./agent_memory.sqlite3 serve --host 127.0.0.1 --port 8000
```

Store and query memory over HTTP:

```sh
curl -X POST http://127.0.0.1:8000/remember -H "Content-Type: application/json" -d "{\"text\":\"Andrey is a trader\",\"namespace\":\"demo\"}"
curl -X POST http://127.0.0.1:8000/query -H "Content-Type: application/json" -d "{\"query\":\"trader\",\"namespace\":\"demo\",\"top_k\":1}"
```

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

## Integration Patterns

WaveMind only needs two touch points in an agent or app:

1. Before the model call, `query()` for relevant memories and inject the short
   results into the prompt.
2. After the turn, `remember()` durable facts, preferences, summaries, tool
   outcomes, or user corrections.

That makes it usable in more than LangChain:

| Use case | Integration style |
|---|---|
| LangChain or LangGraph agent | Use `WaveMindMemory` from `wavemind.integrations.langchain`. |
| Custom Python agent | Create one `WaveMind` instance and call `query()` before the LLM. |
| Node, Go, Ruby, PHP, or no-code app | Run `wavemind serve` and call the HTTP API. |
| Multi-user SaaS | Use `namespace="user:<id>"` or `namespace="tenant:<id>:agent:<id>"`. |
| Temporary context | Store with `ttl_seconds=...` so stale memory expires automatically. |
| Preference/profile memory | Store with tags such as `profile`, `preference`, `project`, `decision`. |
| Corrections/privacy | Use `forget()` or namespace deletion workflows. |

Minimal custom agent loop:

```python
from wavemind import WaveMind

memory = WaveMind(db_path="./state/wavemind.sqlite3")

def run_turn(user_id: str, user_text: str, history: list[str]) -> str:
    namespace = f"user:{user_id}"
    hits = memory.query(user_text, namespace=namespace, top_k=5, min_score=0.25)
    recalled = "\n".join(f"- {hit.text}" for hit in hits)

    prompt = f"Relevant memory:\n{recalled}\n\nUser: {user_text}"
    answer = call_your_llm(prompt, history)

    memory.remember(f"User said: {user_text}", namespace=namespace, tags=["conversation"])
    memory.remember(f"Assistant answered: {answer}", namespace=namespace, tags=["conversation"])
    return answer
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

WaveMind can store any small-to-medium memory stream where freshness and usage
matter:

| Use case | Example |
|---|---|
| Support memory | Recall past user issues, plans, bugs, and resolutions. |
| Product research | Store interview snippets with `tags=["customer", "pain"]`. |
| Team knowledge | Remember project decisions and suppress expired decisions with TTL. |
| Personal assistant | Store preferences, routines, people, and recurring context. |
| Game/NPC memory | Give characters scoped memory that strengthens after repeated events. |
| Trading research | Store labeled OHLCV pattern notes before building a backtest layer. |
| Document notebook | Import text/PDF/JSON chunks and query by namespace/project. |

## Why Dynamic Memory

WaveMind is not positioned as "a faster Chroma." Chroma, Qdrant, Pinecone, and Weaviate are vector databases: they store embeddings and return nearest neighbors. That is the right tool for many static RAG workloads.

WaveMind is an agent memory layer. It still uses vector search first, but then applies memory-specific signals that a plain vector store does not model by default:

| memory behavior | Why it matters for agents | WaveMind mechanism |
|---|---|---|
| Hot memories | Facts recalled repeatedly should become easier to recall again. | Wave-field hotness and priority updates. |
| Aging memories | Old low-value facts should fade instead of competing forever. | TTL and decay-aware scoring. |
| Scoped memory | One user, agent, workspace, or project should not leak into another. | Namespaces and tags. |
| Explicit forgetting | Agents need deletion, privacy cleanup, and correction workflows. | `forget()` plus SQLite persistence. |
| Stable restart behavior | A memory system must survive process restarts. | SQLite source of truth, reloadable indexes. |
| Vector plus memory rank | Semantic similarity is necessary but not sufficient for long-running agents. | k-NN candidates first, wave field as re-ranker. |

The current Chroma benchmark below is intentionally conservative: it compares static retrieval on the same facts and the same hash embeddings. That benchmark is useful, but it does not exercise WaveMind's main product thesis: memory that changes over time as an agent recalls, reinforces, ages, and forgets information.

The benchmark that should decide whether WaveMind is worth using is a dynamic agent-memory benchmark:

| scenario | What should happen |
|---|---|
| A user repeats a preference many times. | WaveMind should rank it higher than equally similar but unused facts. |
| A fact expires via TTL. | WaveMind should suppress it without requiring manual vector cleanup. |
| A user corrects an old fact. | WaveMind should prefer the newer or reinforced memory. |
| A query is ambiguous across namespaces. | WaveMind should return only the scoped user's memory. |
| A long conversation has many irrelevant facts. | WaveMind should preserve useful recall instead of treating all vectors equally. |

In short: static vector search answers "what is nearest?" Agent memory also asks "what is still relevant, reinforced, scoped, and allowed to be remembered?"

## Benchmark

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
| Primary role | Agent memory engine | Embedding database | Production vector database |
| Local SQLite persistence | Yes | Yes | No, separate service/storage |
| HTTP API | FastAPI included | Included | Included |
| Dynamic memory priority | Wave-field hotness, TTL, priority | Metadata/filter driven | Payload/filter driven |
| Built-in forgetting | TTL and explicit forget | Manual delete/filtering | Manual delete/filtering |
| Best fit | Small to medium agent memory with dynamic recall | Local RAG apps and prototypes | Large-scale vector search |
| Scale target today | Up to 1000 optimal on NumPy, FAISS recommended beyond 5000 | Larger than WaveMind local mode | Production scale |

WaveMind is not trying to replace dedicated vector databases at scale. The intended product gap is dynamic priority: frequently used memories can become hotter while old or low-priority memories fade. For static RAG over large document collections, use a mature vector database. For agent memory that needs persistence, scoped recall, TTL, forgetting, and reinforcement, WaveMind is designed to sit above or beside the vector index.

## Known Limitations

- Optimal capacity on the current NumPy exact index is up to 1000 records.
- At 5000 records, one-word `precision@1` is currently 0.72 with the hash encoder; many misses are ambiguous queries where another sentence containing the same word ranks first.
- For `N > 5000`, use the FAISS backend with `--index faiss` or another production vector index.
- `sentence-transformers/paraphrase-multilingual-mpnet-base-v2` requires about 420 MB of model files and measured about 53 ms per query on the benchmark machine.
- The Chroma comparison currently uses shared precomputed hash embeddings to isolate retrieval/ranking behavior; semantic model comparisons should be run separately.
- In the 200-fact agent benchmark, Chroma is faster on average while WaveMind is slightly higher at `precision@3`.
- The dynamic benchmark currently compares WaveMind against a static Chroma baseline. Chroma and Qdrant can implement similar behavior with extra application-layer metadata policy, deletes, filters, and reinforcement logic.
- Dynamic memory is slower than static Chroma in the current local benchmark: 25.26 ms vs 1.75 ms average query latency on this machine.
- Current WaveMind-only dynamic checks keep `precision@1` at 1.00 through 5000 memories, but average latency is around 48-54 ms. The next optimization target is field/re-ranking latency, not basic recall quality.

## Roadmap

- FAISS-first production index path with persisted index rebuilds.
- Expand the dynamic benchmark to Qdrant, Chroma metadata-policy mode, sentence-transformers, and FAISS.
- Optimize dynamic re-ranking latency after lexical candidate filtering.
- Better semantic query expansion for short and ambiguous queries.
- Namespace quotas, backups, and daemon hardening for SaaS use.
- Webhook on recall for agent runtimes.
- OHLCV pattern-memory experiments for market research and backtests.

## License

MIT. See [LICENSE](LICENSE).

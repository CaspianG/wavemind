<div align="center">

# WaveMind

**Persistent dynamic memory for AI agents.**

Vector search finds similar memories. A wave-field priority layer makes useful
memories hotter, lets stale facts fade, and keeps user/project memory scoped.

![Python](https://img.shields.io/badge/python-3.10%2B-blue)
[![PyPI](https://img.shields.io/pypi/v/wavemind.svg)](https://pypi.org/project/wavemind/)
[![Tests](https://github.com/CaspianG/wavemind/actions/workflows/tests.yml/badge.svg)](https://github.com/CaspianG/wavemind/actions/workflows/tests.yml)
![License](https://img.shields.io/badge/license-MIT-green)

[Quick Start](#quick-start) |
[LangChain](#langchain-memory) |
[OpenClaw](#openclaw-integration) |
[HTTP API](#http-api) |
[Benchmarks](#benchmark) |
[Limitations](#known-limitations)

</div>

## At a Glance

| If you need... | WaveMind gives you... |
|---|---|
| Agent memory that survives restarts | SQLite-backed `remember()`, `query()`, and `forget()`. |
| Scoped memory per user, agent, or project | Namespaces and tags on every record. |
| Memory that changes over time | Hotness, priority, TTL, and decay-aware ranking. |
| Easy integration | Python API, CLI, FastAPI server, and LangChain memory class. |
| Honest benchmarks | Public BEIR/SciFact retrieval run plus dynamic memory-policy checks. |

```mermaid
flowchart LR
    U[User / tool event] --> R[WaveMind query]
    R --> K[k-NN candidates]
    K --> W[Wave-field re-rank]
    W --> P[Prompt memory block]
    P --> L[LLM / agent turn]
    L --> S[remember facts, summaries, corrections]
    S --> D[(SQLite source of truth)]
    D --> R
```

## Terminal Demo

From a cloned repository:

```text
$ python examples/demo.py
[ok] Remembered: "Andrey is a trader who tracks market breakouts."
[ok] Remembered: "Andrey prefers short practical answers about AI agents."

Query: "Andrey trader agent"
-> Result 1 (0.60): "Andrey is a trader who tracks market breakouts."
-> Result 2 (0.30): "Andrey prefers short practical answers about AI agents."
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

WaveMind tracks benchmarks in two layers:

- **Implemented local checks** - fast, reproducible scripts that run from this repository and protect the core memory behavior.
- **Public benchmark roadmap** - external retrieval and memory benchmarks that should decide whether WaveMind is competitive outside hand-made demos.

Machine-readable benchmark matrix: `benchmarks/benchmark_matrix_results.json`.
Full generated benchmark report: [`benchmarks/BENCHMARK_REPORT.md`](benchmarks/BENCHMARK_REPORT.md).

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
| Public agent-memory evidence | On official LoCoMo `locomo10.json`, WaveMind reaches `evidence_recall@5 0.386` with hash embeddings and `0.547` with sentence-transformers. Chroma static reaches `0.185` / `0.383`; Qdrant static reaches `0.203` / `0.384`. | First real public memory benchmark result: WaveMind retrieves more labeled evidence, but Chroma is still the fastest static vector-store baseline. |
| Public retrieval sanity check | On BEIR SciFact, WaveMind reaches `nDCG@10 0.354`, `Recall@10 0.482`; Qdrant matches that quality; Chroma reaches `0.350` / `0.467` with identical hash embeddings. | Same-embedding retrieval quality is close. Chroma is fastest at `1.79 ms`; Qdrant local is `17.71 ms`; WaveMind exact path is `117.02 ms`. |
| Static agent recall | WaveMind `precision@1` equals Chroma at `0.82`; WaveMind `precision@3` is `0.90` vs Chroma `0.88`. | Competitive quality, but Chroma is faster on the static vector-store path. |
| Dynamic memory policy | WaveMind reaches `1.00` stale suppression; Chroma static is `0.00`. | This is the strongest current differentiation: hotness, TTL, corrections, and namespaces. |
| Field memory dynamics | Graph-enabled WaveMind reaches `1.00` `precision@1`, `1.00` stale suppression, and `1.00` concept formation vs static WaveMind at `0.20` / `0.20` / `0.00`. | This is still synthetic, but it is the first regression check for memory-to-memory excitation, conflict inhibition, and decay. |
| Long-term evidence | WaveMind reaches `1.00` evidence recall@5, `1.00` precision@1, and `1.00` stale suppression on the synthetic long-memory evidence benchmark. | This is the first proof-shaped benchmark for agent memory: it measures whether stale/corrected/expired/cross-user facts stay out of retrieved evidence. |
| Capacity | Static `precision@1` is `0.94` at 5000 memories; dynamic policy keeps `1.00` on the current checks. | Quality is holding on these checks, but dynamic latency must be optimized. |
| LongMemEval subset | On the official LongMemEval-S cleaned file, first 50 non-abstention session-level questions, WaveMind reaches `evidence_recall@5 0.920` and `precision@1 0.780`; Chroma static reaches `0.100` / `0.040`; Qdrant static reaches `0.120` / `0.040`. | Strong early signal for long-term memory retrieval, but this is a 50-query subset, not a full LongMemEval score. |
| Next public proof | Full LongMemEval-S, LoCoMo answer generation, and an ANN/VectorDBBench-style latency curve. | The next serious memory number should test updates, abstention, temporal reasoning, answer quality with an LLM, and scaling beyond exact NumPy search. |

### Real Benchmark Matrix

| benchmark | what it proves | status | baseline / competitor | target |
|---|---|---|---|---|
| Agent user-memory retrieval | Natural-language recall over 200 user facts. | implemented | Chroma | Match Chroma `precision@1`, beat `precision@3`, stay under 5 ms at 200 memories. |
| Dynamic memory policy | Hot memory, TTL, corrections, stale suppression, namespace isolation. | implemented | Chroma static | Keep `precision@1` and stale suppression at 1.00, cut avg latency below 10 ms at 1000 memories. |
| Field memory graph dynamics | Related memories excite each other, newer conflicting memories suppress stale facts, graph energy decays, and active clusters expose concept candidates. | implemented | WaveMind static | Keep `precision@1`, stale suppression, and concept formation at 1.00 while moving from synthetic checks to LoCoMo/LongMemEval evidence. |
| WaveMind capacity curve | How recall and latency change at 200 / 1000 / 5000 memories. | implemented | WaveMind-only today | Keep `precision@1 >= 0.95` at 5000 memories and dynamic latency below 20 ms. |
| Long-term memory evidence | Evidence retrieval from long histories with profile, preference, correction, TTL, namespace, and filler noise. | implemented | Static vector / Chroma / Qdrant | Keep this as a small regression test while public LoCoMo and LongMemEval runners carry the stronger evidence claims. |
| BEIR-style open retrieval runner | Public `corpus.jsonl`, `queries.jsonl`, `qrels/*.tsv` datasets with the same metrics for each engine. | implemented | WaveMind / Chroma / Qdrant | Use identical embeddings and report `nDCG@k`, `Recall@k`, `MRR@k`, `precision@1`, and latency. Current checked-in run: BEIR SciFact. |
| [BEIR](https://github.com/beir-cellar/beir) | Standard zero-shot information retrieval quality. | planned | Chroma / Qdrant / FAISS | Stay within 0.02 `nDCG@10` on identical embeddings. |
| [MTEB Retrieval](https://github.com/embeddings-benchmark/mteb) | Separates encoder quality from retrieval-store quality. | planned | Chroma / Qdrant / FAISS | Prove WaveMind does not reduce same-embedding retrieval quality. |
| [MIRACL Russian](https://miracl.ai/) | Multilingual retrieval with Russian relevance judgments. | planned | Chroma / Qdrant / FAISS | Reach same-embedding parity on Russian `nDCG@10`. |
| [ANN-Benchmarks](https://github.com/erikbern/ann-benchmarks) style curve | Recall/latency tradeoff for vector indexes. | planned | FAISS / Annoy / Qdrant HNSW | Keep `recall@10 >= 0.95` while beating NumPy exact latency. |
| [VectorDBBench](https://github.com/zilliztech/VectorDBBench) | Vector database insertion/search/filter/cost-performance benchmark. | planned | Chroma / Qdrant / Milvus / Weaviate / Pinecone / FAISS | Use only after WaveMind has a production index path; today it is a memory layer, not a standalone cloud vector DB. |
| [LoCoMo](https://arxiv.org/abs/2402.17753) | Long conversation memory, temporal consistency, multi-hop recall. Retrieval-only runner is implemented for official `locomo10.json`. | implemented | Static vector / Chroma / Qdrant | Improve answer generation accuracy on top of the stronger sentence-transformers evidence retrieval run. |
| [LongMemEval](https://arxiv.org/abs/2410.10813) | Long-term assistant memory with updates and abstention. | implemented subset, full run planned | Static vector / Chroma / Qdrant / Mem0-style memory | Move from the first 50 official questions to the full LongMemEval-S retrieval and answer-quality run. |
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

Checked-in official LoCoMo retrieval result:

10 conversations, 5882 memory turns, 1977 evidence-labeled questions,
`HashingTextEncoder`, top-k 5. Full machine-readable result:
`benchmarks/locomo_evidence_results.json`.

| engine | evidence recall@5 | precision@1 | MRR@5 | avg latency | p95 latency |
|---|---:|---:|---:|---:|---:|
| WaveMind | 0.386 | 0.239 | 0.307 | 19.65 ms | 37.51 ms |
| Static vector | 0.203 | 0.117 | 0.154 | 23.14 ms | 34.70 ms |
| Chroma static | 0.185 | 0.110 | 0.143 | 3.06 ms | 5.83 ms |
| Qdrant static | 0.203 | 0.117 | 0.154 | 23.63 ms | 36.11 ms |

Checked-in semantic LoCoMo run:

Same official data, same engines, but with
`sentence-transformers/paraphrase-multilingual-mpnet-base-v2`. Full
machine-readable result: `benchmarks/locomo_sentence_evidence_results.json`.

| engine | evidence recall@5 | precision@1 | MRR@5 | avg latency | p95 latency |
|---|---:|---:|---:|---:|---:|
| WaveMind | 0.547 | 0.333 | 0.432 | 13.05 ms | 22.99 ms |
| Static vector | 0.384 | 0.205 | 0.288 | 14.81 ms | 18.96 ms |
| Chroma static | 0.383 | 0.205 | 0.288 | 1.55 ms | 2.20 ms |
| Qdrant static | 0.384 | 0.205 | 0.288 | 26.81 ms | 31.37 ms |

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

Run a bounded session-level subset:

```sh
python benchmarks/longmemeval_memory_benchmark.py --dataset benchmarks/data/longmemeval_s_cleaned.json --engines wavemind static chroma qdrant --granularity session --top-k 5 --limit-queries 50 --output benchmarks/longmemeval_evidence_50_results.json
```

Checked-in official LongMemEval-S subset result:

First 50 non-abstention questions from `longmemeval_s_cleaned.json`,
2436 session memories, `HashingTextEncoder`, top-k 5. This is a real official
dataset subset, not the full LongMemEval score. Full machine-readable result:
`benchmarks/longmemeval_evidence_50_results.json`.

| engine | evidence recall@5 | precision@1 | MRR@5 | context saved | avg latency | p95 latency |
|---|---:|---:|---:|---:|---:|---:|
| WaveMind | 0.920 | 0.780 | 0.838 | 0.869 | 2.56 ms | 5.30 ms |
| Static vector | 0.120 | 0.040 | 0.063 | 0.918 | 5.94 ms | 7.15 ms |
| Chroma static | 0.100 | 0.040 | 0.058 | 0.917 | 3.08 ms | 3.42 ms |
| Qdrant static | 0.120 | 0.040 | 0.063 | 0.918 | 10.52 ms | 15.85 ms |

This result is intentionally labeled as a subset. The next step is the full
LongMemEval-S run, turn-level evidence mode, and answer-quality evaluation with
a local LLM.

### Current Local Runs

Field memory dynamics benchmark:

13 memories, 5 conflicting-fact queries, deterministic local encoder.
This benchmark isolates the `MemoryFieldGraph`: related memories can spread
activation, newer conflicting memories inhibit stale facts, graph energy decays,
and active clusters can surface concept candidates.
Full machine-readable result: `benchmarks/field_memory_dynamics_results.json`.

| engine | precision@1 | precision@3 | stale suppression | concept formation | decay ratio | avg latency |
|---|---:|---:|---:|---:|---:|---:|
| WaveMind graph | 1.00 | 1.00 | 1.00 | 1.00 | 0.81 | 0.82 ms |
| WaveMind static | 0.20 | 1.00 | 0.20 | 0.00 | 0.00 | 0.43 ms |

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
- For `N > 5000`, use the Annoy or FAISS backend as candidate generation, or put WaveMind above a production vector index such as Qdrant.
- `sentence-transformers/paraphrase-multilingual-mpnet-base-v2` requires about 420 MB of model files. Benchmark runners cache embeddings so retrieval latency is measured separately from model encoding latency.
- The Chroma comparison currently uses shared precomputed hash embeddings to isolate retrieval/ranking behavior; semantic model comparisons should be run separately.
- The BEIR SciFact run uses the hash encoder to isolate index/retrieval behavior. It is not a semantic embedding leaderboard result.
- On BEIR SciFact, WaveMind and Qdrant match on hash-encoder `nDCG@10`, while Chroma is much faster. The next index milestone is FAISS/Annoy candidate generation plus WaveMind top-k re-ranking.
- The LoCoMo results are retrieval-only evidence results, not final answer-quality scores. The sentence-transformers run is stronger than the hash run, but still needs answer generation and faithfulness checks.
- In the 200-fact agent benchmark, Chroma is faster on average while WaveMind is slightly higher at `precision@3`.
- The dynamic benchmark currently compares WaveMind against a static Chroma baseline. Chroma and Qdrant can implement similar behavior with extra application-layer metadata policy, deletes, filters, and reinforcement logic.
- `MemoryFieldGraph` is a discrete graph over stored memories, not a continuous mathematical field. Its current build path should be optimized with incremental edge updates before large production use.
- The synthetic long-term memory evidence benchmark is useful for regression and product-shape proof, but it is not a substitute for full LoCoMo or full LongMemEval public runs.
- The LongMemEval number in this README is a 50-query official subset. It is useful evidence, but it is not a full LongMemEval leaderboard-equivalent score.
- MTEB, MIRACL, LMEB, ANN-Benchmarks, VectorDBBench, and RAGBench are listed as the public benchmark roadmap, not as completed results yet.
- Public benchmark adapters require optional datasets, heavier dependencies, or running services. They are intentionally outside the minimal `pip install wavemind` path.
- Dynamic memory is slower than static Chroma in the current local benchmark: 25.26 ms vs 1.75 ms average query latency on this machine.
- Current WaveMind-only dynamic checks keep `precision@1` at 1.00 through 5000 memories, but average latency is around 48-54 ms. The next optimization target is field/re-ranking latency, not basic recall quality.

## Roadmap

- FAISS-first production index path with persisted index rebuilds.
- Add public benchmark adapters in this order: full LongMemEval-S, BEIR NFCorpus, MIRACL Russian, ANN/VectorDBBench-style index curves, then LoCoMo/LongMemEval answer generation.
- Expand competitor baselines to Qdrant local/service mode, Chroma metadata-policy mode, FAISS, Annoy, and sentence-transformers.
- Optimize dynamic re-ranking latency after lexical candidate filtering.
- Better semantic query expansion for short and ambiguous queries.
- Namespace quotas, backups, and daemon hardening for SaaS use.
- Webhook on recall for agent runtimes.
- OHLCV pattern-memory experiments for market research and backtests.

## License

MIT. See [LICENSE](LICENSE).

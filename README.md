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
→ Result 1 (0.54): "Andrey is a trader who tracks market breakouts."
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

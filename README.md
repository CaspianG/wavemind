# WaveMind is persistent dynamic memory for AI agents: vector search first, wave-field priority second, SQLite as the source of truth.

![Python](https://img.shields.io/badge/python-3.10%2B-blue)
[![Tests](https://github.com/CaspianG/wavemind/actions/workflows/tests.yml/badge.svg)](https://github.com/CaspianG/wavemind/actions/workflows/tests.yml)
![License](https://img.shields.io/badge/license-MIT-green)

## Terminal Demo

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

```sh
python -m pip install -e .
wavemind remember "Andrey is a trader" --namespace demo
wavemind query "trader" --namespace demo
```

This creates `wavemind.sqlite3` in your current working directory.

For sentence-transformer embeddings:

```sh
python -m pip install -e ".[sentence]"
wavemind --encoder sentence remember "Andrey is a trader" --namespace demo
wavemind --encoder sentence query "What does Andrey do?" --namespace demo
```

One-file setup scripts are also included:

```sh
sh install.sh
```

```bat
install.bat
```

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

Run locally:

```sh
python benchmarks/ru_sentences_benchmark.py --sentences 200 --queries 50 --encoder hash --index numpy
python benchmarks/ru_sentences_benchmark.py --sentences 200 --queries 50 --encoder sentence --index numpy
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

WaveMind is not trying to replace dedicated vector databases at scale. Its difference is dynamic priority: frequently used memories can become hotter while old or low-priority memories fade.

## Known Limitations

- Optimal capacity on the current NumPy exact index is up to 1000 records.
- At 5000 records, one-word `precision@1` is currently 0.72 with the hash encoder; many misses are ambiguous queries where another sentence containing the same word ranks first.
- For `N > 5000`, use the FAISS backend with `--index faiss` or another production vector index.
- `sentence-transformers/paraphrase-multilingual-mpnet-base-v2` requires about 420 MB of model files and measured about 53 ms per query on the benchmark machine.
- The bundled benchmark is a retrieval sanity check, not a full agent-memory benchmark against Chroma or Qdrant yet.

## Roadmap

- FAISS-first production index path with persisted index rebuilds.
- Larger public benchmark against Chroma and Qdrant on agent-memory tasks.
- Better semantic query expansion for short and ambiguous queries.
- Namespace quotas, backups, and daemon hardening for SaaS use.
- Webhook on recall for agent runtimes.
- OHLCV pattern-memory experiments for market research and backtests.

## License

MIT. See [LICENSE](LICENSE).

# WaveMind Public Benchmark Brief

This is the human-readable benchmark report for launch posts. It summarizes
checked-in benchmark artifacts only. It is not an official leaderboard and it
does not claim WaveMind is a faster static vector database than Chroma, Qdrant,
FAISS, or pgvector.

## Short Readout

WaveMind is strongest when memory behavior matters:

- stale facts should be suppressed;
- newer corrections should outrank older facts;
- temporary facts should expire;
- namespaces should prevent cross-user leakage;
- repeated recall should reinforce useful memories.

Static vector search is still faster in several retrieval-only cases. The
current evidence says WaveMind is a dynamic memory layer, not a replacement for
purpose-built vector databases.

## Checked-In Result Summary

| benchmark | result | artifact | reproduce |
|---|---|---|---|
| Dynamic memory policy | WaveMind reaches `precision@1 1.00` and `stale suppression 1.00`; Chroma static reaches `precision@1 0.57` and `stale suppression 0.00`. | `benchmarks/dynamic_memory_results.json` | `python benchmarks/dynamic_memory_benchmark.py --engines wavemind chroma --memories 200 --output benchmarks/dynamic_memory_results.json` |
| LoCoMo evidence retrieval | WaveMind sentence reaches `evidence_recall@5 0.547`; Chroma sentence reaches `0.407`; Qdrant sentence reaches `0.409`. | `benchmarks/locomo_sentence_evidence_results.json` | `python benchmarks/locomo_memory_benchmark.py --engines wavemind-sentence chroma-sentence qdrant-sentence --output benchmarks/locomo_sentence_evidence_results.json` |
| LongMemEval evidence retrieval | WaveMind reaches `evidence_recall@5 0.782`; Chroma static reaches `0.518`; Qdrant static reaches `0.520`. | `benchmarks/longmemeval_evidence_results.json` | `python benchmarks/longmemeval_memory_benchmark.py --engines wavemind chroma qdrant --output benchmarks/longmemeval_evidence_results.json` |
| LongMemEval answer smoke | With local Ollama `qwen2.5:1.5b`, WaveMind reaches `token_f1 0.333`; Chroma static and Qdrant static reach `0.170`. | `benchmarks/longmemeval_answer_qwen25_1_5b_50_results.json` | `python benchmarks/longmemeval_answer_benchmark.py --dataset benchmarks/data/longmemeval_s_cleaned.json --provider ollama --model qwen2.5:1.5b --engines wavemind chroma qdrant --limit-queries 50 --output benchmarks/longmemeval_answer_qwen25_1_5b_50_results.json` |
| BEIR SciFact retrieval | WaveMind reaches `nDCG@10 0.354`; Chroma reaches `0.350`; Qdrant reaches `0.354`. Chroma is much faster on this static retrieval path. | `benchmarks/open_retrieval_scifact_results.json` | `python benchmarks/open_retrieval_benchmark.py --dataset scifact --engines wavemind chroma qdrant --output benchmarks/open_retrieval_scifact_results.json` |
| NoMIRACL Russian retrieval | WaveMind reaches `nDCG@10 0.434`; Chroma reaches `0.435`; Qdrant reaches `0.433`. Chroma is faster. | `benchmarks/nomiracl_russian_results.json` | `python benchmarks/nomiracl_russian_benchmark.py --engines wavemind chroma qdrant --output benchmarks/nomiracl_russian_results.json` |
| Production index profile | At 50000 vectors, persisted FAISS and Qdrant service both reach `recall@10 1.000`; pgvector with `ef_search=400` reaches `0.811`. | `benchmarks/production_index_profile_results.json` | `docker compose -f examples/production-index-profile/docker-compose.yml run --rm benchmark` |
| Production load profile | At 100000 vectors, Qdrant service reaches `recall@10 1.000`, avg `10.28 ms`, p99 `21.26 ms`. At 1M vectors, tuned Qdrant reaches `0.984`, avg `116.80 ms`, p99 `209.28 ms`; the best EF-sweep point reaches `0.977`, avg `64.76 ms`, p99 `103.77 ms`. | `benchmarks/production_load_qdrant_100k_tuned_results.json`, `benchmarks/production_load_qdrant_1m_tuned_results.json`, `benchmarks/production_load_qdrant_1m_ef_sweep_results.json` | `python benchmarks/production_load_benchmark.py --sizes 100000 --engines qdrant-service` |
| Scale readiness profile | Deterministic 1M-memory simulation: namespace placement survives node loss and zone loss at `1.000`, hot-cache hit rate is `0.920`, replicated runtime survives node loss, active-active delta sync converges, replicated snapshot restore survives primary loss, offsite mirror verification is `true`, portable archive verification is `true`, S3-compatible upload verification is `true`, structured payload precision@1 is `1.000`. | `benchmarks/scale_readiness_results.json` | `python benchmarks/scale_readiness_benchmark.py --simulated-memories 1000000 --output benchmarks/scale_readiness_results.json` |
| Memory competitor adapter profile | WaveMind reaches `precision@1 0.80`, `precision@3 1.00`, stale suppression `1.00`; Mem0, Zep, and LangGraph are skipped until real packages/services are configured. | `benchmarks/memory_competitor_results.json` | `python benchmarks/memory_competitor_benchmark.py --engines wavemind mem0 zep langgraph` |

The generated matrix view is in `benchmarks/BENCHMARK_REPORT.md`; the compact
leaderboard view is in `benchmarks/BENCHMARK_LEADERBOARD.md`.

## What This Proves

WaveMind has credible early evidence for dynamic agent memory:

- it can outperform static vector retrieval when facts update, expire, or
  conflict;
- it can retrieve more labeled long-memory evidence on LoCoMo and LongMemEval
  with the checked-in benchmark settings;
- it can preserve same-embedding retrieval quality on public retrieval datasets
  such as BEIR/SciFact and NoMIRACL Russian.

## What This Does Not Prove Yet

This report does not prove:

- an official LoCoMo, LongMemEval, MTEB, MIRACL, RAGBench, or VectorDBBench
  leaderboard score;
- that WaveMind is faster than Chroma for static vector retrieval;
- that the current local answer-generation smoke run is a full answer-quality
  benchmark;
- that the scale-readiness profile is a 10M-vector database load test;
- that pgvector is already a recommended production candidate index for
  WaveMind. The current profile improves recall but still misses the production
  target;
- that the current 1M Qdrant service profile has a stable sub-100 ms p99 SLO.
  Tuned Qdrant now reaches `recall@10 0.984`, but the 50-query p99 is still
  `209.28 ms`. The EF sweep gets close at `0.977` recall and `103.77 ms` p99,
  so the next work is repeatable 100+ query tuning.

## Launch Post: Hacker News

Title:

```text
Show HN: WaveMind benchmark report, dynamic memory vs static vector retrieval
```

Post:

```text
I have been building WaveMind, an MIT-licensed local-first dynamic memory layer
for apps and agents.

The benchmark report is now checked into the repo. The short version:

- On dynamic memory policy, WaveMind reaches precision@1 1.00 and stale
  suppression 1.00; a static Chroma baseline reaches precision@1 0.57 and stale
  suppression 0.00.
- On LongMemEval evidence retrieval, WaveMind reaches evidence_recall@5 0.782;
  Chroma static reaches 0.518 and Qdrant static reaches 0.520.
- On BEIR/SciFact static retrieval, WaveMind is at retrieval-quality parity but
  Chroma is much faster. This is a real limitation.
- On the production index profile at 50000 vectors, persisted FAISS and Qdrant
  service both reach recall@10 1.000. pgvector is improved but not ready as the
  recommended candidate index.
- On the 100000-vector production load profile, Qdrant service reaches
  recall@10 1.000, avg 10.28 ms, and p99 21.26 ms. On the tuned 1M Qdrant run,
  recall reaches 0.984, but p99 still needs work before a stable SLO claim.

I am not claiming this replaces vector databases. WaveMind is a memory-behavior
layer: TTL, hotness, corrections, namespaces, priority, audit, backups, and
explicit forgetting around vector candidate search.

All results have checked-in JSON artifacts and reproduction commands.
```

## Launch Post: Reddit

Title:

```text
I benchmarked my open-source dynamic memory layer against static vector retrieval
```

Post:

```text
I am building WaveMind, an MIT-licensed local-first memory layer for agents and
apps. I finally put together a checked-in benchmark report instead of just
describing the idea.

The main thing I wanted to test: when memory changes over time, does a dynamic
memory layer help compared with plain vector retrieval?

Current results:

- Dynamic memory policy: WaveMind precision@1 1.00, stale suppression 1.00;
  Chroma static precision@1 0.57, stale suppression 0.00.
- LongMemEval evidence retrieval: WaveMind evidence_recall@5 0.782; Chroma
  static 0.518; Qdrant static 0.520.
- LoCoMo sentence evidence retrieval: WaveMind 0.547; Chroma 0.407; Qdrant
  0.409.
- BEIR/SciFact static retrieval: quality is roughly at parity, but Chroma is
  much faster. I am not hiding that.
- Production load: Qdrant service is strong at 100k vectors. Tuned 1M Qdrant
  now reaches recall@10 0.984, but p99 latency still needs work before a stable
  sub-100 ms SLO claim.

The conclusion is not "WaveMind is a better vector DB." It is not. The
conclusion is narrower: if you need TTL, corrections, hotness, namespaces,
stale-fact suppression, audit, and local source-of-truth storage, a dynamic
memory layer can beat static vector retrieval on memory-shaped workloads.

The repo includes JSON result artifacts and commands for reproduction. I would
like feedback on the benchmark design, especially from people building
long-running agents or local-first RAG tools.
```

## Launch Post: X Thread

1.

```text
I published a checked-in benchmark report for WaveMind.

WaveMind is an open-source dynamic memory layer for apps/agents. The question:
can memory policy beat plain vector retrieval when facts update, expire, or
conflict?
```

2.

```text
Dynamic memory policy:

WaveMind:
precision@1 1.00
stale suppression 1.00

Chroma static:
precision@1 0.57
stale suppression 0.00

This is the strongest current signal.
```

3.

```text
LongMemEval evidence retrieval:

WaveMind evidence_recall@5: 0.782
Chroma static: 0.518
Qdrant static: 0.520

This is retrieval-only, not a full official answer-quality leaderboard.
```

4.

```text
Static retrieval reality check:

On BEIR/SciFact, WaveMind is around retrieval-quality parity, but Chroma is much
faster.

So the claim is not "better vector DB". The claim is "memory behavior layer".
```

5.

```text
Production index profile at 50k vectors:

WaveMind persisted FAISS recall@10: 1.000, avg 3.52 ms
Qdrant service recall@10: 1.000, avg 4.41 ms
pgvector recall@10: 0.811, avg 10.95 ms

pgvector still needs tuning.
```

6.

```text
Production load:

100k Qdrant service:
recall@10 1.000
avg 10.28 ms
p99 21.26 ms

1M Qdrant service tuned:
recall@10 0.984
avg 116.80 ms
p99 209.28 ms

1M Qdrant EF sweep best recall point:
hnsw_ef 2048
recall@10 0.977
avg 64.76 ms
p99 103.77 ms

The 1M path is now recall-credible, but not yet a stable sub-100 ms p99 SLO.
Next work: collection-level HNSW build tuning and 100+ query confirmation.
```

7.

```text
The full report includes checked-in JSON artifacts and reproduction commands.

WaveMind is MIT licensed, local-first, installable with:

pip install wavemind

Repo: https://github.com/CaspianG/wavemind
```

## Follow-Up Issues To Open From Feedback

Convert real launch feedback into issues using these categories:

- benchmark methodology;
- missing baseline;
- unclear install path;
- misleading README copy;
- integration request;
- performance bottleneck;
- docs/example gap.

# WaveMind Benchmark Report

This report is generated from `benchmarks/benchmark_matrix_results.json`.
It separates completed local runs from runner-ready public benchmarks and planned external evaluations.

Planned rows are not claimed wins. They are the public proof path WaveMind must complete before stronger production claims.

## Completed Runs

| benchmark | category | status | current result | next step |
|---|---|---|---|---|
| Agent user-memory retrieval | agent-memory | implemented | WaveMind: precision@1 0.82, precision@3 0.90, avg latency 2.25, p95 latency 6.89<br>Chroma: precision@1 0.82, precision@3 0.88, avg latency 0.93, p95 latency 1.09 | Run the same benchmark with sentence-transformers and a FAISS-backed candidate index. |
| Dynamic memory policy | agent-memory | implemented | WaveMind: precision@1 1.00, precision@3 1.00, stale suppression 1.00, avg latency 25.3, p95 latency 28.5<br>Chroma static: precision@1 0.57, precision@3 1.00, stale suppression 0.00, avg latency 1.75, p95 latency 6.28 | Add Chroma metadata-policy and Qdrant payload-filter baselines so the comparison is not only static-vector search. |
| Field memory graph dynamics | agent-memory | implemented | WaveMind graph: precision@1 1.00, precision@3 1.00, stale suppression 1.00, concept formation 1.00, decay ratio 0.81, avg latency 0.82<br>WaveMind static: precision@1 0.20, precision@3 1.00, stale suppression 0.20, concept formation 0.00, decay ratio 0.00, avg latency 0.43 | Make MemoryFieldGraph incremental and evaluate conflict/update behavior on public long-memory datasets. |
| WaveMind capacity curve | capacity | implemented | static_agent_memory: 3 points, last p@1 0.94, avg 13.7 ms<br>dynamic_agent_memory: 3 points, last p@1 1.00, avg 48.4 ms | Move candidate generation to FAISS/Annoy and limit wave-field reranking to the top candidate set. |
| Long-term memory evidence | long-term-agent-memory | implemented | WaveMind: evidence recall@k 1.00, precision@1 1.00, stale suppression 1.00, context saved 0.87, avg latency 6.10, p95 latency 8.99<br>Static vector: evidence recall@k 1.00, precision@1 0.57, stale suppression 0.00, context saved 0.88, avg latency 0.65, p95 latency 0.94 | Run the same normalized evidence benchmark with Chroma and Qdrant installed, then add LoCoMo or LongMemEval adapters. |
| BEIR-style open retrieval runner | retrieval | implemented | WaveMind: nDCG@k 0.35, Recall@k 0.48, MRR@k 0.32, precision@1 0.24, avg latency 117.0, p95 latency 256.6<br>Chroma: nDCG@k 0.35, Recall@k 0.47, MRR@k 0.32, precision@1 0.24, avg latency 1.79, p95 latency 2.39<br>Qdrant: nDCG@k 0.35, Recall@k 0.48, MRR@k 0.32, precision@1 0.24, avg latency 17.7, p95 latency 23.3 | Add sentence-transformers runs for SciFact, then add NFCorpus as the second BEIR dataset. |
| [LoCoMo evidence retrieval runner](https://github.com/snap-research/locomo) | long-term-conversation-memory | implemented | WaveMind: evidence recall@k 0.39, precision@1 0.24, MRR@k 0.31, context saved 0.00, avg latency 19.7, p95 latency 37.5<br>Static vector: evidence recall@k 0.20, precision@1 0.12, MRR@k 0.15, context saved 0.00, avg latency 23.1, p95 latency 34.7<br>Chroma static: evidence recall@k 0.18, precision@1 0.11, MRR@k 0.14, context saved 0.00, avg latency 3.06, p95 latency 5.83<br>Qdrant static: evidence recall@k 0.20, precision@1 0.12, MRR@k 0.15, context saved 0.00, avg latency 23.6, p95 latency 36.1<br>WaveMind sentence: evidence recall@k 0.55, precision@1 0.33, MRR@k 0.43, context saved 0.00, avg latency 13.0, p95 latency 23.0<br>Chroma sentence: evidence recall@k 0.38, precision@1 0.21, MRR@k 0.29, context saved 0.00, avg latency 1.55, p95 latency 2.20<br>Qdrant sentence: evidence recall@k 0.38, precision@1 0.21, MRR@k 0.29, context saved 0.00, avg latency 26.8, p95 latency 31.4 | Add LoCoMo answer generation with a local LLM and measure answer accuracy/faithfulness. |
| [LongMemEval evidence retrieval subset](https://github.com/xiaowu0162/LongMemEval) | long-term-agent-memory | implemented | WaveMind: evidence recall@k 0.92, precision@1 0.78, MRR@k 0.84, context saved 0.87, avg latency 2.56, p95 latency 5.30<br>Chroma static: evidence recall@k 0.10, precision@1 0.04, MRR@k 0.06, context saved 0.92, avg latency 3.08, p95 latency 3.42<br>Qdrant static: evidence recall@k 0.12, precision@1 0.04, MRR@k 0.06, context saved 0.92, avg latency 10.5, p95 latency 15.9 | Run full LongMemEval-S and turn-level evidence mode with sentence-transformers. |

## Runner-Ready Public Benchmarks

None currently. LoCoMo and BEIR/SciFact now have checked-in retrieval results.

## Public Benchmark Roadmap

| benchmark | category | status | competitors | target |
|---|---|---|---|---|
| [BEIR](https://github.com/beir-cellar/beir) | retrieval | planned | Chroma, Qdrant, FAISS | On identical embeddings, stay within 0.02 nDCG@10 of Chroma/Qdrant and keep WaveMind reranking latency below 10 ms. |
| [MTEB Retrieval](https://github.com/embeddings-benchmark/mteb) | retrieval | planned | Chroma, Qdrant, FAISS | Use MTEB to separate encoder quality from memory-policy quality; WaveMind should not reduce same-embedding retrieval quality. |
| [MIRACL Russian](https://miracl.ai/) | multilingual-retrieval | planned | Chroma, Qdrant, FAISS | Prove Russian recall with semantic embeddings; target nDCG@10 parity with same-embedding Chroma/Qdrant. |
| [ANN-Benchmarks style index curve](https://github.com/erikbern/ann-benchmarks) | index-latency | planned | FAISS, Annoy, Qdrant HNSW | At 5000 to 100000 memories, preserve recall@10 >= 0.95 while cutting query latency below the NumPy exact path. |
| [VectorDBBench](https://github.com/zilliztech/VectorDBBench) | vector-db | planned | Chroma, Qdrant, Milvus, Weaviate, Pinecone, FAISS | Use this only after WaveMind has a production index path; current NumPy mode is not a fair vector database competitor. |
| [LoCoMo answer generation](https://arxiv.org/abs/2402.17753) | long-term-conversation-memory | planned | Chroma RAG, Qdrant RAG, Mem0-style memory | Beat static vector-store RAG on temporal/correction questions by at least 15 percentage points while returning compact evidence. |
| [LongMemEval](https://arxiv.org/abs/2410.10813) | long-term-agent-memory | planned | Chroma RAG, Qdrant RAG, Mem0-style memory | Demonstrate update/abstention gains over static vector recall without exceeding 100 ms retrieval latency. |
| [LongMemEval-V2](https://arxiv.org/abs/2605.12493) | web-agent-memory | planned | AgentRunbook-R, Chroma RAG, Qdrant RAG | Become a compact evidence retriever for agent trajectories, with explicit wins on dynamic state tracking and gotcha recall. |
| [LMEB](https://github.com/KaLM-Embedding/LMEB) | memory-embedding | planned | embedding-only baselines, Chroma, Qdrant | Use LMEB to choose the default semantic encoder and prove that memory retrieval is not just passage retrieval. |
| [RAGBench](https://huggingface.co/datasets/rungalileo/ragbench) | rag-quality | planned | Chroma RAG, Qdrant RAG, Pinecone RAG | Show whether WaveMind's dynamic suppression improves context quality when facts become stale or conflicting. |

## Reading Guide

- Retrieval benchmarks such as BEIR, MTEB, and MIRACL test whether WaveMind can preserve vector-search quality.
- Vector database benchmarks such as ANN-Benchmarks and VectorDBBench test latency, recall, and scale, not memory policy.
- Agent-memory benchmarks such as LoCoMo and LongMemEval are the most important public proof targets for WaveMind.
- The synthetic dynamic-memory and long-memory evidence checks remain useful regression tests, but they are not substitutes for public datasets.

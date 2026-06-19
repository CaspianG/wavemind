# WaveMind Benchmark Report

This report is generated from `benchmarks/benchmark_matrix_results.json`.
It separates completed local runs from runner-ready public benchmarks and planned external evaluations.

Planned rows are not claimed wins. They are the public proof path WaveMind must complete before stronger production claims.

## Completed Runs

| benchmark | category | status | current result | next step |
|---|---|---|---|---|
| Agent user-memory retrieval | agent-memory | implemented | WaveMind: precision@1 0.82, precision@3 0.90, avg latency 2.25, p95 latency 6.89<br>Chroma: precision@1 0.82, precision@3 0.88, avg latency 0.93, p95 latency 1.09 | Run the same benchmark with sentence-transformers and a FAISS-backed candidate index. |
| Dynamic memory policy | agent-memory | implemented | WaveMind: precision@1 1.00, precision@3 1.00, stale suppression 1.00, avg latency 25.3, p95 latency 28.5<br>Chroma static: precision@1 0.57, precision@3 1.00, stale suppression 0.00, avg latency 1.75, p95 latency 6.28 | Add Chroma metadata-policy and Qdrant payload-filter baselines so the comparison is not only static-vector search. |
| Field memory graph dynamics | agent-memory | implemented | WaveMind graph: precision@1 1.00, precision@3 1.00, stale suppression 1.00, concept formation 1.00, decay ratio 0.81, avg latency 0.82<br>WaveMind static: precision@1 0.20, precision@3 1.00, stale suppression 0.20, concept formation 0.00, decay ratio 0.00, avg latency 0.43 | Make MemoryFieldGraph incremental and add public-dataset conflict/update scenarios instead of only deterministic synthetic checks. |
| WaveMind capacity curve | capacity | implemented | static_agent_memory: 3 points, last p@1 0.94, avg 13.7 ms<br>dynamic_agent_memory: 3 points, last p@1 1.00, avg 48.4 ms | Move candidate generation to FAISS/Annoy and limit wave-field reranking to the top candidate set. |
| Long-term memory evidence | long-term-agent-memory | implemented | WaveMind: evidence recall@k 1.00, precision@1 1.00, stale suppression 1.00, context saved 0.87, avg latency 6.10, p95 latency 7.43<br>Static vector: evidence recall@k 1.00, precision@1 0.57, stale suppression 0.00, context saved 0.88, avg latency 0.65, p95 latency 1.01 | Run the same normalized evidence benchmark with Chroma and Qdrant installed, then add LoCoMo or LongMemEval adapters. |
| BEIR-style open retrieval runner | retrieval | implemented | No checked-in result yet. | Download SciFact or NFCorpus into benchmarks/data and publish the first full public-dataset result JSON. |

## Runner-Ready Public Benchmarks

| benchmark | category | status | current result | next step |
|---|---|---|---|---|
| [LoCoMo evidence retrieval runner](https://github.com/snap-research/locomo) | long-term-conversation-memory | runner-ready | WaveMind: no checked-in result<br>Static vector: no checked-in result | Download locomo10.json in an unrestricted network environment and commit benchmarks/locomo_evidence_results.json from the full run. |

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

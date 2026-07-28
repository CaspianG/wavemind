# Public Memory Competitors

Official LoCoMo: **5,882 memories**, **1,977 evidence queries**, top-5.

| Engine | Recall@5 | Precision@1 | MRR@5 | Query avg | Query p95 | Ingest avg | Ingest scope |
|---|---:|---:|---:|---:|---:|---:|---|
| WaveMind | 0.548 | 0.333 | 0.432 | 4.88 ms | 7.67 ms | 0.61 ms | index_and_persistence_from_precomputed_embeddings |
| WaveMind + Memory OS | 0.548 | 0.332 | 0.431 | 5.99 ms | 8.67 ms | 0.49 ms | index_and_persistence_from_precomputed_embeddings |
| Chroma static | 0.408 | 0.219 | 0.305 | 4.12 ms | 4.86 ms | 0.75 ms | local_index_write_from_precomputed_embeddings |
| Qdrant static | 0.409 | 0.219 | 0.305 | 103.27 ms | 111.45 ms | 0.63 ms | local_index_write_from_precomputed_embeddings |
| Mem0 OSS | 0.500 | 0.263 | 0.369 | 270.24 ms | 293.08 ms | 217.91 ms | end_to_end_native_embedding_and_persistence |
| Hindsight OSS | 0.316 | 0.052 | 0.148 | 320.61 ms | 463.14 ms | 62.33 ms | end_to_end_native_embedding_and_persistence |

## Verdict

- Quality winner: **WaveMind** at recall@5 `0.548`.
- Fastest average local query: **Chroma static** at `4.12 ms`.

## Boundaries

- WaveMind, Chroma, and Qdrant ingest starts from shared precomputed embeddings. Mem0 and Hindsight ingest includes their native embedding and persistence work.
- This is LoCoMo retrieval evidence on one local machine. It is not final answer quality, hosted-service throughput, or an architecture-only comparison because real systems use their pinned native embedding stacks.
- Source commit: `4b6d7dd3e938dc04663bd7ba2c2356d5e7d1fe62`.
- Dataset SHA-256: `79fa87e90f04081343b8c8debecb80a9a6842b76a7aa537dc9fdf651ea698ff4`.

# Embeddings And Index Backends

WaveMind keeps durable memory state separate from candidate generation. SQLite
or PostgreSQL is the source of truth; local or service-backed vector indexes
produce candidates before WaveMind applies memory policy and re-ranking.

## Optional Embeddings

The base install uses the deterministic hash encoder so the Quick Start remains
offline and keyless.

For sentence-transformer embeddings:

```sh
python -m pip install "wavemind[sentence]"
wavemind --encoder sentence remember "Andrey is a trader" --namespace demo
wavemind --encoder sentence query "What does Andrey do?" --namespace demo
```

## Available Indexes

The default index is NumPy exact search. It is simple and reliable for local
memory. For larger candidate generation, WaveMind also exposes optional index
backends:

| index | Install | Notes |
|---|---|---|
| `numpy` | default | Exact cosine search, local, linear scan. |
| `quantized` | default | Local int8-compressed candidate index with int32-safe scoring. Useful for memory-footprint experiments; approximate recall and latency must still be measured per workload. |
| `annoy` | `pip install "wavemind[indexes]"` | Local ANN. Faster at larger N, but recall must be checked. |
| `faiss` | `pip install "wavemind[indexes]"` | FAISS flat inner-product path where `faiss-cpu` is available. |
| `faiss-persisted` | `pip install "wavemind[indexes]"` | FAISS with an explicit persisted index snapshot and id map. |
| `pgvector` | `pip install "wavemind[postgres]"` | PostgreSQL/pgvector candidate index. SQLite can still remain the local source of truth. |
| `qdrant` | `pip install "wavemind[indexes]"` | Qdrant service/local-mode candidate index. SQLite remains the source of truth; Qdrant stores vectors. |

Choose with evidence rather than by name alone:

1. Run `wavemind scale-plan --target-memories <N>`.
2. Measure recall and p95/p99 latency on your data.
3. Keep the source of truth independent from the candidate index.
4. Run `index-health` and rebuild from durable state when required.

## Persisted FAISS

```sh
export WAVEMIND_FAISS_PATH="./state/wavemind.faiss"
wavemind --index faiss-persisted remember "Andrey is a trader" --namespace demo
wavemind --index faiss-persisted query "trader" --namespace demo
```

The persisted FAISS files are a candidate-index snapshot and are validated
against the current memory ids, vector dimension, vector count, and a SHA-256
checksum of normalized source vectors on load. If the snapshot does not match
the stored memories, WaveMind rebuilds it from the durable store.

Check and rebuild explicitly:

```sh
wavemind --index faiss-persisted index-health --json
wavemind --index faiss-persisted rebuild-index
```

Local indexes report exact missing and extra ids. Service backends report exact
ids when the backend exposes an id scan and otherwise fall back to count-based
health.

## pgvector

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
- `WAVEMIND_PGVECTOR_EF_SEARCH` - optional per-query HNSW search depth.
- `WAVEMIND_PGVECTOR_ITERATIVE_SCAN=strict_order|relaxed_order|off` - optional
  iterative HNSW scan mode for higher recall on newer pgvector builds.
- `WAVEMIND_PGVECTOR_MAX_SCAN_TUPLES` and
  `WAVEMIND_PGVECTOR_SCAN_MEM_MULTIPLIER` - optional HNSW scan bounds.
- `WAVEMIND_PGVECTOR_EXACT=1` - force an exact scan for recall audits and
  correctness-sensitive jobs.

If `WAVEMIND_PGVECTOR_DSN` is missing, WaveMind raises a clear error instead of
silently falling back to another index backend. The table is created with the
current encoder dimension, so use a separate table when switching vector sizes.

## Qdrant

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

For tuning methodology, large-N artifacts, and claim boundaries, continue with
the [Benchmark Guide](BENCHMARKS.md) and
[Scale And Production](SCALE_AND_PRODUCTION.md).

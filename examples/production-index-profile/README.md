# Production Index Profile

This example runs the ANN/index production profile against real services:

- persisted FAISS inside the Linux benchmark container;
- Qdrant v1.18.2 in service mode;
- PostgreSQL with pgvector, HNSW enabled, and explicit `ef_search` tuning.

Run from the repository root:

```sh
docker compose -f examples/production-index-profile/docker-compose.yml up -d qdrant postgres
docker compose -f examples/production-index-profile/docker-compose.yml run --rm benchmark
docker compose -f examples/production-index-profile/docker-compose.yml down
```

The benchmark writes:

```text
benchmarks/production_index_profile_results.json
```

For the larger load profile, start the same services and run:

```sh
set WAVEMIND_QDRANT_URL=http://127.0.0.1:6333
set WAVEMIND_PGVECTOR_DSN=postgresql://wavemind:wavemind@127.0.0.1:15432/wavemind
set WAVEMIND_PGVECTOR_CREATE_HNSW=1
set WAVEMIND_PGVECTOR_EF_SEARCH=400
python benchmarks/production_load_benchmark.py --sizes 100000 --dim 128 --queries 100 --top-k 10 --engines qdrant-service pgvector pgvector-exact pgvector-iterative faiss-persisted
python benchmarks/production_load_benchmark.py --sizes 1000000 --dim 128 --queries 50 --top-k 10 --engines qdrant-service --output benchmarks/production_load_qdrant_1m_results.json
```

Use the Linux benchmark container for persisted FAISS, because `faiss-cpu` is
not installed for every Windows Python environment.
Use `pgvector-exact` as the recall floor and `pgvector-iterative` to tune the
HNSW + filtered-collection production path. If the installed pgvector version
does not support iterative scan settings, the runner reports that variant as
skipped or failed explicitly instead of silently falling back.

This is not an official VectorDBBench score. It is a reproducible WaveMind
candidate-index profile for checking recall, latency, build time, and persisted
FAISS startup behavior under the same generated vectors.

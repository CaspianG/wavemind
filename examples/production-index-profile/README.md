# Production Index Profile

This example runs the ANN/index production profile against real services:

- persisted FAISS inside the Linux benchmark container;
- Qdrant v1.18.2 in service mode;
- PostgreSQL with pgvector and HNSW enabled.

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

This is not an official VectorDBBench score. It is a reproducible WaveMind
candidate-index profile for checking recall, latency, build time, and persisted
FAISS startup behavior under the same generated vectors.

# Sharded Qdrant Streaming Smoke

This example starts two independent Qdrant services and runs the WaveMind
streaming benchmark with id-based routing plus parallel fanout merge.

```sh
docker compose -f examples/qdrant-sharded-streaming/docker-compose.yml up -d
```

```sh
WAVEMIND_QDRANT_URLS=http://127.0.0.1:6333,http://127.0.0.1:6334 \
WAVEMIND_QDRANT_COLLECTION_PREFIX=wavemind_sharded_smoke \
WAVEMIND_QDRANT_UPSERT_BATCH_SIZE=500 \
WAVEMIND_QDRANT_FANOUT_WORKERS=2 \
WAVEMIND_QDRANT_WAIT_AFTER_BUILD_SECONDS=2 \
WAVEMIND_QDRANT_WARMUP_QUERIES=10 \
python benchmarks/production_streaming_load_benchmark.py \
  --sizes 5000 \
  --dim 64 \
  --queries 20 \
  --top-k 10 \
  --batch-size 1000 \
  --engines qdrant-sharded-service \
  --output benchmarks/production_streaming_load_qdrant_sharded_smoke_results.json
```

```sh
docker compose -f examples/qdrant-sharded-streaming/docker-compose.yml down
```

The checked-in smoke artifact proves the runner can write to multiple Qdrant
services, route ids deterministically, query all shards in parallel, and merge
the scored top-k hits. It is not a 10M benchmark; the 10M sharded profile is
tracked separately as `benchmarks/production_streaming_load_qdrant_sharded_10m_plan.json`.

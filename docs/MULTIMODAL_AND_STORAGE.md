# Multimodal, Storage, And API

This guide contains the detailed data, lifecycle, and service reference moved from the project README.

## Structured And Multimodal Memory

WaveMind can store non-text memories as structured text plus metadata. This is
useful for product events, tables, call transcripts, images, videos, 3D assets,
and knowledge graphs while keeping the same query API.

```python
from wavemind import WaveMind, image_payload, remember_payload

memory = WaveMind()
remember_payload(
    memory,
    image_payload("s3://demo/chart.png", caption="enterprise revenue expansion chart"),
    namespace="research",
)
print(memory.query("enterprise expansion chart", namespace="research")[0].metadata)
```

For agent workflows that need one memory layer across payload types, use
`CrossModalMemoryLayer`. It stores typed payloads through WaveMind, keeps
provenance in metadata, and re-ranks inside an explicitly registered embedding
space. The zero-config descriptor encoder below is a local development path,
not evidence of real image, audio, video, or 3D understanding.

```python
from wavemind import CrossModalMemoryLayer, WaveMind, audio_payload, image_payload

memory = WaveMind()
layer = CrossModalMemoryLayer(memory)

layer.remember(image_payload("s3://demo/chart.png", caption="Q2 revenue chart"), namespace="research")
layer.remember(audio_payload("s3://demo/call.wav", transcript="Customer asked about Q2 revenue"), namespace="research")

for result in layer.query("revenue chart", namespace="research", target_modality="image"):
    print(result.modality, result.score, result.provenance)
```

If your application already computes CLIP/audio/video/3D embeddings, use the
strict precomputed-vector path. WaveMind stores the vector with the payload and
requires a query vector at search time, so there is no hidden descriptor
fallback:

```python
from wavemind import CrossModalMemoryLayer, PrecomputedCrossModalEncoder, WaveMind, image_payload

memory = WaveMind()
space_id = "openclip:ViT-B-32@laion2b-s34b-b79k"
layer = CrossModalMemoryLayer(
    memory,
    cross_modal_encoder=PrecomputedCrossModalEncoder(
        vector_dim=512,
        space_id=space_id,
        name="openclip",
        model_revision="laion2b-s34b-b79k",
    ),
)

layer.remember(
    image_payload(
        "s3://demo/chart.png",
        caption="Q2 revenue chart",
        metadata={
            "cross_modal_vector": image_clip_vector,
            "cross_modal_space_id": space_id,
        },
    ),
    namespace="research",
)
results = layer.query(
    "revenue chart",
    namespace="research",
    target_modality="image",
    query_vector=text_clip_vector,
    query_space_id=space_id,
)
```

Precomputed payload and query vectors must declare the same `space_id`. WaveMind
rejects a missing ID and rejects equal-length vectors from different spaces
before cosine similarity is calculated.

Mixed queries use the same rule and expose normalized fusion weights:

```python
from wavemind import CrossModalQueryPart

mixed_space_id = "imagebind:huge@pinned-revision"
mixed_layer = CrossModalMemoryLayer(
    memory,
    cross_modal_encoder=PrecomputedCrossModalEncoder(
        vector_dim=1024,
        space_id=mixed_space_id,
        name="imagebind",
        model_revision="pinned-revision",
        modalities=("text", "image", "audio", "video", "3d"),
    ),
)
results = mixed_layer.query_mixed(
    [
        CrossModalQueryPart(
            modality="image",
            vector=tuple(image_query_vector),
            space_id=mixed_space_id,
            weight=3,
        ),
        CrossModalQueryPart(
            modality="audio",
            vector=tuple(audio_query_vector),
            space_id=mixed_space_id,
            weight=1,
        ),
    ],
    namespace="research",
)
print(results[0].fusion)
print(results[0].score_breakdown)
```

To validate an explicitly precomputed-vector integration, run the external
storage contract. It writes representative image, audio, table, event, video,
3D, and graph payloads through the real memory layer, then checks global
retrieval, target-modality routing, persisted finite normalized vectors,
provenance, and separation margin:

```python
from wavemind import WaveMind, validate_precomputed_cross_modal_contract

memory = WaveMind()
report = validate_precomputed_cross_modal_contract(memory)
assert report.ok, report.failures
```

This proves storage and recall behavior only. It does not measure the encoder
that produced the vectors and cannot unlock real-encoder production admission.
External CLIP/audio/video/3D integrations should still run this contract before
publication, then pass the separate real-encoder benchmark.

For encoders that produce both payload and query vectors, run the active encoder
health check as a deployment preflight. It probes all supported modalities,
checks finite normalized vectors, target routing, global precision@1, dimension
compatibility, separation margin, and p95 encode latency:

```python
from wavemind import (
    DescriptorCrossModalEncoder,
    HashingTextEncoder,
    check_cross_modal_encoder_health,
)

encoder = DescriptorCrossModalEncoder(HashingTextEncoder(vector_dim=64), vector_dim=64)
report = check_cross_modal_encoder_health(encoder)
assert report.ok, report.failures
```

The checked-in structured-memory report includes this health gate, so a backend
can fail before it reaches traffic. Descriptor-based health checks remain
development checks, not production encoder evidence.

`wavemind multimodal-admission` applies the stricter release boundary. Admission
requires real local text, image, audio, video, and 3D encoders over at least
1000 real or publicly licensed assets and 200 independent queries, with at least
100 assets and 20 queries per modality. The evidence must include explicit
compatible shared-space IDs, bidirectional text-to-media and media-to-text
checks, per-modality precision and encoding budgets, persisted-vector parity,
three stable runs, and a complete S3-compatible lifecycle. Local MinIO is a
valid object-store target. Descriptor, filename, metadata, OCR-only,
synthetic-vector, and precomputed-vector shortcuts are rejected as encoder
evidence.

The checked public suite currently passes that boundary. It uses pinned local
SentenceTransformers, CLIP, CLAP, and OpenShape PointBERT revisions over 1000
public assets and 200 independent held-out queries. Three exact-SHA runs report
macro, cross-modal, and mixed precision@1 `0.925`, persisted/reload parity
`1.000`, retrieval p99 `48.64 ms`, and zero errors. The artifacts are
`benchmarks/multimodal_external_encoder_results.json`,
`benchmarks/multimodal_per_query.jsonl`,
`benchmarks/multimodal_per_asset.jsonl`, and
`benchmarks/multimodal_admission_results.json`. This admission is bounded to
the pinned suite, model revisions, source SHA, and tested local MinIO topology.

For production media, keep large files in S3-compatible object storage and store
a verified content-addressed manifest with the memory. This keeps SQLite/Postgres
as metadata source of truth while video, audio, image, and 3D bytes live in S3,
R2, or MinIO:

```python
from wavemind import S3AssetStore, video_payload

assets = S3AssetStore.from_uri("s3://wavemind-assets/media")
asset = assets.upload_asset("demo.mp4", kind="video")

payload = video_payload(
    asset.uri,
    summary="memory graph demo",
    metadata=asset.payload_metadata(),
)
```

`asset.payload_metadata()` includes `asset_sha256`, `asset_bytes`,
`asset_media_type`, and `asset_verified`; cross-modal results return those fields
in provenance so downstream agents can audit the exact media object behind a
recall.

For a built-in CLIP-style image/text backend, install the multimodal extra:

```sh
python -m pip install "wavemind[multimodal]"
```

```python
from wavemind import CrossModalMemoryLayer, SentenceTransformersCrossModalEncoder, WaveMind, image_payload

memory = WaveMind()
layer = CrossModalMemoryLayer(
    memory,
    cross_modal_encoder=SentenceTransformersCrossModalEncoder(
        "clip-ViT-B-32",
        model_revision="pinned-model-revision",
    ),
)

layer.remember(
    image_payload("chart.png", caption="Q2 revenue chart"),
    namespace="research",
)
results = layer.query("revenue chart", namespace="research", target_modality="image")
```

This backend loads local image files with Pillow and encodes text queries through
the same sentence-transformers model. It fails clearly for remote images and for
audio, video, or 3D instead of substituting a caption, filename, metadata, OCR,
or descriptor. Use a selectable backend that actually supports those modalities,
or provide explicitly scoped precomputed vectors for storage integration; the
precomputed path still cannot satisfy real-encoder admission.

Supported payload helpers:

| helper | use case |
|---|---|
| `image_payload()` | image URI plus caption or alt text |
| `audio_payload()` | audio URI plus transcript or summary |
| `video_payload()` | video URI plus transcript, scenes, duration, and summary |
| `asset3d_payload()` | 3D model URI plus labels, dimensions, and format |
| `table_payload()` | compact table preview with row count |
| `event_payload()` | structured product, user, or system event |
| `graph_payload()` | knowledge graph triples stored as queryable memory |

For graph-heavy memory, use `KnowledgeGraphMemoryLayer` when you need entity
filters and multi-hop traversal instead of plain text recall:

```python
from wavemind import KnowledgeGraphMemoryLayer, WaveMind

memory = WaveMind()
graph = KnowledgeGraphMemoryLayer(memory)

graph.remember_triples(
    [
        ("Andrey", "works_on", "trading agent"),
        ("trading agent", "uses", "WaveMind memory"),
    ],
    namespace="agent",
    title="agent memory graph",
)

path = graph.query(
    "how is Andrey connected to WaveMind memory?",
    namespace="agent",
    subject="Andrey",
    object="WaveMind memory",
    max_depth=2,
)[0]

print(path.depth, path.path, path.provenance)
```

Temporal events can also be queried as time-aware memory:

```python
from wavemind import TemporalEventMemoryLayer, WaveMind

memory = WaveMind()
events = TemporalEventMemoryLayer(memory)

events.remember(
    "risk limits reviewed",
    namespace="agent:trading",
    actor="agent",
    timestamp="2026-07-07T12:00:00Z",
    tags=["risk"],
)

fresh = events.query(
    "risk limits",
    namespace="agent:trading",
    actor="agent",
    recency_anchor="2026-07-08T12:00:00Z",
)
```

## Storage Backends

SQLite is the default source of truth. For multi-tenant production deployments,
WaveMind also exposes PostgreSQL as an explicit source-of-truth backend:

```sh
export WAVEMIND_STORE="postgres"
export WAVEMIND_POSTGRES_DSN="postgresql://user:password@localhost:5432/wavemind"
wavemind --store postgres remember "Andrey is a trader" --namespace user:andrey
wavemind --store postgres query "trader" --namespace user:andrey
```

Optional table environment variables:

- `WAVEMIND_POSTGRES_MEMORIES_TABLE`, default `wavemind_memories`.
- `WAVEMIND_POSTGRES_AUDIT_TABLE`, default `wavemind_audit_events`.

Postgres storage is separate from `pgvector`: Postgres storage keeps memories,
metadata, TTL, audit events, and vectors as durable application state; pgvector
is a candidate index backend for nearest-neighbor search. You can use SQLite
storage with pgvector, Postgres storage with NumPy/FAISS/Qdrant, or eventually
Postgres storage plus pgvector when you want both state and vector search inside
PostgreSQL.

## Backup And Restore

Exact one-file backup:

```sh
wavemind --db ./state/wavemind.sqlite3 backup --out ./backups/wavemind.sqlite3
```

Timestamped backups with retention:

```sh
wavemind --db ./state/wavemind.sqlite3 backup --out ./backups --prefix wavemind --keep-last 7
```

Restore into a new or replacement SQLite file:

```sh
wavemind restore --from ./backups/wavemind-20260630-120000.sqlite3 --to ./state/wavemind.sqlite3 --overwrite
```

The backup command uses SQLite's backup API, so it is safe to run while the
process is alive. Restore is intentionally an explicit command and refuses to
overwrite an existing database unless `--overwrite` is passed.

SQLite point-in-time recovery:

```python
import time

from wavemind import SQLiteMemoryStore, WaveMind

memory = WaveMind(
    db_path="./state/wavemind.sqlite3",
    recovery_journal_path="./state/wavemind.recovery.jsonl",
)
memory.remember("Tenant A prefers short support replies.", namespace="tenant:a")
checkpoint = time.time()
memory.remember("Tenant A switched to detailed reports.", namespace="tenant:a")
memory.forget(text="Tenant A prefers short support replies.", namespace="tenant:a")

SQLiteMemoryStore.restore_recovery_journal(
    "./state/wavemind.recovery.jsonl",
    "./state/restored-at-checkpoint.sqlite3",
    until=checkpoint,
)
```

Equivalent CLI:

```sh
wavemind --db ./state/wavemind.sqlite3 --recovery-journal ./state/wavemind.recovery.jsonl remember "Tenant A prefers short support replies." --namespace tenant:a
wavemind recovery-restore --from ./state/wavemind.recovery.jsonl --to ./state/restored.sqlite3 --overwrite --json
```

For API/server deployments, set `WAVEMIND_RECOVERY_JOURNAL=/data/wavemind.recovery.jsonl`.

The recovery journal is append-only JSONL. It records `remember`, `forget`, and
`purge_expired` mutations with the persisted memory id, text, metadata, tags,
vector, and field pattern, so restore replay does not need to call the encoder
again. Use regular SQLite backups for coarse snapshots and the journal when you
need to restore to a specific mutation boundary.

For Postgres storage, use database-native backup tooling such as `pg_dump`,
managed snapshots, or Postgres point-in-time recovery. WaveMind's JSONL recovery
journal is a local SQLite source-of-truth mechanism, not a replacement for
database-native WAL/PITR in managed Postgres.

Postgres PITR runbook/preflight:

```sh
wavemind postgres-pitr-plan --out ./ops/postgres-pitr-plan.json --json
```

This emits a secret-safe database-native runbook with WAL archiving, streaming
`pg_basebackup`, restore target configuration, replay verification, and
promotion steps. It stores environment variable names only, not DSNs or secret
values. The checked-in artifact is
`benchmarks/postgres_pitr_plan.json`; a real managed Postgres restore drill
should execute the plan in staging and record replay LSN, target timestamp,
restore duration, and post-restore row/index checks.

Replicated runtime snapshot/restore:

```python
from wavemind import HashingTextEncoder, ReplicatedSnapshotWorker, ReplicatedWaveMind

memory = ReplicatedWaveMind(
    root_path="./state/replicas",
    nodes=["node-a", "node-b", "node-c"],
    replication_factor=3,
    encoder=HashingTextEncoder(vector_dim=64),
)
memory.remember("Tenant A prefers short support replies.", namespace="tenant:a")

snapshot_job = ReplicatedSnapshotWorker(memory).run_once(
    destination="./backups/replicated",
    offsite_destination="./offsite/replicated",
    archive_destination="./archives/replicated",
    object_store_destination="s3://my-bucket/wavemind/prod",
    keep_last=7,
    object_store_keep_last=30,
)
assert snapshot_job.ok

restored, report = ReplicatedWaveMind.restore_snapshot_archive(
    snapshot_job.archive_path,
    "./state/restored-replicas",
    encoder=HashingTextEncoder(vector_dim=64),
)
```

The replicated snapshot job writes one SQLite backup per replica plus
`manifest.json` with SHA-256 checksums, replica metadata, quorum settings, and
node definitions. It can mirror the snapshot to a second path for offsite
backup, write a portable `.tar.gz` archive for object-store/offsite systems,
verify that archive, upload it to any S3-compatible object store through
`boto3`, list the newest remote archive, restore from the newest remote archive,
run a disaster-recovery drill from the newest or exact remote archive, and apply
`keep_last` retention locally, offsite, for archives, and explicitly for
object-store archives through `object_store_keep_last`.
Restore refuses to overwrite a non-empty root unless `overwrite=True` is passed.

Equivalent CLI:

```sh
wavemind replicated-snapshot \
  --root ./state/replicas \
  --node node-a --node node-b --node node-c \
  --out ./backups/replicated \
  --offsite ./offsite/replicated \
  --archive ./archives/replicated \
  --s3 s3://my-bucket/wavemind/prod \
  --keep-last 7 \
  --s3-keep-last 30 \
  --json

wavemind replicated-s3-archives \
  --s3 s3://my-bucket/wavemind/prod \
  --latest \
  --json

wavemind replicated-restore \
  --from ./archives/replicated/wavemind-replicated-20260705-120000.tar.gz \
  --to ./state/restored-replicas \
  --overwrite \
  --json

wavemind replicated-restore \
  --from s3://my-bucket/wavemind/prod \
  --latest \
  --to ./state/restored-replicas \
  --overwrite \
  --json

wavemind replicated-drill \
  --from s3://my-bucket/wavemind/prod \
  --to ./state/drill-restore \
  --query "short support replies" \
  --expect-text "Tenant A prefers short support replies." \
  --json
```

Install S3/R2/MinIO support with `pip install "wavemind[s3]"`. For
S3-compatible endpoints such as Cloudflare R2 or MinIO, pass
`--s3-endpoint-url` and optionally `--s3-region`.

## HTTP API

Run the local FastAPI server:

```sh
wavemind --db ./app_memory.sqlite3 serve --host 127.0.0.1 --port 8000
```

Store and query memory over HTTP:

```sh
curl -X POST http://127.0.0.1:8000/remember -H "Content-Type: application/json" -d "{\"text\":\"Andrey is a trader\",\"namespace\":\"demo\"}"
curl -X POST http://127.0.0.1:8000/query -H "Content-Type: application/json" -d "{\"query\":\"trader\",\"namespace\":\"demo\",\"top_k\":1}"
curl -X POST http://127.0.0.1:8000/query/batch -H "Content-Type: application/json" -d "{\"queries\":[{\"query\":\"trader\",\"namespace\":\"demo\",\"top_k\":1},{\"query\":\"Andrey\",\"namespace\":\"demo\",\"top_k\":1}]}"
```

Operational endpoints:

```sh
curl http://127.0.0.1:8000/stats?namespace=demo
curl http://127.0.0.1:8000/audit?namespace=demo
curl http://127.0.0.1:8000/metrics
curl http://127.0.0.1:8000/observability
curl http://127.0.0.1:8000/index/health
curl "http://127.0.0.1:8000/scale-plan?target_memories=50000"
curl -X POST http://127.0.0.1:8000/index/rebuild
curl -X POST http://127.0.0.1:8000/consolidate -H "Content-Type: application/json" -d '{"namespace":"demo","seed_text":"Rust compiler systems","min_energy":0.01}'
curl -X POST http://127.0.0.1:8000/backup -H "Content-Type: application/json" -d '{"path":"./backups","keep_last":7}'
```

`/audit` returns mutation events such as `remember`, `forget`, `backup`, and
`consolidate_concept`. Query audit is opt-in with `WAVEMIND_AUDIT_QUERIES=1` because
writing an audit row for every query changes latency. `/metrics` returns a
Prometheus-compatible text payload without adding a required dependency.
`/index/health` reports source-of-truth versus candidate-index consistency.
`/index/rebuild` rebuilds the candidate index from stored active memories and
logs an `index_rebuild` audit event.

Full observability guide and local Prometheus/OTEL examples:
[`docs/OBSERVABILITY.md`](OBSERVABILITY.md).

OpenTelemetry traces are optional and off by default:

```sh
pip install "wavemind[otel]"
export WAVEMIND_OTEL_ENABLED=1
export WAVEMIND_OTEL_SERVICE_NAME=wavemind-api
export WAVEMIND_OTEL_EXPORTER=otlp
export WAVEMIND_OTEL_ENDPOINT="http://localhost:4318/v1/traces"
wavemind --db ./app_memory.sqlite3 serve --host 127.0.0.1 --port 8000
```

Use `WAVEMIND_OTEL_EXPORTER=console` for local trace inspection. FastAPI
requests are instrumented, and core memory phases such as encode, index search,
graph propagation, reranking, load, and backup create spans when OpenTelemetry
is enabled.

Production API controls are opt-in:

```sh
export WAVEMIND_READ_KEYS="read-key"
export WAVEMIND_WRITE_KEYS="write-key"
export WAVEMIND_ADMIN_KEYS="admin-key"
export WAVEMIND_RATE_LIMIT_PER_MINUTE=120
export WAVEMIND_API_SERIALIZE_OPERATIONS=1
```

For multiple API workers, use a shared Redis rate-limit bucket:

```sh
export WAVEMIND_RATE_LIMIT_PER_MINUTE=120
export WAVEMIND_RATE_LIMIT_REDIS_URL=redis://localhost:6379/0
export WAVEMIND_RATE_LIMIT_REDIS_PREFIX=wavemind:rate
```

`WAVEMIND_API_SERIALIZE_OPERATIONS=1` is the default. It keeps one in-process
FastAPI worker from running concurrent operations through the same local
WaveMind/SQLite runtime. Set it to `0` only when the backing store and index
path are safe for concurrent in-process access.

Role behavior:

| role | Env var | Allows |
|---|---|---|
| read | `WAVEMIND_READ_KEYS` | `/query`, `/query/batch`, `/stats`, `/metrics`, `/index/health` |
| write | `WAVEMIND_WRITE_KEYS` | read actions plus `/remember` and `/import` |
| admin | `WAVEMIND_ADMIN_KEYS` or `WAVEMIND_API_KEYS` | all actions, including `/audit`, `/backup`, `/index/rebuild`, `/forget`, and `/forget/batch` |

Keys are accepted through `Authorization: Bearer <key>` or `X-API-Key: <key>`.
If no key env vars are set, authentication is disabled for local development.

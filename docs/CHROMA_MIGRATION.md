# Migrating From Chroma to WaveMind Dynamic Memory

This guide is for developers who already use Chroma as local memory or a local
RAG store and want to add memory behavior: namespaces, TTL, hotness, priority,
corrections, explicit forgetting, audit events, and backup-friendly local state.

Chroma and WaveMind solve different layers:

- **Chroma** is a vector database. It is a strong choice for static document
  retrieval, local RAG prototypes, and fast embedding search.
- **WaveMind** is a dynamic memory layer. It stores memories in SQLite or
  Postgres, retrieves vector candidates, then re-ranks them using memory state.

Use WaveMind when the question is not only "what is nearest?" but also "what is
still useful, current, scoped, and allowed to be remembered?"

Official Chroma docs used as API reference:

- [Getting Started](https://docs.trychroma.com/docs/overview/getting-started)
- [Add Data](https://docs.trychroma.com/docs/collections/add-data)
- [Query and Get](https://docs.trychroma.com/docs/querying-collections/query-and-get)
- [Metadata Filtering](https://docs.trychroma.com/docs/querying-collections/metadata-filtering)
- [Update Data](https://docs.trychroma.com/docs/collections/update-data)

## When To Keep Chroma

Keep Chroma as-is when your workload is mostly static vector retrieval:

| Keep Chroma for... | Reason |
|---|---|
| Large document collections | Chroma is built as a vector database. |
| Static RAG | Plain nearest-neighbor retrieval is enough. |
| Existing Chroma server or Chroma Cloud deployment | No need to move stable infrastructure. |
| Lowest local static-retrieval latency | Current WaveMind benchmarks show Chroma is faster on static retrieval. |
| Multimodal or embedding-function workflows already built around Chroma | Avoid changing a working data path unless you need memory behavior. |

WaveMind is not a faster Chroma replacement. The migration only makes sense
when memory state matters: user preferences, corrections, expiring facts,
repeated recall, scoped personal memory, or audit-friendly forgetting.

## What To Move To WaveMind

Move data that behaves like memory:

| Move to WaveMind | Why |
|---|---|
| User profile facts | They need namespace isolation and correction handling. |
| Preferences | Frequently used preferences should become easier to recall. |
| Agent conversation summaries | They need durable recall across restarts. |
| Temporary facts | TTL should remove them without manual cleanup logic. |
| Corrections | New facts should suppress stale facts. |
| Decisions, runbooks, support notes | They need tags, provenance metadata, and auditability. |

Do not blindly migrate every document chunk. A good hybrid setup is:

- keep static documents in Chroma;
- store user/app/agent memory in WaveMind;
- query both if a request needs both durable documents and evolving memory.

## Concept Mapping

| Chroma concept | WaveMind equivalent | Migration note |
|---|---|---|
| collection | namespace or database file | Use namespaces for users, tenants, agents, or projects. |
| document | memory text | Pass as `memory.remember(text=...)`. |
| metadata | metadata plus tags | Keep raw fields in `metadata`; promote common filters into `tags`. |
| id | WaveMind id plus `metadata["chroma_id"]` | WaveMind assigns integer ids; preserve old Chroma ids in metadata. |
| `where` filter | namespace, tags, metadata in app logic | Use namespace first; tags for common categories. |
| `n_results` | `top_k` | Same idea: number of returned results. |
| update/upsert | remember new fact, optionally forget old one | Corrections often work better as explicit new memories. |
| delete | `forget(id=...)`, `forget(text=...)`, or `forget(namespace=...)` | Use for privacy, compliance, and hard corrections. |
| collection persistence | SQLite or Postgres source of truth | SQLite is easiest for local apps; Postgres for multi-tenant services. |

## Before: Common Chroma Memory Pattern

```python
import chromadb

client = chromadb.PersistentClient(path="./chroma")
collection = client.get_or_create_collection("agent_memory")

collection.upsert(
    ids=["m1", "m2"],
    documents=[
        "Andrey is a trader.",
        "Andrey prefers short practical answers.",
    ],
    metadatas=[
        {"user_id": "42", "kind": "profile"},
        {"user_id": "42", "kind": "preference"},
    ],
)

results = collection.query(
    query_texts=["How should I answer Andrey?"],
    n_results=3,
    where={"user_id": "42"},
)

for document in results["documents"][0]:
    print(document)
```

This is a good vector-search pattern. The missing parts usually live in your
application code: TTL, priority, stale-fact suppression, recall reinforcement,
forgetting policy, and audit.

## After: WaveMind Memory Pattern

```python
from wavemind import WaveMind

memory = WaveMind(db_path="./state/wavemind.sqlite3")

memory.remember(
    "Andrey is a trader.",
    namespace="user:42",
    tags=["profile"],
    metadata={"source": "chroma", "chroma_id": "m1"},
    priority=1.5,
)

memory.remember(
    "Andrey prefers short practical answers.",
    namespace="user:42",
    tags=["preference"],
    metadata={"source": "chroma", "chroma_id": "m2"},
)

hits = memory.query("How should I answer Andrey?", namespace="user:42", top_k=3)

for hit in hits:
    print(hit.score, hit.text)
```

What changed:

- `namespace="user:42"` replaces repeated metadata filters for user isolation.
- `tags` make common memory categories easy to filter.
- `priority` lets known important facts start stronger.
- WaveMind updates recall state when memories are returned.
- The SQLite file is easy to inspect, copy, and back up.

## Bulk Migration Script

Use Chroma's `get()` pagination to export documents and metadata, then insert
the memory-shaped records into WaveMind.

```python
from __future__ import annotations

from collections.abc import Iterable
from typing import Any

import chromadb
from wavemind import WaveMind


def namespace_from_metadata(metadata: dict[str, Any], fallback: str) -> str:
    user_id = metadata.get("user_id") or metadata.get("tenant_id")
    if user_id:
        return f"user:{user_id}"
    project = metadata.get("project")
    if project:
        return f"project:{project}"
    return fallback


def tags_from_metadata(metadata: dict[str, Any]) -> list[str]:
    tags: list[str] = []
    for key in ("kind", "type", "category"):
        value = metadata.get(key)
        if isinstance(value, str) and value:
            tags.append(value)
    raw_tags = metadata.get("tags")
    if isinstance(raw_tags, str):
        tags.extend(tag.strip() for tag in raw_tags.split(",") if tag.strip())
    elif isinstance(raw_tags, Iterable):
        tags.extend(str(tag) for tag in raw_tags if tag)
    return sorted(set(tags))


def migrate_collection(
    *,
    chroma_path: str = "./chroma",
    collection_name: str = "agent_memory",
    wavemind_db_path: str = "./state/wavemind.sqlite3",
    fallback_namespace: str = "chroma:agent_memory",
    batch_size: int = 500,
) -> int:
    client = chromadb.PersistentClient(path=chroma_path)
    collection = client.get_collection(collection_name)
    memory = WaveMind(db_path=wavemind_db_path)

    migrated = 0
    offset = 0
    while True:
        batch = collection.get(
            limit=batch_size,
            offset=offset,
            include=["documents", "metadatas"],
        )
        ids = batch.get("ids") or []
        documents = batch.get("documents") or []
        metadatas = batch.get("metadatas") or [{} for _ in ids]
        if not ids:
            break

        for chroma_id, text, metadata in zip(ids, documents, metadatas):
            if not text:
                continue
            metadata = dict(metadata or {})
            namespace = namespace_from_metadata(metadata, fallback_namespace)
            tags = tags_from_metadata(metadata)
            ttl_seconds = metadata.pop("ttl_seconds", None)
            priority = float(metadata.pop("priority", 1.0))
            metadata["source"] = metadata.get("source", "chroma")
            metadata["chroma_collection"] = collection_name
            metadata["chroma_id"] = chroma_id

            memory.remember(
                text,
                namespace=namespace,
                tags=tags,
                ttl_seconds=ttl_seconds,
                metadata=metadata,
                priority=priority,
            )
            migrated += 1

        offset += len(ids)

    memory.save()
    return migrated


if __name__ == "__main__":
    count = migrate_collection()
    print(f"Migrated {count} Chroma records into WaveMind.")
```

Run it from your app environment:

```sh
python migrate_chroma_to_wavemind.py
wavemind --db ./state/wavemind.sqlite3 query "answer style" --namespace user:42
```

## Modeling Namespaces, Tags, TTL, And Priority

### Namespaces

Use namespaces for the strongest isolation boundary:

```python
namespace = f"user:{user_id}"
namespace = f"tenant:{tenant_id}:agent:{agent_id}"
namespace = f"project:{project_id}"
```

This is safer than relying only on metadata filters because every `query()`
must choose a namespace.

### Tags

Use tags for categories that you query often:

```python
memory.remember(
    "Andrey prefers short answers.",
    namespace="user:42",
    tags=["preference", "profile"],
)

memory.query("answer style", namespace="user:42", tags=["preference"])
```

Keep rich provenance in `metadata`; keep compact categories in `tags`.

### TTL

Use TTL for facts that should expire automatically:

```python
memory.remember(
    "The user is testing the trial plan this week.",
    namespace="user:42",
    tags=["temporary", "billing"],
    ttl_seconds=7 * 24 * 60 * 60,
)
```

Temporary Chroma metadata such as `{"expires_at": ...}` or `{"ttl_seconds": ...}`
should become WaveMind `ttl_seconds` where possible.

### Priority

Use priority for facts that should start stronger than normal conversation
snippets:

```python
memory.remember(
    "The user never wants investment advice without risk notes.",
    namespace="user:42",
    tags=["preference", "safety"],
    priority=3.0,
)
```

## Corrections

For a normal vector database, correction usually means updating or deleting a
record. For memory, it is often useful to keep the correction as an event and
then remove the old fact only when required.

Soft correction:

```python
memory.remember(
    "Correction: Andrey is not a day trader; he researches longer-term setups.",
    namespace="user:42",
    tags=["correction", "profile"],
    metadata={"replaces_chroma_id": "m1"},
    priority=3.0,
)
```

Hard correction or privacy deletion:

```python
memory.forget(text="Andrey is a trader.", namespace="user:42")
memory.remember(
    "Andrey researches longer-term setups.",
    namespace="user:42",
    tags=["profile"],
    priority=2.0,
)
```

Use hard deletion when the old fact is wrong, sensitive, or must be forgotten.

## HTTP-Only Migration

If your application is not Python, run WaveMind as a local service:

```sh
wavemind --db ./state/wavemind.sqlite3 serve --host 127.0.0.1 --port 8000
```

Then store migrated memories over HTTP:

```sh
curl -X POST http://127.0.0.1:8000/remember \
  -H "Content-Type: application/json" \
  -d "{\"text\":\"Andrey prefers short answers\",\"namespace\":\"user:42\",\"tags\":[\"preference\"],\"metadata\":{\"source\":\"chroma\",\"chroma_id\":\"m2\"}}"
```

Query:

```sh
curl -X POST http://127.0.0.1:8000/query \
  -H "Content-Type: application/json" \
  -d "{\"query\":\"answer style\",\"namespace\":\"user:42\",\"top_k\":3}"
```

## Validation Checklist

After migration, check the behavior that matters:

1. Query a known profile fact by namespace.
2. Query the same text under another namespace and verify it does not leak.
3. Insert a temporary memory with `ttl_seconds`, wait or run a short test, and
   verify it stops appearing.
4. Insert a correction with higher priority and verify it outranks the stale
   fact.
5. Run `wavemind --db ./state/wavemind.sqlite3 index-health --json`.
6. Run a backup:

```sh
wavemind --db ./state/wavemind.sqlite3 backup --out ./backups --keep-last 7
```

For benchmark-style validation:

```sh
pip install -e ".[bench]"
python benchmarks/dynamic_memory_benchmark.py --engines wavemind chroma --memories 200
```

## Common Pitfalls

| Pitfall | Fix |
|---|---|
| Migrating every static document chunk | Keep large static corpora in Chroma; migrate memory-shaped records. |
| Using one namespace for every user | Use `user:<id>` or `tenant:<id>:agent:<id>`. |
| Treating tags like arbitrary metadata | Tags should be short query categories; put rich data in `metadata`. |
| Forgetting to preserve Chroma ids | Store them in `metadata["chroma_id"]` for traceability. |
| Expecting Chroma latency from WaveMind dynamic ranking | Chroma is faster for static retrieval; WaveMind adds memory policy. |
| Switching encoders without reindexing | Use a new database or rebuild indexes when changing vector dimensions. |

## Recommended Migration Path

1. Start with one user, agent, or project namespace.
2. Migrate only profile, preference, decision, correction, and summary records.
3. Keep static documents in Chroma until you have a reason to move them.
4. Add TTL to temporary facts and priority to high-value facts.
5. Run the validation checklist.
6. Roll out namespace by namespace.

This keeps the migration reversible and avoids turning WaveMind into a generic
document database. The product gap is dynamic memory, not replacing a mature
vector store for every static RAG workload.

from __future__ import annotations

import argparse
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from wavemind import WaveMind


DEFAULT_COLLECTION = "agent_memory"


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
    chroma_path: str | Path,
    collection_name: str = DEFAULT_COLLECTION,
    wavemind_db_path: str | Path,
    fallback_namespace: str | None = None,
    batch_size: int = 500,
) -> int:
    try:
        import chromadb
    except ImportError as exc:
        raise RuntimeError('Install Chroma support with: pip install "wavemind[bench]"') from exc

    fallback_namespace = fallback_namespace or f"chroma:{collection_name}"
    client = chromadb.PersistentClient(path=str(chroma_path))
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
                ttl_seconds=float(ttl_seconds) if ttl_seconds is not None else None,
                metadata=metadata,
                priority=priority,
            )
            migrated += 1

        offset += len(ids)

    memory.save()
    return migrated


def build_demo_chroma_collection(
    chroma_path: str | Path,
    collection_name: str = DEFAULT_COLLECTION,
) -> None:
    try:
        import chromadb
    except ImportError as exc:
        raise RuntimeError('Install Chroma support with: pip install "wavemind[bench]"') from exc

    client = chromadb.PersistentClient(path=str(chroma_path))
    try:
        client.delete_collection(collection_name)
    except Exception:
        pass
    collection = client.get_or_create_collection(
        collection_name,
        metadata={"hnsw:space": "cosine"},
    )
    collection.upsert(
        ids=["m1", "m2", "m3", "m4"],
        documents=[
            "Andrey is a trader.",
            "Andrey prefers short practical answers.",
            "Andrey has a monthly tool budget of 2000 dollars.",
            "Maria prefers detailed research notes.",
        ],
        embeddings=[
            [1.0, 0.0, 0.0, 0.0],
            [0.0, 1.0, 0.0, 0.0],
            [0.0, 0.0, 1.0, 0.0],
            [0.0, 0.0, 0.0, 1.0],
        ],
        metadatas=[
            {"user_id": "42", "kind": "profile", "priority": 2.0},
            {"user_id": "42", "kind": "preference", "tags": "style,agent"},
            {"user_id": "42", "kind": "billing", "ttl_seconds": 86400},
            {"user_id": "7", "kind": "preference", "tags": "style,research"},
        ],
    )


def run_demo(chroma_path: Path, wavemind_db_path: Path) -> int:
    build_demo_chroma_collection(chroma_path)
    migrated = migrate_collection(
        chroma_path=chroma_path,
        collection_name=DEFAULT_COLLECTION,
        wavemind_db_path=wavemind_db_path,
    )
    memory = WaveMind(db_path=wavemind_db_path)
    hits = memory.query(
        "How should I answer Andrey?",
        namespace="user:42",
        tags=["preference"],
        top_k=2,
    )
    print(f"Migrated {migrated} Chroma records into WaveMind.")
    for index, hit in enumerate(hits, start=1):
        chroma_id = hit.metadata.get("chroma_id", "?")
        print(f"{index}. {hit.text} [{chroma_id}]")
    return migrated


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--chroma-path", type=Path, default=Path("./state/chroma-demo"))
    parser.add_argument("--wavemind-db", type=Path, default=Path("./state/wavemind-from-chroma.sqlite3"))
    args = parser.parse_args()
    args.chroma_path.parent.mkdir(parents=True, exist_ok=True)
    args.wavemind_db.parent.mkdir(parents=True, exist_ok=True)
    run_demo(args.chroma_path, args.wavemind_db)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

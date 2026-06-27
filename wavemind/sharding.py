from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from .core import QueryResult, WaveMind


class NamespaceShardRouter:
    def __init__(self, root_path: str | Path, shard_count: int = 16):
        if shard_count <= 0:
            raise ValueError("shard_count must be positive")
        self.root_path = Path(root_path)
        self.shard_count = int(shard_count)
        self.root_path.mkdir(parents=True, exist_ok=True)

    def shard_for(self, namespace: str) -> int:
        digest = hashlib.sha256(namespace.encode("utf-8")).digest()
        return int.from_bytes(digest[:8], "big") % self.shard_count

    def db_path(self, namespace: str) -> Path:
        return self.root_path / f"shard-{self.shard_for(namespace):04d}.sqlite3"

    def existing_shards(self) -> list[Path]:
        return sorted(self.root_path.glob("shard-*.sqlite3"))


class ShardedWaveMind:
    """Route namespaces across multiple local WaveMind SQLite databases."""

    def __init__(
        self,
        root_path: str | Path,
        shard_count: int = 16,
        **mind_kwargs: Any,
    ):
        if "db_path" in mind_kwargs:
            raise ValueError("ShardedWaveMind manages db_path per shard")
        self.router = NamespaceShardRouter(root_path=root_path, shard_count=shard_count)
        self.mind_kwargs = dict(mind_kwargs)
        self._minds: dict[Path, WaveMind] = {}

    def remember(
        self,
        text: str,
        namespace: str = "default",
        **kwargs: Any,
    ) -> int:
        return self._mind(namespace).remember(text, namespace=namespace, **kwargs)

    def query(
        self,
        text: str,
        namespace: str = "default",
        **kwargs: Any,
    ) -> list[QueryResult]:
        return self._mind(namespace).query(text, namespace=namespace, **kwargs)

    def forget(
        self,
        namespace: str = "default",
        **kwargs: Any,
    ) -> int:
        return self._mind(namespace).forget(namespace=namespace, **kwargs)

    def purge_expired(self) -> int:
        return sum(mind.purge_expired() for mind in self._all_minds())

    def stats(self, namespace: str | None = None) -> dict[str, Any]:
        if namespace is not None:
            payload = self._mind(namespace).stats(namespace=namespace)
            payload["shard"] = self.router.shard_for(namespace)
            payload["shards"] = self.router.shard_count
            return payload

        totals: dict[str, Any] = {
            "active_memories": 0,
            "expired_memories": 0,
            "total_memories": 0,
            "audit_events": 0,
            "shards": self.router.shard_count,
            "shard_files": 0,
        }
        for mind in self._all_minds():
            stats = mind.stats()
            totals["active_memories"] += int(stats["active_memories"])
            totals["expired_memories"] += int(stats["expired_memories"])
            totals["total_memories"] += int(stats["total_memories"])
            totals["audit_events"] += int(stats.get("audit_events", 0))
            totals["shard_files"] += 1
        return totals

    def save(self, backup_dir: str | Path) -> list[Path]:
        backup_dir = Path(backup_dir)
        backup_dir.mkdir(parents=True, exist_ok=True)
        paths = []
        for mind in self._all_minds():
            path = Path(mind.store.path)
            paths.append(mind.save(backup_dir / path.name))
        return [path for path in paths if path is not None]

    def close(self) -> None:
        for mind in self._minds.values():
            mind.close()
        self._minds.clear()

    def __enter__(self) -> "ShardedWaveMind":
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        self.close()

    def _mind(self, namespace: str) -> WaveMind:
        path = self.router.db_path(namespace)
        mind = self._minds.get(path)
        if mind is None:
            mind = WaveMind(db_path=path, **self.mind_kwargs)
            self._minds[path] = mind
        return mind

    def _all_minds(self) -> list[WaveMind]:
        for path in self.router.existing_shards():
            if path not in self._minds:
                self._minds[path] = WaveMind(db_path=path, **self.mind_kwargs)
        return list(self._minds.values())

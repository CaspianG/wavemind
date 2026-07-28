from __future__ import annotations

import json
import sqlite3
from collections.abc import Awaitable, Callable, Mapping, Sequence
from pathlib import Path
from threading import RLock
from typing import Any

from wavemind.experience_compiler import ExperienceCompiler
from wavemind.memory_firewall import FirewallContext


class WaveMindAgentsSession:
    """Durable implementation of the OpenAI Agents SDK Session protocol."""

    session_settings: Any | None = None

    def __init__(
        self,
        session_id: str,
        *,
        db_path: str | Path = "wavemind-agents.db",
    ):
        selected = str(session_id).strip()
        if not selected:
            raise ValueError("session_id must not be empty")
        self.session_id = selected
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = RLock()
        self._conn = sqlite3.connect(
            str(self.db_path),
            check_same_thread=False,
            timeout=30.0,
        )
        self._conn.row_factory = sqlite3.Row
        with self._conn:
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS openai_session_items (
                    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL,
                    payload_json TEXT NOT NULL
                )
                """
            )
            self._conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_openai_session_items
                ON openai_session_items(session_id, sequence)
                """
            )

    async def get_items(self, limit: int | None = None) -> list[dict[str, Any]]:
        if limit is not None and int(limit) < 1:
            raise ValueError("limit must be positive")
        query = (
            "SELECT payload_json FROM openai_session_items "
            "WHERE session_id = ? ORDER BY sequence"
        )
        values: list[Any] = [self.session_id]
        if limit is not None:
            query = (
                "SELECT payload_json FROM ("
                "SELECT sequence, payload_json FROM openai_session_items "
                "WHERE session_id = ? ORDER BY sequence DESC LIMIT ?"
                ") ORDER BY sequence"
            )
            values.append(int(limit))
        with self._lock:
            rows = self._conn.execute(query, values).fetchall()
        return [json.loads(str(row["payload_json"])) for row in rows]

    async def add_items(self, items: Sequence[Mapping[str, Any]]) -> None:
        payloads = [_serialize_item(item) for item in items]
        if not payloads:
            return
        with self._lock, self._conn:
            self._conn.executemany(
                """
                INSERT INTO openai_session_items (session_id, payload_json)
                VALUES (?, ?)
                """,
                [(self.session_id, payload) for payload in payloads],
            )

    async def pop_item(self) -> dict[str, Any] | None:
        with self._lock, self._conn:
            row = self._conn.execute(
                """
                SELECT sequence, payload_json FROM openai_session_items
                WHERE session_id = ? ORDER BY sequence DESC LIMIT 1
                """,
                (self.session_id,),
            ).fetchone()
            if row is None:
                return None
            self._conn.execute(
                "DELETE FROM openai_session_items WHERE sequence = ?",
                (int(row["sequence"]),),
            )
        return json.loads(str(row["payload_json"]))

    async def clear_session(self) -> None:
        with self._lock, self._conn:
            self._conn.execute(
                "DELETE FROM openai_session_items WHERE session_id = ?",
                (self.session_id,),
            )

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    def __enter__(self) -> "WaveMindAgentsSession":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()


def make_experience_input_callback(
    compiler: ExperienceCompiler,
    *,
    namespace: str,
    token_budget: int = 800,
    top_k: int = 8,
    actor: str = "openai_agents",
) -> Callable[
    [Sequence[Mapping[str, Any]], Sequence[Mapping[str, Any]]],
    Awaitable[list[dict[str, Any]]],
]:
    """Build the official session_input_callback without persisting packet text."""

    async def callback(
        history: Sequence[Mapping[str, Any]],
        new_input: Sequence[Mapping[str, Any]],
    ) -> list[dict[str, Any]]:
        query = _latest_text(new_input)
        combined = [dict(item) for item in history]
        if query:
            packet = compiler.compile_packet(
                query,
                namespace=namespace,
                context=FirewallContext(namespace=namespace, actor=actor),
                token_budget=token_budget,
                top_k=top_k,
            )
            if packet.items:
                combined.append(
                    {
                        "role": "system",
                        "content": packet.as_prompt(),
                        "metadata": {
                            "wavemind_schema": "wavemind.experience_packet.v1",
                            "citations": list(packet.citations),
                            "ephemeral": True,
                        },
                    }
                )
        combined.extend(dict(item) for item in new_input)
        return combined

    return callback


def _serialize_item(item: Mapping[str, Any]) -> str:
    try:
        return json.dumps(
            dict(item),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    except (TypeError, ValueError) as exc:
        raise ValueError("session item must be JSON serializable") from exc


def _latest_text(items: Sequence[Mapping[str, Any]]) -> str:
    for item in reversed(items):
        content = item.get("content")
        if isinstance(content, str) and content.strip():
            return content.strip()
        if isinstance(content, Sequence) and not isinstance(content, (str, bytes)):
            parts = [
                str(part.get("text"))
                for part in content
                if isinstance(part, Mapping) and part.get("text")
            ]
            if parts:
                return "\n".join(parts)
    return ""

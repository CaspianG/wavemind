from __future__ import annotations

import sqlite3
from pathlib import PurePosixPath
from threading import RLock
from typing import Any

from wavemind.experience_portability import validate_anthropic_memory_path
from wavemind.experience_runtime import AgentExperienceRuntime
from .experience_runtime import AgentExperienceHooks


ANTHROPIC_MEMORY_TOOL = {
    "type": "memory_20250818",
    "name": "memory",
}


class AnthropicMemoryHandler:
    """Client-side storage handler for Anthropic's official memory tool."""

    tool_definition = ANTHROPIC_MEMORY_TOOL

    def __init__(
        self,
        db_path: str = "wavemind-anthropic.db",
        *,
        namespace: str = "default",
    ):
        self.namespace = str(namespace).strip()
        if not self.namespace:
            raise ValueError("namespace must not be empty")
        self._lock = RLock()
        self._conn = sqlite3.connect(db_path, check_same_thread=False, timeout=30.0)
        self._conn.row_factory = sqlite3.Row
        with self._conn:
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS anthropic_memory_files (
                    namespace TEXT NOT NULL,
                    path TEXT NOT NULL,
                    content TEXT NOT NULL,
                    PRIMARY KEY (namespace, path)
                )
                """
            )

    def execute(self, command: str, path: str, **arguments: Any) -> dict[str, Any]:
        selected = str(command).strip()
        normalized = validate_anthropic_memory_path(path)
        handlers = {
            "view": self._view,
            "create": self._create,
            "str_replace": self._str_replace,
            "insert": self._insert,
            "delete": self._delete,
            "rename": self._rename,
        }
        if selected not in handlers:
            raise ValueError(f"unsupported Anthropic memory command: {selected}")
        return handlers[selected](normalized, **arguments)

    def _view(self, path: str, **arguments: Any) -> dict[str, Any]:
        with self._lock:
            if path == "/memories" or arguments.get("directory"):
                prefix = path.rstrip("/") + "/"
                rows = self._conn.execute(
                    """
                    SELECT path FROM anthropic_memory_files
                    WHERE namespace = ? AND path LIKE ? ORDER BY path
                    """,
                    (self.namespace, prefix + "%"),
                ).fetchall()
                return {"path": path, "files": [str(row["path"]) for row in rows]}
            row = self._conn.execute(
                """
                SELECT content FROM anthropic_memory_files
                WHERE namespace = ? AND path = ?
                """,
                (self.namespace, path),
            ).fetchone()
        if row is None:
            raise FileNotFoundError(path)
        content = str(row["content"])
        view_range = arguments.get("view_range")
        if view_range is not None:
            start, end = (int(value) for value in view_range)
            if start < 1 or end < start:
                raise ValueError("view_range must contain positive ordered lines")
            content = "\n".join(content.splitlines()[start - 1 : end])
        return {"path": path, "content": content}

    def _create(self, path: str, **arguments: Any) -> dict[str, Any]:
        if path == "/memories":
            raise ValueError("create requires a file path")
        content = str(arguments.get("file_text", arguments.get("content", "")))
        with self._lock, self._conn:
            existing = self._conn.execute(
                """
                SELECT 1 FROM anthropic_memory_files
                WHERE namespace = ? AND path = ?
                """,
                (self.namespace, path),
            ).fetchone()
            if existing is not None:
                raise FileExistsError(path)
            self._conn.execute(
                """
                INSERT INTO anthropic_memory_files (namespace, path, content)
                VALUES (?, ?, ?)
                """,
                (self.namespace, path, content),
            )
        return {"path": path, "created": True}

    def _str_replace(self, path: str, **arguments: Any) -> dict[str, Any]:
        old = str(arguments.get("old_str", ""))
        new = str(arguments.get("new_str", ""))
        if not old:
            raise ValueError("old_str must not be empty")
        content = self._content(path)
        count = content.count(old)
        if count != 1:
            raise ValueError("old_str must match exactly once")
        self._write(path, content.replace(old, new, 1))
        return {"path": path, "replaced": True}

    def _insert(self, path: str, **arguments: Any) -> dict[str, Any]:
        line = int(arguments.get("insert_line", 0))
        text = str(arguments.get("insert_text", ""))
        lines = self._content(path).splitlines()
        if line < 0 or line > len(lines):
            raise ValueError("insert_line is outside the file")
        lines[line:line] = text.splitlines()
        self._write(path, "\n".join(lines))
        return {"path": path, "inserted": True}

    def _delete(self, path: str, **_: Any) -> dict[str, Any]:
        if path == "/memories":
            raise ValueError("cannot delete the memory root")
        with self._lock, self._conn:
            cursor = self._conn.execute(
                """
                DELETE FROM anthropic_memory_files
                WHERE namespace = ? AND path = ?
                """,
                (self.namespace, path),
            )
        if cursor.rowcount != 1:
            raise FileNotFoundError(path)
        return {"path": path, "deleted": True}

    def _rename(self, path: str, **arguments: Any) -> dict[str, Any]:
        new_path = validate_anthropic_memory_path(str(arguments.get("new_path", "")))
        if new_path == "/memories":
            raise ValueError("rename requires a file destination")
        content = self._content(path)
        with self._lock, self._conn:
            conflict = self._conn.execute(
                """
                SELECT 1 FROM anthropic_memory_files
                WHERE namespace = ? AND path = ?
                """,
                (self.namespace, new_path),
            ).fetchone()
            if conflict is not None:
                raise FileExistsError(new_path)
            self._conn.execute(
                """
                INSERT INTO anthropic_memory_files (namespace, path, content)
                VALUES (?, ?, ?)
                """,
                (self.namespace, new_path, content),
            )
            self._conn.execute(
                """
                DELETE FROM anthropic_memory_files
                WHERE namespace = ? AND path = ?
                """,
                (self.namespace, path),
            )
        return {"path": path, "new_path": new_path, "renamed": True}

    def _content(self, path: str) -> str:
        return str(self._view(path)["content"])

    def _write(self, path: str, content: str) -> None:
        with self._lock, self._conn:
            cursor = self._conn.execute(
                """
                UPDATE anthropic_memory_files SET content = ?
                WHERE namespace = ? AND path = ?
                """,
                (content, self.namespace, path),
            )
        if cursor.rowcount != 1:
            raise FileNotFoundError(path)

    def export_files(self) -> dict[str, str]:
        with self._lock:
            rows = self._conn.execute(
                """
                SELECT path, content FROM anthropic_memory_files
                WHERE namespace = ? ORDER BY path
                """,
                (self.namespace,),
            ).fetchall()
        return {str(row["path"]): str(row["content"]) for row in rows}

    def close(self) -> None:
        with self._lock:
            self._conn.close()


def anthropic_memory_filename(path: str) -> str:
    return PurePosixPath(validate_anthropic_memory_path(path)).name


def make_anthropic_experience_hooks(
    runtime: AgentExperienceRuntime,
    *,
    namespace: str,
    token_budget: int = 400,
    top_k: int = 3,
) -> AgentExperienceHooks:
    """Create lifecycle hooks compatible with Anthropic Agent SDK callbacks."""

    return AgentExperienceHooks(
        runtime,
        namespace=namespace,
        provider="anthropic_agent_sdk",
        token_budget=token_budget,
        top_k=top_k,
    )

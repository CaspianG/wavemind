from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Iterable


def segment_text(text: str, max_chars: int = 1000, overlap: int = 120) -> list[str]:
    text = text.replace("\r\n", "\n").strip()
    if not text:
        return []
    paragraphs = [part.strip() for part in re.split(r"\n\s*\n", text) if part.strip()]
    chunks: list[str] = []
    for paragraph in paragraphs:
        if len(paragraph) <= max_chars:
            chunks.append(paragraph)
            continue
        start = 0
        while start < len(paragraph):
            end = min(len(paragraph), start + max_chars)
            chunk = paragraph[start:end].strip()
            if chunk:
                chunks.append(chunk)
            if end == len(paragraph):
                break
            start = max(0, end - overlap)
    return chunks


def import_txt(
    path: str | Path,
    mind,
    namespace: str = "default",
    tags: Iterable[str] | None = None,
    max_chars: int = 1000,
    overlap: int = 120,
) -> list[int]:
    path = Path(path)
    text = path.read_text(encoding="utf-8")
    ids = []
    for chunk in segment_text(text, max_chars=max_chars, overlap=overlap):
        ids.append(
            mind.remember(
                chunk,
                namespace=namespace,
                tags=tags or (),
                metadata={"source": str(path), "format": "txt"},
            )
        )
    return ids


def import_json(
    path: str | Path,
    mind,
    namespace: str = "default",
    tags: Iterable[str] | None = None,
) -> list[int]:
    path = Path(path)
    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, dict):
        items = data.get("items", [data])
    else:
        items = data

    ids = []
    for item in items:
        if isinstance(item, str):
            text = item
            item_tags = set(tags or ())
            metadata = {"source": str(path), "format": "json"}
        elif isinstance(item, dict):
            text = str(item.get("text", "")).strip()
            item_tags = set(tags or ()) | set(item.get("tags", []))
            metadata = {
                key: value
                for key, value in item.items()
                if key not in {"text", "tags"}
            }
            metadata.update({"source": str(path), "format": "json"})
        else:
            continue
        if not text:
            continue
        ids.append(mind.remember(text, namespace=namespace, tags=sorted(item_tags), metadata=metadata))
    return ids


def import_pdf(
    path: str | Path,
    mind,
    namespace: str = "default",
    tags: Iterable[str] | None = None,
    max_chars: int = 1000,
    overlap: int = 120,
) -> list[int]:
    try:
        from pypdf import PdfReader
    except ImportError as exc:
        raise ImportError("Install pypdf to import PDF files") from exc

    path = Path(path)
    reader = PdfReader(str(path))
    text = "\n\n".join((page.extract_text() or "") for page in reader.pages)
    ids = []
    for chunk in segment_text(text, max_chars=max_chars, overlap=overlap):
        ids.append(
            mind.remember(
                chunk,
                namespace=namespace,
                tags=tags or (),
                metadata={"source": str(path), "format": "pdf"},
            )
        )
    return ids


def import_path(
    path: str | Path,
    mind,
    namespace: str = "default",
    tags: Iterable[str] | None = None,
    max_chars: int = 1000,
    overlap: int = 120,
) -> list[int]:
    path = Path(path)
    suffix = path.suffix.lower()
    if suffix == ".txt":
        return import_txt(path, mind, namespace=namespace, tags=tags, max_chars=max_chars, overlap=overlap)
    if suffix == ".json":
        return import_json(path, mind, namespace=namespace, tags=tags)
    if suffix == ".pdf":
        return import_pdf(path, mind, namespace=namespace, tags=tags, max_chars=max_chars, overlap=overlap)
    raise ValueError(f"Unsupported import format: {suffix}")


"""Bounded, offline import parsers. Source bytes are never executable input."""

import io
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time

from .models import BrainError


MAX_FILE_BYTES = 10 * 1024 * 1024
MAX_EXTRACTED_BYTES = 2 * 1024 * 1024
PARSE_TIMEOUT_SECONDS = 30


def _error(code="invalid_document"):
    return BrainError(code, "Document could not be imported.")


def normalize_text(text: str) -> str:
    """Offsets address this text: BOM removed, CRLF/CR mapped to LF."""
    text = text.removeprefix("\ufeff").replace("\r\n", "\n").replace("\r", "\n")
    try:
        size = len(text.encode("utf-8"))
    except UnicodeError:
        raise _error() from None
    if size > MAX_EXTRACTED_BYTES:
        raise _error("extracted_limit")
    if not text.strip() or any(ord(c) < 32 and c not in "\n\t" for c in text):
        raise _error()
    return text


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise _error()
        result[key] = value
    return result


def _messages(content):
    value = json.loads(content.decode("utf-8-sig"), object_pairs_hook=_unique_object)
    if (
        not isinstance(value, dict)
        or set(value) != {"schema", "messages"}
        or value["schema"] != "wavemind.messages.v1"
        or not isinstance(value["messages"], list)
        or not value["messages"]
    ):
        raise _error()
    parts, size = [], 0
    for message in value["messages"]:
        if (
            not isinstance(message, dict)
            or not {"role", "content"} <= message.keys()
            or not message.keys() <= {"role", "content", "timestamp"}
            or message["role"] not in ("system", "user", "assistant", "tool")
            or not isinstance(message["content"], str)
        ):
            raise _error()
        if "timestamp" in message:
            stamp = message["timestamp"]
            if type(stamp) not in (int, float) or not math.isfinite(stamp):
                raise _error()
        part = message["role"] + ": " + normalize_text(message["content"])
        size += len(part.encode("utf-8")) + bool(parts)
        if size > MAX_EXTRACTED_BYTES:
            raise _error("extracted_limit")
        parts.append(part)
    return normalize_text("\n".join(parts))


def _pdf_text(content):
    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(content), strict=True)
    if reader.is_encrypted:
        raise _error("encrypted_pdf")
    parts, size = [], 0
    for page in reader.pages:
        text = page.extract_text()
        if not text or not text.strip():
            continue
        text = normalize_text(text)
        size += len(text.encode("utf-8")) + bool(parts)
        if size > MAX_EXTRACTED_BYTES:
            raise _error("extracted_limit")
        parts.append(text)
    return normalize_text("\n".join(parts))


def _pdf_worker():
    # Fixed executable module, stdin bytes and JSON stdout only; no pickle, URL,
    # path or code supplied by the document. Parent discards stderr diagnostics.
    try:
        content = sys.stdin.buffer.read(MAX_FILE_BYTES + 1)
        if len(content) > MAX_FILE_BYTES:
            raise _error()
        result = {"text": _pdf_text(content)}
    except BrainError as error:
        result = {"error": error.code}
    except Exception:
        result = {"error": "invalid_document"}
    sys.stdout.buffer.write(json.dumps(result, ensure_ascii=False).encode("utf-8"))


def _bounded_pdf(content, deadline):
    # TemporaryFile uses private, randomly allocated task-owned files. Both
    # handles are closed on every exit, including timeout and worker failures.
    with tempfile.TemporaryFile() as source, tempfile.TemporaryFile() as output:
        source.write(content)
        source.seek(0)
        process = subprocess.Popen(
            [sys.executable, "-m", "wavemind.brain.parsing"],
            stdin=source,
            stdout=output,
            stderr=subprocess.DEVNULL,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
        try:
            process.wait(timeout=max(0, deadline - time.monotonic()))
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()
            raise _error("parse_timeout") from None
        except BaseException:
            process.kill()
            process.wait()
            raise
        if process.returncode != 0:
            raise _error()
        # JSON quoting may expand every text byte to six bytes.
        output.seek(0)
        raw = output.read(MAX_EXTRACTED_BYTES * 6 + 1025)
        if len(raw) > MAX_EXTRACTED_BYTES * 6 + 1024:
            raise _error("extracted_limit")
        result = json.loads(raw)
        if "error" in result:
            raise _error(
                result["error"]
                if result["error"]
                in ("invalid_document", "encrypted_pdf", "extracted_limit")
                else "invalid_document"
            )
        return normalize_text(result["text"])


def parse_file(*, name: str, content: bytes) -> tuple[str, str]:
    """Return normalized text and kind, with a finite per-file parsing budget."""
    deadline = time.monotonic() + PARSE_TIMEOUT_SECONDS
    if not isinstance(content, bytes) or len(content) > MAX_FILE_BYTES:
        raise _error()
    extension = Path(name).suffix.lower()
    # Refuse archive signatures even when disguised under an accepted suffix.
    if (
        content.startswith(
            (
                b"PK\x03\x04",
                b"PK\x05\x06",
                b"\x1f\x8b",
                b"7z\xbc\xaf\x27\x1c",
                b"Rar!",
                b"BZh",
                b"\xfd7zXZ",
            )
        )
        or content[257:262] == b"ustar"
    ):
        raise _error("unsupported_format")
    try:
        if extension in (".txt", ".md", ".markdown"):
            text, kind = normalize_text(content.decode("utf-8-sig")), "text"
        elif extension == ".json":
            text, kind = _messages(content), "messages"
        elif extension == ".pdf":
            text, kind = _bounded_pdf(content, deadline), "pdf"
        else:
            raise _error("unsupported_format")
    except OSError:
        raise _error("parser_unavailable") from None
    except (ValueError, TypeError, KeyError, RecursionError, OverflowError):
        raise _error() from None
    if time.monotonic() > deadline:
        raise _error("parse_timeout")
    return text, kind


if __name__ == "__main__":
    _pdf_worker()

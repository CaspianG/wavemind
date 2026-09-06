from __future__ import annotations

import hashlib
from pathlib import Path

from wavemind.evidence import (
    build_source_manifest,
    recorded_file_matches,
    validate_source_manifest,
)


def test_recorded_file_matches_lf_and_crlf_checkouts(tmp_path: Path) -> None:
    source = tmp_path / "evidence.json"
    crlf = b'{\r\n  "status": "pass"\r\n}\r\n'
    source.write_bytes(crlf.replace(b"\r\n", b"\n"))

    assert recorded_file_matches(
        source,
        size=len(crlf),
        sha256=hashlib.sha256(crlf).hexdigest(),
    )


def test_recorded_file_rejects_content_changes(tmp_path: Path) -> None:
    source = tmp_path / "evidence.json"
    expected = b'{\r\n  "status": "pass"\r\n}\r\n'
    source.write_bytes(b'{\n  "status": "failed"\n}\n')

    assert not recorded_file_matches(
        source,
        size=len(expected),
        sha256=hashlib.sha256(expected).hexdigest(),
    )


def test_source_manifest_normalizes_git_text_line_endings(tmp_path: Path) -> None:
    source = tmp_path / "source.py"
    source.write_bytes(b"first\nsecond\n")
    lf_manifest = build_source_manifest(tmp_path, ["source.py"])

    source.write_bytes(b"first\r\nsecond\r\n")
    crlf_manifest = build_source_manifest(tmp_path, ["source.py"])

    assert crlf_manifest == lf_manifest
    assert (
        validate_source_manifest(tmp_path, lf_manifest, require_current_files=True)
        == []
    )


def test_source_manifest_still_rejects_content_changes(tmp_path: Path) -> None:
    source = tmp_path / "source.py"
    source.write_bytes(b"first\nsecond\n")
    manifest = build_source_manifest(tmp_path, ["source.py"])

    source.write_bytes(b"first\nchanged\n")

    assert validate_source_manifest(tmp_path, manifest, require_current_files=True) == [
        "source manifest file hash mismatch: source.py"
    ]

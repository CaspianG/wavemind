from __future__ import annotations

from pathlib import Path

from wavemind.evidence import build_source_manifest, validate_source_manifest


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

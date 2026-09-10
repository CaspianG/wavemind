from __future__ import annotations

import os
import sqlite3
import stat
import subprocess
import sys
from pathlib import Path

import pytest

from wavemind.brain.auth import BrainAuth
from wavemind.brain.models import BrainError


def _run_init(profile: Path, key_file: Path):
    return subprocess.run(
        [
            sys.executable,
            "-m",
            "wavemind",
            "brain",
            "init",
            "--state-dir",
            str(profile),
            "--owner-key-file",
            str(key_file),
        ],
        capture_output=True,
        text=True,
        timeout=30,
    )


def test_existing_key_file_is_preserved_as_incomplete_initialization(tmp_path):
    profile = tmp_path / "profile"
    key_file = tmp_path / "owner.key"
    key_file.write_text("unrelated sentinel", encoding="utf-8")

    result = _run_init(profile, key_file)

    assert result.returncode == 2
    assert "incomplete_initialization" in result.stderr
    assert key_file.read_text(encoding="utf-8") == "unrelated sentinel"
    assert not profile.exists()
    assert "unrelated sentinel" not in result.stdout + result.stderr


def test_linked_key_destination_is_rejected_before_profile_mutation(tmp_path):
    target = tmp_path / "target.key"
    target.write_text("sentinel", encoding="utf-8")
    link = tmp_path / "owner.key"
    junction = None
    try:
        link.symlink_to(target)
    except OSError as error:
        if os.name != "nt":
            raise AssertionError("test filesystem must support symbolic links") from error
        real_parent = tmp_path / "real-parent"
        real_parent.mkdir()
        junction = tmp_path / "linked-parent"
        created = subprocess.run(
            ["cmd", "/c", "mklink", "/J", str(junction), str(real_parent)],
            capture_output=True,
            text=True,
        )
        assert created.returncode == 0, created.stderr
        link = junction / "owner.key"
    try:
        result = _run_init(tmp_path / "profile", link)

        assert result.returncode == 2
        assert "invalid_path" in result.stderr
        assert target.read_text(encoding="utf-8") == "sentinel"
        assert not (tmp_path / "profile").exists()
    finally:
        if junction is not None:
            os.rmdir(junction)


@pytest.mark.parametrize(
    "destination",
    [r"\\server\share\owner.key", r"\\.\NUL", "https://example.com/key"],
)
def test_remote_device_and_url_key_destinations_are_rejected_before_mutation(
    tmp_path, destination
):
    profile = tmp_path / "profile"

    result = _run_init(profile, Path(destination))

    assert result.returncode == 2
    assert "invalid_path" in result.stderr
    assert not profile.exists()


def test_directory_is_not_misdiagnosed_as_incomplete_key_file(tmp_path):
    profile = tmp_path / "profile"
    destination = tmp_path / "directory"
    destination.mkdir()

    result = _run_init(profile, destination)

    assert result.returncode == 2
    assert "invalid_path" in result.stderr
    assert "incomplete_initialization" not in result.stderr
    assert not profile.exists()


def test_owner_is_not_committed_when_durable_handoff_fails(tmp_path):
    auth = BrainAuth(tmp_path)

    with pytest.raises(OSError, match="simulated persistence failure"):
        auth.bootstrap_owner(
            persist=lambda _token: (_ for _ in ()).throw(
                OSError("simulated persistence failure")
            )
        )

    with pytest.raises(BrainError) as error:
        _ = auth.owner_identity
    assert error.value.code == "bootstrap_required"
    with sqlite3.connect(tmp_path / "brain-auth.sqlite3") as conn:
        assert conn.execute("SELECT count(*) FROM credentials").fetchone()[0] == 0
    auth.close()


def test_owner_key_has_native_private_permissions(tmp_path):
    key_file = tmp_path / "owner.key"

    result = _run_init(tmp_path / "profile", key_file)

    assert result.returncode == 0
    if os.name != "nt":
        info = key_file.stat()
        assert stat.S_IMODE(info.st_mode) == 0o600
        assert info.st_uid == os.geteuid()
        return

    import ctypes
    from ctypes import wintypes

    class AclSizeInformation(ctypes.Structure):
        _fields_ = [
            ("AceCount", wintypes.DWORD),
            ("AclBytesInUse", wintypes.DWORD),
            ("AclBytesFree", wintypes.DWORD),
        ]

    advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    advapi32.EqualSid.argtypes = [wintypes.LPVOID, wintypes.LPVOID]
    advapi32.EqualSid.restype = wintypes.BOOL
    kernel32.LocalFree.argtypes = [wintypes.LPVOID]
    kernel32.LocalFree.restype = wintypes.LPVOID
    owner, dacl, descriptor = wintypes.LPVOID(), wintypes.LPVOID(), wintypes.LPVOID()
    status = advapi32.GetNamedSecurityInfoW(
        str(key_file),
        1,
        0x00000001 | 0x00000004,
        ctypes.byref(owner),
        None,
        ctypes.byref(dacl),
        None,
        ctypes.byref(descriptor),
    )
    assert status == 0
    try:
        control, revision = wintypes.WORD(), wintypes.DWORD()
        assert advapi32.GetSecurityDescriptorControl(
            descriptor, ctypes.byref(control), ctypes.byref(revision)
        )
        assert control.value & 0x1000
        size = AclSizeInformation()
        assert advapi32.GetAclInformation(
            dacl, ctypes.byref(size), ctypes.sizeof(size), 2
        )
        assert size.AceCount == 1
        ace = wintypes.LPVOID()
        assert advapi32.GetAce(dacl, 0, ctypes.byref(ace))
        header = ctypes.string_at(ace, 8)
        assert header[0] == 0
        assert header[1] == 0
        assert int.from_bytes(header[4:8], "little") == 0x001F01FF
        assert advapi32.EqualSid(owner, wintypes.LPVOID(ace.value + 8))
        assert key_file.read_text(encoding="utf-8").strip()
    finally:
        kernel32.LocalFree(descriptor)

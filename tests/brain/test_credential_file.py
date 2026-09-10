from __future__ import annotations

import os
import sqlite3
import stat
import subprocess
import sys
from pathlib import Path

import pytest

from wavemind.brain.auth import BrainAuth
from wavemind.brain.credential_file import owner_key_path, persist_owner_key
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
            raise AssertionError(
                "test filesystem must support symbolic links"
            ) from error
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


def test_native_locality_check_rejects_remote_destination_before_path_preflight(
    tmp_path, monkeypatch
):
    from wavemind.brain import credential_file

    if os.name == "nt":
        monkeypatch.setattr(credential_file, "_windows_drive_type", lambda _path: 4)

        def unexpected_preflight(_path):
            raise AssertionError("remote destination reached path preflight")

        monkeypatch.setattr(credential_file, "safe_path", unexpected_preflight)
        destination = tmp_path / "mapped-owner.key"
    else:
        destination = Path("//server/share/mapped-owner.key")

    with pytest.raises(BrainError) as error:
        owner_key_path(destination)

    assert error.value.code == "invalid_path"


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


def _assert_no_owner(auth: BrainAuth, profile: Path) -> None:
    with pytest.raises(BrainError) as error:
        _ = auth.owner_identity
    assert error.value.code == "bootstrap_required"
    with sqlite3.connect(profile / "brain-auth.sqlite3") as conn:
        assert conn.execute("SELECT count(*) FROM credentials").fetchone()[0] == 0


def test_native_sync_failures_preserve_ambiguous_file_and_roll_back_owner(
    tmp_path, monkeypatch
):
    from wavemind.brain import credential_file

    sync_names = (
        ("_flush_windows_file",)
        if os.name == "nt"
        else ("_sync_posix_file", "_sync_posix_directory")
    )
    for index, sync_name in enumerate(sync_names):
        profile = tmp_path / f"profile-{index}"
        key_file = tmp_path / f"owner-{index}.key"
        auth = BrainAuth(profile)

        def fail_sync(*_args, **_kwargs):
            raise OSError("simulated native sync failure")

        with monkeypatch.context() as scoped:
            scoped.setattr(credential_file, sync_name, fail_sync, raising=False)
            with pytest.raises(BrainError) as error:
                auth.bootstrap_owner(
                    persist=lambda token: persist_owner_key(key_file, token)
                )
        assert error.value.code == "private_file_failed"
        assert key_file.is_file()
        _assert_no_owner(auth, profile)
        auth.close()


def _intercept_windows_native_call(monkeypatch, library, name, action):
    import ctypes

    native_dll = ctypes.WinDLL
    native_library = native_dll(library, use_last_error=True)

    class NativeCall:
        def __init__(self, function):
            object.__setattr__(self, "function", function)

        def __setattr__(self, attribute, value):
            setattr(self.function, attribute, value)

        def __call__(self, *args):
            action(*args)
            return self.function(*args)

    intercepted = NativeCall(getattr(native_library, name))

    class LibraryProxy:
        def __getattr__(self, attribute):
            return (
                intercepted if attribute == name else getattr(native_library, attribute)
            )

    def load_dll(library, **kwargs):
        if library == target_library:
            return LibraryProxy()
        return native_dll(library, **kwargs)

    target_library = library
    monkeypatch.setattr(ctypes, "WinDLL", load_dll)


def _replace_windows_native_call(monkeypatch, library, name, replacement):
    import ctypes

    native_dll = ctypes.WinDLL
    native_library = native_dll(library, use_last_error=True)
    native_function = getattr(native_library, name)

    class NativeCall:
        def __setattr__(self, attribute, value):
            setattr(native_function, attribute, value)

        def __call__(self, *args):
            return replacement(native_function, *args)

    class LibraryProxy:
        def __getattr__(self, attribute):
            return (
                NativeCall()
                if attribute == name
                else getattr(native_library, attribute)
            )

    def load_dll(requested_library, **kwargs):
        if requested_library == library:
            return LibraryProxy()
        return native_dll(requested_library, **kwargs)

    monkeypatch.setattr(ctypes, "WinDLL", load_dll)


def _assert_native_private_protection(path: Path) -> None:
    if os.name != "nt":
        info = path.stat()
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
    dacl, descriptor = wintypes.LPVOID(), wintypes.LPVOID()
    status = advapi32.GetNamedSecurityInfoW(
        str(path),
        1,
        0x00000004,
        None,
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
    finally:
        kernel32.LocalFree(descriptor)


def test_native_write_failures_preserve_private_partial_file_and_roll_back_owner(
    tmp_path, monkeypatch
):
    from wavemind.brain import credential_file

    for mode in ("immediate", "partial"):
        profile = tmp_path / f"write-profile-{mode}"
        key_file = tmp_path / f"write-owner-{mode}.key"
        auth = BrainAuth(profile)
        issued = []

        with monkeypatch.context() as scoped:
            if os.name == "nt":
                calls = [0]

                def replace_write(native, handle, buffer, length, written, overlapped):
                    calls[0] += 1
                    if mode == "partial" and calls[0] == 1:
                        return native(handle, buffer, 5, written, overlapped)
                    written._obj.value = 0
                    return 0

                _replace_windows_native_call(
                    scoped, "kernel32", "WriteFile", replace_write
                )
            else:
                native_write = credential_file.os.write
                calls = [0]

                def replace_write(fd, content):
                    calls[0] += 1
                    if mode == "partial" and calls[0] == 1:
                        return native_write(fd, content[:5])
                    raise OSError("simulated native write failure")

                scoped.setattr(credential_file.os, "write", replace_write)

            def handoff(token):
                issued.append(token)
                persist_owner_key(key_file, token)

            with pytest.raises(BrainError) as error:
                auth.bootstrap_owner(persist=handoff)

        assert error.value.code == "private_file_failed"
        assert issued and issued[0] not in str(error.value)
        expected = (issued[0] + "\n").encode("utf-8")[:5] if mode == "partial" else b""
        assert key_file.read_bytes() == expected
        _assert_native_private_protection(key_file)
        _assert_no_owner(auth, profile)
        auth.close()


def test_parent_replacement_is_pinned_through_native_creation(tmp_path, monkeypatch):
    from wavemind.brain import credential_file

    parent = tmp_path / "selected-parent"
    parent.mkdir()
    moved = tmp_path / "moved-parent"
    key_file = parent / "owner.key"
    replacement = {"succeeded": False, "blocked": False}

    def replace_parent():
        try:
            parent.rename(moved)
            parent.mkdir()
            replacement["succeeded"] = True
        except OSError:
            replacement["blocked"] = True

    if os.name == "nt":

        def before_create(_handle, _access, attributes, *_args):
            native_name = attributes._obj.ObjectName.contents.Buffer
            if native_name == key_file.name:
                replace_parent()

        _intercept_windows_native_call(
            monkeypatch, "ntdll", "NtCreateFile", before_create
        )
        with pytest.raises(BrainError, match="private owner key file"):
            persist_owner_key(key_file, "synthetic-owner-token")
        assert replacement == {"succeeded": True, "blocked": False}
        assert not key_file.exists()
        assert (moved / "owner.key").read_bytes() == b""
    else:
        native_open = credential_file.os.open

        def before_open(path, flags, mode=0o600, *, dir_fd=None):
            if flags & os.O_CREAT:
                replace_parent()
            return native_open(path, flags, mode, dir_fd=dir_fd)

        monkeypatch.setattr(credential_file.os, "open", before_open)
        with pytest.raises(BrainError, match="private owner key file"):
            persist_owner_key(key_file, "synthetic-owner-token")
        assert replacement == {"succeeded": True, "blocked": False}
        assert not key_file.exists()
        assert (moved / "owner.key").read_text(encoding="utf-8").strip() == (
            "synthetic-owner-token"
        )


def test_file_replacement_is_blocked_or_detected_without_deleting_replacement(
    tmp_path, monkeypatch
):
    from wavemind.brain import credential_file

    key_file = tmp_path / "owner.key"
    replacement = {"succeeded": False, "blocked": False}
    sentinel = "unrelated replacement sentinel"

    def replace_file():
        try:
            key_file.unlink()
            key_file.write_text(sentinel, encoding="utf-8")
            replacement["succeeded"] = True
        except OSError:
            replacement["blocked"] = True

    if os.name == "nt":
        attempted = {"value": False}

        def before_flush(*_args):
            if not attempted["value"]:
                attempted["value"] = True
                replace_file()

        _intercept_windows_native_call(
            monkeypatch, "kernel32", "FlushFileBuffers", before_flush
        )
        persist_owner_key(key_file, "synthetic-owner-token")
        assert replacement == {"succeeded": False, "blocked": True}
        assert key_file.read_text(encoding="utf-8").strip() == "synthetic-owner-token"
    else:
        native_fsync = credential_file.os.fsync
        attempted = {"value": False}

        def after_file_sync(fd):
            native_fsync(fd)
            info = os.fstat(fd)
            if (
                not attempted["value"]
                and key_file.exists()
                and (key_file.stat().st_dev, key_file.stat().st_ino)
                == (info.st_dev, info.st_ino)
            ):
                attempted["value"] = True
                replace_file()

        monkeypatch.setattr(credential_file.os, "fsync", after_file_sync)
        with pytest.raises(BrainError, match="private owner key file"):
            persist_owner_key(key_file, "synthetic-owner-token")
        assert replacement == {"succeeded": True, "blocked": False}
        assert key_file.read_text(encoding="utf-8") == sentinel


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

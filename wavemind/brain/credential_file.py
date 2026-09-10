"""Create a new owner credential file with private access from its first byte."""

from __future__ import annotations

import os
import stat
from pathlib import Path

from .models import BrainError
from .portability_archive import safe_path


def owner_key_path(value: str | Path) -> Path:
    """Validate a deliberate, new local owner-key destination."""
    raw = str(value)
    if raw.startswith(("\\\\", "//")) or "://" in raw:
        raise BrainError("invalid_path", "Select a new ordinary local key file.")
    if os.name == "nt" and ":" in raw[2:]:
        raise BrainError("invalid_path", "Select a new ordinary local key file.")
    path = safe_path(value)
    parent = safe_path(path.parent)
    if not parent.is_dir():
        raise BrainError("invalid_path", "Select an existing local directory.")
    if path.exists() or path.is_symlink():
        if not path.is_file():
            raise BrainError("invalid_path", "Select a new ordinary local key file.")
        raise BrainError(
            "incomplete_initialization",
            "The selected key file already exists. Preserve it and inspect the profile before retrying.",
        )
    return path


def persist_owner_key(path: str | Path, token: str) -> None:
    """Durably persist *token* to a new private regular file."""
    destination = owner_key_path(path)
    encoded = (token + "\n").encode("utf-8")
    if os.name == "nt":
        _persist_windows(destination, encoded)
    elif os.name == "posix":
        _persist_posix(destination, encoded)
    else:  # pragma: no cover - Python only exposes nt/posix on supported CI.
        raise BrainError(
            "private_file_unsupported",
            "Private key-file creation is unsupported on this platform.",
        )


def _persist_posix(path: Path, content: bytes) -> None:
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    flags |= getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    fd = None
    created = False
    try:
        fd = os.open(path, flags, 0o600)
        created = True
        os.fchmod(fd, 0o600)
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid():
            raise OSError("private regular file ownership unavailable")
        view = memoryview(content)
        while view:
            written = os.write(fd, view)
            if written <= 0:
                raise OSError("owner key write failed")
            view = view[written:]
        os.fsync(fd)
    except FileExistsError:
        raise BrainError(
            "incomplete_initialization",
            "The selected key file already exists. Preserve it and inspect the profile before retrying.",
        ) from None
    except OSError:
        if created:
            _remove_created_file(path)
        raise BrainError(
            "private_file_failed",
            "Could not create and persist the private owner key file.",
        ) from None
    finally:
        if fd is not None:
            os.close(fd)


def _persist_windows(path: Path, content: bytes) -> None:
    import ctypes
    from ctypes import wintypes

    advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    token_handle = wintypes.HANDLE()
    security_descriptor = wintypes.LPVOID()
    sid_string = wintypes.LPWSTR()
    file_handle = None
    created = False

    class SecurityAttributes(ctypes.Structure):
        _fields_ = [
            ("nLength", wintypes.DWORD),
            ("lpSecurityDescriptor", wintypes.LPVOID),
            ("bInheritHandle", wintypes.BOOL),
        ]

    class FileAttributeTagInfo(ctypes.Structure):
        _fields_ = [
            ("FileAttributes", wintypes.DWORD),
            ("ReparseTag", wintypes.DWORD),
        ]

    class AclSizeInformation(ctypes.Structure):
        _fields_ = [
            ("AceCount", wintypes.DWORD),
            ("AclBytesInUse", wintypes.DWORD),
            ("AclBytesFree", wintypes.DWORD),
        ]

    kernel32.GetCurrentProcess.restype = wintypes.HANDLE
    advapi32.OpenProcessToken.argtypes = [
        wintypes.HANDLE,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.HANDLE),
    ]
    advapi32.OpenProcessToken.restype = wintypes.BOOL
    advapi32.GetTokenInformation.argtypes = [
        wintypes.HANDLE,
        ctypes.c_int,
        wintypes.LPVOID,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD),
    ]
    advapi32.GetTokenInformation.restype = wintypes.BOOL
    advapi32.ConvertSidToStringSidW.argtypes = [
        wintypes.LPVOID,
        ctypes.POINTER(wintypes.LPWSTR),
    ]
    advapi32.ConvertSidToStringSidW.restype = wintypes.BOOL
    advapi32.ConvertStringSecurityDescriptorToSecurityDescriptorW.argtypes = [
        wintypes.LPCWSTR,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.LPVOID),
        ctypes.POINTER(wintypes.DWORD),
    ]
    advapi32.ConvertStringSecurityDescriptorToSecurityDescriptorW.restype = (
        wintypes.BOOL
    )
    advapi32.GetSecurityInfo.argtypes = [
        wintypes.HANDLE,
        wintypes.DWORD,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.LPVOID),
        ctypes.POINTER(wintypes.LPVOID),
        ctypes.POINTER(wintypes.LPVOID),
        ctypes.POINTER(wintypes.LPVOID),
        ctypes.POINTER(wintypes.LPVOID),
    ]
    advapi32.GetSecurityInfo.restype = wintypes.DWORD
    advapi32.GetSecurityDescriptorControl.argtypes = [
        wintypes.LPVOID,
        ctypes.POINTER(wintypes.WORD),
        ctypes.POINTER(wintypes.DWORD),
    ]
    advapi32.GetSecurityDescriptorControl.restype = wintypes.BOOL
    advapi32.GetAclInformation.argtypes = [
        wintypes.LPVOID,
        wintypes.LPVOID,
        wintypes.DWORD,
        ctypes.c_int,
    ]
    advapi32.GetAclInformation.restype = wintypes.BOOL
    advapi32.GetAce.argtypes = [
        wintypes.LPVOID,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.LPVOID),
    ]
    advapi32.GetAce.restype = wintypes.BOOL
    advapi32.EqualSid.argtypes = [wintypes.LPVOID, wintypes.LPVOID]
    advapi32.EqualSid.restype = wintypes.BOOL
    kernel32.CreateFileW.argtypes = [
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        ctypes.POINTER(SecurityAttributes),
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.HANDLE,
    ]
    kernel32.CreateFileW.restype = wintypes.HANDLE
    kernel32.GetFileType.argtypes = [wintypes.HANDLE]
    kernel32.GetFileType.restype = wintypes.DWORD
    kernel32.GetFileInformationByHandleEx.argtypes = [
        wintypes.HANDLE,
        ctypes.c_int,
        wintypes.LPVOID,
        wintypes.DWORD,
    ]
    kernel32.GetFileInformationByHandleEx.restype = wintypes.BOOL
    kernel32.WriteFile.argtypes = [
        wintypes.HANDLE,
        wintypes.LPCVOID,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD),
        wintypes.LPVOID,
    ]
    kernel32.WriteFile.restype = wintypes.BOOL
    kernel32.FlushFileBuffers.argtypes = [wintypes.HANDLE]
    kernel32.FlushFileBuffers.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL
    kernel32.LocalFree.argtypes = [wintypes.LPVOID]
    kernel32.LocalFree.restype = wintypes.LPVOID

    try:
        if not advapi32.OpenProcessToken(
            kernel32.GetCurrentProcess(), 0x0008, ctypes.byref(token_handle)
        ):
            raise OSError("token query unavailable")
        needed = wintypes.DWORD()
        advapi32.GetTokenInformation(token_handle, 1, None, 0, ctypes.byref(needed))
        if not needed.value:
            raise OSError("token identity unavailable")
        token_info = ctypes.create_string_buffer(needed.value)
        if not advapi32.GetTokenInformation(
            token_handle, 1, token_info, needed, ctypes.byref(needed)
        ):
            raise OSError("token identity unavailable")
        sid = ctypes.cast(token_info, ctypes.POINTER(wintypes.LPVOID))[0]
        if not advapi32.ConvertSidToStringSidW(sid, ctypes.byref(sid_string)):
            raise OSError("token identity unavailable")
        sid_text = sid_string.value
        sddl = f"O:{sid_text}D:P(A;;FA;;;{sid_text})"
        if not advapi32.ConvertStringSecurityDescriptorToSecurityDescriptorW(
            sddl, 1, ctypes.byref(security_descriptor), None
        ):
            raise OSError("private security descriptor unavailable")
        attributes = SecurityAttributes(
            ctypes.sizeof(SecurityAttributes), security_descriptor, False
        )
        file_handle = kernel32.CreateFileW(
            str(path),
            0x40000000 | 0x00020000,
            0,
            ctypes.byref(attributes),
            1,
            0x00000080 | 0x00200000,
            None,
        )
        if file_handle == ctypes.c_void_p(-1).value:
            error = ctypes.get_last_error()
            if error in {80, 183}:
                raise FileExistsError
            raise OSError("private file creation failed")
        created = True
        if kernel32.GetFileType(file_handle) != 1:
            raise OSError("owner key destination is not a disk file")
        file_info = FileAttributeTagInfo()
        if (
            not kernel32.GetFileInformationByHandleEx(
                file_handle, 9, ctypes.byref(file_info), ctypes.sizeof(file_info)
            )
            or file_info.FileAttributes & 0x400
        ):
            raise OSError("owner key destination is not a regular file")
        actual_owner = wintypes.LPVOID()
        actual_dacl = wintypes.LPVOID()
        actual_descriptor = wintypes.LPVOID()
        if advapi32.GetSecurityInfo(
            file_handle,
            1,
            0x00000001 | 0x00000004,
            ctypes.byref(actual_owner),
            None,
            ctypes.byref(actual_dacl),
            None,
            ctypes.byref(actual_descriptor),
        ):
            raise OSError("private security verification unavailable")
        try:
            control, revision = wintypes.WORD(), wintypes.DWORD()
            acl_info = AclSizeInformation()
            ace = wintypes.LPVOID()
            if (
                not advapi32.GetSecurityDescriptorControl(
                    actual_descriptor,
                    ctypes.byref(control),
                    ctypes.byref(revision),
                )
                or not control.value & 0x1000
                or not advapi32.GetAclInformation(
                    actual_dacl,
                    ctypes.byref(acl_info),
                    ctypes.sizeof(acl_info),
                    2,
                )
                or acl_info.AceCount != 1
                or not advapi32.GetAce(actual_dacl, 0, ctypes.byref(ace))
            ):
                raise OSError("private security verification failed")
            header = ctypes.string_at(ace, 8)
            if (
                header[0] != 0
                or header[1] != 0
                or int.from_bytes(header[4:8], "little") != 0x001F01FF
                or not advapi32.EqualSid(actual_owner, sid)
                or not advapi32.EqualSid(sid, wintypes.LPVOID(ace.value + 8))
            ):
                raise OSError("private security verification failed")
        finally:
            kernel32.LocalFree(actual_descriptor)
        offset = 0
        while offset < len(content):
            written = wintypes.DWORD()
            block = content[offset:]
            buffer = ctypes.create_string_buffer(block)
            if (
                not kernel32.WriteFile(
                    file_handle, buffer, len(block), ctypes.byref(written), None
                )
                or not written.value
            ):
                raise OSError("owner key write failed")
            offset += written.value
        if not kernel32.FlushFileBuffers(file_handle):
            raise OSError("owner key flush failed")
    except FileExistsError:
        raise BrainError(
            "incomplete_initialization",
            "The selected key file already exists. Preserve it and inspect the profile before retrying.",
        ) from None
    except OSError:
        if created:
            _remove_created_file(path)
        raise BrainError(
            "private_file_failed",
            "Could not create and persist the private owner key file.",
        ) from None
    finally:
        if file_handle not in {None, ctypes.c_void_p(-1).value}:
            kernel32.CloseHandle(file_handle)
        if security_descriptor:
            kernel32.LocalFree(security_descriptor)
        if sid_string:
            kernel32.LocalFree(sid_string)
        if token_handle:
            kernel32.CloseHandle(token_handle)


def _remove_created_file(path: Path) -> None:
    try:
        path.unlink()
    except OSError:
        pass

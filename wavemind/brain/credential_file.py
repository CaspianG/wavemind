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
    if os.name == "nt" and _windows_drive_type(Path(value).absolute()) in {0, 1, 4}:
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
    nofollow = getattr(os, "O_NOFOLLOW", None)
    directory = getattr(os, "O_DIRECTORY", None)
    if nofollow is None or directory is None:
        raise BrainError(
            "private_file_unsupported",
            "Private key-file creation is unsupported on this platform.",
        )
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    flags |= getattr(os, "O_CLOEXEC", 0) | nofollow
    fd = None
    parent_handles = []
    try:
        directory_flags = (
            os.O_RDONLY | directory | nofollow | getattr(os, "O_CLOEXEC", 0)
        )
        parent_handles.append(os.open(path.anchor, directory_flags))
        for component in path.parent.relative_to(path.anchor).parts:
            parent_handles.append(
                os.open(component, directory_flags, dir_fd=parent_handles[-1])
            )
        parent_fd = parent_handles[-1]
        parent_info = os.fstat(parent_fd)
        current_parent = path.parent.stat(follow_symlinks=False)
        if not stat.S_ISDIR(parent_info.st_mode) or (
            parent_info.st_dev,
            parent_info.st_ino,
        ) != (current_parent.st_dev, current_parent.st_ino):
            raise OSError("owner key parent changed")
        fd = os.open(path.name, flags, 0o600, dir_fd=parent_fd)
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
        _sync_posix_file(fd)
        _verify_posix_identity(path, parent_fd, fd)
        _sync_posix_directory(parent_fd)
        _verify_posix_identity(path, parent_fd, fd)
    except FileExistsError:
        raise BrainError(
            "incomplete_initialization",
            "The selected key file already exists. Preserve it and inspect the profile before retrying.",
        ) from None
    except OSError:
        raise BrainError(
            "private_file_failed",
            "Could not create and persist the private owner key file.",
        ) from None
    finally:
        if fd is not None:
            os.close(fd)
        for parent_handle in reversed(parent_handles):
            os.close(parent_handle)


def _sync_posix_file(fd: int) -> None:
    os.fsync(fd)


def _sync_posix_directory(fd: int) -> None:
    os.fsync(fd)


def _verify_posix_identity(path: Path, parent_fd: int, file_fd: int) -> None:
    parent = os.fstat(parent_fd)
    current_parent = path.parent.stat(follow_symlinks=False)
    opened = os.fstat(file_fd)
    current_file = os.stat(path.name, dir_fd=parent_fd, follow_symlinks=False)
    if (parent.st_dev, parent.st_ino) != (
        current_parent.st_dev,
        current_parent.st_ino,
    ) or (opened.st_dev, opened.st_ino) != (current_file.st_dev, current_file.st_ino):
        raise OSError("owner key path changed")


def _persist_windows(path: Path, content: bytes) -> None:
    import ctypes
    from ctypes import wintypes

    advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    ntdll = ctypes.WinDLL("ntdll", use_last_error=True)
    token_handle = wintypes.HANDLE()
    security_descriptor = wintypes.LPVOID()
    sid_string = wintypes.LPWSTR()
    file_handle = None

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

    class UnicodeString(ctypes.Structure):
        _fields_ = [
            ("Length", wintypes.USHORT),
            ("MaximumLength", wintypes.USHORT),
            ("Buffer", wintypes.LPWSTR),
        ]

    class ObjectAttributes(ctypes.Structure):
        _fields_ = [
            ("Length", wintypes.ULONG),
            ("RootDirectory", wintypes.HANDLE),
            ("ObjectName", ctypes.POINTER(UnicodeString)),
            ("Attributes", wintypes.ULONG),
            ("SecurityDescriptor", wintypes.LPVOID),
            ("SecurityQualityOfService", wintypes.LPVOID),
        ]

    class IoStatusBlock(ctypes.Structure):
        _fields_ = [("Status", wintypes.LONG), ("Information", ctypes.c_size_t)]

    kernel32.GetCurrentProcess.restype = wintypes.HANDLE
    kernel32.GetDriveTypeW.argtypes = [wintypes.LPCWSTR]
    kernel32.GetDriveTypeW.restype = wintypes.UINT
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
    kernel32.GetFinalPathNameByHandleW.argtypes = [
        wintypes.HANDLE,
        wintypes.LPWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
    ]
    kernel32.GetFinalPathNameByHandleW.restype = wintypes.DWORD
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
    ntdll.NtCreateFile.argtypes = [
        ctypes.POINTER(wintypes.HANDLE),
        wintypes.DWORD,
        ctypes.POINTER(ObjectAttributes),
        ctypes.POINTER(IoStatusBlock),
        wintypes.LPVOID,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.LPVOID,
        wintypes.DWORD,
    ]
    ntdll.NtCreateFile.restype = wintypes.LONG

    def nt_open_relative(parent, name, *, directory, create, descriptor=None):
        buffer = ctypes.create_unicode_buffer(name)
        name_bytes = len(name.encode("utf-16-le"))
        object_name = UnicodeString(
            name_bytes, name_bytes + 2, ctypes.cast(buffer, wintypes.LPWSTR)
        )
        attributes = ObjectAttributes(
            ctypes.sizeof(ObjectAttributes),
            parent,
            ctypes.pointer(object_name),
            0x40,
            descriptor,
            None,
        )
        io_status = IoStatusBlock()
        handle = wintypes.HANDLE()
        status = ntdll.NtCreateFile(
            ctypes.byref(handle),
            (0x00000020 | 0x00000080 | 0x00100000)
            if directory
            else (0x00000002 | 0x00000080 | 0x00020000 | 0x00100000),
            ctypes.byref(attributes),
            ctypes.byref(io_status),
            None,
            0 if directory else 0x00000080,
            0x00000001 | 0x00000002 | 0x00000004 if directory else 0,
            2 if create else 1,
            (0x00000001 if directory else 0x00000040) | 0x00000020 | 0x00200000,
            None,
            0,
        )
        if status != 0:
            if status & 0xFFFFFFFF == 0xC0000035:
                raise FileExistsError
            raise OSError("native relative open failed")
        return handle

    def verify_parent_path(handle):
        needed = kernel32.GetFinalPathNameByHandleW(handle, None, 0, 0)
        if not needed:
            raise OSError("owner key parent identity unavailable")
        buffer = ctypes.create_unicode_buffer(needed + 1)
        if not kernel32.GetFinalPathNameByHandleW(handle, buffer, len(buffer), 0):
            raise OSError("owner key parent identity unavailable")
        observed = buffer.value
        if observed.startswith("\\\\?\\"):
            observed = observed[4:]
        if os.path.normcase(os.path.normpath(observed)) != os.path.normcase(
            os.path.normpath(str(path.parent))
        ):
            raise OSError("owner key parent changed")

    parent_handles = []
    try:
        drive_type = _windows_drive_type(path)
        if drive_type in {0, 1, 4}:
            raise OSError("owner key destination is not a local drive")
        root_handle = kernel32.CreateFileW(
            path.anchor,
            0,
            0x00000001 | 0x00000002 | 0x00000004,
            None,
            3,
            0x02000000 | 0x00200000,
            None,
        )
        if root_handle == ctypes.c_void_p(-1).value:
            raise OSError("owner key parent pinning failed")
        parent_handles.append(root_handle)
        for component in path.parent.relative_to(Path(path.anchor)).parts:
            parent_handles.append(
                nt_open_relative(
                    parent_handles[-1], component, directory=True, create=False
                )
            )
        for directory_handle in parent_handles:
            directory_info = FileAttributeTagInfo()
            if (
                not kernel32.GetFileInformationByHandleEx(
                    directory_handle,
                    9,
                    ctypes.byref(directory_info),
                    ctypes.sizeof(directory_info),
                )
                or not directory_info.FileAttributes & 0x10
                or directory_info.FileAttributes & 0x400
            ):
                raise OSError("owner key parent is not an ordinary directory")
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
        verify_parent_path(parent_handles[-1])
        file_handle = nt_open_relative(
            parent_handles[-1],
            path.name,
            directory=False,
            create=True,
            descriptor=security_descriptor,
        )
        verify_parent_path(parent_handles[-1])
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
        _flush_windows_file(kernel32, file_handle)
        verify_parent_path(parent_handles[-1])
    except FileExistsError:
        raise BrainError(
            "incomplete_initialization",
            "The selected key file already exists. Preserve it and inspect the profile before retrying.",
        ) from None
    except OSError:
        raise BrainError(
            "private_file_failed",
            "Could not create and persist the private owner key file.",
        ) from None
    finally:
        if file_handle is not None and file_handle != ctypes.c_void_p(-1).value:
            kernel32.CloseHandle(file_handle)
        if security_descriptor:
            kernel32.LocalFree(security_descriptor)
        if sid_string:
            kernel32.LocalFree(sid_string)
        if token_handle:
            kernel32.CloseHandle(token_handle)
        for parent_handle in reversed(parent_handles):
            kernel32.CloseHandle(parent_handle)


def _flush_windows_file(kernel32, file_handle) -> None:
    if not kernel32.FlushFileBuffers(file_handle):
        raise OSError("owner key flush failed")


def _windows_drive_type(path: Path) -> int:
    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.GetDriveTypeW.argtypes = [wintypes.LPCWSTR]
    kernel32.GetDriveTypeW.restype = wintypes.UINT
    return int(kernel32.GetDriveTypeW(path.anchor))

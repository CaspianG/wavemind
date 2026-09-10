"""Local Python developer launch; deliberately separate from legacy settings."""

import argparse
import getpass
import json
import os
import stat
import sqlite3
import sys
from pathlib import Path

from .auth import BrainAuth
from .credential_file import owner_key_path, persist_owner_key
from .models import BrainError
from .portability_archive import safe_path
from .service import BrainService

NOTICE = "D1 developer pilot requires Python; this is not the D2 consumer installer. Plaintext local storage for nonsecret materials. D3 deployment and D4 usefulness validation remain separate."


def local_path(value):
    raw = str(value)
    # D1 selected paths cannot reach UNC/network shares, devices, or URLs.
    if (
        raw.startswith(("\\\\", "//"))
        or "://" in raw
        or (os.name == "nt" and ":" in raw[2:])
    ):
        raise BrainError("invalid_path", "Select an ordinary local path.")
    path = safe_path(value)
    if path.exists() and not (stat.S_ISREG(path.stat().st_mode) or path.is_dir()):
        raise BrainError("invalid_path", "Select an ordinary local path.")
    return path


def _parser():
    parser = argparse.ArgumentParser(prog="wavemind brain", description=NOTICE)
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("init", "serve", "mcp", "backup", "restore", "export", "doctor"):
        command = commands.add_parser(name)
        command.add_argument("--state-dir", type=Path, required=True)
        if name == "init":
            command.add_argument("--owner-key-file", type=Path, required=True)
        else:
            command.add_argument(
                "--token-file",
                type=Path,
                help="Selected local credential file; otherwise WAVEMIND_BRAIN_TOKEN or a terminal prompt.",
            )
        if name in ("backup", "export"):
            command.add_argument("--brain-id", required=True)
            command.add_argument("--destination", type=Path, required=True)
        if name == "restore":
            command.add_argument("--archive", type=Path, required=True)
            command.add_argument("--current-state-dir", type=Path)
        if name == "serve":
            command.add_argument("--host", default="127.0.0.1")
            command.add_argument("--port", type=int, default=8000)
    return parser


def _credential(args):
    if args.token_file is not None:
        path = local_path(args.token_file)
        if not path.is_file() or path.stat().st_size > 1024:
            raise BrainError("invalid_path", "Invalid local credential file.")
        value = path.read_text(encoding="utf-8").strip()
    else:
        value = os.environ.get("WAVEMIND_BRAIN_TOKEN", "")
        if not value and sys.stdin.isatty():
            value = getpass.getpass("Local Brain credential: ")
    if not value:
        raise BrainError(
            "unauthenticated",
            "Set a local credential via environment, file or terminal prompt.",
        )
    return value


def main(argv=None):
    args = _parser().parse_args(argv)
    service, auth = None, None
    try:
        if args.command == "serve" and (
            args.host not in ("127.0.0.1", "localhost", "::1")
            or not 1 <= args.port <= 65535
        ):
            raise BrainError(
                "deployment_gate",
                "D1 serve is loopback-only. Nonlocal hosting requires the separate D3/TLS deployment stage.",
            )
        state_dir = local_path(args.state_dir)
        selected_owner_key = (
            owner_key_path(args.owner_key_file) if args.command == "init" else None
        )
        auth = BrainAuth(state_dir)
        if args.command == "init":
            auth.bootstrap_owner(
                persist=lambda token: persist_owner_key(selected_owner_key, token)
            )
            service = BrainService(state_dir)
            service.bootstrap_owner = auth.owner_identity
            print(
                json.dumps(
                    {
                        "schema": "wavemind.brain_init.v2",
                        "owner_key_file": str(selected_owner_key),
                        "notice": NOTICE,
                    }
                )
            )
            return 0
        token = _credential(args)
        principal = auth.authenticate(token)
        service = BrainService(state_dir, bootstrap_owner=auth.owner_identity)
        if args.command == "serve":
            if principal.kind != "human" or principal.identity != auth.owner_identity:
                raise BrainError("not_found", "Local owner required.")
            from ..api import create_app
            import uvicorn

            host = "[::1]" if args.host == "::1" else args.host
            auth.allowed_hosts = (f"{host}:{args.port}",)
            app = create_app(brain_service=service, brain_auth=auth, brain_only=True)
            print(NOTICE, file=sys.stderr)
            uvicorn.run(
                app,
                host=args.host,
                port=args.port,
                access_log=False,
                log_level="warning",
                proxy_headers=False,
            )
            return 0
        if args.command == "mcp":
            from .mcp import build_brain_mcp_server

            build_brain_mcp_server(service, auth, token).run(transport="stdio")
            return 0
        if args.command == "backup":
            result = service.backup_brain(
                principal=principal,
                brain_id=args.brain_id,
                destination=local_path(args.destination),
            )
        elif args.command == "restore":
            result = service.restore_brain(
                principal=principal,
                archive=local_path(args.archive),
                current_state_dir=None
                if args.current_state_dir is None
                else local_path(args.current_state_dir),
            )
        elif args.command == "export":
            path = local_path(args.destination)
            result = service.export_brain(principal=principal, brain_id=args.brain_id)
            try:
                with path.open("x", encoding="utf-8") as target:
                    json.dump(result, target, ensure_ascii=False, allow_nan=False)
            except FileExistsError:
                raise BrainError(
                    "destination_exists", "Choose a new export destination."
                ) from None
            result = {
                "schema": "wavemind.brain_export_file.v1",
                "brain_id": args.brain_id,
                "destination": str(path),
            }
        else:
            result = {
                "schema": "wavemind.brain_doctor.v1",
                "brains": service.list_brains(principal=principal),
                "network_calls": 0,
                "model_connected": False,
                "notice": NOTICE,
            }
        print(json.dumps(result, ensure_ascii=False, allow_nan=False))
        return 0
    except BrainError as error:
        print(
            json.dumps({"error": {"code": error.code, "message": error.message}}),
            file=sys.stderr,
        )
        return 2
    except (OSError, ValueError, RuntimeError, sqlite3.Error):
        print(
            json.dumps(
                {
                    "error": {
                        "code": "local_operation_failed",
                        "message": "Local operation failed; check selected paths and installed optional dependencies.",
                    }
                }
            ),
            file=sys.stderr,
        )
        return 2
    finally:
        if service is not None:
            service.close()
        if auth is not None:
            auth.close()


if __name__ == "__main__":
    raise SystemExit(main())

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest


def main() -> int:
    """Return pytest's verdict without Windows interpreter-exit interference."""
    encoded_args = os.environ.get("WAVEMIND_PYTEST_ARGS_JSON")
    pytest_args = json.loads(encoded_args) if encoded_args else sys.argv[1:]
    if not isinstance(pytest_args, list) or not all(
        isinstance(value, str) for value in pytest_args
    ):
        raise SystemExit("WAVEMIND_PYTEST_ARGS_JSON must encode a string list")
    exit_code = int(pytest.main(pytest_args))
    verdict_path = os.environ.get("WAVEMIND_PYTEST_VERDICT_PATH")
    if verdict_path:
        Path(verdict_path).write_text(f"{exit_code}\n", encoding="utf-8")
    print(f"pytest-return-code={exit_code}", flush=True)
    sys.stdout.flush()
    sys.stderr.flush()
    if os.name == "nt":
        os._exit(exit_code)  # noqa: SLF001 - preserve pytest's completed verdict.
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())

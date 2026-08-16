from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest


def main() -> int:
    """Return pytest's verdict without Windows interpreter-exit interference."""
    exit_code = int(pytest.main(sys.argv[1:]))
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

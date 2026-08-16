from __future__ import annotations

import os
import sys

import pytest


def main() -> int:
    """Return pytest's verdict without Windows interpreter-exit interference."""
    exit_code = int(pytest.main(sys.argv[1:]))
    print(f"pytest-return-code={exit_code}", file=sys.stderr, flush=True)
    sys.stdout.flush()
    sys.stderr.flush()
    if os.name == "nt":
        os._exit(exit_code)  # noqa: SLF001 - preserve pytest's completed verdict.
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())

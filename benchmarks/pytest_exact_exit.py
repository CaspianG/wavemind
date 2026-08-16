from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest


class _ShardPlugin:
    def __init__(self, index: int, count: int) -> None:
        self.index = index
        self.count = count

    def pytest_collection_modifyitems(self, config, items) -> None:
        selected = [
            item
            for position, item in enumerate(items)
            if position % self.count == self.index
        ]
        deselected = [
            item
            for position, item in enumerate(items)
            if position % self.count != self.index
        ]
        items[:] = selected
        config.hook.pytest_deselected(items=deselected)


def main() -> int:
    """Return pytest's verdict without Windows interpreter-exit interference."""
    encoded_args = os.environ.get("WAVEMIND_PYTEST_ARGS_JSON")
    pytest_args = json.loads(encoded_args) if encoded_args else sys.argv[1:]
    if not isinstance(pytest_args, list) or not all(
        isinstance(value, str) for value in pytest_args
    ):
        raise SystemExit("WAVEMIND_PYTEST_ARGS_JSON must encode a string list")
    plugins = []
    shard_count = int(os.environ.get("WAVEMIND_PYTEST_SHARD_COUNT", "1"))
    shard_index = int(os.environ.get("WAVEMIND_PYTEST_SHARD_INDEX", "0"))
    if shard_count < 1 or not 0 <= shard_index < shard_count:
        raise SystemExit("invalid pytest shard index/count")
    if shard_count > 1:
        plugins.append(_ShardPlugin(shard_index, shard_count))
        print(f"pytest-shard={shard_index + 1}/{shard_count}", flush=True)
    exit_code = int(pytest.main(pytest_args, plugins=plugins))
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

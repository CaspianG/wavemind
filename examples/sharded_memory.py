from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from wavemind import HashingTextEncoder, ShardedWaveMind


def main() -> int:
    memory = ShardedWaveMind(
        root_path=Path(".wavemind-shards"),
        shard_count=8,
        encoder=HashingTextEncoder(vector_dim=128),
        width=32,
        height=32,
        layers=2,
        evolve_on_feed=1,
    )
    try:
        memory.remember("Tenant A uses short support answers", namespace="tenant:a")
        memory.remember("Tenant B tracks trading research", namespace="tenant:b")

        print("Tenant A:")
        for hit in memory.query("support answers", namespace="tenant:a", top_k=1):
            print(f"- {hit.text}")

        print("Tenant B:")
        for hit in memory.query("trading research", namespace="tenant:b", top_k=1):
            print(f"- {hit.text}")

        print("Shard stats:")
        print(memory.stats())
    finally:
        memory.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

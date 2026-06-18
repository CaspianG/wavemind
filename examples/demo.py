from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from wavemind import WaveMind
from wavemind.encoders import HashingTextEncoder


def configure_stdio() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def main() -> int:
    configure_stdio()
    memory = WaveMind(
        encoder=HashingTextEncoder(vector_dim=384),
        index_kind="numpy",
        width=32,
        height=32,
        layers=2,
        evolve_on_feed=1,
    )
    memories = [
        "Andrey is a trader who tracks market breakouts.",
        "Andrey prefers short practical answers about AI agents.",
    ]

    for text in memories:
        memory.remember(text, namespace="demo")
        print(f'✓ Remembered: "{text}"')

    query = "Andrey trader agent"
    print(f'\nQuery: "{query}"')
    for index, result in enumerate(memory.query(query, namespace="demo", top_k=2), start=1):
        print(f'→ Result {index} ({result.score:.2f}): "{result.text}"')

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

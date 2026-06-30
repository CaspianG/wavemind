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


def build_memory() -> WaveMind:
    return WaveMind(
        encoder=HashingTextEncoder(vector_dim=384),
        index_kind="numpy",
        width=32,
        height=32,
        layers=2,
        evolve_on_feed=1,
        field_weight=0.0,
        vector_weight=0.75,
        priority_weight=0.25,
        lexical_weight=0.20,
        short_query_lexical_weight=0.60,
        graph_weight=0.35,
        graph_steps=3,
        graph_expand_k=5,
    )


def print_result(prefix: str, result) -> None:
    print(f'{prefix} ({result.score:.2f}): "{result.text}"')


def main() -> int:
    configure_stdio()
    memory = build_memory()

    print("WaveMind dynamic memory demo")
    print()

    old_budget = "User budget is $500."
    new_budget = "User budget is $2000."
    temporary = "Temporary discount code is ALPHA-24."
    other_user = "User budget is $9000."

    memory.remember(
        old_budget,
        namespace="user:andrey",
        tags=["profile", "budget"],
        metadata={"conflict_group": "budget"},
        priority=1.0,
    )
    print(f'[store]   user:andrey -> "{old_budget}"')

    memory.remember(
        new_budget,
        namespace="user:andrey",
        tags=["profile", "budget"],
        metadata={"conflict_group": "budget"},
        priority=8.0,
    )
    print(f'[correct] user:andrey -> "{new_budget}"')

    memory.remember(
        temporary,
        namespace="user:andrey",
        tags=["temporary"],
        ttl_seconds=-1,
    )
    print(f'[expire]  user:andrey -> "{temporary}"')

    memory.remember(
        other_user,
        namespace="user:maria",
        tags=["profile", "budget"],
        priority=10.0,
    )
    print(f'[store]   user:maria  -> "{other_user}"')

    purged = memory.purge_expired()
    print(f"[purge]   expired memories removed: {purged}")

    query = "what is the user budget?"
    print()
    print(f'Query user:andrey: "{query}"')
    andrey_results = memory.query(query, namespace="user:andrey", top_k=2)
    for index, result in enumerate(andrey_results, start=1):
        print_result(f"-> Result {index}", result)
    if andrey_results and andrey_results[0].text == new_budget:
        print("[ok] corrected newer budget outranks the stale budget")

    print()
    print(f'Query user:maria: "{query}"')
    maria_result = memory.query(query, namespace="user:maria", top_k=1)[0]
    print_result("-> Result 1", maria_result)
    if maria_result.text == other_user:
        print("[ok] namespace isolation keeps Maria separate from Andrey")

    print()
    print('Query user:andrey temporary tag: "discount code"')
    temporary_results = memory.query(
        "discount code",
        namespace="user:andrey",
        tags=["temporary"],
        top_k=3,
    )
    if not temporary_results:
        print("[ok] expired temporary memory is not recalled")
    else:
        for index, result in enumerate(temporary_results, start=1):
            print_result(f"-> Result {index}", result)

    health = memory.index_health()
    print()
    print("Index health")
    print(
        "[ok] "
        f"{health['backend']} healthy={health['healthy']} "
        f"expected={health['expected_count']} vectors={health['vector_count']}"
    )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

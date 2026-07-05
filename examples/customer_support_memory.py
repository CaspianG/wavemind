from __future__ import annotations

import argparse
import sys
import tempfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from wavemind import WaveMind
from wavemind.encoders import HashingTextEncoder


ACME_NAMESPACE = "tenant:demo:customer:acme"
GLOBEX_NAMESPACE = "tenant:demo:customer:globex"


def configure_stdio() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def build_memory(db_path: str | Path | None = None) -> WaveMind:
    return WaveMind(
        db_path=db_path,
        encoder=HashingTextEncoder(vector_dim=256),
        index_kind="numpy",
        width=32,
        height=32,
        layers=2,
        evolve_on_feed=1,
        field_weight=0.0,
        vector_weight=0.70,
        priority_weight=0.30,
        lexical_weight=0.25,
        short_query_lexical_weight=0.70,
        rerank_k=8,
    )


def seed_customer_memory(memory: WaveMind) -> int:
    memory.remember(
        "ACME account plan is Starter.",
        namespace=ACME_NAMESPACE,
        tags=["account", "plan"],
        metadata={"source": "crm", "conflict_group": "account-plan"},
        priority=0.2,
    )
    memory.remember(
        "Correction: ACME account plan is Enterprise.",
        namespace=ACME_NAMESPACE,
        tags=["account", "plan", "correction"],
        metadata={"source": "crm", "conflict_group": "account-plan"},
        priority=9.0,
    )
    memory.remember(
        "ACME prefers concise support replies with clear next actions.",
        namespace=ACME_NAMESPACE,
        tags=["support", "preference"],
        metadata={"source": "ticket"},
        priority=4.0,
    )
    memory.remember(
        "ACME has an open billing ticket INV-2042 about duplicate invoice charges.",
        namespace=ACME_NAMESPACE,
        tags=["billing", "ticket"],
        metadata={"ticket": "INV-2042", "source": "helpdesk"},
        priority=5.0,
    )
    memory.remember(
        "Resolved: ACME SSO outage was caused by an expired SAML certificate.",
        namespace=ACME_NAMESPACE,
        tags=["support", "resolution"],
        metadata={"source": "postmortem"},
        priority=3.0,
    )
    memory.remember(
        "ACME temporary retention discount code is SAVE20.",
        namespace=ACME_NAMESPACE,
        tags=["temporary", "billing"],
        metadata={"source": "support"},
        ttl_seconds=-1,
        priority=4.0,
    )
    memory.remember(
        "Globex support team prefers detailed technical explanations and architecture notes.",
        namespace=GLOBEX_NAMESPACE,
        tags=["support", "preference"],
        metadata={"source": "ticket"},
        priority=4.0,
    )
    return memory.purge_expired()


def run_customer_support_checks(memory: WaveMind) -> dict[str, object]:
    purged = seed_customer_memory(memory)
    plan_hits = memory.query(
        "what plan is ACME account on?",
        namespace=ACME_NAMESPACE,
        tags=["plan"],
        top_k=2,
    )
    brief_hits = memory.query(
        "support brief billing ticket preference",
        namespace=ACME_NAMESPACE,
        top_k=4,
    )
    discount_hits = memory.query(
        "discount code",
        namespace=ACME_NAMESPACE,
        tags=["temporary"],
        top_k=3,
    )
    globex_hits = memory.query(
        "support preference",
        namespace=GLOBEX_NAMESPACE,
        top_k=1,
    )
    acme_cross_check = memory.query(
        "detailed technical explanations",
        namespace=ACME_NAMESPACE,
        top_k=3,
    )
    return {
        "purged": purged,
        "plan_hits": plan_hits,
        "brief_hits": brief_hits,
        "discount_hits": discount_hits,
        "globex_hits": globex_hits,
        "acme_cross_check": acme_cross_check,
        "stats": memory.stats(namespace=ACME_NAMESPACE),
    }


def print_results(results: dict[str, object]) -> None:
    print("WaveMind customer support memory demo")
    print()
    print(f"[purge] expired temporary memories removed: {results['purged']}")

    plan_hits = results["plan_hits"]
    print()
    print('Query ACME: "what plan is ACME account on?"')
    for index, hit in enumerate(plan_hits, start=1):
        print(f'-> Result {index} ({hit.score:.2f}): "{hit.text}"')
    if plan_hits and "Enterprise" in plan_hits[0].text:
        print("[ok] corrected account plan outranks stale CRM data")

    brief_hits = results["brief_hits"]
    print()
    print('Query ACME: "support brief billing ticket preference"')
    for index, hit in enumerate(brief_hits, start=1):
        tags = ",".join(hit.tags)
        print(f'-> Result {index} ({hit.score:.2f}) [{tags}]: "{hit.text}"')

    print()
    if not results["discount_hits"]:
        print("[ok] expired discount code is not recalled")

    globex_hits = results["globex_hits"]
    acme_cross_check = results["acme_cross_check"]
    print()
    print('Query Globex: "support preference"')
    for index, hit in enumerate(globex_hits, start=1):
        print(f'-> Result {index} ({hit.score:.2f}): "{hit.text}"')
    if globex_hits and all("Globex" not in hit.text for hit in acme_cross_check):
        print("[ok] customer namespaces prevent cross-account leakage")

    stats = results["stats"]
    print()
    print(
        "[ok] "
        f"ACME active={stats['active_memories']} "
        f"expired={stats['expired_memories']} "
        f"audit_events={stats['audit_events']} "
        f"index_healthy={stats['index_healthy']}"
    )


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run an offline customer support / CRM memory demo."
    )
    parser.add_argument(
        "--db",
        type=Path,
        help="Optional SQLite path. Defaults to a temporary database.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    configure_stdio()
    args = parse_args(argv)
    if args.db is not None:
        args.db.parent.mkdir(parents=True, exist_ok=True)
        with build_memory(args.db) as memory:
            results = run_customer_support_checks(memory)
            print_results(results)
        print()
        print(f"[store] SQLite database: {args.db}")
        return 0

    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "customer-support.sqlite3"
        with build_memory(db_path) as memory:
            results = run_customer_support_checks(memory)
            print_results(results)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

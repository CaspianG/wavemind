from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .benchmark import BenchmarkCase, run_benchmark, synthetic_cases
from .core import WaveMind
from .encoders import create_text_encoder
from .importers import import_path
from .storage import SQLiteMemoryStore


def configure_stdio() -> None:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8", errors="replace")
            except (OSError, ValueError):
                pass


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="wavemind",
        description="WaveMind persistent dynamic memory engine",
    )
    parser.add_argument("--db", default=None, help="SQLite database path")
    parser.add_argument(
        "--index",
        default="numpy",
        choices=["numpy", "quantized", "faiss", "annoy", "pgvector", "qdrant"],
    )
    parser.add_argument("--encoder", default="hash", choices=["hash", "sentence"])
    parser.add_argument(
        "--model",
        default="sentence-transformers/paraphrase-multilingual-mpnet-base-v2",
        help="sentence-transformers model name when --encoder sentence is used",
    )
    parser.add_argument("--score-threshold", type=float, default=0.0)
    parser.add_argument("--width", type=int, default=128)
    parser.add_argument("--height", type=int, default=128)
    parser.add_argument("--layers", type=int, default=6)
    parser.add_argument("--graph-weight", type=float, default=0.0)
    parser.add_argument("--graph-steps", type=int, default=2)
    parser.add_argument("--graph-expand-k", type=int, default=10)

    sub = parser.add_subparsers(dest="command")

    remember = sub.add_parser("remember", help="Store a memory")
    remember.add_argument("text")
    remember.add_argument("--namespace", default="default")
    remember.add_argument("--tag", action="append", default=[])
    remember.add_argument("--ttl-seconds", type=float)
    remember.add_argument("--priority", type=float, default=1.0)

    query = sub.add_parser("query", help="Query memories")
    query.add_argument("text")
    query.add_argument("--namespace", default="default")
    query.add_argument("--tag", action="append", default=[])
    query.add_argument("--top-k", type=int, default=3)
    query.add_argument("--min-score", type=float)
    query.add_argument("--json", action="store_true")

    forget = sub.add_parser("forget", help="Delete a memory")
    forget.add_argument("--id", type=int)
    forget.add_argument("--text")
    forget.add_argument("--namespace")

    stats = sub.add_parser("stats", help="Show memory stats")
    stats.add_argument("--namespace")

    audit = sub.add_parser("audit", help="Show audit log events")
    audit.add_argument("--namespace")
    audit.add_argument("--action")
    audit.add_argument("--limit", type=int, default=20)
    audit.add_argument("--json", action="store_true")

    imp = sub.add_parser("import", help="Import txt/pdf/json")
    imp.add_argument("path")
    imp.add_argument("--namespace", default="default")
    imp.add_argument("--tag", action="append", default=[])
    imp.add_argument("--max-chars", type=int, default=1000)
    imp.add_argument("--overlap", type=int, default=120)

    backup = sub.add_parser("backup", help="Backup SQLite database")
    backup.add_argument("--out", required=True)
    backup.add_argument("--keep-last", type=int)
    backup.add_argument("--prefix", default="wavemind")

    restore = sub.add_parser("restore", help="Restore a SQLite backup")
    restore.add_argument("--from", dest="source", required=True)
    restore.add_argument("--to", dest="destination")
    restore.add_argument("--overwrite", action="store_true")

    bench = sub.add_parser("benchmark", help="Run a synthetic recall benchmark")
    bench.add_argument("--namespace", default="bench")
    bench.add_argument("--top-k", type=int, default=1)

    serve = sub.add_parser("serve", help="Run FastAPI daemon")
    serve.add_argument("--host", default="0.0.0.0")
    serve.add_argument("--port", type=int, default=8000)

    sub.add_parser("test", help="Run pytest suite")
    return parser


def make_mind(args) -> WaveMind:
    encoder = create_text_encoder(kind=args.encoder, vector_dim=384, model_name=args.model)
    db_path = Path(args.db) if args.db else Path.cwd() / "wavemind.sqlite3"
    return WaveMind(
        db_path=db_path,
        width=args.width,
        height=args.height,
        layers=args.layers,
        encoder=encoder,
        index_kind=args.index,
        score_threshold=args.score_threshold,
        graph_weight=args.graph_weight,
        graph_steps=args.graph_steps,
        graph_expand_k=args.graph_expand_k,
    )


def print_stats(stats: dict) -> None:
    for key, value in stats.items():
        print(f"{key}: {value}")


def run_interactive(args) -> int:
    mind = make_mind(args)
    print("WaveMind v2 interactive CLI. Type help or exit.")
    while True:
        try:
            line = input("> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nexit")
            return 0
        if not line:
            continue
        if line in {"exit", "quit"}:
            print("exit")
            return 0
        if line == "help":
            print("remember <text> | query <text> | query5 <text> | stats | list | exit")
            continue
        command, _, rest = line.partition(" ")
        if command == "remember" and rest:
            id = mind.remember(rest)
            print(f"remembered id={id}")
        elif command == "query" and rest:
            for result in mind.query(rest, top_k=3):
                print(f"{result.score:.4f} id={result.id} {result.text}")
        elif command == "query5" and rest:
            for result in mind.query(rest, top_k=5):
                print(f"{result.score:.4f} id={result.id} {result.text}")
        elif command == "stats":
            print_stats(mind.stats())
        elif command == "list":
            for record in mind.store.list(include_expired=False):
                print(f"{record.id}: [{record.namespace}] {record.text}")
        else:
            print("unknown command")


def main(argv: list[str] | None = None) -> int:
    configure_stdio()
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command is None:
        if argv is not None:
            parser.print_help()
            return 0
        return run_interactive(args)

    if args.command == "test":
        import pytest

        return int(pytest.main(["-q"]))

    if args.command == "serve":
        import uvicorn

        from .api import create_app

        uvicorn.run(create_app(mind=make_mind(args)), host=args.host, port=args.port)
        return 0

    if args.command == "restore":
        destination = Path(args.destination) if args.destination else (
            Path(args.db) if args.db else Path.cwd() / "wavemind.sqlite3"
        )
        path = SQLiteMemoryStore.restore_backup(
            source=args.source,
            destination=destination,
            overwrite=args.overwrite,
        )
        print(f"restored: {path}")
        return 0

    mind = make_mind(args)
    if args.command == "remember":
        id = mind.remember(
            args.text,
            namespace=args.namespace,
            tags=args.tag,
            ttl_seconds=args.ttl_seconds,
            priority=args.priority,
        )
        print(f"remembered id={id}")
        return 0

    if args.command == "query":
        results = mind.query(
            args.text,
            namespace=args.namespace,
            tags=args.tag,
            top_k=args.top_k,
            min_score=args.min_score,
        )
        if args.json:
            print(json.dumps([result.__dict__ for result in results], ensure_ascii=False, indent=2))
        else:
            for result in results:
                print(
                    f"{result.score:.4f} "
                    f"vector={result.vector_score:.4f} "
                    f"field={result.field_score:.4f} "
                    f"graph={result.graph_score:.4f} "
                    f"id={result.id} {result.text}"
                )
        return 0

    if args.command == "forget":
        print(f"deleted={mind.forget(id=args.id, text=args.text, namespace=args.namespace)}")
        return 0

    if args.command == "stats":
        print_stats(mind.stats(namespace=args.namespace))
        return 0

    if args.command == "audit":
        events = mind.audit_events(
            namespace=args.namespace,
            action=args.action,
            limit=args.limit,
        )
        payload = [
            {
                "id": event.id,
                "created_at": event.created_at,
                "action": event.action,
                "namespace": event.namespace,
                "memory_id": event.memory_id,
                "metadata": event.metadata,
            }
            for event in events
        ]
        if args.json:
            print(json.dumps(payload, ensure_ascii=False, indent=2))
        else:
            for event in events:
                namespace = event.namespace or "-"
                memory_id = event.memory_id if event.memory_id is not None else "-"
                print(
                    f"{event.created_at:.3f} "
                    f"action={event.action} "
                    f"namespace={namespace} "
                    f"memory_id={memory_id}"
                )
        return 0

    if args.command == "import":
        ids = import_path(
            args.path,
            mind,
            namespace=args.namespace,
            tags=args.tag,
            max_chars=args.max_chars,
            overlap=args.overlap,
        )
        print(f"imported={len(ids)} ids={','.join(str(id) for id in ids)}")
        return 0

    if args.command == "backup":
        path = mind.save(
            args.out,
            keep_last=args.keep_last,
            backup_prefix=args.prefix,
        )
        print(f"backup: {path}")
        return 0

    if args.command == "benchmark":
        existing = {
            record.text
            for record in mind.store.list(namespace=args.namespace, include_expired=False)
        }
        for query, text in synthetic_cases(namespace=args.namespace):
            if text not in existing:
                mind.remember(text, namespace=args.namespace)
                existing.add(text)
        cases = [
            BenchmarkCase(query=query, expected_text=text, namespace=args.namespace)
            for query, text in synthetic_cases(namespace=args.namespace)
        ]
        report = run_benchmark(mind, cases, k=args.top_k)
        print(json.dumps(report.__dict__, ensure_ascii=False, indent=2))
        return 0

    parser.print_help()
    return 2


if __name__ == "__main__":
    raise SystemExit(main())

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from pathlib import Path

from . import __version__
from .benchmark import BenchmarkCase, run_benchmark, synthetic_cases
from .cluster import ClusterNode, build_cluster_plan
from .core import WaveMind
from .encoders import create_text_encoder
from .scale import build_scale_plan, scale_status_meets_or_exceeds
from .importers import import_path
from .jobs import (
    CachePrewarmWorker,
    DistributedRepairWorker,
    HotMemoryCache,
    MemoryMaintenanceWorker,
    ReplicatedObjectStoreDrillWorker,
    ReplicatedSnapshotWorker,
    RedisHotMemoryCache,
)
from .object_store import S3SnapshotStore
from .replication import ReplicatedWaveMind
from .sharding import DistributedShardedWaveMind, HTTPNamespaceShardClient
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
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            'Try: wavemind quickstart\n'
            'Then: wavemind remember "Andrey is a trader" --namespace demo\n'
            'And:  wavemind query "What does Andrey do?" --namespace demo'
        ),
    )
    parser.add_argument("--db", default=None, help="SQLite database path")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    parser.add_argument("--store", default=None, choices=["sqlite", "postgres"])
    parser.add_argument("--postgres-dsn", default=None)
    parser.add_argument(
        "--index",
        default="numpy",
        choices=[
            "numpy",
            "quantized",
            "faiss",
            "faiss-persisted",
            "annoy",
            "pgvector",
            "qdrant",
        ],
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
    parser.add_argument(
        "--audit-queries",
        action="store_true",
        default=os.environ.get("WAVEMIND_AUDIT_QUERIES", "0").lower()
        in {"1", "true", "yes", "on"},
        help="Store query text in the audit log for cache prewarm and diagnostics.",
    )

    sub = parser.add_subparsers(dest="command")

    sub.add_parser("quickstart", help="Show the shortest CLI path")

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

    index_health = sub.add_parser("index-health", help="Check vector index consistency")
    index_health.add_argument("--json", action="store_true")

    rebuild_index = sub.add_parser("rebuild-index", help="Rebuild vector index from stored memories")
    rebuild_index.add_argument("--json", action="store_true")

    consolidate = sub.add_parser("consolidate", help="Create concept memories from active field clusters")
    consolidate.add_argument("--namespace")
    consolidate.add_argument("--seed")
    consolidate.add_argument("--min-energy", type=float, default=0.05)
    consolidate.add_argument("--min-size", type=int, default=2)
    consolidate.add_argument("--max-concepts", type=int, default=3)
    consolidate.add_argument("--priority", type=float, default=6.0)
    consolidate.add_argument("--json", action="store_true")

    scale_plan = sub.add_parser("scale-plan", help="Show scale readiness and index recommendations")
    scale_plan.add_argument("--namespace")
    scale_plan.add_argument("--current-memories", type=int)
    scale_plan.add_argument("--target-memories", type=int)
    scale_plan.add_argument("--latency-target-ms", type=float, default=20.0)
    scale_plan.add_argument(
        "--fail-on",
        choices=["watch", "action_required", "architecture_required"],
        help="Exit non-zero when scale status reaches this threshold",
    )
    scale_plan.add_argument("--json", action="store_true")

    cluster_plan = sub.add_parser("cluster-plan", help="Plan namespace placement across cluster nodes")
    cluster_plan.add_argument("--namespace", action="append", default=[])
    cluster_plan.add_argument("--namespace-prefix", default="tenant")
    cluster_plan.add_argument("--namespace-count", type=int, default=0)
    cluster_plan.add_argument("--node", action="append", required=True, help="node_id=host:port or node_id")
    cluster_plan.add_argument("--replication-factor", type=int, default=2)
    cluster_plan.add_argument("--kubernetes", action="store_true")
    cluster_plan.add_argument("--image", default="wavemind:latest")
    cluster_plan.add_argument("--storage-size", default="20Gi")
    cluster_plan.add_argument("--repair-cronjob", action="store_true")
    cluster_plan.add_argument("--repair-schedule", default="*/15 * * * *")
    cluster_plan.add_argument("--repair-name", default="wavemind-cluster-repair")
    cluster_plan.add_argument("--repair-api-key-secret")
    cluster_plan.add_argument("--repair-api-key-secret-key", default="api-key")
    cluster_plan.add_argument("--repair-limit", type=int, default=1000)
    cluster_plan.add_argument("--repair-include-expired", action="store_true")
    cluster_plan.add_argument("--repair-tag", action="append", default=[])
    cluster_plan.add_argument("--json", action="store_true")

    cluster_repair = sub.add_parser(
        "cluster-repair",
        help="Run service-mode anti-entropy repair across cluster namespaces",
    )
    cluster_repair.add_argument("--namespace", action="append", default=[])
    cluster_repair.add_argument("--namespace-prefix", default="tenant")
    cluster_repair.add_argument("--namespace-count", type=int, default=0)
    cluster_repair.add_argument("--node", action="append", required=True, help="node_id=host:port or node_id")
    cluster_repair.add_argument("--replication-factor", type=int, default=2)
    cluster_repair.add_argument("--write-quorum", type=int)
    cluster_repair.add_argument("--read-quorum", type=int, default=1)
    cluster_repair.add_argument(
        "--api-key",
        default=os.environ.get("WAVEMIND_API_KEY"),
        help="Bearer token for WaveMind API nodes. Defaults to WAVEMIND_API_KEY.",
    )
    cluster_repair.add_argument("--timeout", type=float, default=10.0)
    cluster_repair.add_argument("--limit", type=int, default=1000)
    cluster_repair.add_argument("--include-expired", action="store_true")
    cluster_repair.add_argument("--tag", action="append", default=[])
    cluster_repair.add_argument("--fail-fast", action="store_true")
    cluster_repair.add_argument("--json", action="store_true")

    audit = sub.add_parser("audit", help="Show audit log events")
    audit.add_argument("--namespace")
    audit.add_argument("--action")
    audit.add_argument("--limit", type=int, default=20)
    audit.add_argument("--json", action="store_true")

    maintenance = sub.add_parser("maintenance", help="Run one deterministic maintenance job")
    maintenance.add_argument("--namespace")
    maintenance.add_argument("--consolidate-steps", type=int, default=0)
    maintenance.add_argument("--consolidate-concepts", action="store_true")
    maintenance.add_argument("--no-rebuild-index", action="store_true")
    maintenance.add_argument("--json", action="store_true")

    cache_prewarm = sub.add_parser(
        "cache-prewarm",
        help="Prewarm hot query cache from audited query events",
    )
    cache_prewarm.add_argument("--namespace")
    cache_prewarm.add_argument("--audit-limit", type=int, default=256)
    cache_prewarm.add_argument("--max-queries", type=int, default=32)
    cache_prewarm.add_argument("--min-frequency", type=int, default=1)
    cache_prewarm.add_argument("--top-k", type=int, default=3)
    cache_prewarm.add_argument("--min-score", type=float)
    cache_prewarm.add_argument("--capacity", type=int, default=512)
    cache_prewarm.add_argument("--ttl-seconds", type=float, default=60.0)
    cache_prewarm.add_argument(
        "--redis-url",
        default=os.environ.get("WAVEMIND_REDIS_URL"),
        help="Redis URL for a shared production cache. Defaults to WAVEMIND_REDIS_URL.",
    )
    cache_prewarm.add_argument(
        "--redis-prefix",
        default=os.environ.get("WAVEMIND_REDIS_PREFIX", "wavemind:hot"),
    )
    cache_prewarm.add_argument("--json", action="store_true")

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

    replicated_snapshot = sub.add_parser(
        "replicated-snapshot",
        help="Snapshot a ReplicatedWaveMind root with optional offsite mirror/archive",
    )
    replicated_snapshot.add_argument("--root", required=True)
    replicated_snapshot.add_argument("--node", action="append", required=True)
    replicated_snapshot.add_argument("--replication-factor", type=int, default=3)
    replicated_snapshot.add_argument("--write-quorum", type=int)
    replicated_snapshot.add_argument("--read-quorum", type=int, default=1)
    replicated_snapshot.add_argument("--out", required=True)
    replicated_snapshot.add_argument("--offsite")
    replicated_snapshot.add_argument("--archive")
    replicated_snapshot.add_argument(
        "--s3",
        help="Upload archive to s3://bucket/prefix or s3://bucket/key.tar.gz",
    )
    replicated_snapshot.add_argument("--s3-endpoint-url")
    replicated_snapshot.add_argument("--s3-region")
    replicated_snapshot.add_argument(
        "--s3-keep-last",
        type=int,
        help="Prune older S3-compatible snapshot archives after upload",
    )
    replicated_snapshot.add_argument("--keep-last", type=int)
    replicated_snapshot.add_argument("--prefix", default="wavemind-replicated")
    replicated_snapshot.add_argument("--allow-partial", action="store_true")
    replicated_snapshot.add_argument("--json", action="store_true")

    replicated_restore = sub.add_parser(
        "replicated-restore",
        help="Restore a ReplicatedWaveMind snapshot into a replica root",
    )
    replicated_restore.add_argument("--from", dest="source", required=True)
    replicated_restore.add_argument("--to", dest="destination", required=True)
    replicated_restore.add_argument("--overwrite", action="store_true")
    replicated_restore.add_argument("--s3-endpoint-url")
    replicated_restore.add_argument("--s3-region")
    replicated_restore.add_argument(
        "--latest",
        action="store_true",
        help="Restore the newest archive under an s3://bucket/prefix source",
    )
    replicated_restore.add_argument("--json", action="store_true")

    replicated_s3_archives = sub.add_parser(
        "replicated-s3-archives",
        help="List or prune S3-compatible replicated snapshot archives",
    )
    replicated_s3_archives.add_argument("--s3", required=True)
    replicated_s3_archives.add_argument("--s3-endpoint-url")
    replicated_s3_archives.add_argument("--s3-region")
    replicated_s3_archives.add_argument("--latest", action="store_true")
    replicated_s3_archives.add_argument("--prune-keep-last", type=int)
    replicated_s3_archives.add_argument("--json", action="store_true")

    replicated_drill = sub.add_parser(
        "replicated-drill",
        help="Run an S3-compatible replicated snapshot disaster-recovery drill",
    )
    replicated_drill.add_argument("--from", dest="source", required=True)
    replicated_drill.add_argument("--to", dest="destination", required=True)
    replicated_drill.add_argument("--download-to")
    replicated_drill.add_argument("--overwrite", action="store_true")
    replicated_drill.add_argument("--s3-endpoint-url")
    replicated_drill.add_argument("--s3-region")
    replicated_drill.add_argument("--latest", action="store_true")
    replicated_drill.add_argument("--namespace")
    replicated_drill.add_argument("--query")
    replicated_drill.add_argument("--expect-text")
    replicated_drill.add_argument("--top-k", type=int, default=1)
    replicated_drill.add_argument("--keep-primary", action="store_true")
    replicated_drill.add_argument("--json", action="store_true")

    bench = sub.add_parser("benchmark", help="Run a synthetic recall benchmark")
    bench.add_argument("--namespace", default="bench")
    bench.add_argument("--top-k", type=int, default=1)

    serve = sub.add_parser("serve", help="Run FastAPI daemon")
    serve.add_argument("--host", default="0.0.0.0")
    serve.add_argument("--port", type=int, default=8000)

    studio = sub.add_parser("studio", help="Run local WaveMind Studio dashboard")
    studio.add_argument("--host", default="127.0.0.1")
    studio.add_argument("--port", type=int, default=8000)
    studio.add_argument("--no-open", action="store_true")

    sub.add_parser("test", help="Run pytest suite")
    return parser


def make_mind(args) -> WaveMind:
    encoder = create_text_encoder(kind=args.encoder, vector_dim=384, model_name=args.model)
    db_path = Path(args.db) if args.db else Path.cwd() / "wavemind.sqlite3"
    return WaveMind(
        db_path=db_path,
        store_kind=args.store,
        postgres_dsn=args.postgres_dsn,
        width=args.width,
        height=args.height,
        layers=args.layers,
        encoder=encoder,
        index_kind=args.index,
        score_threshold=args.score_threshold,
        audit_queries=args.audit_queries,
        graph_weight=args.graph_weight,
        graph_steps=args.graph_steps,
        graph_expand_k=args.graph_expand_k,
    )


def make_replicated_mind(args) -> ReplicatedWaveMind:
    encoder = create_text_encoder(kind=args.encoder, vector_dim=384, model_name=args.model)
    return ReplicatedWaveMind(
        root_path=args.root,
        nodes=[_parse_cluster_node(value) for value in args.node],
        replication_factor=args.replication_factor,
        write_quorum=args.write_quorum,
        read_quorum=args.read_quorum,
        width=args.width,
        height=args.height,
        layers=args.layers,
        encoder=encoder,
        index_kind=args.index,
        score_threshold=args.score_threshold,
        audit_queries=args.audit_queries,
        graph_weight=args.graph_weight,
        graph_steps=args.graph_steps,
        graph_expand_k=args.graph_expand_k,
    )


def replicated_restore_kwargs(args) -> dict[str, object]:
    return {
        "width": args.width,
        "height": args.height,
        "layers": args.layers,
        "encoder": create_text_encoder(
            kind=args.encoder,
            vector_dim=384,
            model_name=args.model,
        ),
        "index_kind": args.index,
        "score_threshold": args.score_threshold,
        "graph_weight": args.graph_weight,
        "graph_steps": args.graph_steps,
        "graph_expand_k": args.graph_expand_k,
    }


def print_stats(stats: dict) -> None:
    for key, value in stats.items():
        print(f"{key}: {value}")


def print_scale_plan(plan: dict[str, object]) -> None:
    print(f"tier: {plan['tier']}")
    print(f"status: {plan['status']}")
    print(f"current_memories: {plan['current_memories']}")
    print(f"target_memories: {plan['target_memories']}")
    print(f"index: {plan['index']}")
    print(f"recommended_index: {plan['recommended_index']}")
    print(f"latency_target_ms: {plan['latency_target_ms']}")
    warnings = plan.get("warnings") or []
    actions = plan.get("actions") or []
    if warnings:
        print("warnings:")
        for item in warnings:
            print(f"- {item}")
    if actions:
        print("actions:")
        for item in actions:
            print(f"- {item}")


def print_quickstart() -> None:
    print(
        """WaveMind quickstart

Install:
  python -m pip install wavemind

Store one memory:
  wavemind remember "Andrey is a trader" --namespace demo

Query it:
  wavemind query "What does Andrey do?" --namespace demo

Check state:
  wavemind stats --namespace demo

Where data goes:
  ./wavemind.sqlite3 in the current directory by default

Useful next commands:
  wavemind --help
  wavemind studio
  wavemind import ./notes.txt --namespace demo
  wavemind serve --host 127.0.0.1 --port 8000
  wavemind forget --namespace demo
"""
    )


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

    if args.command == "quickstart":
        print_quickstart()
        return 0

    if args.command == "test":
        import pytest

        return int(pytest.main(["-q"]))

    if args.command == "serve":
        import uvicorn

        from .api import create_app

        uvicorn.run(create_app(mind=make_mind(args)), host=args.host, port=args.port)
        return 0

    if args.command == "studio":
        import webbrowser
        from threading import Timer

        import uvicorn

        from .api import create_app

        open_host = "127.0.0.1" if args.host in {"0.0.0.0", "::"} else args.host
        url = f"http://{open_host}:{args.port}/studio"
        print(f"WaveMind Studio: {url}")
        if not args.no_open:
            Timer(1.0, lambda: webbrowser.open(url)).start()
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

    if args.command == "replicated-snapshot":
        memory = make_replicated_mind(args)
        try:
            object_store = None
            if args.s3 and (args.s3_endpoint_url or args.s3_region):
                object_store = S3SnapshotStore.from_uri(
                    args.s3,
                    endpoint_url=args.s3_endpoint_url,
                    region_name=args.s3_region,
                )
            report = ReplicatedSnapshotWorker(memory).run_once(
                destination=args.out,
                prefix=args.prefix,
                keep_last=args.keep_last,
                require_all=not args.allow_partial,
                offsite_destination=args.offsite,
                archive_destination=args.archive,
                object_store_destination=args.s3,
                object_store=object_store,
                object_store_keep_last=args.s3_keep_last,
            )
        finally:
            memory.close()
        payload = report.as_dict()
        if args.json:
            print(json.dumps(payload, ensure_ascii=False, indent=2))
        else:
            print(f"snapshot: {payload['snapshot_path']}")
            print(f"verified: {payload['verified']}")
            if payload["offsite_path"]:
                print(f"offsite: {payload['offsite_path']}")
                print(f"offsite_verified: {payload['offsite_verified']}")
            if payload["archive_path"]:
                print(f"archive: {payload['archive_path']}")
                print(f"archive_verified: {payload['archive_verified']}")
            if payload["object_store_upload"]:
                upload = payload["object_store_upload"]
                print(f"object_store: {upload['uri']}")
                print(f"object_store_verified: {upload['verified']}")
            if payload["pruned_object_store"]:
                print(f"object_store_pruned: {len(payload['pruned_object_store'])}")
        return 0 if report.ok else 4

    if args.command == "replicated-restore":
        source = Path(args.source)
        if args.source.startswith("s3://"):
            store = S3SnapshotStore.from_uri(
                args.source,
                endpoint_url=args.s3_endpoint_url,
                region_name=args.s3_region,
            )
            with tempfile.TemporaryDirectory(prefix="wavemind-s3-restore-") as tmp:
                remote_source = args.source
                if args.latest:
                    latest = store.latest_archive()
                    if latest is None:
                        print(
                            f"no snapshot archives found under {args.source}",
                            file=sys.stderr,
                        )
                        return 4
                    remote_source = latest.uri
                archive_path = store.download_archive(remote_source, tmp)
                restored, report = ReplicatedWaveMind.restore_snapshot_archive(
                    archive_path,
                    args.destination,
                    overwrite=args.overwrite,
                )
        elif args.latest:
            print("--latest is only supported with s3:// sources", file=sys.stderr)
            return 2
        elif source.name.endswith(".tar.gz") or source.suffix == ".tgz":
            restored, report = ReplicatedWaveMind.restore_snapshot_archive(
                source,
                args.destination,
                overwrite=args.overwrite,
            )
        else:
            restored, report = ReplicatedWaveMind.restore_snapshot(
                source,
                args.destination,
                overwrite=args.overwrite,
            )
        try:
            payload = report.as_dict()
        finally:
            restored.close()
        if args.json:
            print(json.dumps(payload, ensure_ascii=False, indent=2))
        else:
            print(f"restored: {payload['root_path']}")
            print(f"nodes: {len(payload['nodes'])}")
        return 0

    if args.command == "replicated-s3-archives":
        store = S3SnapshotStore.from_uri(
            args.s3,
            endpoint_url=args.s3_endpoint_url,
            region_name=args.s3_region,
        )
        pruned = ()
        if args.prune_keep_last is not None:
            pruned = store.prune_archives(keep_last=args.prune_keep_last)
        archives = store.list_archives()
        latest = archives[0] if archives else None
        archive_dicts = [archive.as_dict() for archive in archives]
        if args.latest:
            archive_dicts = [latest.as_dict()] if latest is not None else []
        payload = {
            "source": args.s3,
            "archives": archive_dicts,
            "latest": latest.as_dict() if latest is not None else None,
            "pruned": [archive.as_dict() for archive in pruned],
        }
        if args.json:
            print(json.dumps(payload, ensure_ascii=False, indent=2))
        else:
            if not archive_dicts:
                print(f"no snapshot archives found under {args.s3}")
            else:
                for archive in archive_dicts:
                    print(
                        f"{archive['uri']} "
                        f"bytes={archive['total_bytes']} "
                        f"verified={archive['verified']}"
                    )
                if pruned:
                    print(f"pruned: {len(pruned)}")
        return 0

    if args.command == "replicated-drill":
        store = S3SnapshotStore.from_uri(
            args.source,
            endpoint_url=args.s3_endpoint_url,
            region_name=args.s3_region,
        )
        try:
            report = ReplicatedObjectStoreDrillWorker(store).run_once(
                source=args.source,
                destination=args.destination,
                latest=args.latest or None,
                download_destination=args.download_to,
                overwrite=args.overwrite,
                namespace=args.namespace,
                query=args.query,
                expected_text=args.expect_text,
                top_k=args.top_k,
                disable_primary=not args.keep_primary,
                **replicated_restore_kwargs(args),
            )
        except Exception as exc:
            if args.json:
                print(
                    json.dumps(
                        {"ok": False, "error": str(exc)},
                        ensure_ascii=False,
                        indent=2,
                    )
                )
            else:
                print(f"drill failed: {exc}", file=sys.stderr)
            return 4
        payload = report.as_dict()
        if args.json:
            print(json.dumps(payload, ensure_ascii=False, indent=2))
        else:
            print(f"selected_archive: {payload['selected_archive']['uri']}")
            print(f"download_matches_object: {payload['download_matches_object']}")
            print(f"archive_verified: {payload['archive_verified']}")
            print(f"restored: {payload['restore_root']}")
            if payload["primary_node_disabled"]:
                print(f"primary_node_disabled: {payload['primary_node_disabled']}")
                print(
                    "recalled_after_primary_loss: "
                    f"{payload['recalled_after_primary_loss']}"
                )
            print(f"ok: {payload['ok']}")
        return 0 if report.ok else 4

    if args.command == "scale-plan":
        current_memories = args.current_memories
        vector_dim = 768 if args.encoder == "sentence" else 384
        index_name = args.index
        mind = None
        try:
            if current_memories is None:
                mind = make_mind(args)
                plan_obj = mind.scale_plan(
                    target_memories=args.target_memories,
                    namespace=args.namespace,
                    latency_target_ms=args.latency_target_ms,
                )
            else:
                plan_obj = build_scale_plan(
                    current_memories=current_memories,
                    target_memories=args.target_memories,
                    index=index_name,
                    vector_dim=vector_dim,
                    namespace=args.namespace,
                    latency_target_ms=args.latency_target_ms,
                )
            plan = plan_obj.as_dict()
            failed_threshold = (
                args.fail_on is not None
                and scale_status_meets_or_exceeds(plan_obj.status, args.fail_on)
            )
        finally:
            if mind is not None:
                mind.close()
        if args.json:
            print(json.dumps(plan, ensure_ascii=False, indent=2))
        else:
            print_scale_plan(plan)
        return 3 if failed_threshold else 0

    if args.command == "cluster-plan":
        namespaces = list(args.namespace)
        namespaces.extend(
            f"{args.namespace_prefix}:{index}"
            for index in range(max(0, int(args.namespace_count)))
        )
        nodes = [_parse_cluster_node(value) for value in args.node]
        plan = build_cluster_plan(
            namespaces=namespaces,
            nodes=nodes,
            replication_factor=args.replication_factor,
        )
        payload = plan.as_dict()
        if args.kubernetes:
            payload["kubernetes"] = plan.kubernetes_manifest(
                image=args.image,
                storage_size=args.storage_size,
            )
        if args.repair_cronjob:
            payload["repair_cronjob"] = plan.kubernetes_repair_cronjob(
                image=args.image,
                schedule=args.repair_schedule,
                name=args.repair_name,
                api_key_secret=args.repair_api_key_secret,
                api_key_secret_key=args.repair_api_key_secret_key,
                repair_limit=args.repair_limit,
                include_expired=args.repair_include_expired,
                tags=tuple(args.repair_tag),
            )
        if args.json:
            print(json.dumps(payload, ensure_ascii=False, indent=2))
        else:
            print(f"nodes: {len(plan.nodes)}")
            print(f"namespaces: {len(plan.placements)}")
            print(f"replication_factor: {plan.replication_factor}")
            print("node_load:")
            for node_id, load in sorted(plan.node_load.items()):
                print(f"- {node_id}: {load}")
            if plan.warnings:
                print("warnings:")
                for warning in plan.warnings:
                    print(f"- {warning}")
        return 0

    if args.command == "cluster-repair":
        namespaces = list(args.namespace)
        namespaces.extend(
            f"{args.namespace_prefix}:{index}"
            for index in range(max(0, int(args.namespace_count)))
        )
        if not namespaces:
            print("cluster-repair requires --namespace or --namespace-count", file=sys.stderr)
            return 2
        client = HTTPNamespaceShardClient(api_key=args.api_key, timeout=args.timeout)
        memory = DistributedShardedWaveMind(
            nodes=[_parse_cluster_node(value) for value in args.node],
            replication_factor=args.replication_factor,
            write_quorum=args.write_quorum,
            read_quorum=args.read_quorum,
            client=client,
        )
        report = DistributedRepairWorker(memory).run_once(
            namespaces=tuple(namespaces),
            limit=args.limit,
            include_expired=args.include_expired,
            tags=tuple(args.tag),
            fail_fast=args.fail_fast,
        )
        payload = report.as_dict()
        if args.json:
            print(json.dumps(payload, ensure_ascii=False, indent=2))
        else:
            print(f"namespaces: {len(payload['namespaces'])}")
            print(f"repaired_total: {payload['repaired_total']}")
            print(f"tombstone_deleted: {payload['tombstone_deleted']}")
            if payload["failed_namespaces"]:
                print("failed_namespaces:")
                for namespace, error in payload["failed_namespaces"].items():
                    print(f"- {namespace}: {error}")
            print(f"ok: {payload['ok']}")
        return 0 if report.ok else 4

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

    if args.command == "index-health":
        health = mind.index_health()
        if args.json:
            print(json.dumps(health, ensure_ascii=False, indent=2))
        else:
            print_stats(health)
        return 0

    if args.command == "rebuild-index":
        health = mind.rebuild_index()
        if args.json:
            print(json.dumps(health, ensure_ascii=False, indent=2))
        else:
            print_stats(health)
        return 0

    if args.command == "consolidate":
        concepts = mind.consolidate_concepts(
            namespace=args.namespace,
            seed_text=args.seed,
            min_energy=args.min_energy,
            min_size=args.min_size,
            max_concepts=args.max_concepts,
            priority=args.priority,
        )
        if args.json:
            print(json.dumps({"concepts": concepts}, ensure_ascii=False, indent=2))
        else:
            if not concepts:
                print("created=0")
            for concept in concepts:
                print(f"created id={concept['id']} namespace={concept['namespace']} {concept['text']}")
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

    if args.command == "maintenance":
        report = MemoryMaintenanceWorker(mind).run_once(
            namespace=args.namespace,
            consolidate_steps=args.consolidate_steps,
            consolidate_concepts=args.consolidate_concepts,
            rebuild_unhealthy_index=not args.no_rebuild_index,
        )
        payload = report.as_dict()
        if args.json:
            print(json.dumps(payload, ensure_ascii=False, indent=2))
        else:
            print_stats(payload)
        return 0

    if args.command == "cache-prewarm":
        if args.redis_url:
            cache = RedisHotMemoryCache.from_url(
                args.redis_url,
                prefix=args.redis_prefix,
                ttl_seconds=args.ttl_seconds,
            )
        else:
            cache = HotMemoryCache(capacity=args.capacity, ttl_seconds=args.ttl_seconds)
        report = CachePrewarmWorker(mind, cache).run_once(
            namespace=args.namespace,
            audit_limit=args.audit_limit,
            max_queries=args.max_queries,
            min_frequency=args.min_frequency,
            top_k=args.top_k,
            min_score=args.min_score,
        )
        payload = report.as_dict()
        payload["cache"] = "redis" if args.redis_url else "local"
        if args.json:
            print(json.dumps(payload, ensure_ascii=False, indent=2))
        else:
            print_stats(payload)
            if not args.redis_url:
                print(
                    "note: local cache is process-local; use --redis-url for production prewarm",
                    file=sys.stderr,
                )
        return 0 if report.ok else 4

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


def _parse_cluster_node(value: str) -> ClusterNode:
    node_id, sep, address = value.partition("=")
    node_id = node_id.strip()
    address = address.strip() if sep else node_id
    return ClusterNode(id=node_id, address=address)


if __name__ == "__main__":
    raise SystemExit(main())

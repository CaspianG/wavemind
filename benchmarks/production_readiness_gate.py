from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _load_optional_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return _load_json(path)


def _engine_results(payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        str(result["engine"]): result
        for result in payload.get("results", [])
        if "engine" in result
    }


def _size_results(payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
    rows: dict[str, dict[str, Any]] = {}
    for size_result in payload.get("results", []):
        for result in size_result.get("results", []):
            if "engine" in result:
                rows[str(result["engine"])] = result
    return rows


def _criterion(
    *,
    criterion_id: str,
    title: str,
    status: str,
    requirement: str,
    evidence: str,
    next_step: str,
) -> dict[str, str]:
    if status not in {"pass", "action_required", "fail"}:
        raise ValueError("status must be pass, action_required, or fail")
    return {
        "id": criterion_id,
        "title": title,
        "status": status,
        "requirement": requirement,
        "evidence": evidence,
        "next_step": next_step,
    }


def _load_artifacts(root: Path) -> dict[str, dict[str, Any]]:
    benchmark_dir = root / "benchmarks"
    return {
        "audit": _load_json(benchmark_dir / "benchmark_artifact_audit.json"),
        "load_100k": _load_json(benchmark_dir / "production_load_qdrant_100k_tuned_results.json"),
        "load_1m": _load_json(benchmark_dir / "production_load_qdrant_1m_tuned_results.json"),
        "load_1m_faiss": _load_json(benchmark_dir / "production_load_faiss_1m_results.json"),
        "load_1m_ef": _load_json(benchmark_dir / "production_load_qdrant_1m_ef_sweep_results.json"),
        "load_10m": _load_optional_json(benchmark_dir / "production_load_10m_results.json"),
        "scale": _load_json(benchmark_dir / "scale_readiness_results.json"),
        "competitors": _load_json(benchmark_dir / "memory_competitor_results.json"),
    }


def evaluate_production_readiness(root: Path = PROJECT_ROOT) -> dict[str, Any]:
    artifacts = _load_artifacts(root)
    audit = artifacts["audit"]
    load_100k = _size_results(artifacts["load_100k"]).get("Qdrant service", {})
    load_1m_qdrant = _size_results(artifacts["load_1m"]).get("Qdrant service", {})
    load_1m_faiss = _size_results(artifacts["load_1m_faiss"]).get("WaveMind faiss-persisted", {})
    load_10m_candidates = [
        result
        for size_result in artifacts["load_10m"].get("results", [])
        if int(size_result.get("vectors", 0)) >= 10_000_000
        for result in size_result.get("results", [])
        if not result.get("skipped")
    ]
    load_10m = max(
        load_10m_candidates,
        key=lambda row: (
            float(row.get("recall_at_k", 0.0)) >= 0.95,
            float(row.get("p99_latency_ms", float("inf"))) <= 100.0,
            row.get("cost_status") == "valid_slo",
            float(row.get("recall_at_k", 0.0)),
            -float(row.get("p99_latency_ms", float("inf"))),
        ),
        default={},
    )
    load_10m_pass = (
        bool(load_10m)
        and float(load_10m.get("recall_at_k", 0.0)) >= 0.95
        and float(load_10m.get("p99_latency_ms", float("inf"))) <= 100.0
        and load_10m.get("cost_status") == "valid_slo"
    )
    load_1m_candidates = [row for row in (load_1m_faiss, load_1m_qdrant) if row]
    load_1m = max(
        load_1m_candidates,
        key=lambda row: (
            float(row.get("recall_at_k", 0.0)) >= 0.95,
            float(row.get("p99_latency_ms", float("inf"))) <= 100.0,
            row.get("cost_status") == "valid_slo",
            float(row.get("recall_at_k", 0.0)),
            -float(row.get("p99_latency_ms", float("inf"))),
        ),
        default={},
    )
    load_1m_queries = max(
        int(artifacts["load_1m"].get("scenario", {}).get("queries_per_size", 0)),
        int(artifacts["load_1m_faiss"].get("scenario", {}).get("queries_per_size", 0)),
    )
    scale = _engine_results(artifacts["scale"])
    competitors = _engine_results(artifacts["competitors"])

    cluster = scale.get("WaveMind cluster planner", {})
    operator = scale.get("WaveMind Kubernetes operator", {})
    serverless = scale.get("WaveMind serverless plan", {})
    hot_cache = scale.get("WaveMind hot cache", {})
    sharding = scale.get("WaveMind distributed sharding", {})
    runtime = scale.get("WaveMind replicated runtime", {})
    active_active = scale.get("WaveMind active-active delta sync", {})
    field_crdt = scale.get("WaveMind field-state CRDT", {})
    snapshot = scale.get("WaveMind replicated snapshot", {})
    payloads = scale.get("WaveMind structured payloads", {})

    skipped_competitors = [
        name
        for name in ("Mem0", "Zep", "LangGraph persistent memory")
        if competitors.get(name, {}).get("skipped")
    ]

    criteria = [
        _criterion(
            criterion_id="benchmark_artifact_freshness",
            title="Checked-in benchmark artifacts are synchronized",
            status="pass" if audit.get("status") == "pass" else "fail",
            requirement="Benchmark matrix, report, and leaderboard must render from the same checked-in JSON.",
            evidence=f"audit status {audit.get('status')}, generated_at {audit.get('generated_at')}",
            next_step="Keep the benchmark refresh workflow green and block stale artifacts before release.",
        ),
        _criterion(
            criterion_id="production_100k_slo_cost",
            title="100k service-backed load profile passes SLO and cost gate",
            status=(
                "pass"
                if load_100k.get("slo_status") == "pass"
                and load_100k.get("cost_status") == "valid_slo"
                else "fail"
            ),
            requirement="recall@10 >= 0.95, p99 <= 100 ms, target QPS capacity available, and cost estimate present.",
            evidence=(
                f"recall {load_100k.get('recall_at_k')}, "
                f"p99 {load_100k.get('p99_latency_ms')} ms, "
                f"cost ${load_100k.get('compute_cost_per_1m_queries_usd'):.2f}/1M queries"
            ),
            next_step="Keep the 100k profile green while adding persisted FAISS and pgvector service runs.",
        ),
        _criterion(
            criterion_id="production_1m_slo",
            title="1M service-backed load profile meets recall and p99 SLO",
            status=(
                "pass"
                if float(load_1m.get("recall_at_k", 0.0)) >= 0.95
                and float(load_1m.get("p99_latency_ms", float("inf"))) <= 100.0
                and load_1m.get("cost_status") == "valid_slo"
                else "action_required"
                if float(load_1m.get("recall_at_k", 0.0)) >= 0.95
                else "fail"
            ),
            requirement="recall@10 >= 0.95 and p99 <= 100 ms at 1M vectors.",
            evidence=(
                f"{load_1m.get('engine')}: recall {load_1m.get('recall_at_k')}, "
                f"p99 {load_1m.get('p99_latency_ms')} ms, "
                f"SLO {load_1m.get('slo_status')}"
            ),
            next_step="Keep FAISS 1M green in CI-capable benchmark environments and continue tuning Qdrant/pgvector service paths.",
        ),
        _criterion(
            criterion_id="production_1m_query_depth",
            title="1M load result has enough query depth for a production claim",
            status="pass" if load_1m_queries >= 100 else "action_required",
            requirement="Use at least 100 queries for checked-in 1M production claims.",
            evidence=f"current tuned 1M profile uses {load_1m_queries} queries",
            next_step="Keep 100+ query depth for all checked-in 1M production profiles.",
        ),
        _criterion(
            criterion_id="cluster_ha_placement",
            title="Namespace placement survives node and zone loss",
            status=(
                "pass"
                if cluster.get("node_loss_min_availability") == 1.0
                and cluster.get("zone_loss_min_availability") == 1.0
                else "fail"
            ),
            requirement="Replicated namespace placement must keep availability at 1.0 under node and zone loss simulation.",
            evidence=(
                f"node loss {cluster.get('node_loss_min_availability')}, "
                f"zone loss {cluster.get('zone_loss_min_availability')}, "
                f"namespaces {cluster.get('namespaces')}"
            ),
            next_step="Validate the same placement under live multi-node service load.",
        ),
        _criterion(
            criterion_id="operator_autoscaling_repair",
            title="Kubernetes operator bundle includes HPA and repair job",
            status=(
                "pass"
                if operator.get("bundle_has_crd")
                and operator.get("has_hpa")
                and operator.get("has_repair_cronjob")
                else "fail"
            ),
            requirement="Operator output must include CRD, StatefulSet, Service, HPA, and scheduled repair.",
            evidence=(
                f"CRD {operator.get('bundle_has_crd')}, "
                f"HPA {operator.get('has_hpa')}, repair {operator.get('has_repair_cronjob')}"
            ),
            next_step="Run a real Kubernetes smoke deploy and collect HPA behavior under load.",
        ),
        _criterion(
            criterion_id="serverless_externalized_state",
            title="Serverless plan externalizes state and validates KEDA target",
            status=(
                "pass"
                if serverless.get("valid_keda_scale_target")
                and serverless.get("uses_postgres")
                and serverless.get("uses_external_qdrant")
                and serverless.get("uses_shared_cache")
                else "fail"
            ),
            requirement="Serverless mode must use external durable state, external vector index, and shared cache.",
            evidence=(
                f"Postgres {serverless.get('uses_postgres')}, "
                f"Qdrant {serverless.get('uses_external_qdrant')}, "
                f"Redis {serverless.get('uses_shared_cache')}"
            ),
            next_step="Run service-backed KEDA/Knative load tests instead of manifest-only checks.",
        ),
        _criterion(
            criterion_id="hot_cache_prewarm",
            title="Hot cache and query-audit prewarm work",
            status=(
                "pass"
                if float(hot_cache.get("hit_rate", 0.0)) >= 0.8
                and hot_cache.get("prewarm_hit")
                else "fail"
            ),
            requirement="Frequently recalled memory paths must be cacheable and prewarmable.",
            evidence=(
                f"hit rate {hot_cache.get('hit_rate')}, "
                f"prewarm hit {hot_cache.get('prewarm_hit')}, "
                f"p99 {hot_cache.get('p99_lookup_ms')} ms"
            ),
            next_step="Back the cache with Redis in a service-mode benchmark.",
        ),
        _criterion(
            criterion_id="distributed_repair_tombstones",
            title="Distributed sharding repairs replicas and tombstones stale deletes",
            status=(
                "pass"
                if sharding.get("recalled_after_primary_loss")
                and sharding.get("repair_ok")
                and sharding.get("tombstone_suppressed_after_repair")
                and sharding.get("anti_entropy_worker_ok")
                else "fail"
            ),
            requirement="Replicated writes, missing-record repair, tombstone repair, and anti-entropy must all pass.",
            evidence=(
                f"repair {sharding.get('repair_repaired_total')}, "
                f"tombstone deleted {sharding.get('tombstone_repair_deleted_records')}, "
                f"anti-entropy repaired {sharding.get('anti_entropy_worker_repaired_total')}"
            ),
            next_step="Run the same repair flow against real HTTP shard clients.",
        ),
        _criterion(
            criterion_id="replicated_runtime_loss",
            title="Runtime replica quorum survives node loss",
            status=(
                "pass"
                if runtime.get("recalled_after_node_loss")
                and runtime.get("repair_copied_records", 0) >= 1
                and runtime.get("tombstone_suppressed_after_repair")
                else "fail"
            ),
            requirement="Quorum runtime must recall after node loss and repair missing records plus tombstones.",
            evidence=(
                f"recall after loss {runtime.get('recalled_after_node_loss')}, "
                f"repair copied {runtime.get('repair_copied_records')}, "
                f"p99 {runtime.get('p99_query_after_loss_ms')} ms"
            ),
            next_step="Measure the same path under concurrent writes and reads.",
        ),
        _criterion(
            criterion_id="active_active_field_crdt",
            title="Active-active sync and field-state CRDT converge",
            status=(
                "pass"
                if active_active.get("converged_after_bidirectional_sync")
                and active_active.get("tombstone_converged")
                and field_crdt.get("commutative_convergence")
                and field_crdt.get("idempotent_remerge")
                and field_crdt.get("tombstone_wins")
                else "fail"
            ),
            requirement="Multi-region memory deltas and field state must converge without duplicate amplification.",
            evidence=(
                f"delta sync {active_active.get('converged_after_bidirectional_sync')}, "
                f"CRDT idempotent {field_crdt.get('idempotent_remerge')}"
            ),
            next_step="Run active-active sync against independent persistent stores.",
        ),
        _criterion(
            criterion_id="backup_restore_dr",
            title="Snapshots, archives, offsite mirror, and object-store DR verify",
            status=(
                "pass"
                if snapshot.get("manifest_healthy")
                and snapshot.get("offsite_verified")
                and snapshot.get("archive_verified")
                and snapshot.get("object_store_drill_ok")
                and snapshot.get("recalled_after_restore_node_loss")
                else "fail"
            ),
            requirement="Backups must be checksummed, restorable, offsite-capable, and recover recall after restore.",
            evidence=(
                f"archive {snapshot.get('archive_verified')}, "
                f"object-store DR {snapshot.get('object_store_drill_ok')}, "
                f"restored files {snapshot.get('restored_files')}"
            ),
            next_step="Repeat the drill with real S3-compatible storage and larger SQLite/Postgres dumps.",
        ),
        _criterion(
            criterion_id="structured_multimodal_payloads",
            title="Structured and multimodal payload retrieval works",
            status="pass" if payloads.get("precision_at_1") == 1.0 else "fail",
            requirement="Images, audio, tables, and events must be storable and retrievable through the same memory API.",
            evidence=(
                f"modalities {', '.join(payloads.get('modalities', []))}, "
                f"precision@1 {payloads.get('precision_at_1')}"
            ),
            next_step="Add real CLIP/audio embedding backends and larger multimodal retrieval tests.",
        ),
        _criterion(
            criterion_id="real_competitor_adapters",
            title="Mem0, Zep, and LangGraph adapters have real configured results",
            status="pass" if not skipped_competitors else "action_required",
            requirement="Competitor comparison must run real packages/services, not approximations.",
            evidence=(
                "all configured"
                if not skipped_competitors
                else "skipped: " + ", ".join(skipped_competitors)
            ),
            next_step="Configure a dedicated Zep service/API key with cleanup policy and check in the live Zep adapter result.",
        ),
        _criterion(
            criterion_id="ten_million_load_profile",
            title="10M-vector production load profile passes recall, p99, and cost gate",
            status="pass" if load_10m_pass else "action_required",
            requirement="A real non-skipped 10M-vector service-backed benchmark must meet recall@10 >= 0.95, p99 <= 100 ms, and valid cost SLO before claiming 10M readiness.",
            evidence=(
                f"{load_10m.get('engine')}: recall {load_10m.get('recall_at_k')}, "
                f"p99 {load_10m.get('p99_latency_ms')} ms, "
                f"cost {load_10m.get('cost_status')}"
                if load_10m
                else "production_load_10m_results.json has no non-skipped 10M SLO row"
            ),
            next_step="Run 10M on larger hardware with FAISS/Qdrant/pgvector service profiles and check in the measured artifact.",
        ),
    ]

    pass_count = sum(1 for row in criteria if row["status"] == "pass")
    action_required_count = sum(
        1 for row in criteria if row["status"] == "action_required"
    )
    fail_count = sum(1 for row in criteria if row["status"] == "fail")
    total = len(criteria)
    readiness_score = pass_count / total
    overall_status = (
        "fail"
        if fail_count
        else "action_required"
        if action_required_count
        else "pass"
    )

    return {
        "schema": "wavemind.production_readiness.v1",
        "generated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "overall_status": overall_status,
        "readiness_score": readiness_score,
        "summary": {
            "overall_status": overall_status,
            "readiness_score": readiness_score,
            "pass_count": pass_count,
            "action_required_count": action_required_count,
            "fail_count": fail_count,
            "total_criteria": total,
        },
        "criteria": criteria,
    }


def render_markdown(payload: dict[str, Any]) -> str:
    summary = payload["summary"]
    lines = [
        "# WaveMind Production Readiness Gate",
        "",
        "This gate is generated from checked-in benchmark artifacts. It is a readiness",
        "verdict, not a marketing claim.",
        "",
        "| metric | value |",
        "|---|---:|",
        f"| overall status | `{summary['overall_status']}` |",
        f"| readiness score | `{summary['readiness_score']:.3f}` |",
        f"| passed criteria | `{summary['pass_count']}` |",
        f"| action required | `{summary['action_required_count']}` |",
        f"| failed criteria | `{summary['fail_count']}` |",
        f"| total criteria | `{summary['total_criteria']}` |",
        "",
        "| criterion | status | evidence | next step |",
        "|---|---|---|---|",
    ]
    for row in payload["criteria"]:
        lines.append(
            f"| {row['title']} | `{row['status']}` | {row['evidence']} | {row['next_step']} |"
        )
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=PROJECT_ROOT)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("benchmarks/production_readiness_results.json"),
    )
    parser.add_argument(
        "--markdown-output",
        type=Path,
        default=Path("benchmarks/PRODUCTION_READINESS.md"),
    )
    args = parser.parse_args()

    payload = evaluate_production_readiness(args.root)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    args.markdown_output.parent.mkdir(parents=True, exist_ok=True)
    args.markdown_output.write_text(render_markdown(payload), encoding="utf-8")
    print(
        f"{payload['overall_status']} "
        f"({payload['summary']['pass_count']}/{payload['summary']['total_criteria']} pass)"
    )
    return 0 if payload["overall_status"] in {"pass", "action_required"} else 1


if __name__ == "__main__":
    raise SystemExit(main())

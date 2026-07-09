from __future__ import annotations

import argparse
import json
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SOURCE_FILE = "benchmarks/scale_readiness_results.json"


def build_structured_memory_report(root: Path = PROJECT_ROOT) -> dict[str, Any]:
    root = Path(root)
    source = _load_json(root / SOURCE_FILE)
    row = _structured_row(source)
    if row is None:
        summary = _missing_summary()
        checks: list[dict[str, Any]] = []
    else:
        checks = _checks(row)
        summary = {
            "status": "pass" if all(check["pass"] for check in checks) else "watch",
            "modality_count": len(row.get("modalities", [])),
            "modalities": row.get("modalities", []),
            "query_count": row.get("queries", 0),
            "precision_at_1": row.get("precision_at_1"),
            "cross_modal_precision_at_1": row.get("cross_modal_precision_at_1"),
            "cross_modal_vectors_persisted_rate": row.get("cross_modal_vectors_persisted_rate"),
            "cross_modal_provenance_rate": row.get("cross_modal_provenance_rate"),
            "precomputed_vector_precision_at_1": row.get("precomputed_vector_precision_at_1"),
            "precomputed_vector_persisted_rate": row.get("precomputed_vector_persisted_rate"),
            "encoder_contract_ok": row.get("encoder_contract_ok"),
            "encoder_contract_target_precision_at_1": row.get("encoder_contract_target_precision_at_1"),
            "encoder_contract_global_precision_at_1": row.get("encoder_contract_global_precision_at_1"),
            "encoder_contract_margin": row.get("encoder_contract_min_global_margin"),
            "encoder_contract_min_required_margin": row.get("encoder_contract_min_required_margin"),
            "temporal_event_precision_at_1": row.get("temporal_event_precision_at_1"),
            "temporal_event_persistence_rate": row.get("temporal_event_persistence_rate"),
            "temporal_event_provenance_rate": row.get("temporal_event_provenance_rate"),
            "knowledge_graph_precision_at_1": row.get("knowledge_graph_precision_at_1"),
            "knowledge_graph_path_precision_at_1": row.get("knowledge_graph_path_precision_at_1"),
            "knowledge_graph_persistence_rate": row.get("knowledge_graph_persistence_rate"),
            "knowledge_graph_provenance_rate": row.get("knowledge_graph_provenance_rate"),
            "avg_latency_ms": row.get("avg_latency_ms"),
            "cross_modal_avg_latency_ms": row.get("cross_modal_avg_latency_ms"),
            "temporal_event_avg_latency_ms": row.get("temporal_event_avg_latency_ms"),
            "knowledge_graph_avg_latency_ms": row.get("knowledge_graph_avg_latency_ms"),
            "asset_manifest_verified": row.get("asset_manifest_verified"),
        }
    return {
        "schema": "wavemind.structured_memory_report.v1",
        "generated_at": _generated_at(root),
        "source_ref": _source_ref(root),
        "source_file": SOURCE_FILE,
        "claim_boundary": (
            "Structured-memory rows come from the checked-in scale-readiness artifact. "
            "They prove typed payload routing, provenance, persistence, temporal recall, "
            "and graph traversal on the deterministic fixture; they do not claim full "
            "production multimodal model quality."
        ),
        "summary": summary,
        "checks": checks,
        "raw_metrics": row or {},
    }


def render_structured_memory_markdown(payload: dict[str, Any]) -> str:
    summary = payload.get("summary", {})
    checks = payload.get("checks", [])
    raw = payload.get("raw_metrics", {})
    return "\n".join(
        [
            "# WaveMind Structured Memory Report",
            "",
            f"Generated: `{payload.get('generated_at', 'unknown')}`.",
            "",
            str(payload.get("claim_boundary", "")),
            "",
            "## Summary",
            "",
            f"- Status: `{summary.get('status', 'missing')}`.",
            f"- Modalities: `{', '.join(summary.get('modalities', []))}`.",
            f"- Structured precision@1: `{_fmt(summary.get('precision_at_1'))}`.",
            f"- Cross-modal precision@1: `{_fmt(summary.get('cross_modal_precision_at_1'))}`.",
            f"- Precomputed-vector precision@1: `{_fmt(summary.get('precomputed_vector_precision_at_1'))}`.",
            f"- Temporal event precision@1: `{_fmt(summary.get('temporal_event_precision_at_1'))}`.",
            f"- Knowledge-graph precision@1: `{_fmt(summary.get('knowledge_graph_precision_at_1'))}`.",
            f"- Cross-modal avg latency: `{_fmt(summary.get('cross_modal_avg_latency_ms'))} ms`.",
            f"- Temporal avg latency: `{_fmt(summary.get('temporal_event_avg_latency_ms'))} ms`.",
            f"- Knowledge-graph avg latency: `{_fmt(summary.get('knowledge_graph_avg_latency_ms'))} ms`.",
            "",
            "## Gate Checks",
            "",
            "| check | status | value | target |",
            "|---|---|---:|---:|",
            *[_check_row(check) for check in checks],
            "",
            "## Coverage",
            "",
            "| area | evidence |",
            "|---|---|",
            f"| Typed payloads | `{raw.get('queries', 0)}` queries across `{len(raw.get('modalities', []))}` modalities. |",
            f"| Cross-modal routing | `{raw.get('cross_modal_queries', 0)}` typed queries, persisted vector rate `{_fmt(raw.get('cross_modal_vectors_persisted_rate'))}`, provenance `{_fmt(raw.get('cross_modal_provenance_rate'))}`. |",
            f"| External vectors | `{raw.get('precomputed_vector_queries', 0)}` strict precomputed-vector queries over `{', '.join(raw.get('precomputed_vector_target_modalities', []))}`. |",
            f"| Encoder contract | target@1 `{_fmt(raw.get('encoder_contract_target_precision_at_1'))}`, global@1 `{_fmt(raw.get('encoder_contract_global_precision_at_1'))}`, margin `{_fmt(raw.get('encoder_contract_min_global_margin'))}`. |",
            f"| Temporal events | around/window/recency/interval `{raw.get('temporal_event_around_precision_at_1')}/{raw.get('temporal_event_window_precision_at_1')}/{raw.get('temporal_event_recency_precision_at_1')}/{raw.get('temporal_event_interval_precision_at_1')}`. |",
            f"| Knowledge graph | direct/two-hop/three-hop/predicate `{raw.get('knowledge_graph_direct_precision_at_1')}/{raw.get('knowledge_graph_two_hop_precision_at_1')}/{raw.get('knowledge_graph_three_hop_precision_at_1')}/{raw.get('knowledge_graph_predicate_precision_at_1')}`. |",
            "",
            "## Next Production Step",
            "",
            "Run the same contract on real CLIP/audio/video/3D production encoders and larger object-store-backed corpora before claiming broad multimodal model quality.",
            "",
        ]
    )


def _checks(row: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        _check("modalities", len(row.get("modalities", [])), 7, ">="),
        _check("structured_precision_at_1", row.get("precision_at_1"), 1.0, ">="),
        _check("cross_modal_precision_at_1", row.get("cross_modal_precision_at_1"), 1.0, ">="),
        _check("cross_modal_vectors_persisted", row.get("cross_modal_vectors_persisted_rate"), 1.0, ">="),
        _check("cross_modal_provenance", row.get("cross_modal_provenance_rate"), 1.0, ">="),
        _check("precomputed_vector_precision_at_1", row.get("precomputed_vector_precision_at_1"), 1.0, ">="),
        _check("precomputed_vector_persisted", row.get("precomputed_vector_persisted_rate"), 1.0, ">="),
        _check("encoder_contract_ok", row.get("encoder_contract_ok"), True, "is"),
        _check("encoder_contract_target_precision_at_1", row.get("encoder_contract_target_precision_at_1"), 1.0, ">="),
        _check("encoder_contract_global_precision_at_1", row.get("encoder_contract_global_precision_at_1"), 1.0, ">="),
        _check("encoder_contract_margin", row.get("encoder_contract_min_global_margin"), row.get("encoder_contract_min_required_margin"), ">="),
        _check("temporal_event_precision_at_1", row.get("temporal_event_precision_at_1"), 1.0, ">="),
        _check("temporal_event_persistence", row.get("temporal_event_persistence_rate"), 1.0, ">="),
        _check("temporal_event_provenance", row.get("temporal_event_provenance_rate"), 1.0, ">="),
        _check("knowledge_graph_precision_at_1", row.get("knowledge_graph_precision_at_1"), 1.0, ">="),
        _check("knowledge_graph_path_precision_at_1", row.get("knowledge_graph_path_precision_at_1"), 1.0, ">="),
        _check("knowledge_graph_persistence", row.get("knowledge_graph_persistence_rate"), 1.0, ">="),
        _check("knowledge_graph_provenance", row.get("knowledge_graph_provenance_rate"), 1.0, ">="),
        _check("asset_manifest_verified", row.get("asset_manifest_verified"), True, "is"),
    ]


def _check(name: str, value: Any, target: Any, op: str) -> dict[str, Any]:
    passed = False
    if op == ">=":
        try:
            passed = float(value) >= float(target)
        except (TypeError, ValueError):
            passed = False
    elif op == "is":
        passed = value is target
    return {
        "name": name,
        "value": value,
        "target": target,
        "op": op,
        "pass": passed,
    }


def _check_row(check: dict[str, Any]) -> str:
    status = "pass" if check.get("pass") else "watch"
    target = f"{check.get('op')} {check.get('target')}"
    return (
        f"| {check.get('name')} | `{status}` | "
        f"`{_fmt(check.get('value'))}` | `{target}` |"
    )


def _structured_row(payload: dict[str, Any]) -> dict[str, Any] | None:
    for row in payload.get("results", []):
        if row.get("engine") == "WaveMind structured payloads":
            return row
    return None


def _missing_summary() -> dict[str, Any]:
    return {
        "status": "missing",
        "modality_count": 0,
        "modalities": [],
    }


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _generated_at(root: Path) -> str:
    env_value = os.getenv("WAVEMIND_BENCHMARK_GENERATED_AT")
    if env_value:
        return env_value
    source = _load_json(root / SOURCE_FILE)
    if source.get("generated_at"):
        return str(source["generated_at"])
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _source_ref(root: Path) -> str | None:
    env_value = os.getenv("GITHUB_SHA")
    if env_value:
        return env_value[:12]
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "--short=12", "HEAD"],
            cwd=root,
            text=True,
            encoding="utf-8",
            stderr=subprocess.DEVNULL,
        ).strip()
    except Exception:
        return None


def _fmt(value: Any) -> str:
    try:
        return f"{float(value):.3f}".rstrip("0").rstrip(".")
    except (TypeError, ValueError):
        return str(value)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=Path("benchmarks/structured_memory_results.json"))
    parser.add_argument("--markdown-output", type=Path, default=Path("benchmarks/STRUCTURED_MEMORY.md"))
    args = parser.parse_args()
    payload = build_structured_memory_report()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    args.markdown_output.parent.mkdir(parents=True, exist_ok=True)
    args.markdown_output.write_text(render_structured_memory_markdown(payload), encoding="utf-8")
    print(f"Wrote {args.output}")
    print(f"Wrote {args.markdown_output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

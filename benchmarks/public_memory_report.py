from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


REQUIRED_ENGINES = (
    "WaveMind",
    "WaveMind + Memory OS",
    "Chroma static",
    "Qdrant static",
    "Mem0 OSS",
    "Hindsight OSS",
)
EXTERNAL_ENGINES = {"Mem0 OSS", "Hindsight OSS"}
SCENARIO_KEYS = (
    "dataset_sha256",
    "conversations",
    "memories",
    "queries",
    "top_k",
)


def _load(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{path}: root must be an object")
    return payload


def _require_equal(
    artifacts: list[tuple[Path, dict[str, Any]]],
    *,
    section: str,
    keys: Iterable[str],
) -> dict[str, Any]:
    first_path, first_payload = artifacts[0]
    first = dict(first_payload.get(section) or {})
    for key in keys:
        if key not in first:
            raise ValueError(f"{first_path}: missing {section}.{key}")
    for path, payload in artifacts[1:]:
        current = dict(payload.get(section) or {})
        for key in keys:
            if current.get(key) != first[key]:
                raise ValueError(
                    f"{path}: {section}.{key} does not match "
                    f"{first_path}"
                )
    return first


def merge_locomo_artifacts(paths: Iterable[str | Path]) -> dict[str, Any]:
    resolved = [Path(path) for path in paths]
    if not resolved:
        raise ValueError("at least one artifact is required")
    artifacts = [(path, _load(path)) for path in resolved]
    scenario = _require_equal(
        artifacts,
        section="scenario",
        keys=SCENARIO_KEYS,
    )
    source_shas = {str(payload.get("source_sha") or "") for _, payload in artifacts}
    if len(source_shas) != 1:
        raise ValueError("all artifacts must use the same source_sha")
    source_sha = source_shas.pop()
    if len(source_sha) != 40 or source_sha == "unknown":
        raise ValueError("source_sha must be an exact 40-character commit")

    results: dict[str, dict[str, Any]] = {}
    source_artifacts: list[str] = []
    for path, payload in artifacts:
        protocol = dict(payload.get("comparison_protocol") or {})
        for key in ("same_memories", "same_queries", "same_top_k"):
            if protocol.get(key) is not True:
                raise ValueError(f"{path}: comparison_protocol.{key} must be true")
        if protocol.get("evidence_mapping") != (
            "source provenance only; no text matching"
        ):
            raise ValueError(f"{path}: evidence mapping is not provenance-only")
        source_artifacts.append(path.name)
        for row in payload.get("results") or []:
            engine = str(row.get("engine") or "")
            if not engine:
                raise ValueError(f"{path}: result is missing engine")
            if engine in results:
                raise ValueError(f"duplicate engine: {engine}")
            results[engine] = dict(row)

    missing = [engine for engine in REQUIRED_ENGINES if engine not in results]
    if missing:
        raise ValueError(f"missing required engines: {', '.join(missing)}")
    for engine in EXTERNAL_ENGINES:
        row = results[engine]
        if str(row.get("system_version") or "") in {"", "unknown"}:
            raise ValueError(f"{engine}: exact system_version is required")
        if not str(row.get("embedding_profile") or ""):
            raise ValueError(f"{engine}: embedding_profile is required")
        if not str(row.get("provenance_mode") or ""):
            raise ValueError(f"{engine}: provenance_mode is required")

    ordered = [results[engine] for engine in REQUIRED_ENGINES]
    quality_winner = max(
        ordered,
        key=lambda row: float(row["evidence_recall_at_k"]),
    )
    latency_winner = min(
        ordered,
        key=lambda row: float(row["avg_latency_ms"]),
    )
    return {
        "schema": "wavemind.public_memory_competitors.v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source_sha": source_sha,
        "scenario": scenario,
        "protocol": {
            "same_dataset": True,
            "same_memories": True,
            "same_queries": True,
            "same_top_k": True,
            "evidence_mapping": "source provenance only; no text matching",
            "external_inference": False,
            "external_native_embeddings": True,
            "internal_embedding": (
                "sentence-transformers/"
                "paraphrase-multilingual-mpnet-base-v2"
            ),
            "ingest_scope_boundary": (
                "WaveMind, Chroma, and Qdrant ingest starts from shared "
                "precomputed embeddings. Mem0 and Hindsight ingest includes "
                "their native embedding and persistence work."
            ),
        },
        "results": ordered,
        "summary": {
            "quality_winner": quality_winner["engine"],
            "quality_winner_recall_at_k": quality_winner[
                "evidence_recall_at_k"
            ],
            "query_latency_winner": latency_winner["engine"],
            "query_latency_winner_avg_ms": latency_winner["avg_latency_ms"],
        },
        "source_artifacts": sorted(source_artifacts),
        "claim_boundary": (
            "This is LoCoMo retrieval evidence on one local machine. It is "
            "not final answer quality, hosted-service throughput, or an "
            "architecture-only comparison because real systems use their "
            "pinned native embedding stacks."
        ),
    }


def render_markdown(payload: dict[str, Any]) -> str:
    scenario = payload["scenario"]
    top_k = int(scenario["top_k"])
    lines = [
        "# Public Memory Competitors",
        "",
        (
            f"Official LoCoMo: **{scenario['memories']:,} memories**, "
            f"**{scenario['queries']:,} evidence queries**, "
            f"top-{top_k}."
        ),
        "",
        (
            f"| Engine | Recall@{top_k} | Precision@1 | MRR@{top_k} | "
            "Query avg | Query p95 | Ingest avg | Ingest scope |"
        ),
        "|---|---:|---:|---:|---:|---:|---:|---|",
    ]
    for row in payload["results"]:
        lines.append(
            f"| {row['engine']} | "
            f"{float(row['evidence_recall_at_k']):.3f} | "
            f"{float(row['precision_at_1']):.3f} | "
            f"{float(row['mrr_at_k']):.3f} | "
            f"{float(row['avg_latency_ms']):.2f} ms | "
            f"{float(row['p95_latency_ms']):.2f} ms | "
            f"{float(row.get('ingest_avg_ms') or 0.0):.2f} ms | "
            f"{row.get('ingest_scope') or 'not recorded'} |"
        )
    lines.extend(
        [
            "",
            "## Verdict",
            "",
            (
                f"- Quality winner: **{payload['summary']['quality_winner']}** "
                f"at recall@{top_k} "
                f"`{payload['summary']['quality_winner_recall_at_k']:.3f}`."
            ),
            (
                "- Fastest average local query: "
                f"**{payload['summary']['query_latency_winner']}** at "
                f"`{payload['summary']['query_latency_winner_avg_ms']:.2f} ms`."
            ),
            "",
            "## Boundaries",
            "",
            f"- {payload['protocol']['ingest_scope_boundary']}",
            f"- {payload['claim_boundary']}",
            f"- Source commit: `{payload['source_sha']}`.",
            f"- Dataset SHA-256: `{scenario['dataset_sha256']}`.",
            "",
        ]
    )
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--artifacts", nargs="+", type=Path, required=True)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path(
            "benchmarks/locomo_public_memory_competitors_results.json"
        ),
    )
    parser.add_argument(
        "--markdown-output",
        type=Path,
        default=Path("benchmarks/PUBLIC_MEMORY_COMPETITORS.md"),
    )
    args = parser.parse_args()
    payload = merge_locomo_artifacts(args.artifacts)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    args.markdown_output.parent.mkdir(parents=True, exist_ok=True)
    args.markdown_output.write_text(
        render_markdown(payload),
        encoding="utf-8",
    )
    print(render_markdown(payload))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

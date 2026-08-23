from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path

from wavemind.scientific_development_evidence import build_development_evidence


GRAPH = "evidence-constrained-associative-graph-v1"
CAUSAL = "causal-utility-controller-v1"


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> int:
    parser = argparse.ArgumentParser(description="Build bounded development decision.")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    source_sha = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=root, text=True, encoding="utf-8"
    ).strip()
    payload = build_development_evidence(
        source_sha=source_sha,
        protocol=_load(root / "benchmarks" / "scientific_memory_protocol_v1.json"),
        mab_artifacts={
            GRAPH: _load(
                root
                / "benchmarks"
                / "scientific_memoryagentbench_graph_multicluster_dev_results.json"
            ),
            CAUSAL: _load(
                root
                / "benchmarks"
                / "scientific_memoryagentbench_causal_multicluster_dev_results.json"
            ),
        },
        mab_raw_paths={
            GRAPH: root
            / "benchmarks"
            / "scientific_memoryagentbench_graph_multicluster_dev_raw.jsonl",
            CAUSAL: root
            / "benchmarks"
            / "scientific_memoryagentbench_causal_multicluster_dev_raw.jsonl",
        },
        memops_artifacts={
            GRAPH: _load(
                root
                / "benchmarks"
                / "scientific_memops_graph_candidate_dev_results.json"
            ),
            CAUSAL: _load(
                root / "benchmarks" / "scientific_memops_candidate_dev_results.json"
            ),
        },
        state_bench_artifact=_load(
            root / "benchmarks" / "scientific_state_bench_prepared_dev_results.json"
        ),
    )
    if args.output.exists():
        raise FileExistsError(f"development evidence is retained: {args.output}")
    args.output.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(payload, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

from __future__ import annotations

import json
from pathlib import Path

from wavemind.scientific_development_gate_v6 import build_v6_development_gate


ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    benchmarks = ROOT / "benchmarks"
    payload = build_v6_development_gate(
        project_root=ROOT,
        candidate_sha="a8240fe6bd9a79aec3d524b1cbbbdb4b907f8d97",
        protocol_path=benchmarks / "scientific_memory_protocol_v6.json",
        mab_runs=tuple(
            (
                benchmarks / f"scientific_memoryagentbench_v6_accurate_run{run}_results.json",
                benchmarks / f"scientific_memoryagentbench_v6_accurate_run{run}_raw.jsonl",
            )
            for run in (1, 2, 3)
        ),
        memops_runs=tuple(
            (
                benchmarks / f"scientific_memops_v6_allops_run{run}_results.json",
                benchmarks / f"scientific_memops_v6_allops_run{run}_raw.jsonl",
            )
            for run in (1, 2, 3)
        ),
        retained_failed_attempts=(
            benchmarks / "SCIENTIFIC_MEMORY_V5_OUTCOME.md",
            benchmarks / "scientific_memops_v6_invalid_max20_raw.jsonl",
        ),
    )
    output = benchmarks / "scientific_development_gate_v6_results.json"
    output.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(payload, indent=2, ensure_ascii=False))
    return int(not payload["development_gate_passed"])


if __name__ == "__main__":
    raise SystemExit(main())

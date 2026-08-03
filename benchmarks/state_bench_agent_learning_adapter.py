from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Sequence

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from wavemind.integrations.state_bench import build_state_bench_adapter_artifact


def _repository_sha(root: Path) -> str:
    return subprocess.check_output(
        ["git", "rev-parse", "HEAD"],
        cwd=root,
        text=True,
        encoding="utf-8",
    ).strip()


def _upstream_sha(training_root: Path) -> str | None:
    try:
        return subprocess.check_output(
            ["git", "-C", str(training_root), "rev-parse", "HEAD"],
            text=True,
            encoding="utf-8",
            stderr=subprocess.DEVNULL,
        ).strip()
    except (OSError, subprocess.CalledProcessError):
        return None


def render_markdown(payload: dict) -> str:
    protocol = payload["official_protocol"]
    training = payload["training_data"]
    counts = training["file_counts"]
    return "\n".join(
        [
            "# STATE-Bench Agent Learning Adapter",
            "",
            f"Status: **{payload['status']}**",
            "",
            f"Source SHA: `{payload['source_sha']}`",
            "",
            "## Protocol",
            "",
            f"- Domains: {', '.join(protocol['domains'])}",
            f"- Train trajectories: {counts}",
            f"- Held-out tasks per domain: {protocol['held_out_tasks_per_domain']}",
            f"- Repeats: {protocol['repeats']}",
            f"- Retrieval top-k: {protocol['top_k']}",
            "- Retrieval is read-only during evaluation.",
            "- The official paid model run was not performed.",
            "",
            payload["claim_boundary"],
            "",
        ]
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Validate and package WaveMind STATE-Bench interoperability"
    )
    parser.add_argument("training_root", type=Path)
    parser.add_argument("--source-sha")
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("benchmarks/state_bench_agent_learning_adapter_results.json"),
    )
    parser.add_argument(
        "--markdown",
        type=Path,
        default=Path("benchmarks/STATE_BENCH_AGENT_LEARNING_ADAPTER.md"),
    )
    args = parser.parse_args(argv)
    payload = build_state_bench_adapter_artifact(
        training_root=args.training_root,
        source_sha=args.source_sha or _repository_sha(PROJECT_ROOT),
        upstream_sha=_upstream_sha(args.training_root),
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(payload, indent=2, ensure_ascii=True) + "\n",
        encoding="utf-8",
    )
    args.markdown.write_text(render_markdown(payload), encoding="utf-8")
    print(
        json.dumps(
            {"status": payload["status"], "training_data": payload["training_data"]},
            indent=2,
        )
    )
    return 0 if payload["status"] == "runner_ready" else 2


if __name__ == "__main__":
    raise SystemExit(main())

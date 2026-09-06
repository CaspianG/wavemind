from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from state_bench.agents.base import AgentRuntimeContext
from state_bench.agents.loader import load_root_agent_class
from state_bench.client import LLMClient


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Preflight the official STATE-Bench scientific retrieval hook."
    )
    parser.add_argument("--project-root", type=Path, required=True)
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--domain", required=True)
    args = parser.parse_args()

    os.environ["STATE_BENCH_AGENT_PROVIDER"] = "openai"
    os.environ["STATE_BENCH_AGENT_MODEL"] = "gpt-5.4"
    os.environ["WAVEMIND_STATE_BENCH_SCIENTIFIC_DB"] = str(args.database.resolve())
    os.environ["WAVEMIND_STATE_BENCH_DOMAIN"] = args.domain
    os.environ["WAVEMIND_STATE_BENCH_PHASE"] = "bounded-development-shadow"
    context = AgentRuntimeContext(
        task_id="bounded-development-adapter-preflight",
        user_id="adapter-preflight",
        domain=args.domain,
        now="2026-08-23T00:00:00Z",
    )
    client = object.__new__(LLMClient)
    treatment_class = load_root_agent_class(
        "ScientificStateBenchAgent",
        root=args.project_root.resolve(),
    )
    control_class = load_root_agent_class(
        "ScientificStateBenchNoMemoryControlAgent",
        root=args.project_root.resolve(),
    )
    common = {
        "client": client,
        "system_prompt": "official-preflight-placeholder",
        "tools": [],
        "tool_handlers": {},
        "runtime_context": context,
        "retrieve_learnings_top_k": 3,
    }
    treatment = treatment_class(**common)
    shadow = treatment.retrieve_learnings(
        "check policy, compare options, and confirm before a state change",
        top_k=3,
    )
    treatment._scientific_finalizer()
    control = control_class(**common)
    empty = control.retrieve_learnings(
        "check policy, compare options, and confirm before a state change",
        top_k=3,
    )
    os.environ["WAVEMIND_STATE_BENCH_PHASE"] = "production"
    production = treatment_class(**common)
    abstained = production.retrieve_learnings(
        "check policy, compare options, and confirm before a state change",
        top_k=3,
    )
    production._scientific_finalizer()
    payload = {
        "shadow_count": len(shadow),
        "control_count": len(empty),
        "production_count": len(abstained),
        "common_retrieval_tool": bool(
            treatment.retrieval_enabled and control.retrieval_enabled
        ),
        "llm_or_official_task_executed": False,
    }
    expected = {
        "shadow_count": 3,
        "control_count": 0,
        "production_count": 0,
        "common_retrieval_tool": True,
        "llm_or_official_task_executed": False,
    }
    if payload != expected:
        raise RuntimeError(f"STATE-Bench adapter preflight failed: {payload}")
    print(json.dumps(payload, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

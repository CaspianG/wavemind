from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

STATE_BENCH_SHA = "5644b1838d96bc4483da29642d058ecaa6f80f7f"
MODEL_NAME = "qwen3:0.6b"
MODEL_MANIFEST_DIGEST = "7df6b6e09427"
MODEL_WEIGHT_SHA256 = "7f4030143c1c477224c5434f8272c662a8b042079a0a584f0a27a1684fe2e1fa"
SEEDS = (101, 211, 307, 401, 503)
TREATMENTS = ("no-memory", "wavemind-core", "wavemind-memory-os")
PROTOCOL_PATH = Path("benchmarks/state_bench_workflow_development_protocol_v1.json")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _payload_sha256(payload: dict[str, Any]) -> str:
    body = {key: value for key, value in payload.items() if key != "integrity"}
    encoded = json.dumps(
        body, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _git_sha(root: Path) -> str:
    return subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=root, text=True
    ).strip()


def build_protocol(repo_root: Path, upstream_root: Path) -> dict[str, Any]:
    upstream_sha = _git_sha(upstream_root)
    if upstream_sha != STATE_BENCH_SHA:
        raise ValueError(
            f"STATE-Bench checkout must be {STATE_BENCH_SHA}, got {upstream_sha}"
        )

    development = json.loads(
        (repo_root / "benchmarks/evaluation_development_protocol_v2.json").read_text(
            encoding="utf-8"
        )
    )
    units = [
        unit
        for unit in development["bounded_sample"]["units"]
        if unit["dataset"] == "state-bench"
    ]
    if len(units) != 15:
        raise ValueError(f"expected 15 frozen STATE-Bench development units, got {len(units)}")

    rows: list[dict[str, Any]] = []
    for unit in units:
        _, domain, task_id = unit["unit_id"].split(":", 2)
        task_path = upstream_root / "state_bench" / "domains" / domain / "tasks" / f"{task_id}.json"
        trajectory_path = (
            upstream_root
            / "datasets"
            / "train_task_trajectories"
            / domain
            / f"{task_id}.json"
        )
        task = json.loads(task_path.read_text(encoding="utf-8"))
        env_path = upstream_root / task["task_env_path"]
        if not env_path.is_file() or not trajectory_path.is_file():
            raise ValueError(f"missing official development inputs for {unit['unit_id']}")
        rows.append(
            {
                "unit_id": unit["unit_id"],
                "domain": domain,
                "task_id": task_id,
                "cluster_id": unit["cluster_id"],
                "split": "development",
                "task_sha256": _sha256(task_path),
                "environment_sha256": _sha256(env_path),
                "training_trajectory_sha256": _sha256(trajectory_path),
                "has_state_requirements": bool(task.get("state_requirements")),
            }
        )

    payload: dict[str, Any] = {
        "schema": "wavemind.state_bench_workflow_development_protocol.v1",
        "phase": "bounded_development_only",
        "protocol_parent_sha": _git_sha(repo_root),
        "official_source": {
            "repository": "https://github.com/microsoft/STATE-Bench",
            "revision": STATE_BENCH_SHA,
            "license": "MIT",
            "official_agent_learning_result": False,
        },
        "access_policy": {
            "allowed": ["datasets/train_task_trajectories", "frozen development tasks and task environments"],
            "forbidden": ["validation rows", "official test/final tasks", "held-out result inspection"],
            "backend_forbidden_fields": [
                "task_id",
                "state_requirements",
                "task_requirements",
                "expected outcome",
                "split",
                "evaluator metadata",
            ],
        },
        "execution_profile": {
            "kind": "local_official-compatible_development",
            "model": MODEL_NAME,
            "model_manifest_digest": MODEL_MANIFEST_DIGEST,
            "model_weight_sha256": MODEL_WEIGHT_SHA256,
            "ollama_min_version": "0.31.1",
            "cpu_only": True,
            "num_gpu": 0,
            "temperature": 0.0,
            "think": False,
            "context_window": 8192,
            "max_output_tokens": 1024,
            "seeds": list(SEEDS),
            "same_model_for_agent_and_simulator": True,
            "ux_judge": "disabled_no_pinned_calibration",
        },
        "treatments": [
            {
                "id": "no-memory",
                "description": "Identical local agent with no learning retrieval surface.",
            },
            {
                "id": "wavemind-core",
                "description": "Identical local agent with read-only WaveMind Core retrieval from the frozen training corpus.",
            },
            {
                "id": "wavemind-memory-os",
                "description": "Identical local agent with read-only verified Experience Packet retrieval; unverified trajectory text cannot be promoted.",
            },
        ],
        "primary_metrics": {
            "deterministic_state_pass_at_1": "mean state assertion pass across five paired seeds",
            "deterministic_state_pass_power_5": "fraction of tasks passing deterministic state assertions on all five seeds",
            "paired_task_ci": "paired cluster bootstrap by task with 95% confidence",
        },
        "secondary_metrics": [
            "turns",
            "tool_calls",
            "tool_errors",
            "repeated_tool_calls",
            "context_tokens",
            "output_tokens",
            "latency_ms",
            "cost_proxy",
        ],
        "claim_boundary": (
            "This lane measures deterministic final-state workflow behavior on frozen development rows "
            "with a local open-weight model. It is not an official STATE-Bench result, does not score UX, "
            "and does not establish held-out generalization. No-state tasks are safety diagnostics and do "
            "not substitute for task-content judging."
        ),
        "preregistered_hypothesis": {
            "id": "verified-correction-guidance-v1",
            "statement": (
                "On tasks whose training corpus contains independently admissible correction evidence, "
                "a minimal verified Experience Packet will reduce repeated policy/workflow errors without "
                "increasing forbidden writes. Raw TASK_DONE text is not verification evidence."
            ),
            "affected_metrics": [
                "deterministic_state_pass_at_1",
                "deterministic_state_pass_power_5",
                "tool_errors",
                "repeated_tool_calls",
            ],
            "development_gate": {
                "memory_os_minus_strongest_baseline_pass_at_1": 0.01,
                "lower_95_ci_above": 0.0,
                "forbidden_write_regressions": 0,
                "namespace_leakage": 0,
            },
        },
        "rows": rows,
    }
    payload["integrity"] = {
        "algorithm": "sha256",
        "payload_sha256": _payload_sha256(payload),
    }
    return payload


@dataclass(frozen=True)
class OllamaProfile:
    model: str = MODEL_NAME
    endpoint: str = "http://127.0.0.1:11434/api/chat"
    seed: int = SEEDS[0]
    timeout_seconds: int = 180


class OllamaChatClient:
    def __init__(self, profile: OllamaProfile) -> None:
        self.profile = profile

    def _request(
        self,
        *,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": self.profile.model,
            "stream": False,
            "think": False,
            "messages": messages,
            "options": {
                "num_gpu": 0,
                "temperature": 0,
                "seed": self.profile.seed,
                "num_ctx": 8192,
                "num_predict": 1024,
            },
        }
        if tools:
            payload["tools"] = tools
        request = urllib.request.Request(
            self.profile.endpoint,
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.profile.timeout_seconds) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.URLError as exc:
            raise RuntimeError(f"Ollama request failed: {exc}") from exc

    def complete_chat(
        self,
        messages: list[dict[str, str]],
        max_tokens: int = 1024,
        temperature: float | None = None,
    ) -> str:
        del max_tokens, temperature
        response = self._request(messages=list(messages))
        return str(response.get("message", {}).get("content", ""))


def _ollama_tools(tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
    converted = []
    for tool in tools:
        converted.append(
            {
                "type": "function",
                "function": {
                    "name": tool["name"],
                    "description": tool.get("description", ""),
                    "parameters": tool.get("parameters", {"type": "object"}),
                },
            }
        )
    return converted


def _ollama_messages(
    system_prompt: str, conversation: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    messages: list[dict[str, Any]] = [{"role": "system", "content": system_prompt}]
    for message in conversation:
        role = message.get("role")
        if role == "tool":
            for call in message.get("content") or []:
                messages.append(
                    {
                        "role": "tool",
                        "tool_name": call["name"],
                        "content": json.dumps(call.get("result"), ensure_ascii=False),
                    }
                )
            continue
        converted: dict[str, Any] = {
            "role": role,
            "content": str(message.get("content", "") or ""),
        }
        calls = message.get("tool_calls") or []
        if calls:
            converted["tool_calls"] = [
                {
                    "type": "function",
                    "function": {
                        "name": call["name"],
                        "arguments": call.get("arguments", {}),
                    },
                }
                for call in calls
            ]
        messages.append(converted)
    return messages


def run_preflight(
    *, repo_root: Path, upstream_root: Path, task_id: str, domain_name: str, seed: int
) -> dict[str, Any]:
    sys.path.insert(0, str(upstream_root))
    from state_bench.agents.base import (
        AgentToolCallRequest,
        AgentTurnResponse,
        BaseAgent,
    )
    from state_bench.domain import get_domain_config
    from state_bench.env_loader import load_task_environment
    from state_bench.orchestrator import run_task
    from state_bench.schemas import TaskDefinition
    from state_bench.scoring import evaluate_state_requirements

    class LocalAgent(BaseAgent):
        def __init__(self, client: OllamaChatClient, runtime_context: Any = None) -> None:
            super().__init__(runtime_context=runtime_context)
            self.client = client

        def generate_next_turn(
            self,
            *,
            system_prompt: str,
            conversation: list[dict[str, Any]],
            tools: list[dict[str, Any]],
        ) -> Any:
            response = self.client._request(
                messages=_ollama_messages(system_prompt, conversation),
                tools=_ollama_tools(tools),
            )
            self.add_token_usage(
                input_tokens=int(response.get("prompt_eval_count", 0) or 0),
                output_tokens=int(response.get("eval_count", 0) or 0),
            )
            message = response.get("message", {})
            calls = []
            for call in message.get("tool_calls") or []:
                function = call.get("function", {})
                calls.append(
                    AgentToolCallRequest(
                        name=str(function.get("name", "")),
                        arguments=dict(function.get("arguments") or {}),
                    )
                )
            return AgentTurnResponse(
                text=str(message.get("content", "") or ""), tool_calls=calls
            )

    protocol = json.loads((repo_root / PROTOCOL_PATH).read_text(encoding="utf-8"))
    allowed = {(row["domain"], row["task_id"]) for row in protocol["rows"]}
    if (domain_name, task_id) not in allowed:
        raise ValueError("preflight task is not in the frozen development split")

    domain = get_domain_config(domain_name)
    task_path = upstream_root / "state_bench" / "domains" / domain_name / "tasks" / f"{task_id}.json"
    task = TaskDefinition.load(task_path)
    env_data, _ = load_task_environment(domain, task)
    client = OllamaChatClient(OllamaProfile(seed=seed))
    agent = LocalAgent(client)
    started = time.perf_counter()
    trajectory = run_task(
        task=task,
        env_data=env_data,
        user_id=task.user_id,
        client=None,
        simulator_client=client,
        domain=domain,
        agent=agent,
        trajectory_metadata={
            "lane": "local_task_native_development_preflight",
            "treatment": "no-memory",
            "seed": seed,
        },
    )
    elapsed_ms = (time.perf_counter() - started) * 1000.0
    state_score = evaluate_state_requirements(task, trajectory.state_diff)
    tool_calls = [
        call
        for message in trajectory.conversation
        for call in (message.get("tool_calls") or [])
    ]
    return {
        "schema": "wavemind.state_bench_workflow_preflight.v1",
        "status": "passed" if state_score is not None and tool_calls else "blocked",
        "source_sha": _git_sha(repo_root),
        "protocol_payload_sha256": protocol["integrity"]["payload_sha256"],
        "upstream_sha": _git_sha(upstream_root),
        "model": MODEL_NAME,
        "model_weight_sha256": MODEL_WEIGHT_SHA256,
        "cpu_only": True,
        "domain": domain_name,
        "task_id": task_id,
        "seed": seed,
        "state_requirements_met": state_score.score if state_score else None,
        "state_reasoning": state_score.reasoning if state_score else None,
        "turns": trajectory.efficiency.turns,
        "tool_calls": len(tool_calls),
        "tool_errors": trajectory.efficiency.tool_errors,
        "repeated_calls": trajectory.efficiency.redundant_calls,
        "input_tokens": trajectory.token_usage.input_tokens,
        "output_tokens": trajectory.token_usage.output_tokens,
        "elapsed_ms": round(elapsed_ms, 3),
        "claim_boundary": "Execution plumbing preflight only; not a baseline, candidate, or official result.",
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", type=Path, default=Path.cwd())
    parser.add_argument("--upstream-root", type=Path, required=True)
    parser.add_argument("--write-protocol", action="store_true")
    parser.add_argument("--preflight", action="store_true")
    parser.add_argument("--domain", default="shopping_assistant")
    parser.add_argument("--task-id", default="125-hard_promo_expired_code_no_replacement")
    parser.add_argument("--seed", type=int, default=SEEDS[0])
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("benchmarks/state_bench_workflow_preflight_results.json"),
    )
    args = parser.parse_args()
    repo_root = args.repo_root.resolve()
    upstream_root = args.upstream_root.resolve()
    if args.write_protocol:
        payload = build_protocol(repo_root, upstream_root)
        path = repo_root / PROTOCOL_PATH
        path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        print(json.dumps({"status": "written", "path": str(path), "rows": len(payload["rows"])}))
    if args.preflight:
        result = run_preflight(
            repo_root=repo_root,
            upstream_root=upstream_root,
            task_id=args.task_id,
            domain_name=args.domain,
            seed=args.seed,
        )
        output = repo_root / args.output
        output.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        print(
            json.dumps(
                {
                    "status": result["status"],
                    "output": str(output),
                    "state_requirements_met": result["state_requirements_met"],
                    "tool_calls": result["tool_calls"],
                    "elapsed_ms": result["elapsed_ms"],
                }
            )
        )
        if result["status"] != "passed":
            raise SystemExit(1)


if __name__ == "__main__":
    main()

from __future__ import annotations

import argparse
import hashlib
import json
import random
import statistics
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


def _training_text(payload: dict[str, Any]) -> str:
    messages = payload.get("conversation") or []
    excerpts = []
    for message in messages:
        if message.get("role") not in {"user", "assistant"}:
            continue
        content = str(message.get("content", "") or "").strip()
        if content:
            excerpts.append(f"{message['role']}: {content}")
    return "\n".join(excerpts)


def _prepare_core_store(
    *, repo_root: Path, upstream_root: Path, protocol: dict[str, Any], store_path: Path
) -> dict[str, int]:
    from wavemind import WaveMind

    excluded = {(row["domain"], row["task_id"]) for row in protocol["rows"]}
    if store_path.exists():
        store_path.unlink()
    mind = WaveMind(
        db_path=store_path,
        width=16,
        height=16,
        layers=2,
        evolve_on_feed=0,
        field_weight=0.0,
        priority_weight=0.0,
        lexical_weight=0.20,
        short_query_lexical_weight=2.0,
        confidence_gate=True,
    )
    counts: dict[str, int] = {}
    try:
        for domain in ("travel", "customer_support", "shopping_assistant"):
            source = upstream_root / "datasets" / "train_task_trajectories" / domain
            items = []
            for path in sorted(source.glob("*.json")):
                if (domain, path.stem) in excluded:
                    continue
                payload = json.loads(path.read_text(encoding="utf-8"))
                text = _training_text(payload)
                if not text:
                    continue
                items.append(
                    {
                        "text": text,
                        "namespace": f"state-bench/{domain}",
                        "tags": ("state-bench", "raw-training-trajectory"),
                        "metadata": {
                            "domain": domain,
                            "source": "official-train-trajectory",
                            "source_sha256": _sha256(path),
                            "verification_status": "unverified",
                        },
                    }
                )
            mind.remember_batch(items)
            counts[domain] = len(items)
    finally:
        mind.store.close()
    if sum(counts.values()) != 285:
        raise RuntimeError(f"expected 285 non-evaluation training trajectories, got {counts}")
    return counts


def _core_retriever(store_path: Path, domain: str):
    from wavemind import WaveMind

    mind = WaveMind(
        db_path=store_path,
        width=16,
        height=16,
        layers=2,
        evolve_on_feed=0,
        field_weight=0.0,
        priority_weight=0.0,
        lexical_weight=0.20,
        short_query_lexical_weight=2.0,
        confidence_gate=True,
    )

    def retrieve(query: str, top_k: int) -> list[str]:
        return [
            result.text
            for result in mind.query(
                query,
                namespace=f"state-bench/{domain}",
                top_k=top_k,
            )
        ]

    return retrieve, mind.store.close


def _empty_memory_os_retriever(store_path: Path, domain: str):
    from wavemind import (
        AgentExperienceRuntime,
        AgentExperienceRuntimePolicy,
        ExperienceCompiler,
        ExperienceCompilerPolicy,
        MemoryFirewall,
        MemoryFirewallPolicy,
        SQLiteExperienceStore,
    )
    from wavemind.integrations.state_bench import WaveMindStateBenchLearningAdapter

    namespace = f"state-bench/{domain}"
    store = SQLiteExperienceStore(store_path)
    compiler = ExperienceCompiler(
        store,
        MemoryFirewall(
            MemoryFirewallPolicy(
                namespace=namespace,
                allow_canary_retrieval=False,
                require_consent_for_user_data=False,
            )
        ),
        policy=ExperienceCompilerPolicy(),
    )
    runtime = AgentExperienceRuntime(
        compiler,
        policy=AgentExperienceRuntimePolicy(
            intervention_score_threshold=0.0,
            default_packet_tokens=600,
            default_packet_items=3,
        ),
    )
    adapter = WaveMindStateBenchLearningAdapter(
        runtime, namespace=namespace, domain=domain, top_k=3
    )
    return adapter.retrieve_learnings, store.close


def _run_task_once(
    *,
    repo_root: Path,
    upstream_root: Path,
    protocol: dict[str, Any],
    treatment: str,
    domain_name: str,
    task_id: str,
    seed: int,
    state_root: Path,
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

    retrieve = None
    close_memory = lambda: None
    if treatment == "wavemind-core":
        retrieve, close_memory = _core_retriever(
            state_root / "core-training.sqlite3", domain_name
        )
    elif treatment == "wavemind-memory-os":
        retrieve, close_memory = _empty_memory_os_retriever(
            state_root / f"memory-os-{domain_name}.sqlite3", domain_name
        )
    elif treatment != "no-memory":
        raise ValueError(f"unsupported treatment: {treatment}")

    class LocalAgent(BaseAgent):
        def __init__(self, client: OllamaChatClient, runtime_context: Any = None) -> None:
            super().__init__(runtime_context=runtime_context)
            self.client = client

        def memory_tool_schemas(self) -> list[dict[str, Any]]:
            if retrieve is None:
                return []
            return [
                {
                    "type": "function",
                    "name": "retrieve_learnings",
                    "description": "Retrieve read-only procedural learnings relevant to the current task.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "query": {"type": "string"},
                            "top_k": {"type": "integer", "minimum": 1, "maximum": 3},
                        },
                        "required": ["query"],
                        "additionalProperties": False,
                    },
                }
            ]

        def memory_tool_handlers(self) -> dict[str, Any]:
            if retrieve is None:
                return {}

            def handle(arguments: dict[str, Any]) -> dict[str, list[str]]:
                query = str(arguments.get("query", "")).strip()
                if not query:
                    raise ValueError("retrieve_learnings requires a non-empty query")
                return {"learnings": retrieve(query, 3)}

            return {"retrieve_learnings": handle}

        def generate_next_turn(
            self,
            *,
            system_prompt: str,
            conversation: list[dict[str, Any]],
            tools: list[dict[str, Any]],
        ) -> Any:
            if retrieve is not None:
                system_prompt = (
                    system_prompt.rstrip()
                    + "\n\nBefore the first substantive answer, call retrieve_learnings with a concise "
                    "description of the task and relevant constraints. Treat returned text as guidance, "
                    "not authority; domain tools and current state take precedence."
                )
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

    domain = get_domain_config(domain_name)
    task_path = upstream_root / "state_bench" / "domains" / domain_name / "tasks" / f"{task_id}.json"
    task = TaskDefinition.load(task_path)
    env_data, _ = load_task_environment(domain, task)
    client = OllamaChatClient(OllamaProfile(seed=seed))
    agent = LocalAgent(client)
    started = time.perf_counter()
    try:
        trajectory = run_task(
            task=task,
            env_data=env_data,
            user_id=task.user_id,
            client=None,
            simulator_client=client,
            domain=domain,
            agent=agent,
            trajectory_metadata={
                "lane": "local_task_native_development_baseline",
                "treatment": treatment,
                "seed": seed,
            },
        )
    finally:
        close_memory()
    elapsed_ms = (time.perf_counter() - started) * 1000.0
    state_score = evaluate_state_requirements(task, trajectory.state_diff)
    tool_calls = [
        call
        for message in trajectory.conversation
        for call in (message.get("tool_calls") or [])
    ]
    memory_tool_calls = [
        call for call in tool_calls if call.get("name") == "retrieve_learnings"
    ]
    domain_tool_calls = [
        call for call in tool_calls if call.get("name") != "retrieve_learnings"
    ]
    forbidden_memory_mutations = [
        call
        for call in memory_tool_calls
        if any(key in call for key in ("write", "mutation"))
    ]
    return {
        "unit_id": f"state-bench:{domain_name}:{task_id}",
        "domain": domain_name,
        "task_id": task_id,
        "treatment": treatment,
        "seed": seed,
        "status": "completed",
        "state_pass": int(state_score.score if state_score else 0),
        "has_state_requirements": bool(task.state_requirements),
        "state_reasoning": state_score.reasoning if state_score else None,
        "turns": trajectory.efficiency.turns,
        "tool_calls": len(tool_calls),
        "memory_tool_calls": len(memory_tool_calls),
        "domain_tool_calls": len(domain_tool_calls),
        "domain_tool_names": [str(call.get("name")) for call in domain_tool_calls],
        "tool_errors": trajectory.efficiency.tool_errors,
        "repeated_calls": trajectory.efficiency.redundant_calls,
        "input_tokens": trajectory.token_usage.input_tokens,
        "output_tokens": trajectory.token_usage.output_tokens,
        "latency_ms": round(elapsed_ms, 3),
        "cost_proxy": 0.0,
        "forbidden_memory_mutations": len(forbidden_memory_mutations),
    }


def _percentile(values: list[float], probability: float) -> float:
    ordered = sorted(values)
    if not ordered:
        return 0.0
    position = (len(ordered) - 1) * probability
    lower = int(position)
    upper = min(len(ordered) - 1, lower + 1)
    fraction = position - lower
    return ordered[lower] + (ordered[upper] - ordered[lower]) * fraction


def _paired_task_ci(
    rows: list[dict[str, Any]], treatment: str, baseline: str, *, samples: int = 10000
) -> dict[str, float]:
    primary_rows = [row for row in rows if row["has_state_requirements"]]
    tasks = sorted({row["unit_id"] for row in primary_rows})
    deltas = []
    for task in tasks:
        treatment_values = [
            row["state_pass"]
            for row in primary_rows
            if row["unit_id"] == task and row["treatment"] == treatment
        ]
        baseline_values = [
            row["state_pass"]
            for row in primary_rows
            if row["unit_id"] == task and row["treatment"] == baseline
        ]
        if len(treatment_values) != len(SEEDS) or len(baseline_values) != len(SEEDS):
            raise ValueError(f"incomplete paired rows for {task}")
        deltas.append(statistics.fmean(treatment_values) - statistics.fmean(baseline_values))
    rng = random.Random(20260812)
    boot = [
        statistics.fmean(rng.choice(deltas) for _ in deltas)
        for _ in range(samples)
    ]
    return {
        "mean": round(statistics.fmean(deltas), 6),
        "low": round(_percentile(boot, 0.025), 6),
        "high": round(_percentile(boot, 0.975), 6),
        "cluster_count": len(deltas),
        "bootstrap_samples": samples,
    }


def _aggregate_baseline(
    *, repo_root: Path, protocol: dict[str, Any], rows: list[dict[str, Any]]
) -> dict[str, Any]:
    expected = len(protocol["rows"]) * len(SEEDS) * len(TREATMENTS)
    completed = [row for row in rows if row.get("status") == "completed"]
    if len(completed) != expected:
        raise ValueError(f"expected {expected} completed rows, got {len(completed)}")
    treatment_metrics: dict[str, Any] = {}
    for treatment in TREATMENTS:
        selected = [row for row in completed if row["treatment"] == treatment]
        primary = [row for row in selected if row["has_state_requirements"]]
        task_ids = sorted({row["unit_id"] for row in primary})
        treatment_metrics[treatment] = {
            "primary_state_task_count": len(task_ids),
            "diagnostic_no_state_task_count": len(
                {row["unit_id"] for row in selected if not row["has_state_requirements"]}
            ),
            "state_pass_at_1": round(statistics.fmean(row["state_pass"] for row in primary), 6),
            "state_pass_power_5": round(
                statistics.fmean(
                    int(
                        all(
                            row["state_pass"] == 1
                            for row in primary
                            if row["unit_id"] == task_id
                        )
                    )
                    for task_id in task_ids
                ),
                6,
            ),
            "mean_turns": round(statistics.fmean(row["turns"] for row in selected), 3),
            "mean_tool_calls": round(statistics.fmean(row["tool_calls"] for row in selected), 3),
            "mean_memory_tool_calls": round(
                statistics.fmean(row["memory_tool_calls"] for row in selected), 3
            ),
            "mean_domain_tool_calls": round(
                statistics.fmean(row["domain_tool_calls"] for row in selected), 3
            ),
            "mean_input_tokens": round(statistics.fmean(row["input_tokens"] for row in selected), 3),
            "mean_output_tokens": round(statistics.fmean(row["output_tokens"] for row in selected), 3),
            "p95_latency_ms": round(
                _percentile([row["latency_ms"] for row in selected], 0.95), 3
            ),
            "tool_errors": sum(row["tool_errors"] for row in selected),
            "repeated_calls": sum(row["repeated_calls"] for row in selected),
            "forbidden_memory_mutations": sum(
                row["forbidden_memory_mutations"] for row in selected
            ),
        }
    strongest = max(
        ("no-memory", "wavemind-core"),
        key=lambda name: treatment_metrics[name]["state_pass_at_1"],
    )
    ci = _paired_task_ci(completed, "wavemind-memory-os", strongest)
    gate = protocol["preregistered_hypothesis"]["development_gate"]
    admitted = (
        ci["mean"] >= gate["memory_os_minus_strongest_baseline_pass_at_1"]
        and ci["low"] > gate["lower_95_ci_above"]
        and treatment_metrics["wavemind-memory-os"]["forbidden_memory_mutations"] == 0
    )
    payload: dict[str, Any] = {
        "schema": "wavemind.state_bench_workflow_development_baseline.v1",
        "status": "development_gate_passed" if admitted else "development_gate_failed",
        "source_sha": _git_sha(repo_root),
        "protocol_payload_sha256": protocol["integrity"]["payload_sha256"],
        "model": MODEL_NAME,
        "model_weight_sha256": MODEL_WEIGHT_SHA256,
        "cpu_only": True,
        "row_count": len(completed),
        "treatments": treatment_metrics,
        "strongest_baseline": strongest,
        "memory_os_paired_lift": ci,
        "development_gate": gate,
        "admitted_for_product_candidate": admitted,
        "taxonomy": {
            "training_trajectory_count": 300,
            "evaluation_trajectory_exclusions": 15,
            "raw_core_training_records": 285,
            "memory_os_verified_training_records": 0,
            "verification_gap": (
                "Official training dialogues contain no executable tool trace or independent final-state result; "
                "TASK_DONE text is not promoted as verified experience."
            ),
        },
        "claim_boundary": (
            "Bounded development result only. Deterministic state assertions are native, but no-state rows "
            "remain safety diagnostics; UX and official task-content judges are not claimed."
        ),
    }
    payload["integrity"] = {
        "algorithm": "sha256",
        "payload_sha256": _payload_sha256(payload),
    }
    return payload


def run_baseline(
    *, repo_root: Path, upstream_root: Path, output: Path, checkpoint: Path
) -> dict[str, Any]:
    protocol = json.loads((repo_root / PROTOCOL_PATH).read_text(encoding="utf-8"))
    state_root = output.parent / "state_bench_workflow_state"
    state_root.mkdir(parents=True, exist_ok=True)
    counts = _prepare_core_store(
        repo_root=repo_root,
        upstream_root=upstream_root,
        protocol=protocol,
        store_path=state_root / "core-training.sqlite3",
    )
    existing: list[dict[str, Any]] = []
    if checkpoint.exists():
        existing = [
            json.loads(line)
            for line in checkpoint.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
    keys = {
        (row["treatment"], row["unit_id"], row["seed"])
        for row in existing
        if row.get("status") == "completed"
    }
    with checkpoint.open("a", encoding="utf-8") as handle:
        for row in protocol["rows"]:
            for seed in SEEDS:
                for treatment in TREATMENTS:
                    key = (treatment, row["unit_id"], seed)
                    if key in keys:
                        continue
                    try:
                        result = _run_task_once(
                            repo_root=repo_root,
                            upstream_root=upstream_root,
                            protocol=protocol,
                            treatment=treatment,
                            domain_name=row["domain"],
                            task_id=row["task_id"],
                            seed=seed,
                            state_root=state_root,
                        )
                    except (RuntimeError, ValueError, OSError, KeyError, TypeError) as exc:
                        result = {
                            "unit_id": row["unit_id"],
                            "domain": row["domain"],
                            "task_id": row["task_id"],
                            "treatment": treatment,
                            "seed": seed,
                            "status": "error",
                            "error_type": type(exc).__name__,
                            "error": str(exc),
                        }
                    handle.write(json.dumps(result, ensure_ascii=False) + "\n")
                    handle.flush()
                    existing.append(result)
                    if result["status"] != "completed":
                        raise RuntimeError(
                            f"baseline stopped fail-closed at {key}: {result.get('error')}"
                        )
    payload = _aggregate_baseline(repo_root=repo_root, protocol=protocol, rows=existing)
    payload["training_records_by_domain"] = counts
    payload["integrity"]["payload_sha256"] = _payload_sha256(payload)
    output.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return payload


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", type=Path, default=Path.cwd())
    parser.add_argument("--upstream-root", type=Path, required=True)
    parser.add_argument("--write-protocol", action="store_true")
    parser.add_argument("--preflight", action="store_true")
    parser.add_argument("--baseline", action="store_true")
    parser.add_argument("--domain", default="shopping_assistant")
    parser.add_argument("--task-id", default="125-hard_promo_expired_code_no_replacement")
    parser.add_argument("--seed", type=int, default=SEEDS[0])
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("benchmarks/state_bench_workflow_preflight_results.json"),
    )
    parser.add_argument(
        "--checkpoint",
        type=Path,
        default=Path("state/state_bench_workflow_development_rows.jsonl"),
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
    if args.baseline:
        output = repo_root / args.output
        checkpoint = repo_root / args.checkpoint
        output.parent.mkdir(parents=True, exist_ok=True)
        checkpoint.parent.mkdir(parents=True, exist_ok=True)
        result = run_baseline(
            repo_root=repo_root,
            upstream_root=upstream_root,
            output=output,
            checkpoint=checkpoint,
        )
        print(
            json.dumps(
                {
                    "status": result["status"],
                    "output": str(output),
                    "row_count": result["row_count"],
                    "strongest_baseline": result["strongest_baseline"],
                    "memory_os_paired_lift": result["memory_os_paired_lift"],
                }
            )
        )


if __name__ == "__main__":
    main()

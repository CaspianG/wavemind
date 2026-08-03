from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from wavemind.core import WaveMind
from wavemind.experience import (
    ExperienceKind,
    ExperienceOutcome,
    ExperienceRecord,
    ExperienceSource,
    ExperienceStatus,
    TrustClass,
)
from wavemind.experience_compiler import ExperienceCompiler
from wavemind.experience_runtime import OutcomeVerifier
from wavemind.memory_firewall import FirewallContext

from .experience_runtime import AgentExperienceHooks, ProviderExperienceRun


def make_recall_node(
    memory: WaveMind,
    namespace: str = "default",
    input_key: str = "input",
    output_key: str = "memory_context",
    top_k: int = 5,
) -> Callable[[Mapping[str, Any]], dict[str, Any]]:
    """Create a LangGraph node that adds recalled WaveMind context to state."""

    def recall_node(state: Mapping[str, Any]) -> dict[str, Any]:
        query = str(state.get(input_key, ""))
        results = memory.query(query, namespace=namespace, top_k=top_k) if query else []
        return {
            output_key: "\n".join(result.text for result in results),
            f"{output_key}_items": [
                {
                    "id": result.id,
                    "text": result.text,
                    "score": result.score,
                    "namespace": result.namespace,
                    "tags": list(result.tags),
                }
                for result in results
            ],
        }

    return recall_node


def make_persist_node(
    memory: WaveMind,
    namespace: str = "default",
    input_key: str = "input",
    output_key: str | None = "output",
    tags: tuple[str, ...] = ("conversation",),
) -> Callable[[Mapping[str, Any]], dict[str, Any]]:
    """Create a LangGraph node that persists selected state as memory."""

    def persist_node(state: Mapping[str, Any]) -> dict[str, Any]:
        ids: list[int] = []
        input_text = str(state.get(input_key, ""))
        if input_text:
            ids.append(memory.remember(input_text, namespace=namespace, tags=tags))
        if output_key:
            output_text = str(state.get(output_key, ""))
            if output_text:
                ids.append(memory.remember(output_text, namespace=namespace, tags=tags))
        return {"wavemind_memory_ids": ids}

    return persist_node


def make_experience_recall_node(
    compiler: ExperienceCompiler,
    *,
    namespace: str,
    input_key: str = "input",
    output_key: str = "experience_packet",
    token_budget: int = 800,
    top_k: int = 8,
) -> Callable[[Mapping[str, Any]], dict[str, Any]]:
    """Create a LangGraph node that compiles trusted experience into state."""

    def recall_node(state: Mapping[str, Any]) -> dict[str, Any]:
        query = str(state.get(input_key, "")).strip()
        if not query:
            return {output_key: "", f"{output_key}_data": None}
        packet = compiler.compile_packet(
            query,
            namespace=namespace,
            context=FirewallContext(namespace=namespace, actor="langgraph"),
            token_budget=token_budget,
            top_k=top_k,
        )
        return {
            output_key: packet.as_prompt() if packet.items else "",
            f"{output_key}_data": packet.as_dict(),
        }

    return recall_node


def make_experience_capture_node(
    compiler: ExperienceCompiler,
    *,
    namespace: str,
    content_key: str = "experience",
    title_key: str = "experience_title",
    kind: ExperienceKind = ExperienceKind.EPISODE,
) -> Callable[[Mapping[str, Any]], dict[str, Any]]:
    """Capture graph output as a shadow candidate guarded by the firewall."""

    def capture_node(state: Mapping[str, Any]) -> dict[str, Any]:
        content = str(state.get(content_key, "")).strip()
        if not content:
            return {"wavemind_experience_id": None}
        title = str(state.get(title_key) or "LangGraph experience").strip()
        record = ExperienceRecord.create(
            kind=kind,
            title=title,
            content=content,
            namespace=namespace,
            outcome=ExperienceOutcome(
                success=state.get("success")
                if isinstance(state.get("success"), bool)
                else None,
            ),
            trust=TrustClass.AGENT_GENERATED,
            status=ExperienceStatus.SHADOW,
            source=ExperienceSource(
                provider="langgraph",
                source_type="graph_state",
                source_id=str(state.get("thread_id") or ""),
            ),
        )
        stored, decision = compiler.submit(
            record,
            context=FirewallContext(namespace=namespace, actor="langgraph"),
        )
        return {
            "wavemind_experience_id": stored.id,
            "wavemind_firewall": decision.as_dict(),
        }

    return capture_node


def make_experience_runtime_start_node(
    hooks: AgentExperienceHooks,
    *,
    domain: str,
    task_type: str,
    input_key: str = "input",
    objective_key: str = "objective",
    run_key: str = "wavemind_experience_run",
    tools: tuple[str, ...] = (),
) -> Callable[[Mapping[str, Any]], dict[str, Any]]:
    """Start a canonical runtime run and expose a selective packet in graph state."""

    def start_node(state: Mapping[str, Any]) -> dict[str, Any]:
        query = str(state.get(input_key) or "").strip()
        if not query:
            raise ValueError(f"LangGraph state key {input_key!r} must not be empty")
        objective = str(state.get(objective_key) or query).strip()
        run = hooks.begin(
            query,
            objective=objective,
            domain=domain,
            task_type=task_type,
            tools=tools,
            session_id=_optional_state_text(state, "thread_id"),
            run_id=_optional_state_text(state, "run_id"),
            task_id=_optional_state_text(state, "task_id"),
            metadata={"framework": "langgraph"},
        )
        return {
            run_key: run,
            f"{run_key}_id": run.run_id,
            "experience_intervention": run.packet,
            "experience_packet": (
                run.intervention.packet.as_prompt()
                if run.intervention.inject and run.intervention.packet is not None
                else ""
            ),
        }

    return start_node


def wrap_experience_runtime_node(
    node: Callable[[Mapping[str, Any]], Mapping[str, Any]],
    *,
    tool_name: str,
    run_key: str = "wavemind_experience_run",
) -> Callable[[Mapping[str, Any]], dict[str, Any]]:
    """Wrap a LangGraph tool node with automatic call/result/error capture."""

    def wrapped(state: Mapping[str, Any]) -> dict[str, Any]:
        run = state.get(run_key)
        if not isinstance(run, ProviderExperienceRun):
            raise ValueError(f"LangGraph state is missing {run_key!r}")
        call_id = run.tool_call(tool_name, {"state": dict(state)})
        try:
            output = dict(node(state))
        except Exception as exc:
            run.error(exc, error_code=type(exc).__name__)
            run.tool_result(
                tool_name,
                success=False,
                output={"error_type": type(exc).__name__},
                call_id=call_id,
            )
            raise
        run.tool_result(tool_name, success=True, output=output, call_id=call_id)
        return output

    return wrapped


def make_experience_runtime_finish_node(
    verifier: OutcomeVerifier,
    *,
    run_key: str = "wavemind_experience_run",
) -> Callable[[Mapping[str, Any]], dict[str, Any]]:
    """Verify and finalize a LangGraph run using independent evidence."""

    def finish_node(state: Mapping[str, Any]) -> dict[str, Any]:
        run = state.get(run_key)
        if not isinstance(run, ProviderExperienceRun):
            raise ValueError(f"LangGraph state is missing {run_key!r}")
        verification = run.verify(verifier)
        finalization = run.finish()
        return {
            "wavemind_verification": verification.as_dict(),
            "wavemind_finalization": finalization.as_dict(),
        }

    return finish_node


def _optional_state_text(state: Mapping[str, Any], key: str) -> str | None:
    value = str(state.get(key) or "").strip()
    return value or None

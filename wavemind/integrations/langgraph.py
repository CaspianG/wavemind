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
from wavemind.memory_firewall import FirewallContext


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

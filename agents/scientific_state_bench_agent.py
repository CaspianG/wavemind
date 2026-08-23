"""Official STATE-Bench adapter for the frozen scientific memory candidate."""

from __future__ import annotations

import os
import weakref
from pathlib import Path
from typing import Any

from state_bench.agents.base import AgentRuntimeContext
from state_bench.agents.state_bench import StateBenchAgent

from wavemind.scientific_runtime import (
    ScientificCandidateMode,
    ScientificMemoryRuntime,
)
from wavemind.scientific_state_bench import (
    STATE_BENCH_AGENT_MODEL,
    STATE_BENCH_RETRIEVAL_TOKEN_BUDGET,
    STATE_BENCH_RETRIEVAL_TOP_K,
)


def _validate_frozen_agent_environment() -> None:
    if os.environ.get("STATE_BENCH_AGENT_PROVIDER") != "openai":
        raise ValueError("STATE-Bench scientific agent provider must remain openai")
    if os.environ.get("STATE_BENCH_AGENT_MODEL") != STATE_BENCH_AGENT_MODEL:
        raise ValueError("STATE-Bench scientific agent model must remain gpt-5.4")


class ScientificStateBenchAgent(StateBenchAgent):
    """Read-only retrieval hook; unverified memories are shadow-only."""

    def __init__(
        self,
        *args: Any,
        runtime_context: AgentRuntimeContext | None = None,
        retrieve_learnings_top_k: int = STATE_BENCH_RETRIEVAL_TOP_K,
        **kwargs: Any,
    ) -> None:
        if runtime_context is None or not runtime_context.domain:
            raise ValueError("official STATE-Bench runtime context is required")
        _validate_frozen_agent_environment()
        if retrieve_learnings_top_k != STATE_BENCH_RETRIEVAL_TOP_K:
            raise ValueError("STATE-Bench scientific retrieval top_k must remain 3")
        expected_domain = os.environ.get("WAVEMIND_STATE_BENCH_DOMAIN")
        if expected_domain and expected_domain != runtime_context.domain:
            raise ValueError("STATE-Bench domain does not match prepared store")
        phase = os.environ.get("WAVEMIND_STATE_BENCH_PHASE")
        if phase not in {"bounded-development-shadow", "production"}:
            raise ValueError("WAVEMIND_STATE_BENCH_PHASE is missing or invalid")
        database_value = os.environ.get("WAVEMIND_STATE_BENCH_SCIENTIFIC_DB")
        if not database_value:
            raise ValueError("WAVEMIND_STATE_BENCH_SCIENTIFIC_DB is required")
        database = Path(database_value).resolve()
        event_database = database.with_name(
            database.name + ".scientific-events.sqlite3"
        )
        if not database.is_file() or not event_database.is_file():
            raise FileNotFoundError("prepared STATE-Bench scientific store is missing")

        self._scientific_phase = phase
        self._scientific_domain = runtime_context.domain
        self._scientific_runtime = ScientificMemoryRuntime(
            database,
            mode=ScientificCandidateMode.CAUSAL,
        )
        try:
            if not self._scientific_runtime.event_log.definitions():
                raise ValueError("prepared STATE-Bench store has no memories")
            super().__init__(
                *args,
                runtime_context=runtime_context,
                retrieve_learnings_top_k=retrieve_learnings_top_k,
                **kwargs,
            )
        except BaseException:
            self._scientific_runtime.close()
            raise
        self._scientific_finalizer = weakref.finalize(
            self,
            self._scientific_runtime.close,
        )

    def retrieve_learnings(self, query: str, top_k: int = 3) -> list[str]:
        if top_k != STATE_BENCH_RETRIEVAL_TOP_K:
            raise ValueError("STATE-Bench scientific retrieval top_k must remain 3")
        recall_method = (
            self._scientific_runtime.shadow_recall
            if self._scientific_phase == "bounded-development-shadow"
            else self._scientific_runtime.recall
        )
        recall = recall_method(
            query,
            context={"domain": self._scientific_domain},
            moment=0.0,
            token_budget=STATE_BENCH_RETRIEVAL_TOKEN_BUDGET,
            latency_budget_ms=1000.0,
            max_safety_risk=1.0,
            namespace=f"state-bench-{self._scientific_domain}",
        )
        return list(recall.contents[:STATE_BENCH_RETRIEVAL_TOP_K])


class ScientificStateBenchNoMemoryControlAgent(StateBenchAgent):
    """Prompt/tool-matched paired control that always returns no learnings."""

    def __init__(
        self,
        *args: Any,
        retrieve_learnings_top_k: int = STATE_BENCH_RETRIEVAL_TOP_K,
        **kwargs: Any,
    ) -> None:
        _validate_frozen_agent_environment()
        if retrieve_learnings_top_k != STATE_BENCH_RETRIEVAL_TOP_K:
            raise ValueError("STATE-Bench scientific retrieval top_k must remain 3")
        super().__init__(
            *args,
            retrieve_learnings_top_k=retrieve_learnings_top_k,
            **kwargs,
        )

    def retrieve_learnings(self, query: str, top_k: int = 3) -> list[str]:
        if not query.strip():
            raise ValueError("STATE-Bench retrieval query must be non-empty")
        if top_k != STATE_BENCH_RETRIEVAL_TOP_K:
            raise ValueError("STATE-Bench scientific retrieval top_k must remain 3")
        return []

from __future__ import annotations

import hashlib
import json
import re
import subprocess
import sys
import tempfile
import types
from pathlib import Path
from typing import Any, Mapping


OFFICIAL_REPOSITORY_SHA = "2cc8c540bdb87fe6761629b585e727e1c4704520"
CANDIDATE_SOURCE_SHA = "a8240fe6bd9a79aec3d524b1cbbbdb4b907f8d97"
MEMORY_TYPE = "wavemind_scientific_v6"
STATE_SLICE_CHARACTERS = 2048


def _git_sha(path: Path) -> str:
    return subprocess.check_output(
        ["git", "rev-parse", "HEAD"],
        cwd=path,
        text=True,
        encoding="utf-8",
    ).strip()


def _require_exact_checkout(path: Path, expected_sha: str, label: str) -> None:
    actual = _git_sha(path)
    if actual != expected_sha:
        raise RuntimeError(f"{label} SHA mismatch: expected {expected_sha}, got {actual}")
    status = subprocess.check_output(
        ["git", "status", "--porcelain=v1"],
        cwd=path,
        text=True,
        encoding="utf-8",
    )
    if status.strip():
        raise RuntimeError(f"{label} checkout is not clean")


def _normalized_text(value: object) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _state_slices(trajectory: Mapping[str, Any]) -> tuple[dict[str, Any], ...]:
    trajectory_id = str(trajectory.get("id") or "").strip()
    if not trajectory_id:
        raise ValueError("LongMemEval-V2 trajectory requires an ID")
    common = " | ".join(
        part
        for part in (
            f"Environment: {_normalized_text(trajectory.get('environment'))}",
            f"Trajectory goal: {_normalized_text(trajectory.get('goal'))}",
            f"Trajectory outcome: {_normalized_text(trajectory.get('outcome'))}",
        )
        if not part.endswith(": ")
    )
    rows: list[dict[str, Any]] = []
    for fallback_index, raw_state in enumerate(trajectory.get("states") or []):
        if not isinstance(raw_state, Mapping):
            continue
        state_index = int(raw_state.get("state_index") or fallback_index)
        state_header = " | ".join(
            part
            for part in (
                common,
                f"State index: {state_index}",
                f"URL: {_normalized_text(raw_state.get('url'))}",
                f"Action: {_normalized_text(raw_state.get('action'))}",
                f"Thought: {_normalized_text(raw_state.get('thought'))}",
            )
            if not part.endswith(": ")
        )
        observed = _normalized_text(raw_state.get("accessibility_tree"))
        if not observed:
            observed = _normalized_text(raw_state)
        chunks = [
            observed[offset : offset + STATE_SLICE_CHARACTERS]
            for offset in range(0, len(observed), STATE_SLICE_CHARACTERS)
        ] or ["(no textual observation)"]
        for slice_index, chunk in enumerate(chunks):
            rows.append(
                {
                    "trajectory_id": trajectory_id,
                    "state_index": state_index,
                    "slice_index": slice_index,
                    "text": f"{state_header} | Observed page: {chunk}",
                }
            )
    return tuple(rows)


def _install_optional_baseline_import_shims() -> tuple[str, ...]:
    """Avoid importing unused optional baselines with incompatible dependencies."""

    modules = {
        "memory_modules.codex": "CodexMemory",
        "memory_modules.agentrunbook_c": "AgentRunbookC",
        "memory_modules.agentrunbook_c_v2": "AgentRunbookCV2",
        "memory_modules.agentrunbook_r": "AgentRunbookR",
        "memory_modules.rag": "RagMemory",
    }
    installed: list[str] = []
    for module_name, class_name in modules.items():
        if module_name in sys.modules:
            continue
        module = types.ModuleType(module_name)
        setattr(module, class_name, type(class_name, (), {}))
        sys.modules[module_name] = module
        installed.append(module_name)
    return tuple(installed)


def register_backend(
    *,
    official_repository: str | Path,
    candidate_repository: str | Path,
) -> type:
    """Register the frozen v6 candidate in an unmodified official harness."""

    official_root = Path(official_repository).resolve()
    candidate_root = Path(candidate_repository).resolve()
    _require_exact_checkout(
        official_root,
        OFFICIAL_REPOSITORY_SHA,
        "LongMemEval-V2 official repository",
    )
    _require_exact_checkout(
        candidate_root,
        CANDIDATE_SOURCE_SHA,
        "WaveMind v6 candidate",
    )
    for root in (candidate_root, official_root):
        value = str(root)
        if value in sys.path:
            sys.path.remove(value)
        sys.path.insert(0, value)

    _install_optional_baseline_import_shims()
    from memory_modules.memory import Memory, register_memory
    from wavemind.evidence import canonical_json_bytes, sha256_bytes
    from wavemind.scientific_memory import MemoryDefinition, MemoryKind
    from wavemind.scientific_memoryagentbench import compile_candidate_units
    from wavemind.scientific_runtime import (
        ScientificCandidateMode,
        ScientificMemoryRuntime,
    )

    @register_memory
    class ScientificLongMemEvalV6(Memory):
        memory_type = MEMORY_TYPE

        def __init__(self, memory_params: dict[str, object]) -> None:
            super().__init__(memory_params)
            scratch_root = Path(
                str(memory_params.get("scratch_root") or tempfile.gettempdir())
            ).resolve()
            scratch_root.mkdir(parents=True, exist_ok=True)
            self._work_dir = Path(
                tempfile.mkdtemp(prefix="wavemind-lme-v6-", dir=scratch_root)
            )
            self._runtime = ScientificMemoryRuntime(
                self._work_dir / "candidate.sqlite3",
                mode=ScientificCandidateMode.OPERATION_AWARE_TOMBSTONE_RECONCILER,
            )
            self._trajectories: list[dict[str, Any]] = []
            self._compiled = False
            self._event_hashes: tuple[str, ...] = ()
            self._full_context_estimated_tokens = 0
            self._last_metadata: dict[str, object] | None = None

        def insert(self, trajectory: dict[str, object]) -> None:
            if self._compiled:
                raise RuntimeError("cannot insert after the first v6 query")
            self._trajectories.append(dict(trajectory))

        def _compile_once(self) -> None:
            if self._compiled:
                return
            structural_rows = [
                row
                for trajectory in self._trajectories
                for row in _state_slices(trajectory)
            ]
            structural_text = "\n\n".join(str(row["text"]) for row in structural_rows)
            compiled = compile_candidate_units(
                context=structural_text,
                source="longmemeval-v2-official-trajectory",
                official_chunks=[str(row["text"]) for row in structural_rows],
                mode=ScientificCandidateMode.OPERATION_AWARE_TOMBSTONE_RECONCILER,
            )
            if len(compiled) != len(structural_rows):
                raise RuntimeError("v6 structural compiler changed LongMemEval slice count")
            definitions = []
            for row, unit in zip(structural_rows, compiled):
                content = unit.content
                definitions.append(
                    MemoryDefinition(
                        memory_id=(
                            "lme-v6-"
                            + sha256_bytes(
                                canonical_json_bytes(
                                    {
                                        "trajectory_id": row["trajectory_id"],
                                        "state_index": row["state_index"],
                                        "slice_index": row["slice_index"],
                                        "content": content,
                                    }
                                )
                            )[:24]
                        ),
                        kind=MemoryKind.FACT,
                        content=content,
                        provenance=(
                            f"longmemeval-v2:{row['trajectory_id']}",
                            f"state-index:{row['state_index']}",
                            f"slice-index:{row['slice_index']}",
                            f"source-order:{unit.source_order}",
                            f"structural-kind:{unit.structural_kind}",
                        ),
                        estimated_tokens=max(1, (len(content) + 3) // 4),
                        estimated_latency_ms=0.1,
                        safety_risk=0.0,
                    )
                )
            self._full_context_estimated_tokens = sum(
                definition.estimated_tokens for definition in definitions
            )
            self._event_hashes = self._runtime.register_evaluation_memories(
                definitions,
                actor="longmemeval-v2-admission-adapter-v6",
            )
            self._compiled = True

        def query(
            self,
            query: str,
            query_image: str | None = None,
        ) -> list[dict[str, str]]:
            del query_image
            self._compile_once()
            recall = self._runtime.evaluation_recall(
                query,
                context={},
                moment=0.0,
                token_budget=8192,
                latency_budget_ms=1000.0,
                max_safety_risk=0.0,
            )
            production_count = self._runtime.retriever.store.count(
                namespace="scientific"
            )
            chain_errors = self._runtime.event_log.validate_chain()
            context_digest = hashlib.sha256(
                json.dumps(
                    list(recall.contents),
                    ensure_ascii=False,
                    separators=(",", ":"),
                ).encode("utf-8")
            ).hexdigest()
            self._last_metadata = {
                "candidate_source_sha": CANDIDATE_SOURCE_SHA,
                "selected_memory_ids": list(recall.selected_memory_ids),
                "selected_count": len(recall.selected_memory_ids),
                "selected_estimated_tokens": recall.estimated_tokens,
                "full_context_estimated_tokens": self._full_context_estimated_tokens,
                "context_sha256": context_digest,
                "event_count": len(self._event_hashes),
                "event_chain_valid": not chain_errors,
                "event_chain_errors": list(chain_errors),
                "production_index_count": production_count,
                "evaluation_only": recall.evaluation_only,
                "intervention_present": bool(recall.contents),
                "reason": recall.reason,
            }
            return [
                {"type": "text", "value": content}
                for content in recall.contents
                if content.strip()
            ]

        def post_query_hook(
            self,
            *,
            query: str,
            query_image: str | None,
            memory_context: list[dict[str, str]],
        ) -> dict[str, object] | None:
            del query, query_image, memory_context
            return dict(self._last_metadata or {})

        def close(self) -> None:
            self._runtime.close()

    return ScientificLongMemEvalV6


def registration_fingerprint() -> str:
    return hashlib.sha256(Path(__file__).read_bytes()).hexdigest()

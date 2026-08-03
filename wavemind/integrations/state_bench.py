from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..experience import TrustClass
from ..experience_runtime import AgentExperienceRuntime
from ..memory_firewall import FirewallContext


STATE_BENCH_DOMAINS = ("travel", "customer_support", "shopping_assistant")
STATE_BENCH_TOP_K = 3
STATE_BENCH_REPEATS = 5
STATE_BENCH_TRAIN_PER_DOMAIN = 100


@dataclass(frozen=True)
class StateBenchProtocolValidation:
    valid: bool
    errors: tuple[str, ...]
    file_counts: dict[str, int]
    fingerprint_sha256: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "valid": self.valid,
            "errors": list(self.errors),
            "file_counts": dict(self.file_counts),
            "fingerprint_sha256": self.fingerprint_sha256,
        }


class WaveMindStateBenchLearningAdapter:
    """Read-only `retrieve_learnings` adapter for STATE-Bench Agent Learning."""

    def __init__(
        self,
        runtime: AgentExperienceRuntime,
        *,
        namespace: str,
        domain: str,
        top_k: int = STATE_BENCH_TOP_K,
    ) -> None:
        if domain not in STATE_BENCH_DOMAINS:
            raise ValueError(f"unsupported STATE-Bench domain: {domain}")
        if top_k != STATE_BENCH_TOP_K:
            raise ValueError("official STATE-Bench protocol requires top_k=3")
        self.runtime = runtime
        self.namespace = namespace
        self.domain = domain
        self.top_k = top_k

    def retrieve_learnings(
        self, query: str, top_k: int = STATE_BENCH_TOP_K
    ) -> list[str]:
        if top_k != self.top_k:
            raise ValueError(
                "evaluation top_k must match the frozen adapter configuration"
            )
        before = self._mutation_fingerprint()
        packet = self.runtime.compiler.compile_packet(
            query,
            namespace=self.namespace,
            context=FirewallContext(
                namespace=self.namespace,
                actor="state_bench_read_only",
                actor_trust=TrustClass.TOOL_OUTPUT,
            ),
            token_budget=600,
            top_k=top_k,
            domains=(self.domain,),
        )
        learnings = [item.excerpt for item in packet.items if item.excerpt]
        if self._mutation_fingerprint() != before:
            raise RuntimeError("STATE-Bench retrieval mutated the experience store")
        return learnings

    def _mutation_fingerprint(self) -> tuple[int, int, int]:
        with self.runtime.store._lock:
            conn = self.runtime.store.conn
            return (
                int(
                    conn.execute("SELECT COUNT(*) FROM experience_records").fetchone()[
                        0
                    ]
                ),
                int(
                    conn.execute(
                        "SELECT COUNT(*) FROM experience_audit_events"
                    ).fetchone()[0]
                ),
                int(
                    conn.execute(
                        "SELECT COUNT(*) FROM agent_experience_injections"
                    ).fetchone()[0]
                ),
            )


def validate_state_bench_training_root(
    root: str | Path,
) -> StateBenchProtocolValidation:
    root = Path(root)
    errors: list[str] = []
    counts: dict[str, int] = {}
    digest = hashlib.sha256()
    if "test" in {part.lower() for part in root.parts}:
        errors.append("training root must not point at STATE-Bench test data")
    for domain in STATE_BENCH_DOMAINS:
        domain_root = root / domain
        files = sorted(domain_root.glob("*.json")) if domain_root.is_dir() else []
        counts[domain] = len(files)
        if len(files) != STATE_BENCH_TRAIN_PER_DOMAIN:
            errors.append(
                f"{domain} must contain exactly {STATE_BENCH_TRAIN_PER_DOMAIN} training trajectories"
            )
        for path in files:
            payload = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(payload, dict) or not isinstance(
                payload.get("conversation"), list
            ):
                errors.append(f"{path.name} does not contain a conversation trajectory")
            digest.update(domain.encode())
            digest.update(path.name.encode())
            digest.update(path.read_bytes())
    return StateBenchProtocolValidation(
        valid=not errors,
        errors=tuple(errors),
        file_counts=counts,
        fingerprint_sha256=digest.hexdigest(),
    )


def build_state_bench_adapter_artifact(
    *,
    training_root: str | Path,
    source_sha: str,
    upstream_sha: str | None = None,
) -> dict[str, Any]:
    validation = validate_state_bench_training_root(training_root)
    return {
        "schema": "wavemind.state_bench_agent_learning_adapter.v1",
        "status": "runner_ready" if validation.valid else "blocked",
        "source_sha": source_sha,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "official_protocol": {
            "repository": "https://github.com/microsoft/STATE-Bench",
            "repository_sha": upstream_sha,
            "domains": list(STATE_BENCH_DOMAINS),
            "training_trajectories_per_domain": STATE_BENCH_TRAIN_PER_DOMAIN,
            "held_out_tasks_per_domain": 50,
            "top_k": STATE_BENCH_TOP_K,
            "repeats": STATE_BENCH_REPEATS,
            "evaluation_retrieval_is_read_only": True,
            "official_paid_model_run_performed": False,
        },
        "training_data": validation.as_dict(),
        "adapter": {
            "class": "wavemind.integrations.state_bench.WaveMindStateBenchLearningAdapter",
            "method": "retrieve_learnings(query, top_k=3) -> list[str]",
        },
        "claim_boundary": "Runner-ready interoperability is not an official STATE-Bench result.",
    }

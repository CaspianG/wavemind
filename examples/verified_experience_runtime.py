from __future__ import annotations

import tempfile
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from wavemind import (
    AgentExperienceRuntime,
    AgentExperienceRuntimePolicy,
    CallableOutcomeVerifier,
    ExperienceCompiler,
    MemoryFirewall,
    MemoryFirewallPolicy,
    SQLiteExperienceStore,
    VerificationSource,
)


SAFE_PLAN = ("inspect", "stage", "apply", "verify")


class DeploymentEnvironment:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def call(self, name: str) -> dict[str, object]:
        self.calls.append(name)
        return {"tool": name, "revision": len(self.calls)}

    def healthy(self) -> bool:
        return tuple(self.calls) == SAFE_PLAN


def build_runtime(path: Path) -> AgentExperienceRuntime:
    namespace = "demo-agent"
    store = SQLiteExperienceStore(path)
    compiler = ExperienceCompiler(
        store,
        MemoryFirewall(
            MemoryFirewallPolicy(
                namespace=namespace,
                require_consent_for_user_data=False,
            )
        ),
    )
    return AgentExperienceRuntime(
        compiler,
        policy=AgentExperienceRuntimePolicy(intervention_score_threshold=0.0),
    )


def execute_and_verify(
    runtime: AgentExperienceRuntime,
    *,
    run_id: str,
    plan: tuple[str, ...],
):
    environment = DeploymentEnvironment()
    run = runtime.begin_run(
        namespace="demo-agent",
        objective="deploy safely and verify health",
        domain="operations",
        task_type="safe_deploy",
        run_id=run_id,
    )
    for tool_name in plan:
        run.execute_tool(tool_name, environment.call, tool_name)
    run.verify(
        CallableOutcomeVerifier(
            source=VerificationSource.ENVIRONMENT,
            verifier="deployment-state",
            callback=lambda _context: (
                environment.healthy(),
                1.0 if environment.healthy() else 0.0,
            ),
            reference=f"local-state://{run_id}",
        )
    )
    return run.finish(), environment.healthy()


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="wavemind-experience-demo-") as directory:
        runtime = build_runtime(Path(directory) / "experience.sqlite3")
        _, first_success = execute_and_verify(
            runtime,
            run_id="failed-attempt",
            plan=("apply", "verify"),
        )
        print(
            "1. Cold attempt verified by environment: "
            f"{'PASS' if first_success else 'FAIL'}"
        )

        for index in range(3):
            execute_and_verify(
                runtime,
                run_id=f"verified-reference-{index}",
                plan=SAFE_PLAN,
            )
        decision = runtime.decide(
            "deploy safely and verify health",
            namespace="demo-agent",
            domains=("operations",),
            task_types=("safe_deploy",),
            tools=SAFE_PLAN,
            top_k=1,
        )
        assert decision.packet is not None
        record = runtime.store.get(decision.packet.items[0].experience_id)
        assert record is not None
        learned_plan = tuple(record.metadata["tool_plan"])
        _, final_success = execute_and_verify(
            runtime,
            run_id="held-out-attempt",
            plan=learned_plan,
        )
        print(
            "2. Independently verified procedure: "
            f"{'LEARNED' if decision.inject else 'MISSING'}"
        )
        print(f"3. Held-out attempt: {'PASS' if final_success else 'FAIL'}")
        print(f"4. Citation: {decision.packet.items[0].citation}")
        runtime.store.close()


if __name__ == "__main__":
    main()

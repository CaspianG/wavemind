from __future__ import annotations

from wavemind import (
    ExperienceCompiler,
    ExperienceStatus,
    ExperiencedWorkAgent,
    MemoryFirewall,
    MemoryFirewallPolicy,
    SQLiteExperienceStore,
    ToolExecution,
    WorkRequest,
)


class Runtime:
    available_tools = ("unsafe", "inspect", "apply", "verify")

    def __init__(self):
        self.inspected = False
        self.applied = False
        self.calls: list[str] = []

    def call(self, name: str) -> ToolExecution:
        self.calls.append(name)
        success = True
        error = None
        if name == "unsafe":
            success = False
            error = "unsafe_order"
        elif name == "inspect":
            self.inspected = True
        elif name == "apply":
            success = self.inspected
            self.applied = success
            error = None if success else "missing_inspection"
        elif name == "verify":
            success = self.applied
            error = None if success else "verification_failed"
        return ToolExecution(
            name=name,
            success=success,
            output={"called": name},
            error_code=error,
            duration_ms=0.1,
        )

    def verify(self) -> bool:
        return self.inspected and self.applied


def _agent(tmp_path):
    store = SQLiteExperienceStore(tmp_path / "agent.db")
    compiler = ExperienceCompiler(
        store,
        MemoryFirewall(MemoryFirewallPolicy(namespace="agent")),
    )
    return store, ExperiencedWorkAgent(compiler)


def test_work_agent_learns_only_after_repeated_verified_outcomes(tmp_path) -> None:
    store, agent = _agent(tmp_path)
    try:
        for index in range(3):
            run = agent.run(
                WorkRequest(
                    id=f"train-{index}",
                    objective="Repair the service safely",
                    namespace="agent",
                    domain="coding",
                    task_type="safe_repair",
                    fallback_plan=("unsafe", "verify"),
                    demonstration_plan=("inspect", "apply", "verify"),
                ),
                Runtime(),
            )
            assert run.success
            assert run.plan_source == "demonstration"

        strategy = store.get(run.learned_experience_id)
        assert strategy is not None
        assert strategy.status == ExperienceStatus.ACTIVE

        held_out = agent.run(
            WorkRequest(
                id="held-out",
                objective="Recover an unhealthy service",
                namespace="agent",
                domain="coding",
                task_type="safe_repair",
                fallback_plan=("unsafe", "verify"),
            ),
            Runtime(),
            learn=False,
        )
        assert held_out.success
        assert held_out.plan_source == "experience"
        assert held_out.plan == ("inspect", "apply", "verify")
        assert held_out.selected_experience_id == strategy.id
        assert held_out.packet is not None
        assert held_out.packet["citations"] == [f"experience:{strategy.id}@v1"]
    finally:
        store.close()


def test_work_agent_records_failed_trajectory_and_repeat_error(tmp_path) -> None:
    store, agent = _agent(tmp_path)
    try:
        run = agent.run(
            WorkRequest(
                id="failure",
                objective="Repair without a learned procedure",
                namespace="agent",
                domain="coding",
                task_type="unknown",
                fallback_plan=("unsafe", "verify"),
            ),
            Runtime(),
            known_error_codes=("unsafe_order",),
        )
        assert run.success is False
        assert run.repeated_error_codes == ("unsafe_order",)
        assert store.get_trajectory(run.trajectory_id) is not None
        failure = store.get(run.learned_experience_id)
        assert failure is not None
        assert failure.status == ExperienceStatus.SHADOW
        assert failure.metadata["error_codes"] == [
            "unsafe_order",
            "verification_failed",
        ]
    finally:
        store.close()

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from wavemind.evidence import attach_artifact_integrity, file_sha256
from wavemind.evaluation_splits import SCHEMA as EVALUATION_SPLIT_SCHEMA
from wavemind.evaluation_splits import STATE_BENCH_REVISION
from wavemind.scientific_runtime import ScientificCandidateMode, ScientificMemoryRuntime
from wavemind.scientific_state_bench import (
    STATE_BENCH_RETRIEVAL_TOKEN_BUDGET,
    build_state_bench_development_plan,
    extract_procedure_memory,
    prepare_state_bench_development_store,
    validate_prepared_state_bench_artifact,
)


def _trajectory(index: int) -> dict[str, object]:
    return {
        "conversation": [
            {
                "role": "user",
                "content": (
                    f"Cancel booking BK-{index:04d} for user_{index:03d}; "
                    "the quoted price is $123."
                ),
            },
            {
                "role": "assistant",
                "content": "I will inspect policy before any write.",
                "tool_calls": [
                    {
                        "name": "get_booking",
                        "arguments": {"booking_id": f"BK-{index:04d}"},
                        "result": {"status": "confirmed"},
                    },
                    {
                        "name": "cancel_booking",
                        "arguments": {
                            "booking_id": f"BK-{index:04d}",
                            "confirm": False,
                        },
                        "result": {"status": "preview"},
                    },
                ],
            },
        ]
    }


def _split_fixture(tmp_path: Path) -> tuple[Path, dict[str, object]]:
    root = tmp_path / "state-bench"
    root.mkdir()
    (root / "uv.lock").write_text("# pinned lock\n", encoding="utf-8")
    (root / "pyproject.toml").write_text(
        "[project]\nname='state-bench'\nversion='0.0.0'\n",
        encoding="utf-8",
    )
    trajectory_root = root / "datasets" / "train_task_trajectories" / "travel"
    trajectory_root.mkdir(parents=True)
    official_root = root / "state_bench"
    (official_root / "scripts").mkdir(parents=True)
    (official_root / "agents").mkdir(parents=True)
    (official_root / "configs" / "eval_protocols").mkdir(parents=True)
    (official_root / "scripts" / "run_batch.py").write_text(
        "# pinned official runner\n", encoding="utf-8"
    )
    (official_root / "agents" / "state_bench.py").write_text(
        "# pinned official agent hook\n", encoding="utf-8"
    )
    (official_root / "configs" / "eval_protocols" / "gpt54.json").write_text(
        '{"model":"gpt-5.4"}\n', encoding="utf-8"
    )
    units: list[dict[str, object]] = []
    for index in range(80):
        task_id = f"task-{index:03d}"
        path = trajectory_root / f"{task_id}.json"
        path.write_text(json.dumps(_trajectory(index)), encoding="utf-8")
        units.append(
            {
                "dataset": "state-bench",
                "domain": "travel",
                "task_id": task_id,
                "trajectory_sha256": file_sha256(path),
                "unit_id": f"state-bench:travel:{task_id}",
                "source_split": "train",
                "split": "development",
            }
        )
    manifest = attach_artifact_integrity(
        {
            "schema": EVALUATION_SPLIT_SCHEMA,
            "upstream": {
                "state-bench": {
                    "revision": STATE_BENCH_REVISION,
                    "official_train_test_preserved": True,
                }
            },
            "units": units,
        }
    )
    return root, manifest


def test_state_bench_development_plan_is_frozen_and_disjoint(tmp_path):
    _, manifest = _split_fixture(tmp_path)

    first = build_state_bench_development_plan(manifest, domain="travel")
    second = build_state_bench_development_plan(manifest, domain="travel")

    assert len(first.learning_units) == 77
    assert len(first.evaluation_units) == 3
    assert first == second
    assert not set(first.learning_unit_ids) & set(first.evaluation_unit_ids)
    assert all(unit["split"] == "development" for unit in first.learning_units)
    assert all(unit["split"] == "development" for unit in first.evaluation_units)


def test_state_bench_development_plan_rejects_tampered_manifest(tmp_path):
    _, manifest = _split_fixture(tmp_path)
    manifest["units"][0]["task_id"] = "tampered"

    with pytest.raises(ValueError, match="integrity failed"):
        build_state_bench_development_plan(manifest, domain="travel")


def test_procedure_extraction_never_copies_task_arguments_or_identifiers():
    trajectory = _trajectory(7)
    definition = extract_procedure_memory(
        unit={
            "unit_id": "state-bench:travel:task-007",
            "task_id": "task-007",
            "trajectory_sha256": "a" * 64,
        },
        trajectory=trajectory,
        domain="travel",
    )

    assert "get_booking -> cancel_booking" in definition.content
    assert "BK-0007" not in definition.content
    assert "user_007" not in definition.content
    assert "$123" not in definition.content
    assert definition.applicability == {"domain": "travel"}
    assert definition.safety_risk == 0.25


def test_prepared_store_is_persistent_shadow_only_and_integrity_bound(
    tmp_path,
    monkeypatch,
):
    root, manifest = _split_fixture(tmp_path)
    monkeypatch.setattr(
        "wavemind.scientific_state_bench._git_sha",
        lambda unused_root: STATE_BENCH_REVISION,
    )
    monkeypatch.setattr(
        "wavemind.scientific_state_bench._run_official_loader_preflight",
        lambda **unused: {
            "argv": ["uv"],
            "returncode": 0,
            "stdout": (
                "ScientificStateBenchAgent,ScientificStateBenchNoMemoryControlAgent"
            ),
            "stderr": "",
            "both_agent_classes_loaded": True,
        },
    )
    monkeypatch.setattr(
        "wavemind.scientific_state_bench._validate_source_checkout",
        lambda *unused: None,
    )
    monkeypatch.setattr(
        "wavemind.scientific_state_bench._run_official_adapter_preflight",
        lambda **unused: {
            "argv": ["uv"],
            "returncode": 0,
            "result": {
                "shadow_count": 3,
                "control_count": 0,
                "production_count": 0,
                "common_retrieval_tool": True,
                "llm_or_official_task_executed": False,
            },
            "stderr": "",
            "passed": True,
        },
    )
    database = tmp_path / "prepared" / "scientific.sqlite3"
    learning_manifest = tmp_path / "prepared" / "learnings.json"

    payload = prepare_state_bench_development_store(
        project_root=Path.cwd(),
        state_bench_root=root,
        split_manifest=manifest,
        protocol_digest="b" * 64,
        source_sha="c" * 40,
        domain="travel",
        database_path=database,
        learning_manifest_path=learning_manifest,
        environment={},
    )

    assert validate_prepared_state_bench_artifact(payload) == []
    assert payload["status"] == "prepared_waiting_for_credentials"
    assert payload["candidate"]["memory_count"] == 77
    assert payload["candidate"]["production_memory_count"] == 0
    assert payload["paired_execution"]["run_count"] == 3
    assert payload["paired_execution"]["common_prompt_and_retrieval_tool"] is True
    assert payload["development_plan"]["evaluation_trajectory_content_touched"] is False
    assert learning_manifest.is_file()
    with ScientificMemoryRuntime(
        database,
        mode=ScientificCandidateMode.CAUSAL,
        bootstrap_repeats=100,
    ) as runtime:
        definitions = runtime.event_log.definitions()
        assert len(definitions) == 77
        assert not any(
            runtime.event_log.memory_state(memory_id).production_eligible
            for memory_id in definitions
        )
        production = runtime.recall(
            "get booking then cancel booking",
            context={"domain": "travel"},
            moment=0.0,
            token_budget=STATE_BENCH_RETRIEVAL_TOKEN_BUDGET,
            latency_budget_ms=1000.0,
            max_safety_risk=1.0,
            namespace="state-bench-travel",
        )
        shadow = runtime.shadow_recall(
            "get booking then cancel booking",
            context={"domain": "travel"},
            moment=0.0,
            token_budget=STATE_BENCH_RETRIEVAL_TOKEN_BUDGET,
            latency_budget_ms=1000.0,
            max_safety_risk=1.0,
            namespace="state-bench-travel",
        )
        assert production.abstained is True
        assert shadow.evaluation_only is True
        assert shadow.selected_memory_ids

    tampered = copy.deepcopy(payload)
    tampered["candidate"]["production_memory_count"] = 1
    tampered = attach_artifact_integrity(
        {key: value for key, value in tampered.items() if key != "integrity"}
    )
    assert "unverified STATE-Bench memories gained production influence" in (
        validate_prepared_state_bench_artifact(tampered)
    )

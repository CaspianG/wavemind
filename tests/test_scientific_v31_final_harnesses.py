from __future__ import annotations

import ast
import concurrent.futures
import gc
import hashlib
import importlib.util
import json
from pathlib import Path
import threading
import time
import types
from types import SimpleNamespace


ROOT = Path(__file__).resolve().parents[1]
PROTOCOL = json.loads(
    (ROOT / "benchmarks" / "scientific_memory_protocol_v31.json").read_text(
        encoding="utf-8"
    )
)
OFFICIAL_LONGMEM = (
    ROOT.parents[1] / "scientific-evidence" / "upstreams" / "longmemeval-v2"
)
CANDIDATE = ROOT.parent / "wavemind-scientific-v31-official-exact"


def _assignments(path: Path) -> dict[str, object]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    values: dict[str, object] = {}
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        for target in node.targets:
            if isinstance(target, ast.Name):
                try:
                    values[target.id] = ast.literal_eval(node.value)
                except (ValueError, TypeError):
                    pass
    return values


def test_v31_mab_final_runner_matches_frozen_units_without_opening_rows():
    values = _assignments(ROOT / "benchmarks" / "scientific_mab_v31_final.py")
    assert values["CANDIDATE_SOURCE_SHA"] == (
        "2a55c83ef3d3e4a3c5d9dff4418258eacb378127"
    )
    assert values["PROTOCOL_DIGEST"] == PROTOCOL["protocol_digest"]
    assert list(values["FINAL_UNIT_IDS"]) == PROTOCOL["frozen_admission"][
        "memoryagentbench_fresh_final_unit_ids"
    ]
    assert values["MODEL_DIGEST"] == PROTOCOL["frozen_parameters"]["model_digest"]


def test_v31_memops_final_runner_matches_frozen_subjects_and_router():
    path = ROOT / "benchmarks" / "scientific_memops_v31_final.py"
    values = _assignments(path)
    source = path.read_text(encoding="utf-8")
    assert list(values["FINAL_SUBJECTS"]) == PROTOCOL["frozen_admission"][
        "memops_final_subjects"
    ]
    assert values["CANDIDATE_SOURCE_SHA"] == (
        "2a55c83ef3d3e4a3c5d9dff4418258eacb378127"
    )
    assert values["PROTOCOL_DIGEST"] == PROTOCOL["protocol_digest"]
    assert "TARGET_STATE_CUTOVER_AGENT" in source
    assert "TARGET_SCOPED_OPERATION_AGENT" in source
    assert 'configured.QUESTION_SELECTION = "operation-adaptive-v7"' in source


def test_v31_longmemeval_runner_matches_frozen_revision_and_protocol():
    backend = _assignments(
        ROOT / "benchmarks" / "scientific_longmemeval_v2_backend_v31.py"
    )
    runner = _assignments(
        ROOT / "benchmarks" / "scientific_longmemeval_v2_run_v31.py"
    )
    assert backend["CANDIDATE_SOURCE_SHA"] == (
        "2a55c83ef3d3e4a3c5d9dff4418258eacb378127"
    )
    assert backend["OFFICIAL_REPOSITORY_SHA"] == (
        "2cc8c540bdb87fe6761629b585e727e1c4704520"
    )
    assert runner["PROTOCOL_DIGEST"] == PROTOCOL["protocol_digest"]
    assert runner["DATASET_REVISION"] == PROTOCOL["frozen_admission"][
        "longmemeval_v2_dataset_revision"
    ]


def test_v31_longmemeval_backend_registers_exact_candidate_without_gold(tmp_path):
    path = ROOT / "benchmarks" / "scientific_longmemeval_v2_backend_v31.py"
    spec = importlib.util.spec_from_file_location("scientific_lme_v31_backend_test", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    backend_class = module.register_backend(
        official_repository=OFFICIAL_LONGMEM,
        candidate_repository=CANDIDATE,
    )
    backend = backend_class({"scratch_root": str(tmp_path)})
    try:
        backend.insert(
            {
                "id": "synthetic-trajectory",
                "environment": "shop",
                "goal": "find checkout rule",
                "outcome": "success",
                "states": [
                    {
                        "state_index": 0,
                        "url": "https://example.test/checkout",
                        "action": "open checkout",
                        "thought": "observe",
                        "accessibility_tree": "Checkout requires a delivery window.",
                    }
                ],
            }
        )
        queries = ["What does checkout require?"] * 4
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
            contexts = list(executor.map(backend.query, queries))
        context = contexts[0]
        metadata = backend.post_query_hook(
            query="What does checkout require?",
            query_image=None,
            memory_context=context,
        )
    finally:
        backend.close()

    assert all(contexts)
    assert all(item == context for item in contexts)
    assert metadata is not None
    assert metadata["candidate_source_sha"] == module.CANDIDATE_SOURCE_SHA
    assert metadata["event_chain_valid"] is True
    assert metadata["production_index_count"] == 0
    assert metadata["evaluation_only"] is True
    assert metadata["intervention_present"] is True


def test_v31_longmemeval_backend_serializes_shared_queries_and_keeps_metadata_local(
    tmp_path,
):
    path = ROOT / "benchmarks" / "scientific_longmemeval_v2_backend_v31.py"
    spec = importlib.util.spec_from_file_location(
        "scientific_lme_v31_backend_query_lock_test", path
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    backend_class = module.register_backend(
        official_repository=OFFICIAL_LONGMEM,
        candidate_repository=CANDIDATE,
    )
    backend = backend_class({"scratch_root": str(tmp_path)})
    backend.insert(
        {
            "id": "synthetic-trajectory",
            "environment": "shop",
            "goal": "find checkout rule",
            "outcome": "success",
            "states": [
                {
                    "state_index": 0,
                    "url": "https://example.test/checkout",
                    "action": "open checkout",
                    "thought": "observe",
                    "accessibility_tree": "Checkout requires a delivery window.",
                }
            ],
        }
    )
    backend._compile_once()

    counter_lock = threading.Lock()
    active = 0
    maximum_active = 0

    def fake_recall(query, **_kwargs):
        nonlocal active, maximum_active
        with counter_lock:
            active += 1
            maximum_active = max(maximum_active, active)
        time.sleep(0.02)
        with counter_lock:
            active -= 1
        return SimpleNamespace(
            contents=(f"context:{query}",),
            selected_memory_ids=(f"memory:{query}",),
            estimated_tokens=1,
            evaluation_only=True,
            reason="query-lock-test",
        )

    backend._runtime.evaluation_recall = fake_recall
    barrier = threading.Barrier(4)

    def perform(query):
        context = backend.query(query)
        barrier.wait(timeout=5.0)
        metadata = backend.post_query_hook(
            query=query,
            query_image=None,
            memory_context=context,
        )
        return context, metadata

    queries = [f"query-{index}" for index in range(4)]
    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
            results = list(executor.map(perform, queries))
    finally:
        backend.close()

    assert maximum_active == 1
    for query, (context, metadata) in zip(queries, results):
        assert context == [{"type": "text", "value": f"context:{query}"}]
        assert metadata is not None
        expected_digest = hashlib.sha256(
            json.dumps(
                [f"context:{query}"],
                ensure_ascii=False,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        assert metadata["context_sha256"] == expected_digest
        assert metadata["selected_memory_ids"] == [f"memory:{query}"]


def test_v31_longmemeval_streaming_operation_selector_is_exactly_equivalent():
    from wavemind.scientific_memory import MemoryDefinition, MemoryKind
    from wavemind.scientific_reconciliation import ProofCarryingStateReconciler

    path = ROOT / "benchmarks" / "scientific_longmemeval_v2_backend_v31.py"
    spec = importlib.util.spec_from_file_location(
        "scientific_lme_v31_streaming_equivalence_test", path
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    definitions = {}
    for index in range(600):
        words = [f"noise-{index}-{offset}" for offset in range(40)]
        if index % 3 == 0:
            words.extend(("kevin", "checkout"))
        if index % 5 == 0:
            words.extend(("delivery", "state"))
        provenance = [f"source-order:{index}", "memory-operation:1"]
        if index % 11 == 0:
            provenance.append("memory-tombstone:1")
        definitions[f"memory-{index:04d}"] = MemoryDefinition(
            memory_id=f"memory-{index:04d}",
            kind=MemoryKind.FACT,
            content=" ".join(words),
            provenance=tuple(provenance),
            estimated_tokens=8 + (index % 7),
            estimated_latency_ms=0.1,
            safety_risk=0.0,
        )
    query = "What is Kevin's checkout delivery state?"
    configurations = (
        {},
        {"query_phrase_aware": True, "target_scoped_tombstones": True},
        {
            "query_phrase_aware": True,
            "target_scoped_tombstones": True,
            "relevant_tombstones_first": True,
        },
        {
            "query_phrase_aware": True,
            "target_scoped_tombstones": True,
            "relevant_tombstones_first": True,
            "tombstone_cutover": True,
        },
    )
    for configuration in configurations:
        reference = ProofCarryingStateReconciler(
            operation_aware=True,
            **configuration,
        )
        optimized = ProofCarryingStateReconciler(
            operation_aware=True,
            **configuration,
        )
        optimized._select_operation_memories = types.MethodType(
            module._memory_safe_select_operation_memories,
            optimized,
        )
        expected = reference._select_operation_memories(
            query,
            definitions,
            token_budget=128,
            latency_budget_ms=20.0,
        )
        actual = optimized._select_operation_memories(
            query,
            definitions,
            token_budget=128,
            latency_budget_ms=20.0,
        )
        assert actual == expected


def test_v31_longmemeval_streaming_selector_does_not_retain_document_token_sets(
    monkeypatch,
):
    from wavemind.scientific_memory import MemoryDefinition, MemoryKind
    from wavemind import scientific_reconciliation as reconciliation

    path = ROOT / "benchmarks" / "scientific_longmemeval_v2_backend_v31.py"
    spec = importlib.util.spec_from_file_location(
        "scientific_lme_v31_streaming_memory_test", path
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    class TrackedSet(set):
        live = 0
        peak = 0

        def __init__(self, values=()):
            super().__init__(values)
            type(self).live += 1
            type(self).peak = max(type(self).peak, type(self).live)

        def __del__(self):
            type(self).live -= 1

    monkeypatch.setattr(
        reconciliation,
        "_tokens",
        lambda value: TrackedSet(value.lower().split()),
    )
    definitions = {
        f"memory-{index}": MemoryDefinition(
            memory_id=f"memory-{index}",
            kind=MemoryKind.FACT,
            content=f"document {index} query-token " + "noise " * 100,
            provenance=(f"source-order:{index}", "memory-operation:1"),
            estimated_tokens=20,
            estimated_latency_ms=0.1,
            safety_risk=0.0,
        )
        for index in range(100)
    }
    reference = reconciliation.ProofCarryingStateReconciler(operation_aware=True)
    reference._select_operation_memories(
        "query-token",
        definitions,
        token_budget=100,
        latency_budget_ms=10.0,
    )
    reference_peak = TrackedSet.peak
    gc.collect()
    assert TrackedSet.live == 0

    TrackedSet.peak = 0
    optimized = reconciliation.ProofCarryingStateReconciler(operation_aware=True)
    optimized._select_operation_memories = types.MethodType(
        module._memory_safe_select_operation_memories,
        optimized,
    )
    optimized._select_operation_memories(
        "query-token",
        definitions,
        token_budget=100,
        latency_budget_ms=10.0,
    )
    optimized_peak = TrackedSet.peak
    gc.collect()
    assert TrackedSet.live == 0

    assert reference_peak >= len(definitions) + 1
    assert optimized_peak <= 2

from __future__ import annotations

import ast
import concurrent.futures
import importlib.util
import json
from pathlib import Path


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

from __future__ import annotations

import ast
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RUNNER = ROOT / "benchmarks" / "scientific_mab_v19_final.py"
PROTOCOL = ROOT / "benchmarks" / "scientific_memory_protocol_v19.json"


def _literal_assignment(tree: ast.Module, name: str):
    for node in tree.body:
        if isinstance(node, ast.Assign):
            if any(isinstance(target, ast.Name) and target.id == name for target in node.targets):
                return ast.literal_eval(node.value)
    raise AssertionError(f"missing assignment: {name}")


def test_v19_mab_final_runner_matches_frozen_protocol_without_opening_rows():
    tree = ast.parse(RUNNER.read_text(encoding="utf-8"))
    protocol = json.loads(PROTOCOL.read_text(encoding="utf-8"))

    assert _literal_assignment(tree, "CANDIDATE_SOURCE_SHA") == (
        "c509511f09dbcd3b4206ec1b74a7abc9510d9e73"
    )
    assert _literal_assignment(tree, "PROTOCOL_DIGEST") == protocol["protocol_digest"]
    assert list(_literal_assignment(tree, "FINAL_UNIT_IDS")) == protocol[
        "frozen_admission"
    ]["memoryagentbench_fresh_final_unit_ids"]
    assert _literal_assignment(tree, "MODEL_DIGEST") == protocol["frozen_parameters"][
        "model_digest"
    ]

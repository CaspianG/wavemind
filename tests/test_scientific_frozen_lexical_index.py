from __future__ import annotations

import concurrent.futures
import importlib.util
import json
from pathlib import Path
import sys

import pytest

from benchmarks.scientific_frozen_lexical_index import FrozenLexicalIndex
from wavemind.evidence import file_sha256, validate_artifact_integrity
from wavemind.scientific_memory import MemoryDefinition, MemoryKind
from wavemind.scientific_reconciliation import ProofCarryingStateReconciler


ROOT = Path(__file__).resolve().parents[1]
PROBE = ROOT / "benchmarks" / "scientific_frozen_lexical_index_probe_results.json"
PROBE_INDEX = ROOT / "benchmarks" / ".scientific_frozen_lexical_index_probe.sqlite3"
OFFICIAL_LONGMEM = (
    ROOT.parents[1] / "scientific-evidence" / "upstreams" / "longmemeval-v2"
)
CANDIDATE = ROOT.parent / "wavemind-scientific-v31-official-exact"


def _definitions(*, operation: bool) -> dict[str, MemoryDefinition]:
    definitions: dict[str, MemoryDefinition] = {}
    for index in range(600):
        words = [f"noise-{index}-{offset}" for offset in range(40)]
        if index % 3 == 0:
            words.extend(("kevin", "checkout"))
        if index % 5 == 0:
            words.extend(("delivery", "state"))
        if index % 7 == 0:
            words.extend(("kevin", "checkout", "delivery", "state"))
        provenance = [f"source-order:{index}"]
        if operation:
            provenance.append("memory-operation:1")
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
    return definitions


QUERIES = (
    "What is Kevin's checkout delivery state?",
    "Choose between ['Kevin Checkout', 'Delivery State'] for Kevin's checkout.",
    "Which memory mentions noise-355-9 and checkout?",
)


@pytest.mark.parametrize(
    "configuration",
    (
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
    ),
)
def test_frozen_index_operation_selection_is_exact(
    tmp_path: Path,
    configuration: dict[str, bool],
):
    definitions = _definitions(operation=True)
    reference = ProofCarryingStateReconciler(
        operation_aware=True,
        **configuration,
    )
    indexed = ProofCarryingStateReconciler(
        operation_aware=True,
        **configuration,
    )
    with FrozenLexicalIndex(tmp_path / "operation.sqlite3", definitions) as index:
        for query in QUERIES:
            expected = reference._select_operation_memories(
                query,
                definitions,
                token_budget=128,
                latency_budget_ms=20.0,
            )
            actual = index.select_operation_memories(
                indexed,
                query,
                definitions,
                token_budget=128,
                latency_budget_ms=20.0,
            )
            assert actual == expected


@pytest.mark.parametrize(
    "configuration",
    (
        {},
        {"source_recency_weight": 0.25},
        {"query_phrase_aware": True},
        {"query_phrase_aware": True, "source_recency_weight": 0.25},
    ),
)
def test_frozen_index_ranked_selection_is_exact(
    tmp_path: Path,
    configuration: dict[str, bool | float],
):
    definitions = _definitions(operation=False)
    reference = ProofCarryingStateReconciler(**configuration)
    indexed = ProofCarryingStateReconciler(**configuration)
    with FrozenLexicalIndex(tmp_path / "ranked.sqlite3", definitions) as index:
        for query in QUERIES:
            expected = reference._select_ranked_memories(
                query,
                definitions,
                token_budget=128,
                latency_budget_ms=20.0,
            )
            actual = index.select_ranked_memories(
                indexed,
                query,
                definitions,
                token_budget=128,
                latency_budget_ms=20.0,
            )
            assert actual == expected


def test_frozen_index_keeps_content_and_document_token_sets_on_disk(tmp_path: Path):
    definitions = _definitions(operation=True)

    with FrozenLexicalIndex(tmp_path / "bounded.sqlite3", definitions) as index:
        assert index.definition_count == 600
        assert index.token_count > 500
        assert not hasattr(index, "_normalized_contents_by_memory")
        assert not hasattr(index, "_tokens_by_memory")
        assert index.path.stat().st_size > 0


def test_frozen_index_rejects_changed_definition_membership(tmp_path: Path):
    definitions = _definitions(operation=False)
    reconciler = ProofCarryingStateReconciler()

    with FrozenLexicalIndex(tmp_path / "membership.sqlite3", definitions) as index:
        changed = dict(definitions)
        changed.pop("memory-0000")
        with pytest.raises(RuntimeError, match="definition set changed"):
            index.select_ranked_memories(
                reconciler,
                QUERIES[0],
                changed,
                token_budget=128,
                latency_budget_ms=20.0,
            )


def test_frozen_index_probe_is_reproducible_synthetic_evidence():
    payload = json.loads(PROBE.read_text(encoding="utf-8"))

    assert validate_artifact_integrity(payload) == []
    assert payload["status"] == "pass"
    assert payload["evidence_class"] == "synthetic_performance_probe_not_admission"
    assert payload["held_out_benchmark_rows_used"] is False
    assert payload["workload"]["definition_count"] == 10_000
    assert payload["workload"]["query_count"] == 40
    assert payload["exact_selection_equality"] is True
    assert payload["exact_selection_equality_by_run"] == [True, True, True]
    assert payload["repeat_count"] == 3
    assert payload["indexed"]["maximum_p95_seconds"] <= 1.0
    assert payload["minimum_speedup_at_p95"] > 1.0
    assert payload["index"]["retains_document_content_in_python"] is False
    assert payload["index"]["retains_per_document_token_sets_in_python"] is False
    for source in payload["sources"]:
        path = ROOT / source["path"]
        assert path.stat().st_size == source["bytes"]
        assert file_sha256(path) == source["sha256"]
    assert not PROBE_INDEX.exists()


def _load_backend_module(name: str, filename: str):
    path = ROOT / "benchmarks" / filename
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _synthetic_trajectory() -> dict[str, object]:
    return {
        "id": "synthetic-indexed-trajectory",
        "environment": "shop",
        "goal": "find checkout delivery state",
        "outcome": "success",
        "states": [
            {
                "state_index": index,
                "url": f"https://example.test/checkout/{index}",
                "action": "open checkout",
                "thought": "observe delivery state",
                "accessibility_tree": (
                    f"Checkout account {index} requires delivery state {index % 3}."
                ),
            }
            for index in range(40)
        ],
    }


def test_indexed_prototype_matches_v31_backend_across_worker_threads(tmp_path: Path):
    reference_module = _load_backend_module(
        "scientific_lme_v31_reference_for_index_test",
        "scientific_longmemeval_v2_backend_v31.py",
    )
    indexed_module = _load_backend_module(
        "scientific_lme_indexed_prototype_test",
        "scientific_longmemeval_v2_backend_indexed_prototype.py",
    )
    reference_class = reference_module.register_backend(
        official_repository=OFFICIAL_LONGMEM,
        candidate_repository=CANDIDATE,
    )
    indexed_class = indexed_module.register_backend(
        official_repository=OFFICIAL_LONGMEM,
        candidate_repository=CANDIDATE,
    )
    reference = reference_class({"scratch_root": str(tmp_path / "reference")})
    indexed = indexed_class({"scratch_root": str(tmp_path / "indexed")})
    reference.insert(_synthetic_trajectory())
    indexed.insert(_synthetic_trajectory())
    queries = [f"What delivery state applies to account {index}?" for index in range(8)]
    try:
        expected = [reference.query(query) for query in queries]
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
            actual = list(executor.map(indexed.query, queries))
        assert actual == expected
        assert indexed._indexed_ready is True
        assert indexed._frozen_lexical_index is not None
        assert indexed._frozen_lexical_index.definition_count > 0
        assert indexed._frozen_definitions
        assert indexed._frozen_lexical_index.path.is_file()
    finally:
        reference.close()
        indexed.close()

    assert indexed._frozen_lexical_index is None

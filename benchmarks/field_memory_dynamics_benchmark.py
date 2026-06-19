from __future__ import annotations

import argparse
import json
import math
import shutil
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from wavemind import WaveMind


@dataclass(frozen=True)
class ConflictFact:
    name: str
    query: str
    old_text: str
    new_text: str
    conflict_group: str


CONFLICT_FACTS = (
    ConflictFact(
        name="city",
        query="current city",
        old_text="The user's current city is Berlin.",
        new_text="The user moved and their current city is Lisbon.",
        conflict_group="profile.city",
    ),
    ConflictFact(
        name="budget",
        query="current budget",
        old_text="The user's working budget is 2000 dollars.",
        new_text="The user corrected the working budget to 1200 dollars.",
        conflict_group="profile.budget",
    ),
    ConflictFact(
        name="reply_style",
        query="preferred answer style",
        old_text="The user prefers long detailed answers.",
        new_text="The user now prefers brief practical answers.",
        conflict_group="profile.reply_style",
    ),
    ConflictFact(
        name="profession",
        query="current profession",
        old_text="The user is currently focused on marketing work.",
        new_text="The user corrected their profile: they are a trader.",
        conflict_group="profile.profession",
    ),
    ConflictFact(
        name="skill_level",
        query="python skill level",
        old_text="The user is a beginner Python developer.",
        new_text="The user clarified they are an advanced Python developer.",
        conflict_group="profile.python_level",
    ),
)

CONCEPT_FACTS = (
    "User likes Rust systems programming.",
    "User studies compiler internals.",
    "User optimizes memory allocators and runtime performance.",
)


class DynamicMemoryEncoder:
    vector_dim = 16

    def __init__(self) -> None:
        self._topics = {
            "city": (0, ("current city", "berlin"), ("lisbon", "moved")),
            "budget": (1, ("current budget", "2000"), ("1200",)),
            "reply_style": (2, ("answer style", "long detailed"), ("brief practical", "now prefers")),
            "profession": (3, ("current profession", "marketing"), ("trader",)),
            "skill_level": (4, ("python skill level", "beginner"), ("advanced", "clarified")),
        }

    def encode_vector(self, text: str) -> np.ndarray:
        lowered = text.lower()
        for _, (index, old_markers, new_markers) in self._topics.items():
            if any(marker in lowered for marker in old_markers):
                return self._basis(index)
            if any(marker in lowered for marker in new_markers):
                return self._near_basis(index, index + 8)
        if "rust" in lowered:
            return self._basis(5)
        if "compiler" in lowered:
            return self._near_basis(5, 6)
        if "allocator" in lowered or "runtime" in lowered:
            return self._near_basis(5, 7)
        return self._basis(15)

    def _basis(self, index: int) -> np.ndarray:
        vector = np.zeros(self.vector_dim, dtype=np.float32)
        vector[index] = 1.0
        return vector

    def _near_basis(self, primary: int, secondary: int, primary_weight: float = 0.95) -> np.ndarray:
        vector = np.zeros(self.vector_dim, dtype=np.float32)
        vector[primary] = primary_weight
        vector[secondary] = math.sqrt(max(0.0, 1.0 - primary_weight**2))
        return vector.astype(np.float32)


def run_benchmark(workdir: str | Path) -> dict[str, object]:
    root = Path(workdir)
    if root.exists():
        shutil.rmtree(root)
    root.mkdir(parents=True, exist_ok=True)

    static_result = _run_engine(root / "static.sqlite3", graph=False)
    graph_result = _run_engine(root / "graph.sqlite3", graph=True)
    return {
        "scenario": "field_memory_dynamics",
        "description": (
            "Agent-memory stress test with conflicting facts, stale suppression, "
            "activation spreading, decay, and concept-candidate formation."
        ),
        "wave_static": static_result,
        "wave_graph": graph_result,
    }


def _run_engine(db_path: Path, graph: bool) -> dict[str, float]:
    mind = WaveMind(
        db_path=db_path,
        encoder=DynamicMemoryEncoder(),
        width=16,
        height=16,
        layers=1,
        vector_weight=0.20 if graph else 1.0,
        field_weight=0.0,
        priority_weight=0.0,
        lexical_weight=0.0,
        short_query_lexical_weight=0.0,
        rerank_k=20,
        graph_weight=1.0 if graph else 0.0,
        graph_steps=1,
        graph_expand_k=20,
    )
    expected: dict[str, int] = {}
    stale: dict[str, int] = {}
    for fact in CONFLICT_FACTS:
        stale[fact.name] = mind.remember(
            fact.old_text,
            namespace="agent",
            metadata={"conflict_group": fact.conflict_group},
        )
        expected[fact.name] = mind.remember(
            fact.new_text,
            namespace="agent",
            metadata={"conflict_group": fact.conflict_group},
        )
    for text in CONCEPT_FACTS:
        mind.remember(text, namespace="agent", tags=("systems",))

    top1_hits = 0
    top3_hits = 0
    stale_suppressed = 0
    latencies: list[float] = []

    for fact in CONFLICT_FACTS:
        start = time.perf_counter()
        results = mind.query(fact.query, namespace="agent", top_k=3)
        latencies.append((time.perf_counter() - start) * 1000)
        ids = [result.id for result in results]
        if ids and ids[0] == expected[fact.name]:
            top1_hits += 1
        if expected[fact.name] in ids[:3]:
            top3_hits += 1
        expected_rank = ids.index(expected[fact.name]) if expected[fact.name] in ids else 999
        stale_rank = ids.index(stale[fact.name]) if stale[fact.name] in ids else 999
        if expected_rank < stale_rank:
            stale_suppressed += 1

    before_decay = mind.graph.energy() if graph else 0.0
    mind.consolidate(steps=20)
    after_decay = mind.graph.energy() if graph else 0.0
    mind.query("Rust", namespace="agent", top_k=1)
    concepts = mind.concept_candidates(namespace="agent", min_energy=0.01) if graph else []
    concept_formation = 1.0 if _has_systems_concept(concepts) else 0.0

    return {
        "precision@1": round(top1_hits / len(CONFLICT_FACTS), 4),
        "precision@3": round(top3_hits / len(CONFLICT_FACTS), 4),
        "stale_suppression": round(stale_suppressed / len(CONFLICT_FACTS), 4),
        "concept_formation": concept_formation,
        "decay_ratio": round((after_decay / before_decay), 4) if before_decay > 0 else 0.0,
        "avg_latency_ms": round(sum(latencies) / len(latencies), 4),
    }


def _has_systems_concept(concepts: Iterable[dict[str, object]]) -> bool:
    for concept in concepts:
        label = str(concept.get("label", ""))
        memory_ids = concept.get("memory_ids", [])
        if "systems" in label and isinstance(memory_ids, list) and len(memory_ids) >= 2:
            return True
    return False


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the WaveMind field-memory dynamics benchmark.")
    parser.add_argument("--workdir", type=Path, default=Path("benchmarks/.field_memory_workdir"))
    parser.add_argument("--output", type=Path, default=Path("benchmarks/field_memory_dynamics_results.json"))
    args = parser.parse_args(argv)

    result = run_benchmark(args.workdir)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

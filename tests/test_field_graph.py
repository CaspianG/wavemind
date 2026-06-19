import numpy as np

from wavemind.field_graph import MemoryFieldGraph
from wavemind.storage import MemoryRecord


def make_record(
    id: int,
    text: str,
    vector: list[float],
    *,
    namespace: str = "agent",
    tags: tuple[str, ...] = (),
    metadata: dict | None = None,
    created_at: float = 1.0,
    priority: float = 1.0,
) -> MemoryRecord:
    array = np.array(vector, dtype=np.float32)
    array = array / np.linalg.norm(array)
    return MemoryRecord(
        id=id,
        text=text,
        namespace=namespace,
        tags=tags,
        metadata=metadata or {},
        vector=array,
        pattern=np.zeros((2, 2), dtype=np.float32),
        created_at=created_at,
        updated_at=created_at,
        priority=priority,
    )


def test_graph_spreads_activation_to_related_memory():
    rust = make_record(1, "User likes Rust and systems programming", [1.0, 0.0], tags=("systems",))
    compiler = make_record(2, "User studies compilers and low level code", [0.95, 0.05], tags=("systems",))
    unrelated = make_record(3, "User cooks pasta on weekends", [0.0, 1.0], tags=("cooking",))
    graph = MemoryFieldGraph(similarity_threshold=0.5, propagation_strength=0.5)

    graph.build([rust, compiler, unrelated])
    scores = graph.propagate({1: 1.0}, allowed_ids={1, 2, 3}, steps=2)

    assert scores[2] > 0.05
    assert scores.get(3, 0.0) == 0.0


def test_graph_inhibits_older_conflicting_memory():
    old_city = make_record(
        1,
        "The user's current city is Berlin",
        [1.0, 0.0],
        metadata={"conflict_group": "profile.city"},
        created_at=1.0,
    )
    new_city = make_record(
        2,
        "The user's current city is Lisbon",
        [1.0, 0.0],
        metadata={"conflict_group": "profile.city"},
        created_at=2.0,
    )
    graph = MemoryFieldGraph(similarity_threshold=0.5, conflict_strength=0.75)

    graph.build([old_city, new_city])
    scores = graph.propagate({1: 1.0, 2: 1.0}, allowed_ids={1, 2}, steps=1)

    assert scores[2] > scores[1]


def test_graph_energy_decays_without_input():
    memory = make_record(1, "User likes persistent memory systems", [1.0, 0.0])
    graph = MemoryFieldGraph(decay=0.8)
    graph.build([memory])

    graph.propagate({1: 1.0}, allowed_ids={1}, steps=0)
    before = graph.energy(1)
    graph.decay_energy(steps=3)
    after = graph.energy(1)

    assert 0.0 < after < before


def test_graph_detects_coactivated_concept_candidate():
    rust = make_record(1, "Rust systems programming", [1.0, 0.0], tags=("systems",))
    compiler = make_record(2, "Compiler internals and low level code", [0.98, 0.02], tags=("systems",))
    memory = make_record(3, "Memory allocators and runtime performance", [0.96, 0.04], tags=("systems",))
    graph = MemoryFieldGraph(similarity_threshold=0.5, propagation_strength=0.5)

    graph.build([rust, compiler, memory])
    graph.propagate({1: 1.0, 2: 0.8, 3: 0.7}, allowed_ids={1, 2, 3}, steps=2)
    concepts = graph.concept_candidates(min_energy=0.05, min_size=2)

    assert concepts
    assert set(concepts[0]["memory_ids"]).issuperset({1, 2})
    assert "systems" in concepts[0]["label"] or "programming" in concepts[0]["label"]

"""Preflight arithmetic/graph controls, not a preview of the frozen main corpus."""

from decision_gate_falsifier import ablations, anchor_feasible, exact_orbit, multiply, rank_one
from lc_graph_oracle import bipartite, complement_at


def test_matrix_units():
    for i in range(2):
        for j in range(2):
            for k in range(2):
                for m in range(2):
                    expected = (1 << (2 * i + m)) if j == k else 0
                    assert multiply(1 << (2 * i + j), 1 << (2 * k + m), 1) == expected


def test_rank_one_count_and_identities():
    assert sum(rank_one(v) for v in range(16)) == 6
    assert multiply(9, 14, 1) == multiply(14, 9, 1) == 14
    assert multiply(14, 14, 1) == 7
    assert multiply(0x99, 0xE1, 2) == 0xE1


def test_anchor_system_controls():
    assert anchor_feasible([9], [0], 1) is None
    assert anchor_feasible([1, 8], [0], 1) == 1
    assert anchor_feasible([1, 8], [0], 14) is None


def test_ablation_controls():
    result = ablations()
    assert result["without_closure_implication_fails"]
    assert result["without_atom_restriction_implication_fails"]


def test_small_graph_orbit_and_resource_limit():
    assert bipartite(3, 3) and not bipartite(7, 3)
    assert complement_at(7, 3, 0) == 3
    result = exact_orbit(7, 3, 100, 10)
    assert result["resolved"] and result["possible"] and result["size"] == 4
    assert exact_orbit(7, 3, 1, 10)["resolved"] is False

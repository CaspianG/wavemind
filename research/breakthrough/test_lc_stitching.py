import copy

import pytest

from lc_certificate_check import brute_lc_css, unpack
from lc_graph_oracle import bipartite, complement_at, graph_stabilizers, orbit_table
from lc_stitching import solve, stitch
from lc_stitching_check import verify
from lc_r6_corpus import toric_rows
from test_lc_projector import paulis


@pytest.mark.parametrize("words,expected", [
    (["XZ", "ZX"], True), (["ZIXZ", "YXYI", "IZZX"], False),
    (["XZZXI", "IXZZX", "XIXZZ", "ZXIXZ"], False), (["XXXX", "ZZZZ"], True),
])
def test_known_controls(words, expected):
    n, rows = len(words[0]), paulis(words)
    result = solve(rows, n)
    assert (result["status"] == "css_equivalent") == expected
    assert result["status"] != "unresolved"
    verify(unpack(rows, 2 * n), result)


def test_forced_order_three_negative_and_tamper():
    rows = paulis(["XZZXI", "IXZZX", "XIXZZ", "ZXIXZ"])
    result = solve(rows, 5)
    assert result["certificate_type"] == "forced_order_three_block"
    verify(unpack(rows, 10), result)
    bad = copy.deepcopy(result)
    bad["forced_b_constraints"] = []
    with pytest.raises(AssertionError):
        verify(unpack(rows, 10), bad)


def test_stitching_disjoint_masks_not_just_one_candidate():
    # Full local algebra on S=0: trace-one affine slice has independent a,b,c.
    n = 2
    particular = (3 << n) | (3 << (2 * n))  # order-three blocks at both sites
    basis = [1 << i for i in range(3 * n)]
    projector, remaining, pieces, considered = stitch(particular, basis, n)
    assert remaining == 0 and len(pieces) == 2 and considered <= len(basis) + 1
    assert not ((projector >> n) & (projector >> (2 * n)) & 3)
    assert int(pieces[0]["sites_hex"], 16) & int(pieces[1]["sites_hex"], 16) == 0


def test_no_affine_dimension_cap_and_invalid_commutation():
    result = solve([], 30)
    assert result["affine_dimension"] == 90 and result["status"] == "css_equivalent"
    verify(unpack([], 60), result)
    with pytest.raises(ValueError, match="noncommuting"):
        solve(paulis(["X", "Z"]), 1)


def test_graph_oracle_triangle_and_involution():
    triangle = 7
    assert not bipartite(triangle, 3)
    assert bipartite(complement_at(triangle, 3, 0), 3)
    assert complement_at(complement_at(triangle, 3, 0), 3, 0) == triangle
    table = orbit_table(3)
    assert len(table) == 8 and table[triangle]["css_equivalent"]
    for word in range(8):
        rows = graph_stabilizers(word, 3)
        expected = brute_lc_css(unpack(rows, 6))
        assert expected == table[word]["css_equivalent"]
        result = solve(rows, 3)
        assert (result["status"] == "css_equivalent") == expected
        verify(unpack(rows, 6), result)


def test_toric_constructor_on_smaller_preflight_size():
    rows = toric_rows(2)
    result = solve(rows, 8)
    assert result["status"] == "css_equivalent" and result["stabilizer_rank"] == 6
    verify(unpack(rows, 16), result)

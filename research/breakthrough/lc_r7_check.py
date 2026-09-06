"""Dense intermediate-invariant audit of the frozen packed R6 stitch helper."""

from itertools import product

import numpy as np

from lc_certificate_check import dense_css, dense_rank, transformed, unpack
from lc_r7_frames import packed, unpacked
from lc_stitching import stitch


def abc(matrix):
    n = len(matrix)
    return sum(int(bit) << (i + block * n) for block, bits in enumerate(
        (matrix[:, 0, 0], matrix[:, 0, 1], matrix[:, 1, 0])) for i, bit in enumerate(bits))


def from_abc(value, n):
    a, b, c = [np.array([(value >> (i + j * n)) & 1 for i in range(n)], dtype=np.uint8)
               for j in range(3)]
    return np.stack((a, b, c, 1 ^ a), axis=1).reshape(n, 2, 2)


def is_projector(matrix):
    a, b, c, d = matrix.reshape(len(matrix), 4).T
    return bool(np.all((a ^ d) == 1) and np.all((a * d ^ b * c) == 0))


def dense_kernel(matrix):
    """Full ordinary annihilator via dense reduced row elimination."""
    reduced = matrix.copy()
    pivots = []
    for column in range(reduced.shape[1]):
        locations = np.flatnonzero(reduced[len(pivots):, column])
        if not len(locations):
            continue
        row = len(pivots)
        chosen = row + int(locations[0])
        reduced[[row, chosen]] = reduced[[chosen, row]]
        others = np.flatnonzero(reduced[:, column])
        others = others[others != row]
        reduced[others] ^= reduced[row]
        pivots.append(column)
    free = [j for j in range(reduced.shape[1]) if j not in pivots]
    kernel = np.zeros((len(free), reduced.shape[1]), dtype=np.uint8)
    for i, column in enumerate(free):
        kernel[i, column] = 1
        kernel[i, pivots] = reduced[:len(pivots), column]
    assert not np.any((matrix @ kernel.T) % 2)
    assert dense_rank(kernel) == matrix.shape[1] - len(pivots)
    return kernel


def check(case):
    n, blocks = case["n"], case["blocks"]
    rows = unpack([int(v, 16) for v in case["rows_hex"]], 2 * n)
    units = np.array([unpacked(int(v, 16), n) for v in case["matrix_units_hex"]])
    particular = unpacked(int(case["particular_hex"], 16), n)
    basis = [unpacked(int(v, 16), n) for v in case["basis_hex"]]
    rank = dense_rank(rows)
    assert rank == 2 * blocks and n == blocks * case["length"]
    assert case["length"] >= 2 and case["length"] % 2 == 0
    assert np.all((rows[:, :n] @ rows[:, n:].T ^ rows[:, n:] @ rows[:, :n].T) % 2 == 0)
    flat_units = units.reshape(4 * blocks, 4 * n)
    assert dense_rank(flat_units) == 4 * blocks
    products = (units[:, None] @ units[None, :]) % 2
    expected_products = np.zeros_like(products)
    for block in range(blocks):
        for a, b, d in product(range(2), repeat=3):
            expected_products[4 * block + 2 * a + b, 4 * block + 2 * b + d] = units[4 * block + 2 * a + d]
    assert np.array_equal(products, expected_products)
    assert dense_rank(units[:, :, 0, 0] ^ units[:, :, 1, 1]) == blocks
    assert len(basis) == 3 * blocks and dense_rank(np.array(basis).reshape(len(basis), 4 * n)) == 3 * blocks
    assert np.all((particular[:, 0, 0] ^ particular[:, 1, 1]) == 1)
    assert all(np.all((v[:, 0, 0] ^ v[:, 1, 1]) == 0) for v in basis)
    checked_maps = 0
    pair_rows = np.stack((rows[:, :n], rows[:, n:]), axis=-1)
    dual = dense_kernel(rows)
    pair_dual = np.stack((dual[:, :n], dual[:, n:]), axis=-1)
    constraints = np.einsum("rni,snj->rsnij", pair_rows, pair_dual).reshape(-1, 4 * n)
    full_algebra_dimension = 4 * n - dense_rank(constraints)
    assert full_algebra_dimension == 4 * blocks

    def preserving(member):
        nonlocal checked_maps
        checked_maps += 1
        assert dense_rank(np.vstack((flat_units, member.reshape(1, 4 * n)))) == 4 * blocks
        mapped = np.einsum("rni,nij->rnj", pair_rows, member) % 2
        mapped = np.concatenate((mapped[:, :, 0], mapped[:, :, 1]), axis=1)
        assert dense_rank(np.vstack((rows, mapped))) == rank

    for member in [*units, particular, *basis]:
        preserving(member)
    packed_result, uncovered, reported_pieces, considered = stitch(abc(particular), [abc(v) for v in basis], n)
    identity = np.tile(np.eye(2, dtype=np.uint8), (n, 1, 1))
    remaining, assembled, naive = identity.copy(), np.zeros_like(identity), np.zeros_like(identity)
    pieces, complete_at, single_candidates = [], None, 0
    for index in range(len(basis) + 1):
        candidate = particular if index == 0 else particular ^ basis[index - 1]
        preserving(candidate)
        assert np.all((candidate[:, 0, 0] ^ candidate[:, 1, 1]) == 1)
        good = identity ^ ((candidate @ candidate) % 2) ^ candidate
        preserving(good)
        assert np.all(good[:, 0, 1] == 0) and np.all(good[:, 1, 0] == 0)
        assert np.array_equal(good[:, 0, 0], good[:, 1, 1])
        single_candidates += int(is_projector(candidate))
        naive ^= (good @ candidate) % 2
        if complete_at is not None:
            continue
        selected = (remaining @ good) % 2
        piece = (selected @ candidate) % 2
        preserving(selected)
        preserving(piece)
        if np.any(selected):
            sites = sum(int(bit) << j for j, bit in enumerate(selected[:, 0, 0]))
            pieces.append({"candidate_index": index, "sites_hex": hex(sites)})
        assembled ^= piece
        remaining = (remaining @ (identity ^ good)) % 2
        preserving(assembled)
        preserving(remaining)
        assert np.array_equal((assembled @ assembled) % 2, assembled)
        assert not np.any((assembled @ remaining) % 2)
        if not np.any(remaining):
            complete_at = index + 1
    assert uncovered == 0 and not np.any(remaining)
    assert considered == complete_at <= len(basis) + 1
    assert pieces == reported_pieces and np.array_equal(from_abc(packed_result, n), assembled)
    assert is_projector(assembled) and np.array_equal((assembled @ assembled) % 2, assembled)
    preserving(naive)
    gates = []
    p0 = np.array([[1, 0], [0, 0]], dtype=np.uint8)
    for member in assembled:
        for gate in product((0, 1), repeat=4):
            if (gate[0] * gate[3] ^ gate[1] * gate[2]) != 1:
                continue
            candidate_gate = np.array(gate, dtype=np.uint8).reshape(2, 2)
            if np.array_equal((member @ candidate_gate) % 2, candidate_gate @ p0):
                gates.append(gate)
                break
        else:
            raise AssertionError("no local diagonalizing Clifford")
    assert dense_css(transformed(rows, gates))
    # Compute determinant metadata exactly over F2, without floating point.
    a, b, c, d = particular.reshape(n, 4).T
    initial_bad = int(np.count_nonzero(a * d ^ b * c))
    hard = blocks >= 2 and case["basis_mode"] == "localized" and case["particular_mode"] == "all_order_three"
    if hard:
        assert initial_bad == n and single_candidates == 0 and len(pieces) == blocks
    return {"status": "all_dense_invariants_verified", "n": n, "stabilizer_rank": rank,
            "algebra_dimension": full_algebra_dimension, "affine_dimension": len(basis),
            "matrix_unit_products_checked": (4 * blocks) ** 2, "preserving_maps_checked": checked_maps,
            "initial_bad_sites": initial_bad, "global_single_candidates": single_candidates,
            "candidates_considered": considered, "pieces": pieces, "hard_arm": hard,
            "unpartitioned_sum_is_projector": is_projector(naive),
            "projector_matrix_hex": hex(packed(assembled)), "local_cliffords": gates}


def non_algebra_control():
    identity = np.tile(np.eye(2, dtype=np.uint8), (2, 1, 1))
    p = np.array([[0, 0], [0, 1]], dtype=np.uint8)
    f = np.array([[0, 1], [1, 1]], dtype=np.uint8)
    h = np.array([[0, 1], [1, 0]], dtype=np.uint8)
    particular, direction = np.array([p, f]), np.array([h, h])
    generators = [identity, particular, direction]
    span = set()
    for coefficients in product((0, 1), repeat=3):
        value = np.zeros_like(identity)
        for coefficient, g in zip(coefficients, generators, strict=True):
            if coefficient:
                value ^= g
        span.add(packed(value))
    assert len(span) == 8
    closure_failure = any(packed((a @ b) % 2) not in span for a in generators for b in generators)
    affine = [particular ^ (identity if a else 0) ^ (direction if b else 0)
              for a, b in product((0, 1), repeat=2)]
    assert all(not is_projector(member) for member in affine)
    assert all(any(is_projector(member[site:site + 1]) for member in affine) for site in range(2))
    result, remaining, pieces, _ = stitch(abc(particular), [abc(identity), abc(direction)], 2)
    outside = packed(from_abc(result, 2)) not in span
    assert closure_failure and outside and remaining == 0
    return {"status": "omitting_algebra_closure_refuted", "span_size": len(span),
            "affine_points": len(affine), "no_global_projector": True,
            "per_site_feasible": True, "stitched_output_outside_span": outside, "pieces": pieces}

"""Independent dense constraint, partition, and certificate audit for R8.

Does not import the scalar solver or R5/R6 search helpers. Matrix rank and
CSS witness checking reuse only the frozen dense R5 certificate checker.
"""

from itertools import product

import numpy as np

from lc_certificate_check import dense_css, dense_rank, transformed, unpack


def kernel(matrix):
    matrix = matrix.copy()
    pivots, rank = [], 0
    for col in range(matrix.shape[1]):
        indices = np.flatnonzero(matrix[rank:, col])
        if not len(indices):
            continue
        selected = rank + int(indices[0])
        matrix[[rank, selected]] = matrix[[selected, rank]]
        indices = np.flatnonzero(matrix[:, col])
        indices = indices[indices != rank]
        matrix[indices] ^= matrix[rank]
        pivots.append(col)
        rank += 1
        if rank == matrix.shape[0]:
            break
    vectors = []
    for free in set(range(matrix.shape[1])) - set(pivots):
        vector = np.zeros(matrix.shape[1], dtype=np.uint8)
        vector[free] = 1
        vector[pivots] = matrix[:rank, free]
        vectors.append(vector)
    return np.asarray(vectors, dtype=np.uint8).reshape(-1, matrix.shape[1])


def invariance(matrix, annihilators, scalar=False):
    n = matrix.shape[1] // 2
    x, z = matrix[:, :n], matrix[:, n:]
    u, v = annihilators[:, :n], annihilators[:, n:]
    xu, xv = x[:, None, :] * u[None, :, :], x[:, None, :] * v[None, :, :]
    zu, zv = z[:, None, :] * u[None, :, :], z[:, None, :] * v[None, :, :]
    if scalar:
        return (xu ^ zv).reshape(-1, n)
    return np.stack((xu, xv, zu, zv), axis=-1).reshape(-1, 4 * n)


def check(rows, n, result):
    assert result["n"] == n
    matrix = unpack(rows, 2 * n)
    rank = dense_rank(matrix)
    annihilators = kernel(matrix)
    constraints = invariance(matrix, annihilators, scalar=True)
    basis = unpack([int(v, 16) for v in result["scalar_basis_hex"]], n)
    dimension = n - dense_rank(constraints)
    assert dense_rank(basis) == len(basis) == dimension
    assert not np.any((constraints @ basis.T) % 2)
    groups = [c["sites"] for c in result["components"]]
    assert len(groups) == dimension
    assert sorted(i for group in groups for i in group) == list(range(n))
    assert all(group and sorted(set(group)) == group for group in groups)
    assert len({tuple(group) for group in groups}) == dimension
    projected_ranks, possible, systems = [], True, 0
    expected_blocks = [None] * n
    anchors = [p for p in product((0, 1), repeat=4)
               if p[0] + p[3] == 1 and (p[0] * p[3] + p[1] * p[2]) % 2 == 0]
    for component in result["components"]:
        sites, attempts = component["sites"], component["attempts"]
        indicator = np.zeros(n, dtype=np.uint8)
        indicator[sites] = 1
        assert not np.any((constraints @ indicator) % 2)
        size = len(sites)
        local = matrix[:, sites + [n + i for i in sites]]
        saved = unpack([int(v, 16) for v in component["rows_hex"]], 2 * size)
        local_rank = dense_rank(local)
        projected_ranks.append(local_rank)
        assert dense_rank(saved) == len(saved) == local_rank
        assert dense_rank(np.concatenate((saved, local))) == local_rank
        dual = unpack([int(v, 16) for v in component["annihilator_hex"]], 2 * size)
        assert dense_rank(dual) == len(dual) == 2 * size - local_rank
        assert not np.any((saved @ dual.T) % 2)
        equations = invariance(saved, dual)
        trace = np.zeros((size, 4 * size), dtype=np.uint8)
        for i in range(size):
            trace[i, 4 * i] = trace[i, 4 * i + 3] = 1
        fixed = np.eye(4, 4 * size, dtype=np.uint8)
        system = np.concatenate((equations, trace, fixed))
        system_rank = dense_rank(system)
        assert 1 <= len(attempts) <= 6
        local_possible = False
        for j, attempt in enumerate(attempts):
            systems += 1
            assert attempt["anchor"] == list(anchors[j])
            rhs = np.concatenate((np.zeros(len(equations), dtype=np.uint8),
                                  np.ones(size, dtype=np.uint8), np.array(anchors[j], dtype=np.uint8)))
            consistent = dense_rank(np.column_stack((system, rhs))) == system_rank
            assert attempt["consistent"] == consistent
            if consistent:
                assert j == len(attempts) - 1
                value = int(attempt["solution_hex"], 16)
                assert 0 <= value < 1 << (4 * size)
                solution = unpack([value], 4 * size)[0]
                assert np.array_equal((system @ solution) % 2, rhs)
                local_blocks = solution.reshape(size, 2, 2)
                assert all(dense_rank(block) == 1 for block in local_blocks)
                assert np.array_equal((local_blocks @ local_blocks) % 2, local_blocks)
                for k, site in enumerate(sites):
                    expected_blocks[site] = local_blocks[k].reshape(4).tolist()
                local_possible = True
            else:
                indices = attempt["contradiction"]
                assert indices and len(set(indices)) == len(indices)
                assert all(0 <= i < len(system) for i in indices)
                assert not np.any(np.bitwise_xor.reduce(system[indices], axis=0))
                assert np.bitwise_xor.reduce(rhs[indices]) == 1
        if not local_possible:
            assert len(attempts) == 6
        possible &= local_possible
    assert sum(projected_ranks) == rank
    assert result["anchor_systems"] == systems <= 6 * dimension
    assert result["status"] == ("css_equivalent" if possible else "not_lc_css")
    if possible:
        assert result["projector_blocks"] == expected_blocks
        assert dense_css(transformed(matrix, result["gates"]))
    else:
        assert result["projector_blocks"] is None and result["gates"] is None
    return {"components": dimension, "component_sizes": [len(group) for group in groups],
            "anchor_systems": systems, "rank": rank, "possible": possible}

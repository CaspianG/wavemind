"""Independent dense certificate checker. Does not import the search solver.

Checks witness matrices, or necessary constraints that imply impossibility.
For an affine-exhaustion proof, it rebuilds the solution set of the supplied
necessary constraints with opposite-pivot elimination and binary enumeration.
"""

from itertools import product

import numpy as np


def dense_pbb(record):
    ell, m = record["ell"], record["m"]
    size = ell * m
    matrices = []
    for name in "ABCD":
        matrix = np.zeros((size, size), dtype=np.uint8)
        for dx, dy in record[name + "_terms"]:
            for row in range(size):
                i, j = divmod(row, m)
                matrix[row, ((i + dx) % ell) * m + (j + dy) % m] ^= 1
        matrices.append(matrix)
    a, b, c, d = matrices
    zero = np.zeros_like(a)
    return np.block([[a, b, c, d], [zero, zero, b.T, a.T]])


def dense_rank(matrix):
    matrix = matrix.copy()
    rank = 0
    for col in range(matrix.shape[1]):
        locations = np.flatnonzero(matrix[rank:, col])
        if not len(locations):
            continue
        chosen = rank + int(locations[0])
        matrix[[rank, chosen]] = matrix[[chosen, rank]]
        below = np.flatnonzero(matrix[rank + 1:, col]) + rank + 1
        matrix[below] ^= matrix[rank]
        rank += 1
        if rank == matrix.shape[0]:
            break
    return rank


def unpack(values, width):
    return np.array([[(v >> j) & 1 for j in range(width)] for v in values], dtype=np.uint8).reshape(-1, width)


def dense_css(matrix):
    n = matrix.shape[1] // 2
    return dense_rank(matrix) == dense_rank(matrix[:, :n]) + dense_rank(matrix[:, n:])


def transformed(matrix, gates):
    n = matrix.shape[1] // 2
    gates = np.asarray(gates, dtype=np.uint8)
    assert gates.shape == (n, 4) and np.all(gates <= 1)
    a, b, c, d = gates.T
    assert np.all((a * d ^ b * c) == 1)
    x, z = matrix[:, :n], matrix[:, n:]
    return np.concatenate((x * a ^ z * c, x * b ^ z * d), axis=1)


def binary_affine_vectors(matrix, rhs):
    """Opposite-pivot reference elimination; no Gray code or solver import."""
    width = matrix.shape[1]
    reduced = {}
    for row_array, bit in zip(matrix, rhs, strict=True):
        value = sum(int(b) << j for j, b in enumerate(row_array))
        bit = int(bit)
        while value:
            pivot = (value & -value).bit_length() - 1
            if pivot not in reduced:
                reduced[pivot] = (value, bit)
                break
            old, old_bit = reduced[pivot]
            value ^= old
            bit ^= old_bit
        else:
            if bit:
                return
    free = [j for j in range(width) if j not in reduced]
    if len(free) > 18:
        raise ValueError("certificate residual exceeds registered verifier bound")
    for choices in product((0, 1), repeat=len(free)):
        solution = sum(bit << j for bit, j in zip(choices, free, strict=True))
        for j in sorted(reduced, reverse=True):
            row, bit = reduced[j]
            bit ^= (row & solution).bit_count() % 2
            solution |= bit << j
        yield solution


def verify_certificate(matrix, result):
    n = matrix.shape[1] // 2
    rank = dense_rank(matrix)
    assert n == result["n"] and rank == result["stabilizer_rank"]
    # Sparse commutation check, independent of the packed solver representation.
    for row in matrix:
        columns = np.flatnonzero(np.concatenate((row[n:], row[:n])))
        assert not np.any(np.bitwise_xor.reduce(matrix[:, columns], axis=1, initial=0))
    if result["status"] == "unresolved":
        return "unresolved_not_a_certificate"
    if result["status"] == "css_equivalent":
        assert dense_css(transformed(matrix, result["gates"]))
        return "local_clifford_witness_verified"
    assert result["status"] == "not_lc_css"
    constraints = result["constraints"]
    assert constraints
    indices = [c["generator"] for c in constraints]
    assert all(0 <= i < len(matrix) for i in indices)
    dual_values = [int(c["annihilator_hex"], 16) for c in constraints]
    assert all(0 <= w < 1 << (2 * n) for w in dual_values)
    dual = unpack(dual_values, 2 * n)
    for row in matrix:
        assert not np.any(np.bitwise_xor.reduce(dual[:, np.flatnonzero(row)], axis=1, initial=0))
    g = matrix[indices]
    x, z, u, v = g[:, :n], g[:, n:], dual[:, :n], dual[:, n:]
    coefficients = np.concatenate((x * u ^ z * v, x * v, z * u), axis=1)
    rhs = np.bitwise_xor.reduce(z * v, axis=1)
    if result["certificate_type"] == "linear_contradiction":
        assert not np.any(np.bitwise_xor.reduce(coefficients, axis=0))
        assert int(np.bitwise_xor.reduce(rhs)) == 1
        return "linear_impossibility_certificate_verified"
    assert result["certificate_type"] == "affine_exhaustion"
    checked = 0
    mask = (1 << n) - 1
    for value in binary_affine_vectors(coefficients, rhs):
        checked += 1
        assert ((value >> n) & mask) & (value >> (2 * n))
    assert checked == result["assignments_checked"] == 1 << result["affine_dimension"]
    return "exhaustive_impossibility_certificate_verified"


def brute_lc_css(matrix):
    gates = [g for g in product((0, 1), repeat=4) if (g[0] * g[3] ^ g[1] * g[2]) == 1]
    for assignment in product(gates, repeat=matrix.shape[1] // 2):
        if dense_css(transformed(matrix, assignment)):
            return True
    return False

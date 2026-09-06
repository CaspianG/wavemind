"""Dense checker for R6 forced-bit certificates; no search-solver import."""

import numpy as np

from lc_certificate_check import dense_rank, unpack, verify_certificate


def verify(matrix, result):
    if result.get("certificate_type") != "forced_order_three_block":
        return verify_certificate(matrix, result)
    n = matrix.shape[1] // 2
    assert result["status"] == "not_lc_css" and n == result["n"]
    assert dense_rank(matrix) == result["stabilizer_rank"]
    for g in matrix:
        swap = np.concatenate((g[n:], g[:n]))
        assert not np.any(np.bitwise_xor.reduce(matrix[:, np.flatnonzero(swap)], axis=1, initial=0))
    qubit = result["qubit"]
    assert isinstance(qubit, int) and 0 <= qubit < n
    for kind, block in (("b", 1), ("c", 2)):
        constraints = result[f"forced_{kind}_constraints"]
        assert constraints
        equation_sum = np.zeros(3 * n, dtype=np.uint8)
        rhs = 0
        for item in constraints:
            gi, word = item["generator"], int(item["annihilator_hex"], 16)
            assert 0 <= gi < len(matrix) and 0 <= word < 1 << (2 * n)
            w = unpack([word], 2 * n)[0]
            assert not np.any(np.bitwise_xor.reduce(matrix[:, np.flatnonzero(w)], axis=1, initial=0))
            x, z = matrix[gi, :n], matrix[gi, n:]
            u, v = w[:n], w[n:]
            equation_sum ^= np.concatenate((x * u ^ z * v, x * v, z * u))
            rhs ^= int(np.bitwise_xor.reduce(z * v))
        target = np.zeros(3 * n, dtype=np.uint8)
        target[block * n + qubit] = 1
        assert np.array_equal(equation_sum, target) and rhs == 1
    return "forced_order_three_impossibility_verified"

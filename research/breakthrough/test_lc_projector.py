import copy
import random

import numpy as np
import pytest

from lc_certificate_check import brute_lc_css, dense_pbb, dense_rank, unpack, verify_certificate
from lc_projector import CLIFFORDS, nullspace, pbb_rows, solve, transform


def paulis(words):
    n = len(words[0])
    return [sum((int(p in "XY") << i) | (int(p in "ZY") << (i + n))
                for i, p in enumerate(word)) for word in words]


@pytest.mark.parametrize("words,expected", [
    (["XZ", "ZX"], True),
    (["ZIXZ", "YXYI", "IZZX"], False),
    (["XZZXI", "IXZZX", "XIXZZ", "ZXIXZ"], False),
    (["XXXX", "ZZZZ"], True),
    (["I"], True),
])
def test_named_codes_against_all_six_power_n(words, expected):
    n, rows = len(words[0]), paulis(words)
    result = solve(rows, n)
    assert (result["status"] == "css_equivalent") == expected
    assert result["status"] != "unresolved"
    assert brute_lc_css(unpack(rows, 2 * n)) == expected
    verify_certificate(unpack(rows, 2 * n), result)


def test_random_commuting_codes_against_independent_brute():
    rng = random.Random(2026090605)
    for n in range(1, 5):
        for _ in range(12):
            rows = [1 << (n + i) for i in range(rng.randrange(n + 1))]
            for _ in range(30):
                if n > 1 and rng.randrange(2):
                    control, target = rng.sample(range(n), 2)
                    rows = [r ^ (((r >> control) & 1) << target)
                            ^ (((r >> (n + target)) & 1) << (n + control)) for r in rows]
                else:
                    rows = transform(rows, n, [rng.choice(CLIFFORDS) for _ in range(n)])
            result = solve(rows, n)
            matrix = unpack(rows, 2 * n)
            assert result["status"] != "unresolved"
            assert (result["status"] == "css_equivalent") == brute_lc_css(matrix)
            verify_certificate(matrix, result)


def test_scrambled_steane_row_changes_and_dual():
    words = ["XXXXIII", "XXIIXXI", "XIXIXIX", "ZZZZIII", "ZZIIZZI", "ZIZIZIZ"]
    rows = transform(paulis(words), 7, [CLIFFORDS[i % 6] for i in range(7)])
    rows = [rows[i] ^ rows[-1] for i in range(5)] + rows[-1:] + [rows[0]]
    matrix = unpack(rows, 14)
    dual = unpack(nullspace(rows, 14), 14)
    assert dense_rank(dual) == 14 - dense_rank(matrix)
    assert np.all((matrix @ dual.T) % 2 == 0)
    result = solve(rows, 7)
    assert result["status"] == "css_equivalent"
    verify_certificate(matrix, result)


def test_independent_polynomial_constructors_and_cancellation():
    record = {"ell": 3, "m": 2, "A_terms": [[1, 0], [1, 0], [0, 1]],
              "B_terms": [[2, 1]], "C_terms": [], "D_terms": []}
    assert np.array_equal(unpack(pbb_rows(record), 24), dense_pbb(record))


def test_invalid_and_tampered_certificates_rejected():
    with pytest.raises(ValueError, match="noncommuting"):
        solve(paulis(["X", "Z"]), 1)
    rows = paulis(["ZIXZ", "YXYI", "IZZX"])
    result = solve(rows, 4)
    assert result["status"] == "not_lc_css"
    changed = copy.deepcopy(result)
    changed["constraints"][0]["annihilator_hex"] = "0xffff"
    with pytest.raises(AssertionError):
        verify_certificate(unpack(rows, 8), changed)
    changed = copy.deepcopy(solve(paulis(["XZ", "ZX"]), 2))
    changed["gates"][0] = [0, 0, 0, 0]
    with pytest.raises(AssertionError):
        verify_certificate(unpack(paulis(["XZ", "ZX"]), 4), changed)


def test_resource_limit_does_not_claim_impossibility():
    result = solve([], 7, max_dimension=0)
    assert result["status"] == "unresolved" and result["reason"] == "affine_dimension_bound"

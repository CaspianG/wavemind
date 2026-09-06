"""Preflight outside the complete n<=3 domain; no main corpus before freeze."""

from copy import deepcopy

import numpy as np
import pytest

from experiment_r8 import r6_theorem
from lc_certificate_check import dense_rank, unpack
from lc_r8_corpus import brute_css
from lc_scalar_check import check, invariance, kernel
from lc_scalar_components import PROJECTORS, affine, solve


def paulis(words):
    n = len(words[0])
    return [sum(((char in "XY") << i) | ((char in "ZY") << (n + i))
                for i, char in enumerate(word)) for word in words]


@pytest.mark.parametrize("words,expected", [
    (["XXXX", "ZZZZ"], True),
    (["XZZXI", "IXZZX", "XIXZZ", "ZXIXZ"], False),
])
def test_known_four_and_five_qubit_controls(words, expected):
    rows, n = paulis(words), len(words[0])
    result = solve(rows, n)
    assert check(rows, n, result)["possible"] == expected
    assert r6_theorem(rows, n)["possible"] == expected
    assert (brute_css(rows, n)["positive_frames"] > 0) == expected


def test_binary_projector_count_and_affine_contradiction():
    assert len(PROJECTORS) == 6 and len(set(PROJECTORS)) == 6
    assert affine([(3, 0), (3, 1)], 2) == {"consistent": False, "contradiction": [0, 1]}
    result = affine([(3, 1)], 3)
    assert result["consistent"] and result["rank"] == 1 and len(result["basis"]) == 2
    assert (result["particular"] & 3).bit_count() % 2 == 1
    assert all((v & 3).bit_count() % 2 == 0 for v in result["basis"])


def test_undecomposed_one_anchor_is_insufficient():
    rows = paulis(["XXII", "ZZII", "IIXX", "IIZZ"])
    matrix = unpack(rows, 8)
    equations = invariance(matrix, kernel(matrix))
    blocks = np.array([[1, 0, 0, 0]] * 2 + [[0, 1, 1, 1]] * 2, dtype=np.uint8)
    assert not np.any((equations @ blocks.reshape(-1)) % 2)
    assert [dense_rank(b.reshape(2, 2)) for b in blocks] == [1, 1, 2, 2]
    result = solve(rows, 4)
    assert check(rows, 4, result)["components"] == 2


@pytest.mark.parametrize("mutation", ["partition", "projector", "contradiction"])
def test_dense_checker_rejects_corrupted_witnesses(mutation):
    words = ["XZZXI", "IXZZX", "XIXZZ", "ZXIXZ"] if mutation == "contradiction" else ["XXXX", "ZZZZ"]
    rows, n = paulis(words), len(words[0])
    result = deepcopy(solve(rows, n))
    if mutation == "partition":
        result["components"][0]["sites"].pop()
    elif mutation == "projector":
        result["projector_blocks"][0][0] ^= 1
    else:
        result["components"][0]["attempts"][0]["contradiction"] = []
    with pytest.raises(AssertionError):
        check(rows, n, result)

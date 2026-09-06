"""Preflight only: one block lies outside every registered main block count."""

from copy import deepcopy

import numpy as np
import pytest

from lc_r7_check import abc, check, from_abc, non_algebra_control
from lc_r7_frames import generate, packed, unpacked


def one_block():
    return generate(2, 1, 12345, "localized", "all_order_three")


def test_single_block_control_and_dense_witness():
    result = check(one_block())
    assert result["status"] == "all_dense_invariants_verified"
    assert result["algebra_dimension"] == 4
    assert result["affine_dimension"] == 3
    assert result["initial_bad_sites"] == 2
    assert len(result["pieces"]) == 1
    assert not result["hard_arm"]


def test_non_algebra_assumption_control():
    result = non_algebra_control()
    assert result["stitched_output_outside_span"]
    assert result["no_global_projector"] and result["per_site_feasible"]


@pytest.mark.parametrize("field", ["matrix_units_hex", "rows_hex", "basis_hex"])
def test_corrupted_input_is_rejected(field):
    case = deepcopy(one_block())
    case[field][0] = "0x0"
    with pytest.raises(AssertionError):
        check(case)


def test_packing_distinguishes_trace_zero_and_trace_one():
    for word in range(256):
        matrix = unpacked(word, 2)
        assert packed(matrix) == word
        if np.all((matrix[:, 0, 0] ^ matrix[:, 1, 1]) == 1):
            assert np.array_equal(from_abc(abc(matrix), 2), matrix)

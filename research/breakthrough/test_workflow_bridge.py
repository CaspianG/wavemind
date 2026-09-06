"""Preflight on separate one/two-qubit controls; no main run before freeze."""

from fractions import Fraction as F

import pytest

from workflow_bridge_control import exact_decode, image, local_image, packed, transport


def test_unencoded_uniform_qubit_has_three_quarter_failure():
    result = exact_decode([], [[F(1, 4)] * 4])
    assert result["failure"] == "3/4"
    assert result["parameters"] == {"n": 1, "k": 1, "d": 1}
    assert len(result["errors"]) == 4


def test_bell_state_has_no_logical_error_under_pauli_channel():
    result = exact_decode(packed(["XX", "ZZ"]), [[F(1, 4)] * 4] * 2)
    assert result["failure"] == "0"
    assert result["parameters"] == {"n": 2, "k": 0, "d": None}


def test_non_symmetric_gate_and_channel_round_trip():
    gate, inverse = [1, 1, 1, 0], [0, 1, 1, 1]
    channel = [[F(1, 2), F(1, 4), F(1, 8), F(1, 8)]]
    assert transport(transport(channel, [gate]), [inverse]) == channel
    assert [local_image(p, gate) for p in range(4)] == [0, 3, 1, 2]
    assert all(image(image(p, [gate]), [inverse]) == p for p in range(4))


def test_invalid_distribution_and_noncommuting_input_rejected():
    with pytest.raises(ValueError, match="probability"):
        exact_decode([], [[F(1), F(-1), F(1), F(0)]])
    with pytest.raises(ValueError, match="noncommuting"):
        exact_decode(packed(["X", "Z"]), [[F(1, 4)] * 4])

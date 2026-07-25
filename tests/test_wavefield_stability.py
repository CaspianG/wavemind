from __future__ import annotations

import numpy as np
import pytest

from wavemind.core import WaveField


def test_wavefield_remains_finite_under_repeated_strong_updates() -> None:
    field = WaveField(
        width=18,
        height=18,
        layers=3,
        decay=0.998,
        speed=0.08,
        nonlin=0.01,
        max_amplitude=6.0,
    )
    pattern = np.ones((18, 18), dtype=np.float32)

    for _ in range(500):
        field.feed(pattern, strength=40.0)
        field.evolve(1)

    assert np.all(np.isfinite(field.state))
    assert float(np.max(np.abs(field.state))) <= 6.0
    assert math_is_finite(field.energy())
    assert math_is_finite(field.field_resonance(pattern))


def math_is_finite(value: float) -> bool:
    return bool(np.isfinite(value))


def test_wavefield_rejects_non_positive_amplitude_bound() -> None:
    for value in (0.0, -1.0):
        with pytest.raises(ValueError, match="max_amplitude"):
            WaveField(max_amplitude=value)

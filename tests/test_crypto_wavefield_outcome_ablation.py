from __future__ import annotations

import numpy as np


def test_signed_resonance_preserves_outcome_sign():
    from benchmarks.crypto_wavefield_outcome_ablation import _signed_resonance

    pattern = np.asarray([[1.0, 0.0], [0.0, 0.0]], dtype=float)

    assert _signed_resonance(pattern, pattern) > 0.99
    assert _signed_resonance(-pattern, pattern) < -0.99


def test_score_probability_is_bounded_and_monotonic():
    from benchmarks.crypto_wavefield_outcome_ablation import _scores_to_probability

    probabilities = _scores_to_probability(np.asarray([-1.0, 0.0, 1.0]), scale=10.0)

    assert 0.0 < probabilities[0] < probabilities[1] < probabilities[2] < 1.0
    assert probabilities[1] == 0.5

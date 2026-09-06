"""Independent model checks and certificate soundness; not admission evidence."""

import unittest

import numpy as np

from experiment_r1 import (AXES, FAMILIES, Anchor, born_probability,
                           certified_decision, continuity_bound, entropy, scores)


class MechanismChecks(unittest.TestCase):
    def test_bloch_matches_independent_unitary(self):
        pauli = [np.array([[0, 1], [1, 0]]), np.array([[0, -1j], [1j, 0]]),
                 np.diag([1, -1])]
        identity = np.eye(2)
        for axis in FAMILIES.values():
            generator = sum(axis[i] * pauli[i] for i in range(3))
            for initial in [AXES["z"], AXES["x"]]:
                rho = (identity + sum(initial[i] * pauli[i] for i in range(3))) / 2
                for measurement in AXES.values():
                    projector = (identity + sum(measurement[i] * pauli[i] for i in range(3))) / 2
                    for omega, t in [(.37, .29), (1.3, 2.7), (2.1, .8)]:
                        unitary = (np.cos(omega * t / 2) * identity
                                   - 1j * np.sin(omega * t / 2) * generator)
                        probability = np.trace(projector @ unitary @ rho @ unitary.conj().T).real
                        self.assertAlmostEqual(float(born_probability(
                            omega, axis, initial, measurement, t)), float(probability), places=13)

    def test_continuity_bound_covers_random_channels(self):
        rng = np.random.default_rng(17)
        for _ in range(100):
            p, q = rng.dirichlet(np.ones(9), size=2)
            table = rng.random((11, 9))
            distance = np.abs(p - q).sum() / 2
            delta = np.max(np.abs(scores(p, table, entropy(table)) - scores(q, table, entropy(table))))
            self.assertLessEqual(delta, continuity_bound(distance) + 1e-13)

    def test_certificate_can_reuse_and_can_refuse(self):
        table = np.array([[.1, .9], [.5, .5]])
        p = np.array([.5, .5])
        _, anchor, recomputed, _, _ = certified_decision(p, table, entropy(table), None)
        self.assertTrue(recomputed)
        action, _, recomputed, _, _ = certified_decision(np.array([.501, .499]), table,
                                                       entropy(table), anchor)
        self.assertFalse(recomputed)
        self.assertEqual(action, 0)
        _, _, recomputed, _, _ = certified_decision(np.array([.999, .001]), table,
                                                   entropy(table), anchor)
        self.assertTrue(recomputed)

    def test_tie_reuses_only_identical_posterior(self):
        table = np.full((2, 2), .5)
        anchor = Anchor(np.array([.5, .5]), 0, 0.)
        self.assertFalse(certified_decision(anchor.posterior, table, entropy(table), anchor)[2])
        self.assertTrue(certified_decision(np.array([.6, .4]), table, entropy(table), anchor)[2])

    def test_entropy_endpoints(self):
        np.testing.assert_allclose(entropy(np.array([0., .5, 1.])), [0., np.log(2), 0.])


if __name__ == "__main__":
    unittest.main()

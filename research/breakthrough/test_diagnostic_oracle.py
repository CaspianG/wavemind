import unittest
from fractions import Fraction as F

from diagnostic_oracle import Problem, dot, enumerate_policy_vectors, sign_problem, solve


class DiagnosticOracleChecks(unittest.TestCase):
    def test_matches_all_depth_two_policy_trees(self):
        # Two tests, two stop actions -> 202 deterministic trees at depth two.
        for noise in [F(0), F(1, 10), F(1, 2)]:
            problem = sign_problem(noise, F(1, 100))
            vectors = enumerate_policy_vectors(problem, 2)
            self.assertEqual(len(vectors), 202)
            for prior in [(F(1, 2), F(1, 2)), (F(1, 5), F(4, 5)), (F(0), F(1))]:
                expected = min(dot(prior, v) for v in vectors)
                self.assertEqual(solve(problem, prior, 2)["risk"], expected)

    def test_overlapping_safe_actions(self):
        problem = Problem(likelihood_one=((F(0), F(1), F(1)),), costs=(F(1, 10),),
                          losses=((F(0), F(0), F(1)), (F(1), F(0), F(0))))
        self.assertEqual(solve(problem, (F(1, 3),) * 3, 1)["risk"], F(1, 10))

    def test_noiseless_probe_and_uninformative_channel(self):
        self.assertEqual(solve(sign_problem(0, F(1, 100)), (F(1, 2),) * 2, 6)["risk"], F(1, 100))
        result = solve(sign_problem(F(1, 2), F(1, 100)), (F(1, 2),) * 2, 6)
        self.assertEqual(result["risk"], F(1, 2))
        self.assertEqual(result["expected_probes"], 0)

    def test_zero_probability_branch_and_costly_measurement(self):
        self.assertEqual(solve(sign_problem(0, 1), (F(1, 2),) * 2, 2)["expected_probes"], 0)
        self.assertEqual(solve(sign_problem(0, 0), (F(1), F(0)), 2)["risk"], 0)

    def test_invalid_prior_rejected(self):
        with self.assertRaises(ValueError):
            solve(sign_problem(F(1, 10), F(1, 100)), (F(1), F(1)), 2)


if __name__ == "__main__":
    unittest.main()

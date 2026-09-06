import unittest

import numpy as np

from experiment_r1 import entropy, scores
from experiment_r2 import quotient


class QuotientChecks(unittest.TestCase):
    def test_complement_and_duplicate_preserve_information(self):
        table = np.array([[.1, .8, .4], [.9, .2, .6], [.2, .5, .7], [.1, .8, .4]])
        reduced, mapping = quotient(table)
        self.assertEqual(mapping, [0, 0, 1, 0])
        for p in [np.array([.2, .3, .5]), np.array([.8, .1, .1])]:
            np.testing.assert_allclose(scores(p, table, entropy(table)),
                                       scores(p, reduced, entropy(reduced))[mapping], atol=1e-14)

    def test_distinct_channels_not_merged(self):
        reduced, mapping = quotient(np.array([[.1, .8], [.1001, .8]]))
        self.assertEqual(len(reduced), 2)
        self.assertEqual(mapping, [0, 1])


if __name__ == "__main__":
    unittest.main()

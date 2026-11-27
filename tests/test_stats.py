"""Small-sample intervals keep the benchmark honest about n."""

import unittest

from assaystone.stats import wilson_interval


class WilsonTest(unittest.TestCase):
    def test_known_interval(self):
        low, high = wilson_interval(11, 13)
        self.assertAlmostEqual(low, 0.58, delta=0.03)
        self.assertAlmostEqual(high, 0.96, delta=0.03)

    def test_empty_sample(self):
        self.assertEqual(wilson_interval(0, 0), (0.0, 0.0))

    def test_perfect_sample_has_a_lower_bound(self):
        low, high = wilson_interval(4, 4)
        self.assertGreater(low, 0.4)
        self.assertEqual(high, 1.0)

    def test_bounds_are_clamped(self):
        for successes, total in ((0, 5), (5, 5), (1, 2), (3, 7)):
            low, high = wilson_interval(successes, total)
            self.assertGreaterEqual(low, 0.0)
            self.assertLessEqual(high, 1.0)
            self.assertLessEqual(low, high)


if __name__ == "__main__":
    unittest.main()

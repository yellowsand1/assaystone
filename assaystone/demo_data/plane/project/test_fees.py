import unittest

from fee import fee_cents


class FeeTest(unittest.TestCase):
    def test_us_rate(self):
        self.assertEqual(fee_cents(4000, "us", "new"), 116)

    def test_eu_rate(self):
        self.assertEqual(fee_cents(5000, "eu", "new"), 125)

    def test_unknown_region_defaults(self):
        self.assertEqual(fee_cents(1000, "apac", "new"), 25)

    def test_old_and_new_agree_on_known_regions(self):
        for amount in (1, 999, 3300, 4000, 123456):
            for region in ("us", "eu"):
                self.assertEqual(
                    fee_cents(amount, region, "old"),
                    fee_cents(amount, region, "new"),
                )

import unittest

from helpers.assertions import assert_close
from src.pricing import total


class TestTotal(unittest.TestCase):
    def test_total(self):
        assert_close(total(19.99, 3), 59.97)


if __name__ == "__main__":
    unittest.main()

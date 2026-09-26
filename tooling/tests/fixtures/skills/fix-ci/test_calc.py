import unittest

from calc import divide


class DivideTests(unittest.TestCase):
    def test_negative_divisor(self):
        self.assertEqual(divide(6, -3), -2)

    def test_zero(self):
        with self.assertRaises(ZeroDivisionError):
            divide(1, 0)

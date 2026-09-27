import unittest

from runner import greet


class GreetTests(unittest.TestCase):
    def test_plain_name(self):
        self.assertEqual(greet("ada"), "hello ada")

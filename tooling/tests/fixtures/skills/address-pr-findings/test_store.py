import unittest

import store


class StoreTests(unittest.TestCase):
    def test_round_trip(self):
        store.put("a", 1)
        self.assertEqual(store.get("a"), 1)

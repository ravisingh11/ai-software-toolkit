import unittest

from app import version


class VersionTests(unittest.TestCase):
    def test_version_is_string(self):
        self.assertIsInstance(version(), str)

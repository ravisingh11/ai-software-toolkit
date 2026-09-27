import unittest

from app import add, is_even, slugify


class AppTests(unittest.TestCase):
    def test_slugify_normalizes_words_and_punctuation(self) -> None:
        self.assertEqual(slugify(" Proof, made useful! "), "proof-made-useful")

    def test_slugify_handles_empty_input(self) -> None:
        self.assertEqual(slugify("---"), "")

    def test_add_returns_sum(self) -> None:
        self.assertEqual(add(2, 3), 5)

    def test_add_handles_negative_values(self) -> None:
        self.assertEqual(add(-2, 3), 1)

    def test_is_even_identifies_even_and_odd_values(self) -> None:
        self.assertTrue(is_even(4))
        self.assertFalse(is_even(5))


if __name__ == "__main__":
    unittest.main()

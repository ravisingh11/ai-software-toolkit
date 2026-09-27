"""Small application module used by the Proof adoption example."""

import re


def slugify(value: str) -> str:
    """Convert human-readable text into a stable URL slug."""
    normalized = re.sub(r"[^a-z0-9]+", "-", value.strip().lower())
    return normalized.strip("-")


def add(left: int, right: int) -> int:
    """Return the sum of two values."""
    return left + right


def is_even(value: int) -> bool:
    """Return whether a number is evenly divisible by two."""
    return value % 2 == 0

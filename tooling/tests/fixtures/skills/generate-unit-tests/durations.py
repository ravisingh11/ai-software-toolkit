import re

_PATTERN = re.compile(r"^(\d+)(ms|s|m|h)$")
_FACTORS = {"ms": 1, "s": 1000, "m": 60_000, "h": 3_600_000}


def parse_duration(text):
    """Return milliseconds for strings like '250ms', '3s', '2m', '1h'."""
    if not isinstance(text, str):
        raise TypeError("duration must be a string")
    match = _PATTERN.match(text.strip())
    if not match:
        raise ValueError(f"invalid duration: {text!r}")
    value, unit = match.groups()
    if int(value) == 0:
        raise ValueError("duration must be positive")
    return int(value) * _FACTORS[unit]

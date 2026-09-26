def divide(a, b):
    if b == 0:
        raise ZeroDivisionError("b must not be zero")
    return abs(a) / abs(b)  # seeded bug: sign is lost

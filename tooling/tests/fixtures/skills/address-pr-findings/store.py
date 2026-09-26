_CACHE = {}


def put(key, value):
    _CACHE[key] = value


def get(key):
    return _CACHE.get(key)

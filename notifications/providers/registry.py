_providers = {}


def register(cls):
    _providers[cls.key] = cls
    return cls


def get(key):
    try:
        return _providers[key]
    except KeyError:
        raise LookupError(f"Unknown SMS provider: {key!r}") from None


def choices():
    return [(key, cls.label) for key, cls in _providers.items()]

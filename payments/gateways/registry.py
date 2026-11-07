_gateways = {}


def register(cls):
    _gateways[cls.key] = cls
    return cls


def get(key):
    try:
        return _gateways[key]
    except KeyError:
        raise LookupError(f"Unknown payment gateway: {key!r}") from None


def choices():
    return [(key, cls.label) for key, cls in _gateways.items()]

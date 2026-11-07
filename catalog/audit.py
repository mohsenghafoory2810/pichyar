"""Who is changing things right now, so price logs can name the user on every path
(admin form, list edit, Excel import, bulk action) without threading `user` through."""

from contextlib import contextmanager
from contextvars import ContextVar

_acting_user = ContextVar("acting_user", default=None)


def get_acting_user():
    return _acting_user.get()


@contextmanager
def acting_as(user):
    token = _acting_user.set(user)
    try:
        yield
    finally:
        _acting_user.reset(token)


class ActingUserMiddleware:
    """Exposes request.user to get_acting_user() for the duration of the request."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        # request.user is a lazy object, so this costs nothing unless a log is written.
        with acting_as(request.user):
            return self.get_response(request)

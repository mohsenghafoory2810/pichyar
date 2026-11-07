from urllib.parse import unquote

from django.db.models import F
from django.http import HttpResponsePermanentRedirect

from .models import Redirect


class RedirectMiddleware:
    """On a 404, look the path up in seo.Redirect and answer 301 instead."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        if response.status_code != 404:
            return response
        path = unquote(request.path)
        candidates = [path] if path.endswith("/") else [path, path + "/"]
        redirect = Redirect.objects.filter(old_path__in=candidates, is_active=True).first()
        if redirect is None:
            return response
        Redirect.objects.filter(pk=redirect.pk).update(hits=F("hits") + 1)
        target = redirect.new_path
        if request.META.get("QUERY_STRING") and not target.startswith("https://"):
            target = f"{target}?{request.META['QUERY_STRING']}"
        return HttpResponsePermanentRedirect(target)

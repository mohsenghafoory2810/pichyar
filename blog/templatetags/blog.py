from django import template

from blog.jsonld import iso as iso_datetime

register = template.Library()


@register.filter
def iso(value):
    """Datetime -> '2026-11-08T10:30:00+03:30' for <time datetime="...">."""
    return iso_datetime(value)

import json

from django import template
from django.utils.encoding import escape_uri_path
from django.utils.html import format_html
from django.utils.safestring import mark_safe

register = template.Library()

# Escaped as JSON unicode escapes so "</script>" or "<!--" inside a value can't end the script.
_JSON_ESCAPES = {ord(">"): "\\u003e", ord("<"): "\\u003c", ord("&"): "\\u0026"}


@register.filter
def jsonld(data):
    """<script type="application/ld+json"> with </script>-safe escaping."""
    if not data:
        return ""
    text = json.dumps(data, ensure_ascii=False, separators=(",", ":")).translate(_JSON_ESCAPES)
    return format_html('<script type="application/ld+json">{}</script>', mark_safe(text))


@register.simple_tag(takes_context=True)
def site_jsonld(context):
    """Organization + WebSite (SearchAction) + BreadcrumbList of the current page_meta."""
    from seo import jsonld as ld

    request = context.get("request")
    site_settings = context.get("site_settings")
    if request is None or site_settings is None:
        return ""
    blocks = [ld.organization(request, site_settings), ld.website(request, site_settings)]
    page_meta = context.get("page_meta")
    if page_meta is not None and page_meta.breadcrumbs:
        blocks.append(ld.breadcrumb_list(request, page_meta.breadcrumbs))
    return mark_safe("\n".join(jsonld(b) for b in blocks if b))


@register.simple_tag(takes_context=True)
def og_image(context):
    """{"url", "width", "height", "alt"} for og:image: the page's image, else the default
    sharing image from the site settings, else the logo. None when there is none."""
    from seo.meta import absolute

    request = context.get("request")
    page_meta = context.get("page_meta")
    site_settings = context.get("site_settings")
    if page_meta is not None and page_meta.image:
        return {
            "url": absolute(request, page_meta.image),
            "width": page_meta.image_width or None,
            "height": page_meta.image_height or None,
            "alt": page_meta.image_alt,
        }
    if site_settings is None or request is None:
        return None
    for field in (site_settings.default_og_image, site_settings.logo):
        if field:
            dims = image_size(field)
            return {
                "url": absolute(request, field.url),
                "width": dims["width"] if dims else None,
                "height": dims["height"] if dims else None,
                "alt": site_settings.site_name,
            }
    return None


@register.simple_tag
def image_size(field_file):
    """{"width", "height"} of an ImageField file, or None if missing/unreadable."""
    if not field_file:
        return None
    try:
        return {"width": field_file.width, "height": field_file.height}
    except (OSError, ValueError, TypeError):
        return None


@register.filter
def srcset(product_image):
    """srcset of a ProductImage: its smaller WebP variants that exist plus the original."""
    from catalog.images import srcset_for

    return srcset_for(product_image)


@register.simple_tag(takes_context=True)
def page_url(context, number):
    """Link to page `number` of the current list, other parameters kept; page 1 has no ?page=
    (the canonical form) and no stray '?'."""
    request = context["request"]
    params = request.GET.copy()
    params.pop("page", None)
    if int(number) > 1:
        params["page"] = number
    query = params.urlencode()
    path = escape_uri_path(request.path)
    return f"{path}?{query}" if query else path

"""Page metadata contract shared by every public view.

A view puts `page_meta` (a PageMeta) in its context; base.html renders <title>, description,
robots, canonical, Open Graph / Twitter tags, breadcrumbs JSON-LD and any extra JSON-LD from it.
Views that set nothing get site-wide defaults.

    from seo.meta import PageMeta, crumbs
    page_meta = PageMeta.for_object(request, product, title=product.name, description=..., image=url,
                                    breadcrumbs=crumbs(("خانه", "/"), (cat.name, cat.get_absolute_url())))
"""

import re
from dataclasses import dataclass, field

from django.utils.encoding import iri_to_uri
from django.utils.html import strip_tags
from django.utils.text import Truncator

from .models import META_DESCRIPTION_MAX, META_TITLE_MAX

_SPACES = re.compile(r"\s+")


def plain_text(html_or_text):
    return _SPACES.sub(" ", strip_tags(html_or_text or "")).strip()


def auto_description(*parts, limit=META_DESCRIPTION_MAX):
    """First non-empty text among parts, tags stripped, cut at a word boundary."""
    for part in parts:
        text = plain_text(part)
        if text:
            return Truncator(text).chars(limit, truncate="…")
    return ""


def auto_title(title, site_name, limit=META_TITLE_MAX):
    full = f"{title} | {site_name}" if title and site_name and title != site_name else (title or site_name)
    return full if len(full) <= limit else title


def crumbs(*pairs):
    """crumbs(("خانه", "/"), ("دسته", "/c/x/"), ("محصول", None)) — the last one is the current page."""
    return [{"name": name, "url": url} for name, url in pairs]


@dataclass
class PageMeta:
    title: str = ""  # full <title> text
    description: str = ""
    canonical: str = ""  # absolute URL; "" = no canonical tag
    noindex: bool = False
    og_type: str = "website"
    image: str = ""  # absolute URL
    image_alt: str = ""
    breadcrumbs: list = field(default_factory=list)  # [{"name", "url"}], url relative or absolute
    jsonld: list = field(default_factory=list)  # extra JSON-LD dicts (Product, Article, FAQPage, ...)
    published_time: str = ""  # ISO 8601, articles
    modified_time: str = ""
    image_width: int = 0  # og:image:width / height when known
    image_height: int = 0

    @property
    def robots(self):
        return "noindex, follow" if self.noindex else "index, follow, max-image-preview:large"

    @classmethod
    def for_object(cls, request, obj, *, title, description_fallback="", site_settings=None, **kwargs):
        """Defaults from an SEOFields object: meta_title/meta_description/canonical_url/noindex."""
        from core.utils import get_site_settings

        site_settings = site_settings or get_site_settings(request)
        noindex = kwargs.pop("noindex", False)
        meta_title = (getattr(obj, "meta_title", "") or "").strip()
        canonical = (getattr(obj, "canonical_url", "") or "").strip() or obj.get_absolute_url()
        return cls(
            title=meta_title or auto_title(title, site_settings.site_name),
            description=(getattr(obj, "meta_description", "") or "").strip() or auto_description(description_fallback),
            canonical=absolute(request, canonical),
            noindex=bool(getattr(obj, "noindex", False)) or bool(noindex),
            **kwargs,
        )


def absolute(request, url):
    """Absolute, percent-encoded URL (the one canonical form used in tags, JSON-LD and sitemaps)."""
    if not url:
        return url
    if url.startswith(("http://", "https://")):
        return iri_to_uri(url)
    return request.build_absolute_uri(url)


# --- listing pages (category, search, blog lists) -----------------------------------

PAGE_PARAM = "page"


def has_filter_params(request):
    """Any GET parameter other than ?page= (sort, search, filters, tracking, ...)."""
    return any(key != PAGE_PARAM for key in request.GET)


def listing_canonical(request, base_url, page_number=1):
    """Absolute canonical for a paginated list: page 1 has no parameter, page N keeps ?page=N;
    sorted/filtered/searched variants point to the base page (and are noindex, see listing_robots)."""
    if page_number > 1 and not has_filter_params(request):
        return absolute(request, f"{base_url}?{PAGE_PARAM}={page_number}")
    return absolute(request, base_url)


# Pages that are private to a visitor (cart, checkout, account, ...): never indexed.
PRIVATE_PREFIXES = ("/cart/", "/checkout/", "/accounts/", "/orders/", "/payments/", "/reviews/", "/age-check/")


def default_page_meta(request, site_settings):
    """What base.html shows when a view sets no page_meta."""
    private = request.path.startswith(PRIVATE_PREFIXES)
    return PageMeta(
        title=site_settings.site_name,
        description=auto_description(site_settings.site_description),
        canonical="" if private else absolute(request, request.path),
        noindex=private or has_filter_params(request),
    )

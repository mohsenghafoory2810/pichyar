from django.conf import settings
from django.db.models import Prefetch
from django.utils.functional import SimpleLazyObject

from seo.meta import default_page_meta

from .models import StaticPage
from .utils import get_site_settings, is_age_verified


def footer_categories():
    """Active top-level categories with their active children (footer links)."""
    from catalog.models import Category

    children = Category.objects.filter(is_active=True)
    return (
        Category.objects.filter(is_active=True, parent__isnull=True)
        .prefetch_related(Prefetch("children", queryset=children, to_attr="active_children"))
        .only("name", "slug")
    )


def site(request):
    site_settings = get_site_settings(request)
    return {
        "site_settings": site_settings,
        # A view's own page_meta (in its context) takes precedence over this default.
        "page_meta": SimpleLazyObject(lambda: default_page_meta(request, site_settings)),
        "footer_categories": footer_categories(),
        "age_verified": is_age_verified(request),
        "age_gate_exit_url": settings.AGE_GATE_EXIT_URL,
        "footer_pages": StaticPage.objects.filter(is_active=True, show_in_footer=True).only("title", "slug"),
    }

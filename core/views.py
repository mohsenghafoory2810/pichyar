from django.conf import settings
from django.db import connection
from django.http import HttpResponseRedirect, JsonResponse
from django.shortcuts import get_object_or_404, render
from django.template import TemplateDoesNotExist
from django.template.loader import get_template
from django.templatetags.static import static
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_POST

from catalog.views import home_sections
from seo.meta import PageMeta, absolute, auto_description, crumbs, has_filter_params

from .models import Banner, StaticPage
from .utils import get_site_settings

LATEST_ARTICLES = 3
LATEST_ARTICLES_TEMPLATE = "blog/_latest_articles.html"


def latest_articles(limit=LATEST_ARTICLES):
    try:
        from blog.services import latest_articles as blog_latest
    except ImportError:
        from blog.models import Article

        return list(Article.objects.published().select_related("category")[:limit])
    return blog_latest(limit)


def _optional_template(name):
    """The template name if it exists (the blog partial is optional), else None."""
    try:
        get_template(name)
    except TemplateDoesNotExist:
        return None
    return name


def home(request):
    site_settings = get_site_settings(request)
    banners = Banner.objects.filter(is_active=True)
    page_meta = PageMeta(
        title=site_settings.site_name,
        description=auto_description(site_settings.site_description),
        canonical=absolute(request, "/"),
        noindex=has_filter_params(request),
    )
    articles_template = _optional_template(LATEST_ARTICLES_TEMPLATE)
    return render(
        request,
        "core/home.html",
        {
            "banners": banners,
            "sections": home_sections(),
            "page_meta": page_meta,
            "latest_articles": latest_articles() if articles_template else [],
            "latest_articles_template": articles_template,
        },
    )


def static_page(request, slug):
    page = get_object_or_404(StaticPage, slug=slug, is_active=True)
    page_meta = PageMeta.for_object(
        request,
        page,
        title=page.title,
        description_fallback=page.body,
        breadcrumbs=crumbs(("خانه", "/"), (page.title, None)),
        modified_time=page.updated_at.isoformat(),
    )
    return render(request, "core/static_page.html", {"page": page, "page_meta": page_meta})


def coming_soon(request, title):
    """Placeholder for pages built in later parts (login, cart, search)."""
    return render(request, "core/coming_soon.html", {"title": title, "query": request.GET.get("q", "")})


@require_POST
def age_confirm(request):
    next_url = request.POST.get("next") or "/"
    if not url_has_allowed_host_and_scheme(next_url, {request.get_host()}, require_https=request.is_secure()):
        next_url = "/"
    response = HttpResponseRedirect(next_url)
    response.set_cookie(
        settings.AGE_GATE_COOKIE,
        "1",
        max_age=settings.AGE_GATE_MAX_AGE,
        secure=settings.SESSION_COOKIE_SECURE,
        httponly=True,
        samesite="Lax",
    )
    return response


def favicon(request):
    """/favicon.ico (browsers and crawlers ask for it without reading the page): the uploaded
    icon, else the default. A temporary redirect so a newly uploaded icon is picked up."""
    site_settings = get_site_settings(request)
    url = site_settings.favicon.url if site_settings.favicon else static("img/favicon.svg")
    response = HttpResponseRedirect(url)
    response["Cache-Control"] = "public, max-age=86400"
    return response


@never_cache
def health(request):
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            cursor.fetchone()
    except Exception:
        return JsonResponse({"status": "error", "database": "unavailable"}, status=503)
    return JsonResponse({"status": "ok"})

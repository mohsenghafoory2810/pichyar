from django.contrib.sitemaps import views as sitemap_views
from django.http import Http404, HttpResponse
from django.urls import reverse
from django.views.decorators.cache import cache_control

from core.utils import get_site_settings

from .meta import absolute, plain_text
from .sitemaps import SITEMAPS

# Crawlers that collect training / answer-engine data. Blocked when SiteSettings.allow_ai_crawlers is off.
AI_CRAWLERS = ("GPTBot", "ClaudeBot", "PerplexityBot", "Google-Extended", "CCBot")

# Private or duplicate areas. The admin path is deliberately NOT listed: robots.txt is public and
# would reveal it; the admin pages carry their own noindex meta tag.
DISALLOW = (
    "/cart/",
    "/checkout/",
    "/orders/",
    "/accounts/",
    "/payments/",
    "/search/",
    "/reviews/",
    "/age-check/",
    "/tinymce/",
    # Sorted / searched variants of the lists (?page= stays crawlable).
    "/*?*sort=",
    "/*?*q=",
)

TEXT = "text/plain; charset=utf-8"
CACHE = cache_control(public=True, max_age=3600)


@CACHE
def robots_txt(request):
    site_settings = get_site_settings(request)
    lines = ["User-agent: *", *(f"Disallow: {path}" for path in DISALLOW), "Allow: /", ""]
    if not site_settings.allow_ai_crawlers:
        for bot in AI_CRAWLERS:
            lines += [f"User-agent: {bot}", "Disallow: /", ""]
    lines.append(f"Sitemap: {absolute(request, reverse('seo:sitemap'))}")
    return HttpResponse("\n".join(lines) + "\n", content_type=TEXT)


def _first_sentence(text, limit=200):
    text = plain_text(text)
    for mark in (".", "؟", "!", "?"):
        index = text.find(mark)
        if 0 < index < limit:
            text = text[: index + 1]
    return text[:limit].strip()


@CACHE
def llms_txt(request):
    """/llms.txt (llmstxt.org): a plain map of the site built only from real content."""
    from blog.models import Article
    from catalog.views import active_categories
    from core.models import StaticPage

    site_settings = get_site_settings(request)
    out = [f"# {site_settings.site_name}", ""]
    description = plain_text(site_settings.site_description)
    if description:
        out += [f"> {description}", ""]

    tops = list(active_categories().filter(parent__isnull=True, noindex=False).prefetch_related("children"))
    if tops:
        out.append("## دسته‌بندی‌ها")
        for cat in tops:
            out.append(f"- [{cat.name}]({absolute(request, cat.get_absolute_url())})")
            for child in cat.children.all():
                if child.is_active and not child.noindex:
                    out.append(f"  - [{child.name}]({absolute(request, child.get_absolute_url())})")
        out.append("")

    out.append("## صفحه‌های اصلی")
    out.append(f"- [مقاله‌ها]({absolute(request, reverse('blog:list'))})")
    for page in StaticPage.objects.filter(is_active=True, noindex=False):
        out.append(f"- [{page.title}]({absolute(request, page.get_absolute_url())})")
    out.append("")

    articles = list(Article.objects.published().filter(noindex=False)[:10])
    if articles:
        out.append("## آخرین مقاله‌ها")
        for article in articles:
            line = f"- [{article.title}]({absolute(request, article.get_absolute_url())})"
            summary = _first_sentence(article.short_answer)
            out.append(f"{line}: {summary}" if summary else line)
        out.append("")

    contact = []
    if site_settings.phone:
        contact.append(f"- تلفن: {site_settings.phone}")
    for line in (site_settings.support_info or "").splitlines():
        if line.strip():
            contact.append(f"- {line.strip()}")
    if contact:
        out += ["## تماس", *contact, ""]
    return HttpResponse("\n".join(out), content_type=TEXT)


def _section(section):
    if section not in SITEMAPS:
        raise Http404("بخش نقشهٔ سایت وجود ندارد.")
    return {section: SITEMAPS[section]}


@CACHE
def sitemap_index(request):
    return sitemap_views.index(request, SITEMAPS, sitemap_url_name="seo:sitemap_section")


@CACHE
def sitemap_section(request, section):
    return sitemap_views.sitemap(request, _section(section), section=section)

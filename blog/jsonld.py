"""Article JSON-LD (schema.org BlogPosting) for the article page's PageMeta.jsonld."""

from django.utils import timezone

from seo.jsonld import CONTEXT
from seo.meta import absolute, auto_description


def iso(value):
    """Aware datetime -> '2026-11-08T10:30:00+03:30' in the site's timezone ('' for None)."""
    if not value:
        return ""
    if timezone.is_aware(value):
        value = timezone.localtime(value)
    return value.isoformat(timespec="seconds")


def published_date(article):
    # A draft being previewed has no published_at yet.
    return article.published_at or article.created_at


def organization(request, site_settings):
    name = getattr(site_settings, "organization_display_name", "") or site_settings.site_name
    org = {"@type": "Organization", "name": name, "url": request.build_absolute_uri("/")}
    logo = getattr(site_settings, "logo", None)
    if logo:
        org["logo"] = {"@type": "ImageObject", "url": absolute(request, logo.url)}
    return org


def article_jsonld(request, article, site_settings, description=""):
    """BlogPosting dict. The author is the article's author_name, or the shop itself when blank."""
    url = absolute(request, article.get_absolute_url())
    publisher = organization(request, site_settings)
    author = (
        {"@type": "Person", "name": article.author_name.strip()}
        if (article.author_name or "").strip()
        else {"@type": "Organization", "name": publisher["name"], "url": publisher["url"]}
    )
    data = {
        "@context": CONTEXT,
        "@type": "BlogPosting",
        "headline": article.title[:110],
        "description": description or auto_description(article.short_answer, article.body),
        "datePublished": iso(published_date(article)),
        "dateModified": iso(article.updated_at or published_date(article)),
        "author": author,
        "publisher": publisher,
        "mainEntityOfPage": {"@type": "WebPage", "@id": url},
        "url": url,
        "inLanguage": "fa-IR",
    }
    if article.cover:
        image = {"@type": "ImageObject", "url": absolute(request, article.cover.url)}
        if article.cover_width and article.cover_height:
            image.update(width=article.cover_width, height=article.cover_height)
        data["image"] = image
    if article.category_id:
        data["articleSection"] = article.category.name
    keywords = [t.name for t in article.tags.all()]
    if keywords:
        data["keywords"] = ", ".join(keywords)
    if not data["description"]:
        del data["description"]
    return data

"""sitemap.xml sections (django.contrib.sitemaps). Only indexable pages: active, published,
not noindex, and not pointing their canonical somewhere else. Tag pages are left out."""

from urllib.parse import unquote, urlsplit

from django.contrib.sitemaps import Sitemap
from django.db.models import Max, Q
from django.urls import NoReverseMatch, reverse

LIMIT = 5000  # URLs per sitemap page (?p=2, ... beyond that)


def self_canonical(obj):
    """True when the object has no canonical override, or the override is its own URL."""
    override = (getattr(obj, "canonical_url", "") or "").strip()
    if not override:
        return True
    own = unquote(obj.get_absolute_url())
    return unquote(urlsplit(override).path or override) == own and not urlsplit(override).query


def _indexable(qs):
    return [obj for obj in qs.filter(noindex=False) if self_canonical(obj)]


class BaseSitemap(Sitemap):
    limit = LIMIT

    def get_latest_lastmod(self):
        """For the index: the newest lastmod, ignoring items that have none."""
        dates = [d for d in (self.lastmod(item) for item in self.items()) if d]
        return max(dates) if dates else None


class ProductSitemap(BaseSitemap):
    changefreq = "weekly"

    def items(self):
        from catalog.models import Product

        return _indexable(Product.objects.active().order_by("pk").only("slug", "updated_at", "canonical_url", "noindex"))

    def lastmod(self, obj):
        return obj.updated_at


class CategorySitemap(BaseSitemap):
    changefreq = "weekly"

    def items(self):
        from catalog.views import active_categories

        qs = active_categories().order_by("order", "pk").annotate(
            own_latest=Max("products__updated_at", filter=Q(products__is_active=True)),
            child_latest=Max("children__products__updated_at", filter=Q(children__products__is_active=True)),
        )
        return _indexable(qs)

    def lastmod(self, obj):
        dates = [d for d in (obj.own_latest, obj.child_latest) if d]
        return max(dates) if dates else None


class ArticleSitemap(BaseSitemap):
    changefreq = "monthly"

    def items(self):
        from blog.models import Article

        return _indexable(Article.objects.published().order_by("-published_at", "-pk"))

    def lastmod(self, obj):
        return obj.updated_at


class ArticleCategorySitemap(BaseSitemap):
    changefreq = "weekly"

    def items(self):
        from blog.models import Article, ArticleCategory

        published = Article.objects.published()
        qs = (
            ArticleCategory.objects.filter(articles__in=published)
            .annotate(latest=Max("articles__updated_at", filter=Q(articles__in=published)))
            .distinct()
            .order_by("order", "pk")
        )
        return _indexable(qs)

    def lastmod(self, obj):
        return obj.latest


class PagesSitemap(BaseSitemap):
    """Home, the blog index and the active static pages."""

    changefreq = "weekly"

    def items(self):
        from blog.models import Article
        from catalog.models import Product
        from core.models import StaticPage

        items = [
            {"url": "/", "lastmod": Product.objects.active().aggregate(m=Max("updated_at"))["m"]},
        ]
        try:
            blog_url = reverse("blog:list")
        except NoReverseMatch:
            blog_url = None
        if blog_url:
            items.append({"url": blog_url, "lastmod": Article.objects.published().aggregate(m=Max("updated_at"))["m"]})
        for page in _indexable(StaticPage.objects.filter(is_active=True).order_by("order", "pk")):
            items.append({"url": page.get_absolute_url(), "lastmod": page.updated_at})
        return items

    def location(self, item):
        return item["url"]

    def lastmod(self, item):
        return item["lastmod"]


SITEMAPS = {
    "products": ProductSitemap,
    "categories": CategorySitemap,
    "articles": ArticleSitemap,
    "article-categories": ArticleCategorySitemap,
    "pages": PagesSitemap,
}

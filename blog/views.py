from django.core.paginator import InvalidPage, Paginator
from django.db.models import Prefetch
from django.http import Http404
from django.shortcuts import get_object_or_404, render
from django.utils.safestring import mark_safe

from catalog.models import Product
from catalog.views import with_images
from core.utils import get_site_settings
from reviews.stats import attach_ratings
from seo.jsonld import faq_page
from seo.meta import PageMeta, absolute, auto_description, auto_title, crumbs

from .jsonld import article_jsonld, iso, published_date
from .models import Article, ArticleCategory, ArticleFAQ, Tag
from .toc import with_heading_ids

PAGE_SIZE = 12
THIN_TAG_MIN_ARTICLES = 3  # tag pages with fewer published articles are noindex (thin content)
RELATED_LIMIT = 8
BLOG_CRUMB = ("مقاله‌ها", "/blog/")


def _cards(qs):
    return qs.select_related("category")


def _page(request, articles):
    """Page of `articles` from ?page=N. A malformed or out-of-range page is a 404 (no soft
    fallback to page 1, so search engines never index duplicate pages)."""
    raw = request.GET.get("page")
    if raw is None:
        number = 1
    elif not raw.isascii() or not raw.isdigit():
        raise Http404
    else:
        number = int(raw)
    try:
        return Paginator(articles, PAGE_SIZE).page(number)
    except InvalidPage:
        raise Http404 from None


def _page_url(request, path, page):
    """Self-canonical: page 1 is the bare path, later pages keep ?page=N."""
    return absolute(request, path if page.number == 1 else f"{path}?page={page.number}")


def _page_title(title, page):
    return title if page.number == 1 else f"{title} — صفحهٔ {page.number}"


def _listing(request, template, page, page_meta, extra):
    return render(
        request,
        template,
        {"page_obj": page, "articles": page.object_list, "page_meta": page_meta, **extra},
    )


def article_list(request):
    site = get_site_settings(request)
    page = _page(request, _cards(Article.objects.published()))
    title = _page_title("مقاله‌ها", page)
    page_meta = PageMeta(
        title=auto_title(title, site.site_name),
        description=auto_description(f"مقاله‌ها و راهنماهای {site.site_name}"),
        canonical=_page_url(request, request.path, page),
        breadcrumbs=crumbs(("خانه", "/"), ("مقاله‌ها", None)),
    )
    return _listing(request, "blog/article_list.html", page, page_meta, {"heading": "مقاله‌ها"})


def category_detail(request, slug):
    category = get_object_or_404(ArticleCategory, slug=slug)
    page = _page(request, _cards(Article.objects.published().filter(category=category)))
    page_meta = PageMeta.for_object(
        request,
        category,
        title=_page_title(category.name, page),
        description_fallback=category.description or f"مقاله‌های {category.name}",
        site_settings=get_site_settings(request),
        breadcrumbs=crumbs(("خانه", "/"), BLOG_CRUMB, (category.name, None)),
    )
    if page.number > 1 and not category.canonical_url:
        page_meta.canonical = _page_url(request, category.get_absolute_url(), page)
    return _listing(
        request, "blog/article_list.html", page, page_meta, {"heading": category.name, "category": category}
    )


def tag_detail(request, slug):
    tag = get_object_or_404(Tag, slug=slug)
    published = Article.objects.published().filter(tags=tag)
    page = _page(request, _cards(published))
    site = get_site_settings(request)
    title = _page_title(f"برچسب: {tag.name}", page)
    page_meta = PageMeta(
        title=auto_title(title, site.site_name),
        description=auto_description(f"مقاله‌های دارای برچسب «{tag.name}» در {site.site_name}"),
        canonical=_page_url(request, tag.get_absolute_url(), page),
        noindex=page.paginator.count < THIN_TAG_MIN_ARTICLES,
        breadcrumbs=crumbs(("خانه", "/"), BLOG_CRUMB, (tag.name, None)),
    )
    return _listing(request, "blog/article_list.html", page, page_meta, {"heading": f"برچسب: {tag.name}", "tag": tag})


def article_detail(request, slug):
    article = get_object_or_404(
        Article.objects.select_related("category").prefetch_related(
            "tags", Prefetch("faqs", queryset=ArticleFAQ.objects.order_by("order", "id"))
        ),
        slug=slug,
    )
    is_preview = not article.is_published
    if is_preview and not (request.user.is_authenticated and request.user.is_staff):
        raise Http404

    site = get_site_settings(request)
    body, toc = with_heading_ids(article.body)
    faqs = list(article.faqs.all())
    tags = list(article.tags.all())
    description = (article.meta_description or "").strip() or auto_description(article.short_answer, article.body)

    breadcrumbs = [("خانه", "/"), BLOG_CRUMB]
    if article.category:
        breadcrumbs.append((article.category.name, article.category.get_absolute_url()))
    breadcrumbs.append((article.title, None))

    page_meta = PageMeta.for_object(
        request,
        article,
        title=article.title,
        description_fallback=description,
        site_settings=site,
        og_type="article",
        image=absolute(request, article.cover.url) if article.cover else "",
        image_alt=article.cover_alt_text if article.cover else "",
        breadcrumbs=crumbs(*breadcrumbs),
        published_time=iso(published_date(article)),
        modified_time=iso(article.updated_at),
    )
    page_meta.noindex = page_meta.noindex or is_preview  # drafts / future articles seen by staff
    page_meta.jsonld.append(article_jsonld(request, article, site, description=page_meta.description))
    faq_data = faq_page(faqs)
    if faq_data:
        page_meta.jsonld.append(faq_data)

    related_products = attach_ratings(
        with_images(Product.objects.active().filter(articles=article)).order_by("sort_order", "id")[:RELATED_LIMIT]
    )
    related_articles = list(
        _cards(article.related_articles.published().exclude(pk=article.pk))[:RELATED_LIMIT]
    )
    return render(
        request,
        "blog/article_detail.html",
        {
            "article": article,
            # The body was sanitized on save (core.html.sanitize_html); only heading ids are added here.
            "body": mark_safe(body),
            "toc": toc,
            "faqs": faqs,
            "tags": tags,
            "related_products": related_products,
            "related_articles": related_articles,
            "is_preview": is_preview,
            "page_meta": page_meta,
        },
    )

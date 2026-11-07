from django.core.paginator import EmptyPage, PageNotAnInteger, Paginator
from django.db.models import Prefetch, Q
from django.http import Http404
from django.shortcuts import get_object_or_404, render
from django.urls import reverse

from cart.cart import Cart
from core.persian import toman
from core.utils import get_site_settings
from reviews.stats import attach_ratings, rating_summary
from seo import jsonld
from seo.meta import PageMeta, absolute, auto_description, auto_title, crumbs, has_filter_params, listing_canonical

from .models import Category, Product, ProductImage
from .text import normalize_fa

PAGE_SIZE = 24
SORTS = {
    "": ("پیش‌فرض", ("sort_order", "id")),
    "price_asc": ("ارزان‌ترین", ("price", "id")),
    "price_desc": ("گران‌ترین", ("-price", "id")),
    "newest": ("جدیدترین", ("-created_at", "-id")),
}
HOME_SECTION_SIZE = 8
RELATED_PRODUCTS = 8
RELATED_ARTICLES = 4
JSONLD_REVIEWS = 5


def with_images(qs):
    return qs.select_related("category").prefetch_related(
        Prefetch("images", queryset=ProductImage.objects.order_by("order", "id"))
    )


def active_categories():
    return Category.objects.filter(is_active=True).filter(Q(parent__isnull=True) | Q(parent__is_active=True))


def home_sections():
    """One section per active top-level category (توتون, لوازم), sub-categories included."""
    sections = []
    for category in active_categories().filter(parent__isnull=True).prefetch_related("children"):
        products = attach_ratings(with_images(Product.objects.active().in_category(category))[:HOME_SECTION_SIZE])
        if products:
            sections.append({"category": category, "products": products})
    return sections


# --- metadata helpers (also used for the admin's placeholder hints) ------------------


def product_meta_description(product, site_name):
    """The product's own text, else «name، unit، price — site»."""
    fallback = f"{product.name}، {product.unit}، {toman(product.price)}"
    if site_name:
        fallback = f"{fallback} — {site_name}"
    return auto_description(product.description, fallback)


def category_meta_description(category):
    return auto_description(category.intro, category.name)


def category_crumbs(category, current=True):
    pairs = [("خانه", reverse("core:home"))]
    if category.parent_id:
        pairs.append((category.parent.name, category.parent.get_absolute_url()))
    pairs.append((category.name, None if current else category.get_absolute_url()))
    return crumbs(*pairs)


def _page_number(request):
    """?page=N as an int; anything else (0, -1, 'abc', '1.5') is a 404 so no duplicate pages exist."""
    raw = request.GET.get("page")
    if raw is None:
        return 1
    try:
        number = int(raw)
    except ValueError:
        raise Http404("صفحه نامعتبر است.")
    if number < 1:
        raise Http404("صفحه نامعتبر است.")
    return number


def _listing(request, products, extra_context, page_meta_factory, template="catalog/product_list.html"):
    query = normalize_fa(request.GET.get("q", ""))[:100]
    if query:
        products = products.filter(Q(name__icontains=query) | Q(short_name__icontains=query) | Q(description__icontains=query))
    sort = request.GET.get("sort", "")
    if sort not in SORTS:
        sort = ""
    paginator = Paginator(with_images(products.order_by(*SORTS[sort][1])), PAGE_SIZE)
    try:
        page = paginator.page(_page_number(request))
    except (EmptyPage, PageNotAnInteger):
        raise Http404("صفحه وجود ندارد.")
    context = {
        "page_obj": page,
        "products": attach_ratings(page.object_list),
        "query": query,
        "sort": sort,
        "sorts": [(key, label) for key, (label, _) in SORTS.items()],
        **extra_context,
    }
    if request.headers.get("HX-Request") and request.headers.get("HX-Target") == "product-results":
        template = "catalog/_product_results.html"
    else:
        context["page_meta"] = page_meta_factory(page)
    return render(request, template, context)


def category_detail(request, slug):
    category = get_object_or_404(
        active_categories().select_related("parent").prefetch_related("faqs"), slug=slug
    )
    top = category.parent or category  # sub-category chips: the top category's children
    site_settings = get_site_settings(request)
    faqs = list(category.faqs.all())

    def page_meta(page):
        title = category.name if page.number == 1 else f"{category.name} - صفحهٔ {page.number}"
        meta = PageMeta.for_object(
            request,
            category,
            title=title,
            description_fallback=category_meta_description(category),
            site_settings=site_settings,
            image=category.image.url if category.image else "",
            image_alt=category.image_alt or category.name,
            breadcrumbs=category_crumbs(category),
            jsonld=[ld for ld in [jsonld.faq_page(faqs)] if ld],
        )
        if page.number > 1 and category.meta_title:
            meta.title = f"{category.meta_title} - صفحهٔ {page.number}"
        if not category.canonical_url:
            meta.canonical = listing_canonical(request, category.get_absolute_url(), page.number)
        if has_filter_params(request):
            meta.noindex = True
        return meta

    return _listing(
        request,
        Product.objects.active().in_category(category),
        {
            "category": category,
            "top_category": top,
            "subcategories": top.children.filter(is_active=True),
            "faqs": faqs,
        },
        page_meta,
    )


def search(request):
    site_settings = get_site_settings(request)

    def page_meta(page):
        query = normalize_fa(request.GET.get("q", ""))[:100]
        title = f"جستجوی «{query}»" if query else "جستجو"
        return PageMeta(
            title=auto_title(title, site_settings.site_name),
            description=auto_description(site_settings.site_description),
            canonical=absolute(request, reverse("catalog:search")),
            noindex=True,  # search result pages are never indexed
            breadcrumbs=crumbs(("خانه", reverse("core:home")), ("جستجو", None)),
        )

    return _listing(request, Product.objects.active(), {"category": None, "is_search": True}, page_meta)


def product_detail(request, slug):
    product = get_object_or_404(
        with_images(Product.objects.active()).select_related("category__parent").prefetch_related("specs"), slug=slug
    )
    site_settings = get_site_settings(request)
    images = list(product.images.all())
    specs = list(product.specs.all())
    rating = rating_summary(product)

    main = images[0] if images else None
    page_meta = PageMeta.for_object(
        request,
        product,
        title=product.name,
        description_fallback=product_meta_description(product, site_settings.site_name),
        site_settings=site_settings,
        og_type="product",
        image=main.image.url if main else "",
        image_width=(main.width or 0) if main else 0,
        image_height=(main.height or 0) if main else 0,
        image_alt=main.alt if main else "",
        breadcrumbs=category_crumbs(product.category, current=False) + crumbs((product.name, None)),
    )
    reviews = []
    if rating:
        from reviews.models import Review

        reviews = list(Review.objects.approved().filter(product=product).select_related("user")[:JSONLD_REVIEWS])
    page_meta.jsonld.append(
        jsonld.product(
            request, product, url=page_meta.canonical, images=images, specs=specs, rating=rating, reviews=reviews
        )
    )

    related = attach_ratings(
        with_images(Product.objects.active().filter(category=product.category).exclude(pk=product.pk))[:RELATED_PRODUCTS]
    )
    return render(
        request,
        "catalog/product_detail.html",
        {
            "product": product,
            "images": images,
            "specs": specs,
            "in_cart": Cart(request).quantity_of(product),
            "page_meta": page_meta,
            "related_products": related,
            "related_articles": related_articles(product),
        },
    )


def related_articles(product):
    """Published articles that list this product among their related products."""
    from blog.models import Article

    return list(
        Article.objects.published().filter(related_products=product).order_by("-published_at", "-id")[:RELATED_ARTICLES]
    )

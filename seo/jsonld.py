"""JSON-LD (schema.org) builders. Each returns a dict for PageMeta.jsonld / the |jsonld filter."""

from django.utils import timezone

from .meta import absolute, plain_text

CONTEXT = "https://schema.org"


def breadcrumb_list(request, breadcrumbs):
    """BreadcrumbList from seo.meta.crumbs(); the current page (url None) uses request's URL."""
    if not breadcrumbs:
        return None
    items = []
    for position, crumb in enumerate(breadcrumbs, 1):
        url = crumb.get("url") or request.build_absolute_uri(request.path)
        items.append({"@type": "ListItem", "position": position, "name": crumb["name"], "item": absolute(request, url)})
    return {"@context": CONTEXT, "@type": "BreadcrumbList", "itemListElement": items}


def faq_page(faqs):
    """FAQPage from objects with .question / .answer; None when there are none."""
    entities = [
        {"@type": "Question", "name": f.question, "acceptedAnswer": {"@type": "Answer", "text": plain_text(f.answer)}}
        for f in faqs
        if f.question and f.answer
    ]
    if not entities:
        return None
    return {"@context": CONTEXT, "@type": "FAQPage", "mainEntity": entities}


def organization(request, site_settings):
    """Organization: name, url, logo, telephone, sameAs (social profiles)."""
    data = {
        "@context": CONTEXT,
        "@type": "Organization",
        "@id": absolute(request, "/") + "#organization",
        "name": site_settings.organization_display_name,
        "url": absolute(request, "/"),
    }
    if site_settings.logo:
        data["logo"] = absolute(request, site_settings.logo.url)
    if site_settings.phone:
        data["telephone"] = site_settings.phone
    if site_settings.social_urls:
        data["sameAs"] = site_settings.social_urls
    return data


def website(request, site_settings, search_path="/search/"):
    """WebSite with a SearchAction (sitelinks search box)."""
    return {
        "@context": CONTEXT,
        "@type": "WebSite",
        "@id": absolute(request, "/") + "#website",
        "name": site_settings.site_name,
        "url": absolute(request, "/"),
        "inLanguage": "fa-IR",
        "publisher": {"@id": absolute(request, "/") + "#organization"},
        "potentialAction": {
            "@type": "SearchAction",
            "target": {"@type": "EntryPoint", "urlTemplate": absolute(request, search_path) + "?q={search_term_string}"},
            "query-input": "required name=search_term_string",
        },
    }


IN_STOCK = "https://schema.org/InStock"
OUT_OF_STOCK = "https://schema.org/OutOfStock"
TOMAN_TO_RIAL = 10


def product(request, product, *, url, images=(), specs=(), rating=None, reviews=()):
    """Product with an Offer in IRR (prices are stored in Toman). aggregateRating / review
    only from approved reviews: pass rating=reviews.stats.rating_summary(product) (None = no reviews)."""
    description = plain_text(product.description)
    spec_lines = [f"{s.name}: {s.value}" for s in specs]
    if spec_lines:
        description = "\n".join([description, *spec_lines]) if description else "\n".join(spec_lines)
    data = {
        "@context": CONTEXT,
        "@type": "Product",
        "name": product.name,
        "sku": product.sku_or_id,
        "url": url,
        "offers": {
            "@type": "Offer",
            "url": url,
            "price": product.price * TOMAN_TO_RIAL,
            "priceCurrency": "IRR",
            "availability": IN_STOCK if product.in_stock else OUT_OF_STOCK,
            "itemCondition": "https://schema.org/NewCondition",
            "seller": {"@id": absolute(request, "/") + "#organization"},
        },
    }
    image_urls = [absolute(request, img.image.url) for img in images if img.image]
    if image_urls:
        data["image"] = image_urls
    if description:
        data["description"] = description
    if product.brand:
        data["brand"] = {"@type": "Brand", "name": product.brand}
    if product.category_id:
        data["category"] = product.category.name
    if rating and rating.count:
        data["aggregateRating"] = {
            "@type": "AggregateRating",
            "ratingValue": rating.average,
            "reviewCount": rating.count,
            "bestRating": 5,
            "worstRating": 1,
        }
        items = [_review(r) for r in reviews]
        if items:
            data["review"] = items
    return data


def review_author_name(review):
    """The same masked public name the review list shows."""
    from reviews.services import author_name

    return author_name(review.user)


def _review(review):
    data = {
        "@type": "Review",
        "author": {"@type": "Person", "name": review_author_name(review)},
        "reviewRating": {"@type": "Rating", "ratingValue": review.rating, "bestRating": 5, "worstRating": 1},
        "reviewBody": plain_text(review.text),
        "datePublished": timezone.localtime(review.created_at).date().isoformat(),
    }
    if review.title:
        data["name"] = review.title
    return data

"""Rating figures from APPROVED reviews only (storefront, product cards, Product JSON-LD)."""

from dataclasses import dataclass, field

from django.db.models import Avg, Count

from .models import Review


@dataclass
class RatingSummary:
    count: int
    average: float  # rounded to 1 decimal
    distribution: dict = field(default_factory=dict)  # {5: n, 4: n, ..., 1: n}

    @property
    def percentages(self):
        """[(stars, count, percent)] from 5 down to 1."""
        return [
            (s, self.distribution.get(s, 0), round(100 * self.distribution.get(s, 0) / self.count))
            for s in range(5, 0, -1)
        ]


def rating_summary(product):
    """RatingSummary, or None when the product has no approved review."""
    rows = Review.objects.approved().filter(product=product).values("rating").annotate(n=Count("id"))
    distribution = {r["rating"]: r["n"] for r in rows}
    count = sum(distribution.values())
    if not count:
        return None
    average = sum(stars * n for stars, n in distribution.items()) / count
    return RatingSummary(count=count, average=round(average, 1), distribution=distribution)


def ratings_for(product_ids):
    """{product_id: (average, count)} for products with at least one approved review (one query)."""
    rows = (
        Review.objects.approved()
        .filter(product_id__in=list(product_ids))
        .values("product_id")
        .annotate(avg=Avg("rating"), n=Count("id"))
    )
    return {r["product_id"]: (round(r["avg"], 1), r["n"]) for r in rows}


def attach_ratings(products):
    """Sets product.rating_average / product.rating_count (None / 0 without approved reviews)
    on each product, with one query. Returns the products as a list."""
    products = list(products)
    ratings = ratings_for(p.pk for p in products)
    for p in products:
        p.rating_average, p.rating_count = ratings.get(p.pk, (None, 0))
    return products

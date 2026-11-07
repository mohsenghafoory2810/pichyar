"""Load the initial product list. Safe to run again: existing products (matched by
slug or name) are left untouched, so prices and stock edited in the admin survive.
The initial gift pool («دستگاه خشابی» and every tobacco product, gift stock 0) is only
created while the pool is empty, so gifts the admin removed don't come back."""

import colorsys
import hashlib
from io import BytesIO

from django.core.files.base import ContentFile
from django.core.management.base import BaseCommand
from django.db import transaction
from django.db.models import Q
from PIL import Image, ImageDraw

from catalog.models import Category, Product, ProductImage
from catalog.seed_data import ACCESSORIES, ACCESSORY_UNIT, CATEGORY_TREE, GIFT_POOL_PRODUCTS, TOBACCO, TOBACCO_UNIT
from catalog.text import make_slug
from orders.models import GiftPoolItem


def placeholder_image(name, base_hue):
    """A plain coloured square (varied per product) with a simple emblem."""
    shift = int(hashlib.md5(name.encode()).hexdigest()[:4], 16) / 0xFFFF
    hue = (base_hue + (shift - 0.5) * 0.08) % 1
    light = colorsys.hls_to_rgb(hue, 0.86, 0.35)
    dark = colorsys.hls_to_rgb(hue, 0.38, 0.40)
    rgb = lambda c: tuple(int(v * 255) for v in c)  # noqa: E731
    img = Image.new("RGB", (600, 600), rgb(light))
    draw = ImageDraw.Draw(img)
    draw.ellipse((170, 170, 430, 430), outline=rgb(dark), width=18)
    draw.ellipse((255, 255, 345, 345), fill=rgb(dark))
    out = BytesIO()
    img.save(out, "PNG")
    return ContentFile(out.getvalue(), name=f"{make_slug(name)[:60] or 'product'}.png")


class Command(BaseCommand):
    help = "Create the initial categories and products (stock 0) with placeholder images. Idempotent."

    def add_arguments(self, parser):
        parser.add_argument("--no-images", action="store_true", help="Do not create placeholder images.")

    @transaction.atomic
    def handle(self, *args, no_images=False, **options):
        categories = self.ensure_categories()
        rows = [(name, price, "tobacco", None, TOBACCO_UNIT, 0.08) for name, price in TOBACCO]
        rows += [(name, price, cat, short, ACCESSORY_UNIT, 0.58) for name, price, cat, short in ACCESSORIES]

        created = 0
        for sort_order, (name, price, cat_slug, short_name, unit, hue) in enumerate(rows):
            slug = make_slug(name)
            if Product.objects.filter(Q(slug=slug) | Q(name=name)).exists():
                continue
            product = Product.objects.create(
                name=name,
                short_name=short_name or name,
                slug=slug,
                category=categories[cat_slug],
                price=price,
                unit=unit,
                stock=0,
                sort_order=sort_order,
            )
            if not no_images:
                ProductImage.objects.create(product=product, image=placeholder_image(name, hue), order=0)
            created += 1
        self.stdout.write(self.style.SUCCESS(f"{created} new products, {len(rows) - created} already existed."))
        gifts = self.ensure_gift_pool(categories["tobacco"])
        if gifts:
            self.stdout.write(self.style.SUCCESS(f"Gift pool: {gifts} products added (gift stock 0; set it in the admin)."))

    def ensure_gift_pool(self, tobacco):
        if GiftPoolItem.objects.exists():
            return 0
        products = Product.objects.filter(Q(category=tobacco) | Q(name__in=GIFT_POOL_PRODUCTS)).order_by(
            "sort_order", "id"
        )
        GiftPoolItem.objects.bulk_create(
            GiftPoolItem(product=product, gift_stock=0, order=i) for i, product in enumerate(products)
        )
        return len(products)

    def ensure_categories(self):
        by_slug = {}
        for order, (slug, name, children) in enumerate(CATEGORY_TREE):
            parent, _ = Category.objects.get_or_create(slug=slug, defaults={"name": name, "order": order})
            by_slug[slug] = parent
            for child_order, (child_slug, child_name) in enumerate(children):
                by_slug[child_slug], _ = Category.objects.get_or_create(
                    slug=child_slug, defaults={"name": child_name, "parent": parent, "order": child_order}
                )
        return by_slug

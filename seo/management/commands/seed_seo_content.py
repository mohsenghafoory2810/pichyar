"""Fill empty SEO content: site description, home page texts, category intros/guides/meta/FAQs,
product descriptions/meta titles and the guide articles (seo/content/). Safe to run again: anything
already written in the admin is left untouched, and articles are matched by title.

    python manage.py seed_seo_content              # articles are created as drafts
    python manage.py seed_seo_content --publish    # ... or published right away
    python manage.py seed_seo_content --dry-run    # only report what would change
    python manage.py seed_seo_content --overwrite  # replace the existing texts with seo/content/

--overwrite replaces the home page texts, the category texts and FAQs and the product descriptions
that have a text in seo/content/, even when they were edited in the admin (take a backup first).
Product SEO titles, the site description and existing articles are never replaced.
"""

import re
from urllib.parse import unquote

from django.core.management.base import BaseCommand
from django.db import transaction

from blog.models import Article, ArticleCategory, ArticleFAQ
from catalog.models import Category, CategoryFAQ, Product
from core.html import rich_text, sanitize_html
from core.models import SiteSettings
from core.persian import latin_digits
from seo.content import articles as article_content
from seo.content import catalog as catalog_content
from seo.models import META_TITLE_MAX

SITE_SUFFIX = " | پیچ‌یار"


def norm(text):
    """Name key that ignores spacing/ZWNJ and Arabic ي/ك, so «زیگ‌زاگ» matches «زیگ زاگ»."""
    return "".join((text or "").replace("ي", "ی").replace("ك", "ک").replace("‌", "").split())


_PRODUCT_LINK = re.compile(r'<a href="/p/([^"/]+)/">(.*?)</a>', re.DOTALL)
_NOT_WORD = re.compile(r"[\W_]+")


def link_key(text):
    """Product name or slug reduced to letters and digits («دستگاه-زیگ‌زاگ» = «دستگاه زیگ زاگ»)."""
    return _NOT_WORD.sub("", latin_digits(norm(unquote(text))))


class ProductLinks:
    """The texts link to products as /p/<name with hyphens>/. The real slug can differ (half-spaces,
    digits, a renamed product), so every such link is pointed at the product's actual URL; a link to
    a product that does not exist is removed and its text kept."""

    def __init__(self):
        self.urls = {link_key(p.name): p.get_absolute_url() for p in Product.objects.all()}
        self.missing = set()

    def __call__(self, html):
        def replace(match):
            url = self.urls.get(link_key(match.group(1)))
            if url:
                return f'<a href="{url}">{match.group(2)}</a>'
            self.missing.add(unquote(match.group(1)))
            return match.group(2)

        return _PRODUCT_LINK.sub(replace, html or "")


def product_meta_title(product):
    """«خرید توتون چاپمن آلمانی | پیچ‌یار» / «خرید دستگاه خشابی | پیچ‌یار»; the suffix is dropped when too long."""
    prefix = "خرید توتون " if product.category.slug == "tobacco" else "خرید "
    for title in (f"{prefix}{product.name}{SITE_SUFFIX}", f"{prefix}{product.name}"):
        if len(title) <= META_TITLE_MAX:
            return title
    return ""


class Command(BaseCommand):
    help = "Fill empty SEO texts (categories, products, site description) and add starter articles. Idempotent."

    def add_arguments(self, parser):
        parser.add_argument("--publish", action="store_true", help="Publish new articles instead of saving drafts.")
        parser.add_argument("--dry-run", action="store_true", help="Report what would change, write nothing.")
        parser.add_argument(
            "--overwrite", action="store_true", help="Replace existing home, category and product texts (not only empty ones)."
        )

    def handle(self, *args, publish=False, dry_run=False, overwrite=False, **options):
        self.overwrite = overwrite
        self.counts = {}
        with transaction.atomic():
            self.links = ProductLinks()
            self.site()
            self.categories()
            self.products()
            self.articles(publish)
            if dry_run:
                transaction.set_rollback(True)
        for slug in sorted(self.links.missing):
            self.stdout.write(f"  لینک به محصولی که پیدا نشد (حذف شد): {slug}")
        label = "اجرای آزمایشی (چیزی ذخیره نشد)" if dry_run else "انجام شد"
        self.stdout.write(self.style.SUCCESS(label))
        for key, value in self.counts.items():
            self.stdout.write(f"  {key}: {value}")

    def count(self, key, n=1):
        self.counts[key] = self.counts.get(key, 0) + n

    # --- site -------------------------------------------------------------------------
    def site(self):
        for settings in SiteSettings.objects.all():
            if not settings.site_description.strip():
                settings.site_description = catalog_content.SITE_DESCRIPTION
                settings.save(update_fields=["site_description"])
                self.count("توضیح سایت")
            changed = []
            for field, value in catalog_content.HOME.items():
                value = sanitize_html(self.links(value.strip())) if field == "home_intro" else value.strip()
                current = (getattr(settings, field) or "").strip()
                if (self.overwrite and current != value) or not current:
                    setattr(settings, field, value)
                    changed.append(field)
            if changed:
                settings.save(update_fields=changed)
                self.count("متن‌های صفحهٔ اصلی", len(changed))

    # --- categories -------------------------------------------------------------------
    def categories(self):
        for category in Category.objects.all():
            data = catalog_content.CATEGORIES.get(category.slug)
            if not data:
                continue
            changed = []
            for field in ("meta_title", "meta_description", "intro", "guide"):
                value = (data.get(field) or "").strip()
                if field in ("intro", "guide"):
                    value = sanitize_html(self.links(value))  # the stored form
                current = (getattr(category, field) or "").strip()
                if value and ((self.overwrite and current != value) or not current):
                    setattr(category, field, value)
                    changed.append(field)
            if changed:
                category.save()
                self.count("دسته‌بندی‌های به‌روزشده")
            faqs = [(f.question, f.answer) for f in category.faqs.all()]
            if self.overwrite and faqs and faqs != list(data["faqs"]):
                category.faqs.all().delete()
                faqs = []
            if not faqs:
                CategoryFAQ.objects.bulk_create(
                    CategoryFAQ(category=category, question=q, answer=a, order=i)
                    for i, (q, a) in enumerate(data["faqs"])
                )
                self.count("پرسش‌های دسته‌بندی", len(data["faqs"]))

    # --- products ---------------------------------------------------------------------
    def products(self):
        tobacco = {link_key(name): text for name, text in catalog_content.TOBACCO.items()}
        accessories = {link_key(name): text for name, text in catalog_content.ACCESSORIES.items()}
        missing = []
        for product in Product.objects.select_related("category").order_by("sort_order", "pk"):
            key = link_key(product.name)
            if key in tobacco:
                description = tobacco[key]
            elif key in accessories:
                description = accessories[key]
            else:
                missing.append(product.name)
                continue
            fields = []
            description = rich_text(self.links(description))  # the form it is stored in, so a second run changes nothing
            if (self.overwrite and product.description != description) or not product.description.strip():
                product.description = description
                fields.append("description")
            if not product.meta_title.strip():
                title = product_meta_title(product)
                if title:
                    product.meta_title = title
                    fields.append("meta_title")
            if fields:
                product.save(update_fields=[*fields, "updated_at"])
                self.count("محصولات به‌روزشده")
        if missing:
            self.count("محصولات بدون متن آماده", len(missing))
            for name in missing:
                self.stdout.write(f"  بدون متن آماده: {name}")

    # --- articles ---------------------------------------------------------------------
    def articles(self, publish):
        data = article_content.CATEGORY
        category, created = ArticleCategory.objects.get_or_create(
            name=data["name"],
            defaults={"description": data["description"], "meta_description": data["meta_description"]},
        )
        if created:
            self.count("دستهٔ مقاله")
        products = {link_key(p.name): p for p in Product.objects.all()}
        new_articles = []
        for item in article_content.ARTICLES:
            existing = Article.objects.filter(title=item["title"]).first()
            if existing:
                # A guide added earlier as a draft: --publish puts it on the site (its text is kept).
                if publish and existing.status == Article.Status.DRAFT:
                    existing.status = Article.Status.PUBLISHED
                    existing.save()
                    self.count("پیش‌نویس‌های منتشرشده")
                continue
            article = Article(
                title=item["title"],
                meta_title=item["meta_title"],
                meta_description=item["meta_description"],
                short_answer=item["short_answer"],
                body=self.links(item["body"].strip()) + "\n" + article_content.HEALTH_NOTE,
                category=category,
                author_name=article_content.AUTHOR,
                status=Article.Status.PUBLISHED if publish else Article.Status.DRAFT,
            )  # save() sets published_at when publishing
            article.save()
            ArticleFAQ.objects.bulk_create(
                ArticleFAQ(article=article, question=q, answer=a, order=i) for i, (q, a) in enumerate(item["faqs"])
            )
            article.related_products.set([products[link_key(n)] for n in item["related_products"] if link_key(n) in products])
            new_articles.append(article)
            self.count("مقاله‌های جدید")
        # Link the new guides to each other: the three that follow each one (wrapping around), so
        # every guide is linked from others however many there are.
        for index, article in enumerate(new_articles):
            others = new_articles[index + 1 :] + new_articles[:index]
            article.related_articles.set(others[:3])

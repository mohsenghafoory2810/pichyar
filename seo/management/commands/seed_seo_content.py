"""Fill empty SEO content: site description, category intros/meta/FAQs, product descriptions/meta
titles and the starter guide articles (seo/content/). Safe to run again: anything already written
in the admin is left untouched, and articles are matched by title.

    python manage.py seed_seo_content              # articles are created as drafts
    python manage.py seed_seo_content --publish    # ... or published right away
    python manage.py seed_seo_content --dry-run    # only report what would change
"""

from django.core.management.base import BaseCommand
from django.db import transaction

from blog.models import Article, ArticleCategory, ArticleFAQ
from catalog.models import Category, CategoryFAQ, Product
from core.models import SiteSettings
from seo.content import articles as article_content
from seo.content import catalog as catalog_content
from seo.models import META_TITLE_MAX

SITE_SUFFIX = " | پیچ‌یار"


def norm(text):
    """Name key that ignores spacing/ZWNJ and Arabic ي/ك, so «زیگ‌زاگ» matches «زیگ زاگ»."""
    return "".join((text or "").replace("ي", "ی").replace("ك", "ک").replace("‌", "").split())


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

    def handle(self, *args, publish=False, dry_run=False, **options):
        self.counts = {}
        with transaction.atomic():
            self.site()
            self.categories()
            self.products()
            self.articles(publish)
            if dry_run:
                transaction.set_rollback(True)
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

    # --- categories -------------------------------------------------------------------
    def categories(self):
        for category in Category.objects.all():
            data = catalog_content.CATEGORIES.get(category.slug)
            if not data:
                continue
            changed = []
            for field in ("meta_title", "meta_description", "intro"):
                if not (getattr(category, field) or "").strip():
                    setattr(category, field, data[field].strip())
                    changed.append(field)
            if changed:
                category.save()
                self.count("دسته‌بندی‌های به‌روزشده")
            if not category.faqs.exists():
                CategoryFAQ.objects.bulk_create(
                    CategoryFAQ(category=category, question=q, answer=a, order=i)
                    for i, (q, a) in enumerate(data["faqs"])
                )
                self.count("پرسش‌های دسته‌بندی", len(data["faqs"]))

    # --- products ---------------------------------------------------------------------
    def products(self):
        tobacco = {norm(name): text for name, text in catalog_content.TOBACCO.items()}
        accessories = {norm(name): text for name, text in catalog_content.ACCESSORIES.items()}
        tobacco_index = 0
        missing = []
        for product in Product.objects.select_related("category").order_by("sort_order", "pk"):
            key = norm(product.name)
            if key in tobacco:
                use = catalog_content.TOBACCO_USE[tobacco_index % len(catalog_content.TOBACCO_USE)]
                tobacco_index += 1
                description = f"{tobacco[key]}\n\n{use}"
            elif key in accessories:
                description = accessories[key]
            else:
                missing.append(product.name)
                continue
            fields = []
            if not product.description.strip():
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
        products = {norm(p.name): p for p in Product.objects.all()}
        new_articles = []
        for item in article_content.ARTICLES:
            if Article.objects.filter(title=item["title"]).exists():
                continue
            article = Article(
                title=item["title"],
                meta_title=item["meta_title"],
                meta_description=item["meta_description"],
                short_answer=item["short_answer"],
                body=item["body"].strip() + "\n" + article_content.HEALTH_NOTE,
                category=category,
                author_name=article_content.AUTHOR,
                status=Article.Status.PUBLISHED if publish else Article.Status.DRAFT,
            )  # save() sets published_at when publishing
            article.save()
            ArticleFAQ.objects.bulk_create(
                ArticleFAQ(article=article, question=q, answer=a, order=i) for i, (q, a) in enumerate(item["faqs"])
            )
            article.related_products.set([products[norm(n)] for n in item["related_products"] if norm(n) in products])
            new_articles.append(article)
            self.count("مقاله‌های جدید")
        # Link the new guides to each other (up to three each).
        for article in new_articles:
            article.related_articles.set([a for a in new_articles if a.pk != article.pk][:3])

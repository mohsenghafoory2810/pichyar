"""manage.py seed_seo_content: fills only empty fields, is idempotent, and the texts show up on the pages."""

from io import StringIO

from django.core.management import call_command

from blog.models import Article
from catalog.models import Category
from core.models import SiteSettings
from seo.content import articles as article_content
from seo.content import catalog as catalog_content
from seo.meta import plain_text

from .utils import SEOTestCase, jsonld_of_type, make_product


def run(*args):
    call_command("seed_seo_content", *args, stdout=StringIO())


class SeedContentTests(SEOTestCase):
    def test_fills_empty_fields_and_keeps_admin_text(self):
        chapman = make_product("چاپمن آلمانی")
        machine = make_product("دستگاه زیگ زاگ طلایی ترکیه ای", category=Category.objects.get(slug="machines"))  # spacing differs
        edited = make_product("دیویدوف", description="متن خود مدیر", meta_title="عنوان خود مدیر")
        unknown = make_product("محصول تازه")
        self.tobacco.intro = "<p>معرفی خود مدیر</p>"
        self.tobacco.save()

        run()

        chapman.refresh_from_db()
        self.assertTrue(plain_text(chapman.description).startswith(plain_text(catalog_content.TOBACCO["چاپمن آلمانی"])))
        self.assertEqual(chapman.meta_title, "خرید توتون چاپمن آلمانی | پیچ‌یار")
        machine.refresh_from_db()
        self.assertIn("زیگ‌زاگ", machine.description)
        self.assertEqual(machine.meta_title, "خرید دستگاه زیگ زاگ طلایی ترکیه ای | پیچ‌یار")
        edited.refresh_from_db()
        self.assertEqual((edited.description, edited.meta_title), ("<p>متن خود مدیر</p>", "عنوان خود مدیر"))
        unknown.refresh_from_db()
        self.assertEqual(unknown.description, "")

        self.tobacco.refresh_from_db()
        self.assertEqual(self.tobacco.intro, "<p>معرفی خود مدیر</p>")
        self.assertEqual(self.tobacco.meta_title, catalog_content.CATEGORIES["tobacco"]["meta_title"])
        self.assertEqual(self.tobacco.faqs.count(), len(catalog_content.CATEGORIES["tobacco"]["faqs"]))
        self.assertTrue(self.pipes.faqs.exists())
        self.assertEqual(SiteSettings.objects.get().site_description, catalog_content.SITE_DESCRIPTION)

    def test_idempotent_and_articles_are_drafts_by_default(self):
        make_product("دستگاه خشابی", category=Category.objects.get(slug="machines"))
        run()
        run()
        self.assertEqual(Article.objects.count(), len(article_content.ARTICLES))
        self.assertFalse(Article.objects.published().exists())
        self.assertEqual(self.tobacco.faqs.count(), len(catalog_content.CATEGORIES["tobacco"]["faqs"]))
        article = Article.objects.get(title=article_content.ARTICLES[0]["title"])
        self.assertEqual(article.faqs.count(), 3)
        self.assertTrue(article.related_products.filter(name="دستگاه خشابی").exists())
        self.assertEqual(article.related_articles.count(), 3)

    def test_dry_run_writes_nothing(self):
        run("--dry-run")
        self.assertFalse(Article.objects.exists())
        self.assertFalse(self.tobacco.faqs.exists())

    def test_published_guides_and_category_texts_render(self):
        run("--publish")
        self.assertEqual(Article.objects.published().count(), len(article_content.ARTICLES))

        response = self.html(self.tobacco.get_absolute_url())
        self.assertContains(response, "توتون سیگار پیچ</strong>")
        self.assertTrue(jsonld_of_type(response, "FAQPage"))

        article = Article.objects.get(title=article_content.ARTICLES[0]["title"])
        response = self.html(article.get_absolute_url())
        self.assertContains(response, "آماده کردن توتون")
        self.assertTrue(jsonld_of_type(response, "FAQPage"))

    def test_overwrite_replaces_texts_and_is_idempotent(self):
        machine = make_product("دستگاه خشابی", category=Category.objects.get(slug="machines"))
        edited = make_product("دیویدوف", description="متن قدیمی", meta_title="عنوان خود مدیر")
        self.tobacco.intro = "<p>معرفی قدیمی</p>"
        self.tobacco.save()
        run()

        out = StringIO()
        call_command("seed_seo_content", "--overwrite", stdout=out)
        edited.refresh_from_db()
        self.assertNotIn("متن قدیمی", edited.description)
        self.assertEqual(edited.meta_title, "عنوان خود مدیر")  # SEO titles are never replaced
        self.tobacco.refresh_from_db()
        self.assertNotIn("معرفی قدیمی", self.tobacco.intro)
        self.assertTrue(self.tobacco.guide)
        self.assertEqual(self.tobacco.faqs.count(), len(catalog_content.CATEGORIES["tobacco"]["faqs"]))
        site = SiteSettings.objects.get()
        self.assertEqual(site.home_meta_title, catalog_content.HOME["home_meta_title"])
        self.assertIn("<h2>", site.home_intro)

        # Links to products point at real product URLs; links to products that do not exist are dropped.
        machine.refresh_from_db()
        self.assertNotIn('href="/p/', self.tobacco.guide.replace(f'href="{machine.get_absolute_url()}"', ""))
        self.assertIn("پیدا نشد", out.getvalue())

        out = StringIO()
        call_command("seed_seo_content", "--overwrite", stdout=out)
        for label in ("محصولات به‌روزشده", "دسته‌بندی‌های به‌روزشده", "پرسش‌های دسته‌بندی", "متن‌های صفحهٔ اصلی"):
            self.assertNotIn(label, out.getvalue())

    def test_publish_also_publishes_earlier_drafts(self):
        run()
        self.assertFalse(Article.objects.published().exists())
        run("--publish")
        self.assertEqual(Article.objects.published().count(), len(article_content.ARTICLES))

    def test_content_limits_and_links(self):
        import re

        from seo.models import META_DESCRIPTION_MAX, META_TITLE_MAX

        names = {name.replace(" ", "-") for name in [*catalog_content.TOBACCO, *catalog_content.ACCESSORIES]}
        texts = [*catalog_content.TOBACCO.values(), *catalog_content.ACCESSORIES.values(), catalog_content.HOME["home_intro"]]
        for slug, data in catalog_content.CATEGORIES.items():
            self.assertLessEqual(len(data["meta_title"]), META_TITLE_MAX, slug)
            self.assertLessEqual(len(data["meta_description"]), META_DESCRIPTION_MAX, slug)
            texts += [data["intro"], data["guide"]]
        for item in article_content.ARTICLES:
            self.assertLessEqual(len(item["meta_title"]), META_TITLE_MAX, item["title"])
            self.assertLessEqual(len(item["meta_description"]), META_DESCRIPTION_MAX, item["title"])
            texts.append(item["body"])
        for text in texts:
            for href in re.findall(r'href="([^"]+)"', text):
                if href.startswith("/p/"):
                    self.assertIn(href[3:-1], names, href)
                else:
                    self.assertRegex(href, r"^/(blog/|c/[a-z]+/)$")

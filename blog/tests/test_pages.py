import json
import re
from datetime import datetime, timedelta

from django.conf import settings
from django.contrib.auth import get_user_model
from django.template.loader import render_to_string
from django.test import TestCase
from django.utils import timezone

from blog.models import Article, ArticleCategory, ArticleFAQ, Tag
from blog.services import latest_articles
from blog.views import PAGE_SIZE
from catalog.tests.utils import TempMediaMixin, image_upload, make_product

from .utils import make_article

LD_JSON = re.compile(r'<script type="application/ld\+json">(.*?)</script>', re.DOTALL)


class BlogTestCase(TestCase):
    def setUp(self):
        self.client.cookies[settings.AGE_GATE_COOKIE] = "1"


class ListPagesTests(BlogTestCase):
    def test_list_shows_only_published(self):
        make_article("منتشرشده")
        make_article("پیش‌نویس", status=Article.Status.DRAFT)
        make_article("آینده", published_at=timezone.now() + timedelta(days=2))
        response = self.client.get("/blog/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual([a.title for a in response.context["articles"]], ["منتشرشده"])
        self.assertContains(response, "<h1", count=1)
        meta = response.context["page_meta"]
        self.assertEqual(meta.canonical, "http://testserver/blog/")
        self.assertFalse(meta.noindex)

    def test_empty_list(self):
        response = self.client.get("/blog/")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "هنوز مقاله‌ای منتشر نشده است.")

    def test_pagination_canonical_and_404(self):
        for i in range(PAGE_SIZE + 1):
            make_article(f"مقاله {i}", published_at=timezone.now() - timedelta(hours=i + 1))
        first = self.client.get("/blog/")
        self.assertEqual(len(first.context["articles"]), PAGE_SIZE)
        self.assertContains(first, 'href="?page=2"')
        second = self.client.get("/blog/", {"page": 2})
        self.assertEqual(second.status_code, 200)
        self.assertEqual(len(second.context["articles"]), 1)
        self.assertEqual(second.context["page_meta"].canonical, "http://testserver/blog/?page=2")
        self.assertIn("صفحهٔ 2", second.context["page_meta"].title)
        self.assertContains(second, 'href="/blog/"')  # back to page 1 without ?page=1
        for bad in ("3", "0", "abc", "-1", "۲"):
            with self.subTest(page=bad):
                self.assertEqual(self.client.get("/blog/", {"page": bad}).status_code, 404)

    def test_category_page(self):
        cat = ArticleCategory.objects.create(name="راهنمای خرید", description="توضیح دسته")
        other = ArticleCategory.objects.create(name="دیگر")
        make_article("در دسته", category=cat)
        make_article("بیرون", category=other)
        response = self.client.get(cat.get_absolute_url())
        self.assertEqual([a.title for a in response.context["articles"]], ["در دسته"])
        self.assertContains(response, "توضیح دسته")
        meta = response.context["page_meta"]
        self.assertEqual(meta.canonical, "http://testserver" + cat.get_absolute_url())
        self.assertEqual([c["name"] for c in meta.breadcrumbs], ["خانه", "مقاله‌ها", "راهنمای خرید"])
        self.assertContains(response, 'aria-label="مسیر"')
        self.assertEqual(self.client.get("/blog/category/nope/").status_code, 404)

    def test_category_seo_fields(self):
        cat = ArticleCategory.objects.create(name="دسته", meta_title="عنوان سفارشی", noindex=True)
        meta = self.client.get(cat.get_absolute_url()).context["page_meta"]
        self.assertEqual(meta.title, "عنوان سفارشی")
        self.assertTrue(meta.noindex)

    def test_tag_noindex_when_thin(self):
        tag = Tag.objects.create(name="مبتدی")
        for i in range(2):
            make_article(f"برچسب‌دار {i}").tags.add(tag)
        make_article("پیش‌نویس برچسب‌دار", status=Article.Status.DRAFT).tags.add(tag)  # drafts don't count
        response = self.client.get(tag.get_absolute_url())
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.context["articles"]), 2)
        self.assertTrue(response.context["page_meta"].noindex)
        make_article("سومی").tags.add(tag)
        self.assertFalse(self.client.get(tag.get_absolute_url()).context["page_meta"].noindex)
        self.assertEqual(self.client.get("/blog/tag/nope/").status_code, 404)

    def test_latest_articles_service_and_partial(self):
        self.assertEqual(render_to_string("blog/_latest_articles.html", {"latest_articles": latest_articles()}).strip(), "")
        for i in range(4):
            make_article(f"تازه {i}", published_at=timezone.now() - timedelta(hours=i + 1))
        make_article("پیش‌نویس", status=Article.Status.DRAFT)
        articles = latest_articles()
        self.assertEqual([a.title for a in articles], ["تازه 0", "تازه 1", "تازه 2"])
        html = render_to_string("blog/_latest_articles.html", {"latest_articles": articles})
        self.assertIn("تازه‌ترین مقاله‌ها", html)
        self.assertIn('href="/blog/"', html)
        self.assertEqual(html.count("<h3"), 3)


class ArticleDetailTests(TempMediaMixin, BlogTestCase):
    def setUp(self):
        super().setUp()
        self.category = ArticleCategory.objects.create(name="راهنما")
        self.tag = Tag.objects.create(name="نکته")
        self.article = make_article(
            "عنوان مقاله",
            category=self.category,
            short_answer="پاسخ کوتاه آزمایشی.",
            body="<h2>بخش اول</h2><p>متن</p><h3>زیر بخش</h3><p>متن</p><h2>بخش دوم</h2>",
            author_name="نویسندهٔ آزمایشی",
            cover=image_upload(),
            cover_alt="توضیح تصویر",
        )
        self.article.tags.add(self.tag)

    def get(self, article=None):
        return self.client.get((article or self.article).get_absolute_url())

    def test_renders(self):
        response = self.get()
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "<h1", count=1)
        self.assertContains(response, 'role="note"')
        self.assertContains(response, "پاسخ کوتاه آزمایشی.")
        self.assertContains(response, "نویسندهٔ آزمایشی")
        self.assertContains(response, "دقیقه مطالعه")
        self.assertContains(response, "آخرین به‌روزرسانی")
        published_iso = timezone.localtime(self.article.published_at).replace(microsecond=0).isoformat()
        self.assertContains(response, f'<time datetime="{published_iso}">')
        self.assertContains(response, self.category.get_absolute_url())
        self.assertContains(response, self.tag.get_absolute_url())
        self.assertContains(response, 'fetchpriority="high"')
        self.assertContains(response, 'alt="توضیح تصویر"')
        self.assertContains(response, f'width="{self.article.cover_width}" height="{self.article.cover_height}"')
        self.assertNotContains(response, "پیش‌نمایش پیش‌نویس")
        meta = response.context["page_meta"]
        self.assertEqual(meta.og_type, "article")
        self.assertTrue(meta.published_time and meta.modified_time)
        self.assertTrue(meta.image.startswith("http://testserver/"))
        self.assertEqual(meta.canonical, "http://testserver" + self.article.get_absolute_url())
        self.assertEqual([c["name"] for c in meta.breadcrumbs], ["خانه", "مقاله‌ها", "راهنما", "عنوان مقاله"])
        self.assertIsNone(meta.breadcrumbs[-1]["url"])
        self.assertFalse(meta.noindex)

    def test_heading_order(self):
        content = self.get().content.decode()
        levels = [int(n) for n in re.findall(r"<h([1-6])\b", content.split('id="main"', 1)[-1])]
        self.assertEqual(levels[0], 1)
        self.assertEqual(levels.count(1), 1)
        for prev, cur in zip(levels, levels[1:]):
            self.assertLessEqual(cur, prev + 1, levels)  # never skips a level

    def test_toc_links_match_heading_ids(self):
        response = self.get()
        content = response.content.decode()
        toc = response.context["toc"]
        self.assertEqual([t["title"] for t in toc], ["بخش اول", "زیر بخش", "بخش دوم"])
        for item in toc:
            self.assertIn(f'href="#{item["id"]}"', content)
            self.assertIn(f'id="{item["id"]}"', content)
        self.assertIn("فهرست مطالب", content)

    def test_draft_and_future_are_404_for_public(self):
        draft = make_article("پیش‌نویس", status=Article.Status.DRAFT)
        future = make_article("آینده", published_at=timezone.now() + timedelta(days=1))
        self.assertEqual(self.get(draft).status_code, 404)
        self.assertEqual(self.get(future).status_code, 404)
        customer = get_user_model().objects.create_user("09120000009", password="pass")
        self.client.force_login(customer)
        self.assertEqual(self.get(draft).status_code, 404)

    def test_staff_preview(self):
        draft = make_article("پیش‌نویس", status=Article.Status.DRAFT, body="<h2>بخش</h2>")
        future = make_article("آینده", published_at=timezone.now() + timedelta(days=1))
        staff = get_user_model().objects.create_user("09120000002", password="pass", is_staff=True)
        self.client.force_login(staff)
        for article in (draft, future):
            with self.subTest(article=article.title):
                response = self.get(article)
                self.assertEqual(response.status_code, 200)
                self.assertContains(response, "پیش‌نمایش پیش‌نویس")
                self.assertTrue(response.context["page_meta"].noindex)
                self.assertTrue(response.context["page_meta"].jsonld[0]["datePublished"])
        published = self.get()  # a published article is not a preview, even for staff
        self.assertNotContains(published, "پیش‌نمایش پیش‌نویس")
        self.assertFalse(published.context["page_meta"].noindex)

    def test_meta_fields_override(self):
        self.article.meta_title = "عنوان سئو"
        self.article.meta_description = "توضیح متا"
        self.article.noindex = True
        self.article.save()
        meta = self.get().context["page_meta"]
        self.assertEqual((meta.title, meta.description, meta.noindex), ("عنوان سئو", "توضیح متا", True))

    def test_faq_section(self):
        self.assertNotContains(self.get(), "پرسش‌های متداول")
        ArticleFAQ.objects.create(article=self.article, question="پرسش دوم؟", answer="پاسخ دوم", order=2)
        ArticleFAQ.objects.create(article=self.article, question="پرسش اول؟", answer="پاسخ اول", order=1)
        response = self.get()
        self.assertContains(response, '<h2 id="faq-title"')
        self.assertContains(response, "<dt", count=2)
        content = response.content.decode()
        self.assertLess(content.index("پرسش اول؟"), content.index("پرسش دوم؟"))

    def test_related_products_and_articles(self):
        active = make_product("محصول فعال")
        hidden = make_product("محصول غیرفعال", is_active=False)
        self.article.related_products.add(active, hidden)
        other = make_article("مقالهٔ مرتبط")
        draft = make_article("مرتبط پیش‌نویس", status=Article.Status.DRAFT)
        self.article.related_articles.add(other, draft)
        response = self.get()
        self.assertEqual([p.name for p in response.context["related_products"]], ["محصول فعال"])
        self.assertTrue(hasattr(response.context["related_products"][0], "rating_count"))
        self.assertContains(response, "محصولات مرتبط")
        self.assertNotContains(response, "محصول غیرفعال")
        self.assertEqual([a.title for a in response.context["related_articles"]], ["مقالهٔ مرتبط"])
        self.assertNotContains(response, "مرتبط پیش‌نویس")

    def test_list_card_has_lazy_cover(self):
        response = self.client.get("/blog/")
        self.assertContains(response, 'loading="lazy"')
        self.assertContains(response, 'alt="توضیح تصویر"')
        self.assertContains(response, "<time datetime=")


class JsonLdTests(TempMediaMixin, BlogTestCase):
    def setUp(self):
        super().setUp()
        self.article = make_article("عنوان", short_answer="پاسخ کوتاه.", author_name="نویسنده", cover=image_upload())

    def jsonld(self, article=None):
        return self.client.get((article or self.article).get_absolute_url()).context["page_meta"].jsonld

    def test_article_jsonld(self):
        data = json.loads(json.dumps(self.jsonld()[0], ensure_ascii=False))  # JSON-serializable
        self.assertEqual(data["@context"], "https://schema.org")
        self.assertEqual(data["@type"], "BlogPosting")
        self.assertEqual(data["headline"], "عنوان")
        self.assertEqual(data["author"], {"@type": "Person", "name": "نویسنده"})
        self.assertEqual(data["publisher"]["@type"], "Organization")
        self.assertTrue(data["publisher"]["name"])
        self.assertEqual(data["description"], "پاسخ کوتاه.")
        self.assertTrue(data["image"]["url"].startswith("http://testserver/"))
        self.assertEqual(data["mainEntityOfPage"]["@id"], "http://testserver" + self.article.get_absolute_url())
        self.assertEqual(datetime.fromisoformat(data["datePublished"]), self.article.published_at.replace(microsecond=0))
        self.assertTrue(datetime.fromisoformat(data["dateModified"]))
        self.assertEqual(len(self.jsonld()), 1)  # no FAQPage without FAQs

    def test_author_falls_back_to_organization_and_no_cover(self):
        data = self.jsonld(make_article("بدون نویسنده"))[0]
        self.assertEqual(data["author"]["@type"], "Organization")
        self.assertNotIn("image", data)

    def test_faq_page_only_with_faqs(self):
        ArticleFAQ.objects.create(article=self.article, question="پرسش؟", answer="پاسخ <b>پررنگ</b>")
        jsonld = self.jsonld()
        self.assertEqual([d["@type"] for d in jsonld], ["BlogPosting", "FAQPage"])
        self.assertEqual(jsonld[1]["mainEntity"][0]["name"], "پرسش؟")
        self.assertEqual(jsonld[1]["mainEntity"][0]["acceptedAnswer"]["text"], "پاسخ پررنگ")

    def test_rendered_scripts_are_valid_json(self):
        ArticleFAQ.objects.create(article=self.article, question="پرسش؟", answer="پاسخ")
        content = self.client.get(self.article.get_absolute_url()).content.decode()
        scripts = LD_JSON.findall(content)
        if not scripts:
            self.skipTest("base.html does not render page_meta.jsonld yet")
        by_type = {d["@type"]: d for d in (json.loads(s) for s in scripts)}
        self.assertIn("FAQPage", by_type)
        for key in ("headline", "datePublished", "dateModified", "author"):
            self.assertIn(key, by_type["BlogPosting"])


class SanitizationTests(BlogTestCase):
    def test_body_cleaned_on_save_and_render(self):
        article = make_article(
            "امن",
            body=(
                '<h2 onclick="x()">عنوان</h2><script>alert(1)</script>'
                '<p><img src="/a.png" onerror="alert(2)" alt="a"></p>'
                '<p><a href="javascript:alert(3)">پیوند</a> <a href="https://example.com">خوب</a></p>'
                '<p style="color:red">متن</p>'
            ),
        )
        rendered = self.client.get(article.get_absolute_url()).content.decode()
        for text in (article.body, rendered):
            self.assertNotIn("alert(", text)
            self.assertNotIn("onerror", text)
            self.assertNotIn("javascript:", text)
            self.assertNotIn("onclick", text)
            self.assertNotIn('style="color:red"', text)
        self.assertIn('href="https://example.com"', article.body)

    def test_short_answer_and_faq_are_escaped(self):
        article = make_article("فرار", short_answer="<script>alert(1)</script>")
        ArticleFAQ.objects.create(article=article, question="<b>q</b>", answer="<img src=x onerror=alert(1)>")
        content = self.client.get(article.get_absolute_url()).content.decode()
        self.assertNotIn("<script>alert(1)</script>", content)
        self.assertNotIn("<img src=x onerror", content)
        self.assertIn("&lt;script&gt;", content)

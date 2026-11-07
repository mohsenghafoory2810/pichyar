from django.contrib.auth import get_user_model
from django.contrib.messages import get_messages
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from blog.checklist import missing_items
from blog.models import Article, ArticleCategory, ArticleFAQ, Tag
from catalog.tests.utils import TempMediaMixin, image_upload

from .utils import make_article


class ArticleAdminTests(TempMediaMixin, TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = get_user_model().objects.create_superuser("09120000001", email="boss@example.com", password="pass")

    def setUp(self):
        self.client.force_login(self.admin)
        self.category = ArticleCategory.objects.create(name="راهنما")
        self.tag = Tag.objects.create(name="نکته")
        self.article = make_article("مقاله", category=self.category)
        self.article.tags.add(self.tag)

    def test_pages_render(self):
        urls = [
            reverse("admin:blog_article_changelist"),
            reverse("admin:blog_article_add"),
            reverse("admin:blog_article_change", args=[self.article.pk]),
            reverse("admin:blog_articlecategory_changelist"),
            reverse("admin:blog_articlecategory_add"),
            reverse("admin:blog_articlecategory_change", args=[self.category.pk]),
            reverse("admin:blog_tag_changelist"),
            reverse("admin:blog_tag_add"),
        ]
        for url in urls:
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 200)

    def test_changelist_filters_and_search(self):
        url = reverse("admin:blog_article_changelist")
        for params in ({"status__exact": "draft"}, {"category__id__exact": self.category.pk}, {"tags__id__exact": self.tag.pk}, {"q": "مقاله"}):
            with self.subTest(params=params):
                self.assertEqual(self.client.get(url, params).status_code, 200)

    def test_change_form_shows_checklist_and_preview(self):
        response = self.client.get(reverse("admin:blog_article_change", args=[self.article.pk]))
        self.assertContains(response, "فهرست بررسی محتوا")
        self.assertContains(response, "«پاسخ کوتاه» نوشته نشده است")
        self.assertContains(response, "data-seo-counter")
        self.assertContains(response, self.article.get_absolute_url())
        changelist = self.client.get(reverse("admin:blog_article_changelist"))
        self.assertContains(changelist, "۴ مورد ناقص")

    def _post_data(self, **overrides):
        data = {
            "title": "مقالهٔ تازه",
            "slug": "",
            "short_answer": "",
            "body": "<p>متن</p>",
            "cover_alt": "",
            "status": "draft",
            "published_at_0": "",
            "published_at_1": "",
            "author_name": "",
            "category": "",
            "meta_title": "",
            "meta_description": "",
            "canonical_url": "",
            "faqs-TOTAL_FORMS": "0",
            "faqs-INITIAL_FORMS": "0",
            "faqs-MIN_NUM_FORMS": "0",
            "faqs-MAX_NUM_FORMS": "1000",
        }
        data.update(overrides)
        return data

    def test_add_warns_but_saves(self):
        response = self.client.post(reverse("admin:blog_article_add"), self._post_data(), follow=True)
        self.assertEqual(response.status_code, 200)
        article = Article.objects.get(title="مقالهٔ تازه")
        self.assertEqual(article.slug, "مقاله-تازه")  # slug from the title
        warnings = [str(m) for m in get_messages(response.wsgi_request) if m.level_tag == "warning"]
        self.assertEqual(len(warnings), 1)
        for text in ("پاسخ کوتاه", "توضیح متا", "تصویر شاخص", "پرسش متداول"):
            self.assertIn(text, warnings[0])

    def test_complete_article_has_no_warning(self):
        data = self._post_data(
            short_answer="پاسخ.",
            meta_description="توضیح.",
            cover_alt="توضیح تصویر",
            **{
                "faqs-TOTAL_FORMS": "1",
                "faqs-0-question": "پرسش؟",
                "faqs-0-answer": "پاسخ",
                "faqs-0-order": "0",
            },
        )
        data["cover"] = image_upload()
        response = self.client.post(reverse("admin:blog_article_add"), data, follow=True)
        article = Article.objects.get(title="مقالهٔ تازه")
        self.assertEqual(article.faqs.count(), 1)
        self.assertEqual(missing_items(article), [])
        self.assertFalse([m for m in get_messages(response.wsgi_request) if m.level_tag == "warning"])

    def test_cover_without_alt_is_flagged(self):
        article = make_article("با تصویر", cover=image_upload(), short_answer="x", meta_description="y")
        ArticleFAQ.objects.create(article=article, question="q", answer="a")
        self.assertEqual(len(missing_items(article)), 1)
        self.assertIn("متن جایگزین", missing_items(article)[0])

    def test_bulk_publish_and_unpublish(self):
        draft = make_article("پیش‌نویس", status=Article.Status.DRAFT)
        url = reverse("admin:blog_article_changelist")
        self.client.post(url, {"action": "publish", "_selected_action": [draft.pk]})
        draft.refresh_from_db()
        self.assertEqual(draft.status, Article.Status.PUBLISHED)
        self.assertIsNotNone(draft.published_at)
        self.assertLessEqual(draft.published_at, timezone.now())
        self.assertTrue(draft.is_published)

        self.client.post(url, {"action": "unpublish", "_selected_action": [draft.pk, self.article.pk]})
        draft.refresh_from_db()
        self.article.refresh_from_db()
        self.assertEqual(draft.status, Article.Status.DRAFT)
        self.assertEqual(self.article.status, Article.Status.DRAFT)
        self.assertFalse(Article.objects.published().exists())

    def test_staff_preview_from_admin_link(self):
        draft = make_article("پیش‌نویس", status=Article.Status.DRAFT)
        self.assertEqual(self.client.get(draft.get_absolute_url()).status_code, 200)

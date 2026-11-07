"""sitemap.xml, robots.txt and llms.txt."""

from core.models import SiteSettings, StaticPage

from .utils import SEOTestCase, make_article, make_product


class SitemapTests(SEOTestCase):
    def test_index_links_every_section(self):
        response = self.client.get("/sitemap.xml")
        self.assertEqual(response.status_code, 200)
        self.assertIn("xml", response["Content-Type"])
        body = response.content.decode()
        for section in ("products", "categories", "articles", "article-categories", "pages"):
            self.assertIn(f"http://testserver/sitemap-{section}.xml", body)

    def test_unknown_section_is_404(self):
        self.assertEqual(self.client.get("/sitemap-nope.xml").status_code, 404)

    def test_products(self):
        active = make_product("دیویدوف طلایی")
        inactive = make_product("غیرفعال", is_active=False)
        hidden = make_product("بدون ایندکس", noindex=True)
        elsewhere = make_product("کپی", canonical_url="/p/other/")
        own = make_product("کنونیکال خودش")
        own.canonical_url = own.get_absolute_url()
        own.save()
        body = self.client.get("/sitemap-products.xml").content.decode()
        self.assertIn(f"http://testserver{active.get_absolute_url()}", body)  # percent-encoded Persian slug
        self.assertIn("%D8%AF%DB%8C%D9%88%DB%8C%D8%AF%D9%88%D9%81", body)
        self.assertIn(f"http://testserver{own.get_absolute_url()}", body)
        self.assertIn("<lastmod>", body)
        for p in (inactive, hidden, elsewhere):
            self.assertNotIn(p.get_absolute_url(), body)

    def test_categories_with_lastmod(self):
        make_product("پیپ", category=self.pipes)
        self.tobacco.noindex = True
        self.tobacco.save()
        body = self.client.get("/sitemap-categories.xml").content.decode()
        self.assertIn(self.pipes.get_absolute_url(), body)
        self.assertIn(self.accessories.get_absolute_url(), body)
        self.assertNotIn(self.tobacco.get_absolute_url(), body)
        self.assertIn("<lastmod>", body)

    def test_inactive_parent_hides_children(self):
        self.accessories.is_active = False
        self.accessories.save()
        body = self.client.get("/sitemap-categories.xml").content.decode()
        self.assertNotIn(self.pipes.get_absolute_url(), body)

    def test_articles_and_article_categories(self):
        from blog.models import ArticleCategory

        cat = ArticleCategory.objects.create(name="راهنما")
        empty_cat = ArticleCategory.objects.create(name="خالی")
        published = make_article("مقالهٔ منتشرشده", category=cat)
        draft = make_article("پیش‌نویس", published=False, category=empty_cat)
        hidden = make_article("مخفی", noindex=True)
        body = self.client.get("/sitemap-articles.xml").content.decode()
        self.assertIn(published.get_absolute_url(), body)
        self.assertNotIn(draft.get_absolute_url(), body)
        self.assertNotIn(hidden.get_absolute_url(), body)
        self.assertIn("<lastmod>", body)
        body = self.client.get("/sitemap-article-categories.xml").content.decode()
        self.assertIn(cat.get_absolute_url(), body)
        self.assertNotIn(empty_cat.get_absolute_url(), body)

    def test_pages(self):
        about = StaticPage.objects.get(slug="about")
        StaticPage.objects.filter(slug="privacy").update(is_active=False)
        StaticPage.objects.filter(slug="terms").update(noindex=True)
        body = self.client.get("/sitemap-pages.xml").content.decode()
        self.assertIn("<loc>http://testserver/</loc>", body)
        self.assertIn("<loc>http://testserver/blog/</loc>", body)
        self.assertIn(about.get_absolute_url(), body)
        self.assertNotIn("/pages/privacy/", body)
        self.assertNotIn("/pages/terms/", body)
        self.assertIn("<lastmod>", body)

    def test_no_tag_pages(self):
        from blog.models import Tag

        tag = Tag.objects.create(name="برچسب")
        make_article("با برچسب").tags.add(tag)
        for section in ("products", "categories", "articles", "article-categories", "pages"):
            self.assertNotIn("/blog/tag/", self.client.get(f"/sitemap-{section}.xml").content.decode())


class RobotsTests(SEOTestCase):
    def get(self):
        response = self.client.get("/robots.txt")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "text/plain; charset=utf-8")
        return response.content.decode()

    def test_rules_and_sitemap(self):
        body = self.get()
        self.assertTrue(body.startswith("User-agent: *\n"))
        for rule in (
            "/cart/", "/checkout/", "/accounts/", "/payments/", "/search/", "/reviews/",
            "/age-check/", "/tinymce/", "/*?*sort=", "/*?*q=",
        ):
            self.assertIn(f"Disallow: {rule}\n", body)
        self.assertNotIn("page=", body)
        self.assertIn("Sitemap: http://testserver/sitemap.xml", body)

    def test_admin_path_not_revealed(self):
        from django.conf import settings

        self.assertNotIn(settings.ADMIN_URL, self.get())

    def test_ai_crawlers_allowed_by_default(self):
        body = self.get()
        self.assertNotIn("GPTBot", body)
        self.assertEqual(body.count("User-agent:"), 1)

    def test_ai_crawlers_blocked(self):
        SiteSettings.objects.filter(pk=1).update(allow_ai_crawlers=False)
        body = self.get()
        for bot in ("GPTBot", "ClaudeBot", "PerplexityBot", "Google-Extended", "CCBot"):
            self.assertIn(f"User-agent: {bot}\nDisallow: /\n", body)
        self.assertIn("User-agent: *\n", body)


class LlmsTxtTests(SEOTestCase):
    def test_content(self):
        SiteSettings.objects.filter(pk=1).update(
            site_description="یک توضیح ثبت‌شده در مدیریت.", phone="02112345678", support_info="ساعت ۹ تا ۱۷"
        )
        article = make_article("راهنمای نگهداری", short_answer="پاسخ اول. پاسخ دوم.")
        make_article("پیش‌نویس", published=False)
        response = self.client.get("/llms.txt")
        self.assertEqual(response["Content-Type"], "text/plain; charset=utf-8")
        body = response.content.decode()
        site_name = SiteSettings.load().site_name
        self.assertTrue(body.startswith(f"# {site_name}\n"))
        self.assertIn("> یک توضیح ثبت‌شده در مدیریت.", body)
        self.assertIn(f"- [{self.tobacco.name}](http://testserver{self.tobacco.get_absolute_url()})", body)
        self.assertIn(f"  - [{self.pipes.name}](http://testserver{self.pipes.get_absolute_url()})", body)
        self.assertIn("(http://testserver/blog/)", body)
        self.assertIn("/pages/about/", body)
        self.assertIn(f"[راهنمای نگهداری](http://testserver{article.get_absolute_url()}): پاسخ اول.", body)
        self.assertNotIn("پاسخ دوم", body)
        self.assertNotIn("پیش‌نویس", body)
        self.assertIn("- تلفن: 02112345678", body)
        self.assertIn("- ساعت ۹ تا ۱۷", body)

    def test_no_description_no_quote(self):
        self.assertNotIn("\n> ", self.client.get("/llms.txt").content.decode())

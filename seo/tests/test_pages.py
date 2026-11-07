"""Head tags, canonical/noindex rules, JSON-LD and page content."""

import re

from django.test import RequestFactory

from catalog.models import CategoryFAQ, ProductSpec
from catalog.views import PAGE_SIZE
from core.models import SiteSettings, StaticPage
from seo.meta import PageMeta

from .utils import SEOTestCase, jsonld_blocks, jsonld_of_type, make_article, make_customer, make_product

TITLE_RE = re.compile(r"<title>(.*?)</title>", re.S)


def title(response):
    return TITLE_RE.search(response.content.decode()).group(1).strip()


def canonical(response):
    m = re.search(r'<link rel="canonical" href="([^"]*)">', response.content.decode())
    return m.group(1) if m else None


def robots(response):
    return re.search(r'<meta name="robots" content="([^"]*)">', response.content.decode()).group(1)


class HeadTests(SEOTestCase):
    def test_home_defaults_and_site_jsonld(self):
        SiteSettings.objects.filter(pk=1).update(
            site_description="توضیح سایت از مدیریت", phone="021", social_links="https://t.me/x\nnot-a-url"
        )
        response = self.html("/")
        site_name = SiteSettings.load().site_name
        self.assertEqual(title(response), site_name)
        self.assertContains(response, '<meta name="description" content="توضیح سایت از مدیریت">')
        self.assertEqual(canonical(response), "http://testserver/")
        self.assertIn("index, follow", robots(response))
        self.assertContains(response, '<meta property="og:locale" content="fa_IR">')
        self.assertContains(response, f'<meta property="og:site_name" content="{site_name}">')
        self.assertContains(response, '<meta property="og:url" content="http://testserver/">')
        org = jsonld_of_type(response, "Organization")[0]
        self.assertEqual(org["name"], site_name)
        self.assertEqual(org["url"], "http://testserver/")
        self.assertEqual(org["telephone"], "021")
        self.assertEqual(org["sameAs"], ["https://t.me/x"])
        site = jsonld_of_type(response, "WebSite")[0]
        self.assertEqual(
            site["potentialAction"]["target"]["urlTemplate"], "http://testserver/search/?q={search_term_string}"
        )

    def test_verification_tags(self):
        response = self.html("/")
        self.assertNotContains(response, "google-site-verification")
        SiteSettings.objects.filter(pk=1).update(google_site_verification="g-123", bing_site_verification="b-456")
        response = self.html("/")
        self.assertContains(response, '<meta name="google-site-verification" content="g-123">')
        self.assertContains(response, '<meta name="msvalidate.01" content="b-456">')

    def test_analytics_snippet_on_public_pages(self):
        SiteSettings.objects.filter(pk=1).update(analytics_snippet='<script src="/stats.js" data-x="1"></script>')
        self.assertContains(self.html("/"), '<script src="/stats.js" data-x="1"></script>')

    def test_jsonld_is_escaped(self):
        make_product("نام </script><b>", description="x")
        response = self.html(make_product("ب").get_absolute_url())
        self.assertNotContains(response, "</script><b>")
        jsonld_blocks(response)

    def test_unique_titles(self):
        p = make_product("دیویدوف")
        urls = ["/", p.get_absolute_url(), self.tobacco.get_absolute_url(), self.pipes.get_absolute_url(), "/pages/about/"]
        titles = [title(self.html(u)) for u in urls]
        self.assertEqual(len(set(titles)), len(titles), titles)
        self.assertEqual(titles[1], f"دیویدوف | {SiteSettings.load().site_name}")

    def test_private_pages_are_noindex(self):
        self.assertTrue(robots(self.html("/cart/")).startswith("noindex"))

    def test_404_is_noindex(self):
        response = self.client.get("/pages/nope/")
        self.assertEqual(response.status_code, 404)
        self.assertIn("noindex", robots(response))
        self.assertIsNone(canonical(response))


class ListingCanonicalTests(SEOTestCase):
    def test_category_page_one(self):
        response = self.html(self.pipes.get_absolute_url())
        self.assertEqual(canonical(response), f"http://testserver{self.pipes.get_absolute_url()}")
        self.assertIn("index, follow", robots(response))

    def test_sort_and_search_are_noindex_with_base_canonical(self):
        base = f"http://testserver{self.tobacco.get_absolute_url()}"
        for params in ({"sort": "price_asc"}, {"q": "x"}, {"sort": "newest", "page": 1}, {"utm_source": "a"}):
            response = self.html(self.tobacco.get_absolute_url(), data=params)
            self.assertEqual(robots(response), "noindex, follow", params)
            self.assertEqual(canonical(response), base, params)

    def test_pagination_self_canonical(self):
        for i in range(PAGE_SIZE + 1):
            make_product(f"توتون {i}")
        url = self.tobacco.get_absolute_url()
        second = self.html(url, data={"page": 2})
        self.assertEqual(canonical(second), f"http://testserver{url}?page=2")
        self.assertIn("index, follow", robots(second))
        self.assertNotEqual(title(second), title(self.html(url)))
        first = self.html(url, data={"page": 1})
        self.assertEqual(canonical(first), f"http://testserver{url}")
        self.assertNotContains(self.html(url, data={"page": 2}), f'href="{url}?page=1"')

    def test_invalid_pages_are_404(self):
        url = self.tobacco.get_absolute_url()
        for page in ("abc", "0", "-1", "99", "1.5"):
            self.assertEqual(self.client.get(url, {"page": page}).status_code, 404, page)

    def test_search_always_noindex(self):
        response = self.html("/search/", data={"q": "پیپ"})
        self.assertEqual(robots(response), "noindex, follow")
        self.assertEqual(canonical(response), "http://testserver/search/")

    def test_object_overrides(self):
        self.pipes.meta_title = "عنوان دستی"
        self.pipes.meta_description = "توضیح دستی"
        self.pipes.canonical_url = "/c/accessories/"
        self.pipes.noindex = True
        self.pipes.save()
        response = self.html(self.pipes.get_absolute_url())
        self.assertEqual(title(response), "عنوان دستی")
        self.assertContains(response, '<meta name="description" content="توضیح دستی">')
        self.assertEqual(canonical(response), "http://testserver/c/accessories/")
        self.assertEqual(robots(response), "noindex, follow")

    def test_for_object_accepts_noindex_kwarg(self):
        request = RequestFactory().get("/")
        product = make_product("الف")
        meta = PageMeta.for_object(request, product, title="الف", noindex=True)
        self.assertTrue(meta.noindex)
        self.assertFalse(PageMeta.for_object(request, product, title="الف").noindex)


class CategoryContentTests(SEOTestCase):
    def test_intro_faq_and_breadcrumbs(self):
        self.pipes.intro = "<p>متن <strong>معرفی</strong></p><script>alert(1)</script>"
        self.pipes.save()
        CategoryFAQ.objects.create(category=self.pipes, question="پرسش یک؟", answer="پاسخ یک")
        CategoryFAQ.objects.create(category=self.pipes, question="پرسش دو؟", answer="پاسخ دو")
        response = self.html(self.pipes.get_absolute_url())
        self.assertContains(response, "<strong>معرفی</strong>")
        self.assertNotContains(response, "alert(1)")
        self.assertContains(response, "<summary", count=2)
        faq = jsonld_of_type(response, "FAQPage")[0]
        self.assertEqual([q["name"] for q in faq["mainEntity"]], ["پرسش یک؟", "پرسش دو؟"])
        self.assertEqual(faq["mainEntity"][0]["acceptedAnswer"]["text"], "پاسخ یک")
        crumbs = jsonld_of_type(response, "BreadcrumbList")[0]["itemListElement"]
        self.assertEqual([c["name"] for c in crumbs], ["خانه", self.accessories.name, self.pipes.name])
        self.assertEqual(crumbs[-1]["item"], f"http://testserver{self.pipes.get_absolute_url()}")
        self.assertContains(response, f'<li aria-current="page" class="text-ink">{self.pipes.name}</li>')
        self.assertContains(response, "<h1", count=1)

    def test_no_faq_no_faqpage(self):
        self.assertEqual(jsonld_of_type(self.html(self.pipes.get_absolute_url()), "FAQPage"), [])

    def test_description_from_intro(self):
        self.pipes.intro = "<p>معرفی کوتاه دسته</p>"
        self.pipes.save()
        self.assertContains(self.html(self.pipes.get_absolute_url()), '<meta name="description" content="معرفی کوتاه دسته">')


class ProductPageTests(SEOTestCase):
    def test_product_jsonld(self):
        p = make_product("دیویدوف", price=300_000, stock=2, description="توضیح <b>محصول</b>", brand="Davidoff", sku="DV-1")
        ProductSpec.objects.create(product=p, name="کشور سازنده", value="آلمان")
        response = self.html(p.get_absolute_url())
        data = jsonld_of_type(response, "Product")[0]
        self.assertEqual(data["name"], "دیویدوف")
        self.assertEqual(data["sku"], "DV-1")
        self.assertEqual(data["brand"], {"@type": "Brand", "name": "Davidoff"})
        self.assertEqual(data["offers"]["price"], 3_000_000)  # toman × 10 = rial
        self.assertEqual(data["offers"]["priceCurrency"], "IRR")
        self.assertEqual(data["offers"]["availability"], "https://schema.org/InStock")
        self.assertEqual(data["offers"]["url"], f"http://testserver{p.get_absolute_url()}")
        self.assertIn("توضیح محصول", data["description"])
        self.assertIn("کشور سازنده: آلمان", data["description"])
        self.assertNotIn("aggregateRating", data)
        self.assertNotIn("review", data)
        self.assertEqual(canonical(response), f"http://testserver{p.get_absolute_url()}")
        self.assertContains(response, '<meta property="og:type" content="product">')

    def test_out_of_stock_without_brand(self):
        p = make_product("بی‌برند", stock=0)
        data = jsonld_of_type(self.html(p.get_absolute_url()), "Product")[0]
        self.assertEqual(data["offers"]["availability"], "https://schema.org/OutOfStock")
        self.assertNotIn("brand", data)
        self.assertEqual(data["sku"], f"P{p.pk}")

    def test_ratings_only_from_approved_reviews(self):
        from reviews.models import Review

        p = make_product("با نظر")
        for i, (rating, status) in enumerate(
            [(5, Review.Status.APPROVED), (4, Review.Status.APPROVED), (1, Review.Status.PENDING), (1, Review.Status.REJECTED)]
        ):
            Review.objects.create(
                product=p, user=make_customer(f"0912000000{i}", name="علی رضایی"), rating=rating,
                text="متن نظر آزمایشی برای محصول", status=status,
            )
        data = jsonld_of_type(self.html(p.get_absolute_url()), "Product")[0]
        self.assertEqual(
            data["aggregateRating"],
            {"@type": "AggregateRating", "ratingValue": 4.5, "reviewCount": 2, "bestRating": 5, "worstRating": 1},
        )
        self.assertEqual(len(data["review"]), 2)
        self.assertEqual({r["reviewRating"]["ratingValue"] for r in data["review"]}, {4, 5})
        self.assertEqual(data["review"][0]["author"], {"@type": "Person", "name": "علی"})
        self.assertNotIn("0912", str(data["review"]))

    def test_pending_reviews_only_no_rating(self):
        from reviews.models import Review

        p = make_product("بی‌نظر")
        Review.objects.create(product=p, user=make_customer(), rating=5, text="در انتظار بررسی است", status=Review.Status.PENDING)
        data = jsonld_of_type(self.html(p.get_absolute_url()), "Product")[0]
        self.assertNotIn("aggregateRating", data)
        self.assertNotIn("review", data)

    def test_specs_table_and_health_warning(self):
        p = make_product("مشخصه‌دار")
        ProductSpec.objects.create(product=p, name="وزن", value="۵۰ گرم", order=1)
        ProductSpec.objects.create(product=p, name="کشور", value="ترکیه", order=0)
        response = self.html(p.get_absolute_url())
        content = response.content.decode()
        self.assertIn('<th scope="row"', content)
        self.assertLess(content.index("ترکیه"), content.index("۵۰ گرم"))
        warning = SiteSettings.load().health_warning
        self.assertEqual(warning, "استعمال دخانیات برای سلامت مضر است")
        self.assertEqual(content.count("data-health-warning"), 2)  # product page + footer
        self.assertContains(response, "<h1", count=1)

    def test_health_warning_in_footer_everywhere(self):
        self.assertContains(self.html("/pages/about/"), "استعمال دخانیات برای سلامت مضر است")

    def test_default_description_and_breadcrumbs(self):
        p = make_product("بدون توضیح", price=120_000, unit="۵۰ گرم", category=self.pipes)
        response = self.html(p.get_absolute_url())
        site_name = SiteSettings.load().site_name
        self.assertContains(response, f'content="بدون توضیح، ۵۰ گرم، ۱۲۰٬۰۰۰ تومان — {site_name}"')
        crumbs = jsonld_of_type(response, "BreadcrumbList")[0]["itemListElement"]
        self.assertEqual([c["name"] for c in crumbs], ["خانه", self.accessories.name, self.pipes.name, "بدون توضیح"])

    def test_related_products_and_articles(self):
        p = make_product("اصلی")
        sibling = make_product("هم‌دسته")
        make_product("غیرفعال هم‌دسته", is_active=False)
        other = make_product("دستهٔ دیگر", category=self.pipes)
        article = make_article("مقالهٔ مرتبط")
        article.related_products.add(p)
        draft = make_article("پیش‌نویس مرتبط", published=False)
        draft.related_products.add(p)
        response = self.html(p.get_absolute_url())
        self.assertEqual([x.name for x in response.context["related_products"]], ["هم‌دسته"])
        self.assertNotContains(response, other.name)
        self.assertContains(response, "مقاله‌های مرتبط")
        self.assertContains(response, article.get_absolute_url())
        self.assertNotContains(response, "پیش‌نویس مرتبط")
        self.assertTrue(sibling)


class StaticPageTests(SEOTestCase):
    def test_meta(self):
        page = StaticPage.objects.get(slug="about")
        page.body = "<p>متن صفحه درباره</p>"
        page.save()
        response = self.html(page.get_absolute_url())
        self.assertContains(response, '<meta name="description" content="متن صفحه درباره">')
        self.assertEqual(canonical(response), "http://testserver/pages/about/")
        self.assertContains(response, "article:modified_time")
        self.assertEqual(len(jsonld_of_type(response, "BreadcrumbList")), 1)


class InternalLinkTests(SEOTestCase):
    def test_header_and_footer_links(self):
        response = self.html("/pages/about/")
        content = response.content.decode()
        self.assertGreaterEqual(content.count('href="/blog/"'), 2)  # header + footer
        self.assertIn(self.pipes.get_absolute_url(), content)  # footer sub-category link

    def test_home_latest_articles(self):
        article = make_article("تازه‌ترین")
        self.assertContains(self.html("/"), article.get_absolute_url())

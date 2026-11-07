from django.test import override_settings

from catalog.tests.utils import make_product
from reviews.models import Review
from reviews.services import author_name
from reviews.stats import rating_summary

from .utils import ReviewTestCase, make_customer, make_review

S = Review.Status


def section(response):
    """The reviews <section> of the product page (the Product JSON-LD repeats review texts)."""
    html = response.content.decode()
    start = html.index('<section id="reviews"')
    return html[start:html.index("</section>", start)]


class ProductPageTests(ReviewTestCase):
    def test_empty_state(self):
        response = self.client.get(self.product.get_absolute_url())
        self.assertContains(response, "هنوز نظری برای این محصول منتشر نشده است")
        self.assertIsNone(rating_summary(self.product))

    def test_only_approved_reviews_shown_and_counted(self):
        make_review(self.product, self.customer, rating=5, text="نظر تأییدشدهٔ اول")
        make_review(self.product, make_customer("09122222222", name="مریم احمدی"), rating=4, text="نظر تأییدشدهٔ دوم")
        make_review(self.product, make_customer("09123333333"), rating=1, text="نظر در انتظار", status=S.PENDING)
        make_review(self.product, make_customer("09124444444"), rating=1, text="نظر ردشده", status=S.REJECTED)

        summary = rating_summary(self.product)
        self.assertEqual((summary.count, summary.average), (2, 4.5))
        self.assertEqual(summary.percentages[0], (5, 1, 50))

        response = self.client.get(self.product.get_absolute_url())
        self.assertContains(response, "نظر تأییدشدهٔ اول")
        self.assertContains(response, "نظر تأییدشدهٔ دوم")
        self.assertNotContains(response, "نظر در انتظار")  # nor in the JSON-LD
        self.assertNotContains(response, "نظر ردشده")
        self.assertContains(response, "۴٫۵")
        self.assertContains(response, "بر اساس ۲ نظر")
        self.assertContains(response, "۵۰٪")
        self.assertContains(response, "۵ از ۵ ستاره")
        self.assertContains(response, "مریم")
        self.assertNotContains(response, "احمدی")
        self.assertNotContains(response, "09121111111")
        self.assertContains(response, "کاربر …۱۱۱۱")

    def test_card_rating_on_listing(self):
        make_review(self.product, self.customer, rating=4)
        make_review(self.product, make_customer("09125555555"), rating=1, status=S.PENDING)
        unrated = make_product("بدون نظر")
        response = self.client.get(self.product.category.get_absolute_url())
        self.assertContains(response, "امتیاز ۴٫۰ از ۵ بر اساس ۱ نظر")
        self.assertContains(response, "(۱)")
        products = {p.pk: p for p in response.context["products"]}
        self.assertEqual(products[unrated.pk].rating_count, 0)
        self.assertEqual(response.content.decode().count("امتیاز ۴٫۰ از ۵"), 1)

    def test_verified_badge_and_admin_reply(self):
        make_review(self.product, self.customer, verified_purchase=True, admin_reply="از خرید شما سپاسگزاریم.")
        response = self.client.get(self.product.get_absolute_url())
        self.assertContains(response, "خرید تأییدشده")
        self.assertContains(response, "پاسخ فروشگاه")
        self.assertContains(response, "از خرید شما سپاسگزاریم.")

    def test_output_is_escaped(self):
        make_review(self.product, self.customer, text="<script>alert(1)</script>\nخط دوم", title="<b>عنوان</b>",
                    admin_reply="<img src=x onerror=alert(1)>")
        content = self.client.get(self.product.get_absolute_url()).content.decode()
        self.assertNotIn("<script>alert(1)</script>", content)
        self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt;<br>خط دوم", content)
        self.assertNotIn("<b>عنوان</b>", content)
        self.assertNotIn("<img src=x", content)

    def test_author_name(self):
        self.assertEqual(author_name(make_customer("09126666666", name="  علی رضایی ")), "علی")
        self.assertEqual(author_name(make_customer("09127777777")), "کاربر …۷۷۷۷")


@override_settings(REVIEWS_PAGE_SIZE=2)
class PaginationTests(ReviewTestCase):
    def setUp(self):
        super().setUp()
        for i in range(5):
            make_review(self.product, make_customer(f"0912100000{i}"), text=f"نظر شمارهٔ {i} برای آزمون")
        # newest first: 4, 3 | 2, 1 | 0

    def test_first_page_and_more_link(self):
        html = section(self.client.get(self.product.get_absolute_url()))
        self.assertIn("نظر شمارهٔ 4", html)
        self.assertNotIn("نظر شمارهٔ 2", html)
        self.assertIn(f'hx-get="{self.list_url()}?page=2"', html)
        self.assertIn("?reviews_page=2#reviews", html)

    def test_without_js(self):
        html = section(self.client.get(self.product.get_absolute_url(), {"reviews_page": 2}))
        self.assertIn("نظر شمارهٔ 2", html)
        self.assertNotIn("نظر شمارهٔ 4", html)
        self.assertIn("نظرهای جدیدتر", html)

    def test_htmx_partial(self):
        response = self.client.get(self.list_url(), {"page": 3}, HTTP_HX_REQUEST="true")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["X-Robots-Tag"], "noindex")
        self.assertContains(response, "نظر شمارهٔ 0")
        self.assertNotContains(response, "نظر شمارهٔ 1")
        self.assertNotContains(response, "reviews-more")
        self.assertNotContains(response, "<html")

    def test_list_without_htmx_redirects_to_product(self):
        response = self.client.get(self.list_url(), {"page": 2})
        self.assertRedirects(
            response, self.product.get_absolute_url() + "?reviews_page=2#reviews", fetch_redirect_response=False
        )

    def test_pending_not_in_partial(self):
        make_review(self.product, self.customer, text="این نظر هنوز بررسی نشده", status=S.PENDING)
        response = self.client.get(self.list_url(), HTTP_HX_REQUEST="true")
        self.assertNotContains(response, "هنوز بررسی نشده")

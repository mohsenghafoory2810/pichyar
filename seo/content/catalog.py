"""Site description, home page texts, category texts/FAQs and product descriptions.

The category and product texts live in tobacco.py and accessories.py; this module is the one the
seeding command reads. Product descriptions only state what follows from the product's name and
type (plus well-known facts about tobacco origins). Taste, strength and moisture details should be
added in the admin by someone who knows each product.
"""

from . import accessories as _accessories
from . import tobacco as _tobacco

SITE_DESCRIPTION = (
    "پیچ‌یار، فروشگاه آنلاین توتون و لوازم سیگار پیچ: انواع توتون ۵۰ گرمی، دستگاه سیگار پیچ، "
    "پوکه، پیپر، فیلتر، چوب سیگار و پیپ."
)

# Home page (SiteSettings fields).
HOME = {
    "home_meta_title": "پیچ‌یار | خرید توتون سیگار پیچ و لوازم سیگار دست‌پیچ",
    "home_meta_description": (
        "خرید اینترنتی توتون سیگار پیچ، دستگاه سیگار پیچ، پوکه، پیپر، فیلتر، چوب سیگار و پیپ از پیچ‌یار. "
        "فروش فقط به افراد بالای ۱۸ سال."
    ),
    "home_heading": "فروشگاه توتون و لوازم سیگار پیچ",
    "home_intro": """
<h2>پیچ‌یار؛ توتون و لوازم سیگار پیچ در یک‌جا</h2>
<p>پیچ‌یار فروشگاه تخصصی <strong>توتون سیگار پیچ</strong> و لوازم سیگار دست‌پیچ است. هر چیزی که برای پیچیدن سیگار لازم دارید، از توتون تا دستگاه و پوکه، در همین فروشگاه پیدا می‌شود و می‌توانید همه را در یک سفارش بگیرید.</p>
<h3>توتون</h3>
<p>در بخش <a href="/c/tobacco/">توتون</a> بیش از سی مدل توتون سیگار پیچ می‌بینید: توتون‌های ترکیه‌ای مثل ادیامان، بتلیس و شمزین، توتون روشن ویرجینیا، و مدل‌های آمریکایی، کوبایی، کلمبیایی و یونانی. در صفحهٔ هر توتون توضیح داده‌ایم که از چه نوعی است و با کدام مدل‌ها قابل مقایسه است.</p>
<h3>لوازم سیگار پیچ</h3>
<ul>
<li><a href="/c/machines/">دستگاه سیگار پیچ</a>: دستگاه رومیزی، خشابی، زیگ‌زاگ و رولی جیبی</li>
<li><a href="/c/tubes/">پوکهٔ سیگار</a>: پوکه‌های فیلتردار ۲۰۰ نخی برای پر کردن با دستگاه</li>
<li><a href="/c/papers/">پیپر</a> و <a href="/c/filters/">فیلتر</a>: برای پیچیدن دستی یا با دستگاه رولی</li>
<li><a href="/c/holders/">چوب سیگار</a>، <a href="/c/pipes/">پیپ</a> و <a href="/c/cigars/">سیگار برگ</a></li>
<li><a href="/c/other/">جعبهٔ توتون، جعبهٔ سیگار و جاسیگاری</a></li>
</ul>
<h3>از کجا شروع کنم؟</h3>
<p>دو راه اصلی برای سیگار دست‌پیچ هست. در روش اول، توتون را با <a href="/c/machines/">دستگاه</a> داخل <a href="/c/tubes/">پوکهٔ فیلتردار</a> پر می‌کنید؛ این روش سریع است و تمرین نمی‌خواهد. در روش دوم، توتون را با <a href="/c/papers/">پیپر</a> و <a href="/c/filters/">فیلتر</a> می‌پیچید؛ لوازمش جمع‌وجورتر است اما کمی تمرین لازم دارد. در <a href="/blog/">مقاله‌های پیچ‌یار</a> هر دو روش را قدم‌به‌قدم توضیح داده‌ایم.</p>
<p>فروش محصولات پیچ‌یار فقط به افراد بالای ۱۸ سال انجام می‌شود.</p>
""",
}

# slug → {meta_title, meta_description, intro (HTML), guide (HTML, below the products), faqs: [(question, answer)]}
CATEGORIES = {"tobacco": _tobacco.TOBACCO_CATEGORY, **_accessories.CATEGORIES}

# product name → description (HTML)
TOBACCO = _tobacco.TOBACCO
ACCESSORIES = _accessories.ACCESSORIES

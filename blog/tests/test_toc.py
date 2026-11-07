from django.test import SimpleTestCase

from blog.toc import with_heading_ids


class TocTests(SimpleTestCase):
    def test_ids_added_and_listed(self):
        html, toc = with_heading_ids("<h2>انتخاب توتون</h2><p>x</p><h3>نگهداری درست</h3><h4>ریز</h4>")
        self.assertIn('<h2 id="انتخاب-توتون">انتخاب توتون</h2>', html)
        self.assertIn('<h3 id="نگهداری-درست">', html)
        self.assertNotIn("<h4 id", html)  # only h2/h3 go into the table of contents
        self.assertEqual(
            toc,
            [
                {"level": 2, "id": "انتخاب-توتون", "title": "انتخاب توتون"},
                {"level": 3, "id": "نگهداری-درست", "title": "نگهداری درست"},
            ],
        )

    def test_duplicates_and_existing_ids_are_unique(self):
        html, toc = with_heading_ids('<h2>بخش</h2><h2 id="بخش-2">دستی</h2><h2>بخش</h2><h2>faq</h2><h2>!!!</h2>')
        ids = [item["id"] for item in toc]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertEqual(ids[:3], ["بخش", "بخش-2", "بخش-3"])  # hand-written id kept, generated one skips it
        self.assertNotIn("faq", ids)  # reserved by the page itself
        self.assertEqual(ids[4], "بخش-5")  # no letters: numbered fallback
        self.assertEqual(html.count(" id="), 5)

    def test_zwnj_and_inline_markup(self):
        html, toc = with_heading_ids("<h2>روش <strong>نگه‌داری</strong></h2>")
        self.assertEqual(toc[0]["title"], "روش نگه‌داری")
        self.assertEqual(toc[0]["id"], "روش-نگه-داری")
        self.assertIn("<strong>نگه‌داری</strong></h2>", html)

    def test_stable(self):
        body = "<h2>الف</h2><h3>ب</h3>"
        first, _ = with_heading_ids(body)
        second, _ = with_heading_ids(first)
        self.assertEqual(first, second)

    def test_empty(self):
        self.assertEqual(with_heading_ids(""), ("", []))

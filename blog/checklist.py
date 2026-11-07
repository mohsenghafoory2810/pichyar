"""Content checklist for an article: what is still missing before it is "complete".

Only warns (admin panel + message after save); it never blocks saving or publishing.
"""


def missing_items(article, faq_count=None):
    """Persian messages for each missing item; [] when everything is in place.
    faq_count: pass it when already known (annotated changelist) to avoid a query."""
    missing = []
    if not (article.short_answer or "").strip():
        missing.append("«پاسخ کوتاه» نوشته نشده است (کادر برجستهٔ بالای مقاله).")
    if not (article.meta_description or "").strip():
        missing.append("«توضیح متا (description)» خالی است؛ در بخش سئو بنویسید.")
    if not article.cover:
        missing.append("«تصویر شاخص» انتخاب نشده است.")
    elif not (article.cover_alt or "").strip():
        missing.append("«متن جایگزین تصویر (alt)» برای تصویر شاخص خالی است.")
    if faq_count is None:
        faq_count = article.faqs.count() if article.pk else 0
    if not faq_count:
        missing.append("هیچ «پرسش متداول»ی اضافه نشده است.")
    return missing

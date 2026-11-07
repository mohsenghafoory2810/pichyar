from datetime import timedelta

from django.utils import timezone

from blog.models import Article


def make_article(title="مقالهٔ آزمایشی", status=Article.Status.PUBLISHED, **kwargs):
    if status == Article.Status.PUBLISHED:
        kwargs.setdefault("published_at", timezone.now() - timedelta(hours=1))
    return Article.objects.create(title=title, status=status, **kwargs)

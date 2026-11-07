"""Blog helpers used outside the blog pages (home page section)."""

from .models import Article


def latest_articles(limit=3):
    """The newest published articles, for templates/blog/_latest_articles.html."""
    return list(Article.objects.published().select_related("category")[:limit])

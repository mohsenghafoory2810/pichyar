"""Table of contents for an article body: stable ids on <h2>/<h3> and the list linking to them.

Runs at render time on the already-sanitized body (core.html.sanitize_html keeps `id` on
h2/h3/h4), so ids follow the current heading text and nothing is stored:

    html, toc = with_heading_ids(article.body)
    toc == [{"level": 2, "id": "انتخاب-توتون", "title": "انتخاب توتون"}, ...]

Headings that already have an id (written by hand in the editor) keep it.
"""

import html as html_lib
import re

from django.utils.html import escape

from catalog.text import make_slug
from seo.meta import plain_text

_HEADING = re.compile(r"<h([23])(\s[^>]*)?>(.*?)</h\1\s*>", re.IGNORECASE | re.DOTALL)
_ID_ATTR = re.compile(r"""\sid\s*=\s*(?:"([^"]*)"|'([^']*)')""", re.IGNORECASE)

# ids the article page itself uses; a heading never takes one of them.
RESERVED_IDS = {"main", "page", "article-title", "short-answer", "toc", "toc-title", "faq", "faq-title",
                "related-products", "related-products-title", "related-articles", "related-articles-title"}


def _existing_id(attrs):
    match = _ID_ATTR.search(attrs or "")
    if not match:
        return ""
    return html_lib.unescape(match.group(1) if match.group(1) is not None else match.group(2)).strip()


def with_heading_ids(body):
    """(body HTML with an id on every h2/h3, [{"level", "id", "title"}]) — the body must be sanitized."""
    if not body:
        return "", []
    used = set(RESERVED_IDS)
    # Hand-written ids are claimed first so a generated one never duplicates them.
    for match in _HEADING.finditer(body):
        existing = _existing_id(match.group(2))
        if existing:
            used.add(existing)

    toc = []
    counter = 0

    def replace(match):
        nonlocal counter
        counter += 1
        level, attrs, inner = int(match.group(1)), match.group(2) or "", match.group(3)
        title = plain_text(html_lib.unescape(inner))
        heading_id = _existing_id(attrs)
        if not heading_id:
            base = make_slug(title)[:80].strip("-") or f"بخش-{counter}"
            heading_id, n = base, 2
            while heading_id in used:
                heading_id, n = f"{base}-{n}", n + 1
            used.add(heading_id)
            attrs = f'{attrs} id="{escape(heading_id)}"'
        if title:
            toc.append({"level": level, "id": heading_id, "title": title})
        return f"<h{level}{attrs}>{inner}</h{level}>"

    return _HEADING.sub(replace, body), toc

"""Sanitizing rich text written in the admin (TinyMCE): pages, category intros, articles."""

import re

import nh3
from django.utils.html import linebreaks

ALLOWED_TAGS = {
    "p", "br", "hr", "h2", "h3", "h4", "strong", "b", "em", "i", "u", "s", "blockquote",
    "ul", "ol", "li", "a", "img", "figure", "figcaption", "table", "thead", "tbody", "tr", "th", "td",
    "caption", "span", "code", "pre",
}
ALLOWED_ATTRIBUTES = {
    "a": {"href", "title"},
    "img": {"src", "alt", "width", "height", "loading"},
    "h2": {"id"},
    "h3": {"id"},
    "h4": {"id"},
    "th": {"colspan", "rowspan", "scope"},
    "td": {"colspan", "rowspan"},
}


def sanitize_html(html):
    """Only formatting tags survive; scripts, styles, event handlers and javascript: URLs are removed.
    Links get rel="noopener noreferrer"."""
    return nh3.clean(
        html or "",
        tags=ALLOWED_TAGS,
        attributes=ALLOWED_ATTRIBUTES,
        url_schemes={"http", "https", "mailto", "tel"},
        link_rel="noopener noreferrer",
    )


_ANY_TAG = re.compile(r"</?[a-zA-Z][^>]*>")
_BLOCK_TAG = re.compile(r"<(p|br|h[2-4]|ul|ol|li|table|blockquote|figure|hr)\b", re.IGNORECASE)


def rich_text(value):
    """Sanitized HTML from a field that may still hold plain text (older rows, imports, seed
    commands): without block tags, line breaks become <p> / <br>; text with no tag at all is
    escaped first."""
    value = (value or "").strip()
    if value and not _BLOCK_TAG.search(value):
        value = linebreaks(value, autoescape=not _ANY_TAG.search(value))
    return sanitize_html(value)

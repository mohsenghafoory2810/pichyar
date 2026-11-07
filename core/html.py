"""Sanitizing rich text written in the admin (TinyMCE): pages, category intros, articles."""

import nh3

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

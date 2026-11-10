"""Render every storefront and admin page and report English text shown to people.

Usage (from the project root):  .venv/Scripts/python.exe .claude/skills/persian-ui-check/scan_english.py
Exit code: 0 = nothing found, 1 = English text or a broken page was found (report on stdout).

Reads the dev database (config.settings.dev) but does not change it: sessions are signed cookies and
last_login is not updated. Pages are rendered with the Django test client, no running server needed.
"""

import os
import re
import sys
from collections import defaultdict
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.dev")

# --- what is NOT a finding (edit here) --------------------------------------------------------------

# Latin words that are fine in Persian UI text: technical terms, brands, formats, file names.
ALLOWED_WORDS = {
    "alt", "api", "bing", "canonical", "ccbot", "claudebot", "command", "content", "control", "cron",
    "description", "excel", "extended", "google", "gptbot", "html", "htmx", "http", "https", "ipv4", "ipv6",
    "jpg", "jpeg", "json", "llms", "mac", "microsoft", "authenticator", "msvalidate", "noindex",
    "organization", "perplexitybot", "pichyar", "png", "robots", "search", "console", "seo", "sha256",
    "sitemap", "sku", "slug", "sms", "svg", "title", "totp", "txt", "url", "utc", "webmaster", "webp",
    "xlsx", "xml", "agent", "user", "accept", "get", "post", "pickle", "admin", "kavenegar", "zarinpal",
}
# Exact strings (after the [attr] prefix) that are fine: icon alt texts Django hard-codes.
ALLOWED_EXACT = {"[alt] True", "[alt] False", "[alt] None", "[alt] Search"}
# URL prefixes not worth rendering (third-party endpoints that need extra apps).
SKIP_URL_PREFIXES = ("/tinymce/", "/media/", "/static/")

# ---------------------------------------------------------------------------------------------------

import django  # noqa: E402

django.setup()

from django.conf import settings  # noqa: E402

settings.ALLOWED_HOSTS = ["*"]
settings.SESSION_ENGINE = "django.contrib.sessions.backends.signed_cookies"
settings.DEBUG = False

import json  # noqa: E402

from django.contrib import admin as dj_admin  # noqa: E402
from django.contrib.auth import get_user_model, user_logged_in  # noqa: E402
from django.contrib.auth.models import update_last_login  # noqa: E402
from django.test import Client  # noqa: E402
from django.urls import NoReverseMatch, URLPattern, URLResolver, get_resolver, reverse  # noqa: E402

user_logged_in.disconnect(update_last_login, dispatch_uid="update_last_login")
import logging  # noqa: E402

logging.disable(logging.CRITICAL)

SKIP_TAGS = {"script", "style", "svg", "code", "pre", "textarea"}
LABEL_ATTRS = ("title", "placeholder", "aria-label", "alt")
LATIN_WORD = re.compile(r"[A-Za-z][A-Za-z']{2,}")
NOISE = [
    re.compile(r"https?://\S+|www\.\S+|[\w.+-]+@[\w.-]+"),  # URLs, emails
    re.compile(r"\S+\.(?:webp|jpe?g|png|gif|svg|pdf|xlsx|csv)\b", re.I),  # uploaded file names
    re.compile(r"\S*\*{3,}"),  # masked secrets (password hash parts)
    re.compile(r"(?<![\w])/[\w./\-<>?=&%]*"),  # paths like /p/name/ or /robots.txt
    re.compile(r"\{[^{}]*\}|%\(\w+\)[sd]|%[sd]"),  # placeholders {order_number}, %(name)s
    re.compile(r"\b[\w]+(?:[-_.][\w]+)+\b"),  # identifiers: slugs, dotted paths, task names, file.ext
    re.compile(r"\b\w*\d\w*\b"),  # tokens with digits (hashes, abc123)
]


class TextParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.skip = 0
        self.items = []

    def handle_starttag(self, tag, attrs):
        if tag in SKIP_TAGS:
            self.skip += 1
        attrs = dict(attrs)
        for name in LABEL_ATTRS:
            if attrs.get(name):
                self.items.append(f"[{name}] {attrs[name]}")
        if tag == "input" and attrs.get("type") in ("submit", "button") and attrs.get("value"):
            self.items.append(f"[button] {attrs['value']}")

    def handle_endtag(self, tag):
        if tag in SKIP_TAGS and self.skip:
            self.skip -= 1

    def handle_data(self, data):
        if not self.skip and data.strip():
            self.items.append(data.strip())


def english_words(text):
    """Latin words left after removing allowed terms and data-like tokens; [] = Persian enough."""
    if text in ALLOWED_EXACT or "Traceback" in text:
        return []
    body = re.sub(r"^\[[\w-]+\] ", "", text)
    if re.fullmatch(r"[a-z][\w-]*", body):  # a lone lowercase token is data (slug, username)
        return []
    for pattern in NOISE:
        body = pattern.sub(" ", body)
    return [w for w in LATIN_WORD.findall(body) if w.lower().strip("'") not in ALLOWED_WORDS]


findings = defaultdict(set)  # text -> urls
problems = []  # (url, message)
visited = set()


def scan(client, url, who):
    if url in visited or url.startswith(SKIP_URL_PREFIXES):
        return
    visited.add(url)
    try:
        response = client.get(url)
    except Exception as exc:  # a crash while rendering is a finding too
        problems.append((url, f"{who}: {type(exc).__name__}: {exc}"[:300]))
        return
    if response.status_code >= 500:
        problems.append((url, f"{who}: HTTP {response.status_code}"))
        return
    if response.status_code != 200 or "html" not in response.get("Content-Type", ""):
        return
    parser = TextParser()
    parser.feed(response.content.decode("utf-8", "ignore"))
    for text in parser.items:
        if english_words(text):
            findings[text[:200]].add(url)


def public_urls():
    def walk(patterns, prefix=""):
        for p in patterns:
            if isinstance(p, URLResolver):
                if getattr(p, "app_name", None) == "admin" or getattr(p, "namespace", None) == "admin":
                    continue
                yield from walk(p.url_patterns, prefix + str(p.pattern))
            elif isinstance(p, URLPattern) and not p.pattern.converters and "(?P" not in str(p.pattern):
                yield "/" + (prefix + str(p.pattern)).lstrip("^").rstrip("$")

    return sorted(set(walk(get_resolver().url_patterns)))


def object_urls():
    urls = []
    from catalog.models import Category, Product

    for model in (Category, Product):
        for obj in model.objects.all()[:3]:
            urls.append(obj.get_absolute_url())
    try:
        from blog.models import Article

        urls += [a.get_absolute_url() for a in Article.objects.all()[:2]]
    except Exception:
        pass
    return urls


def admin_site():
    import core.admin_site as module

    for value in vars(module).values():
        if isinstance(value, dj_admin.AdminSite):
            return value
    return dj_admin.site


def main():
    User = get_user_model()
    anon = Client()
    anon.cookies["age_verified"] = "1"
    pages = public_urls() + object_urls() + ["/this-page-does-not-exist/"]
    for url in pages:
        scan(anon, url, "guest")

    customer = User.objects.filter(is_staff=False, is_active=True).first()
    if customer:
        visited.difference_update(pages)
        client = Client()
        client.cookies["age_verified"] = "1"
        client.force_login(customer, backend="django.contrib.auth.backends.ModelBackend")
        for url in pages:
            scan(client, url, "customer")
        from orders.models import Order

        for order in Order.objects.filter(user=customer)[:3] if hasattr(Order, "user") else []:
            if hasattr(order, "get_absolute_url"):
                scan(client, order.get_absolute_url(), "customer")

    superuser = User.objects.filter(is_superuser=True, is_active=True).first()
    if not superuser:
        problems.append(("-", "no active superuser in the dev database: admin pages were not checked"))
    else:
        site = admin_site()
        client = Client()
        client.force_login(superuser, backend="django.contrib.auth.backends.ModelBackend")
        scan(client, reverse(f"{site.name}:index"), "admin")
        for name in ("two_factor", "password_change"):
            try:
                scan(client, reverse(f"{site.name}:{name}"), "admin")
            except NoReverseMatch:
                pass
        for model in site._registry:
            base = f"{site.name}:{model._meta.app_label}_{model._meta.model_name}"
            for suffix in ("changelist", "add", "import", "export"):
                try:
                    scan(client, reverse(f"{base}_{suffix}"), "admin")
                except NoReverseMatch:
                    pass
            for obj in model._default_manager.all()[:2]:
                for suffix in ("change", "history"):
                    try:
                        scan(client, reverse(f"{base}_{suffix}", args=[obj.pk]), "admin")
                    except NoReverseMatch:
                        pass
        js = client.get(reverse(f"{site.name}:jsi18n")).content.decode("utf-8")
        for persian in ("انتخاب همهٔ %s", "یکشنبه"):
            if json.dumps(persian) not in js:
                problems.append(("/jsi18n/", f"admin JS catalog lacks {persian!r} (locale/fa djangojs.mo?)"))

    print(f"Checked {len(visited)} pages.")
    if not findings and not problems:
        print("OK: no English text found.")
        return 0
    if findings:
        print(f"\nEnglish text ({len(findings)}):")
        for text, urls in sorted(findings.items()):
            sample = ", ".join(sorted(urls)[:3]) + (f" (+{len(urls) - 3})" if len(urls) > 3 else "")
            print(f"  {text!r}  <-  {sample}")
    if problems:
        print(f"\nBroken pages / setup problems ({len(problems)}):")
        for url, message in problems:
            print(f"  {url}: {message}")
    return 1


if __name__ == "__main__":
    sys.exit(main())

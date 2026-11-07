"""Content checks for customer reviews: no links and no phone numbers.

Digits are compared after converting Persian/Arabic digits to Latin, and invisible
characters (ZWNJ, direction marks) are removed first so they can't split a number or a
domain. Prices written with thousands separators (۱٬۲۵۰٬۰۰۰ or 1,250,000) are not
phone numbers and pass.
"""

import re

from core.persian import latin_digits

_INVISIBLE = re.compile("[​-‏‪-‮⁦-⁩﻿­]")
_TLDS = r"(?:com|ir|net|org|info|biz|io|me|co|app|shop|site|online|store|xyz|link|ly|to|ru|de|uk)"

URL_PATTERNS = [
    re.compile(r"https?\s*:\s*/\s*/", re.I),
    re.compile(r"\bwww\s*\.", re.I),
    re.compile(r"\b(?:t\.me|telegram\.me|wa\.me|instagram\.com|bit\.ly)\b", re.I),
    # name.tld: example.com, shop.ir, my-site.co (a dot followed by a space is a sentence end)
    re.compile(r"[a-z0-9][a-z0-9-]*\.[a-z]{2,10}\b", re.I),
    # disguised: site . ir, foo[.]com, bar (.) net, baz dot com
    re.compile(r"[a-z0-9-]+\s*(?:\.|\[\.\]|\(\.\)|\bdot\b)\s*" + _TLDS + r"\b", re.I),
    re.compile(r"[\w.+-]+@[\w-]+\.[a-z]{2,}", re.I),  # e-mail address
    re.compile(r"(?<![\w@])@[a-z][a-z0-9_.]{3,}", re.I),  # @handle (Telegram / Instagram)
]

_SEP = r"[\s\-._()/]*"
PHONE_PATTERNS = [
    # Iranian mobiles: 09121234567, 0912 123 4567, +98 912 123 4567, 0098-912-..., 912 123 4567
    re.compile(r"(?:(?:\+|00)\s*98" + _SEP + r"|0)?9(?:" + _SEP + r"\d){9}"),
    # Any other run of 7 or more digits, plain or joined by hyphens/spaces (021-1234567, 1234567)
    re.compile(r"\d(?:[\s-]?\d){6,}"),
]

LINK_ERROR = "لطفاً در نظر خود نشانی وب‌سایت، لینک یا آیدی شبکه‌های اجتماعی ننویسید."
PHONE_ERROR = "لطفاً در نظر خود شمارهٔ تلفن ننویسید."


def normalize(text):
    return latin_digits(_INVISIBLE.sub("", text or ""))


def _without_grouped_numbers(text):
    """Drop numbers written with thousands separators (prices), e.g. 1,250,000 / ۱٬۲۵۰٬۰۰۰."""
    return re.sub(r"\d{1,3}(?:[,٬،]\d{3})+", " ", text)


def has_link(text):
    t = normalize(text)
    return any(p.search(t) for p in URL_PATTERNS)


def has_phone(text):
    t = _without_grouped_numbers(normalize(text))
    return any(p.search(t) for p in PHONE_PATTERNS)


def content_error(text):
    """The message to show when the text contains a link or a phone number, else None."""
    if has_link(text):
        return LINK_ERROR
    if has_phone(text):
        return PHONE_ERROR
    return None

"""Picture code (CAPTCHA), drawn here with Pillow: nothing is loaded from another site.

It is asked before an SMS code is sent, and only while the sending looks like an attack
(accounts.otp.captcha_required), so ordinary customers never see it.

    text = captcha.new_challenge(request)   # the picture view: a new code for this session
    captcha.image(text)                     # PNG bytes
    captcha.check(request, posted_value)    # True once; the code is used up either way

Only an HMAC of the code is kept in the session, it works once and for CAPTCHA_TTL seconds.
"""

import io
import secrets
import time

from django.utils.crypto import constant_time_compare, salted_hmac
from PIL import Image, ImageDraw, ImageFont

from .persian import latin_digits

SESSION_KEY = "captcha"
LENGTH = 5
CAPTCHA_TTL = 5 * 60  # seconds
SIZE = (170, 60)
DIGITS = "23456789"  # no 0/1: they look alike once the picture is distorted
REQUIRED_MESSAGE = "برای ادامه، عددهای داخل تصویر را وارد کنید."
WRONG_MESSAGE = "عددهای تصویر درست وارد نشد. تصویر تازه را ببینید و دوباره وارد کنید."

_random = secrets.SystemRandom()


def _digest(text):
    return salted_hmac("core.captcha", text, algorithm="sha256").hexdigest()


def new_challenge(request):
    """Start a new challenge for this session (the previous one stops working); returns its text."""
    text = "".join(_random.choice(DIGITS) for _ in range(LENGTH))
    request.session[SESSION_KEY] = {"hash": _digest(text), "at": int(time.time())}
    return text


def check(request, value):
    """True when `value` is the session's current picture code. Single use: right or wrong,
    the challenge is removed and a new picture is needed for the next try."""
    challenge = request.session.pop(SESSION_KEY, None)
    value = latin_digits(value or "").strip()
    if not isinstance(challenge, dict) or not value:
        return False
    if time.time() - challenge.get("at", 0) > CAPTCHA_TTL:
        return False
    return constant_time_compare(challenge.get("hash", ""), _digest(value))


def _font(size):
    try:
        return ImageFont.load_default(size=size)  # Pillow's built-in scalable font (needs FreeType)
    except (OSError, TypeError):
        return None


def _digit_tile(char, font, color):
    """One digit on its own transparent tile, turned a little."""
    if font is None:  # no FreeType: enlarge the small bitmap font instead
        small = Image.new("RGBA", (10, 14), (0, 0, 0, 0))
        ImageDraw.Draw(small).text((2, 1), char, font=ImageFont.load_default(), fill=color)
        tile = small.resize((30, 42), Image.Resampling.BICUBIC)
    else:
        tile = Image.new("RGBA", (34, 46), (0, 0, 0, 0))
        ImageDraw.Draw(tile).text((17, 23), char, font=font, fill=color, anchor="mm")
    return tile.rotate(_random.uniform(-24, 24), resample=Image.Resampling.BICUBIC, expand=True)


def _dark():
    return tuple(_random.randint(20, 110) for _ in range(3))


def _pale():
    return tuple(_random.randint(140, 200) for _ in range(3))


def image(text):
    """PNG bytes of `text`: turned digits at uneven heights, with lines and dots over them."""
    width, height = SIZE
    picture = Image.new("RGB", SIZE, (247, 244, 238))
    draw = ImageDraw.Draw(picture)
    for _ in range(4):  # lines behind the digits
        draw.line(
            [(_random.randint(0, width), _random.randint(0, height)) for _ in range(2)], fill=_pale(), width=1
        )
    font = _font(_random.randint(34, 38))
    step = (width - 20) // len(text)
    for i, char in enumerate(text):
        tile = _digit_tile(char, font, _dark())
        x = 10 + i * step + _random.randint(-3, 3)
        y = (height - tile.height) // 2 + _random.randint(-6, 6)
        picture.paste(tile, (x, y), tile)
    for _ in range(3):  # lines across the digits
        points = [(_random.randint(0, width), _random.randint(0, height)) for _ in range(3)]
        draw.line(points, fill=_dark(), width=1)
    for _ in range(140):
        draw.point((_random.randint(0, width - 1), _random.randint(0, height - 1)), fill=_dark())
    out = io.BytesIO()
    picture.save(out, "PNG", optimize=True)
    return out.getvalue()

"""Persian formatting helpers: digits, Toman prices and Jalali dates."""

from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

import jdatetime
from django.utils import timezone

_FA_DIGITS = str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹")
_AR_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩", "۰۱۲۳۴۵۶۷۸۹")
_TO_LATIN = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")

THOUSANDS_SEPARATOR = "٬"  # U+066C, Persian thousands separator


def fa_digits(value) -> str:
    if value is None:
        return ""
    return str(value).translate(_FA_DIGITS).translate(_AR_DIGITS)


def latin_digits(value) -> str:
    if value is None:
        return ""
    return str(value).translate(_TO_LATIN)


def fa_number(value) -> str:
    """12345.6 -> '۱۲٬۳۴۶' (rounded to an integer). Invalid input -> ''."""
    if value is None or value == "":
        return ""
    try:
        number = Decimal(latin_digits(value).replace(",", "").replace(THOUSANDS_SEPARATOR, ""))
    except (InvalidOperation, ValueError, TypeError):
        return ""
    number = int(number.quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    return fa_digits(f"{number:,}".replace(",", THOUSANDS_SEPARATOR))


def toman(value) -> str:
    formatted = fa_number(value)
    return f"{formatted} تومان" if formatted else ""


def to_jalali(value):
    """Convert a date/datetime to jdatetime (datetimes in the local timezone)."""
    if isinstance(value, datetime):
        if timezone.is_aware(value):
            value = timezone.localtime(value)
        return jdatetime.datetime.fromgregorian(datetime=value, locale=jdatetime.FA_LOCALE)
    if isinstance(value, date):
        return jdatetime.date.fromgregorian(date=value, locale=jdatetime.FA_LOCALE)
    return None


def jalali_format(value, fmt="%Y/%m/%d") -> str:
    j = to_jalali(value)
    return fa_digits(j.strftime(fmt)) if j else ""

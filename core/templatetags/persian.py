from django import template

from core import persian

register = template.Library()


@register.filter
def fa_digits(value):
    """'Order 123' -> 'Order ۱۲۳'"""
    return persian.fa_digits(value)


@register.filter
def fa_number(value):
    """1250000 -> '۱٬۲۵۰٬۰۰۰'"""
    return persian.fa_number(value)


@register.filter
def toman(value):
    """1250000 -> '۱٬۲۵۰٬۰۰۰ تومان'"""
    return persian.toman(value)


@register.filter
def jdate(value, fmt="%Y/%m/%d"):
    """Jalali date with Persian digits, e.g. {{ obj.created|jdate:"%d %B %Y" }}"""
    return persian.jalali_format(value, fmt)


@register.filter
def jdatetime(value, fmt="%Y/%m/%d - %H:%M"):
    return persian.jalali_format(value, fmt)

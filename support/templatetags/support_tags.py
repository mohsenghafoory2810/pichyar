from django import template

from support.services import tab_info

register = template.Library()


@register.simple_tag
def support_tab(user):
    """{"tickets": n, "unread": n} for the «پیام به پشتیبانی» tab of the account panel (one query)."""
    return tab_info(user)

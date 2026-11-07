"""Sales figures for the admin dashboard and the orders date filter.

Sales = confirmed orders (paid_processing / shipped / delivered) by the time their payment
was confirmed (paid_at); canceled orders drop out. Periods follow the Iranian calendar in
Tehran time: the week starts on Saturday and the month is the Jalali month.
"""

from dataclasses import dataclass
from datetime import datetime, time, timedelta

import jdatetime
from django.db.models import Count, F, Sum
from django.db.models.functions import TruncDate
from django.utils import timezone

from core.persian import jalali_format

from .models import CONFIRMED_STATUSES, Order, OrderStatus

CHART_DAYS = 30


def _start_of(day):
    return timezone.make_aware(datetime.combine(day, time.min))


def period_bounds(name, now=None):
    """(start, end) aware datetimes of 'today' / 'week' / 'month' / 'last_month' / '30d'."""
    now = timezone.localtime(now or timezone.now())
    today = now.date()
    if name == "today":
        start = today
    elif name == "week":
        start = today - timedelta(days=(today.weekday() - 5) % 7)  # Saturday
    elif name in ("month", "last_month"):
        jtoday = jdatetime.date.fromgregorian(date=today)
        month_start = jtoday.replace(day=1)
        if name == "month":
            start = month_start.togregorian()
        else:
            prev = (month_start - timedelta(days=1)).replace(day=1)
            return _start_of(prev.togregorian()), _start_of(month_start.togregorian())
    elif name == "30d":
        start = today - timedelta(days=29)
    else:
        raise ValueError(name)
    return _start_of(start), _start_of(today + timedelta(days=1))


def confirmed_orders():
    return Order.objects.filter(status__in=CONFIRMED_STATUSES, paid_at__isnull=False)


@dataclass
class PeriodSales:
    key: str
    label: str
    count: int
    amount: int


PERIODS = [("today", "امروز"), ("week", "این هفته"), ("month", "این ماه")]


def sales_summary(now=None):
    out = []
    for key, label in PERIODS:
        start, end = period_bounds(key, now)
        row = confirmed_orders().filter(paid_at__gte=start, paid_at__lt=end).aggregate(c=Count("id"), s=Sum("total"))
        out.append(PeriodSales(key, label, row["c"] or 0, row["s"] or 0))
    return out


def daily_sales(days=CHART_DAYS, now=None):
    """[(date, amount, count)] for the last `days` days (oldest first), zeros included."""
    now = timezone.localtime(now or timezone.now())
    first = now.date() - timedelta(days=days - 1)
    rows = (
        confirmed_orders()
        .filter(paid_at__gte=_start_of(first))
        .annotate(day=TruncDate("paid_at", tzinfo=timezone.get_current_timezone()))
        .values("day")
        .annotate(amount=Sum("total"), count=Count("id"))
    )
    by_day = {r["day"]: (r["amount"] or 0, r["count"]) for r in rows}
    return [(d, *by_day.get(d, (0, 0))) for d in (first + timedelta(days=i) for i in range(days))]


def sales_chart(days=CHART_DAYS, now=None, width=720, height=200):
    """Geometry for the inline SVG bar chart of the dashboard (no JavaScript, no CDN)."""
    series = daily_sales(days, now)
    top = max((amount for _, amount, _ in series), default=0)
    pad_top, pad_bottom = 8, 22
    plot_h = height - pad_top - pad_bottom
    slot = width / len(series)
    bar_w = max(2.0, slot - 2)  # 2px gap between bars
    bars = []
    for i, (day, amount, count) in enumerate(series):
        h = (amount / top * plot_h) if top else 0
        if amount and h < 2:
            h = 2
        bars.append(
            {
                "x": round(width - (i + 1) * slot + 1, 2),  # right-to-left: today is on the left edge
                "slot_x": round(width - (i + 1) * slot, 2),
                "y": round(pad_top + plot_h - h, 2),
                "w": round(bar_w, 2),
                "h": round(h, 2),
                "slot_w": round(slot, 2),
                "amount": amount,
                "count": count,
                "label": jalali_format(day, "%m/%d"),
                "date": jalali_format(day, "%A %d %B"),
                "show_label": i % 5 == 0 or i == len(series) - 1,
            }
        )
    return {
        "width": width,
        "height": height,
        "baseline": pad_top + plot_h,
        "label_y": height - 6,
        "bars": bars,
        "max": top,
        "total": sum(amount for _, amount, _ in series),
        "days": days,
    }


def low_stock_products(limit=10):
    from catalog.models import Product

    qs = Product.objects.filter(is_active=True, stock__lte=F("low_stock_threshold")).select_related("category")
    return qs.order_by("stock", "name")[:limit], qs.count()


def dashboard(user=None, now=None):
    S = OrderStatus
    to_ship = Order.objects.filter(status=S.PAID_PROCESSING)
    awaiting = Order.objects.filter(status=S.AWAITING_APPROVAL)
    low, low_count = low_stock_products()
    return {
        "sales": sales_summary(now),
        "to_ship": to_ship.order_by("paid_at", "id")[:8],
        "to_ship_count": to_ship.count(),
        "awaiting": awaiting.order_by("created_at", "id")[:8],
        "awaiting_count": awaiting.count(),
        "low_stock": low,
        "low_stock_count": low_count,
        "chart": sales_chart(now=now),
    }

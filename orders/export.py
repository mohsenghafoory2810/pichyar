"""Orders -> Excel (xlsx), for the orders admin. One row per order; items in one cell."""

from io import BytesIO

from django.http import HttpResponse
from django.utils import timezone
from openpyxl import Workbook
from openpyxl.styles import Alignment, Font
from openpyxl.utils import get_column_letter

from core.persian import jalali_format

COLUMNS = [
    ("شمارهٔ سفارش", 12),
    ("تاریخ ثبت", 18),
    ("زمان تأیید پرداخت", 18),
    ("وضعیت", 24),
    ("روش پرداخت", 16),
    ("موبایل سفارش‌دهنده", 14),
    ("نام گیرنده", 20),
    ("موبایل گیرنده", 14),
    ("استان", 14),
    ("شهر", 14),
    ("نشانی", 40),
    ("کد پستی", 12),
    ("اقلام", 40),
    ("جمع کالاها (تومان)", 16),
    ("کد تخفیف", 12),
    ("تخفیف (تومان)", 14),
    ("هزینهٔ ارسال (تومان)", 16),
    ("مبلغ کل (تومان)", 16),
    ("کد رهگیری پست", 26),
    ("توضیحات مشتری", 30),
]


def _items_text(order):
    lines = []
    for item in order.items.all():
        line = f"{item.name} × {item.quantity}"
        if item.is_gift:
            line += " (هدیه)"
        lines.append(line)
    return "\n".join(lines)


def order_row(order):
    fmt = "%Y/%m/%d %H:%M"
    return [
        order.number,
        jalali_format(order.created_at, fmt),
        jalali_format(order.paid_at, fmt) if order.paid_at else "",
        order.get_status_display(),
        order.get_payment_method_display(),
        order.mobile,
        order.recipient_name,
        order.recipient_mobile,
        order.province,
        order.city,
        order.address,
        order.postal_code,
        _items_text(order),
        order.items_subtotal,
        order.discount_code_text,
        order.discount_amount,
        order.shipping_fee,
        order.total,
        order.post_tracking_code,
        order.note,
    ]


def orders_workbook(orders):
    wb = Workbook()
    ws = wb.active
    ws.title = "سفارش‌ها"
    ws.sheet_view.rightToLeft = True
    ws.append([title for title, _ in COLUMNS])
    for cell in ws[1]:
        cell.font = Font(bold=True)
    wrap = Alignment(wrap_text=True, vertical="top")
    for order in orders:
        ws.append(order_row(order))
        for cell in ws[ws.max_row]:
            cell.alignment = wrap
    for i, (_, width) in enumerate(COLUMNS, 1):
        ws.column_dimensions[get_column_letter(i)].width = width
        if COLUMNS[i - 1][0].endswith("(تومان)"):
            for (cell,) in ws.iter_rows(min_row=2, min_col=i, max_col=i):
                cell.number_format = "#,##0"
    ws.freeze_panes = "A2"
    return wb


def xlsx_response(orders):
    out = BytesIO()
    orders_workbook(orders.prefetch_related("items")).save(out)
    stamp = timezone.localtime().strftime("%Y%m%d-%H%M")
    response = HttpResponse(
        out.getvalue(), content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
    response["Content-Disposition"] = f'attachment; filename="orders-{stamp}.xlsx"'
    return response

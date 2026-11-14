"""Customer forms. Unlike reviews, links and phone numbers are fine here (it is a private
conversation with the shop): the text is only trimmed and length-checked."""

from django import forms

from core.persian import fa_digits, jalali_format

from .models import SUBJECT_MAX_LENGTH, TEXT_MAX_LENGTH

HONEYPOT_FIELD = "website"


class OrderChoiceField(forms.ModelChoiceField):
    def label_from_instance(self, order):
        return f"سفارش {fa_digits(order.number)} — {jalali_format(order.created_at)}"


class HoneypotMixin:
    @property
    def is_bot(self):
        return bool(self.data.get(HONEYPOT_FIELD, "").strip())


def _honeypot():
    # Hidden from people (and screen readers); bots that fill every field give themselves away.
    return forms.CharField(
        label="وب‌سایت",
        required=False,
        widget=forms.TextInput(attrs={"tabindex": "-1", "autocomplete": "off", "aria-hidden": "true"}),
    )


def _text_field(label):
    return forms.CharField(
        label=label,
        max_length=TEXT_MAX_LENGTH,
        widget=forms.Textarea(attrs={"class": "input", "rows": 5, "maxlength": TEXT_MAX_LENGTH}),
        error_messages={"required": "متن پیام را بنویسید.", "max_length": "متن پیام حداکثر ۳۰۰۰ نویسه باشد."},
    )


class TicketForm(HoneypotMixin, forms.Form):
    subject = forms.CharField(
        label="موضوع",
        max_length=SUBJECT_MAX_LENGTH,
        widget=forms.TextInput(attrs={"class": "input", "maxlength": SUBJECT_MAX_LENGTH}),
        error_messages={"required": "موضوع پیام را بنویسید.", "max_length": "موضوع حداکثر ۱۲۰ نویسه باشد."},
    )
    order = OrderChoiceField(
        label="سفارش مرتبط (اختیاری)",
        queryset=None,
        required=False,
        empty_label="بدون سفارش",
        widget=forms.Select(attrs={"class": "input"}),
        error_messages={"invalid_choice": "سفارش انتخاب‌شده معتبر نیست."},
    )
    text = _text_field("متن پیام")
    website = _honeypot()

    def __init__(self, *args, user, **kwargs):
        super().__init__(*args, **kwargs)
        from orders.models import Order

        self.fields["order"].queryset = Order.objects.for_user(user).order_by("-created_at")

    def clean_subject(self):
        return " ".join(self.cleaned_data.get("subject", "").split())

    def clean_text(self):
        return self.cleaned_data.get("text", "").strip()


class MessageForm(HoneypotMixin, forms.Form):
    text = _text_field("پاسخ شما")
    website = _honeypot()

    def clean_text(self):
        return self.cleaned_data.get("text", "").strip()

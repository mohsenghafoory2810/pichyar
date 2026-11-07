from django import forms

from .models import REVIEW_MIN_LENGTH, Review
from .spam import content_error

RATING_CHOICES = [(n, n) for n in range(5, 0, -1)]
HONEYPOT_FIELD = "website"


class ReviewForm(forms.ModelForm):
    rating = forms.TypedChoiceField(
        label="امتیاز شما",
        choices=RATING_CHOICES,
        coerce=int,
        widget=forms.RadioSelect,
        error_messages={"required": "امتیاز (۱ تا ۵ ستاره) را انتخاب کنید.", "invalid_choice": "امتیاز باید ۱ تا ۵ باشد."},
    )
    # Honeypot: hidden from people (and screen readers); bots that fill every field give themselves away.
    website = forms.CharField(
        label="وب‌سایت",
        required=False,
        widget=forms.TextInput(attrs={"tabindex": "-1", "autocomplete": "off", "aria-hidden": "true"}),
    )

    class Meta:
        model = Review
        fields = ("rating", "title", "text")
        labels = {"title": "عنوان (اختیاری)", "text": "متن نظر"}
        widgets = {
            "title": forms.TextInput(attrs={"class": "input", "maxlength": 120}),
            "text": forms.Textarea(attrs={"class": "input", "rows": 4, "maxlength": 3000}),
        }
        error_messages = {
            "text": {"required": "متن نظر را بنویسید.", "max_length": "متن نظر حداکثر ۳۰۰۰ نویسه باشد."},
            "title": {"max_length": "عنوان حداکثر ۱۲۰ نویسه باشد."},
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["text"].help_text = "دست‌کم ۱۰ نویسه. لینک و شمارهٔ تلفن پذیرفته نمی‌شود."

    @property
    def is_bot(self):
        return bool(self.data.get(HONEYPOT_FIELD, "").strip())

    def clean_title(self):
        title = " ".join(self.cleaned_data.get("title", "").split())
        error = content_error(title)
        if error:
            raise forms.ValidationError(error)
        return title

    def clean_text(self):
        text = self.cleaned_data.get("text", "").strip()
        if len(text) < REVIEW_MIN_LENGTH:
            raise forms.ValidationError("متن نظر دست‌کم ۱۰ نویسه باشد.")
        error = content_error(text)
        if error:
            raise forms.ValidationError(error)
        return text

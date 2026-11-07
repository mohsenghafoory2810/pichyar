from django.utils.text import slugify

_ARABIC_TO_PERSIAN = str.maketrans({"ي": "ی", "ى": "ی", "ك": "ک", "ة": "ه"})


def normalize_fa(text: str) -> str:
    """Unify Arabic/Persian letter variants so searches match whichever keyboard was used."""
    return (text or "").translate(_ARABIC_TO_PERSIAN).strip()


def make_slug(text: str) -> str:
    # slugify() drops the zero-width non-joiner; turn it into a dash so «زیگ‌زاگ» stays readable.
    return slugify(normalize_fa(text).replace("‌", "-"), allow_unicode=True)


def unique_slug(model, text, exclude_pk=None, max_length=150):
    base = make_slug(text)[:max_length] or "item"
    slug, n = base, 2
    qs = model.objects.exclude(pk=exclude_pk) if exclude_pk else model.objects.all()
    while qs.filter(slug=slug).exists():
        slug, n = f"{base}-{n}", n + 1
    return slug

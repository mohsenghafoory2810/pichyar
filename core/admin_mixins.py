from .persian import latin_digits


class PersianDigitsSearchMixin:
    """Search with Persian or Latin digits alike (mobiles and order numbers are stored Latin)."""

    def get_search_results(self, request, queryset, search_term):
        return super().get_search_results(request, queryset, latin_digits(search_term or ""))

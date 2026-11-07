"""The shop's AdminSite (installed through core.apps.ShopAdminConfig).

- index: the dashboard (orders.reports) above the model list.
- get_app_list: models regrouped into the sidebar sections of ADMIN_GROUPS, in that order.
- login: mobile + password, plus the 6-digit code for accounts that turned on two-step
  login (django-otp TOTP). Failed passwords and codes are counted by django-axes.
- has_permission: an admin session must come from that login. A staff member signed in
  on the storefront with an SMS code (accounts.backends.SMSCodeBackend) is a customer
  there and gets the admin login page; with 2FA on, the session must be OTP-verified.
"""

from django.contrib import admin
from django.contrib.auth import BACKEND_SESSION_KEY
from django.urls import NoReverseMatch, path, reverse

SMS_BACKEND = "accounts.backends.SMSCodeBackend"

# (title, [(app_label, model_name, label or None), ...]) — label overrides verbose_name_plural.
ADMIN_GROUPS = [
    (
        "فروش",
        [
            ("orders", "order", None),
            ("accounts", "customer", None),
            ("orders", "discountcode", None),
            ("orders", "giftpoolitem", None),
        ],
    ),
    ("محصولات", [("catalog", "product", None), ("catalog", "category", None)]),
    ("نظرهای مشتریان", [("reviews", "review", None)]),
    (
        "مقاله‌ها",
        [("blog", "article", None), ("blog", "articlecategory", None), ("blog", "tag", None)],
    ),
    (
        "محتوای سایت",
        [("core", "banner", None), ("core", "staticpage", None), ("seo", "redirect", None)],
    ),
    ("پیامک", [("notifications", "smslog", None), ("notifications", "smstemplate", None)]),
    ("تنظیمات", [("core", "sitesettings", None)]),
    (
        "کاربران و امنیت",
        [
            ("accounts", "user", "کاربران و مدیران"),
            ("auth", "group", None),
            ("otp_totp", "totpdevice", "ورود دومرحله‌ای مدیران"),
            ("axes", "accessattempt", "قفل‌های ورود به پنل"),
        ],
    ),
    ("سیستم", [("django_q", "failure", "کارهای پس‌زمینهٔ ناموفق")]),
]


class ShopAdminSite(admin.AdminSite):
    site_header = "مدیریت فروشگاه"
    site_title = "مدیریت فروشگاه"
    index_title = "پیشخوان"
    index_template = "admin/dashboard.html"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        from accounts.admin_forms import ShopAdminLoginForm  # no model imports at module level there

        self.login_form = ShopAdminLoginForm

    # --- access -----------------------------------------------------------------

    def has_permission(self, request):
        if not super().has_permission(request):
            return False
        if request.session.get(BACKEND_SESSION_KEY) == SMS_BACKEND:
            return False
        from django_otp import user_has_device

        if user_has_device(request.user) and not request.user.is_verified():
            return False
        return True

    def login(self, request, extra_context=None):
        """AdminSite.login, with a LoginView that also marks the session OTP-verified."""
        from django.contrib.auth import REDIRECT_FIELD_NAME
        from django.http import HttpResponseRedirect

        from accounts.admin_forms import OTPLoginView

        if request.method == "GET" and self.has_permission(request):
            return HttpResponseRedirect(reverse("admin:index", current_app=self.name))
        context = {
            **self.each_context(request),
            "title": "ورود به پنل مدیریت",
            "subtitle": None,
            "app_path": request.get_full_path(),
            "username": request.user.get_username(),
        }
        if REDIRECT_FIELD_NAME not in request.GET and REDIRECT_FIELD_NAME not in request.POST:
            context[REDIRECT_FIELD_NAME] = reverse("admin:index", current_app=self.name)
        context.update(extra_context or {})
        request.current_app = self.name
        return OTPLoginView.as_view(
            extra_context=context, authentication_form=self.login_form, template_name="admin/login.html"
        )(request)

    def get_urls(self):
        from accounts.admin_views import two_factor_view

        custom = [path("two-factor/", self.admin_view(two_factor_view), name="two_factor")]
        return custom + super().get_urls()

    # --- dashboard and sidebar --------------------------------------------------

    def index(self, request, extra_context=None):
        from orders.reports import dashboard
        from reviews.models import Review

        context = {
            "dashboard": dashboard(request.user),
            "pending_reviews_count": Review.objects.filter(status=Review.Status.PENDING).count(),
            **(extra_context or {}),
        }
        return super().index(request, context)

    def get_app_list(self, request, app_label=None):
        apps = super().get_app_list(request, app_label)
        if app_label is not None:
            return apps
        models = {}
        for app in apps:
            for model in app["models"]:
                models[(app["app_label"], model["object_name"].lower())] = (app, model)
        groups = []
        try:
            index_url = reverse("admin:index", current_app=self.name)
        except NoReverseMatch:
            index_url = "/"
        for number, (title, entries) in enumerate(ADMIN_GROUPS, 1):
            group_models = []
            for app_label_, model_name, label in entries:
                found = models.pop((app_label_, model_name), None)
                if found:
                    model = dict(found[1])
                    if label:
                        model["name"] = label
                    group_models.append(model)
            if group_models:
                groups.append(_group(f"group{number}", title, group_models, index_url))
        leftovers = [model for _, model in models.values()]
        if leftovers:
            groups.append(_group("other", "سایر", leftovers, index_url))
        return groups


def _group(key, title, models, index_url):
    return {
        "name": title,
        "app_label": key,
        "app_url": f"{index_url}#{key}",
        "has_module_perms": True,
        "models": models,
    }

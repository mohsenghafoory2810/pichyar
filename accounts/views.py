import time
from urllib.parse import urlencode

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import login, logout, update_session_auth_hash
from django.contrib.auth.decorators import login_required
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from core.utils import client_ip, get_site_settings, htmx_redirect, is_htmx, safe_next_url
from orders.models import Order

from .flows import otp_step
from .forms import AddressForm, PasswordLoginForm, ProfileForm, SetPasswordForm
from .models import Address, OTPCode, User
from .password_login import LoginError, check_password_login

LOGIN_PENDING_KEY = "login_mobile"
# Unix time of the session's SMS-code login: a password can be (re)set without the current
# one only shortly after it (settings.PASSWORD_SET_RECENT_SMS_LOGIN_SECONDS).
SMS_LOGIN_AT_KEY = "sms_login_at"
SMS_BACKEND = "accounts.backends.SMSCodeBackend"
PASSWORD_BACKEND = "accounts.backends.StorefrontPasswordBackend"


def _after_login(request, user, next_url):
    if not user.name:  # first sign-in (registration): ask for the name
        next_url = f"{reverse('accounts:profile')}?{urlencode({'next': next_url, 'welcome': 1})}"
    return htmx_redirect(request, next_url)


def login_view(request):
    """Sign-in / registration. The SMS code always works (and is the only way for a new
    number); with SiteSettings.password_login_enabled a «رمز عبور» tab is added."""
    next_url = safe_next_url(request, reverse("accounts:orders"))
    if request.user.is_authenticated:
        return redirect(next_url)

    password_enabled = get_site_settings(request).password_login_enabled
    method = request.POST.get("method") or request.GET.get("method")
    if password_enabled and method == "password":
        return _password_login(request, next_url)

    verified, context = otp_step(request, OTPCode.Purpose.LOGIN, LOGIN_PENDING_KEY)
    if verified:
        user = User.objects.filter(mobile=verified).first() or User.objects.create_user(verified)
        if not user.is_active:
            context["error"] = "این حساب غیرفعال شده است. با پشتیبانی تماس بگیرید."
        else:
            user.mobile_verified_at = timezone.now()
            user.save(update_fields=["mobile_verified_at"])
            login(request, user, backend=SMS_BACKEND)
            request.session[SMS_LOGIN_AT_KEY] = int(time.time())
            return _after_login(request, user, next_url)

    context.update({"otp_url": reverse("accounts:login"), "box_id": "login-box"})
    return _render_login(request, "otp", password_enabled, next_url, context)


def _password_login(request, next_url):
    form = PasswordLoginForm(request.POST if request.method == "POST" else None)
    error = ""
    if form.is_bound and form.is_valid():
        try:
            user = check_password_login(form.cleaned_data["mobile"], form.cleaned_data["password"], client_ip(request))
        except LoginError as e:
            error = e.message
        else:
            login(request, user, backend=PASSWORD_BACKEND)
            return _after_login(request, user, next_url)
    return _render_login(request, "password", True, next_url, {"password_form": form, "error": error})


def _render_login(request, method, password_enabled, next_url, context):
    context.update({"method": method, "password_enabled": password_enabled, "next": next_url})
    if is_htmx(request) and request.method == "POST":
        template = "accounts/_password_box.html" if method == "password" else "accounts/_otp_box.html"
        return render(request, template, context)
    return render(request, "accounts/login.html", context)


def recent_sms_login(request):
    at = request.session.get(SMS_LOGIN_AT_KEY)
    limit = getattr(settings, "PASSWORD_SET_RECENT_SMS_LOGIN_SECONDS", 600)
    return bool(at) and time.time() - at <= limit


@login_required
def password_view(request):
    """Create or change the storefront password (only while the password login is on).
    Without a recent SMS-code login the current password is required, so a session left
    open on a shared device can't take the account over. Staff passwords are the admin
    passwords: they are changed in the admin, never here."""
    if not get_site_settings(request).password_login_enabled:
        raise Http404
    user = request.user
    if user.is_staff:
        messages.info(request, "رمز عبور مدیران فقط از پنل مدیریت تغییر می‌کند.")
        return redirect("accounts:profile")
    has_password = user.has_usable_password()
    require_current = has_password and not recent_sms_login(request)
    form = SetPasswordForm(user, request.POST or None, require_current=require_current)
    if request.method == "POST" and form.is_valid():
        form.save()
        update_session_auth_hash(request, user)  # stay signed in here; other sessions are signed out
        request.session.pop(SMS_LOGIN_AT_KEY, None)
        messages.success(request, "رمز عبور تغییر کرد." if has_password else "رمز عبور ساخته شد. از این پس می‌توانید با موبایل و رمز هم وارد شوید.")
        return redirect("accounts:password")
    return render(
        request,
        "accounts/password.html",
        {"form": form, "has_password": has_password, "require_current": require_current, "tab": "password"},
    )


@require_POST
def logout_view(request):
    logout(request)
    return redirect("core:home")


@login_required
def order_list(request):
    orders = Order.objects.for_user(request.user).prefetch_related("items")
    return render(request, "accounts/orders.html", {"orders": orders, "tab": "orders"})


@login_required
def order_detail(request, number):
    order = get_object_or_404(Order.objects.for_user(request.user).prefetch_related("items", "payments"), number=number)
    return render(request, "accounts/order_detail.html", {"order": order, "tab": "orders"})


@login_required
def address_list(request):
    addresses = request.user.addresses.all()
    can_add = len(addresses) < Address.MAX_PER_USER
    return render(request, "accounts/addresses.html", {"addresses": addresses, "can_add": can_add, "tab": "addresses"})


@login_required
def address_form(request, pk=None):
    address = get_object_or_404(Address, pk=pk, user=request.user) if pk else None
    if address is None and request.user.addresses.count() >= Address.MAX_PER_USER:
        messages.error(request, "حداکثر ۱۰ نشانی می‌توانید ذخیره کنید.")
        return redirect("accounts:addresses")
    initial = {} if address else {"recipient_name": request.user.name, "recipient_mobile": request.user.mobile}
    form = AddressForm(request.POST or None, instance=address, initial=initial)
    if request.method == "POST" and form.is_valid():
        obj = form.save(commit=False)
        obj.user = request.user
        obj.save()
        messages.success(request, "نشانی ذخیره شد.")
        return redirect("accounts:addresses")
    return render(request, "accounts/address_form.html", {"form": form, "address": address, "tab": "addresses"})


@login_required
@require_POST
def address_delete(request, pk):
    get_object_or_404(Address, pk=pk, user=request.user).delete()
    messages.success(request, "نشانی حذف شد.")
    return redirect("accounts:addresses")


@login_required
def profile(request):
    next_url = safe_next_url(request, "")
    form = ProfileForm(request.POST or None, instance=request.user)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "مشخصات ذخیره شد.")
        return redirect(next_url or "accounts:profile")
    return render(
        request,
        "accounts/profile.html",
        {"form": form, "next": next_url, "welcome": bool(request.GET.get("welcome")), "tab": "profile"},
    )

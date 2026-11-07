from urllib.parse import urlencode

from django.contrib import messages
from django.contrib.auth import login, logout
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from core.utils import htmx_redirect, is_htmx, safe_next_url
from orders.models import Order

from .flows import otp_step
from .forms import AddressForm, ProfileForm
from .models import Address, OTPCode, User

LOGIN_PENDING_KEY = "login_mobile"


def login_view(request):
    next_url = safe_next_url(request, reverse("accounts:orders"))
    if request.user.is_authenticated:
        return redirect(next_url)

    verified, context = otp_step(request, OTPCode.Purpose.LOGIN, LOGIN_PENDING_KEY)
    if verified:
        user = User.objects.filter(mobile=verified).first() or User.objects.create_user(verified)
        if not user.is_active:
            context["error"] = "این حساب غیرفعال شده است. با پشتیبانی تماس بگیرید."
        else:
            login(request, user, backend="accounts.backends.SMSCodeBackend")
            if not user.name:  # first sign-in (registration): ask for the name
                next_url = f"{reverse('accounts:profile')}?{urlencode({'next': next_url, 'welcome': 1})}"
            return htmx_redirect(request, next_url)

    context.update({"otp_url": reverse("accounts:login"), "box_id": "login-box", "next": next_url})
    if is_htmx(request):
        return render(request, "accounts/_otp_box.html", context)
    return render(request, "accounts/login.html", context)


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

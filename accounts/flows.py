"""The two-step "mobile → SMS code" form shared by login and guest checkout.

State lives in the session (the number waiting for its code), so the steps work
both with HTMX partial swaps and as plain form posts without JavaScript.
"""

from core.utils import client_ip

from . import otp
from .forms import CodeForm, MobileForm


def otp_step(request, purpose, pending_key):
    """Handle one POST of the OTP box (action = send / resend / verify / change).
    Returns (verified_mobile or None, context for accounts/_otp_box.html)."""
    session = request.session
    pending = session.get(pending_key)
    mobile_form, code_form = MobileForm(), CodeForm()
    notice = error = ""
    verified = None

    if request.method == "POST":
        action = request.POST.get("action")
        if action == "send":
            mobile_form = MobileForm(request.POST)
            if mobile_form.is_valid():
                mobile = mobile_form.cleaned_data["mobile"]
                try:
                    otp.send_code(mobile, purpose, client_ip(request))
                    pending, notice = mobile, "کد تأیید پیامک شد."
                except otp.OTPError as e:
                    if e.code == "cooldown":  # a code was just sent to this number: go on with it
                        pending, notice = mobile, e.message
                    else:
                        mobile_form.add_error("mobile", e.message)
        elif action == "resend" and pending:
            try:
                otp.send_code(pending, purpose, client_ip(request))
                notice = "کد جدید پیامک شد."
            except otp.OTPError as e:
                error = e.message
        elif action == "change":
            pending = None
        elif action == "verify":
            if not pending:
                error = "ابتدا شمارهٔ موبایل را وارد کنید."
            else:
                code_form = CodeForm(request.POST)
                if code_form.is_valid():
                    try:
                        otp.verify_code(pending, purpose, code_form.cleaned_data["code"])
                        verified, pending = pending, None
                    except otp.OTPError as e:
                        code_form.add_error("code", e.message)

    if pending:
        session[pending_key] = pending
    else:
        session.pop(pending_key, None)

    return verified, {
        "step": "code" if pending else "mobile",
        "pending_mobile": pending,
        "mobile_form": mobile_form,
        "code_form": code_form,
        "notice": notice,
        "error": error,
        "resend_wait": otp.seconds_until_resend(pending) if pending else 0,
    }

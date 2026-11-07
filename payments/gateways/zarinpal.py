"""Zarinpal (REST API v4). https://www.zarinpal.com/docs/paymentGateway/

request:  POST /pg/v4/payment/request.json -> data.authority; customer goes to /pg/StartPay/<authority>
callback: GET <callback_url>?Authority=...&Status=OK|NOK
verify:   POST /pg/v4/payment/verify.json -> data.code 100 (verified) or 101 (already verified)

Amounts are sent in Rial (Toman × 10). If a payment is never verified, Zarinpal returns
the money to the customer automatically.
"""

import json
import logging
import urllib.error
import urllib.request

from core.persian import fa_digits

from . import registry
from .base import BaseGateway, GatewayError, GatewayRedirect, VerifyResult

logger = logging.getLogger("payments.zarinpal")

OK_CODES = {100, 101}
ERRORS = {
    -9: "اطلاعات ارسالی به درگاه معتبر نیست.",
    -10: "شناسهٔ پذیرنده (مرچنت) یا آی‌پی سرور معتبر نیست.",
    -11: "درگاه پرداخت غیرفعال است.",
    -12: "تلاش‌های بیش از حد؛ کمی بعد دوباره امتحان کنید.",
    -15: "درگاه پرداخت به حالت تعلیق درآمده است.",
    -50: "مبلغ پرداخت‌شده با مبلغ سفارش یکسان نیست.",
    -51: "پرداخت ناموفق بود.",
    -54: "تراکنش نامعتبر است.",
}


@registry.register
class ZarinpalGateway(BaseGateway):
    key = "zarinpal"
    label = "زرین‌پال"

    @property
    def base_url(self):
        return "https://sandbox.zarinpal.com" if self.sandbox else "https://payment.zarinpal.com"

    def _post(self, path, payload):
        req = urllib.request.Request(
            self.base_url + path,
            data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json", "Accept": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                return json.loads(resp.read().decode() or "{}")
        except urllib.error.HTTPError as e:  # Zarinpal answers errors with 4xx + a JSON body
            try:
                return json.loads(e.read().decode() or "{}")
            except ValueError:
                raise GatewayError("پاسخ نامعتبر از درگاه پرداخت.") from e
        except (urllib.error.URLError, TimeoutError, OSError, ValueError) as e:
            logger.warning("Zarinpal %s failed: %s", path, e)
            raise GatewayError("ارتباط با درگاه پرداخت برقرار نشد. لطفاً دوباره تلاش کنید.") from e

    @staticmethod
    def _parse(body):
        data = body.get("data") if isinstance(body.get("data"), dict) else {}
        errors = body.get("errors") if isinstance(body.get("errors"), dict) else {}
        code = data.get("code", errors.get("code"))
        try:
            code = int(code)
        except (TypeError, ValueError):
            code = None
        return code, data

    @staticmethod
    def _message(code):
        if code is None:
            return "پاسخ نامعتبر از درگاه پرداخت."
        return ERRORS.get(code, f"خطای درگاه پرداخت (کد {fa_digits(code)}).")

    def request(self, order, callback_url):
        body = self._post(
            "/pg/v4/payment/request.json",
            {
                "merchant_id": self.merchant_id,
                "amount": order.total * 10,
                "currency": "IRR",
                "callback_url": callback_url,
                "description": f"سفارش {order.number}",
                "metadata": {"mobile": order.mobile, "order_id": order.number},
            },
        )
        code, data = self._parse(body)
        if code != 100 or not data.get("authority"):
            logger.warning("Zarinpal request refused: %s", body)
            raise GatewayError(self._message(code))
        authority = data["authority"]
        return GatewayRedirect(url=f"{self.base_url}/pg/StartPay/{authority}", authority=authority, raw=body)

    def callback_authority(self, request):
        return request.GET.get("Authority", "")

    def is_success_callback(self, request):
        return request.GET.get("Status") == "OK"

    def verify(self, request, payment):
        if not self.is_success_callback(request):
            return VerifyResult(success=False, canceled=True, message="پرداخت انجام نشد یا از آن انصراف دادید.")
        body = self._post(
            "/pg/v4/payment/verify.json",
            {"merchant_id": self.merchant_id, "amount": payment.amount * 10, "authority": payment.authority},
        )
        code, data = self._parse(body)
        if code in OK_CODES:
            return VerifyResult(
                success=True, ref_id=str(data.get("ref_id", "")), card_pan=data.get("card_pan", "") or "", raw=body
            )
        return VerifyResult(success=False, message=self._message(code), raw=body)

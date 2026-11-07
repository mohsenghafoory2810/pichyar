"""Kavenegar (REST). https://kavenegar.com/rest.html

send: POST https://api.kavenegar.com/v1/<API-KEY>/sms/send.json  receptor, message, sender (optional)
      -> {"return": {"status": 200, "message": "..."}, "entries": [{"messageid": ..., ...}]}
Errors come back as HTTP 4xx/5xx with the same JSON shape (return.status = error code).
Long Persian texts are sent as one concatenated (multi-part) SMS by Kavenegar.
"""

import json
import logging
import urllib.error
import urllib.parse
import urllib.request

from . import registry
from .base import BaseSMSProvider, SMSError, SMSResult

logger = logging.getLogger("notifications.kavenegar")

API_URL = "https://api.kavenegar.com/v1/{key}/sms/send.json"
# Codes a retry can't fix: bad parameters, inactive account, bad API key, invalid receptor/sender.
PERMANENT = {400, 401, 403, 404, 405, 407, 411, 412, 414, 417}
ERRORS = {
    400: "پارامترهای ارسال ناقص یا نادرست است.",
    401: "حساب کاوه‌نگار غیرفعال است.",
    402: "ارسال پیامک ناموفق بود.",
    403: "کلید API کاوه‌نگار معتبر نیست.",
    407: "دسترسی به این امکان در حساب کاوه‌نگار فعال نیست.",
    411: "شمارهٔ گیرنده معتبر نیست.",
    412: "شمارهٔ فرستنده (خط) معتبر نیست یا متعلق به حساب شما نیست.",
    414: "تعداد گیرنده‌ها بیش از حد مجاز است.",
    417: "تاریخ ارسال معتبر نیست.",
    418: "اعتبار حساب کاوه‌نگار کافی نیست.",
}


@registry.register
class KavenegarProvider(BaseSMSProvider):
    key = "kavenegar"
    label = "کاوه‌نگار"

    def send(self, mobile, text):
        params = {"receptor": mobile, "message": text}
        if self.sender:
            params["sender"] = self.sender
        req = urllib.request.Request(
            API_URL.format(key=urllib.parse.quote(self.api_key, safe="")),
            data=urllib.parse.urlencode(params).encode(),
            headers={"Content-Type": "application/x-www-form-urlencoded", "Accept": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                raw = resp.read().decode()
        except urllib.error.HTTPError as e:  # errors carry a JSON body with the error code
            raw = e.read().decode(errors="replace")
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            logger.warning("Kavenegar send failed: %s", e)
            raise SMSError("ارتباط با سرویس پیامک برقرار نشد.", response=str(e)) from e
        try:
            body = json.loads(raw or "{}")
            status = int(body["return"]["status"])
        except (ValueError, KeyError, TypeError) as e:
            raise SMSError("پاسخ نامعتبر از سرویس پیامک.", response=raw[:2000]) from e
        if status != 200:
            message = ERRORS.get(status) or body["return"].get("message") or f"خطای کاوه‌نگار (کد {status})."
            raise SMSError(message, response=raw[:2000], retryable=status not in PERMANENT)
        entries = body.get("entries") or [{}]
        return SMSResult(message_id=str(entries[0].get("messageid", "")), response=raw[:2000])

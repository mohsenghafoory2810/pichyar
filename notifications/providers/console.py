import logging

from . import registry
from .base import BaseSMSProvider, SMSResult

logger = logging.getLogger("notifications.sms")


@registry.register
class ConsoleProvider(BaseSMSProvider):
    """Writes the message to the log instead of sending it (used while no SMS account is set up)."""

    key = "console"
    label = "بدون ارسال (فقط ثبت در گزارش برنامه)"
    needs_api_key = False
    is_console = True

    def send(self, mobile, text):
        logger.info("SMS (console mode, not sent) to %s:\n%s", mobile, text)
        return SMSResult(response="console")

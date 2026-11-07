from dataclasses import dataclass


class SMSError(Exception):
    """The provider could not send the message. `retryable=False` for errors a retry can't fix
    (bad API key, invalid number, ...)."""

    def __init__(self, message, response="", retryable=True):
        self.message = message
        self.response = response
        self.retryable = retryable
        super().__init__(message)


@dataclass
class SMSResult:
    message_id: str = ""
    response: str = ""  # raw provider answer, stored in SMSLog


class BaseSMSProvider:
    """An SMS provider. Subclass, set `key`/`label`, implement send() and decorate with @registry.register.

    send(mobile, text) -> SMSResult      (raises SMSError)

    `mobile` is 09xxxxxxxxx; `text` is the full message (long texts are sent as one
    multi-part SMS, never cut). Providers with `needs_api_key` fall back to console
    mode while the API key in SiteSettings is empty.
    """

    key = ""
    label = ""
    needs_api_key = True
    is_console = False

    def __init__(self, api_key="", sender="", timeout=10):
        self.api_key = api_key
        self.sender = sender
        self.timeout = timeout

    @classmethod
    def from_settings(cls, site_settings, timeout=10):
        return cls(api_key=site_settings.sms_api_key.strip(), sender=site_settings.sms_sender.strip(), timeout=timeout)

    def send(self, mobile, text):
        raise NotImplementedError

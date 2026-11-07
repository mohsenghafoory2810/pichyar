from dataclasses import dataclass, field


class GatewayError(Exception):
    """The gateway could not be reached or refused the request. The message is shown to the customer."""


@dataclass
class GatewayRedirect:
    url: str  # where to send the customer
    authority: str  # the gateway's id for this transaction, checked again on callback
    raw: dict = field(default_factory=dict)


@dataclass
class VerifyResult:
    success: bool
    ref_id: str = ""
    card_pan: str = ""
    message: str = ""
    canceled: bool = False  # the customer left the gateway without paying
    raw: dict = field(default_factory=dict)


class BaseGateway:
    """A payment gateway. Subclass, set `key`/`label`, and decorate with @registry.register.

    request(order, callback_url)  -> GatewayRedirect     (raises GatewayError)
    verify(request, payment)      -> VerifyResult        (raises GatewayError on network errors)
    callback_authority(request)   -> the authority the gateway sent back to the callback
    is_success_callback(request)  -> False when the customer canceled / the bank declined

    Amounts in the project are Toman; convert in the subclass if the gateway wants Rial.
    """

    key = ""
    label = ""

    def __init__(self, merchant_id="", sandbox=False, timeout=15):
        self.merchant_id = merchant_id
        self.sandbox = sandbox
        self.timeout = timeout

    @classmethod
    def from_settings(cls, site_settings, timeout=15):
        return cls(merchant_id=site_settings.gateway_merchant_id.strip(), sandbox=site_settings.gateway_sandbox, timeout=timeout)

    def request(self, order, callback_url):
        raise NotImplementedError

    def verify(self, request, payment):
        raise NotImplementedError

    def callback_authority(self, request):
        raise NotImplementedError

    def is_success_callback(self, request):
        return True

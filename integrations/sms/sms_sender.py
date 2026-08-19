"""Provider-independent SMS delivery for external HR notifications.

Local development writes text files to a private outbox. Production can use
Twilio Programmable Messaging through its HTTPS REST API without adding a
third-party Python SDK dependency.
"""

from __future__ import annotations

from base64 import b64encode
from dataclasses import dataclass
import json
from pathlib import Path
import re
from typing import Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from uuid import uuid4

from config.settings import Settings


class SmsDeliveryError(RuntimeError):
    """Raised internally when an SMS cannot be delivered safely."""


@dataclass(slots=True)
class OutboundSms:
    """Provider-independent SMS content."""

    to_number: str
    body: str


class SmsSender(Protocol):
    """Contract implemented by local and internet SMS adapters."""

    def send(self, message: OutboundSms) -> str:
        """Deliver a message and return a provider/reference identifier."""


def _digits(value: str) -> str:
    return re.sub(r"\D", "", value or "")


def normalize_phone_number(
    value: str,
    *,
    default_country_code: str,
) -> str:
    """Normalize a stored employee number to an E.164-like international form.

    Examples with ``+63`` as the configured default:
    ``09171234567`` -> ``+639171234567``
    ``639171234567`` -> ``+639171234567``
    ``+639171234567`` -> unchanged after punctuation cleanup.
    """

    raw = (value or "").strip()
    if not raw:
        raise SmsDeliveryError(
            "The employee contact number is empty."
        )

    if raw.startswith("+"):
        normalized = "+" + _digits(raw[1:])
    elif raw.startswith("00"):
        normalized = "+" + _digits(raw[2:])
    else:
        country_digits = _digits(default_country_code)
        if not country_digits:
            raise SmsDeliveryError(
                "SMS_DEFAULT_COUNTRY_CODE is required when employee "
                "numbers are not stored in +country-code format."
            )

        number_digits = _digits(raw)
        if number_digits.startswith(country_digits):
            normalized = "+" + number_digits
        elif number_digits.startswith("0"):
            normalized = "+" + country_digits + number_digits[1:]
        else:
            normalized = "+" + country_digits + number_digits

    digit_count = len(_digits(normalized))
    if digit_count < 8 or digit_count > 15:
        raise SmsDeliveryError(
            "The employee contact number is not a valid international "
            "SMS number."
        )

    return normalized


class LocalOutboxSmsSender:
    """Write development SMS messages to a private local outbox."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.outbox_dir = Path(
            settings.external_sms_outbox_dir
        ).resolve()
        self.outbox_dir.mkdir(parents=True, exist_ok=True)

    def send(self, message: OutboundSms) -> str:
        destination = (
            self.outbox_dir
            / f"external_sms_{uuid4().hex}.txt"
        )
        destination.write_text(
            f"To: {message.to_number}\n\n{message.body}\n",
            encoding="utf-8",
        )
        return str(destination)


class TwilioSmsSender:
    """Send SMS through Twilio Programmable Messaging REST API."""

    API_BASE = "https://api.twilio.com/2010-04-01"

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.account_sid = (
            settings.twilio_account_sid or ""
        ).strip()
        self.auth_token = (
            settings.twilio_auth_token.get_secret_value()
            if settings.twilio_auth_token is not None
            else ""
        ).strip()
        self.from_number = (
            settings.twilio_from_number or ""
        ).strip()
        self.messaging_service_sid = (
            settings.twilio_messaging_service_sid or ""
        ).strip()

        if not self.account_sid or not self.auth_token:
            raise SmsDeliveryError(
                "TWILIO_ACCOUNT_SID and TWILIO_AUTH_TOKEN are required "
                "for Twilio SMS delivery."
            )
        if not self.from_number and not self.messaging_service_sid:
            raise SmsDeliveryError(
                "Configure TWILIO_FROM_NUMBER or "
                "TWILIO_MESSAGING_SERVICE_SID."
            )

    def send(self, message: OutboundSms) -> str:
        endpoint = (
            f"{self.API_BASE}/Accounts/{self.account_sid}/Messages.json"
        )
        form_data: dict[str, str] = {
            "To": message.to_number,
            "Body": message.body,
        }
        if self.messaging_service_sid:
            form_data["MessagingServiceSid"] = (
                self.messaging_service_sid
            )
        else:
            form_data["From"] = self.from_number

        payload = urlencode(form_data).encode("utf-8")
        credentials = b64encode(
            f"{self.account_sid}:{self.auth_token}".encode("utf-8")
        ).decode("ascii")
        request = Request(
            endpoint,
            data=payload,
            method="POST",
            headers={
                "Authorization": f"Basic {credentials}",
                "Content-Type": (
                    "application/x-www-form-urlencoded"
                ),
                "Accept": "application/json",
                "User-Agent": "AI-HR-Assistant/ExternalNotifications",
            },
        )

        try:
            with urlopen(
                request,
                timeout=self.settings.sms_timeout_seconds,
            ) as response:
                raw = response.read().decode("utf-8")
                data = json.loads(raw or "{}")
        except HTTPError as error:
            raise SmsDeliveryError(
                "Twilio SMS delivery was rejected by the provider. "
                "Check the sender, destination, account permissions, "
                "credentials, and messaging configuration."
            ) from error
        except (URLError, TimeoutError, OSError) as error:
            raise SmsDeliveryError(
                "Twilio SMS delivery could not reach the provider. "
                "Check internet access and SMS configuration."
            ) from error
        except (ValueError, json.JSONDecodeError) as error:
            raise SmsDeliveryError(
                "Twilio returned an unreadable SMS response."
            ) from error

        reference = str(data.get("sid") or "").strip()
        if not reference:
            raise SmsDeliveryError(
                "Twilio did not return an SMS message reference."
            )
        return reference


def build_sms_sender(settings: Settings) -> SmsSender:
    """Return the configured SMS adapter."""

    mode = settings.sms_delivery_mode.strip().lower()
    if mode == "local":
        return LocalOutboxSmsSender(settings)
    if mode == "twilio":
        return TwilioSmsSender(settings)
    raise SmsDeliveryError(
        "SMS_DELIVERY_MODE must be local or twilio."
    )

"""Send one real external SMS test using configured provider settings."""

import sys

from integrations.sms.sms_sender import SmsDeliveryError
from services.external_notification_service import ExternalNotificationService


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit(
            "Usage: python scripts/test_sms_notification.py +639171234567"
        )

    service = ExternalNotificationService()
    try:
        reference = service.send_test_sms(sys.argv[1])
    except SmsDeliveryError as error:
        raise SystemExit(str(error)) from error

    print(f"SMS test sent. Provider reference: {reference}")


if __name__ == "__main__":
    main()

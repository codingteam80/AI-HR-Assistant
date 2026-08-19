"""Configure external HR email/SMS notifications safely in `.env`.

Run from the project root:

    python scripts/configure_external_notifications.py

Email uses the existing SMTP configuration. SMS can use Twilio. The script
preserves unrelated values, backs up an existing `.env`, and never prints the
Twilio Auth Token.
"""

from getpass import getpass
from pathlib import Path
import re
import shutil


PROJECT_ROOT = Path(__file__).resolve().parents[1]
ENV_PATH = PROJECT_ROOT / ".env"
BACKUP_PATH = PROJECT_ROOT / ".env.backup_external_notifications"


def _yes_no(label: str, *, default: bool) -> bool:
    marker = "Y/n" if default else "y/N"
    while True:
        value = input(f"{label} [{marker}]: ").strip().lower()
        if not value:
            return default
        if value in {"y", "yes"}:
            return True
        if value in {"n", "no"}:
            return False
        print("Enter Y or N.")


def _prompt(label: str, *, default: str | None = None, required: bool = True) -> str:
    suffix = f" [{default}]" if default is not None else ""
    while True:
        value = input(f"{label}{suffix}: ").strip()
        if not value and default is not None:
            return default
        if value or not required:
            return value
        print("This value is required.")


def _dotenv(value: str) -> str:
    escaped = (
        value.replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("\r", "")
        .replace("\n", "")
    )
    return f'"{escaped}"'


def _upsert(original: str, updates: dict[str, str]) -> str:
    lines = original.splitlines()
    remaining = dict(updates)
    output: list[str] = []
    pattern = re.compile(r"^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=")

    for line in lines:
        match = pattern.match(line)
        if not match:
            output.append(line)
            continue
        key = match.group(1).upper()
        if key in remaining:
            output.append(f"{key}={remaining.pop(key)}")
        else:
            output.append(line)

    if remaining:
        if output and output[-1].strip():
            output.append("")
        output.append("# External HR notification delivery")
        for key, value in remaining.items():
            output.append(f"{key}={value}")

    return "\n".join(output).rstrip() + "\n"


def main() -> None:
    print("AI HR Assistant — External Notifications")
    print("=" * 49)
    print("Destinations come from Employee Master Record:")
    print("- Work Email")
    print("- Telephone / Mobile No.")
    print()

    email_enabled = _yes_no(
        "Enable external email notifications?",
        default=True,
    )
    sms_enabled = _yes_no(
        "Enable external SMS notifications?",
        default=False,
    )

    updates: dict[str, str] = {
        "EXTERNAL_EMAIL_NOTIFICATIONS_ENABLED": (
            "true" if email_enabled else "false"
        ),
        "EXTERNAL_SMS_NOTIFICATIONS_ENABLED": (
            "true" if sms_enabled else "false"
        ),
    }

    if sms_enabled:
        print()
        print("Twilio SMS configuration")
        account_sid = _prompt("Twilio Account SID")
        auth_token = getpass("Twilio Auth Token: ").strip()
        if not auth_token:
            raise SystemExit("Twilio Auth Token cannot be empty.")

        print()
        print("Sender source:")
        print("1. Twilio phone number")
        print("2. Messaging Service SID")
        while True:
            sender_choice = input("Selection [1-2]: ").strip()
            if sender_choice in {"1", "2"}:
                break
            print("Choose 1 or 2.")

        from_number = ""
        service_sid = ""
        if sender_choice == "1":
            from_number = _prompt(
                "Twilio sender number (international + format)"
            )
        else:
            service_sid = _prompt("Twilio Messaging Service SID")

        country_code = _prompt(
            "Default country code for local employee numbers",
            default="+63",
        )

        updates.update(
            {
                "SMS_DELIVERY_MODE": "twilio",
                "SMS_DEFAULT_COUNTRY_CODE": _dotenv(country_code),
                "TWILIO_ACCOUNT_SID": _dotenv(account_sid),
                "TWILIO_AUTH_TOKEN": _dotenv(auth_token),
                "TWILIO_FROM_NUMBER": _dotenv(from_number),
                "TWILIO_MESSAGING_SERVICE_SID": _dotenv(service_sid),
            }
        )

    original = (
        ENV_PATH.read_text(encoding="utf-8")
        if ENV_PATH.exists()
        else ""
    )
    if ENV_PATH.exists():
        shutil.copy2(ENV_PATH, BACKUP_PATH)

    ENV_PATH.write_text(
        _upsert(original, updates),
        encoding="utf-8",
    )

    print()
    print(f"Saved settings to: {ENV_PATH}")
    if BACKUP_PATH.exists():
        print(f"Backup created at: {BACKUP_PATH}")
    print()
    if email_enabled:
        print(
            "Email notifications require real SMTP. If SMTP is not yet "
            "configured, run: python scripts\\configure_smtp.py"
        )
    if sms_enabled:
        print(
            "SMS is set to Twilio. Use Admin Portal > Integrations > "
            "Send Test SMS after restart."
        )
    print("Restart Streamlit after changing .env settings.")


if __name__ == "__main__":
    main()

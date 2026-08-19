"""Interactively configure real SMTP internet email delivery.

Run from the project root:

    python scripts/configure_smtp.py

The script:
- Preserves unrelated `.env` values.
- Creates `.env.backup` before changing an existing file.
- Never prints the SMTP password.
- Provides Gmail, Microsoft 365, and custom SMTP presets.
- Requires a Streamlit restart after saving.

For Gmail or Google Workspace, use an app password when required by the
account's security configuration. For Microsoft 365, the mailbox/tenant
must allow the chosen SMTP submission method.
"""

from getpass import getpass
from pathlib import Path
import re
import shutil


PROJECT_ROOT = Path(__file__).resolve().parents[1]
ENV_PATH = PROJECT_ROOT / ".env"
BACKUP_PATH = PROJECT_ROOT / ".env.backup"


def _prompt(
    label: str,
    *,
    default: str | None = None,
    required: bool = True,
) -> str:
    """Prompt for a text value with an optional default."""

    default_label = (
        f" [{default}]"
        if default is not None
        else ""
    )

    while True:
        value = input(
            f"{label}{default_label}: "
        ).strip()

        if not value and default is not None:
            return default

        if value or not required:
            return value

        print("This value is required.")


def _prompt_port(default: int) -> int:
    """Prompt until a valid TCP port is provided."""

    while True:
        value = _prompt(
            "SMTP port",
            default=str(default),
        )

        try:
            port = int(value)
        except ValueError:
            print("Enter a valid numeric port.")
            continue

        if 1 <= port <= 65535:
            return port

        print("Port must be between 1 and 65535.")


def _dotenv_value(value: str) -> str:
    """Quote and escape one `.env` value safely."""

    escaped = (
        value
        .replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("\n", "")
        .replace("\r", "")
    )

    return f'"{escaped}"'


def _upsert_env(
    original: str,
    updates: dict[str, str],
) -> str:
    """Replace matching keys and append missing keys."""

    lines = original.splitlines()
    remaining = dict(updates)
    output: list[str] = []

    pattern = re.compile(
        r"^\s*([A-Za-z_][A-Za-z0-9_]*)\s*="
    )

    for line in lines:
        match = pattern.match(line)

        if not match:
            output.append(line)
            continue

        key = match.group(1).upper()

        if key in remaining:
            output.append(
                f"{key}={remaining.pop(key)}"
            )
        else:
            output.append(line)

    if remaining:
        if output and output[-1].strip():
            output.append("")

        output.append(
            "# Real SMTP email delivery"
        )

        for key, value in remaining.items():
            output.append(f"{key}={value}")

    return "\n".join(output).rstrip() + "\n"


def _choose_provider() -> dict[str, object]:
    """Return SMTP preset values selected by the administrator."""

    print()
    print("Choose SMTP provider:")
    print("1. Gmail / Google Workspace")
    print("2. Microsoft 365")
    print("3. Custom SMTP server")

    while True:
        choice = input("Selection [1-3]: ").strip()

        if choice == "1":
            return {
                "name": "Gmail / Google Workspace",
                "host": "smtp.gmail.com",
                "port": 587,
                "starttls": True,
                "ssl": False,
            }

        if choice == "2":
            return {
                "name": "Microsoft 365",
                "host": "smtp.office365.com",
                "port": 587,
                "starttls": True,
                "ssl": False,
            }

        if choice == "3":
            host = _prompt("SMTP host")
            port = _prompt_port(587)

            print()
            print("Encryption:")
            print("1. STARTTLS")
            print("2. SSL/TLS")
            print("3. None")

            while True:
                encryption = input(
                    "Selection [1-3]: "
                ).strip()

                if encryption in {
                    "1",
                    "2",
                    "3",
                }:
                    break

                print("Choose 1, 2, or 3.")

            return {
                "name": "Custom SMTP",
                "host": host,
                "port": port,
                "starttls": encryption == "1",
                "ssl": encryption == "2",
            }

        print("Choose 1, 2, or 3.")


def main() -> None:
    """Collect SMTP settings and update the private `.env` file."""

    print("AI HR Assistant — SMTP Configuration")
    print("=" * 48)

    provider = _choose_provider()

    print()
    print(f"Provider: {provider['name']}")

    username = _prompt(
        "SMTP username / sender account"
    )
    password = getpass(
        "SMTP password or app password: "
    ).strip()

    if not password:
        raise SystemExit(
            "SMTP password cannot be empty."
        )

    from_email = _prompt(
        "From email",
        default=username,
    )
    from_name = _prompt(
        "From display name",
        default="AI HR Assistant",
    )
    base_url = _prompt(
        "Public Streamlit URL",
        default="http://localhost:8501",
    ).rstrip("/")

    original = (
        ENV_PATH.read_text(encoding="utf-8")
        if ENV_PATH.exists()
        else ""
    )

    if ENV_PATH.exists():
        shutil.copy2(
            ENV_PATH,
            BACKUP_PATH,
        )

    updates = {
        "EMAIL_DELIVERY_MODE": "smtp",
        "EXTERNAL_EMAIL_NOTIFICATIONS_ENABLED": "true",
        "PASSWORD_RESET_BASE_URL": (
            _dotenv_value(base_url)
        ),
        "SMTP_HOST": _dotenv_value(
            str(provider["host"])
        ),
        "SMTP_PORT": str(provider["port"]),
        "SMTP_USERNAME": _dotenv_value(username),
        "SMTP_PASSWORD": _dotenv_value(password),
        "SMTP_FROM_EMAIL": _dotenv_value(
            from_email
        ),
        "SMTP_FROM_NAME": _dotenv_value(
            from_name
        ),
        "SMTP_USE_STARTTLS": (
            "true"
            if provider["starttls"]
            else "false"
        ),
        "SMTP_USE_SSL": (
            "true"
            if provider["ssl"]
            else "false"
        ),
    }

    ENV_PATH.write_text(
        _upsert_env(
            original,
            updates,
        ),
        encoding="utf-8",
    )

    print()
    print(f"Saved SMTP settings to: {ENV_PATH}")

    if BACKUP_PATH.exists():
        print(f"Backup created at: {BACKUP_PATH}")

    print()
    print("Next steps:")
    print("1. Stop Streamlit with Ctrl + C")
    print("2. Run: streamlit cache clear")
    print("3. Run: streamlit run app.py")
    print("4. Open Admin Portal > Integrations")
    print("5. Send an Internet Test Email")
    print()
    print("The SMTP password was saved only in the private .env file.")


if __name__ == "__main__":
    main()

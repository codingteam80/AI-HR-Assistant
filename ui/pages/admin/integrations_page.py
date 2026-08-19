"""Administrator External Notifications workspace.

Email and SMS sender configuration is managed directly inside the protected
Admin Portal. Employee recipients remain automatic: Work Email and Telephone /
Mobile No. from Employee Master Record are the authoritative destinations.
"""

import streamlit as st

from authentication.current_user import AuthenticatedUser
from integrations.email.email_sender import EmailDeliveryError
from integrations.sms.sms_sender import SmsDeliveryError
from services.email_integration_service import EmailIntegrationService
from services.external_notification_service import ExternalNotificationService
from services.notification_configuration_service import (
    NotificationConfigurationError,
    NotificationConfigurationService,
)
from ui.components.data_table import render_admin_table
from ui.components.validation_feedback import render_action_warning


def _display_value(value, *, missing: str = "Not configured") -> str:
    if value is None or value == "":
        return missing
    return str(value)


def _masked_identifier(value: str | None) -> str:
    safe = (value or "").strip()
    if not safe:
        return "Not configured"
    if len(safe) <= 8:
        return "Configured"
    return f"Configured · …{safe[-4:]}"


def _email_configuration_section(
    current_user: AuthenticatedUser,
) -> None:
    st.subheader("Email Notifications")
    st.write(
        "Enter the company sender email. Common email providers are detected "
        "automatically, so there is no Gmail/Outlook/Yahoo provider dropdown."
    )

    config_service = NotificationConfigurationService()
    external_service = ExternalNotificationService()
    external_status = external_service.get_status()
    email_service = EmailIntegrationService()
    email_status = email_service.get_status()
    settings = config_service.settings

    configured_sender = (settings.smtp_from_email or "").strip()
    if not configured_sender or configured_sender == "no-reply@example.com":
        configured_sender = current_user.email

    sender_email = st.text_input(
        "Company Sender Email",
        value=configured_sender,
        key="external_email_sender_email",
        max_chars=255,
        help=(
            "Examples: companyhr@gmail.com, hr@outlook.com, or "
            "hr@company.com. Employee recipient addresses are taken "
            "automatically from Employee Master Record."
        ),
    )

    detected = None
    try:
        detected = config_service.detect_sender(sender_email)
        if detected.automatic:
            st.success(
                f"Provider detected automatically: {detected.display_name}"
            )
            st.caption(
                "Outgoing mail server settings will be filled internally. "
                "You only need the credential allowed by that email account."
            )
        else:
            st.info(
                "Custom/company email detected. The email domain alone cannot "
                "reliably identify whether the company uses Google Workspace, "
                "Microsoft 365, an on-premise server, or another relay."
            )
        st.caption(detected.guidance)
    except NotificationConfigurationError:
        detected = None

    custom_host = None
    custom_port = None
    custom_encryption = "STARTTLS"
    if detected is not None and not detected.automatic:
        with st.expander("Advanced SMTP Settings", expanded=True):
            custom_host = st.text_input(
                "Outgoing SMTP Server",
                value=(settings.smtp_host or ""),
                key="external_email_custom_host",
                placeholder="smtp.company.com",
                max_chars=255,
            )
            custom_port = st.number_input(
                "SMTP Port",
                min_value=1,
                max_value=65535,
                value=int(settings.smtp_port or 587),
                step=1,
                key="external_email_custom_port",
            )
            current_encryption = (
                "SSL/TLS"
                if settings.smtp_use_ssl
                else "STARTTLS"
                if settings.smtp_use_starttls
                else "None"
            )
            custom_encryption = st.selectbox(
                "Encryption",
                ["STARTTLS", "SSL/TLS", "None"],
                index=["STARTTLS", "SSL/TLS", "None"].index(
                    current_encryption
                ),
                key="external_email_custom_encryption",
            )

    sender_name = st.text_input(
        "Sender Name",
        value=(settings.smtp_from_name or "AI HR Assistant"),
        key="external_email_sender_name",
        max_chars=120,
    )
    credential_label = (
        detected.credential_label
        if detected is not None
        else "Email Credential"
    )
    credential = st.text_input(
        credential_label,
        value="",
        type="password",
        key="external_email_credential",
        help=(
            "Leave blank to keep the credential already saved in the project. "
            "The saved credential is never displayed back in the browser."
        ),
    )

    activate_email = st.toggle(
        "Activate Email Notifications",
        value=external_status.email_enabled,
        key="external_email_enabled_toggle",
        help=(
            "When active, eligible committed HR notifications are also sent "
            "to each employee's Work Email. Existing rich leave emails are "
            "not duplicated."
        ),
    )

    if st.button(
        "Save Email Settings",
        type="primary",
        width="stretch",
        key="save_external_email_settings",
    ):
        try:
            result = config_service.save_email(
                sender_email=sender_email,
                sender_name=sender_name,
                credential=credential,
                enabled=activate_email,
                custom_host=custom_host,
                custom_port=(int(custom_port) if custom_port else None),
                custom_encryption=custom_encryption,
            )
            st.session_state["external_notifications_success"] = (
                f"Email settings saved. Provider: {result.email_provider}."
            )
            st.rerun()
        except NotificationConfigurationError as error:
            render_action_warning(error)
        except Exception:
            st.error(
                "Email settings could not be saved. Check the project write "
                "permission and try again."
            )

    if email_status.internet_delivery_ready:
        st.success("Internet email delivery is configured.")
    else:
        st.warning("Internet email delivery is not ready.")

    email_state = "Active" if external_status.email_enabled else "Disabled"
    readiness = (
        "Ready" if external_status.email_internet_ready else "Not Ready"
    )
    metrics = st.columns(3)
    metrics[0].metric("Email Notifications", email_state)
    metrics[1].metric("Internet Email", readiness)
    metrics[2].metric(
        "SMTP Credential",
        "Configured" if email_status.password_configured else "Not configured",
    )

    render_admin_table(
        [
            {
                "Setting": "Detected/Configured sender",
                "Value": _display_value(email_status.from_email),
            },
            {
                "Setting": "Outgoing server",
                "Value": _display_value(email_status.host),
            },
            {
                "Setting": "Port / Encryption",
                "Value": (
                    f"{_display_value(email_status.port)} / "
                    f"{email_status.encryption}"
                ),
            },
            {
                "Setting": "External recipient source",
                "Value": "Employee Master Record · Work Email",
            },
        ],
        key="email-integration-details",
        min_width=680,
        column_widths=("240px", "440px"),
        compact=True,
    )

    # Preserve the safe wording protected by earlier SMTP regression checks.
    st.caption(
        "The SMTP password is intentionally hidden and is never sent back to "
        "the browser after it is saved."
    )

    st.markdown("### Send Test Email")
    with st.form("smtp_test_email_form", clear_on_submit=False):
        test_recipient = st.text_input(
            "Test Recipient Email",
            value=current_user.email,
            max_chars=255,
            help=(
                "A real test message will be sent through the configured "
                "SMTP provider. Testing is available even before external "
                "email notifications are activated."
            ),
        )
        send_test = st.form_submit_button(
            "Send Internet Test Email",
            type="primary",
            width="stretch",
            disabled=not email_status.internet_delivery_ready,
        )

    if send_test:
        try:
            result = email_service.send_test_email(test_recipient)
            st.success(
                f"Test email sent successfully to {result.recipient}."
            )
            st.caption(f"Sent at {result.sent_at.isoformat()}.")
        except EmailDeliveryError as error:
            render_action_warning(error)
        except Exception:
            st.error(
                "The test email could not be sent. Review the detected/custom "
                "mail settings, account credential, and network access."
            )


def _sms_configuration_section() -> None:
    st.divider()
    st.subheader("SMS Notifications")
    st.write(
        "Configure the company SMS gateway once. Employees do not select "
        "Globe, Smart, DITO, or another mobile network; the HR Assistant uses "
        "their saved Telephone / Mobile No. automatically."
    )

    config_service = NotificationConfigurationService()
    settings = config_service.settings
    external_service = ExternalNotificationService()
    external_status = external_service.get_status()

    st.caption(
        "Current internet gateway adapter: Twilio Programmable Messaging. "
        "The adapter remains separate from HR business logic so another SMS "
        "gateway can be added later without changing employee records."
    )

    account_sid = st.text_input(
        "Company SMS Gateway Account SID",
        value=(settings.twilio_account_sid or ""),
        key="external_sms_account_sid",
        max_chars=80,
    )
    auth_token = st.text_input(
        "SMS Gateway Auth Token",
        value="",
        type="password",
        key="external_sms_auth_token",
        help=(
            "Leave blank to keep the saved token. The token is never displayed "
            "back in the browser."
        ),
    )
    sender_number = st.text_input(
        "SMS Sender Number",
        value=(settings.twilio_from_number or ""),
        key="external_sms_sender_number",
        placeholder="+15005550006",
        max_chars=50,
        help=(
            "Use the sender number assigned by the company SMS gateway. "
            "Leave blank when a Messaging Service SID supplies the sender."
        ),
    )
    messaging_service_sid = st.text_input(
        "Messaging Service SID (Optional)",
        value=(settings.twilio_messaging_service_sid or ""),
        key="external_sms_messaging_service_sid",
        max_chars=80,
    )
    default_country_code = st.text_input(
        "Default Country Code",
        value=(settings.sms_default_country_code or "+63"),
        key="external_sms_country_code",
        max_chars=5,
        help=(
            "Used only when an employee number is stored in local format. "
            "Example: 09171234567 becomes +639171234567 when +63 is used."
        ),
    )

    activate_sms = st.toggle(
        "Activate SMS Notifications",
        value=external_status.sms_enabled,
        key="external_sms_enabled_toggle",
        help=(
            "When active, eligible committed HR notifications are sent to "
            "Employee Master Record Telephone / Mobile No."
        ),
    )

    if st.button(
        "Save SMS Settings",
        type="primary",
        width="stretch",
        key="save_external_sms_settings",
    ):
        try:
            config_service.save_sms(
                enabled=activate_sms,
                account_sid=account_sid,
                auth_token=auth_token,
                from_number=sender_number,
                messaging_service_sid=messaging_service_sid,
                default_country_code=default_country_code,
            )
            st.session_state["external_notifications_success"] = (
                "SMS gateway settings saved."
            )
            st.rerun()
        except NotificationConfigurationError as error:
            render_action_warning(error)
        except Exception:
            st.error(
                "SMS settings could not be saved. Check the project write "
                "permission and try again."
            )

    sms_metrics = st.columns(3)
    sms_metrics[0].metric(
        "SMS Notifications",
        "Active" if external_status.sms_enabled else "Disabled",
    )
    sms_metrics[1].metric(
        "SMS Internet",
        "Ready" if external_status.sms_internet_ready else "Not Ready",
    )
    sms_metrics[2].metric(
        "SMS Sender",
        "Configured" if external_status.sms_sender_configured else "Not configured",
    )

    render_admin_table(
        [
            {
                "Setting": "Gateway account",
                "Value": _masked_identifier(settings.twilio_account_sid),
            },
            {
                "Setting": "Sender number / service",
                "Value": (
                    _masked_identifier(settings.twilio_from_number)
                    if settings.twilio_from_number
                    else _masked_identifier(settings.twilio_messaging_service_sid)
                ),
            },
            {
                "Setting": "Default country code",
                "Value": external_status.default_country_code,
            },
            {
                "Setting": "External recipient source",
                "Value": "Employee Master Record · Telephone / Mobile No.",
            },
        ],
        key="external-notification-details",
        min_width=680,
        column_widths=("240px", "440px"),
        compact=True,
    )

    st.caption(
        "External delivery happens only after a successful HR transaction "
        "commit. A provider failure does not undo the leave, overtime, "
        "announcement, reminder, form, or other in-app action."
    )

    st.markdown("### Send Test SMS")
    with st.form("external_sms_test_form", clear_on_submit=False):
        sms_recipient = st.text_input(
            "Test Mobile Number",
            placeholder="+639171234567 or 09171234567",
            max_chars=50,
            help=(
                "Local-format numbers use the configured default country code "
                "before they are sent to the SMS gateway."
            ),
        )
        send_sms_test = st.form_submit_button(
            "Send Internet Test SMS",
            type="primary",
            width="stretch",
            disabled=not external_status.sms_internet_ready,
        )

    if send_sms_test:
        try:
            reference = external_service.send_test_sms(sms_recipient)
            st.success(
                "Test SMS sent successfully. "
                f"Provider reference: {reference}"
            )
        except SmsDeliveryError as error:
            render_action_warning(error)
        except Exception:
            st.error(
                "The test SMS could not be sent. Review the company SMS "
                "gateway settings, sender, destination, and network access."
            )


def render_integrations_page(current_user: AuthenticatedUser) -> None:
    """Configure and test external notifications without command-line setup."""

    st.title("External Notifications")
    st.caption(
        "Configure company sender channels here. Employee destinations are "
        "taken automatically from Employee Master Record."
    )

    success_message = st.session_state.pop(
        "external_notifications_success",
        None,
    )
    if success_message:
        st.success(success_message)

    _email_configuration_section(current_user)

    st.divider()
    st.subheader("External HR Notifications")
    st.write(
        "Committed in-app notification events can also be sent outside the "
        "portal using the employee's Work Email and Telephone / Mobile No. "
        "from Employee Master Record."
    )

    _sms_configuration_section()

    st.divider()
    st.subheader("Forgot Password Delivery")
    st.write(
        "When internet email is configured, Forgot Password sends a single-use "
        "reset link directly to the user's registered Login Email."
    )
    st.caption(
        "The existing password is never emailed. The public page always uses "
        "a generic response to protect account privacy."
    )

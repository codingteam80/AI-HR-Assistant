"""Administrator integrations page.

The Email Delivery section reports safe SMTP configuration values and can
send a real test message through the same adapter used by Forgot Password.
Secrets are read from `.env` and are never displayed in the browser.
"""

import streamlit as st
from ui.components.validation_feedback import render_action_warning

from authentication.current_user import AuthenticatedUser
from ui.components.data_table import render_admin_table
from integrations.email.email_sender import (
    EmailDeliveryError,
)
from services.email_integration_service import (
    EmailIntegrationService,
)


def _display_value(
    value,
    *,
    missing: str = "Not configured",
) -> str:
    """Return a readable safe configuration value."""

    if value is None or value == "":
        return missing

    return str(value)


def render_integrations_page(
    current_user: AuthenticatedUser,
) -> None:
    """Display email readiness and send a real SMTP test message."""

    st.title("Integrations")
    st.caption(
        "Configure and verify external services used by the HR Assistant."
    )

    st.subheader("Email Delivery")

    service = EmailIntegrationService()
    status = service.get_status()

    if status.internet_delivery_ready:
        st.success(
            "Internet email delivery is configured."
        )
    else:
        st.warning(
            "Internet email delivery is not ready."
        )

    st.info(status.message)

    metrics = st.columns(4)

    metrics[0].metric(
        "Delivery Mode",
        status.mode.upper(),
    )
    metrics[1].metric(
        "SMTP Host",
        _display_value(status.host),
    )
    metrics[2].metric(
        "SMTP Port",
        _display_value(status.port),
    )
    metrics[3].metric(
        "Encryption",
        status.encryption,
    )

    st.markdown("**Safe configuration details**")

    render_admin_table(
        [
            {
                "Setting": "SMTP username",
                "Value": (
                    "Configured"
                    if status.username_configured
                    else "Not configured"
                ),
            },
            {
                "Setting": "Sender name",
                "Value": status.from_name,
            },
            {
                "Setting": "Sender email",
                "Value": status.from_email,
            },
            {
                "Setting": "Password-reset base URL",
                "Value": status.reset_base_url,
            },
            {
                "Setting": "Authenticated company",
                "Value": current_user.company_name,
            },
        ],
        key="email-integration-details",
        min_width=680,
        column_widths=("220px", "460px"),
        compact=True,
    )

    st.caption(
        "The SMTP password is intentionally hidden and is never sent "
        "to the browser."
    )

    if not status.internet_delivery_ready:
        st.markdown("### Configure Internet Email")
        st.code(
            "python scripts\\configure_smtp.py",
            language="powershell",
        )
        st.caption(
            "The setup script updates the private `.env` file. "
            "Restart Streamlit after configuration."
        )

    st.divider()
    st.subheader("Send Test Email")

    with st.form(
        "smtp_test_email_form",
        clear_on_submit=False,
    ):
        test_recipient = st.text_input(
            "Test Recipient Email",
            value=current_user.email,
            max_chars=255,
            help=(
                "A real test message will be sent through the "
                "configured SMTP provider."
            ),
        )

        send_test = st.form_submit_button(
            "Send Internet Test Email",
            type="primary",
            width="stretch",
            disabled=(
                not status.internet_delivery_ready
            ),
        )

    if send_test:
        try:
            result = service.send_test_email(
                test_recipient
            )

            st.success(
                "Test email sent successfully to "
                f"{result.recipient}."
            )
            st.caption(
                f"Sent at {result.sent_at.isoformat()}."
            )

        except EmailDeliveryError as error:
            render_action_warning(error)
        except Exception:
            st.error(
                "The test email could not be sent. "
                "Review the SMTP settings and network access."
            )

    st.divider()
    st.subheader("Forgot Password Delivery")
    st.write(
        "When SMTP is ready, Forgot Password sends a single-use reset "
        "link directly to the user's registered Login Email."
    )
    st.caption(
        "The existing password is never emailed. The public page always "
        "uses a generic response to protect account privacy."
    )

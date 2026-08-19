# AI HR Assistant — v8.8.162

## External Email & SMS Notifications

This release adds external notification mirroring for committed in-app HR events.

### Included
- Employee Master Record **Work Email** as the external email destination.
- Employee Master Record **Telephone / Mobile No.** as the SMS destination.
- Independent external email and SMS enable/disable settings.
- Existing SMTP adapter reused for real email delivery.
- Twilio Programmable Messaging adapter for real SMS delivery.
- Local SMS outbox mode for development/testing.
- Philippine local-number normalization through configurable `SMS_DEFAULT_COUNTRY_CODE` (default `+63`).
- External delivery runs only after a successful database commit.
- Rollbacks discard queued external messages.
- Provider failures do not roll back successful HR transactions.
- Duplicate rich leave emails are prevented; existing leave To/CC/attachment emails remain authoritative while SMS may mirror the same notification event.
- Admin **External Notifications** workspace with readiness indicators and **Send Internet Test SMS**.
- `scripts/configure_external_notifications.py` and `scripts/test_sms_notification.py`.
- `scripts/configure_smtp.py` now enables external HR email notifications when SMTP is configured.

### Preserved from v8.8.161
- Configurable leave credit reset month/day.
- Manager Annual VL Retention fixed at 13 days.
- Configurable Leave Utilization enable/disable and percentage.
- Attendance Hub Work Status-only editing without changing Time In/Time Out.
- Existing audit/current-view behavior and notification bell workflows.

### Activation
External channels are disabled safely by default until provider credentials are configured.

```powershell
python scripts\configure_smtp.py
python scripts\configure_external_notifications.py
```

Then restart Streamlit and verify status under **Admin Portal > External Notifications**.

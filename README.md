# AI HR Assistant

AI HR Assistant is a local Streamlit HR portal with separate administrator and employee workspaces. It includes authentication, employee management, attendance/DTR, leave and overtime workflows, company forms/documents, announcements, reports, audit history, policy Q&A, and external email/SMS notifications.

This README is an execution and setup guide. Release history is intentionally not maintained here.

### Authoritative setup files

Use the project-root `README.md` and `requirements.txt` as the single source of truth for setup and dependencies. The legacy `schemas/README.md` and `schemas/requirements.txt` are compatibility pointers only and must not maintain a separate dependency/setup copy.

## 1. Requirements

Recommended local environment:

- Windows 10/11
- Python 3.11+
- PowerShell
- Internet connection only for features that call external services such as real email or SMS
- Ollama for the local Chat Assistant

The main HR application and database can still run locally without external email/SMS access.

## 2. Open the Project

Open PowerShell in the project root, where `app.py` and `requirements.txt` are located.

Example:

```powershell
cd C:\user_dev\hr_assistant
```

## 3. Create and Activate the Virtual Environment

Create the environment once:

```powershell
python -m venv .venv
```

Activate it whenever you work on the project:

```powershell
.\.venv\Scripts\Activate.ps1
```

Upgrade pip:

```powershell
python -m pip install --upgrade pip
```

Install project dependencies:

```powershell
python -m pip install -r requirements.txt
```

## 4. Configure `.env`

The project reads local configuration from `.env`.

If `.env` does not exist, copy `.env.example` first:

```powershell
Copy-Item .env.example .env
```

At minimum, review:

```text
DATABASE_URL
INITIAL_COMPANY_CODE
INITIAL_COMPANY_NAME
INITIAL_ADMIN_USERNAME
INITIAL_ADMIN_EMAIL
INITIAL_ADMIN_PASSWORD
```

Do not commit real passwords, SMTP credentials, SMS gateway tokens, or production secrets to Git.

## 5. Create / Verify the Database

Create the database when setting up a new local installation:

```powershell
python -m scripts.create_database
```

Verify the database:

```powershell
python -m scripts.check_database
```

Create the initial company and administrator account when needed:

```powershell
python -m scripts.create_initial_data
```

Verify initial data:

```powershell
python -m scripts.check_initial_data
```

The normal runtime schema upgrade path is additive and should preserve existing records.

## 6. Ollama Chat Assistant Setup

Install Ollama on the PC and make sure the Ollama service is running.

Pull the configured local model:

```powershell
ollama pull qwen2.5:7b
```

Check installed models:

```powershell
ollama list
```

Chat Assistant developer configuration is centralized in:

```text
config/chat_assistant_settings.py
modules/smart_ai/prompts/hr_assistant_prompt.py
```

Use `config/chat_assistant_settings.py` for model/generation/retrieval tuning and
`hr_assistant_prompt.py` for answer instructions and formatting rules. Matching
`SMART_AI_*` values in `.env` can override the safe defaults without editing
business logic.

The default local Ollama endpoint is:

```text
http://localhost:11434
```

The Chat Assistant uses a hybrid company-knowledge design: deterministic
company-scoped queries for structured HR records and permission-sensitive
data, plus grounded retrieval for published policies, portal workflows, and
readable Company Form/Documents file content. Admin questions can return live
employee lists, hierarchy-derived Manager/Leader sets, date-aware HR results,
follow-up counts/lists, and charts when the requested comparison benefits from
a visual. Employee responses remain restricted to the employee's authorized
self/team scope and published company information.

## 7. Run the Application

From the project root with the virtual environment active:

```powershell
streamlit run app.py
```

Open the local Streamlit URL shown in PowerShell, normally:

```text
http://localhost:8501
```

## 8. External Email Notifications

Normal setup is performed inside the application:

1. Log in as Administrator.
2. Open **External Notifications**.
3. Enter the **Company Sender Email**.
4. The app automatically detects supported common providers from the sender email domain.
5. Enter the sender credential or app password required by that account.
6. Save the settings.
7. Send a test email.
8. Turn on **Activate Email Notifications** when ready.

There is no Gmail/Outlook/Yahoo provider selector. The sender email is the input used for provider detection.

For custom/company domains, the email domain alone may not reveal the real outgoing server. In that case, **Advanced SMTP Settings** is shown so the company SMTP host, port, and encryption can be entered once.

Employee recipients do not need separate notification setup. The external recipient is taken automatically from:

```text
Employee Master Record -> Work Email
```

The saved email credential is never displayed back in the browser.

### Optional Email CLI Utilities

The existing scripts remain available as fallback/admin utilities if the UI cannot be used:

```powershell
python scripts\configure_smtp.py
python scripts\test_smtp_email.py
```

They are not required for the normal in-app setup flow.

## 9. External SMS Notifications

SMS is also configured inside **Admin Portal -> External Notifications**.

The company configures the SMS gateway once. Employees do not choose Globe, Smart, DITO, or another recipient network.

Normal setup:

1. Enter the company SMS gateway Account SID.
2. Enter the Auth Token.
3. Enter the SMS sender number or Messaging Service SID.
4. Confirm the default country code, such as `+63`.
5. Save the settings.
6. Send a test SMS.
7. Turn on **Activate SMS Notifications** when ready.

Employee recipients are taken automatically from:

```text
Employee Master Record -> Telephone / Mobile No.
```

For Philippine local numbers, the default `+63` configuration can normalize values such as:

```text
09171234567 -> +639171234567
```

The current internet SMS gateway adapter is Twilio Programmable Messaging. The adapter is isolated from HR business logic so another gateway can be added later without changing employee records or approval workflows.

### Optional SMS CLI Utilities

Fallback/admin utilities remain available:

```powershell
python scripts\configure_external_notifications.py
python scripts\test_sms_notification.py
```

They are not required for normal in-app setup.

## 10. External Notification Safety

External email/SMS is secondary to the in-app HR record.

The application preserves these rules:

- HR data is committed first.
- External delivery happens only after a successful transaction commit.
- A rollback sends no external notification.
- Email/SMS provider failure does not undo a successful leave, overtime, attendance, announcement, form, or other HR action.
- Existing rich leave emails are not duplicated by the generic external-email mirror.
- Email and SMS channels can be enabled independently.

## 11. Employee Contact Data

For external delivery to work, employee records should contain the applicable destination fields:

```text
Work Email
Telephone / Mobile No.
```

If an employee has no Work Email, email delivery for that recipient is skipped.

If an employee has no Telephone / Mobile No., SMS delivery for that recipient is skipped.

The remaining enabled channel can still be used.

## 12. Recommended Validation Commands

Basic project check:

```powershell
python -m scripts.check_project
```

Python syntax check:

```powershell
python -m compileall -q .
```

Run automated tests:

```powershell
python -m pytest -q
```

For focused notification checks:

```powershell
python -m pytest tests\test_email_integration_service.py tests\test_v88162_external_notifications.py tests\test_v88162_external_notifications_static.py -q
```

## 13. Common Troubleshooting

### `ModuleNotFoundError`

Make sure the virtual environment is active and dependencies are installed:

```powershell
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

Run project modules from the project root. For scripts that import project modules, prefer module execution where supported:

```powershell
python -m scripts.create_initial_data
```

### Streamlit command not found

Use:

```powershell
python -m streamlit run app.py
```

### Email test fails

Check:

- Sender email
- Provider/account SMTP permission
- App password or SMTP credential
- Custom SMTP host/port/encryption when using a company domain
- Internet/firewall access

Some email providers enforce account-specific authentication rules. The app detects common server settings where possible, but the provider still controls which authentication method the account may use.

### SMS test fails

Check:

- SMS gateway Account SID
- Auth Token
- Sender number or Messaging Service SID
- Destination number format
- Account permissions and balance/provider restrictions
- Internet/firewall access

### Changes to `.env` are not reflected

In-app notification settings clear the cached application settings and rerun the page automatically. For manual `.env` edits outside the app, restart Streamlit.

## 14. Important Local Data

Before replacing or moving a project installation, back up the live data you want to keep, especially:

```text
.env
data\hr_assistant.db
data\uploads\
data\smart_ai\
```

Do not replace a working production database with a sample database from another package.

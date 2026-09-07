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

Long policy and Company Form/Documents content is indexed with document-aware
retrieval. Each file keeps its own file/title/section/page/chunk metadata; the
retriever first selects the most relevant company files, then ranks chunks
inside those files with BM25 plus the optional local Chroma semantic path.
Policy chunks use sentence/row-aware 180-word targets with 24-word overlap;
Company Form/Documents chunks use 220-word targets with 32-word overlap. The
final context limits seed chunks per file and can add an adjacent chunk from
the same section when a rule crosses a chunk boundary. Structured employee,
attendance, leave, overtime, and other live HR records remain deterministic
and are not flattened into document chunks.

The company-only boundary is unchanged: retrieval is scoped to the authenticated
company and current portal role before ranking, Chroma queries are restricted
to the exact authorized document-set snapshot, and Qwen must not answer from
outside/general knowledge when company evidence is unavailable.

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

## 15. Chat Assistant Terminal Retrieval Trace (v0.8.8.217)

The Admin and Employee Chat Assistants can print a developer-only retrieval
trace to the Streamlit server terminal. Nothing from this trace is rendered in
the portal UI.

Default package setting:

```text
SMART_AI_TERMINAL_DEBUG_ENABLED=true
```

The trace shows the user question, contextual retrieval query, authorized
knowledge counts, file-stage BM25/vector/hybrid scores, selected files,
chunk-stage BM25 scores, vector cosine nearest-neighbor scores, hybrid/RRF
ranking, selected/final evidence chunks, bounded chunk excerpts, deterministic
router answer, Ollama model/timing/retry status, raw Qwen answer, and final Chat
Assistant answer.

To disable the terminal trace, set:

```text
SMART_AI_TERMINAL_DEBUG_ENABLED=false
```

and restart Streamlit. Additional display limits are controlled by
`SMART_AI_TERMINAL_DEBUG_TOP_K`, `SMART_AI_TERMINAL_DEBUG_EXCERPT_CHARS`, and
`SMART_AI_TERMINAL_DEBUG_ANSWER_CHARS`.

## 16. Terminal Candidate Answers Trace (v0.8.8.218)

The Chat Assistant terminal diagnostics now also print **Candidate Answers — Retrieved Evidence**. Each candidate includes the final retrieval score, answer-fit diagnostic score, source document, section/page/chunk metadata, and a bounded question-focused `possible_answer` excerpt. The terminal also shows `ANSWER OPTION — ROUTER`, `ANSWER OPTION — QWEN`, and an `ANSWER SELECTION` line explaining which path produced the final chat answer. These diagnostics are terminal-only and do not add Streamlit UI elements or alter retrieval/ranking/generation behavior.

## v8.8.219 — Readable Chat Retrieval Debug + Relevance Guard + Top Source

This checkpoint keeps the v8.8.218 retrieval/chunking/parser architecture and focuses on Chat Assistant diagnostics and answer safety:

- Terminal retrieval diagnostics are rendered as a structured per-question report (question analysis, file/chunk ranking, candidate answers, final evidence, relevance decision, top nearest source, Ollama/Qwen status, final answer selection, and request summary).
- Each enabled terminal trace is mirrored to a request-local `.log` file under `logs/chat_assistant/` by default. Log writing is best-effort and cannot break the Chat Assistant if the folder is unavailable.
- A retrieval relevance/no-match guard prevents an unrelated nearest policy chunk from being forced into an answer. Existing out-of-company/HR scope behavior and current no-information answer categories are retained.
- Policy Q&A also applies a lightweight topic-support guard before accepting a deterministic policy match, so the same fail-closed behavior remains when Ollama is unavailable and Smart AI enhancement is skipped.
- Admin and Employee Chat UI display only one top approved policy source. Supporting chunks/sources remain visible in terminal/log diagnostics for debugging.
- The previously discussed special broad-topic coverage expansion (for example, expanding `Leave policy` into every leave-policy section) is intentionally **not** included. Short valid topics continue through the normal existing retrieval path.

Default diagnostics settings:

```text
SMART_AI_TERMINAL_DEBUG_ENABLED=true
SMART_AI_TERMINAL_DEBUG_LOG_ENABLED=true
SMART_AI_TERMINAL_DEBUG_LOG_DIR=logs/chat_assistant
```

## v8.8.220 — Compact Live Terminal + Full Forensic Log

This checkpoint is based strictly on v8.8.219 and changes only Chat Assistant
diagnostic presentation/version/tests. Retrieval ranking, relevance guard,
Qwen prompting, source selection, parsers, permissions, and HR workflows are
retained.

When the request-local evidence log is available, the **live terminal** now
shows only the information needed for fast debugging:

- user question;
- files/chunks searched and matched;
- final chunks used;
- top selected source files with file-level score, matched/total chunk count,
  and best chunk;
- up to three candidate answers with answer-fit score, retrieval score, source,
  chunk, and concise possible answer;
- final answer, top source/chunk/final score; and
- Ollama/retry/result timing plus the full-log path.

The per-request `.log` still keeps the **full forensic trace** from v8.8.219:
question analysis, all BM25/vector/hybrid stages, chunk excerpts, selected
evidence, relevance/no-match decision, router/Qwen options, top-nearest source,
runtime events, and request summary. If the log cannot be created, the terminal
automatically falls back to the verbose trace so diagnostic evidence is not
silently lost.

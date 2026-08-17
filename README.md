# AI HR Assistant

This is the base project foundation for the modular HR Assistant.

Included:
- Complete folder architecture
- Centralized settings and logging
- Reusable Streamlit UI shell
- Light and dark mode
- Placeholder pages

Not implemented yet:
- Database business logic
- Authentication
- Employee, policy, leave, request, and document workflows

## Run

```powershell
cd hr_assistant
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
streamlit run app.py
```


## Foundation v1.1 update

- Sidebar is fixed on the left side.
- Sidebar width is locked to 285px.
- Sidebar collapse controls are hidden.
- Sidebar remains visible while the main content scrolls.


## Foundation v1.2 update

- Sidebar is forced to remain expanded.
- All known Streamlit collapse-button selectors are hidden.
- The main content keeps a permanent 285px sidebar offset.
- `initial_sidebar_state` is explicitly set to `expanded`.


## Foundation v1.3

- Fixed the CSS string formatting error caused by literal percentage symbols.
- Kept the sidebar permanently expanded.
- Added broader selectors for Streamlit sidebar controls.


## Database Architecture Module

This version adds:

- SQLAlchemy 2.x database layer
- SQLite development database
- PostgreSQL-compatible database URL configuration
- Flexible SQLAlchemy adapter
- Company, role, department, user, and employee models
- Company-based data isolation
- Repository pattern
- Employee-number uniqueness per company
- Duplicate employee full names are allowed
- Database creation and verification scripts

### Create the database

```powershell
python scripts\create_database.py
python scripts\check_database.py
pytest tests\test_database.py -v
```

Authentication and seed users are intentionally not included yet.


## Initial Data and Company Isolation Module

This version adds:

- Default company seed
- Five company-scoped system roles
- Initial company administrator
- Argon2 password hashing
- Initial admin employee profile
- Idempotent initial-data script
- Company-scoped user uniqueness
- Employee-number uniqueness per company
- Duplicate employee full names are allowed
- Initial-data verification and tests

### Configure the initial administrator

Copy `.env.example` values into `.env` and change:

```text
INITIAL_COMPANY_CODE
INITIAL_COMPANY_NAME
INITIAL_ADMIN_USERNAME
INITIAL_ADMIN_EMAIL
INITIAL_ADMIN_PASSWORD
INITIAL_ADMIN_EMPLOYEE_NUMBER
INITIAL_ADMIN_FIRST_NAME
INITIAL_ADMIN_LAST_NAME
```

The initial user is forced to change the password when login is implemented.

### Run

```powershell
python scripts\create_initial_data.py
python scripts\check_initial_data.py
pytest tests\test_password_manager.py tests\test_initial_data.py -v
```

Running `create_initial_data.py` repeatedly is safe and does not create duplicate records.


## v3.1 Commented Modules

This version keeps the same v3 behavior and adds:

- Expanded module docstrings
- Inline comments for important syntax and decisions
- Clear layer and data-flow explanations
- Debugging notes
- Comments for company isolation and duplicate-name handling
- Comments for password hashing and seed idempotency
- `DEVELOPER_GUIDE.md`


## v4 Authentication and Login

Implemented:

- Company-code login
- Username or email login
- Argon2 verification
- Active account validation
- Streamlit authentication session
- Admin and employee routing
- Protected layouts
- Logout
- Mandatory temporary-password replacement
- Light and dark mode on authentication pages
- Commented modules and debugging notes

Run:

```powershell
python scripts\check_initial_data.py
python scripts\check_authentication.py
pytest tests\test_authentication.py -v
streamlit run app.py
```


## v4.1 Light Mode Widget Contrast Fix

Fixed:

- Invisible text-input and password labels in light mode
- Dark input surfaces remaining active in light mode
- Low-contrast password visibility and help icons
- Low-contrast warning text
- Default red form-submit button replaced with the shared primary color
- Theme-aware form border and background

No authentication or database behavior was changed.


## v5 User and Employee Management

Implemented:
- Company-scoped Users page
- Company-scoped Employees page
- Employee onboarding
- Optional login-account creation
- Role, department, and manager selection support
- Account activation/deactivation
- Self-deactivation protection
- Duplicate full-name support
- Admin dashboard metrics
- Commented modules and automated tests

Run:
```powershell
pytest tests\test_admin_management.py -v
streamlit run app.py
```


## v5.1 Input Text Contrast Fix

Fixed:

- Light-mode input value text contrast
- Light-mode input background for current Streamlit BaseWeb DOM
- Password and text fields using both input and base-input wrappers
- Browser autofill contrast
- Nested primary-button text color

No database, authentication, user-management, or employee-management logic changed.


## v5.2 White Input Text in All Themes

UI-only fix:

- Input values remain white in light mode.
- Input values remain white in dark mode.
- Input backgrounds remain dark in both modes.
- Password, email, username, number, and autofilled fields are covered.
- Placeholder text remains lighter than entered values.
- No authentication, database, user, or employee-management logic changed.


## v5.3 Theme Loader f-string Fix

Fixed:

- NameError caused by unescaped CSS braces inside the Python f-string.
- White input text remains active in both light and dark modes.
- No authentication, database, Users, or Employees logic changed.


## v5.4 White Input Runtime Fix

UI-only changes:

- Removed the input text-shadow that caused outlined/ghost text.
- Added explicit focus and text-selection colors.
- Forced native dark input color scheme in both application themes.
- Added a zero-height MutationObserver fallback that applies white
  text directly to rendered Streamlit input elements.
- The script changes styles only and does not read or transmit values.
- Authentication, database, Users, and Employees logic are unchanged.


## v6 Organization Setup Management

Implemented:

- Company Profile page
- Company-name update with immutable company code
- Departments page
- Department creation and status management
- Roles page
- Custom role creation and status management
- System-role protection
- Assigned-role deactivation protection
- Company-scoped validation and tests
- Commented modules and updated developer guide

Run:

```powershell
pytest tests\test_organization_management.py -v
streamlit run app.py
```


## v6.1 Persistent Theme Selection

The selected theme remains active after form submissions, widget reruns,
browser refresh, logout/login, and new Streamlit sessions in the same
browser. Persistence uses session state, the URL theme parameter, and
browser localStorage.


## v6.6 Simple Default-Account Password Reset

This checkpoint removes the persistent browser authentication-token
experiment and returns to the simpler Streamlit session-state login flow.

Behavior:

1. A newly seeded default administrator starts with
   `must_change_password=True`.
2. After successful login, the password-change page opens immediately.
3. Admin and employee portals remain blocked until the password changes.
4. After a successful change, the flag becomes `False`.
5. Later logins proceed normally.
6. The seed does not force another reset for an existing account.

For an existing default administrator, require another reset with:

```powershell
python scripts\require_default_password_reset.py
python scripts\check_default_password_reset.py
```

The old `auth_sessions` table may remain in an existing SQLite database.
This simplified checkpoint does not use it.


## v6.7 Signed-Cookie Refresh Login

A full browser refresh now restores authentication without returning the
user to the login form.

Implementation:

- Streamlit session_state handles ordinary widget reruns.
- `st.context.cookies` reads the signed cookie synchronously on refresh.
- `streamlit-cookies-controller` writes and removes the cookie only during
  login, password change, and logout.
- `itsdangerous` signs and timestamps the cookie.
- No `auth_sessions` database table or migration is used.
- Password changes invalidate old cookies automatically.
- Inactive users, companies, or roles cannot restore authentication.
- The last employee/admin portal and page are stored in URL navigation
  parameters and restored only after authorization checks.

Production environment:

```env
AUTH_COOKIE_SECRET=replace-with-a-long-random-secret
AUTH_COOKIE_HOURS=12
AUTH_COOKIE_SECURE=true
```

For local `http://localhost`, keep `AUTH_COOKIE_SECURE=false`.


## v6.8 All Form Widget Contrast Fix

The login page text inputs were already forced to use a dark surface and
white value text in both themes. Employee and organization forms also use
date and select widgets, which required separate Streamlit/BaseWeb
selectors.

Fixed widgets:

- Text and password inputs
- Number inputs
- Date and time inputs
- Text areas
- Selectboxes and multiselects
- Dropdown option menus
- Date calendar popover

All listed widgets now use a consistent dark input surface with white value
text in both light and dark application modes.


## v6.9 Selectbox Value Contrast Fix

The date input was already fixed, but selectbox values such as
`No Department` and `No Manager` were still rendered using a nested
BaseWeb combobox element.

The theme now targets `data-baseweb="select"` directly and forces the
selected value, placeholder, combobox input, arrow, and dropdown options
to use white text on the shared dark input surface in both themes.


## v7.0 Refresh Login and Universal Form Contrast

Refresh login:

- The signed cookie is written first.
- The browser performs a real reload only after a short commit delay.
- Streamlit restores the user from the cookie on the next request.
- No auth-session database table or migration is used.
- Logout removes the cookie before returning to login.
- Password change replaces the signed cookie.

Universal form contrast:

- Text and password inputs
- Number inputs
- Date and time inputs
- Text areas
- Disabled values
- Selectbox and multiselect values
- Dropdown options
- Browser autofill

All listed controls use white values on the shared dark input surface in
both light and dark modes.


## v7.1 Employee-Only Flow Validation

A dedicated employee-only account flow is now tested.

Create a local sample employee:

```powershell
python scripts\create_sample_employee_account.py
python scripts\check_sample_employee_account.py
```

First-run test credentials:

```text
Company code: value of INITIAL_COMPANY_CODE
Username: employee.test
Temporary password: Employee123!
```

Expected behavior:

- Mandatory password change opens after first login.
- After changing the password, Employee Portal opens.
- No Admin Portal button is shown.
- Direct admin URL/query changes are redirected to Employee Portal.
- Admin layout independently rejects employee access.
- Browser refresh restores the employee role without elevating access.
- Admin and employee accounts remain separate database records.

The sample-account script is idempotent and does not reset an existing
employee password.


## v7.2 Login and Logout Transition Fix

Resolved:

- Login no longer remains indefinitely on `Completing sign in…`.
- Logout no longer leaves only the protected sidebar visible.
- The cookie component writes/removes the browser cookie first.
- A native one-second Streamlit fragment timer then reruns the full app.
- No sandboxed iframe top-level navigation is attempted.
- A logout-pending state blocks stale request-cookie restoration during the
  same Streamlit WebSocket session.

Expected:

```text
Sign In
→ Completing sign in…
→ Dashboard / Employee Portal

Log Out
→ Signing out…
→ Login page
```


## v8.0 HR Policy Q&A

Implemented:

- Company-scoped `hr_policies` table
- Draft, published, and archived policy statuses
- Versioned policy records
- Effective-date filtering
- Protected administrator Policies page
- Employee Company Policies browser
- Functional employee Policy Q&A chat
- Generic section and keyword matching
- Approved-policy source references
- Exact fallback:
  `Information not found in approved company policies.`
- Draft, archived, future-effective, and other-company policies are excluded
- Runtime creation of the missing `hr_policies` table
- Sample policy seed script

Local test setup:

```powershell
python scripts\create_sample_policies.py
streamlit run app.py
```

This module intentionally does not use a generative LLM or external
knowledge. Full document ingestion and advanced RAG remain future modules.


## v8.1 File-Based Policy Management

Policy source of truth is now the uploaded file.

Supported files:

- PDF
- DOCX
- TXT
- Markdown

Upload flow:

```text
Admin uploads policy file
→ file validation and SHA-256 calculation
→ private company-scoped storage
→ text and section extraction
→ draft or published policy record
→ employee Policy Q&A
→ direct answer with filename, section, and PDF page when available
```

Security and correctness:

- Maximum upload size is configurable.
- Unsupported file types are rejected.
- Filenames are sanitized before storage.
- Relative paths are checked against path traversal.
- Exact duplicate files are blocked within the same company.
- Draft, archived, future-effective, and other-company files are excluded.
- Employees download files only after company and publication checks.
- Scanned image-only PDFs are rejected because OCR is not enabled yet.
- Existing v8.0 manual policies remain readable for backward compatibility.

Configuration:

```env
POLICY_UPLOAD_DIR=data/uploads/policies
POLICY_UPLOAD_MAX_MB=10
```

Local sample:

```powershell
python scripts\create_sample_policies.py
```


## v8.2 Admin Policy Content Viewer

Administrators can now select an existing policy and inspect:

- Policy status, version, category, effective date, and summary
- Original filename, MIME type, file size, page count, and SHA-256
- Extracted policy content stored in the database
- The exact searchable sections used by Policy Q&A
- Optional PDF page number for each searchable section
- Original uploaded file download
- Complete extracted-text download
- Section heading/content search
- Publication-status management

Large extracted documents show the first 100,000 characters in the browser
and provide a complete plain-text download.

All content-view operations validate `company_id` through `PolicyService`.
Older v8.0 manual policy entries remain viewable.


## v8.2.1 Employee Onboarding Polish

The normal administrator Add Employee form now:

- Shows Role, Username, Login Email, and Temporary Password at all times
- Removes the optional login-account checkbox
- Creates the employee profile and linked login account together
- Defaults the role selector to `employee`
- Warns before assigning an elevated administrator role
- Requires a password change on first login
- Shows clear missing-field messages

The backend retains profile-only employee support for future imports,
integrations, and record-only workflows. It is not exposed in the standard
administrator onboarding form.


## v8.2.2 Secure Forgot Password

Self-service flow:

```text
Forgot Password
  ↓
Company Code + registered Login Email
  ↓
single-use reset link
  ↓
new password + confirmation
  ↓
old signed login cookies become invalid
```

Security:

- Existing passwords are never decrypted, displayed, or emailed.
- Database stores only a SHA-256 reset-token hash.
- Reset tokens expire after 30 minutes by default.
- Reset tokens are single-use.
- New reset requests revoke older active links.
- A per-account cooldown limits repeated emails.
- Public responses are generic to prevent account enumeration.
- Password changes invalidate signed-cookie password fingerprints.
- Open authenticated sessions are revalidated on the next Streamlit run.
- Company code and Login Email preserve tenant isolation.

Email modes:

```env
EMAIL_DELIVERY_MODE=local
```

Local development writes `.eml` files to:

```text
data/dev_mail_outbox
```

Read the latest local message with:

```powershell
python scripts\show_latest_password_reset_email.py
```

Production SMTP example:

```env
EMAIL_DELIVERY_MODE=smtp
PASSWORD_RESET_BASE_URL=https://hr.example.com
SMTP_HOST=smtp.office365.com
SMTP_PORT=587
SMTP_USERNAME=hr-system@example.com
SMTP_PASSWORD=your-app-password-or-smtp-password
SMTP_FROM_EMAIL=hr-system@example.com
SMTP_FROM_NAME=Company HR
SMTP_USE_STARTTLS=true
SMTP_USE_SSL=false
```

The `Users` administration page also includes an administrator-assisted
temporary-password reset for employees who cannot access their registered
Login Email. The employee must change that temporary password on next login.


## v8.2.3 Real SMTP Email Delivery

Forgot Password can now use real internet email through the configured SMTP
provider.

Configure SMTP interactively:

```powershell
python scripts\configure_smtp.py
```

The setup supports:

- Gmail / Google Workspace preset
- Microsoft 365 preset
- Custom SMTP host, port, and encryption

The private `.env` file receives the sender credentials. Existing values
are preserved and an `.env.backup` is created before updating an existing
file. The password is not printed by the setup script.

After configuration:

```powershell
Ctrl + C
streamlit cache clear
streamlit run app.py
```

Then open:

```text
Admin Portal → Integrations
```

The page safely displays:

- Delivery mode
- SMTP host and port
- Encryption
- Whether a username is configured
- Sender name/email
- Password-reset public URL

The SMTP password is never returned to the UI.

Use **Send Internet Test Email** before testing Forgot Password. A successful
test confirms that the app can reach the SMTP provider and authenticate with
the configured sender account.

Command-line test:

```powershell
python scripts\test_smtp_email.py recipient@example.com
```

The public Forgot Password page no longer displays local outbox paths or
development implementation details.


## v8.2.4 Email-Only Forgot Password

The employee Forgot Password form now asks for only:

```text
Registered Login Email
```

It no longer asks for Company Code.

Flow:

```text
Registered Login Email
  ↓
system finds active matching accounts
  ↓
single-use reset email
  ↓
new password
  ↓
sign in using the new password
```

Multi-company handling:

- Login Email remains company-scoped in normal account management.
- The same email may exist in more than one company.
- When that happens, each active matching account receives a separate email.
- Every message identifies the company and contains a token bound to only
  that company and user account.
- The public screen still returns the same generic response and does not
  reveal the number of matching accounts.

The SMTP provider remains a one-time private backend configuration. The
employee does not choose Gmail, Microsoft 365, a sender username, password,
or display name.


## v8.2.6 Employees Workspace Consolidation

The previous separate sidebar pages:

- Users
- Employees
- Roles

are now consolidated under one **Employees** navigation item.

Workspace tabs:

```text
Employees
  ├─ Employee Records
  ├─ User Accounts
  └─ Roles & Access
```

Responsibilities:

- **Employee Records** — employee list, onboarding, department/manager
  assignment, and linked account creation
- **User Accounts** — activation/deactivation and administrator-assisted
  temporary-password reset
- **Roles & Access** — system/custom role list, custom role creation, and
  custom-role activation status

Old bookmarks or query parameters for `Users` and `Roles` still open the
Employees workspace instead of failing.


## v8.3.0 Employee Master Record

The previous Employees workspace has been simplified to:

```text
Employees
  ├─ Employee List
  ├─ Add Employee
  └─ Edit Employee
```

Removed from the administrator UI:

- User Accounts tab
- Roles & Access tab
- Custom role assignment

Each employee record now contains:

```text
Employee Number
Last Name
First Name
Middle Name (optional)
Suffix (optional)
Job Title / Position
Department
Manager
Email
Status: Employed or Resigned
Training checklist
Account:
  User ID
  User Name
  Password reset field
  Clearance: 1 Admin or 2 User
```

Important security behavior:

- Actual passwords are never displayed or stored as plain text.
- The database stores only the Argon2 password hash.
- Editing the password uses a blank **New Temporary Password** field.
- A new temporary password forces password change during next login.
- Resigned employees remain in the database but their login account becomes
  inactive.
- Full Name is calculated from the separate name fields.
- Each training item is a separate database row, but the employee table
  displays the checklist in one combined cell.

Existing databases are upgraded automatically:

- Adds `users.clearance`
- Maps old administrator roles to clearance 1
- Maps other roles to clearance 2
- Converts active status to Employed
- Creates `employee_trainings`


## v8.3.1 Wrapped Employee Table

The Employee List no longer uses the default Streamlit dataframe renderer.

Every table cell now supports:

- automatic text wrapping
- preserved multiline Training checklist
- preserved multiline Account details
- top-aligned content
- long-email and long-word breaking
- sticky table header
- horizontal scrolling on smaller displays

Dynamic employee values are HTML-escaped before rendering.


## v8.3.2 Employment and Account Status Sync

```text
Employed -> Account Active
Resigned -> Account Inactive
```

The rule works in both directions. Returning a resigned employee to
Employed automatically reactivates the linked login account. Resigned
employee records remain stored for historical reference.


## v8.3.3 Consistent Administration Tables

The default Streamlit dataframe grid was replaced on administration pages
because its internal theme could remain dark while the surrounding app was
in Light Mode.

Updated tables:

- Employees
- Policies
- Policy details and original-file details
- Departments
- Integrations
- Legacy Users and Roles pages

All tables now provide:

- correct Light/Dark theme colors
- wrapped text in every cell
- multiline content support
- sticky headers
- horizontal scrolling on smaller screens
- HTML-escaped dynamic values
- CSS scoped to each table only


## v8.3.4 Department Entry Through Employees

The separate Departments sidebar item and active route have been removed.

```text
Employees
  ├─ Add Employee -> Department
  └─ Edit Employee -> Department
```

Existing department names are reused case-insensitively. New department names
create normalized database records automatically. The Department model,
table, repository, and employee relationship remain for filtering, reports,
and future integrations. Old Departments bookmarks redirect to Employees.


## v8.3.5 Safe Employee Delete

A permanent-delete option is available under:

```text
Employees -> Edit Employee -> Danger Zone
```

The admin must type the exact Employee Number and acknowledge the permanent
action. The signed-in administrator cannot delete their own account.
Employees referenced by policy history cannot be deleted and should be set
to Resigned instead.

Deletion removes the employee profile, training records, linked login
account, and password-reset tokens. Department records and direct-report
employees remain. Direct reports are changed to No Manager.


## v8.3.6 Employee Operation Feedback

Employee operations now show a visible loading indicator:

```text
Add Employee    -> Creating employee record and login account…
Edit Employee   -> Saving employee changes…
Delete Employee -> Permanently deleting employee record…
```

After completion, the result is stored in Streamlit session state before
`st.rerun()`. The refreshed Employees page displays both:

- a persistent success banner
- a short success toast

Validation and database errors remain visible in the active form and do not
show a false success message.


## v8.3.7 Hover Style Restore

Hover styling is restored without changing employee business logic.

Updated:

- normal and sidebar buttons
- primary/form-submit buttons
- page tabs
- expanders, including the Delete Danger Zone
- Employees table rows
- reusable administration table rows

The hover uses the shared `primary_soft` token, so Light Mode receives a
soft blue-violet background and Dark Mode receives the matching dark accent.
No transform, movement, or layout shift is applied.


## v8.3.10 Light Mode Only

The application now uses one fixed Light Mode and no theme selector.

Light form controls:

- white input/select/textarea background
- dark readable values
- muted gray placeholder text
- soft gray-blue hover border
- violet focus border
- white dropdown/calendar surfaces
- soft blue-violet option hover

Preserved from v8.3.7:

- sidebar and page layout
- wrapped administration tables
- button, tab, expander, and row hover behavior
- employee add/edit/delete behavior
- loading indicators
- success banners and toasts
- authentication and database logic

No native `.streamlit/config.toml` override was introduced.


## v8.3.11 Light Mode Text Contrast Fix

Text color now follows the actual UI surface:

```text
White/light surface       -> dark text
Violet/primary surface    -> white text
Soft-violet hover surface -> violet text
Disabled light field      -> readable muted text
```

The patch also forces Streamlit/BaseWeb input and select wrappers to remain
white whenever their value text is dark. This prevents black text from
appearing on a retained dark native control background.

No employee, authentication, loading, database, table-layout, or navigation
logic was changed.


## v8.3.12 Light Page with Dark Inputs

The page remains Light Mode while editable controls use the approved dark
surface.

```text
Page/cards/sidebar  -> Light
Input box           -> Dark (#252630)
Typed value         -> White
Placeholder         -> Muted light gray
Input hover         -> Slightly lighter dark
Input focus         -> Violet border
Dropdown            -> Dark with white text
```

Labels remain dark because they are outside the input and displayed on the
light page. No employee, authentication, loading, table, or database logic
was changed.


## v8.3.13 Native Control Hover

Added scoped hover styling for Streamlit controls that do not inherit the
normal button/input hover rules:

- file-uploader dropzone
- Upload/Browse button
- uploaded-file row
- remove-file button
- checkbox label and indicator

The page remains Light Mode while form controls remain dark with white text.
No policy upload logic, employee logic, database logic, or layout changed.


## v8.3.14 Tooltip Contrast Fix

Streamlit help tooltips now use:

```text
Tooltip surface -> dark
Tooltip text    -> white
Tooltip icon    -> readable gray
Icon hover      -> soft violet
```

CSS and a small MutationObserver fallback both cover tooltips created after
the initial Streamlit render. Existing file-uploader hover, Light Mode page,
dark controls, white input values, and application logic are unchanged.


## v8.3.15 Download Action Contrast

The three active download actions now have explicit states:

```text
Normal   -> white surface, dark text
Hover    -> violet surface, white text
Focus    -> violet surface, white text, focus ring
Active   -> darker violet
Disabled -> light gray surface, readable muted text
```

The visual audit also rechecked ordinary buttons, form-submit buttons,
file uploaders, tooltips, checkboxes, inputs, tabs, and tables. No policy,
employee, authentication, or database logic changed.


## v8.4.0 Policy Library Redesign

- User-facing IDs use `PID_001` format.
- The active table shows Filename/Title, Category, Version, File Size, and Date Uploaded.
- Filename-derived title and heading-derived category suggestions are automatic.
- Category remains editable and is used for filtering and Q&A organization.
- Version stays manual while previous versions remain visible.
- Upload preview is integrated into the upload section.
- Every successful upload is immediately published.
- Policies can be moved to a reversible Bin and restored; no permanent delete exists.
- Both filename auto-detection and explicit existing-policy selection link new versions.


## v8.4.1 Expander Contrast Fix

The Document Preview header is now readable before hover.

```text
Normal   -> white surface, dark text
Hover    -> soft violet surface, violet text
Focused  -> soft violet surface, visible focus treatment
Expanded -> pale violet surface, violet text
Arrow    -> readable gray/violet
```

The same styling applies consistently to other Streamlit expanders.
Policy preview content, upload processing, version linking, Bin behavior,
employee logic, authentication, and database logic are unchanged.


## v8.4.2 Toast Contrast Fix

Success toasts now use a complete dark-surface contrast system:

```text
Toast surface -> dark
Message text  -> white
Success icon  -> bright green
Close icon    -> light gray
Toast hover   -> slightly lighter dark
```

CSS and the existing MutationObserver runtime fallback cover notifications
created after a Streamlit rerun. The page success banner, policy Bin action,
upload flow, tables, employee features, authentication, and database logic
are unchanged.


## v8.4.3 Policy Upload Reset

After a successful policy upload, the entire upload workspace resets:

```text
successful database/file transaction
  ↓
advance upload-widget generation
  ↓
Streamlit rerun
  ↓
empty file uploader
  ↓
title/category/version/preview/history controls hidden
```

The reset covers:

- selected policy file
- version-linking choice
- selected existing policy
- suggested/edited category
- manual version value
- previous-version table
- extracted document preview
- upload submit state

Validation, parsing, duplicate-version, or database errors do not reset the
form, allowing the administrator to correct the current upload. The success
banner and toast remain visible after the rerun.


## v8.4.4 Policy Edit, New Version, and Permanent Delete

### Manage Existing Policy

New actions:

```text
Edit Details
Upload New Version
Move to Bin
```

- Policy Title and Category are applied to all versions in the same policy
  family so version history remains grouped.
- Version changes only the selected record.
- Editing metadata never overwrites the original uploaded file or extracted
  content.
- Upload New Version creates a separate published record and preserves all
  earlier active or Bin versions.

### Bin

New protected action:

```text
Delete Permanently
```

The administrator must type the exact Policy ID and acknowledge permanent
deletion. The operation removes only the selected Bin version:

- policy database row
- original stored file
- uploaded-document metadata
- extracted full text
- searchable sections

Other versions of the same policy remain available. Active policies cannot
be permanently deleted; they must be moved to the Bin first.


## v8.4.5 Policy Content Edit and Readable Preview

### Edit Details

The selected version now includes editable Policy Content. Saving it updates:

- policy database content
- extracted-content viewer
- generated summary
- stored extracted text
- searchable sections used by Policy Q&A

The original uploaded file, hash, filename, and storage path remain unchanged.
Regenerated sections no longer retain page numbers because edited content may
not match the original source pages exactly.

### Upload Preview

Detected headings are displayed as a wrapped vertical numbered list.

Extracted content is displayed in a section-by-section stacked preview:

```text
1. Section Heading
────────────────────────────────
Section content

2. Next Heading
────────────────────────────────
Next section content
```

The layout is shared by the main Upload Policy flow and Upload New Version.


## v8.4.6 Full Policy Content View

Policy content is no longer limited in the administrator interface.

### Edit Details

- The complete editable content is loaded.
- Editor height expands according to all content lines.
- No internal fixed-height content limit is used.
- Line height is reduced to `1.30` for a compact but readable layout.

### Upload and New-Version Preview

- Every unique detected heading is displayed.
- The `+ more detected sections` message is removed.
- Every extracted section and its full text are displayed.
- Character and section preview limits are removed.
- Section gaps and list spacing are reduced.
- The complete preview remains inside the collapsible Document Preview area.

No policy extraction, save, versioning, Bin, employee, authentication, or
database behavior changed.


## v8.4.7 Policy Section Heading and Content Layout

Each preview section now follows:

```text
────────────────────────────────
Topic / Heading
Content
────────────────────────────────
Next Topic / Heading
Content
────────────────────────────────
```

The separator is no longer between a heading and its own content. Heading
and body are rendered inside one scoped HTML section.

Source text is escaped and newlines are converted to explicit HTML breaks,
preventing the last part of long documents from leaving the dark preview
surface and inheriting black Light Mode text. All nested heading and body
text is forced to white.

The complete unlimited preview remains enabled.


## v8.5.0 Leave Management

### Administration Portal

The former **Leave Settings** navigation item is now **Leave Management**.
It contains:

- Leave Overview
- Leave Credits per employee
- Manual credit adjustments and credit history
- Leave Requests for monitoring and View Details only
- Leave Types & Rules

There are no Admin approve, reject, or cancel actions. Requests are sent to
the employee's assigned department manager. The employee and active company
administrators are copied on the email.

### Employee Portal

Employees can:

- review annual, carried, adjusted, used, reserved, and remaining credits
- submit Vacation, Sick, Emergency, or configured leave requests
- attach PDF, DOCX, PNG, JPG, or JPEG supporting documents
- see their sent request history

Submitting a request reserves available credits, records the request, creates
in-app notifications, and sends an email to the assigned manager. Approval is
handled through the department process outside the HR Admin portal.

### Notification Bell

The authenticated top bar now includes a bell with unread count, recent
notifications, and a **Mark All as Read** action.

New database tables are created automatically and non-destructively:

- `leave_types`
- `leave_balances`
- `leave_credit_transactions`
- `leave_requests`
- `notifications`


## v8.5.1 Company Theme Color

Company Profile now includes a company-wide Primary Accent Color picker.

```text
Default color       -> violet (#4338E8)
Selected color      -> stored per company
Primary buttons     -> selected color
Hover state         -> automatically derived
Soft accent         -> automatically derived
Text on accent      -> automatically black or white for contrast
```

The saved color is used in both Administration and Employee portals for:

- active sidebar navigation
- primary and submit buttons
- tab accents
- focus borders and rings
- checkbox and selection states
- notification bell hover
- uploader and download actions
- branding and soft hover surfaces

The color is stored in `companies.theme_primary_color`. Existing databases
receive the column non-destructively and keep the default violet color.

Company Profile provides:

- live Primary, Hover, and Soft Accent preview
- Save Theme Color
- Reset to Default Violet

Light Mode remains fixed. Dark input surfaces, white input values, Leave
Management, policy features, authentication, and business logic are
unchanged.


## v8.5.2 Leave Detached-Instance Fix

Leave Management repository queries now eagerly load every relationship used
after the database session closes.

Covered relationships:

- Leave Balance → Employee
- Leave Balance → Employee Department
- Leave Balance → Employee Manager
- Leave Balance → Employee/Manager User Account
- Leave Balance → Leave Type
- Leave Request → Employee Department
- Leave Request → Employee/Manager User Account
- Leave Request → Leave Type

This prevents SQLAlchemy `DetachedInstanceError` when Streamlit renders leave
credits or request details after leaving the `SessionFactory()` context.

No database migration is required. Leave calculations, email routing,
notifications, company theme colors, policies, authentication, and employee
records are unchanged.


## v8.5.3 Leave Workspace Reorganization

The administrator Leave Management workspace is reorganized into:

```text
Leave Overview
Credit Management
Leave Requests
Leave Types & Rules
```

### Shared Leave Year

The Leave Year selector is displayed once above the tabs and controls:

- Leave Overview balances and metrics
- Credit Management adjustments and history
- Leave Requests whose leave dates overlap the selected year

Requests crossing December and January appear in both affected leave years.

### Leave Overview

Read-only information is consolidated here:

- selected-year summary metrics
- employee leave-credit table
- View Employee Credit Details
- allocated, carry-over, adjustments, used, reserved, and remaining credits

### Credit Management

Only administrative credit actions are shown here:

- employee selector
- manual positive or negative credit adjustment
- required adjustment reason
- immutable credit transaction history

The old `Leave Credits` tab name is removed to avoid duplicating viewing and
management functions.

Manager-routed request approval remains outside the HR Admin portal. Company
theme colors, notifications, policies, authentication, email routing, and
database records remain unchanged.


## v8.5.4 Simplified Leave Management

The administrator workspace is simplified into four clear areas:

```text
Overview
Employee Leave Accounts
Leave Requests
Leave Rules
```

### Overview

Overview is now a true monitoring dashboard and does not repeat the complete
employee credit table or adjustment forms.

It contains:

- selected-year request metrics
- employees currently on leave
- selected-year leave activity
- low-credit alerts
- recent leave requests

### Employee Leave Accounts

All employee-specific credit work is consolidated in one place:

- department filter
- employee selector
- available, used, and reserved totals
- complete leave-type credit breakdown
- manual positive or negative adjustment
- immutable transaction history

This removes the previous separation between credit viewing and credit
management.

### Leave Requests

Requests remain view-only for HR/Admin and include:

- department filter
- leave-type filter
- status filter
- employee-name or employee-number search
- request table
- complete request details and attachment download

Department managers remain responsible for approving or rejecting requests
outside the HR Admin portal.

### Leave Rules

Leave type configuration is renamed and simplified:

- Add Leave Rule
- Edit Leave Rule
- Save Leave Rule
- annual credits
- paid/unpaid
- carry-over limit
- attachment requirement
- minimum notice
- active/inactive

One shared Leave Year continues to control Overview, Employee Leave Accounts,
and Leave Requests. No database migration is required.


## v8.5.5 Absolute Leave Credits

Employee Leave Accounts no longer uses positive or negative adjustment
numbers.

The administrator now enters the exact remaining credits:

```text
Current credits: 45
New Leave Credits: 10
Saved result: 10
```

The value is not added to the current balance.

### Updated interface

- `Adjust Credits` is renamed to `Set Leave Credits`
- `Adjustment Days` is replaced by `New Leave Credits`
- minimum input value is zero
- the current balance is the default input value
- `Save Leave Credits` clearly saves the exact resulting amount
- the help text includes a 45-to-10 example
- internal signed adjustment arithmetic is hidden from the employee balance
  table
- transaction history records the previous and new balance plus the reason

The service recalculates its internal adjustment component while preserving
annual allocation, carry-over, used days, reserved days, and leave-request
history. No database migration is required.


## v8.5.6 Remove Leave-Credit Reason

The manual reason field is removed from Employee Leave Accounts.

The `Set Leave Credits` form now contains only:

```text
Leave Type
Current Credits
New Leave Credits
Save Leave Credits
```

Transaction history still records:

- previous balance
- new balance
- administrator user reference
- date and time of the change

No user-entered adjustment reason is requested or displayed. No database
migration is required.


## v8.6.0 Manager Approval and Leave Credit Posting

### Employee Portal

Leave Management now contains:

```text
My Leave Overview
File Leave Request
My Requests
Pending Approvals       # assigned managers only
Reviewed Requests       # assigned managers only
```

The request composer shows:

- Leave Type and current available credits
- Start Date and End Date
- calculated Monday-to-Friday Working Days
- Reason
- Work Handover Plan / Countermeasure
- optional PDF, DOCX, XLSX, CSV, or TXT plan file
- automatic To: assigned manager
- automatic CC: employee and active administrators

### Handover Plan Rules

Leave Rules supports:

```text
Optional
Recommended
Required
```

A Required rule accepts either plan text or an uploaded plan file. Vacation
and Leave Without Pay default to Recommended. Sick and Emergency default to
Optional because they may be unexpected.

### Manager Approval

The assigned manager receives:

- an in-app bell notification
- an email containing the request and handover plan
- a login-protected link to Employee Portal Leave Management

Managers can approve or reject only requests assigned to their employee
record. HR/Admin remains view-only.

### Credit Lifecycle

```text
Pending Manager Approval
    No reservation and no deduction

Approved / Scheduled
    Requested days become Reserved
    Available Credits decreases

Approved leave date occurs
    Date reconciliation moves elapsed days from Reserved to Used

All approved leave dates completed
    Status becomes Completed
```

Rejected requests never affect credits.

### Date Reconciliation

Two safeguards are included:

1. Streamlit runs reconciliation whenever an authenticated user opens the app.
2. `python scripts/reconcile_leave_credits.py` can be scheduled daily through
   Windows Task Scheduler.

Posting is idempotent. A date already posted cannot be posted twice.

### Compatibility

Existing v8.5.x `sent_to_manager` requests are converted to Pending Manager
Approval during the non-destructive schema upgrade. Their old submission-time
reservations are released. No database reset is required.


## v8.6.1 Global Notification UI

The top-bar bell is a global notification center, not a leave-only feature.

### Readability

The popover now uses:

- a fixed white notification surface
- dark high-contrast heading, title, message, and timestamp text
- compact notification cards
- unread soft-accent background and dot
- a readable empty state
- a clear unread count
- a compact bell button
- responsive width and scrollable recent-notification list

### Generic categories

The UI automatically labels notification events as:

```text
Leave
Policy
Training
Employee
Security
System
General
```

The notification model and service remain generic and company/user scoped.
Leave is currently the first fully connected workflow. Policy, training,
employee/account, security, and other modules can publish events through the
same `NotificationService.create(...)` method as those workflows are wired.

No database migration is required.


## v8.6.2 Notification Trigger and Render Fix

This UI patch fixes three notification-center problems:

1. The bell no longer changes to an unreadable black or mismatched state.
2. The bell and arrow remain visible during normal, hover, focus, click, and
   open states.
3. `Mark All as Read` no longer exposes raw HTML tags.

### Bell states

```text
Normal
White surface
Dark visible bell and arrow

Hover / Focus / Open
Soft company accent surface
Dark visible bell and arrow
Company accent border
```

### Notification rendering

All recent notification cards are joined into one contiguous HTML block before
being passed to Streamlit. This prevents Markdown from interpreting indented
HTML as a code block during the read-state rerun.

The notification center remains system-wide. No database migration is
required.


## v8.6.3 Public Company Branding

The saved company Primary Accent Color now applies before and after login.

### Covered pages

```text
Login
Forgot Password
Reset Password
Mandatory First Password Change
Administration Portal
Employee Portal
```

### Login behavior

- The Company Code field is outside the credential form so it can refresh
  public branding without submitting a username or password.
- Entering a valid company code updates the login accent and preserves the
  code in the browser URL/session.
- A single-company installation automatically uses its saved company color.
- A multi-company installation uses the matched company code.
- Logout preserves the current company code so the user returns to the same
  branded login page.

### Password reset

Reset links now include the company code. A valid reset token can also resolve
its company directly, so the Reset Password page uses the correct company
name and accent even when opened in a new browser.

The Forgot Password form remains email-only and does not ask for company code.

No database migration is required.


## v8.7.0 Announcements and Employee Dashboard

### Admin Portal — Announcements

Administrators can publish proper company communications with:

```text
Announcement Title
Category
Short Summary
Full Announcement
Optional Cover Image
Publish Date
Optional Expiry Date
Pin on Employee Dashboard
Save as Draft
Publish / Schedule
```

Supported categories:

```text
Company Announcement
Company Activity
Event
Reminder
HR Update
Policy Update
Emergency Notice
```

Cover images support JPG, JPEG, PNG, and WEBP up to the configured
`ANNOUNCEMENT_UPLOAD_MAX_MB` limit.

The module includes:

- lifecycle metrics
- complete announcement table
- employee-view preview
- draft creation
- scheduled publishing
- editing and image replacement
- archive and restore-to-draft
- pinned announcements
- automatic employee notifications

### Employee Portal — Dashboard First

`Dashboard` is now the first employee navigation item and the default page
after employee login or when an administrator switches to Employee Portal.

The dashboard contains:

- featured pinned announcement
- latest company updates
- recent company activities and notices
- full announcement expanders
- View All Company Announcements
- quick access to Leave Management, Company Policies, and HR Assistant

A searchable `Company Announcements` page provides the complete active archive.

### Dissemination

When a post becomes active, every active company user except the publishing
administrator receives an in-app global notification. Scheduled announcements
are reconciled whenever the app opens and through:

```powershell
python scripts/reconcile_announcements.py
```

Expired posts automatically disappear from the Employee Portal while
remaining available to administrators.

### Storage and database

Announcement images are stored privately under:

```text
data/uploads/announcements/
```

The new announcement table is created automatically without resetting the
existing database.


## v8.7.1 Notification Theme Contrast

The notification bell and unread number now follow the saved company Primary
Accent Color in normal, hover, focus, active, and open states. The text color
uses the automatically calculated `--hr-on-primary` contrast value, so light
company colors use dark text and dark company colors use white text. The unread
count inside the notification panel follows the same branding. No database
migration is required.


## v8.7.2 Notification Unread Company Theme

The notification button now has two deliberate visual states:

```text
No unread notification
- white button
- company-color bell and arrow
- subtle company-color border

Unread notification
- full company primary-color button
- automatic accessible black/white icon and count
- visible focus ring
```

The button renders an explicit unread/empty state marker so CSS does not need
to guess from the visible label. This also supports Streamlit DOM variants
through a fallback selector.

The company theme applies to the normal, hover, focus, active, and open states.
No database migration is required.


## v8.7.3 Notification Direct Company Theme

The notification button is now placed inside a keyed Streamlit container:

```text
notification_bell_container
```

This gives the theme a stable selector and avoids relying on Streamlit's
changing sibling/wrapper structure.

The notification button now always uses:

```text
Background: Company Primary Accent Color
Bell / Unread Number / Arrow: Automatic Accessible Contrast
Hover / Focus / Open: Company-color responsive state
```

This applies whether the unread count is zero or greater than zero. The
button no longer falls back to the dark form-control color.

No database migration is required.


## v8.7.4 Notification Default Visibility

The notification button is readable before hover:

```text
Default
- white background
- company-color bell
- company-color unread number
- company-color arrow

Hover / Focus / Open
- soft company-color background
- bell, unread number, and arrow remain visible
```

A browser-side MutationObserver locates the actual Streamlit popover button by
its bell label and reapplies inline `!important` styles after every rerender.
This prevents later dark BaseWeb button styles from hiding the unread count.

No database migration is required.


## v8.7.5 Notification, Announcement Archive, and Merged Dashboard

### Notification

The notification indicator no longer uses `st.popover`.

```text
Default state
- company primary-color button
- visible bell
- visible unread count, including zero
- no hover required

Click
- opens a Notifications dialog
- recent notification cards
- Mark All as Read
```

### Announcement Delete

`Delete Announcement` is a soft-delete action:

```text
Delete Announcement
→ Status becomes Archived
→ Removed from Employee Dashboard
→ Record and image remain stored
→ Can be restored as Draft
```

The Admin Portal includes a dedicated Archive tab.

### Employee Portal

Dashboard and Company Announcements are merged into one page.

```text
Main wide area
- category filter
- announcement search
- featured pinned announcements
- latest active announcements

Compact right column
- Leave Management
- Company Policies
- HR Assistant
```

The separate Company Announcements sidebar item is removed. Old saved URLs are
automatically rendered through Dashboard.

No database migration is required.


## v8.7.6 Notification Dropdown and Responsive Announcement Images

### Notification location

The notification center is no longer a centered dialog.

```text
Click company-colored bell
→ Dropdown appears directly below the bell
→ Recent notifications
→ Mark All as Read
→ Close
```

The unread count remains visible in the default state.

### Announcement images

Admin and Employee announcement images now use a shared aspect-ratio-safe
renderer.

```text
- never stretched
- never distorted
- never enlarged beyond the original size
- automatically reduced to fit maximum width and height
- EXIF orientation corrected
- centered inside the available announcement area
```

Large, wide, tall, and small uploaded images retain their natural proportions.

No database migration is required.


## v8.7.7 Clickable Notifications and Title-First Announcements

### Announcement layout

The announcement information now appears before the image:

```text
Category and publish date
Announcement title
Short summary
Pinned status
Responsive image
Full announcement
```

This applies to Admin previews and the Employee Dashboard. Images continue to
preserve their natural aspect ratio without stretching.

### Wider notification dropdown

The panel is now up to 460 pixels wide and is positioned beneath the bell using
the bell button's actual browser coordinates. Text wraps normally instead of
collapsing into a narrow vertical column.

### Clickable notifications

Every recent notification is a clickable card. Opening one:

```text
- marks that notification as read
- closes the dropdown
- navigates to the related module
- preserves the related entity ID in the URL when available
```

Routing includes Announcements, Leave Management, Policies, Employees,
Integrations, Company Profile, Onboarding, and the appropriate dashboard.

No database migration is required.


## v8.7.8 Full-Width Employee Announcements

The redundant Quick Access panel is removed from the Employee Dashboard.
Leave Management, Company Policies, and HR Assistant remain available in the
fixed employee sidebar.

The dashboard now uses the available content width for company announcements,
filters, search, featured posts, and latest updates. Notification deep links
remain supported.

No database migration is required.

## v8.8.0 Context-Aware HR Assistant

The Employee Chat Assistant is no longer policy-only.

### Grounded answer sources

```text
Live employee master record
Live leave credits
Live leave request history
Configured leave types and operational rules
Approved published company policy files
Existing HR application modules
```

The assistant does not use outside knowledge and does not invent unavailable
company information.

### Leave shorthand and context

```text
VL = Vacation Leave
SL = Sick Leave
EL = Emergency Leave
LWOP = Leave Without Pay
```

Configured custom leave codes and names are matched dynamically. Short
follow-up questions reuse the previous user topic:

```text
User: Paano mag-file ng VL?
User: Ilan na lang?
Assistant: Returns the signed-in employee's current VL breakdown.
```

### Clickable navigation

Answers can open Leave Management, File Leave Request, My Requests, Company
Policies, My Documents, Benefits, Onboarding, HR Contacts, FAQ, and Dashboard.
Leave-related actions support direct views through the `leave_view` query
parameter.

No database migration is required.


## v8.8.1 Readable HR Assistant Responses

The invisible white Markdown list text in the HR Assistant is fixed.

Messages now use a stable keyed wrapper and `st.markdown`, preserving:

```text
Bullets
Numbered steps
Bold leave codes
Links
Policy formatting
```

A Light Mode contrast guard also covers read-only list content in policy
sections, expanders, alerts, and other HR information. Dark editable form
controls remain unchanged.

No database migration is required.


## v8.8.2 Readable Policy Content

Employee policy source text no longer uses the `st.text` component that
inherited an invisible white foreground in Light Mode.

The policy browser now:

```text
Escapes uploaded source text safely
Preserves original line breaks
Uses normal readable typography
Wraps long paragraphs
Keeps headings, numbered paragraphs, and lists visible
```

The Policy Assistant answer is also rendered through a stable keyed Markdown
wrapper. A fallback covers read-only `st.text` and preformatted content inside
policy expanders without changing dark editable form fields.

No database migration is required.


## v8.8.3 Private and Topic-Aware HR Chat

### Conversation privacy

HR Assistant state is scoped using both `company_id` and `user_id`.
Messages, input text, action widgets, and New Conversation controls are
account-specific.

Legacy global chat state is deleted rather than assigned to a newly logged-in
employee. Private chat state is cleared when the authenticated account changes,
logs out, or is cleared after an external password reset.

### Topic reset

A short message is no longer automatically treated as a follow-up.

```text
Leave
→ Leave topic

Policy
→ New policy topic
```

Conversation history is used only for explicit incomplete follow-ups such as:

```text
Ilan na lang?
How many left?
Paano naman?
What about that?
```

Recognizable standalone topics always take priority over previous messages.

No database migration is required.


## v8.8.4 Admin HR Assistant

The Administration Portal now includes a private, company-scoped Chat
Assistant. Its conversation is separate from the Employee Portal chat, even
when the same administrator switches between portals.

### Administrator questions

```text
How many employees do we have?
Show active and inactive user accounts.
Are there pending leave requests?
Show the leave credits of EMP-001.
How many policies are published?
What is the company policy on overtime?
How many announcements are scheduled?
How do I create an announcement?
Where do I configure SMTP?
```

The assistant uses live company records, approved policy sections, and safe
navigation actions. Personal employee questions from an administrator—such as
"Ilan na lang leave ko?"—still use the signed-in administrator's own employee
record.

### Security and privacy

```text
Company-scoped using company_id
Private state using company_id + user_id
Separate Admin and Employee Portal conversations
Cleared on account change, logout, and password-reset session clear
No password hashes, reset tokens, SMTP passwords, or cookie secrets displayed
```

No database migration is required.


## v8.8.5 Company Logo Branding

Administrators can upload, replace, preview, or remove a company logo from:

```text
Admin Portal -> Company Profile -> Company Logo
```

Supported uploads:

```text
PNG
JPG / JPEG
WEBP
Maximum size: configurable, 5 MB by default
```

Uploaded images are decoded, validated, resized only when necessary, and
re-encoded as a safe canonical PNG. The image remains company-scoped at:

```text
data/uploads/company_logos/<company_id>/company_logo.png
```

The logo is displayed at the top of both fixed protected sidebars:

```text
Admin Portal sidebar
Employee Portal sidebar
```

CSS uses `object-fit: contain`, centered alignment, bounded width and height,
and automatic dimensions so wide or tall logos are never stretched or cropped.
When no logo is configured, the sidebar shows a neutral Company Logo
placeholder.

Existing databases receive the nullable `companies.logo_filename` column
through the additive runtime schema upgrade. No destructive migration is used.


## v8.8.6 Larger Company Logo

The company logo now uses nearly the full sidebar logo holder.

```text
Holder height: 112 px
Logo maximum height: 104 px
Inner padding: 4 px vertical / 5 px horizontal
Width and height: use the available holder area
Scaling: object-fit contain
Alignment: centered
```

The logo remains proportional and is not cropped or stretched. The same
company-scoped logo continues to appear in both Admin and Employee portals.

No database migration is required.


## v8.8.8 Specific Notification Deep Links

Notification clicks now open the exact related record instead of only the parent module.

For leave notifications:

```text
Admin notification → Leave Requests → specific request details
Employee notification → My Requests → specific request details
Manager pending notification → Pending Approvals → specific request
Manager decision notification → Reviewed Requests → specific request
```

The route uses both `leave_request_id` and `leave_view`. The destination validates the signed-in employee or manager context before showing employee-portal details. No database migration is required.


## v8.8.9 Employee Form and Searchable List

The Add Employee and Edit Employee tabs now use the same card-based layout:

```text
Employee Information
Name fields
Employment and organization fields
Training Checklist

Account Information
User ID and clearance
Username and temporary password
```

The Employee List now includes a company-scoped search field. All matching
records remain in the table, while the viewport shows five fixed-height rows.
Visible vertical and horizontal scrollbars provide access to the remaining
records and columns. Search covers employee number, name, email, department,
manager, job title, username, account state, status, and training items.

No database migration is required.


## v8.8.10 Notification Tab Targeting

Leave notification links now keep the complete Leave Management workspace and
select the exact tab plus the related request. Admin notifications open the
Leave Requests tab and select the matching request in View Request Details.
Employee and manager notifications select My Requests, Pending Approvals, or
Reviewed Requests as appropriate. No database migration is required.


## v8.8.11 Refresh-Safe Authentication

Normal browser refreshes now preserve the signed-in account and current
Admin or Employee Portal route. The authentication flow checks both the
initial Streamlit request cookies and a one-cycle browser-component fallback
before showing the login page.

When `AUTH_COOKIE_SECRET` is blank, the application creates a private local
secret at `data/.auth_cookie_secret`. Preserve this file with the `data`
folder so valid sessions also survive Streamlit server restarts. Explicit
logout, password reset, expired cookies, disabled accounts, and password
changes still invalidate authentication.

No database migration is required.


## v8.8.12 Admin and Employee UX Refinements

- Ctrl/Cmd+C now remains the normal browser Copy shortcut and no longer
  opens Streamlit's Clear Caches dialog.
- Admin HR Assistant uses admin-specific Quick Actions matching the card
  organization of the Employee HR Assistant. The redundant Admin Shortcuts
  and Answer Sources panels were removed.
- Add Employee and Edit Employee include a company-scoped optional
  Telephone / Mobile No. field. Existing databases receive the new nullable
  column through the additive runtime schema upgrade.
- The employee list includes and searches the telephone/mobile value.
- The Edit Employee Danger Zone targets the currently selected employee and
  now requires only one acknowledgment checkbox and the permanent-delete
  button.

No destructive database migration is required.


## v8.8.13 Table and Leave Management Hotfix

- Removes the accidental `selected_request_id` reference from Employee Leave Accounts.
- Keeps notification filter reset inside the Leave Requests renderer only.
- Makes the Employee List compact by removing duplicate split-name columns.
- Combines email and telephone/mobile into one Contact column.
- Uses a five-row maximum viewport without a large empty area for shorter lists.
- Keeps Employee Number and Full Name visible while horizontally scrolling.

No destructive database migration is required.


## v8.8.14 Native Copy and Verified Refresh Persistence

- Streamlit runs in viewer toolbar mode, removing developer cache tools
  and leaving Ctrl/Cmd+C as the browser's normal Copy command.
- The old JavaScript copy-key interception is removed.
- Browser-cookie reads refresh the cookie component's internal cache.
- A full refresh gets up to five short restoration cycles before the
  login page is allowed to appear.
- Login and password-change transitions verify that the signed cookie is
  present in the browser before continuing, with a bounded timeout.
- Logout verifies cookie removal before completing.

No database migration is required.


## v8.8.15 Copy and Refresh Root Fix

This release removes two root causes from the previous authentication build:

1. The browser-cookie controller is never refreshed immediately after its
   keyed constructor call. The initial component is mounted once, and Login is
   shown only after its first result is available.
2. Cookie write/remove transitions no longer re-read or refresh the same
   component during the same Streamlit run.

Ctrl/Cmd+C now uses a parent-window capture listener that stops Streamlit's
Clear-cache shortcut listener without calling `preventDefault`, preserving the
browser's native Copy action.

No database migration is required.


## v8.8.16 Browser-Storage Refresh Fix

Authentication persistence no longer depends on the third-party
`streamlit-cookies-controller` component. A bundled offline Streamlit
component stores the signed token in browser `localStorage`.

Refresh flow:

```text
F5 / browser refresh
→ new Streamlit session
→ bundled component reads localStorage
→ application waits for ready response
→ signed token is validated against the database
→ same user, portal, and URL-selected page are restored
```

Login, password change, logout, and external password reset all use the same
storage key. The token remains signed, time-limited, password-fingerprint
bound, company-scoped, and invalidated when the account or company is inactive.

The custom component is included in the ZIP and needs no internet connection.
No database migration is required.


## v8.8.17 Single-Submit Login Fix

All three login credentials now belong to one Streamlit form. The Company
Code field no longer uses an external `on_change` rerun that could consume the
first Sign In click.

After successful credential validation, the authenticated Streamlit session
opens the correct portal immediately. Browser-token persistence is retried
non-blockingly from the protected page instead of stopping on the Login page.

The separate full-browser-refresh persistence issue remains an open tracked
item and is not claimed as resolved by this version.

No database migration is required.

## v8.8.19 — Scrollable Policy Management

- Searchable Sections now stays inside a fixed-height scrollable box.
- Version History tables keep a fixed height with vertical scrolling and a sticky header.
- Move to Bin now targets the currently selected policy and uses a confirmation checkbox instead of typed Policy ID confirmation.
- The backend still validates the selected policy ID before moving the version to the Bin.

## v8.8.20 — Visible Policy Scrollbars

- Detected Headings and policy document previews now show a clearly visible scrollbar track and thumb.
- Searchable Sections uses a keyed fixed-height container with an always-reserved vertical scrollbar.
- Extracted Policy Content and Editable Policy Content show visible scrollbars inside their fixed-height text areas.
- Bounded Version History tables use a visible themed vertical scrollbar while keeping the sticky header.
- No database migration is required.

## v8.8.21 — Separated Policy Workspaces

- The Policies area now has separate **Upload Policy File** and **Manage Existing Policy** sub-tabs.
- Upload preview, detected headings, previous versions, and file processing remain inside the upload workspace.
- The active policy table, selector, editing, new-version upload, content, sections, version history, and Move to Bin actions are grouped inside the management workspace.
- The Bin remains a separate main tab, and all visible-scrollbar behavior from v8.8.20 is preserved.
- No database migration is required.

## v8.8.22 — Policy Library Peer Tabs and Preview

- The Policies page now uses four equal-level tabs in this order: **Policies**, **Upload Policy File**, **Manage Existing Policy**, and **Bin**.
- The **Policies** tab contains the active policy list only; the list stays in a fixed-height table with visible vertical and horizontal scrollbars and a sticky header.
- A selected policy is not previewed automatically. Its approved content appears below the list only after **Preview Selected Policy** is clicked.
- The read-only preview uses the same bounded detected-heading and extracted-section layout as the upload preview, without edit, version, file, history, or Bin actions.
- **Manage Existing Policy** keeps all maintenance actions but no longer repeats the active policy list table.
- No database migration is required.


## v8.8.23 — Admin Event Calendar Reminders

- Announcements can optionally be added to an event/activity calendar using a local date picker and time input.
- Event end date and time are optional and validated to occur after the start.
- Administrators can schedule an advance reminder for 1 hour, 1 day, 3 days, or 7 days before an event.
- Due reminders create one in-app notification for every active clearance-1 administrator and never notify standard employee accounts.
- Reminder delivery is database-backed and idempotent; refreshes do not create duplicate reminder notifications.
- The new **Calendar & Reminders** tab provides a calendar-date view plus fixed-height, scrollable tables for scheduled and upcoming events.
- Notification clicks open the related announcement through the existing refresh-safe announcement deep link.
- Employee announcement cards display the configured event/activity schedule, while reminder status remains admin-only.
- Existing databases receive additive event and reminder columns without deleting announcement records.

## Reset local leave test data

Stop Streamlit, then run the leave-only cleanup command from the project root:

```powershell
python -m scripts.reset_leave_test_data --confirm
```

The command creates an SQLite backup, clears leave requests, balances, credit
history, linked notifications, and leave attachments, then recreates clean
current-year balances. Employees, users, companies, departments, and leave
types are preserved.

## v8.8.52 — Annual SL/VL Accrual Phase 2

Vacation Leave and Sick Leave annual credit is based on completed tenure every
January 1: 1–5 years = 15 days, 6–10 = 17, 11–15 = 20, 16–20 = 23, and 21+
= 26. Mid-year bracket changes take effect on the next January processing.
Unused SL/VL is carried into the following year's Beginning Credit.
The processing is idempotent and also runs automatically after authenticated
application startup.

Optional explicit batch command:

```powershell
python -m scripts.process_january_leave_accrual
```

The command accepts `--year` and `--company-code`. Cash conversion remains for
Phase 3, while the three-day Emergency Leave allowance remains for Phase 4.

## v8.8.56 — SL/VL Cash Conversion Phase 3

January annual leave processing now retains a maximum of 15 Sick Leave days and 45 Vacation Leave days. Excess credits are recorded in the Converted to Cash column and removed from Available Credits. Processing is automatic and idempotent, and converted credits are not carried into the next year.


## v8.8.57 — Manual SL/VL Cash Conversion Guard

Manual SL/VL credit updates now enforce the fixed retained limits immediately. Excess credits are moved to Converted to Cash in the same transaction.


## v8.8.58 — Emergency Leave Phase 4

- Emergency Leave is limited to three paid days per calendar year.
- EL does not create additional credits; approved EL days deduct from VL.
- The EL row displays used days and remaining annual allowance.
- Approved EL days beyond the remaining allowance automatically become LWOP.
- Admin manual credit editing excludes the system-managed EL allowance.


## v8.8.70 — Company Form Preview and Table UI Fix

- PDF files now use the supported in-app Streamlit PDF viewer instead of the blank browser iframe.
- Category and Description were removed from Upload Form, Manage Form, and employee-facing form details.
- Existing hidden metadata remains preserved for older records.
- Row-click tables keep their popup behavior and now use the same light surface, border, radius, shadow, and row spacing as the other project tables.
- Modal headings and captions remain readable against the white preview surface.

## Current checkpoint

**v8.8.104 — Removed Human Support Sidebar Card**

## v8.8.78 — Centered Password Change Form

- The complete mandatory password-change composition is centered vertically
  and horizontally on the authentication page.
- Temporary-password guidance is combined into one yellow notice.
- Existing password validation, submission, signed-cookie renewal, and forced
  password-change behavior remain unchanged.
- No database migration is required.

## v8.8.79 — Centered Authentication Forms

- The complete Welcome Back composition, including its title, subtitle, and
  login card, is centered vertically and horizontally in the viewport.
- The centered Change Your Password composition and combined yellow guidance
  from v8.8.78 remain unchanged.
- Login validation, forgot-password navigation, authentication, and session
  behavior remain unchanged.
- No database migration is required.

## v8.8.80 — Authentication Visual Center Correction

- The visible title, subtitle, and form group on both Login and Change Your
  Password pages is shifted upward with a viewport-aware correction so the
  composition has balanced space above and below.
- Short browser windows use a reduced offset to prevent the form from being
  clipped.
- Authentication, validation, password replacement, and session behavior
  remain unchanged.
- No database migration is required.

## v8.8.81 — Compact Admin Sidebar Polish

- The unused Streamlit sidebar-header space is removed so the company logo and
  navigation begin higher on the page.
- The AI HR Assistant brand is centered and slightly larger.
- Administration Portal and administrator-name captions are removed from the
  admin sidebar.
- Sidebar element gaps are reduced and navigation buttons receive a subtle
  default and hover shadow.
- Admin navigation and portal-switch behavior remain unchanged.
- No database migration is required.

## v8.8.82 — Balanced Sidebar Brand Spacing

- A controlled 14-pixel spacer separates the centered AI HR Assistant brand
  from the first admin navigation button.
- Compact spacing between navigation buttons and the subtle button shadows from
  v8.8.81 remain unchanged.
- Admin navigation behavior remains unchanged.
- No database migration is required.

## v8.8.83 — Balanced Sidebar Section Spacing

- The space between the AI HR Assistant brand and the first navigation button
  is increased from 14 to 28 pixels.
- The adjusted separation visually matches the logo-to-brand spacing more
  closely while keeping the navigation list compact.
- Sidebar button shadows and navigation behavior remain unchanged.
- No database migration is required.

## v8.8.84 — Persistent Admin Workspace Tabs

- Company Profile, Employees, Policies, and Company Form/Documents now use
  session-backed tab-style workspace selectors instead of stateless native
  Streamlit tabs.
- Manual tab selection survives Save, Edit, validation, and ordinary widget
  reruns, so the page no longer jumps back to its first tab.
- Only the active workspace content is rendered, while existing success banners
  and toast notifications remain visible after completed actions.
- Existing database, service, validation, and authorization behavior is
  unchanged.
- No database migration is required.

## v8.8.85 — Native-Look Persistent Tabs

- Persistent admin workspace selectors now match the former native tab style:
  transparent surfaces, compact text labels, and an active underline.
- The oversized dark segmented-control boxes are removed through CSS scoped
  only to Company Profile, Employees, Policies, and Company Form/Documents.
- Session-backed active-tab persistence from v8.8.84 remains unchanged.
- No database migration is required.

## v8.8.86 — Native Stateful Admin Tabs

- Company Profile, Employees, Policies, and Company Form/Documents use real
  Streamlit tabs again, restoring the exact former tab appearance.
- Native tab tracking uses stable keys and `on_change="rerun"`, so the selected
  tab survives Save, Edit, validation, and ordinary widget reruns.
- The minimum Streamlit version is now 1.61 because earlier versions do not
  expose tracked native tab state.
- Existing success banners, toast notifications, services, and authorization
  behavior remain unchanged.
- No database migration is required.

## v8.8.87 — Single-Page Company Profile

- Company Profile no longer uses Company Information and Branding tabs.
- Company Information, Company Logo, and Company Theme Color are shown in one
  continuous page in that order.
- Clear horizontal dividers separate all three sections while preserving the
  existing forms, previews, save actions, validation, and notifications.
- Native stateful tabs remain enabled for Employees, Policies, and Company
  Form/Documents.
- No database migration is required.

## v8.8.88 — Forgot Password Style Restore

- The Login-page Forgot Password action has a stable widget key and scoped
  styling that is independent of Streamlit's internal secondary-button markup.
- The action is restored to a transparent text-style secondary button with
  readable dark text and a subtle hover surface.
- Sign In styling, navigation, password reset behavior, and authentication
  remain unchanged.
- No database migration is required.

## v8.8.89 — Company Forms Overview and Preview Polish

- Company Form/Documents overview metrics now sit directly above the active
  forms table, and the redundant Available Company Forms heading is removed.
- Selectable tables use the fixed Light Mode palette, shared border/radius/
  shadow treatment, and a row-aware height that removes unused dark grid rows.
- The File Preview document area is bounded and internally scrollable so the
  dialog title, filename, Download File, upper-right close control, and complete
  modal shell remain visible.
- File Preview can be dismissed through its upper-right X, by clicking outside
  the dialog, or by pressing Escape; dismissal also clears the queued preview
  state so it does not reopen on the next interaction.
- File authorization, row selection, preview, download, submission review, and
  database behavior remain unchanged.
- No database migration is required.

## v8.8.90 — Streamlit 1.61 Input Style Compatibility

- A final global compatibility layer restores the approved dark input surfaces
  and white values after Streamlit 1.61 changed internal control wrappers.
- Text, password, number, date, time, select, multiselect, text-area, disabled,
  and read-only controls now use consistent dark surfaces, readable values,
  placeholders, hover borders, and focus rings throughout the project.
- The v8.8.89 Light Mode selectable-table fix remains enabled without changing
  form-control appearance.
- Existing forms, validation, database writes, and navigation remain unchanged.
- No database migration is required.

## v8.8.91 — Whole-Row Company Form Preview

- Every selectable row in Company Form/Documents can be clicked anywhere on
  its data cells to open the corresponding secure file preview.
- Active forms, employee submissions, Manage Form, and Bin tables use the same
  whole-row interaction and show clearer click instructions.
- Selectable grids display a pointer cursor while preserving Streamlit's native
  keyboard accessibility and single-row selection state.
- File authorization, preview dismissal, download, review, and database
  behavior remain unchanged.
- No database migration is required.

## v8.8.92 — Expanded File Preview Modal

- The Company Form/Documents File Preview modal now uses balanced 48-pixel
  viewport margins so the visible space above and below the panel is equal.
- The preview area is taller and remains responsive on shorter browser windows.
- The File Preview dialog title is centered, and the redundant preview-only
  caption beneath the filename is removed.
- Download File uses half of the action row, leaving a matching action area for
  form printing.
- Secure file authorization, preview rendering, download, and modal dismissal
  behavior remain unchanged.
- No database migration is required.

## v8.8.93 — Functional Company Form Printing

- The File Preview action row now shows Print Form on the left and Download
  File on the right.
- Print Form opens the browser's native print dialog directly from the already
  authorized file bytes without uploading the file to another service.
- PDF files print through the browser's PDF renderer. Images, TXT, CSV, DOCX,
  and modern Excel files receive a clean printable browser representation.
- Legacy DOC/XLS and unknown formats keep printing disabled because browsers
  cannot render them reliably; Download File remains available.
- Existing preview, authorization, download, close, and outside-click dismissal
  behavior remains unchanged.
- No database migration is required.

## v8.8.94 — Centered Preview Title and Matched Actions

- The actual Streamlit File Preview dialog heading is centered against the
  complete modal width while the upper-right close control remains unchanged.
- A browser-side compatibility pass reapplies the centered position after the
  dialog finishes rendering, avoiding Streamlit's generated header wrappers.
- Print Form copies the rendered Download File button's background, text,
  border, radius, shadow, and typography so both actions look consistent under
  the active company theme.
- Print Form remains on the left and Download File remains on the right.
- Printing, downloading, secure preview authorization, and modal dismissal
  behavior remain unchanged.
- No database migration is required.

## v8.8.95 — Native Preview Actions and Restored Title

- The File Preview title is restored to normal document flow and centered by
  expanding the native heading across the dialog header; the fragile absolute
  positioning workaround is removed.
- Print Form is now a native Streamlit secondary button, exactly like Download
  File, so both actions share the same generated design, dimensions, typography,
  theme colors, borders, focus behavior, and hover behavior.
- The hidden browser component now launches printing only after the native Print
  Form button is clicked; it no longer renders or styles a separate button.
- Print Form remains on the left and Download File remains on the right.
- Printing, downloading, secure preview authorization, and modal dismissal
  behavior remain unchanged.
- No database migration is required.

## v8.8.96 — Exact Native Preview Title Centering

- File Preview now targets Streamlit 1.61's actual native modal-header element,
  which is rendered with `slot="title"` instead of an H2 heading.
- The native title slot spans the complete dialog width and centers its text
  with symmetric padding, matching the approved screenshot while preserving the
  upper-right Close control.
- Print Form and Download File remain matching native Streamlit secondary
  actions with identical styling and their left-to-right order unchanged.
- Printing, downloading, secure preview authorization, and modal dismissal
  behavior remain unchanged.
- No database migration is required.

## v8.8.97 — Native Left-Aligned File Preview Layout

- All File Preview title-centering overrides are removed, returning the modal
  to Streamlit's stable native upper-left title layout.
- The upper-right Close control, filename beneath the title, tall document
  preview, and balanced modal height are preserved.
- Print Form remains on the left and Download File remains on the right as
  matching native Streamlit secondary actions.
- Printing, downloading, secure preview authorization, and modal dismissal
  behavior remain unchanged.
- No database migration is required.

## v8.8.98 — Clean Form Container Borders

- Redundant outer borders are removed from Company Form/Documents workspaces
  that already contain a bordered Streamlit form.
- The cleanup covers administrator submission review, administrator upload,
  administrator manage, and employee fill/submit workspaces.
- The inner form card remains visible, so fields and actions retain one clean
  grouping without the large gray or black double-outline around it.
- Intentional borders on document previews, tables, employee-information cards,
  announcement cards, and quick actions remain unchanged.
- Form submission, validation, upload, review, and database behavior remain
  unchanged.
- No database migration is required.

## v8.8.99 — Compact Employee Sidebar Polish

- The Employee Portal sidebar now uses the same compact visual hierarchy as
  the Administration Portal sidebar.
- The redundant employee name and role/company captions beneath the AI HR
  Assistant brand are removed; the signed-in identity remains visible in the
  portal header.
- The centered, slightly larger AI HR Assistant brand now has the same
  controlled 28px spacing before the Employee navigation buttons.
- Existing Employee navigation, Admin Portal access for administrators,
  logout, and human-support behavior remain unchanged.
- The existing subtle sidebar button shadows continue to apply consistently
  in both portals.
- No database migration is required.

## v8.8.100 — Simplified Employee Announcements Dashboard

- The Employee Dashboard no longer shows the announcement Category filter or
  Search field above Latest Updates.
- Active company announcements now appear directly beneath the Company
  Announcements heading for a cleaner landing-page layout.
- Featured announcements, Latest Updates, notification deep links, images,
  and the empty-dashboard message remain supported.
- No database migration is required.

### Planned Attendance / DTR Module

- A successful employee login will record the authenticated employee name and
  Time In; an explicit logout will record Time Out.
- Daily records will contain Employee Name, Date, Time In, Time Out, Total
  Hours, and OT Hours.
- Total and overtime hours will be calculated and stored, with weekly and
  monthly summaries available for reporting.
- Saturday and Sunday records will be accepted and included in computations.
- Reports will support employee/date filtering and downloadable output.
- The final weekend-overtime policy remains pending confirmation before this
  module is implemented.

## v8.8.101 — Restored Active Announcement Count

- The active-announcement count is restored beneath the Company Announcements
  heading on the Employee Dashboard.
- The Category filter and Search field remain removed as requested.
- Featured announcements, Latest Updates, notification deep links, images,
  and empty-dashboard behavior remain unchanged.
- No database migration is required.

## v8.8.102 — Balanced Sidebar Vertical Spacing

- The complete sidebar content block now shares available vertical space
  evenly above and below it on taller browser windows.
- The same balanced layout applies to both Administration and Employee
  portals without changing their navigation items or behavior.
- Equal top and bottom safety padding is preserved around the centered block.
- On shorter windows, automatic margins collapse and the existing sidebar
  scrolling remains available so navigation controls are not clipped.
- No database migration is required.

## v8.8.103 — Calibrated Sidebar Top Spacing

- The shared sidebar top padding is increased from 0.75rem to exactly 2.00rem,
  matching the value verified in the browser inspector.
- Bottom padding remains at 0.75rem because the logo container contributes
  internal top whitespace; the asymmetric CSS values produce the intended
  visual balance between the top and bottom edges.
- The adjustment applies consistently to both Administration and Employee
  portals while preserving responsive scrolling and all navigation behavior.
- No database migration is required.

## v8.8.104 — Removed Human Support Sidebar Card

- The Need Human Support card is removed from the bottom of the Employee
  Portal sidebar.
- Employees can still open the dedicated HR Contacts navigation page when
  human assistance is needed.
- Admin Portal access, Log Out, employee navigation, and the calibrated
  sidebar spacing remain unchanged.
- No database migration is required.

## v8.8.105 — Attendance, DTR, and OT Module

- Employee Dashboard adds explicit Login and Logout attendance actions. The
  authenticated employee identity and Manila-local action time are recorded;
  duplicate daily punches are prevented.
- Employees may set WFO, WFH, or provisional VL/SL/EL. An approved Leave
  Management request automatically becomes the authoritative leave status.
- Admin and Employee dashboards include a horizontally scrollable monthly DTR
  matrix with all calendar dates, weekend shading, Login/Logout times, total
  hours, OT hours, and the approved status color legend.
- Employee visibility is restricted to the signed-in employee plus direct
  manager/leader members. Administrators retain company-wide visibility.
- Company Profile adds configurable regular hours, unpaid lunch duration, and
  Monday-through-Sunday regular-workday settings. Weekday excess hours become
  OT; every worked hour on a configured rest day becomes OT.
- Administrators may correct attendance with a required reason and immutable
  before/after audit history.
- Attendance reports support date, employee, department, and status filters,
  totals, and Excel/PDF downloads.
- Existing databases receive the new schedule columns non-destructively, while
  the new attendance and correction tables are created automatically.

## v8.8.106 — Streamlit 1.61 Iframe Migration

- All active `st.components.v1.html` calls are migrated to Streamlit 1.61's
  supported `st.iframe` API, removing the repeated deprecation warning.
- A shared invisible browser bridge preserves the previous zero-height layout:
  the required 1×1 iframe immediately hides its complete Streamlit element
  container and cannot receive keyboard focus.
- The existing trusted JavaScript behavior is retained for theme persistence,
  input contrast compatibility, native Copy handling, refresh-safe login and
  route state, company-form printing, and Leave notification tab navigation.
- No visible CSS, sidebar spacing, forms, tables, modal layout, colors, or
  navigation design is changed.
- No database migration or dependency change is required.

## v8.8.107 — Employee Attendance Dashboard Editing

- Employee attendance metrics now appear immediately below the Attendance/DTR
  description: Leave Count, today's OT, total OT for the selected month, and
  Work Rate.
- Work Rate follows the requested formula: `100 × ((monthly total hours ÷
  company working days in the selected month) ÷ 8)`.
- Login, Logout, and Save Status remain clickable at all times. Invalid or
  duplicate actions return a clear message instead of disabling the action.
- Employees can edit their own current-day Time In and Time Out. The selected
  Today's Work/Leave Status is saved with the edit unless an approved leave
  request controls the official status.
- Employee time edits create immutable before/after attendance audit entries;
  employees cannot edit another employee or a previous/future date.
- The period selectors are reordered and simplified to Year followed by Month,
  using select controls instead of the numeric Year stepper.
- No database migration or dependency change is required.

## v8.8.118 — Warning-Free Leave Year State

- Initializes the Admin Leave Management year through Session State only and
  removes the duplicate explicit widget default that triggered Streamlit's
  `leave_management_year` warning.
- Preserves the same Year field design, position, range, notification-target
  year selection, tabs, filters, and leave-management behavior.
- No database migration or dependency change is required.

## v8.8.119 — Qwen2.5 3B Chat Assistant

- Connects both the Admin and Employee Chat Assistant pages to the same
  company-scoped Smart AI enhancement service.
- Uses the official Ollama model tag `qwen2.5:3b` for both standard and complex
  grounded responses, avoiding an unexpected switch to a different model.
- Keeps live HR results, exact balances, statuses, security restrictions, and
  company access controls authoritative; Ollama only rewrites eligible answers
  using approved portal and published-policy context.
- Falls back to the existing deterministic HR response when Ollama is stopped,
  unavailable, or times out, so the Chat Assistant remains usable.
- Before starting Streamlit, install the local model once:

  ```powershell
  ollama pull qwen2.5:3b
  ```

- No database migration or UI/layout change is required.

## v8.8.120 — Right-Aligned User Chat and Quiet Chroma Telemetry

- Moves Admin and Employee user questions to the right while keeping assistant
  responses on the left and preserving avatars, Markdown, sources, and related
  module actions.
- Restores the Chat Assistant input to a dark background with white entered
  text, a readable light placeholder, and a visible send icon.
- Disables anonymized Chroma telemetry through the local persistent-client
  settings, removing incompatible PostHog telemetry warnings without disabling
  BM25/vector retrieval or changing the local Chroma database.
- Keeps `qwen2.5:3b` for both Admin and Employee Chat Assistant responses.
- No database migration is required.

## v8.8.121 — Unified Dark Chat Input

- Replaces the white outer Chat Assistant input panel with one seamless dark
  rounded field matching the application's dark search controls.
- Keeps entered text white and the placeholder softly visible on the same dark
  surface.
- Places the send action in a separate black rounded box with a white arrow-up
  icon, including its empty/disabled visual state.
- Preserves the completed right-aligned user questions, Admin/Employee shared
  Qwen2.5 3B integration, and disabled Chroma telemetry from v8.8.120.
- No database migration or chat-function change is required.

## v8.8.122 — Ephemeral Welcome, Exact Routes, and App-Wide Answers

- Shows `Good day, how can I assist you today?` only in a blank or newly reset
  Admin/Employee conversation; it is no longer stored in chat history and
  disappears immediately after the first user message.
- Replaces the unreliable native send artwork with a controlled white `↑` on
  the existing black send box, eliminating the white-square rendering issue.
- Tightens Quick Action title/subtitle spacing and makes Employee Quick Actions
  clickable.
- Opens exact native module views from Quick Actions and assistant links,
  including Leave Requests, Employee Leave Accounts, employee add/list,
  policy library/upload/management, announcement create/manage, company forms,
  employee Attendance/DTR, and employee Announcements.
- Adds company-scoped highest/lowest employee leave-credit ranking so comparison
  questions return actual live employee balances instead of a generic overview.
- Extends grounded Admin and Employee coverage across Attendance/DTR/OT,
  Company Form/Documents, policies, announcements, leave, employee records,
  benefits, onboarding, HR Contacts, FAQ, reports, and integrations while
  continuing to reject outside knowledge and unavailable information.
- Preserves Qwen2.5 3B, right-aligned user messages, unified dark chat input,
  and disabled Chroma telemetry.
- No database migration is required.

## v8.8.123 — Native Send, Visible Loading, and Live Grounding

- Restores Streamlit's original send-arrow artwork inside the completed black
  send box and keeps the native icon white without replacing it with text.
- Shows a temporary assistant-side loading message while either portal searches
  authorized company records and published policies and generates the answer.
- Grounds Qwen2.5 3B with authorized live company, employee, account, leave
  credit, leave request, Attendance/DTR/OT, announcement, and company-form
  records, form submissions, employee training, and admin event reminders in
  addition to published policies and application workflows.
- Keeps employee retrieval private to the signed-in employee's own HR records;
  only employee-visible published announcements and active forms are shared.
- Keeps administrator retrieval company-scoped and never supplies passwords,
  password hashes, reset tokens, credentials, or cross-company records.
- Broad summary intents may now use the live record context to answer the exact
  wording of a question instead of returning an unrelated generic overview.
- No database migration is required.

## v8.8.124 — Chroma/PostHog Telemetry Compatibility Fix

- Pins PostHog below version 6, matching Chroma's official compatibility fix
  for `capture() takes 1 positional argument but 3 were given`.
- Exports `ANONYMIZED_TELEMETRY=False` to the running Python process before
  Chroma is imported; loading the same value through application settings alone
  does not populate the environment seen by Chroma.
- Silences only the disabled Chroma PostHog component in older installations
  that instantiate it despite telemetry being off.
- Keeps Chroma vector retrieval, BM25 retrieval, Qwen2.5 3B answers, live HR
  grounding, and all Admin/Employee Chat Assistant behavior enabled.
- Existing virtual environments should run `python -m pip install --upgrade
  "chromadb>=1.0.15,<2.0" "posthog>=2.4,<6.0.0"` once before restarting
  Streamlit so the installed packages also match the corrected requirements.
- No database migration or UI/layout change is required.

## v8.8.125 — Conversation Above Input and Immediate Welcome Removal

- Keeps the complete Admin and Employee Chat Assistant conversation above the
  input box, including submitted user questions, loading feedback, completed
  assistant answers, approved sources, and exact related-module actions.
- Removes `Good day, how can I assist you today?` immediately when the first
  question is submitted, including during answer loading; it returns only for
  a blank or newly reset conversation.
- Preserves the v8.8.124 Chroma/PostHog telemetry compatibility fix, Qwen2.5 3B,
  live authorized grounding, native send arrow, current styling, and routing.
- No database migration or dependency change is required.

## v8.8.126 — Monthly Workday Calendar and Correct OT Span

- Moves `Attendance Schedule & OT Rules` out of Company Profile and places it
  on Admin Dashboard immediately before `Admin Attendance Correction`, using
  the same collapsible-section spacing as Attendance Edit History.
- Replaces fixed Mon–Sun workweek checkboxes with a compact monthly calendar
  tied to the selected DTR year and month. New months default to Monday–Friday,
  while every date remains selectable for holidays and catch-up workdays.
- Persists every company's monthly calendar independently and applies saved
  workdays to leave synchronization, DTR rest-day shading, working-day totals,
  existing attendance rows, and rest-day OT calculations.
- Corrects the unpaid-lunch span: 8 paid hours plus a 60-minute unpaid lunch
  requires 9 elapsed hours before OT starts. A 09:00–18:00 schedule therefore
  remains 8.00 paid hours and 0.00 OT.
- Recalculates existing records in the saved month using the selected workday
  calendar and current paid-hour/lunch rules without deleting attendance or
  audit history.
- Adds the new company workday table automatically and non-destructively at
  application startup; no manual migration command is required.

## v8.8.127 — Live Search and Autosuggest

- Replaces every explicit Admin and Employee portal search box with one shared
  debounced live-search control. Results update automatically while typing;
  Enter and focus loss are no longer required.
- Adds relevant autosuggestions for employee names/numbers/contact details,
  leave-request employees, policy titles/categories/section headings, and
  announcement titles/categories.
- Adds a visible clear action and Escape-key clearing. Removing the search text
  immediately restores the complete unfiltered result set.
- Preserves the current dark input design, white search text, readable
  placeholder, search scope, filter rules, tab layout, and database behavior.
- Keeps native searchable select boxes and multiselects such as To, CC, and
  Team Member unchanged because they already filter options while typing.
- Uses the Streamlit Components v2 API already supported by the project's
  Streamlit 1.61 requirement; no new dependency or database migration is
  required.
- The separate centralized-audit draft is intentionally excluded from this
  checkpoint, which is based directly on v8.8.126.

## v8.8.128 — Employee Navigation Consolidation

- Removes the duplicate `My Requests` and `My Documents` buttons from the
  Employee Portal sidebar.
- Keeps `My Requests` as a stateful horizontal tab inside Leave Management,
  including exact Quick Action, notification, and assistant destinations.
- Adds `My Documents` as the fourth Company Form/Documents tab and moves the
  employee's submitted-form history, status, administrator notes, preview,
  and download controls out of `Fill / Submit` into that tab.
- Keeps legacy saved `My Requests` and `My Documents` URLs working by
  redirecting them to their consolidated workspaces.
- Routes form-submission status notifications directly to `My Documents`,
  while document requests open the available Company Form/Documents list.
- No database migration or dependency change is required. This checkpoint is
  based directly on v8.8.127.

## v8.8.133 — Integrated Leave Duration, DTR Sessions, and Payroll Reports

- Adds coded Leave Duration choices: `90501 - AM Only`, `90502 - PM Only`,
  and default `90503 - Whole Day`. AM/PM leave is limited to one date and
  consumes 0.50 credit; legacy requests safely default to Whole Day.
- Splits the leave reason layout into equal `Reason` and
  `Reason for Leave: Others` columns. The standard reason selector uses the
  complete configured code list, while the Others explanation is required
  only for `0 - OTHERS`.
- Blocks exact, contained, containing, and partial date overlaps for every
  active request belonging to the same leave owner. Rejected and fully
  cancelled requests no longer block; approved partial cancellation frees
  only its cancelled future dates.
- Allows Leaders and Managers to file leave for direct reports without
  changing ownership or skipping approval. Routing follows the leave owner:
  Member uses Leader then Manager; employees without a Leader use their
  assigned Manager, enabling Manager -> Head Manager -> General Manager.
- Adds multiple non-overlapping WFO/WFH sessions under one daily attendance
  record. Same-location sessions retain WFO/WFH; mixed sessions become
  Hybrid. Actual timestamps remain auditable while payroll Time In rounds up
  and Time Out rounds down to 15-minute intervals.
- Integrates approved half-day leave with DTR: four leave hours on an
  eight-hour workday, four remaining required work hours, no late/undertime
  charge inside the approved leave half, and no conversion of leave, gaps, or
  lunch into overtime.
- Updates employee and administrator attendance editors for zero to eight
  sessions, 15-minute inputs, session overlap validation, leave/work/OT/
  undertime totals, and immutable correction snapshots.
- Updates the combined DTR/OT/Leave workbook: partial leave and rounded
  sessions in DTR, actual computed OT segments with valid dinner flag and
  leader marker, and structured `[Code] - [Description]` Leave Type,
  Duration, and Reason values. All report person names retain
  `Last, First Suffix, M.` formatting.
- Adds a non-destructive runtime schema upgrade for structured leave fields,
  leave/undertime attendance totals, and the new attendance session table.
  Existing companies, users, hashes, leave requests, DTR rows, and uploads are
  preserved. This checkpoint is based directly on v8.8.132.

## v8.8.132 — Middle-Initial Report Name Format

- Standardizes all report person-name fields as
  `Last Name, First Name Suffix, M.` using only the first letter of the middle
  name followed by a period.
- Applies the same formatter to DTR `Name`, OT `emp_name`, Leave `Emp Name`,
  `Pre-approver`, and `Approver` values.
- Omits unavailable suffix and middle-initial segments cleanly without extra
  commas or spaces. No database migration or dependency change is required.
  This checkpoint is based directly on v8.8.131.

## v8.8.131 — Payroll-Compatible Report Field Mapping

- Formats employee names in DTR, OT, and Leave exports as
  `Last Name, First Name Suffix, Middle Name`, omitting missing optional parts.
- Extends `Overtime File` with the required final unlabeled leader-approval
  column, keeps separate zero-padded 12-hour time and AM/PM columns, and
  preserves employee IDs, ISO rendered dates, computed hours, and supported OT
  types. Fields not collected by the application remain blank.
- Extends `Leave File` with `Leave Type` and `Date Filed`, maps supported leave
  types to payroll codes 90401/90402/90404/90405/90406/90407/90409/90410,
  exports whole-day duration as 90503, and formats every filed/leave/approval
  date as `YYYY-MM-DD`.
- Uses `Others` as the standard reason category and places the employee-entered
  explanation in `Reason for Leave: Others`, matching the current application
  data model without inventing structured reasons.
- No database migration or new dependency is required. This checkpoint is
  based directly on v8.8.130.

## v8.8.130 — Reference-Matched Combined Report Templates

- Matches the `DTR Logs` worksheet to the supplied operational layout: white
  headers, two compact Start/End rows per employee, `yyyy/m/d` date columns,
  thin grid lines, and the established WFH/WFO/leave/rest-day colors.
- Matches the `Overtime File` worksheet to the supplied 13-column template,
  including snake-case headers, separate time and AM/PM cells, blue/green
  header accents, filters, and compact bordered rows.
- Matches the `Leave File` worksheet to the supplied 12-column yellow-header
  template. VL, SL, EL, and other configured leave types remain combined; the
  leave code is exported under `Reason for Leave` and the employee's entered
  explanation under `Reason for Leave: Others`.
- Keeps unsupported OT purpose/travel/dinner fields blank instead of inventing
  values. No database migration or new dependency is required. This checkpoint
  is based directly on v8.8.129.

## v8.8.129 — Combined DTR, OT, and Leave Workbook

- Replaces the Admin `Reports` placeholder with a working company-scoped
  report generator and one shared date-range, employee, and department scope.
- Generates one Excel workbook with three sheets: `DTR Logs`, `Overtime File`, and
  `Leave File`.
- Formats DTR as two rows per employee (`Start Time` and `End Time`), horizontal
  date columns, company-calendar rest-day shading, work-location colors, and
  approved leave codes.
- Exports one row per computed OT record with employee ID/name, rendered date,
  calculated OT start/end, estimated hours, and regular/rest-day OT type.
- Exports approved VL, SL, EL, and every other configured leave type together,
  including request dates, reason, staged approvers, approval dates, and notes.
- Keeps OT purpose, travel fare/route, and dinner-break fields blank because
  the application does not currently collect those values; no fabricated data
  is inserted into reports.
- No database migration or new dependency is required. This checkpoint is
  based directly on v8.8.128.

## v8.8.117 — Fixed Notification Action Footer

- Separates the notification dropdown into a fixed header, independently
  scrollable notification list, and fixed bottom action footer.
- Keeps `Mark All as Read` and `Close` visible and stationary even when the
  notification list is long, without changing their existing behavior.
- Preserves bell-triggered panel visibility and clickable notification
  deep-links to the related HR modules.
- No database migration or dependency change is required.

## v8.8.116 — Seamless Transparent Announcement Descriptions

- Removes the visible border and background from the fixed announcement
  description viewport in both Employee and Admin previews.
- Retains vertical-only scrolling, exact line breaks, automatic long-line
  wrapping, and the proportional two-column layout.
- No database migration or dependency change is required.

## v8.8.115 — Seven-Row Attendance Views and Admin Search

- Limits the shared monthly Attendance/DTR/OT viewport to seven visible
  employee rows before vertical scrolling for Admin, Manager, and Leader
  views while retaining horizontal date scrolling and sticky headers.
- Keeps the administrator employee-name search above the monthly DTR and adds
  a visible filtered-result count.
- Restricts announcement description overflow to vertical scrolling only;
  long lines continue wrapping inside the fixed preview box.
- No database migration or dependency change is required.

## v8.8.114 — Preserved Announcement Line Breaks

- Preserves every manually entered line break from the Admin announcement
  description in both Admin and Employee previews.
- Continues to wrap uninterrupted long text within the fixed description box.
- Escapes HTML-like input before display while retaining the exact plain-text
  spacing and line structure.
- Removes the redundant `Description` label above the preview box.
- No database migration or dependency change is required.

## v8.8.113 — Native Dashboard Tabs and Fixed Description Panels

- Replaces the simulated `Dashboard | Announcements` segmented control with
  the same native underlined Streamlit tabs used by Leave Management.
- Keeps the Dashboard tab stateful and preserves unread count animation,
  notification deep-links, lazy content rendering, and per-user read state.
- Replaces the announcement description dropdown in both Employee and Admin
  previews with an always-visible, fixed-height, scrollable description box.
- Preserves the proportional two-column image and content layout.
- No database migration or dependency change is required.

## v8.8.112 — Two-Column Announcement Previews and Width Migration

- Uses the same two-column announcement preview in Admin and Employee
  portals: a larger proportional cover image on the left and the title,
  summary, pinned notice, and full description on the right.
- Keeps announcement images aspect-ratio safe while allowing them to fill the
  available preview column without stretching or cropping.
- Replaces deprecated Streamlit `use_container_width` arguments with the
  supported `width="stretch"` API throughout the application UI.
- No database migration or dependency change is required.

## v8.8.111 — Dashboard Tabs and DTR Layout Polish

- Removes the extra employee Dashboard introduction sentence.
- Places the monthly Year/Month attendance table before the expanded
  `Edit Attendance Record` section.
- Moves Announcements out of the sidebar and into a horizontal
  `Dashboard | Announcements` workspace tab beneath the welcome heading.
- Preserves the per-user unread count, subtle unread shake, category/search
  filters, notification deep-links, and read-state behavior.
- No database migration or dependency change is required.

## v8.8.110 — Editable Future Attendance and Separate Announcements

- Keeps the employee attendance editor expanded and restores its scroll
  position after saving instead of returning to the top of Dashboard.
- Allows employee-owned future attendance entries through year 2100.
- Uses approved VL, SL, or EL as the initial attendance value while allowing
  the employee or administrator to replace that default; every employee edit
  remains visible in Admin Portal `Attendance Edit History`.
- Moves employee announcements out of Dashboard into a separate
  `Announcements` navigation workspace with per-user unread count and shake.
- Uses a light, high-contrast calendar popup while preserving the approved
  dark closed input controls.

## v8.8.109 — Existing Account Login Schema Repair

- Verifies the login-required company schema even when the Streamlit process
  previously marked runtime initialization as complete.
- Repairs missing attendance/work-schedule columns non-destructively before
  existing accounts are queried.
- Preserves all companies, users, password hashes, uploads, and HR records.

## v8.8.108 — Date-Based Attendance History and Unread Announcements

- The employee attendance label is simplified to `Today's Work Status` while
  the current-day Login, Logout, and Save Status workflow stays unchanged.
- Employees may select any current or previous date and update their own Time
  In, Time Out, and Work Status. Future dates and other employees' records
  remain protected, and approved Leave Management statuses stay authoritative.
- Every employee edit continues to create an immutable before/after snapshot.
  The Admin Monthly DTR now includes an Attendance Edit History table showing
  the employee, attendance date, editor, edit timestamp, previous/new times,
  previous/new status, change type, and reason.
- Company Announcements is visually separated below Attendance/DTR and shows a
  per-user unread count beside its title. A subtle count animation appears when
  unread announcements exist and honors reduced-motion accessibility settings.
- Active announcement cards shown on the dashboard are marked viewed for that
  employee only; the active-announcement count remains visible separately.
- No database migration or dependency change is required.
## v8.8.134 — Combined Employee Overtime Request

- Adds one collapsible `Overtime Request` section after the employee attendance
  editor; no new sidebar item or horizontal workspace tab is introduced.
- Combines the DTR-prefilled filing form and `My Overtime Requests` history in
  the same section.
- Keeps Employee ID, Employee Name, and the original DTR reference read-only.
  Date Rendered, OT Start/End, and Estimated Hours are prefilled but editable;
  employee edits never modify the original attendance record.
- Collects employee-selected OT Type, required Purpose, optional Travel Fare
  with required Route, and the Yes/No Dinner Break flag.
- Records DTR-versus-request mismatches, pending/approved/rejected/cancelled
  status, reviewer comments, approver notification, and employee notification.
- Adds `Overtime Requests & Validation` on the Admin Attendance dashboard before
  `Admin Attendance Correction` for approval or rejection.
- Updates the combined OT worksheet: approved requests populate all supported
  columns and the final `CC` marker; DTR-only rows populate only employee ID,
  employee name, rendered date, and estimated hours, leaving unsupported values
  blank instead of guessing them.
- Creates the new `overtime_requests` table automatically and preserves all
  existing companies, accounts, DTR, leave, and report data.

## v8.8.135 — Application-Wide Stay-on-Current-View

- Preserves the current Admin or Employee page position after Save, Edit,
  Update, Save Changes, Approve, Reject, Cancel, upload, and other actions that
  trigger a Streamlit rerun.
- Restores the same vertical scroll position, active native horizontal tab,
  and open collapsible expander for the signed-in user and current page.
- Keeps existing keyed filters, dates, searches, selected records, and form
  choices through Streamlit Session State instead of resetting the workspace.
- Uses separate per-company, per-user, per-portal, and per-page browser state,
  so returning to a page restores its own last view without carrying another
  module's position into it.
- Cleans up browser event listeners on every rerun to prevent duplicated
  handlers or progressively repeated behavior.
- Removes remaining literal widget patterns that supplied both a default value
  and the same Session State key, preventing the earlier duplicate widget-state
  warning from returning.
- Does not use deprecated `use_container_width` parameters and adds no new
  package dependency or destructive database migration.

## v8.8.136 — Open Attendance Session Editor Fix

- Keeps Employee `Attendance / DTR` editable when an active or legacy work
  session has no recorded Time Out, instead of reading `.hour` from `None`.
- Applies the same null-safe timestamp handling to Admin Attendance Correction
  so incomplete sessions cannot trigger the equivalent rendering error there.
- Uses only a display fallback for missing timestamps. `Completed` stays false
  and Time Out remains `None` until the employee or administrator explicitly
  completes the session.
- Preserves the v8.8.135 page/tab/expander/scroll behavior and introduces no
  new widget default/Session State conflict, dependency, or database migration.

## v8.8.137 — Preventive Null and Warning Hardening

- Extends null-safe handling beyond the reported open-session error to Admin
  and Employee Attendance displays, clock feedback, OT DTR references, employee
  form text values, company-logo upload events, and legacy proxy-leave records.
- Prevents a cleared logo uploader from exposing `.name` or `.type` access and
  lets normal form validation handle empty employee fields instead of raising
  `AttributeError` from `.strip()`.
- Keeps attendance rows renderable when a malformed or legacy punch timestamp
  is absent, displaying a missing/open marker without inventing a saved punch.
- Handles nullable Chroma query arrays and ignores unusable localized OT session
  ends instead of failing retrieval or DTR prefill.
- Re-audits the application for keyed-widget default/Session State conflicts,
  deprecated `use_container_width`, and telemetry configuration regressions.
- Adds no dependency, destructive migration, or intended layout/design change.

## v8.8.138 — Admin Leave Management Syntax Hotfix

- Fixes the invalid multiline nested f-string in the Admin Leave Management
  request-details `Filing Source` row that prevented the application from
  importing and starting.
- Preserves the same labels for employee self-filing and Leader/Manager proxy
  filing, including the null-safe fallback for legacy or deleted filer links.
- Adds full-project Python compilation and a focused syntax regression check.
- Adds no dependency, database migration, or intended layout/design change.

## v8.8.139 — Application-Wide Iframe Warning Regression Fix

- Removes the deprecated `st.components.v1.html` calls reintroduced by the
  v8.8.135 current-view preserver and Employee Attendance editor restoration.
- Routes both trusted browser helpers through the existing supported
  `st.iframe` bridge while preserving their invisible layout and behavior.
- Extends the regression audit across every Python file under `ui` so newly
  added pages and helpers cannot silently reintroduce the deprecated API.
- Retains the v8.8.138 Admin Leave Management syntax fix and adds no dependency,
  database migration, or intended design/layout change.

## v8.8.140 — Lander Leave-Credit Column Demo Data

- Adds a recoverable test-data seeder for Lander Garcia (`191220`) that changes
  only the selected employee's VL/SL annual ledgers and preserves all other
  employees, leave requests, approvals, notifications, and attachments.
- Seeds a prior-year ending balance so the application's normal January
  carry-over rule produces visible, stable Beginning Credit values in 2026.
- The bundled test database displays VL as Beginning `30`, Credit `17`, Used
  `3`, Available `42`, Converted `2`; and SL as Beginning `8`, Credit `17`,
  Used `2`, Available `13`, Converted `10`. No hidden adjustment is needed to
  reconcile these visible demo values.
- Creates a timestamped SQLite backup before any write and records auditable
  demo transactions. The utility can be rerun from the project root after
  stopping Streamlit:

  ```powershell
  python -m scripts.seed_leave_credit_column_demo --confirm
  ```

- Retains the application-wide `components.html` prohibition and v8.8.139
  iframe regression audit. No UI, layout, dependency, or schema change.

## v8.8.141 — Tenure Credit Brackets and Correct Column Semantics

- Replaces the old five-year `+2` rule with non-cumulative completed-tenure
  brackets evaluated every January 1: 1–5 years = `15`, 6–10 = `17`,
  11–15 = `20`, 16–20 = `23`, and 21+ = `26` days for both VL and SL.
- The visible Credit column now shows only the current annual allocation or an
  approved event grant. Manual corrections remain part of Available Credits,
  Last Updated, and audit history but no longer inflate Credit.
- Beginning Credit remains the unused prior-year post-conversion balance.
  Converted to Cash remains the fixed excess above the VL/SL retention limit;
  later Used or Reserved days do not reverse that conversion.
- Updates Lander's bundled demo to a fully visible reconciliation: VL
  `30 + 17 - 3 - 2 = 42`; SL `8 + 17 - 2 - 10 = 13`.
- Retains the application-wide prohibition and regression scan for deprecated
  `components.html`. No UI layout, dependency, or database-schema change.

## v8.8.142 — Employee Excel Import, History, and Recoverable Archive

- Adds visible `Hired Date` and automatically calculated completed `Years of
  Service` columns to the active Employee List and employee Excel preview.
- Adds a downloadable `.xlsx` employee-import template above the existing
  manual Add Employee form. The complete batch is validated before saving,
  supports manager/leader assignment by employee number, and is committed as
  one database transaction so an unexpected row failure cannot leave a partial
  batch.
- Generates User ID after saving, defaults Clearance to `2 - User`, creates an
  editable username from all given-name initials plus surname, adds two random
  digits when that default already exists, and generates the editable temporary
  password pattern `XX_EMPLOYEE-NUMBER`. First-login password replacement stays
  mandatory.
- Provides a controlled downloadable import result containing the initial
  account credentials. Plain-text passwords are never written to Employee
  History.
- Adds Employee `History` for manual creation, Excel imports, edits, account
  changes, archive, restore, and eligible permanent deletion, including actor,
  timestamp, source, safe old/new values, and upload information.
- Moves every Resigned employee out of the active list into a recoverable
  `Archive`; the linked login account is disabled while all attendance, leave,
  OT, document, and history records remain intact. Restore reuses the same
  employee and account IDs, returns the employee to Employed, and reactivates
  the linked account after confirmation.
- Upgrades older databases non-destructively with archive metadata and the new
  history table. Existing resigned records are retained and marked archived.
- Preserves the v8.8.141 tenure-credit rules, current layout, current-view
  restoration, and the project-wide bans on deprecated `components.html` and
  `use_container_width`.

## v8.8.143 — Employee Excel Template Sample Row

- Adds one realistic, gray, italicized sample-input row beneath the downloadable
  Employee Excel Template headers so each column has a visible example.
- Automatically excludes the unchanged sample row from upload preview and
  import, preventing accidental employee creation.
- Explains in the Instructions sheet that administrators may delete the sample
  row or replace it with actual employee information.

## v8.8.144 — Dashboard Consolidation, Leave Workdays, History, and Search

- Moves Employees, User Accounts, Active Accounts, and Role metrics from the
  Admin Dashboard into Employee List before its live search field.
- Removes the duplicate Attendance/DTR/OT Reports horizontal tab; the sidebar
  Reports workspace remains the single report-generation destination.
- Bounds Attention Needed and Pending Leave Request to three visible rows with
  vertical scrolling, and limits the latter to pending approval/cancellation
  decisions.
- Adds a company-scoped Leave History tab for filing, staged reviews,
  withdrawals, immutable credit allocations, accruals, adjustments, usage, and
  cash conversion.
- Reorders Employee Leave Accounts to summary metrics, employee heading,
  department/employee selectors, entitlement information, and credit details.
- Uses the saved Attendance Schedule & OT Rules Regular Workdays calendar as
  the official leave-day basis. Holidays/unselected dates are excluded and
  selected catch-up weekend dates are included during preview, submission,
  final approval, DTR synchronization, reconciliation, history, and reports.
- Keeps leave filing available when credits are insufficient and clearly warns
  employees, proxy filers, approvers, and administrators about the automatic
  paid-credit/LWP split.
- Expands live search indexes to all relevant displayed columns while retaining
  tenant/role restrictions and excluding passwords or security secrets.
- Preserves current-view restoration and the project-wide bans on deprecated
  `components.html` and `use_container_width`.

## v8.8.145 — Explicit Monthly Work Rate Formula

- Locks Work Rate to `100 × Total Hours in Month ÷ (saved Regular Workdays in
  Month × Regular Paid Hours per Day)`.
- Uses the complete selected month's saved Attendance Schedule & OT Rules
  calendar: deselected holidays/rest days are excluded and selected catch-up
  workdays are included in the denominator.
- Uses DTR Total Hours only. Unpaid lunch and leave hours are not added, while
  rendered overtime remains included; Work Rate is intentionally not capped
  and may exceed `100%`.
- Keeps Leave Management credit, LWP, AM/PM, holiday, approval, and DTR rules
  unchanged.

## v8.8.146 — Employee Assignment References and Clean Logout Login

- Keeps the Employee Excel Template columns `Manager Employee Number` and
  `Leader Employee Number` unchanged while accepting Employee Number, exact
  full name, First Name + Last Name, or a unique first/last name.
- Resolves references only inside the authenticated company and supports both
  existing employed records and other employed rows in the same Excel upload.
  Ambiguous names are rejected with instructions to use Employee Number or a
  more complete unique name; inactive/resigned and self assignments remain
  blocked.
- Updates the template Instructions worksheet without changing its required
  header names or order.
- Completes Admin and Employee logout with a clean browser reload after the
  persistent token is removed, so the complete Welcome Back login layout is
  shown immediately without a manual refresh.
- Preserves the v8.8.145 Work Rate formula, current layout, current-view
  restoration, and the bans on deprecated `components.html` and
  `use_container_width`.

## v8.8.147 — Editable Word Company Form Downloads

- Renames `Download Original Form` to `Download Form` in both the Admin and
  Employee Company Form/Documents workspaces.
- Converts a stored PDF template into an editable `.docx` download while
  keeping the original stored PDF and its preview unchanged. Existing DOCX and
  other supported source formats continue to download directly.
- Keeps Fill / Submit unchanged: a completed DOCX remains a DOCX submission;
  no automatic DOCX-to-PDF conversion is performed.
- Caches validated conversions briefly to avoid repeating expensive work on
  every Streamlit rerun and shows a controlled message for corrupt,
  password-protected, or otherwise unconvertible PDFs.
- Adds the pinned `pdf2docx` runtime dependency and a warning-free compatible
  PyMuPDF range, while preserving the current layout, current-view restoration,
  and the bans on deprecated `components.html` and `use_container_width`.

## v8.8.148 — Vacation Leave Utilization

- Adds **Leave Utilization** after Available Credits in the Admin and Employee
  leave-credit tables. Vacation Leave shows Required, Used, and Remaining;
  every other leave type shows N/A.
- In 2026, counts only approved paid VL consumed from August 17 through
  December 31 while requiring 50% of the annual VL allocation. From 2027
  onward, the full January-through-December period uses the same 50% target.
- Keeps the target monitoring-only during the year. It never reduces Available
  Credits in advance. Whole-day paid VL counts as one day and AM/PM paid VL as
  one-half day; pending, rejected, cancelled, LWP, EL, SL, and other leave do
  not count.
- Forfeits the unmet target once at year end before carryover. The forfeiture
  is neither carried over nor converted to cash. Remaining VL still
  accumulates under the existing 45-day retention and conversion rule.
- Records the result in Leave History and sends idempotent reminders to the
  employee, direct Leader, direct Manager, and active administrators near year
  end, on target completion, and when an unmet amount is forfeited.
- Preserves current layout, current-view restoration, and the bans on
  deprecated `components.html` and `use_container_width`.

## v8.8.158 — Project-wide Friendly Action Validation

- Adds one shared warning formatter for expected Pydantic, service, file, and
  integration failures across Admin, Employee, and authentication actions.
- Replaces raw exception strings, Pydantic diagnostic payloads, and technical
  documentation URLs with concise field-aware warnings shown only after a
  save, edit, upload, submit, approval, archive, restore, or login attempt.
- Attendance session validation now explains that every session before the
  final session requires a Time Out, while retaining the existing data rule
  that only the final session may remain open.
- Keeps the current form values, tab/view behavior, permissions, database
  services, and successful action flows unchanged. Unexpected exceptions
  continue to use the existing safe generic error handling.
- Preserves the bans on deprecated `components.html` and
  `use_container_width`.

## v8.8.157 — Compact Employee Checklist and Safe Tab Restore

- Makes `Employee Portal > Onboarding > Checklist` compact and readable by
  keeping each item's details, status, related-workspace action, and completion
  action in one aligned row. Long descriptions continue to wrap naturally.
- Preserves the existing checklist service, permissions, automatic/admin
  confirmation rules, employee completion toggle, status feedback, and exact
  related-workspace links.
- Prevents the employee equivalent of the Streamlit widget-state exception by
  queuing `Checklist` as the next tab and applying it before the keyed tabs are
  instantiated on the following rerun.
- Preserves current records and navigation, and introduces no deprecated
  `components.html` or `use_container_width` calls.

## v8.8.156 — Stable Onboarding Tab State and Visible Benefit Actions

- Fixes the Streamlit widget-state exception caused by writing directly to
  `employees_active_tab` after the Employees tabs were instantiated. Onboarding
  actions now queue the target parent and sub-tab and apply them safely before
  those keyed tab widgets are created on the following rerun.
- Keeps `Edit Benefit` and `Delete / Move Benefit to Archive` visible in
  Benefits Management even when there are no active benefits; each section
  displays a clear no-record message until an active benefit is added or
  restored.
- Preserves safe archive/restore behavior, current-view restoration, existing
  design and records, and the bans on deprecated `components.html` and
  `use_container_width`.

## v8.8.155 — Onboarding and Benefits Safe Archive

- Adds confirmation-protected safe-delete actions to `Checklist Setup` and
  `Benefits Management`. Records are moved to Archive instead of being
  permanently deleted.
- Archived checklist items disappear from the Employee Checklist while their
  existing per-employee progress remains stored. Restoring an item returns it
  together with that progress.
- Archived benefits disappear from Employee Onboarding Benefits while the
  company record remains available for restoration.
- Keeps Add/Edit behavior, company isolation, exact active management tabs
  after archive or restore, and the bans on deprecated `components.html` and
  `use_container_width`.

## v8.8.154 — Consolidated Employee Onboarding and Benefits

- Consolidates the Employee Portal `Benefits` sidebar placeholder into the
  permanent `Onboarding` workspace with `Overview`, `Checklist`, and `Benefits`
  tabs. Older Benefits bookmarks open the new Benefits sub-tab automatically.
- Adds company-scoped onboarding checklist definitions, per-employee progress,
  and benefit records. Automatic items can follow password change, first Time
  In, and completion of all assigned training; employee- and admin-confirmed
  items remain explicitly controlled.
- Adds `Employees > Onboarding Management` in the Admin Portal with `Employee
  Progress`, `Checklist Setup`, and `Benefits Management` sub-tabs. Checklist
  links open existing policy, form, attendance, leave, reports, HR contact, and
  FAQ workspaces instead of duplicating their records.
- Keeps Benefits available after onboarding completion and updates employee
  FAQ and Chat Assistant links to open the exact Onboarding Benefits view.
- Preserves company isolation, existing records, exact navigation, active tabs
  after saving, and the bans on deprecated `components.html` and
  `use_container_width`.

## v8.8.153 — Readable Admin Leave Request Table

- Assigns an explicit width to all twelve columns in `Leave Management > Leave
  Requests` instead of leaving Status and Email to collapse into narrow cells.
- Widens Duration, Reason, Manager, and Status while keeping horizontal table
  scrolling, filters, live search, request selection, and details unchanged.
- Preserves the existing layout and the bans on deprecated `components.html`
  and `use_container_width`.

## v8.8.152 — Employee Reports Sidebar Placement

- Moves the Employee Portal `Reports` sidebar item between `Company Policies`
  and `Benefits` without changing its personal-scope workbook functionality.
- Preserves the default FAQ, exact internal links, current layout, and the bans
  on deprecated `components.html` and `use_container_width`.

## v8.8.151 — Employee Personal Reports and Default FAQ

- Adds an employee `Reports` workspace that generates one personal Excel
  workbook with `DTR Logs`, `Overtime File`, and `Leave File` worksheets.
- Enforces the signed-in employee ID as the complete report scope; there is no
  employee or department selector and no other employee record is exported.
- Reuses the payroll-compatible Admin report generator so both portals retain
  the same names, codes, dates, headers, fills, filters, and sheet layout.
- Replaces the employee FAQ placeholder with default questions, complete direct
  answers, and buttons that open the exact related employee workspace when one
  exists.
- Keeps external email, SMS, and actionable-notification work explicitly on
  hold. Preserves current-view restoration and the bans on deprecated
  `components.html` and `use_container_width`.

## v8.8.150 — Attendance Hub and Leave Conversion Report

- Replaces the employee Dashboard's separate Login, Logout, and Save Status
  controls with one full-width, persisted-state `Time In` / `Time Out` button.
- Automatically saves Today's Work Status during Time In; after a completed
  Time Out, the button remains disabled across refresh and relogin.
- Adds an `Attendance Hub` sidebar workspace to both portals. The employee Hub
  contains the monthly table, attendance editor, and overtime request workflow;
  the admin Hub contains the company table, schedule/OT rules, OT validation,
  corrections, and edit history. Dashboard tables remain available without
  duplicating punch or management controls.
- Adds `Reports > Leave Conversion to Cash` with payroll-name formatting,
  previous-year VL/SL balances, current VL credit, separate converted VL/SL,
  total converted days, and a deliberately blank Total Conversion Amount.
- Preserves existing business services, permissions, records, current-view
  restoration, warning-free widget state, and Components v2 usage.

## v8.8.149 — January-Start Leave Utilization Demo

- Treats Vacation Leave utilization as active from January 1, 2026 so the
  annual VL Used column and utilization Used value are visibly consistent.
- Uses the official posted VL ledger for existing/sample data while excluding
  Emergency Leave that was paid from the VL balance.
- Updates the Lander demo to show Used 4, Required 8.5, utilization Used 4,
  Remaining 4.5, and Available Credits 41. This makes the feature behavior
  directly verifiable in both Admin and Employee leave tables.
- Retains the 50% annual target, year-end forfeiture, notifications, history,
  carryover, and cash-conversion behavior from v8.8.148.

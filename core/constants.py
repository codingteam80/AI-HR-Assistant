"""Shared application constants."""

SUPPORTED_THEMES = ("light",)
DEFAULT_PAGE = "Dashboard"
DEFAULT_COMPANY_THEME_COLOR = "#4338E8"

SYSTEM_ROLES = (
    "super_admin",
    "company_admin",
    "hr_admin",
    "manager",
    "employee",
)

SYSTEM_ROLE_DESCRIPTIONS = {
    "super_admin": "Platform-level administrator.",
    "company_admin": "Administrator for one company.",
    "hr_admin": "Human Resources administrator.",
    "manager": "Employee manager and approver.",
    "employee": "Standard employee account.",
}

USER_NAVIGATION = (
    "Dashboard",
    "Chat Assistant",
    "Attendance Hub",
    "Leave Management",
    "Reports",
    "Company Form/Documents",
    "Company Policies",
    "Onboarding",
    "HR Contacts",
    "FAQ",
)


# Simple account clearance used by the Employee Master Record.
# The legacy roles table remains internal for database compatibility.
CLEARANCE_ADMIN = 1
CLEARANCE_USER = 2

CLEARANCE_LABELS = {
    CLEARANCE_ADMIN: "Admin",
    CLEARANCE_USER: "User",
}

VALID_CLEARANCES = tuple(CLEARANCE_LABELS)

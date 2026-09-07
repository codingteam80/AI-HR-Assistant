"""Register all SQLAlchemy models."""

from models.announcement import Announcement
from models.audit_event import AuditEvent
from models.attendance_correction import AttendanceCorrection
from models.attendance_record import AttendanceRecord
from models.attendance_session import AttendanceSession
from models.auth_session import AuthSession
from models.auth_session_navigation import AuthSessionNavigation
from models.auth_session_preference import AuthSessionPreference
from models.company import Company
from models.company_workday import CompanyWorkday
from models.company_form import CompanyForm
from models.company_form_submission import CompanyFormSubmission
from models.department import Department
from models.employee import Employee
from models.employee_history import EmployeeHistory
from models.employee_disciplinary_record import EmployeeDisciplinaryRecord
from models.employee_training import EmployeeTraining
from models.event_reminder import EventReminder
from models.hr_policy import HRPolicy
from models.hr_policy_document import HRPolicyDocument
from models.hr_policy_section import HRPolicySection
from models.policy_violation import PolicyViolation
from models.hr_contact import HRContact
from models.leave_balance import LeaveBalance
from models.leave_credit_transaction import LeaveCreditTransaction
from models.leave_request import LeaveRequest
from models.leave_type import LeaveType
from models.notification import Notification
from models.onboarding import (
    CompanyBenefit,
    EmployeeOnboardingProgress,
    OnboardingChecklistItem,
)
from models.overtime_request import OvertimeRequest
from models.shifting_credit import ShiftingCredit
from models.password_reset_token import PasswordResetToken
from models.role import Role
from models.user import User

__all__ = [
    "Announcement",
    "AuditEvent",
    "AttendanceCorrection",
    "AttendanceRecord",
    "AttendanceSession",
    "AuthSession",
    "AuthSessionNavigation",
    "AuthSessionPreference",
    "Company",
    "CompanyWorkday",
    "CompanyForm",
    "CompanyFormSubmission",
    "Department",
    "Employee",
    "EmployeeHistory",
    "EmployeeDisciplinaryRecord",
    "EmployeeTraining",
    "EventReminder",
    "HRPolicy",
    "HRPolicyDocument",
    "HRPolicySection",
    "PolicyViolation",
    "HRContact",
    "LeaveBalance",
    "LeaveCreditTransaction",
    "LeaveRequest",
    "LeaveType",
    "Notification",
    "CompanyBenefit",
    "EmployeeOnboardingProgress",
    "OnboardingChecklistItem",
    "OvertimeRequest",
    "ShiftingCredit",
    "PasswordResetToken",
    "Role",
    "User",
]

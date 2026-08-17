"""Register all SQLAlchemy models."""

from models.announcement import Announcement
from models.attendance_correction import AttendanceCorrection
from models.attendance_record import AttendanceRecord
from models.attendance_session import AttendanceSession
from models.company import Company
from models.company_workday import CompanyWorkday
from models.company_form import CompanyForm
from models.company_form_submission import CompanyFormSubmission
from models.department import Department
from models.employee import Employee
from models.employee_history import EmployeeHistory
from models.employee_training import EmployeeTraining
from models.event_reminder import EventReminder
from models.hr_policy import HRPolicy
from models.hr_policy_document import HRPolicyDocument
from models.hr_policy_section import HRPolicySection
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
from models.password_reset_token import PasswordResetToken
from models.role import Role
from models.user import User

__all__ = [
    "Announcement",
    "AttendanceCorrection",
    "AttendanceRecord",
    "AttendanceSession",
    "Company",
    "CompanyWorkday",
    "CompanyForm",
    "CompanyFormSubmission",
    "Department",
    "Employee",
    "EmployeeHistory",
    "EmployeeTraining",
    "EventReminder",
    "HRPolicy",
    "HRPolicyDocument",
    "HRPolicySection",
    "LeaveBalance",
    "LeaveCreditTransaction",
    "LeaveRequest",
    "LeaveType",
    "Notification",
    "CompanyBenefit",
    "EmployeeOnboardingProgress",
    "OnboardingChecklistItem",
    "OvertimeRequest",
    "PasswordResetToken",
    "Role",
    "User",
]

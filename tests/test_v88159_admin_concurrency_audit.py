"""Regression coverage for concurrent Admin edits and the central trail."""

from pathlib import Path
import tempfile
import unittest

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

import models  # noqa: F401 - registers every mapped table
from database.audit_listener import install_audit_listener
from database.base import Base
from models.audit_event import AuditEvent
from models.company import Company
from models.employee import Employee
from models.role import Role
from models.user import User
from schemas.admin_management_schema import EmployeeMasterUpdate
from services.admin_management_service import AdminManagementService
from services.audit_context import clear_audit_actor, set_audit_actor
from services.audit_trail_service import AuditTrailService
from services.edit_conflict import EditConflictError


class AdminConcurrencyAuditTest(unittest.TestCase):
    """A stale Admin form must never overwrite the newest saved record."""

    def setUp(self) -> None:
        self._temporary_directory = tempfile.TemporaryDirectory()
        database_path = Path(self._temporary_directory.name) / "audit-test.db"
        self.engine = create_engine(f"sqlite:///{database_path}", future=True)
        Base.metadata.create_all(self.engine)
        install_audit_listener()
        self.Session = sessionmaker(
            bind=self.engine,
            autoflush=False,
            expire_on_commit=False,
        )

        with self.Session() as session:
            company = Company(code="CONFLICT", name="Conflict Test Company")
            session.add(company)
            session.flush()
            admin_role = Role(
                company_id=company.id,
                name="company_admin",
                is_system_role=True,
                is_active=True,
            )
            employee_role = Role(
                company_id=company.id,
                name="employee",
                is_system_role=True,
                is_active=True,
            )
            session.add_all([admin_role, employee_role])
            session.flush()

            admin_a = User(
                company_id=company.id,
                role_id=admin_role.id,
                clearance=1,
                username="admin.a",
                email="admin.a@example.com",
                password_hash="test-hash",
                must_change_password=False,
            )
            admin_b = User(
                company_id=company.id,
                role_id=admin_role.id,
                clearance=1,
                username="admin.b",
                email="admin.b@example.com",
                password_hash="test-hash",
                must_change_password=False,
            )
            target_user = User(
                company_id=company.id,
                role_id=employee_role.id,
                clearance=2,
                username="target.user",
                email="target@example.com",
                password_hash="test-hash",
                must_change_password=False,
            )
            session.add_all([admin_a, admin_b, target_user])
            session.flush()

            session.add_all(
                [
                    Employee(
                        company_id=company.id,
                        user_id=admin_a.id,
                        employee_number="ADMIN-A",
                        first_name="Alice",
                        last_name="Administrator",
                        work_email=admin_a.email,
                    ),
                    Employee(
                        company_id=company.id,
                        user_id=admin_b.id,
                        employee_number="ADMIN-B",
                        first_name="Ben",
                        last_name="Administrator",
                        work_email=admin_b.email,
                    ),
                    Employee(
                        company_id=company.id,
                        user_id=target_user.id,
                        employee_number="EMP-001",
                        first_name="Taylor",
                        last_name="Employee",
                        work_email=target_user.email,
                        job_title="Original Position",
                    ),
                ]
            )
            session.commit()
            self.company_id = company.id
            self.admin_a_id = admin_a.id
            self.admin_b_id = admin_b.id
            self.target_employee_id = target_user.employee.id

    def tearDown(self) -> None:
        clear_audit_actor()
        self.engine.dispose()
        self._temporary_directory.cleanup()

    def _request(self, *, version: int, job_title: str) -> EmployeeMasterUpdate:
        return EmployeeMasterUpdate(
            company_id=self.company_id,
            employee_id=self.target_employee_id,
            expected_edit_version=version,
            employee_number="EMP-001",
            first_name="Taylor",
            last_name="Employee",
            work_email="target@example.com",
            job_title=job_title,
            employment_status="employed",
            username="target.user",
            clearance=2,
        )

    def test_stale_save_is_blocked_and_attributed(self) -> None:
        opened_version = 1

        set_audit_actor(
            company_id=self.company_id,
            user_id=self.admin_a_id,
            module="Employees",
        )
        with self.Session() as session:
            saved = AdminManagementService(session).update_employee_master_record(
                self._request(version=opened_version, job_title="Admin A Position"),
                current_user_id=self.admin_a_id,
            )
            self.assertEqual(saved.edit_version, 2)
            self.assertEqual(saved.last_edited_by_user_id, self.admin_a_id)

        set_audit_actor(
            company_id=self.company_id,
            user_id=self.admin_b_id,
            module="Employees",
        )
        with self.Session() as session:
            with self.assertRaises(EditConflictError) as caught:
                AdminManagementService(session).update_employee_master_record(
                    self._request(version=opened_version, job_title="Admin B Position"),
                    current_user_id=self.admin_b_id,
                )
            self.assertIn("Alice Administrator", str(caught.exception))

        with self.Session() as session:
            latest = session.get(Employee, self.target_employee_id)
            self.assertEqual(latest.job_title, "Admin A Position")
            self.assertEqual(latest.edit_version, 2)

            blocked = session.scalar(
                select(AuditEvent).where(
                    AuditEvent.company_id == self.company_id,
                    AuditEvent.result == "conflict_blocked",
                )
            )
            self.assertIsNotNone(blocked)
            self.assertEqual(blocked.actor_user_id, self.admin_b_id)

            entries = AuditTrailService(session).list_entries(self.company_id)
            self.assertTrue(
                any(
                    entry.result == "successful"
                    and entry.actor_user_id == self.admin_a_id
                    for entry in entries
                )
            )
            self.assertTrue(
                any(
                    entry.result == "conflict_blocked"
                    and entry.actor_user_id == self.admin_b_id
                    for entry in entries
                )
            )


if __name__ == "__main__":
    unittest.main()

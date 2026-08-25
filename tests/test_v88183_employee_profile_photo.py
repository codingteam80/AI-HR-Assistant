"""v8.8.183 employee profile-photo regression checks."""

from __future__ import annotations

from io import BytesIO
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

import models  # noqa: F401 - register the full metadata graph
from database.base import Base
from models.company import Company
from models.employee import Employee
from models.employee_history import EmployeeHistory
from models.role import Role
from models.user import User
from modules.employees.profile_image_storage import EmployeeProfileImageStorage
import services.employee_profile_image_service as profile_service_module
import services.admin_management_service as admin_management_module
from services.employee_profile_image_service import EmployeeProfileImageService
from services.admin_management_service import AdminManagementService
from schemas.admin_management_schema import EmployeeDeleteRequest


ROOT = Path(__file__).resolve().parents[1]


def _source(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def _image_bytes(fmt: str = "JPEG", size: tuple[int, int] = (900, 500)) -> bytes:
    image = Image.new("RGB", size, (90, 140, 190))
    output = BytesIO()
    image.save(output, format=fmt)
    return output.getvalue()


def test_version_model_settings_and_runtime_upgrade_marker() -> None:
    assert 'app_version: str = "0.8.8.183"' in _source("config/settings.py")
    assert "APP_VERSION=0.8.8.183" in _source(".env")
    assert "APP_VERSION=0.8.8.183" in _source(".env.example")
    assert "profile_image_filename" in _source("models/employee.py")
    assert '"profile_image_filename"' in _source("database/runtime_schema.py")
    assert "ADD COLUMN profile_image_filename VARCHAR(255)" in _source(
        "database/schema_upgrade.py"
    )
    settings = _source("config/settings.py")
    assert 'employee_profile_image_dir: str = "data/uploads/employee_profiles"' in settings
    assert "employee_profile_image_max_mb: int = 5" in settings


def test_storage_validates_actual_image_and_normalizes_to_square_png(tmp_path: Path) -> None:
    storage = EmployeeProfileImageStorage(tmp_path, max_mb=5)
    prepared = storage.prepare_png(
        file_name="portrait.jpg",
        content=_image_bytes("JPEG", (900, 500)),
        content_type="image/jpeg",
    )

    with Image.open(BytesIO(prepared)) as normalized:
        assert normalized.format == "PNG"
        assert normalized.size == (512, 512)

    with pytest.raises(ValueError, match="not a valid PNG"):
        storage.prepare_png(
            file_name="renamed.png",
            content=_image_bytes("JPEG"),
            content_type="image/png",
        )

    with pytest.raises(ValueError, match="not a valid image"):
        storage.prepare_png(
            file_name="fake.jpg",
            content=b"not an image",
            content_type="image/jpeg",
        )


def test_storage_is_company_employee_scoped_and_replace_remove_are_reversible(
    tmp_path: Path,
) -> None:
    storage = EmployeeProfileImageStorage(tmp_path, max_mb=5)
    first = storage.prepare_png(
        file_name="first.jpg",
        content=_image_bytes("JPEG", (700, 500)),
        content_type="image/jpeg",
    )
    second = storage.prepare_png(
        file_name="second.png",
        content=_image_bytes("PNG", (500, 800)),
        content_type="image/png",
    )

    initial = storage.stage_replace(company_id=1, employee_id=10, prepared_png=first)
    initial.finalize()
    assert storage.read(company_id=1, employee_id=10, filename="profile.png") == first
    assert storage.read(company_id=2, employee_id=10, filename="profile.png") is None
    assert storage.read(company_id=1, employee_id=11, filename="profile.png") is None

    replacement = storage.stage_replace(company_id=1, employee_id=10, prepared_png=second)
    assert storage.read(company_id=1, employee_id=10, filename="profile.png") == second
    replacement.rollback()
    assert storage.read(company_id=1, employee_id=10, filename="profile.png") == first

    removal = storage.stage_remove(company_id=1, employee_id=10, filename="profile.png")
    assert storage.read(company_id=1, employee_id=10, filename="profile.png") is None
    removal.rollback()
    assert storage.read(company_id=1, employee_id=10, filename="profile.png") == first

    final_removal = storage.stage_remove(company_id=1, employee_id=10, filename="profile.png")
    final_removal.finalize()
    assert storage.read(company_id=1, employee_id=10, filename="profile.png") is None


def _seed_profile_db(session: Session):
    company = Company(code="TEST", name="Test Company", is_active=True)
    other_company = Company(code="OTHER", name="Other Company", is_active=True)
    session.add_all([company, other_company])
    session.flush()

    employee_role = Role(
        company_id=company.id,
        name="employee",
        description="Employee",
        is_active=True,
    )
    admin_role = Role(
        company_id=company.id,
        name="company_admin",
        description="Admin",
        is_active=True,
    )
    other_role = Role(
        company_id=other_company.id,
        name="employee",
        description="Employee",
        is_active=True,
    )
    session.add_all([employee_role, admin_role, other_role])
    session.flush()

    self_user = User(
        company_id=company.id,
        role_id=employee_role.id,
        clearance=2,
        username="selfuser",
        email="self@example.com",
        password_hash="hash",
        is_active=True,
        must_change_password=False,
    )
    other_user = User(
        company_id=company.id,
        role_id=employee_role.id,
        clearance=2,
        username="otheruser",
        email="other@example.com",
        password_hash="hash",
        is_active=True,
        must_change_password=False,
    )
    admin_user = User(
        company_id=company.id,
        role_id=admin_role.id,
        clearance=1,
        username="adminuser",
        email="admin@example.com",
        password_hash="hash",
        is_active=True,
        must_change_password=False,
    )
    foreign_user = User(
        company_id=other_company.id,
        role_id=other_role.id,
        clearance=2,
        username="foreignuser",
        email="foreign@example.com",
        password_hash="hash",
        is_active=True,
        must_change_password=False,
    )
    session.add_all([self_user, other_user, admin_user, foreign_user])
    session.flush()

    self_employee = Employee(
        company_id=company.id,
        user_id=self_user.id,
        employee_number="E-001",
        first_name="Self",
        last_name="Employee",
        employment_status="employed",
    )
    other_employee = Employee(
        company_id=company.id,
        user_id=other_user.id,
        employee_number="E-002",
        first_name="Other",
        last_name="Employee",
        employment_status="employed",
    )
    foreign_employee = Employee(
        company_id=other_company.id,
        user_id=foreign_user.id,
        employee_number="X-001",
        first_name="Foreign",
        last_name="Employee",
        employment_status="employed",
    )
    session.add_all([self_employee, other_employee, foreign_employee])
    session.commit()
    return company, other_company, self_user, other_user, admin_user, self_employee, other_employee, foreign_employee


def test_service_enforces_self_vs_admin_scope_and_records_history(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    profile_root = tmp_path / "profiles"
    monkeypatch.setattr(
        profile_service_module,
        "get_settings",
        lambda: SimpleNamespace(
            employee_profile_image_dir=str(profile_root),
            employee_profile_image_max_mb=5,
        ),
    )

    with Session(engine) as session:
        (
            company,
            other_company,
            self_user,
            _other_user,
            admin_user,
            self_employee,
            other_employee,
            foreign_employee,
        ) = _seed_profile_db(session)
        company_id = company.id
        other_company_id = other_company.id
        self_user_id = self_user.id
        admin_user_id = admin_user.id
        self_employee_id = self_employee.id
        other_employee_id = other_employee.id
        foreign_employee_id = foreign_employee.id

    photo = _image_bytes("JPEG")
    with Session(engine) as session:
        service = EmployeeProfileImageService(session)
        service.save_profile_image(
            company_id=company_id,
            employee_id=self_employee_id,
            actor_user_id=self_user_id,
            actor_clearance=2,
            file_name="me.jpg",
            content=photo,
            content_type="image/jpeg",
        )

    with Session(engine) as session:
        saved = session.scalar(select(Employee).where(Employee.id == self_employee_id))
        assert saved is not None
        assert saved.profile_image_filename == "profile.png"
        history = list(
            session.scalars(
                select(EmployeeHistory).where(
                    EmployeeHistory.employee_id == self_employee_id
                )
            ).all()
        )
        assert history[-1].action_type == "profile_photo_uploaded"
        assert history[-1].source == "profile_photo"

    with Session(engine) as session:
        service = EmployeeProfileImageService(session)
        with pytest.raises(PermissionError, match="only manage your own"):
            service.save_profile_image(
                company_id=company_id,
                employee_id=other_employee_id,
                actor_user_id=self_user_id,
                actor_clearance=2,
                file_name="other.jpg",
                content=photo,
                content_type="image/jpeg",
            )

    with Session(engine) as session:
        service = EmployeeProfileImageService(session)
        service.save_profile_image(
            company_id=company_id,
            employee_id=other_employee_id,
            actor_user_id=admin_user_id,
            actor_clearance=1,
            file_name="other.jpg",
            content=photo,
            content_type="image/jpeg",
        )
        with pytest.raises(ValueError, match="does not exist in this company"):
            service.get_profile_image_bytes(
                company_id=company_id,
                employee_id=foreign_employee_id,
                actor_user_id=admin_user_id,
                actor_clearance=1,
            )
        with pytest.raises(PermissionError, match="only manage your own"):
            service.get_profile_image_bytes(
                company_id=other_company_id,
                employee_id=foreign_employee_id,
                actor_user_id=admin_user_id,
                actor_clearance=2,
            )

    with Session(engine) as session:
        service = EmployeeProfileImageService(session)
        assert service.remove_profile_image(
            company_id=company_id,
            employee_id=self_employee_id,
            actor_user_id=self_user_id,
            actor_clearance=2,
        ) is True

    with Session(engine) as session:
        saved = session.scalar(select(Employee).where(Employee.id == self_employee_id))
        assert saved is not None and saved.profile_image_filename is None
        actions = list(
            session.scalars(
                select(EmployeeHistory.action_type).where(
                    EmployeeHistory.employee_id == self_employee_id
                )
            ).all()
        )
        assert actions == ["profile_photo_uploaded", "profile_photo_removed"]



def test_permanent_employee_delete_removes_private_profile_photo(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    profile_root = tmp_path / "profiles"
    settings = SimpleNamespace(
        employee_profile_image_dir=str(profile_root),
        employee_profile_image_max_mb=5,
    )
    monkeypatch.setattr(profile_service_module, "get_settings", lambda: settings)
    monkeypatch.setattr(admin_management_module, "get_settings", lambda: settings)

    with Session(engine) as session:
        (
            company,
            _other_company,
            _self_user,
            _other_user,
            admin_user,
            _self_employee,
            other_employee,
            _foreign_employee,
        ) = _seed_profile_db(session)
        company_id = company.id
        admin_user_id = admin_user.id
        target_employee_id = other_employee.id

    with Session(engine) as session:
        EmployeeProfileImageService(session).save_profile_image(
            company_id=company_id,
            employee_id=target_employee_id,
            actor_user_id=admin_user_id,
            actor_clearance=1,
            file_name="target.jpg",
            content=_image_bytes("JPEG"),
            content_type="image/jpeg",
        )

    profile_path = (
        profile_root
        / f"company_{company_id}"
        / f"employee_{target_employee_id}"
        / "profile.png"
    )
    assert profile_path.is_file()

    with Session(engine) as session:
        result = AdminManagementService(session).delete_employee_master_record(
            EmployeeDeleteRequest(
                company_id=company_id,
                employee_id=target_employee_id,
                permanent_delete_acknowledged=True,
            ),
            current_user_id=admin_user_id,
        )
        assert result.employee_id == target_employee_id

    assert not profile_path.exists()
    assert not profile_path.parent.exists()
    with Session(engine) as session:
        assert session.scalar(
            select(Employee).where(Employee.id == target_employee_id)
        ) is None

def test_ui_scope_has_employee_self_admin_management_and_default_avatar() -> None:
    dashboard = _source("ui/pages/user/dashboard_page.py")
    employees = _source("ui/pages/admin/employees_page.py")
    topbar = _source("ui/components/topbar.py")
    component = _source("ui/components/employee_profile_photo.py")
    service = _source("services/employee_profile_image_service.py")

    assert "render_profile_photo_manager" in dashboard
    assert "employee_id=current_user.employee_id" in dashboard
    assert "render_profile_photo_manager" in employees
    assert "employee_id=selected_id" in employees
    assert "profile_avatar_html" in topbar
    assert "hr-profile-avatar-initials" in component
    assert 'type=["jpg", "jpeg", "png"]' in component
    assert "prepare_preview" in component
    assert "actor_clearance" in service
    assert "You may only manage your own profile photo." in service
    assert "profile_photo_uploaded" in service
    assert "profile_photo_replaced" in service
    assert "profile_photo_removed" in service


def test_profile_photo_widget_keys_do_not_mix_widget_defaults_with_manual_state() -> None:
    component = _source("ui/components/employee_profile_photo.py")
    # Uploader generation is stored under a separate non-widget key, avoiding
    # the Streamlit default/session-state collision fixed in v8.8.180.
    assert "generation_key =" in component
    assert 'key=f"{key_prefix}_profile_photo_upload_{generation}"' in component
    assert "st.session_state[generation_key] = generation + 1" in component
    assert "st.session_state[f\"{key_prefix}_profile_photo_upload" not in component

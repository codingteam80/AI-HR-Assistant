"""v8.8.75 Company Profile identity and branding regression tests."""

from io import BytesIO
from pathlib import Path

from PIL import Image
from pydantic import SecretStr
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import models  # noqa: F401
from authentication.auth_service import AuthService, AuthenticationError
from config.settings import Settings
from database.base import Base
from modules.company_branding.company_logo_storage import (
    extract_logo_theme_colors,
)
from schemas.organization_schema import CompanyProfileUpdate
from scripts.create_initial_data import seed_initial_data
from services.organization_service import OrganizationService


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _settings(code: str, email: str) -> Settings:
    return Settings(
        _env_file=None,
        database_url="sqlite+pysqlite:///:memory:",
        initial_company_code=code,
        initial_company_name=f"{code} Company",
        initial_admin_username=f"{code.lower()}admin",
        initial_admin_email=email,
        initial_admin_password=SecretStr("Temporary123!"),
        initial_admin_employee_number=f"{code}-001",
        initial_admin_first_name="System",
        initial_admin_last_name="Administrator",
    )


def _factory():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)


def _brand_logo_bytes() -> bytes:
    image = Image.new("RGBA", (500, 180), (255, 255, 255, 0))

    for x in range(40, 360):
        for y in range(35, 145):
            image.putpixel((x, y), (35, 185, 35, 255))

    for x in range(365, 455):
        for y in range(55, 125):
            image.putpixel((x, y), (18, 85, 155, 255))

    output = BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()


def test_company_profile_schema_normalizes_login_code() -> None:
    request = CompanyProfileUpdate(
        company_id=1,
        code="  tsukiden-ph  ",
        name="  Tsukiden Global Solution Inc.  ",
    )

    assert request.code == "TSUKIDEN-PH"
    assert request.name == "Tsukiden Global Solution Inc."


def test_company_code_can_change_without_changing_tenant_id() -> None:
    factory = _factory()

    with factory() as session:
        seed = seed_initial_data(
            session,
            _settings("DEFAULT", "admin.default@example.com"),
        )
        company_id = seed["company"].id
        user_company_id = seed["admin_user"].company_id
        updated = OrganizationService(session).update_company_profile(
            CompanyProfileUpdate(
                company_id=company_id,
                code="tsukiden",
                name="Tsukiden Global Solution Inc.",
            )
        )

        assert updated.id == company_id
        assert updated.code == "TSUKIDEN"
        assert updated.name == "Tsukiden Global Solution Inc."
        assert user_company_id == company_id
        assert seed["admin_user"].company_id == company_id



def test_changed_company_code_is_the_new_login_code() -> None:
    factory = _factory()

    with factory() as session:
        seed = seed_initial_data(
            session,
            _settings("DEFAULT", "login.rename@example.com"),
        )
        OrganizationService(session).update_company_profile(
            CompanyProfileUpdate(
                company_id=seed["company"].id,
                code="tsukiden",
                name="Tsukiden Global Solution Inc.",
            )
        )

        current_user = AuthService(session).authenticate(
            company_code="tsukiden",
            login_identifier="defaultadmin",
            password="Temporary123!",
        )
        assert current_user.company_code == "TSUKIDEN"

        try:
            AuthService(session).authenticate(
                company_code="DEFAULT",
                login_identifier="defaultadmin",
                password="Temporary123!",
            )
        except AuthenticationError:
            pass
        else:
            raise AssertionError("Old company code still authenticated.")

def test_company_code_change_rejects_duplicate_case_insensitively() -> None:
    factory = _factory()

    with factory() as session:
        first = seed_initial_data(
            session,
            _settings("FIRST", "first.brand@example.com"),
        )
        second = seed_initial_data(
            session,
            _settings("SECOND", "second.brand@example.com"),
        )
        service = OrganizationService(session)

        try:
            service.update_company_profile(
                CompanyProfileUpdate(
                    company_id=second["company"].id,
                    code="first",
                    name="Second Company",
                )
            )
        except ValueError as error:
            assert "already in use" in str(error)
        else:
            raise AssertionError("Duplicate company code was accepted.")

        assert service.get_company(first["company"].id).code == "FIRST"
        assert service.get_company(second["company"].id).code == "SECOND"


def test_logo_brand_colors_can_be_suggested() -> None:
    colors = extract_logo_theme_colors(_brand_logo_bytes(), max_colors=4)

    assert colors
    assert all(color.startswith("#") and len(color) == 7 for color in colors)
    assert any(
        int(color[3:5], 16) > int(color[1:3], 16)
        and int(color[3:5], 16) > int(color[5:7], 16)
        for color in colors
    )


def test_company_profile_ui_uses_two_tabs_and_branding_controls() -> None:
    source = (
        PROJECT_ROOT / "ui/pages/admin/company_page.py"
    ).read_text(encoding="utf-8")

    assert '["Company Information", "Branding"]' in source
    assert "CompanyProfileUpdate(" in source
    assert "Changing the Company Code will change the code employees use" in source
    assert "upload_column, preview_column = st.columns(" in source
    assert "Suggested From Company Logo" in source
    assert "extract_logo_theme_colors" in source
    assert '"HEX Color"' not in source
    assert "Theme Colors" not in source
    assert "Standard Colors" not in source
    assert "st.color_picker(" in source
    assert "_render_theme_preview(selected_color)" in source

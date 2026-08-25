"""Validated, atomic Excel import for company benefits."""

from __future__ import annotations

from datetime import date, datetime
from io import BytesIO
from zipfile import BadZipFile

from openpyxl import Workbook, load_workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils.exceptions import InvalidFileException
from openpyxl.workbook.defined_name import DefinedName
from openpyxl.worksheet.datavalidation import DataValidation
from sqlalchemy.orm import Session

from services.excel_template_guidance import add_header_guidance
from services.onboarding_service import OnboardingService
from ui.onboarding_destinations import ONBOARDING_DESTINATIONS


BENEFIT_IMPORT_COLUMNS = (
    "Benefit Name",
    "Category",
    "Description",
    "Eligibility",
    "Effective Date",
    "Enrollment / Claim Instructions",
    "Contact Person / Team",
    "Display Order",
    "Related Workspace",
)
BENEFIT_PREVIEW_COLUMNS = ("Row", *BENEFIT_IMPORT_COLUMNS, "Validation")
SAMPLE_BENEFIT_ROW = (
    "SAMPLE ONLY - Health Coverage",
    "Health",
    "Sample benefit description.",
    "All employees",
    "2026-08-24",
    "Contact HR and submit the required enrollment form.",
    "HR Team",
    10,
    "Onboarding — Benefits",
)


def _text(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value).strip()


def _parse_date(value: object) -> date | None:
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(_text(value))
    except ValueError as exc:
        raise ValueError("Effective Date must use YYYY-MM-DD or an Excel date cell.") from exc


def _reference_validation(sheet, cell_range: str, formula: str) -> None:
    validation = DataValidation(type="list", formula1=formula, allow_blank=False)
    validation.errorTitle = "Invalid selection"
    validation.error = "Choose a Related Workspace from the template's Valid Selections worksheet."
    validation.promptTitle = "Valid Related Workspace"
    validation.prompt = "Choose one of the current project workspace destinations."
    validation.showErrorMessage = True
    validation.showInputMessage = True
    sheet.add_data_validation(validation)
    validation.add(cell_range)


class BenefitBulkImportService:
    """Prepare benefit previews and create a whole valid batch atomically."""

    def __init__(self, session: Session) -> None:
        self.session = session
        self.onboarding_service = OnboardingService(session)

    @staticmethod
    def build_template() -> bytes:
        workbook = Workbook()
        sheet = workbook.active
        sheet.title = "Benefit Import Template"
        sheet.append(list(BENEFIT_IMPORT_COLUMNS))
        sheet.append(list(SAMPLE_BENEFIT_ROW))

        header_fill = PatternFill("solid", fgColor="2F740B")
        header_font = Font(color="FFFFFF", bold=True)
        for cell in sheet[1]:
            cell.fill = header_fill
            cell.font = header_font
            cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        sample_fill = PatternFill("solid", fgColor="D9D9D9")
        sample_font = Font(color="666666", italic=True)
        for cell in sheet[2]:
            cell.fill = sample_fill
            cell.font = sample_font
            cell.alignment = Alignment(vertical="top", wrap_text=True)
        sheet.row_dimensions[2].height = 48
        widths = {"A": 32, "B": 20, "C": 48, "D": 32, "E": 18, "F": 48, "G": 28, "H": 16, "I": 34}
        for column, width in widths.items():
            sheet.column_dimensions[column].width = width
        sheet.freeze_panes = "A2"
        sheet.auto_filter.ref = "A1:I2000"

        add_header_guidance(sheet, "A1", requirement="Required benefit name; free text.")
        add_header_guidance(sheet, "B1", requirement="Optional category; free text. Blank defaults to General. There is no hidden fixed category list.")
        add_header_guidance(sheet, "C1", requirement="Optional benefit description; free text.")
        add_header_guidance(sheet, "D1", requirement="Optional eligibility description; free text. Blank defaults to All employees.")
        add_header_guidance(sheet, "E1", requirement="Optional effective date. Use YYYY-MM-DD or an Excel date cell.")
        add_header_guidance(sheet, "F1", requirement="Optional enrollment/claim instructions; free text.")
        add_header_guidance(sheet, "G1", requirement="Optional contact person/team; free text.")
        add_header_guidance(sheet, "H1", requirement="Optional non-negative whole-number display order. Blank defaults to 0.")
        add_header_guidance(
            sheet,
            "I1",
            requirement="Required. Use one of the current Related Workspace selections.",
            choices=tuple(ONBOARDING_DESTINATIONS),
            extra="The same complete selections are also listed in the 'Valid Selections' worksheet.",
        )

        ref = workbook.create_sheet("Valid Selections")
        ref.append(["Related Workspace"])
        for value in ONBOARDING_DESTINATIONS:
            ref.append([value])
        ref["A1"].fill = header_fill
        ref["A1"].font = header_font
        ref.column_dimensions["A"].width = 42
        workbook.defined_names.add(
            DefinedName(
                "BenefitRelatedWorkspaces",
                attr_text=f"'Valid Selections'!$A$2:$A${len(ONBOARDING_DESTINATIONS)+1}",
            )
        )
        _reference_validation(sheet, "I2:I2000", "=BenefitRelatedWorkspaces")

        stream = BytesIO()
        workbook.save(stream)
        return stream.getvalue()

    def prepare_preview(self, file_bytes: bytes, *, filename: str, company_id: int) -> list[dict[str, object]]:
        if not filename.lower().endswith(".xlsx"):
            raise ValueError("Upload the downloadable .xlsx Benefit template.")
        if not file_bytes:
            raise ValueError("The uploaded Benefit Excel file is empty.")
        if len(file_bytes) > 10 * 1024 * 1024:
            raise ValueError("The Benefit Excel file must not exceed 10 MB.")
        try:
            workbook = load_workbook(BytesIO(file_bytes), data_only=True)
        except (BadZipFile, InvalidFileException, OSError, ValueError) as exc:
            raise ValueError(
                "The uploaded Benefit file is not a readable .xlsx workbook."
            ) from exc
        if "Benefit Import Template" not in workbook.sheetnames:
            raise ValueError("The workbook does not contain the required 'Benefit Import Template' worksheet.")
        sheet = workbook["Benefit Import Template"]
        headers = tuple(_text(cell.value) for cell in sheet[1])
        if headers[: len(BENEFIT_IMPORT_COLUMNS)] != BENEFIT_IMPORT_COLUMNS:
            raise ValueError("The Benefit template columns were changed. Download a fresh template and try again.")

        existing_names = {
            item.name.strip().casefold()
            for item in self.onboarding_service.list_benefits(company_id, active_only=False)
        }
        seen_names: set[str] = set()
        rows: list[dict[str, object]] = []
        count = 0
        for row_number, values in enumerate(sheet.iter_rows(min_row=2, max_col=len(BENEFIT_IMPORT_COLUMNS), values_only=True), start=2):
            if not any(value not in (None, "") for value in values):
                continue
            count += 1
            if count > 1000:
                raise ValueError("A maximum of 1,000 benefits can be imported at once.")
            raw = {column: values[index] for index, column in enumerate(BENEFIT_IMPORT_COLUMNS)}
            display = {"Row": row_number, **{column: _text(raw[column]) for column in BENEFIT_IMPORT_COLUMNS}}
            errors: list[str] = []
            normalized: dict[str, object] | None = None
            try:
                name = _text(raw["Benefit Name"])
                if not name:
                    raise ValueError("Benefit Name is required.")
                name_key = name.casefold()
                if name_key in existing_names:
                    errors.append("A benefit with this name already exists in Active or Archive.")
                if name_key in seen_names:
                    errors.append("Duplicate Benefit Name inside this uploaded workbook.")
                seen_names.add(name_key)
                effective_date = _parse_date(raw["Effective Date"])
                order_text = _text(raw["Display Order"])
                try:
                    sort_order = int(order_text) if order_text else 0
                except ValueError as exc:
                    raise ValueError("Display Order must be a whole number.") from exc
                if sort_order < 0:
                    raise ValueError("Display Order must be zero or greater.")
                destination = _text(raw["Related Workspace"]) or "No related workspace"
                if destination not in ONBOARDING_DESTINATIONS:
                    raise ValueError("Related Workspace is not one of the current project selections.")
                page, query_key, query_value = ONBOARDING_DESTINATIONS[destination]
                normalized = OnboardingService._validated_benefit_values(
                    {
                        "name": name,
                        "category": _text(raw["Category"]) or "General",
                        "description": _text(raw["Description"]),
                        "eligibility": _text(raw["Eligibility"]) or "All employees",
                        "effective_date": effective_date,
                        "enrollment_instructions": _text(raw["Enrollment / Claim Instructions"]),
                        "contact_person": _text(raw["Contact Person / Team"]) or None,
                        "sort_order": sort_order,
                        "is_active": True,
                        "target_page": page,
                        "target_query_key": query_key,
                        "target_query_value": query_value,
                    }
                )
            except ValueError as error:
                errors.append(str(error))
            display["Validation"] = " | ".join(errors) if errors else "Ready"
            display["_values"] = normalized if normalized is not None and not errors else None
            rows.append(display)
        if not rows:
            raise ValueError("The Benefit workbook does not contain any data rows.")
        return rows

    def import_preview_rows(self, rows: list[dict[str, object]], *, company_id: int):
        values: list[dict[str, object]] = []
        for row in rows:
            if row.get("Validation") != "Ready":
                raise ValueError("Every Benefit row must be valid before import.")
            item = row.get("_values")
            if not isinstance(item, dict):
                raise ValueError(f"Row {row.get('Row')} must be validated again before import.")
            values.append(dict(item))
        return self.onboarding_service.create_benefits_many(company_id=company_id, values_list=values)

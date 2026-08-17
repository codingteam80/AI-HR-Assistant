"""Convert authorized PDF company forms to editable Word downloads."""

from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory

from docx import Document


DOCX_MIME_TYPE = (
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
)


def convert_pdf_bytes_to_docx(
    *,
    pdf_bytes: bytes,
    source_filename: str,
) -> tuple[str, str, bytes]:
    """Return a validated DOCX version without changing the source PDF.

    ``pdf2docx`` uses temporary files for its conversion engine. The files are
    removed as soon as the in-memory DOCX has been validated.
    """

    if not pdf_bytes:
        raise ValueError("The selected PDF form is empty and cannot be converted.")

    try:
        from pdf2docx import Converter
    except ImportError as error:  # pragma: no cover - installation safeguard
        raise ValueError(
            "PDF-to-Word conversion is unavailable. Install the project "
            "requirements and restart the application."
        ) from error

    safe_stem = Path(source_filename or "company_form.pdf").stem.strip()
    output_filename = f"{safe_stem or 'company_form'}.docx"

    try:
        with TemporaryDirectory(prefix="hr_form_conversion_") as temporary_dir:
            input_path = Path(temporary_dir) / "source.pdf"
            output_path = Path(temporary_dir) / "editable.docx"
            input_path.write_bytes(pdf_bytes)

            converter = Converter(str(input_path))
            try:
                converter.convert(str(output_path), start=0, end=None)
            finally:
                converter.close()

            converted_bytes = output_path.read_bytes()

        # Validate the generated OOXML package before exposing it for download.
        Document(BytesIO(converted_bytes))
    except Exception as error:
        raise ValueError(
            "This PDF could not be converted to an editable Word document. "
            "Verify that the original PDF is complete and not password-protected."
        ) from error

    return output_filename, DOCX_MIME_TYPE, converted_bytes

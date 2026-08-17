"""Cached preparation of editable company-form downloads."""

import streamlit as st

from modules.documents.pdf_to_docx_converter import convert_pdf_bytes_to_docx
from services.company_form_service import CompanyFormDownload


@st.cache_data(show_spinner=False, max_entries=24, ttl=3600)
def prepare_editable_company_form_download(
    *,
    filename: str,
    mime_type: str,
    data: bytes,
) -> CompanyFormDownload:
    """Convert PDF templates to DOCX and pass all other formats through."""

    is_pdf = (
        mime_type.lower() == "application/pdf"
        or filename.lower().endswith(".pdf")
    )
    if not is_pdf:
        return CompanyFormDownload(
            filename=filename,
            mime_type=mime_type,
            data=data,
        )

    converted_filename, converted_mime_type, converted_data = (
        convert_pdf_bytes_to_docx(
            pdf_bytes=data,
            source_filename=filename,
        )
    )
    return CompanyFormDownload(
        filename=converted_filename,
        mime_type=converted_mime_type,
        data=converted_data,
    )

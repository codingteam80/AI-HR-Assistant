"""Shared payroll codes for leave duration and standard reasons."""

from __future__ import annotations


LEAVE_DURATION_OPTIONS = {
    "90501": "AM Only",
    "90502": "PM Only",
    "90503": "Whole Day",
}

LEAVE_REASON_OPTIONS = {
    "0": "OTHERS",
    "1": "FAMILY MATTERS",
    "2": "BANK PAYMENTS",
    "3": "COUGH AND COLDS",
    "4": "URTI",
    "5": "FEVER",
    "8": "FAMILY MEMBER",
    "9": "FRIEND",
    "10": "WEDDING",
    "11": "WIFE GAVE BIRTH",
    "12": "REST",
    "13": "COMPANY TOUR",
    "14": "CLIENT TOUR",
    "15": "EMERGENCY",
    "16": "Rest Day Credit",
    "17": "JAPAN TRAINING",
    "18": "CHECK-UP",
    "19": "THREATENED ABORTION",
    "20": "BODY PAIN",
    "21": "HEADACHE",
    "22": "ACCIDENT",
    "23": "ANIMAL BITE",
    "24": "TOOTHACHE",
    "25": "BIRTHDAY",
    "26": "LBM",
    "27": "IMPORTANT MATTER",
    "28": "UTI",
    "29": "WEDDING PREPARATION",
    "30": "WEDDING SPONSOR",
    "31": "BAPTISMAL SPONSOR",
    "32": "BED REST",
    "33": "DIZZINESS",
    "34": "VOMITING",
    "36": "ATTEND OATH TAKING CEREMONY",
    "38": "Asthma Attack",
    "39": "Thesis Presentation",
    "40": "Dysmenorrhea",
    "41": "SWOLLEN LEG",
    "42": "SORE EYES",
    "43": "RHINITIS",
    "44": "ACID PEPTIC DISEASE",
    "45": "HOUSE RELOCATION",
    "46": "BURIAL OF MY NEPHEW",
    "47": "ARM SPRAIN",
    "48": "ACUTE TONSILLITIS",
    "49": "DENGUE FEVER",
    "50": "PROCESS OF LICENSE – PRC",
    "51": "DYSPEPSIA",
    "52": "ATTEND CHRISTENING",
    "53": "ALLERGY",
}


def code_description(code: str, options: dict[str, str]) -> str:
    """Return one standardized ``[Code] - [Description]`` value."""

    normalized = str(code or "").strip()
    description = options.get(normalized, "")
    return f"{normalized} - {description}" if normalized and description else ""


def duration_label(code: str) -> str:
    return code_description(code, LEAVE_DURATION_OPTIONS)


def reason_label(code: str) -> str:
    return code_description(code, LEAVE_REASON_OPTIONS)

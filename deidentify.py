"""
De-identification for MedFind retrieval responses (PRD section 7 / section 9).

Applied to every study before it leaves the node on a /api/retrieve call:
- PatientName, PatientID, PatientBirthDate are removed outright.
- PatientAge is coarsened into a band (e.g. "0-2y") instead of an exact value.
- All clinical/technical fields (Diagnosis, Modality, StudyDate, etc.) are kept intact.

Raw PII never crosses the node boundary, even for authorized requests.
"""

from models import StudyRecord

# (low_years_inclusive, high_years_inclusive, label)
_AGE_BANDS: list[tuple[float, float, str]] = [
    (0, 2, "0-2y"),
    (3, 5, "3-5y"),
    (6, 12, "6-12y"),
    (13, 17, "13-17y"),
    (18, 21, "18-21y"),
    (22, 30, "22-30y"),
    (31, 40, "31-40y"),
    (41, 50, "41-50y"),
    (51, 64, "51-64y"),
    (65, float("inf"), "65y+"),
]

DIRECT_IDENTIFIERS = ("PatientName", "PatientID", "PatientBirthDate")


def parse_age_years(patient_age: str) -> float:
    """Parse DICOM-style age strings ('NNNY' / 'NNNM' / 'NNND') into years."""
    if not patient_age or len(patient_age) < 4:
        return 0.0
    value_str, unit = patient_age[:-1], patient_age[-1].upper()
    try:
        value = int(value_str)
    except ValueError:
        return 0.0
    if unit == "Y":
        return float(value)
    if unit == "M":
        return value / 12.0
    if unit == "D":
        return value / 365.0
    return float(value)


def band_age(patient_age: str) -> str:
    """Coarsen an exact DICOM age string into a safe band, e.g. '005D' -> '0-2y'."""
    years = parse_age_years(patient_age)
    for low, high, label in _AGE_BANDS:
        if low <= years <= high:
            return label
    return "unknown"


def deidentify_study(study: StudyRecord) -> dict:
    """Return `study` as a plain dict with direct identifiers stripped/banded."""
    data = study.model_dump()
    for field in DIRECT_IDENTIFIERS:
        data.pop(field, None)
    data["PatientAge"] = band_age(study.PatientAge)
    return data

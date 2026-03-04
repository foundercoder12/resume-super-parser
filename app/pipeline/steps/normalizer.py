"""
Post-extraction normalization.

  1. Date normalization: various human formats → YYYY-MM or YYYY
  2. Employment type classification (full_time / intern / freelance / part_time)
  3. Total YoE calculation (FTE + freelance, overlapping intervals merged)
  4. Dedup repeated page headers/footers
  5. Merge hyphenated line-wrapped bullets
  6. Trim whitespace from all string fields
"""
from __future__ import annotations
import re
from datetime import date
from dateutil import parser as dateutil_parser
from dateutil.parser import ParserError

from app.schemas.canonical import CanonicalResume, ExperienceEntry

# ── Employment-type classifiers ───────────────────────────────────────────────
_INTERN_RE    = re.compile(r"\b(intern(ship)?|trainee|apprentice)\b", re.IGNORECASE)
_PART_TIME_RE = re.compile(r"\bpart[\s-]time\b", re.IGNORECASE)
_FREELANCE_RE = re.compile(r"\b(freelance[r]?|independent|self[\s-]employed)\b", re.IGNORECASE)
_CONTRACT_RE  = re.compile(r"\b(contract(or)?|temp(orary)?)\b", re.IGNORECASE)


def _classify_employment_type(title: str | None) -> str:
    """
    Classify a job title into an employment type.
    Returns: 'intern' | 'part_time' | 'freelance' | 'contract' | 'full_time'
    """
    if not title:
        return "full_time"
    if _INTERN_RE.search(title):
        return "intern"
    if _PART_TIME_RE.search(title):
        return "part_time"
    if _FREELANCE_RE.search(title):
        return "freelance"
    if _CONTRACT_RE.search(title):
        return "contract"   # treated as FTE in YoE
    return "full_time"


def _parse_to_date(date_str: str | None) -> date | None:
    """Convert a YYYY-MM or YYYY string to a date object (1st of month)."""
    if not date_str:
        return None
    try:
        if re.fullmatch(r"\d{4}-\d{2}", date_str):
            y, m = map(int, date_str.split("-"))
            return date(y, m, 1)
        if re.fullmatch(r"\d{4}", date_str):
            return date(int(date_str), 1, 1)
    except (ValueError, OverflowError):
        pass
    return None


def compute_total_yoe(entries: list[ExperienceEntry]) -> float:
    """
    Compute total FTE years of experience.

    Rules:
    - Internships (employment_type == 'intern') are excluded.
    - Part-time roles are excluded.
    - Freelance and contract roles are included.
    - Overlapping date ranges are merged to avoid double-counting concurrent jobs.
    - Returns years rounded to 1 decimal place.
    """
    today = date.today()
    intervals: list[tuple[date, date]] = []

    for entry in entries:
        etype = entry.employment_type or "full_time"
        if etype in ("intern", "part_time"):
            continue

        start = _parse_to_date(entry.start_date)
        if not start:
            continue

        if entry.is_current:
            end = today
        else:
            end = _parse_to_date(entry.end_date)
            if not end:
                continue

        if end < start:
            continue
        intervals.append((start, end))

    if not intervals:
        return 0.0

    # Merge overlapping intervals
    intervals.sort(key=lambda x: x[0])
    merged: list[tuple[date, date]] = [intervals[0]]
    for start, end in intervals[1:]:
        prev_start, prev_end = merged[-1]
        if start <= prev_end:
            merged[-1] = (prev_start, max(prev_end, end))
        else:
            merged.append((start, end))

    total_days = sum((end - start).days for start, end in merged)
    return round(total_days / 365.25, 1)

# Patterns for "current" end dates
_CURRENT_RE = re.compile(r"\b(present|current|now|ongoing|till date|to date)\b", re.IGNORECASE)

# Month abbreviation → number
_MONTH_ABBR = {
    "jan": "01", "feb": "02", "mar": "03", "apr": "04",
    "may": "05", "jun": "06", "jul": "07", "aug": "08",
    "sep": "09", "oct": "10", "nov": "11", "dec": "12",
}


def normalize_date(raw: str | None) -> str | None:
    """Normalise a human date string to YYYY-MM or YYYY. Returns None if unparseable."""
    if not raw:
        return None
    if _CURRENT_RE.search(raw):
        return None   # caller should set is_current=True

    raw_stripped = raw.strip()

    # Fast path: already YYYY-MM
    if re.fullmatch(r"\d{4}-\d{2}", raw_stripped):
        return raw_stripped
    # Fast path: already YYYY
    if re.fullmatch(r"\d{4}", raw_stripped):
        return raw_stripped

    # Try dateutil
    try:
        dt = dateutil_parser.parse(raw_stripped, default=dateutil_parser.parse("2000-01-01"))
        # If original has a month name or number, include it
        month_present = bool(re.search(r"[a-zA-Z]{3,}|\d{1,2}[/-]", raw_stripped))
        if month_present:
            return f"{dt.year:04d}-{dt.month:02d}"
        return f"{dt.year:04d}"
    except (ParserError, ValueError, OverflowError):
        return None


def _normalize_entry(entry: ExperienceEntry) -> ExperienceEntry:
    is_current = entry.is_current

    # Check end_date for "present" markers
    if entry.end_date and _CURRENT_RE.search(entry.end_date):
        is_current = True
        entry = entry.model_copy(update={"end_date": None, "is_current": True})

    normalized_start = normalize_date(entry.start_date)
    normalized_end = normalize_date(entry.end_date) if not is_current else None

    # Merge bullets that look like line-wrapped continuations (start with lowercase)
    merged_bullets: list[str] = []
    for bullet in entry.bullets:
        stripped = bullet.strip()
        if not stripped:
            continue
        # If bullet starts with lowercase and there's a previous bullet, merge
        if merged_bullets and stripped and stripped[0].islower() and not stripped.startswith("-"):
            merged_bullets[-1] = merged_bullets[-1].rstrip() + " " + stripped
        else:
            merged_bullets.append(stripped)

    title_clean = (entry.title or "").strip() or None
    emp_type = entry.employment_type or _classify_employment_type(title_clean)

    return entry.model_copy(update={
        "start_date": normalized_start,
        "end_date": normalized_end,
        "is_current": is_current,
        "bullets": merged_bullets,
        "company": (entry.company or "").strip() or None,
        "title": title_clean,
        "location": (entry.location or "").strip() or None,
        "employment_type": emp_type,
    })


def normalize(resume: CanonicalResume) -> CanonicalResume:
    """Apply all normalization passes to a CanonicalResume."""
    normalized_experience = [_normalize_entry(e) for e in resume.experience]

    # Normalize education dates
    normalized_edu = []
    for edu in resume.sections.education:
        normalized_edu.append(edu.model_copy(update={
            "start_date": normalize_date(edu.start_date),
            "end_date": normalize_date(edu.end_date),
        }))

    # Normalize certifications
    normalized_certs = []
    for cert in resume.sections.certifications:
        normalized_certs.append(cert.model_copy(update={
            "date": normalize_date(cert.date),
        }))

    # Deduplicate skills (case-insensitive)
    seen: set[str] = set()
    deduped_skills: list[str] = []
    for skill in resume.sections.skills:
        key = skill.strip().lower()
        if key and key not in seen:
            seen.add(key)
            deduped_skills.append(skill.strip())

    updated_sections = resume.sections.model_copy(update={
        "education": normalized_edu,
        "certifications": normalized_certs,
        "skills": deduped_skills,
    })

    yoe = compute_total_yoe(normalized_experience)

    return resume.model_copy(update={
        "experience": normalized_experience,
        "sections": updated_sections,
        "total_experience_years": yoe,
    })

"""
Per-field confidence scoring.

Computes confidence for each ExperienceEntry based on:
  - Field presence (non-null values)
  - Field plausibility (date format, length sanity)
  - Bullet quality (not just single words, not heading-like)
  - Overall based on weighted average of field scores
"""
from __future__ import annotations
import re

from app.schemas.canonical import CanonicalResume, ExperienceEntry, ExperienceConfidence, ConfidenceSet

_DATE_RE = re.compile(r"^\d{4}(-\d{2})?$")
_HEADING_LIKE = re.compile(r"^[A-Z][A-Z\s]+$")  # ALL CAPS lines are probably headings not bullets


def _score_company(company: str | None) -> float:
    if not company:
        return 0.0
    if len(company) > 200:
        return 0.3  # suspiciously long
    return 1.0


def _score_title(title: str | None) -> float:
    if not title:
        return 0.0
    if len(title) > 150:
        return 0.3
    return 1.0


def _score_dates(start_date: str | None, end_date: str | None, is_current: bool) -> float:
    if not start_date:
        return 0.2
    score = 0.5
    if _DATE_RE.match(start_date):
        score += 0.3
    if is_current or (end_date and _DATE_RE.match(end_date)):
        score += 0.2
    # Plausibility: start year should be between 1950 and 2030
    try:
        year = int(start_date[:4])
        if 1950 <= year <= 2030:
            score = min(score, 1.0)
        else:
            score *= 0.5
    except (ValueError, IndexError):
        score *= 0.5
    return round(min(score, 1.0), 3)


def _score_bullets(bullets: list[str]) -> float:
    if not bullets:
        return 0.3  # no bullets is weak but not impossible
    good = 0
    for b in bullets:
        if len(b) < 5:
            continue  # too short
        if _HEADING_LIKE.match(b):
            continue  # probably a mis-classified heading
        if len(b) > 500:
            continue  # probably merged incorrectly
        good += 1
    ratio = good / len(bullets)
    return round(0.3 + 0.7 * ratio, 3)


def _score_entry(entry: ExperienceEntry) -> ExperienceConfidence:
    c = _score_company(entry.company)
    t = _score_title(entry.title)
    d = _score_dates(entry.start_date, entry.end_date, entry.is_current)
    b = _score_bullets(entry.bullets)
    overall = round(0.30 * c + 0.25 * t + 0.25 * d + 0.20 * b, 3)
    return ExperienceConfidence(company=c, title=t, dates=d, bullets=b, overall=overall)


def score(resume: CanonicalResume) -> CanonicalResume:
    """Compute and attach confidence scores to all experience entries."""
    scored_entries = []
    exp_overalls: list[float] = []

    for entry in resume.experience:
        conf = _score_entry(entry)
        scored_entries.append(entry.model_copy(update={"confidence": conf}))
        exp_overalls.append(conf.overall)

    exp_avg = round(sum(exp_overalls) / len(exp_overalls), 3) if exp_overalls else 0.0

    # Overall: weighted by section presence
    has_edu = bool(resume.sections.education)
    has_skills = bool(resume.sections.skills)
    overall = round(
        0.60 * exp_avg
        + 0.20 * (0.8 if has_edu else 0.2)
        + 0.20 * (0.8 if has_skills else 0.2),
        3,
    )

    updated_confidence = ConfidenceSet(
        overall=overall,
        experience=exp_avg if exp_overalls else None,
        education=0.8 if has_edu else 0.2,
        skills=0.8 if has_skills else 0.2,
    )

    return resume.model_copy(update={
        "experience": scored_entries,
        "confidence": updated_confidence,
    })

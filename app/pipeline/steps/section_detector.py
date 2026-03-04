"""
Section boundary detection for resume text.

Strategy:
  1. Regex fast-path for well-known headings.
  2. LLM semantic classification for any heading that didn't match regex.
     One batched Gemini call per resume — all unrecognised headings at once.
  3. Fallback: date-pattern density clustering for headingless resumes.

The LLM returns a canonical category name (or "unknown").  Each detected
heading gets a unique key in the result dict so multiple sections of the
same category (e.g. two experience-type sections) are both preserved.
"""
from __future__ import annotations
import json
import re
import structlog

from app.schemas.internal import SectionBoundary

log = structlog.get_logger(__name__)

# ── Regex fast-path ────────────────────────────────────────────────────────────
SECTION_PATTERNS: list[tuple[str, list[str]]] = [
    ("contact",      [r"^(contact|contact information|personal (details?|info(rmation)?))$"]),
    ("summary",      [r"^(summary|professional summary|profile|objective|career objective|about me|overview)$"]),
    ("experience",   [r"^(experience|work experience|employment( history)?|work history|professional experience|career history|employment record)$"]),
    ("internship",   [r"^(internship[s]?|intern(ship)? experience|industrial training)$"]),
    ("positions",    [r"^(positions?\s+of\s+responsibility|leadership(\s+roles?)?|positions?)$"]),
    ("education",    [r"^(education|academic (background|qualifications?)|qualifications?|degrees?|academic history)$"]),
    ("skills",       [r"^(skills?|technical skills?|core competenc(y|ies)|competencies|technologies|tech stack)$"]),
    ("projects",     [r"^(projects?|personal projects?|side projects?|open.?source|notable projects?)$"]),
    ("certifications", [r"^(certifications?|certificates?|licen[sc]es?|credentials?|accreditations?)$"]),
    ("awards",       [r"^(awards?|honors?|achievements?|recognition|prizes?)$"]),
    ("activities",   [r"^(extra[\s\-–—]*curricular(\s+activities)?(\s+and\s+achievements?)?|activities(\s+and\s+achievements?)?)$"]),
    ("publications", [r"^(publications?|research|papers?)$"]),
    ("languages",    [r"^(languages?|language proficiency)$"]),
    ("volunteer",    [r"^(volunteer(ing)?|community service|civic( engagement)?)$"]),
    ("other",        [r"^(other\s+information|additional\s+information|miscellaneous)$"]),
]

COMPILED: list[tuple[str, list[re.Pattern]]] = [
    (name, [re.compile(p, re.IGNORECASE | re.MULTILINE) for p in pats])
    for name, pats in SECTION_PATTERNS
]

# ── Heading-candidate heuristics ───────────────────────────────────────────────
_BULLET_CHARS = set("•·-*–—►▶▸◦◗>")
_NUMBERED_ITEM = re.compile(r"^\d+[.)]\s")


def _looks_like_heading(text: str) -> bool:
    """Return True if the line is plausibly a section heading."""
    if not text or len(text) > 75 or len(text) < 2:
        return False
    if text[0] in _BULLET_CHARS:
        return False
    if _NUMBERED_ITEM.match(text):
        return False
    alpha = [c for c in text if c.isalpha()]
    if len(alpha) < 2:
        return False
    upper = sum(1 for c in alpha if c.isupper())
    lower = sum(1 for c in alpha if c.islower())
    total = upper + lower
    if total == 0:
        return False
    # Heading if ≥ 60 % uppercase OR every word starts uppercase (Title Case)
    mostly_upper = upper / total >= 0.60
    title_case = all(w[0].isupper() for w in text.split() if w and w[0].isalpha())
    return mostly_upper or title_case


# ── LLM semantic classification ────────────────────────────────────────────────
# Module-level cache so repeated headings across resumes don't cost extra calls
_llm_cache: dict[str, str] = {}

_LLM_CATEGORIES = [
    "experience",     # any work / internship / job / role
    "education",      # degrees, schools, academic background
    "skills",         # technical skills, tools, technologies
    "projects",       # personal / academic / open-source projects
    "certifications", # certificates, licenses, credentials
    "awards",         # honors, prizes, recognition, achievements
    "activities",     # extracurricular, clubs, hobbies, sports
    "volunteer",      # community service, NGO, civic work
    "summary",        # professional summary, about me, objective
    "contact",        # contact info, personal details
    "publications",   # papers, research, patents
    "languages",      # spoken / written language proficiency
    "other",          # anything that doesn't fit above
    "unknown",        # cannot determine — will be excluded
]


def _classify_headings_with_llm(headings: list[str]) -> dict[str, str]:
    """
    Batch-classify unrecognised section headings using Gemini.
    Returns {heading_text: canonical_category}.
    """
    # Serve from cache where possible
    uncached = [h for h in headings if h not in _llm_cache]
    if not uncached:
        return {h: _llm_cache[h] for h in headings}

    try:
        from app.config import settings
        from google import genai
        from google.genai import types as genai_types

        if not settings.gemini_api_key:
            return {h: "other" for h in headings}

        cats = ", ".join(_LLM_CATEGORIES)
        prompt = (
            "You are classifying resume section headings into standard categories.\n\n"
            f"Available categories: {cats}\n\n"
            "Rules:\n"
            "- 'experience' covers internships, jobs, positions of responsibility, leadership roles, "
            "volunteer work that reads like a job, freelance work.\n"
            "- 'activities' covers extracurricular activities, clubs, hobbies.\n"
            "- 'awards' covers prizes, honours, achievements, competitions.\n"
            "- 'other' for sections that contain useful resume content but don't fit above.\n"
            "- 'unknown' ONLY if the text is clearly not a section heading (e.g. a sentence or data value).\n\n"
            f"Headings to classify: {json.dumps(uncached)}\n\n"
            "Return a JSON object: {\"heading\": \"category\", ...}"
        )

        client = genai.Client(api_key=settings.gemini_api_key)
        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=prompt,
            config=genai_types.GenerateContentConfig(
                response_mime_type="application/json",
                temperature=0.0,
            ),
        )
        result: dict[str, str] = json.loads(response.text)
        for h in uncached:
            _llm_cache[h] = result.get(h, "other")

        # Capture exact token counts from Gemini response metadata
        usage = getattr(response, "usage_metadata", None)
        if usage:
            from app.core.cost import gemini_cost
            in_tok  = getattr(usage, "prompt_token_count", 0) or 0
            out_tok = getattr(usage, "candidates_token_count", 0) or 0
            _llm_cache["__last_usage__"] = {
                "input_tokens": in_tok,
                "output_tokens": out_tok,
                "cost_usd": gemini_cost(in_tok, out_tok),
            }

        log.info("llm_section_classification", headings=uncached,
                 results={h: _llm_cache[h] for h in uncached})

    except Exception as e:
        log.warning("llm_section_classification_failed", error=str(e))
        for h in uncached:
            _llm_cache[h] = "other"

    return {h: _llm_cache[h] for h in headings}


def pop_last_llm_usage() -> dict | None:
    """Return and clear the token-usage dict from the last LLM heading call."""
    return _llm_cache.pop("__last_usage__", None)


# ── Heuristic date-cluster fallback ───────────────────────────────────────────
DATE_PATTERN = re.compile(
    r"\b(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?\s+\d{4}"
    r"|\b\d{4}\s*[-–]\s*(present|current|\d{4})"
    r"|\b(present|current)\b",
    re.IGNORECASE,
)
TITLE_KEYWORDS = re.compile(
    r"\b(engineer|developer|analyst|manager|director|lead|architect|designer|"
    r"consultant|intern|associate|officer|specialist|coordinator|scientist|"
    r"researcher|principal|senior|junior|staff|vp|cto|ceo|coo)\b",
    re.IGNORECASE,
)
ORG_SUFFIXES = re.compile(
    r"\b(inc\.?|llc\.?|ltd\.?|pvt\.?|corp\.?|technologies|solutions|systems|"
    r"group|company|co\.|associates?|partners?|labs?|studio)\b",
    re.IGNORECASE,
)


# ── Public API ─────────────────────────────────────────────────────────────────

def detect(full_text: str) -> dict[str, SectionBoundary]:
    """
    Detect section boundaries in resume text.

    Returns a dict keyed by a unique section slug (category name, with _2/_3
    suffixes when the same category appears more than once).
    """
    lines = full_text.splitlines(keepends=True)
    # (char_offset, matched_category_or_None, stripped_line)
    candidates: list[tuple[int, str | None, str]] = []

    char_offset = 0
    for line in lines:
        stripped = line.strip()
        if stripped:
            # Try regex fast-path
            matched_category: str | None = None
            for section_name, patterns in COMPILED:
                for pat in patterns:
                    if pat.fullmatch(stripped):
                        matched_category = section_name
                        break
                if matched_category:
                    break

            if matched_category:
                candidates.append((char_offset, matched_category, stripped))
            elif _looks_like_heading(stripped):
                candidates.append((char_offset, None, stripped))  # LLM needed

        char_offset += len(line)

    # Batch-classify all headings that need LLM
    unclassified = [text for _, cat, text in candidates if cat is None]
    if unclassified:
        classifications = _classify_headings_with_llm(unclassified)
        candidates = [
            (offset, cat if cat is not None else classifications.get(text, "other"), text)
            for offset, cat, text in candidates
        ]

    # Drop "unknown" headings
    boundaries: list[tuple[int, str, str]] = [
        (offset, cat, text)
        for offset, cat, text in candidates
        if cat and cat != "unknown"
    ]

    # Build result — preserve all sections with unique keys
    result: dict[str, SectionBoundary] = {}
    category_counts: dict[str, int] = {}

    for i, (start, category, heading) in enumerate(boundaries):
        end = boundaries[i + 1][0] if i + 1 < len(boundaries) else len(full_text)
        section_text = full_text[start:end]

        # Generate a unique key
        count = category_counts.get(category, 0) + 1
        category_counts[category] = count
        key = category if count == 1 else f"{category}_{count}"

        result[key] = SectionBoundary(
            name=key,
            heading_text=heading,
            start_char=start,
            end_char=end,
            text=section_text,
        )

    # If no experience-type section was detected at all, try heuristic
    has_exp = any(
        k == "experience" or k.startswith("experience_")
        or k in ("internship", "positions") or k.startswith("internship_") or k.startswith("positions_")
        for k in result
    )
    if not has_exp:
        fallback = _detect_experience_by_heuristic(full_text)
        if fallback:
            result["experience"] = fallback
            log.info("section_detector_fallback_used", strategy="date_cluster")

    log.info("sections_detected", sections=list(result.keys()))
    return result


def _detect_experience_by_heuristic(full_text: str) -> SectionBoundary | None:
    """
    When no experience-type heading is found, identify experience-like blocks
    by clustering lines that have date patterns + title keywords near them.
    """
    lines = full_text.splitlines(keepends=True)
    scored_lines: list[tuple[int, int, float]] = []

    char_offset = 0
    for line in lines:
        stripped = line.strip()
        score = 0.0
        if DATE_PATTERN.search(stripped):
            score += 2.0
        if TITLE_KEYWORDS.search(stripped):
            score += 1.0
        if ORG_SUFFIXES.search(stripped):
            score += 0.5
        if score > 0:
            scored_lines.append((char_offset, char_offset + len(line), score))
        char_offset += len(line)

    if not scored_lines:
        return None

    start = scored_lines[0][0]
    end = scored_lines[-1][1]
    return SectionBoundary(
        name="experience",
        heading_text="[heuristic]",
        start_char=start,
        end_char=end,
        text=full_text[start:end],
    )

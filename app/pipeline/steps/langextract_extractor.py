"""
Structured extraction using LangExtract (Google) with Gemini backend.

LangExtract extracts verbatim spans from the source text — solving the
company name accuracy issue by never paraphrasing, only quoting exact text.
Each extraction carries char_interval (start_pos, end_pos) for grounding.

Extraction classes:
  company_name      → experience company
  job_title         → experience title
  employment_dates  → date range for a role
  job_location      → location of a role
  bullet_point      → responsibility/achievement bullet
  skill             → individual skill/technology
  education_degree  → degree name
  education_inst    → institution name
  education_dates   → education date range
  gpa               → GPA value
  summary_text      → professional summary paragraph

After extraction we group entities into ExperienceEntry objects by
proximity: company + title + dates that appear close together form one entry,
and bullets that follow them (before the next company) belong to that entry.
"""
from __future__ import annotations

import os
import structlog
import langextract as lx

from app.config import settings
from app.core.exceptions import LlmExtractionError
from app.schemas.internal import ExtractedDocument, SectionBoundary
from app.schemas.canonical import (
    CanonicalResume, ExperienceEntry, ExperienceConfidence,
    Sections, EducationEntry, CertificationEntry, ProjectEntry,
    ConfidenceSet, PipelineTrace, DocumentMeta, Grounding,
    CharSpan, ApiCallCost,
)

log = structlog.get_logger(__name__)

PROMPT_DESCRIPTION = """Extract structured resume information. Use EXACT verbatim text from the resume for each extraction — never paraphrase or rewrite.

Extraction classes:
- company_name: The exact company or organization name for each work experience entry.
- job_title: The exact job title or position for each work experience entry.
- employment_dates: The exact date range text for a work experience entry (e.g. "January 2020 - Present", "Jun 2018 – Dec 2020").
- job_location: The exact location text for a work experience entry (e.g. "San Francisco, CA").
- bullet_point: An individual responsibility or achievement bullet point from a work experience entry.
- skill: An individual technical skill, tool, or technology.
- education_degree: The exact degree name (e.g. "Bachelor of Science in Computer Science").
- education_inst: The exact school or university name.
- education_dates: The date range for an education entry.
- gpa: The exact GPA value (e.g. "3.8/4.0").
- summary_text: The professional summary or objective paragraph.

Important:
- Extract each entity separately — one company_name per entry, one job_title per entry.
- For bullet_point, include the full bullet text without the leading bullet character.
- Do not skip any experience entries.
"""

# Few-shot example to guide the model
EXAMPLES = [
    lx.data.ExampleData(
        text="""PROFESSIONAL SUMMARY
Experienced software engineer with 5 years building distributed systems.

EXPERIENCE
Senior Software Engineer | Acme Technologies
New York, NY | March 2021 - Present
• Designed microservices architecture serving 2M users
• Reduced infrastructure costs by 35% via cloud optimization

Software Engineer | Beta Corp
Austin, TX | June 2018 - February 2021
• Built RESTful APIs using Django and PostgreSQL
• Led migration from monolith to microservices

EDUCATION
Bachelor of Science in Computer Science
MIT | 2014 - 2018 | GPA: 3.9/4.0

SKILLS
Python, Django, FastAPI, Docker, Kubernetes, PostgreSQL, AWS""",
        extractions=[
            lx.data.Extraction(extraction_class="summary_text",
                extraction_text="Experienced software engineer with 5 years building distributed systems."),
            lx.data.Extraction(extraction_class="job_title",
                extraction_text="Senior Software Engineer",
                attributes={"entry": "1"}),
            lx.data.Extraction(extraction_class="company_name",
                extraction_text="Acme Technologies",
                attributes={"entry": "1"}),
            lx.data.Extraction(extraction_class="job_location",
                extraction_text="New York, NY",
                attributes={"entry": "1"}),
            lx.data.Extraction(extraction_class="employment_dates",
                extraction_text="March 2021 - Present",
                attributes={"entry": "1"}),
            lx.data.Extraction(extraction_class="bullet_point",
                extraction_text="Designed microservices architecture serving 2M users",
                attributes={"entry": "1"}),
            lx.data.Extraction(extraction_class="bullet_point",
                extraction_text="Reduced infrastructure costs by 35% via cloud optimization",
                attributes={"entry": "1"}),
            lx.data.Extraction(extraction_class="job_title",
                extraction_text="Software Engineer",
                attributes={"entry": "2"}),
            lx.data.Extraction(extraction_class="company_name",
                extraction_text="Beta Corp",
                attributes={"entry": "2"}),
            lx.data.Extraction(extraction_class="job_location",
                extraction_text="Austin, TX",
                attributes={"entry": "2"}),
            lx.data.Extraction(extraction_class="employment_dates",
                extraction_text="June 2018 - February 2021",
                attributes={"entry": "2"}),
            lx.data.Extraction(extraction_class="bullet_point",
                extraction_text="Built RESTful APIs using Django and PostgreSQL",
                attributes={"entry": "2"}),
            lx.data.Extraction(extraction_class="bullet_point",
                extraction_text="Led migration from monolith to microservices",
                attributes={"entry": "2"}),
            lx.data.Extraction(extraction_class="education_degree",
                extraction_text="Bachelor of Science in Computer Science"),
            lx.data.Extraction(extraction_class="education_inst",
                extraction_text="MIT"),
            lx.data.Extraction(extraction_class="education_dates",
                extraction_text="2014 - 2018"),
            lx.data.Extraction(extraction_class="gpa",
                extraction_text="3.9/4.0"),
            lx.data.Extraction(extraction_class="skill", extraction_text="Python"),
            lx.data.Extraction(extraction_class="skill", extraction_text="Django"),
            lx.data.Extraction(extraction_class="skill", extraction_text="FastAPI"),
            lx.data.Extraction(extraction_class="skill", extraction_text="Docker"),
            lx.data.Extraction(extraction_class="skill", extraction_text="Kubernetes"),
            lx.data.Extraction(extraction_class="skill", extraction_text="PostgreSQL"),
            lx.data.Extraction(extraction_class="skill", extraction_text="AWS"),
        ],
    )
]


def _char_span(ext: lx.data.Extraction, page: int = 0) -> CharSpan | None:
    if ext.char_interval:
        return CharSpan(
            start=ext.char_interval.start_pos,
            end=ext.char_interval.end_pos,
            page=page,
            field=ext.extraction_class,
        )
    return None


def _group_experience_entries(
    extractions: list[lx.data.Extraction],
) -> list[ExperienceEntry]:
    """
    Group company/title/dates/bullets into ExperienceEntry objects.

    Always uses char-position-based grouping. The model-provided `entry`
    attribute is unreliable across complex multi-section resumes, so we
    ignore it and rely on LangExtract's verbatim char positions instead.
    """
    import re
    entry_map = _group_by_position(extractions)

    from app.pipeline.steps.normalizer import normalize_date

    current_re = re.compile(r"\b(present|current|now)\b", re.IGNORECASE)

    entries: list[ExperienceEntry] = []
    for key in sorted(entry_map.keys(), key=lambda k: int(k) if k.isdigit() else 0):
        grp = entry_map[key]
        dates_raw = grp["dates"]
        start_date = None
        end_date = None
        is_current = False

        if dates_raw:
            parts = re.split(r"\s*[-–—to]+\s*", dates_raw, maxsplit=1)
            start_date = normalize_date(parts[0].strip()) if parts else None
            if len(parts) > 1:
                end_raw = parts[1].strip()
                if current_re.search(end_raw):
                    is_current = True
                else:
                    end_date = normalize_date(end_raw)
            elif current_re.search(dates_raw):
                is_current = True

        entries.append(ExperienceEntry(
            company=grp["company"],
            title=grp["title"],
            location=grp["location"],
            start_date=start_date,
            end_date=end_date,
            is_current=is_current,
            bullets=grp["bullets"],
            confidence=ExperienceConfidence(),
            grounding=Grounding(char_spans=[s for s in grp["spans"] if s]),
        ))

    return entries


def _group_by_position(
    extractions: list[lx.data.Extraction],
) -> dict[str, dict]:
    """
    Group experience entities by char position in text.

    A new entry starts when we encounter a company_name or job_title AND:
      1. The current group already has BOTH company and title (role complete), OR
      2. The current group already has this exact field (duplicate = new role), OR
      3. We have seen at least one bullet since the last anchor (role is done).

    This prevents title + company appearing on the same line (e.g.
    "Product Management Intern, Unacademy") from being split into two entries.
    """
    sorted_exts = sorted(
        extractions,
        key=lambda e: e.char_interval.start_pos if e.char_interval else 0,
    )

    entries: dict[str, dict] = {}
    current_id = 0
    current_grp: dict = {
        "company": None, "title": None, "location": None,
        "dates": None, "bullets": [], "spans": [],
    }
    had_bullets = False  # any bullet seen since the last anchor

    for ext in sorted_exts:
        span = _char_span(ext)

        if ext.extraction_class in ("company_name", "job_title"):
            already_has_this_field = (
                (ext.extraction_class == "company_name" and current_grp["company"] is not None)
                or (ext.extraction_class == "job_title" and current_grp["title"] is not None)
            )
            has_both = (
                current_grp["company"] is not None and current_grp["title"] is not None
            )

            should_start_new = (current_grp["company"] or current_grp["title"]) and (
                had_bullets              # bullets seen → previous role is done
                or has_both             # both fields filled → definitely a new role
                or already_has_this_field  # duplicate field → new role
            )

            if should_start_new:
                entries[str(current_id)] = current_grp
                current_id += 1
                current_grp = {
                    "company": None, "title": None, "location": None,
                    "dates": None, "bullets": [], "spans": [],
                }
                had_bullets = False

        if span:
            current_grp["spans"].append(span)

        if ext.extraction_class == "company_name":
            current_grp["company"] = ext.extraction_text
        elif ext.extraction_class == "job_title":
            current_grp["title"] = ext.extraction_text
        elif ext.extraction_class == "job_location":
            current_grp["location"] = ext.extraction_text
        elif ext.extraction_class == "employment_dates":
            current_grp["dates"] = ext.extraction_text
        elif ext.extraction_class == "bullet_point":
            current_grp["bullets"].append(ext.extraction_text)
            had_bullets = True

    if current_grp["company"] or current_grp["title"]:
        entries[str(current_id)] = current_grp

    return entries


def extract(
    sections: dict[str, SectionBoundary],
    doc: ExtractedDocument,
    doc_id: str,
) -> CanonicalResume:
    """
    Run LangExtract on the resume text.
    Uses the experience section text if available, else full document.
    Returns a CanonicalResume (sync — LangExtract is synchronous).
    """
    if not settings.gemini_api_key:
        raise LlmExtractionError("GEMINI_API_KEY is not configured.")

    # Build input text
    if sections:
        parts = []
        for name, boundary in sections.items():
            parts.append(f"### {name.upper()}\n{boundary.text}")
        text = "\n\n".join(parts)
    else:
        text = doc.full_text[:50_000]

    log.info("langextract_start", doc_id=doc_id, text_chars=len(text))

    # Set API key env var for LangExtract
    os.environ["LANGEXTRACT_API_KEY"] = settings.gemini_api_key

    try:
        result = lx.extract(
            text_or_documents=text,
            prompt_description=PROMPT_DESCRIPTION,
            examples=EXAMPLES,
            model_id="gemini-2.5-flash",
            show_progress=False,
        )
    except Exception as e:
        raise LlmExtractionError(f"LangExtract error: {e}")

    # lx.extract returns a single AnnotatedDocument or list
    if isinstance(result, list):
        result = result[0] if result else None
    if result is None:
        raise LlmExtractionError("LangExtract returned no result.")

    extractions = result.extractions or []

    # Estimate cost — LangExtract doesn't expose usage_metadata, so we estimate
    # from input text chars + expected output chars (avg ~80 chars per extraction)
    from app.core.cost import estimate_from_chars
    _est_in_tok, _est_out_tok, _est_cost = estimate_from_chars(
        input_chars=len(text),
        output_chars=len(extractions) * 80,
    )
    log.info("langextract_done", doc_id=doc_id, num_extractions=len(extractions),
             est_input_tokens=_est_in_tok, est_output_tokens=_est_out_tok,
             est_cost_usd=round(_est_cost, 6))

    # ── Group into schema ─────────────────────────────────────────────────────
    exp_extractions = [
        e for e in extractions
        if e.extraction_class in (
            "company_name", "job_title", "employment_dates",
            "job_location", "bullet_point",
        )
    ]
    experience = _group_experience_entries(exp_extractions)

    skills = [
        e.extraction_text for e in extractions
        if e.extraction_class == "skill" and e.extraction_text
    ]

    # Education
    edu_degrees = [e for e in extractions if e.extraction_class == "education_degree"]
    edu_insts   = [e for e in extractions if e.extraction_class == "education_inst"]
    edu_dates   = [e for e in extractions if e.extraction_class == "education_dates"]
    edu_gpas    = [e for e in extractions if e.extraction_class == "gpa"]

    from app.pipeline.steps.normalizer import normalize_date
    education = []
    for i, deg in enumerate(edu_degrees):
        education.append(EducationEntry(
            degree=deg.extraction_text,
            institution=edu_insts[i].extraction_text if i < len(edu_insts) else None,
            start_date=None,
            end_date=normalize_date(edu_dates[i].extraction_text.split("-")[-1].strip())
                if i < len(edu_dates) else None,
            gpa=edu_gpas[i].extraction_text if i < len(edu_gpas) else None,
        ))

    summary_exts = [e for e in extractions if e.extraction_class == "summary_text"]
    summary = summary_exts[0].extraction_text if summary_exts else None

    return CanonicalResume(
        document=DocumentMeta(
            doc_id=doc_id,
            pages=doc.page_count,
            source_type=doc.source_type,
            file_hash="",   # filled by orchestrator
            language="en",
        ),
        sections=Sections(
            summary=summary,
            skills=skills,
            education=education,
        ),
        experience=experience,
        confidence=ConfidenceSet(overall=0.0),  # filled by confidence_scorer
        trace=PipelineTrace(
            api_calls=[ApiCallCost(
                step="langextract",
                input_tokens=_est_in_tok,
                output_tokens=_est_out_tok,
                cost_usd=_est_cost,
                note="estimated",
            )],
            total_cost_usd=_est_cost,
        ),
    )

"""
Structured extraction using Google Gemini.

Uses response_mime_type="application/json" with response_schema for
deterministic structured output. System prompt enforces "unknown-safe" behavior:
never fabricate — return null for uncertain fields.
"""
from __future__ import annotations
import json
import structlog
from google import genai
from google.genai import types as genai_types

from app.config import settings
from app.core.exceptions import LlmExtractionError
from app.schemas.internal import ExtractedDocument, SectionBoundary
from app.schemas.canonical import (
    CanonicalResume, ExperienceEntry, ExperienceConfidence,
    Sections, EducationEntry, CertificationEntry, ProjectEntry,
    ConfidenceSet, PipelineTrace, DocumentMeta, Grounding,
)

log = structlog.get_logger(__name__)

SYSTEM_PROMPT = """You are a resume parsing assistant. Extract structured information from the resume text.

Rules:
1. NEVER fabricate or invent data. If a field is not clearly present in the text, set it to null.
2. For dates, use format YYYY-MM if month is available, or YYYY if only year is known.
3. Set is_current=true and end_date=null when the person is still in that role ("Present", "Current", "Now", etc.).
4. For employment_type, infer from context (intern, contract, full-time) or set to "unknown".
5. Extract bullets as individual items — do not merge unrelated bullets.
6. Return partial results if some sections cannot be confidently extracted.
7. Prefer exact text from the resume over paraphrasing.
"""

# JSON schema for Gemini response
EXTRACTION_SCHEMA = {
    "type": "object",
    "properties": {
        "experience": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "company":         {"type": ["string", "null"]},
                    "title":           {"type": ["string", "null"]},
                    "location":        {"type": ["string", "null"]},
                    "start_date":      {"type": ["string", "null"]},
                    "end_date":        {"type": ["string", "null"]},
                    "is_current":      {"type": "boolean"},
                    "employment_type": {"type": ["string", "null"]},
                    "bullets":         {"type": "array", "items": {"type": "string"}},
                },
                "required": ["company", "title", "start_date", "end_date", "is_current", "bullets"],
            },
        },
        "summary":  {"type": ["string", "null"]},
        "skills":   {"type": "array", "items": {"type": "string"}},
        "education": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "institution": {"type": ["string", "null"]},
                    "degree":      {"type": ["string", "null"]},
                    "field":       {"type": ["string", "null"]},
                    "start_date":  {"type": ["string", "null"]},
                    "end_date":    {"type": ["string", "null"]},
                    "gpa":         {"type": ["string", "null"]},
                },
                "required": ["institution", "degree"],
            },
        },
        "certifications": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name":   {"type": ["string", "null"]},
                    "issuer": {"type": ["string", "null"]},
                    "date":   {"type": ["string", "null"]},
                },
                "required": ["name"],
            },
        },
        "projects": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name":         {"type": ["string", "null"]},
                    "description":  {"type": ["string", "null"]},
                    "technologies": {"type": "array", "items": {"type": "string"}},
                    "url":          {"type": ["string", "null"]},
                },
                "required": ["name"],
            },
        },
    },
    "required": ["experience", "skills"],
}


def _build_prompt(sections: dict[str, SectionBoundary], doc: ExtractedDocument) -> str:
    """Build extraction prompt. Use section text if available, else full doc."""
    if sections:
        parts = ["## Resume Sections\n"]
        for name, boundary in sections.items():
            parts.append(f"### {name.upper()}\n{boundary.text}\n")
        return "\n".join(parts)
    else:
        # Truncate to avoid Gemini context limits (fallback)
        text = doc.full_text[:50_000]
        return f"## Full Resume Text\n\n{text}"


async def extract(
    sections: dict[str, SectionBoundary],
    doc: ExtractedDocument,
    doc_id: str,
) -> CanonicalResume:
    """Call Gemini and parse structured output into CanonicalResume."""
    if not settings.gemini_api_key:
        raise LlmExtractionError("GEMINI_API_KEY is not configured.")

    client = genai.Client(api_key=settings.gemini_api_key)

    prompt = _build_prompt(sections, doc)
    full_prompt = f"{SYSTEM_PROMPT}\n\n{prompt}"

    log.info("gemini_extract_start", doc_id=doc_id, prompt_chars=len(full_prompt))

    try:
        response = await client.aio.models.generate_content(
            model="gemini-2.5-flash",
            contents=full_prompt,
            config=genai_types.GenerateContentConfig(
                response_mime_type="application/json",
                temperature=0.0,
            ),
        )
    except Exception as e:
        raise LlmExtractionError(f"Gemini API error: {e}")

    try:
        raw = json.loads(response.text)
    except (json.JSONDecodeError, AttributeError) as e:
        raise LlmExtractionError(f"Gemini returned invalid JSON: {e}\nRaw: {getattr(response, 'text', '')[:500]}")

    log.info("gemini_extract_done", doc_id=doc_id)
    return _parse_raw(raw, doc, doc_id, sections)


def _coerce_skills(value) -> list:
    """Flatten skills whether Gemini returns a list or a categorized dict."""
    if not value:
        return []
    if isinstance(value, list):
        return [str(s) for s in value if s]
    if isinstance(value, dict):
        flat = []
        for v in value.values():
            if isinstance(v, list):
                flat.extend(str(s) for s in v if s)
            elif v:
                flat.append(str(v))
        return flat
    return []


def _coerce_str(value) -> str | None:
    """Convert a value to string, handling cases where Gemini returns a list instead of a string."""
    if value is None:
        return None
    if isinstance(value, list):
        return " ".join(str(v) for v in value if v)
    return str(value)


def _parse_raw(
    raw: dict,
    doc: ExtractedDocument,
    doc_id: str,
    sections: dict[str, SectionBoundary],
) -> CanonicalResume:
    """Convert Gemini JSON response to CanonicalResume."""
    experience: list[ExperienceEntry] = []
    for entry in raw.get("experience") or []:
        experience.append(ExperienceEntry(
            company=entry.get("company"),
            title=entry.get("title"),
            location=entry.get("location"),
            start_date=entry.get("start_date"),
            end_date=entry.get("end_date"),
            is_current=bool(entry.get("is_current", False)),
            employment_type=entry.get("employment_type"),
            bullets=[b for b in (entry.get("bullets") or []) if b],
            confidence=ExperienceConfidence(),  # filled by confidence_scorer later
            grounding=Grounding(),              # filled by grounding step later
        ))

    education: list[EducationEntry] = [
        EducationEntry(
            institution=e.get("institution"),
            degree=e.get("degree"),
            field=e.get("field"),
            start_date=e.get("start_date"),
            end_date=e.get("end_date"),
            gpa=e.get("gpa"),
        )
        for e in (raw.get("education") or [])
    ]

    certifications: list[CertificationEntry] = [
        CertificationEntry(name=c.get("name"), issuer=c.get("issuer"), date=c.get("date"))
        for c in (raw.get("certifications") or [])
    ]

    projects: list[ProjectEntry] = [
        ProjectEntry(
            name=p.get("name"),
            description=_coerce_str(p.get("description")),
            technologies=p.get("technologies") or [],
            url=p.get("url"),
        )
        for p in (raw.get("projects") or [])
    ]

    return CanonicalResume(
        document=DocumentMeta(
            doc_id=doc_id,
            pages=doc.page_count,
            source_type=doc.source_type,
            file_hash="",   # filled by orchestrator
            language="en",
        ),
        sections=Sections(
            summary=raw.get("summary"),
            skills=_coerce_skills(raw.get("skills")),
            education=education,
            projects=projects,
            certifications=certifications,
        ),
        experience=experience,
        confidence=ConfidenceSet(overall=0.0),   # filled by confidence_scorer
        trace=PipelineTrace(),                    # filled by orchestrator
    )

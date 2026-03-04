from __future__ import annotations
from typing import Any, Optional
from pydantic import BaseModel, Field


# ── Grounding ─────────────────────────────────────────────────────────────────

class CharSpan(BaseModel):
    start: int
    end: int
    page: int = 0
    field: str = ""


class PageSpan(BaseModel):
    page: int
    x1: float
    y1: float
    x2: float
    y2: float
    field: str = ""


class Grounding(BaseModel):
    char_spans: list[CharSpan] = Field(default_factory=list)
    page_spans: list[PageSpan] = Field(default_factory=list)


# ── Per-entry confidence ──────────────────────────────────────────────────────

class ExperienceConfidence(BaseModel):
    company: float = Field(1.0, ge=0.0, le=1.0)
    title:   float = Field(1.0, ge=0.0, le=1.0)
    dates:   float = Field(1.0, ge=0.0, le=1.0)
    bullets: float = Field(1.0, ge=0.0, le=1.0)
    overall: float = Field(1.0, ge=0.0, le=1.0)


# ── Experience ────────────────────────────────────────────────────────────────

class ExperienceEntry(BaseModel):
    company:         Optional[str] = None
    title:           Optional[str] = None
    location:        Optional[str] = None
    start_date:      Optional[str] = None   # YYYY-MM or YYYY
    end_date:        Optional[str] = None   # YYYY-MM, YYYY, or None if current
    is_current:      bool = False
    employment_type: Optional[str] = None   # full-time | intern | contract | unknown
    bullets:         list[str] = Field(default_factory=list)
    raw_text:        Optional[str] = None   # optional raw block for debugging
    confidence:      ExperienceConfidence = Field(default_factory=ExperienceConfidence)
    grounding:       Grounding = Field(default_factory=Grounding)


# ── Education ─────────────────────────────────────────────────────────────────

class EducationEntry(BaseModel):
    institution: Optional[str] = None
    degree:      Optional[str] = None
    field:       Optional[str] = None
    start_date:  Optional[str] = None
    end_date:    Optional[str] = None
    gpa:         Optional[str] = None
    confidence:  float = Field(1.0, ge=0.0, le=1.0)
    grounding:   Grounding = Field(default_factory=Grounding)


# ── Certification ─────────────────────────────────────────────────────────────

class CertificationEntry(BaseModel):
    name:       Optional[str] = None
    issuer:     Optional[str] = None
    date:       Optional[str] = None
    confidence: float = Field(1.0, ge=0.0, le=1.0)


# ── Project ───────────────────────────────────────────────────────────────────

class ProjectEntry(BaseModel):
    name:        Optional[str] = None
    description: Optional[str] = None
    technologies: list[str] = Field(default_factory=list)
    url:         Optional[str] = None
    confidence:  float = Field(1.0, ge=0.0, le=1.0)


# ── Sections ─────────────────────────────────────────────────────────────────

class Sections(BaseModel):
    summary:        Optional[str] = None
    skills:         list[str] = Field(default_factory=list)
    education:      list[EducationEntry] = Field(default_factory=list)
    projects:       list[ProjectEntry] = Field(default_factory=list)
    certifications: list[CertificationEntry] = Field(default_factory=list)


# ── Document metadata ─────────────────────────────────────────────────────────

class DocumentMeta(BaseModel):
    doc_id:      str
    pages:       int
    mime:        str = "application/pdf"
    source_type: str            # digital | scanned | hybrid
    file_hash:   str
    language:    Optional[str] = None


# ── Pipeline trace ────────────────────────────────────────────────────────────

class ApiCallCost(BaseModel):
    step:         str
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd:     float = 0.0
    note:         str = ""   # "exact" | "estimated"


class PipelineTrace(BaseModel):
    route:      list[str] = Field(default_factory=list)
    warnings:   list[str] = Field(default_factory=list)
    errors:     list[str] = Field(default_factory=list)
    api_calls:  list[ApiCallCost] = Field(default_factory=list)
    total_cost_usd: float = 0.0


# ── Overall confidence ────────────────────────────────────────────────────────

class ConfidenceSet(BaseModel):
    overall:        float = Field(0.0, ge=0.0, le=1.0)
    experience:     Optional[float] = Field(None, ge=0.0, le=1.0)
    education:      Optional[float] = Field(None, ge=0.0, le=1.0)
    skills:         Optional[float] = Field(None, ge=0.0, le=1.0)


# ── Top-level canonical output ────────────────────────────────────────────────

class CanonicalResume(BaseModel):
    schema_version: str = "1.0"
    document:       DocumentMeta
    sections:       Sections
    experience:     list[ExperienceEntry] = Field(default_factory=list)
    # Fallback when full structured parse fails
    experience_raw_blocks: list[dict[str, Any]] = Field(default_factory=list)
    # Total FTE years (freelance counted; internships / side-projects excluded)
    total_experience_years: Optional[float] = None
    confidence:     ConfidenceSet
    trace:          PipelineTrace

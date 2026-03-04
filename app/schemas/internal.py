"""
Internal pipeline data contracts.
These are NEVER serialised to the API client.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional

from app.schemas.canonical import PipelineTrace


@dataclass
class BBox:
    """Character bounding box from PyMuPDF (normalised 0-1 coordinates)."""
    char: str
    x0: float
    y0: float
    x1: float
    y1: float
    page: int
    char_index: int  # position in page_text string


@dataclass
class PageText:
    page_number: int      # 0-indexed
    text: str
    char_offset: int      # cumulative char offset in the full-document string
    bboxes: list[BBox] = field(default_factory=list)


@dataclass
class ExtractedDocument:
    full_text: str
    pages: list[PageText]
    page_count: int
    extraction_method: str   # pymupdf | pdfplumber | mistral_ocr
    quality_score: float = 0.0
    source_type: str = "digital"  # digital | scanned | hybrid


@dataclass
class SectionBoundary:
    name: str
    heading_text: str
    start_char: int
    end_char: int           # exclusive; set to start of next section
    text: str


@dataclass
class PipelineContext:
    job_id: str
    file_path: str
    file_hash: str
    extracted: Optional[ExtractedDocument] = None
    sections: dict[str, SectionBoundary] = field(default_factory=dict)
    trace: PipelineTrace = field(default_factory=PipelineTrace)
    force_ocr: bool = False

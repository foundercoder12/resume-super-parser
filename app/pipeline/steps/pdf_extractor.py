"""
PDF text extraction using PyMuPDF (primary) and pdfplumber (fallback).

PyMuPDF gives char-level bounding boxes needed for grounding.
pdfplumber is used as a fallback for multi-column/table-heavy layouts.
"""
from __future__ import annotations
import structlog
import fitz          # PyMuPDF
import pdfplumber

from app.schemas.internal import ExtractedDocument, PageText, BBox
from app.core.exceptions import PdfExtractionError, EncryptedPdfError

log = structlog.get_logger(__name__)


def extract_with_pymupdf(file_path: str) -> ExtractedDocument:
    """Extract text and char-level bounding boxes using PyMuPDF."""
    try:
        doc = fitz.open(file_path)
    except fitz.FileDataError as e:
        raise PdfExtractionError(f"Cannot open PDF: {e}")

    if doc.is_encrypted:
        doc.close()
        raise EncryptedPdfError("PDF is encrypted and no password was provided.")

    pages: list[PageText] = []
    full_text_parts: list[str] = []
    cumulative_offset = 0

    for page_num in range(doc.page_count):
        page = doc[page_num]
        page_text = page.get_text("text", flags=fitz.TEXT_PRESERVE_WHITESPACE | fitz.TEXT_PRESERVE_LIGATURES)

        # Extract char-level bboxes for grounding
        bboxes: list[BBox] = []
        try:
            raw = page.get_text("rawdict", flags=fitz.TEXT_PRESERVE_WHITESPACE)
            char_index = 0
            for block in raw.get("blocks", []):
                if block.get("type") != 0:  # skip image blocks
                    continue
                for line in block.get("lines", []):
                    for span in line.get("spans", []):
                        page_w = page.rect.width or 1
                        page_h = page.rect.height or 1
                        for char_data in span.get("chars", []):
                            bbox = char_data.get("bbox", (0, 0, 0, 0))
                            bboxes.append(BBox(
                                char=char_data.get("c", ""),
                                x0=bbox[0] / page_w,
                                y0=bbox[1] / page_h,
                                x1=bbox[2] / page_w,
                                y1=bbox[3] / page_h,
                                page=page_num,
                                char_index=cumulative_offset + char_index,
                            ))
                            char_index += 1
        except Exception as e:
            log.warning("bbox_extraction_failed", page=page_num, error=str(e))

        pages.append(PageText(
            page_number=page_num,
            text=page_text,
            char_offset=cumulative_offset,
            bboxes=bboxes,
        ))
        full_text_parts.append(page_text)
        cumulative_offset += len(page_text)

    doc.close()
    return ExtractedDocument(
        full_text="\n".join(full_text_parts),
        pages=pages,
        page_count=len(pages),
        extraction_method="pymupdf",
    )


def extract_with_pdfplumber(file_path: str, pymupdf_bboxes: list[BBox]) -> ExtractedDocument:
    """
    Use pdfplumber text (better for multi-column) but retain PyMuPDF bboxes for grounding.
    Called when quality scorer detects garbled column ordering from PyMuPDF.
    """
    pages: list[PageText] = []
    full_text_parts: list[str] = []
    cumulative_offset = 0

    try:
        with pdfplumber.open(file_path) as pdf:
            for page_num, page in enumerate(pdf.pages):
                page_text = page.extract_text(x_tolerance=3, y_tolerance=3) or ""
                page_bboxes = [b for b in pymupdf_bboxes if b.page == page_num]

                pages.append(PageText(
                    page_number=page_num,
                    text=page_text,
                    char_offset=cumulative_offset,
                    bboxes=page_bboxes,
                ))
                full_text_parts.append(page_text)
                cumulative_offset += len(page_text)
    except Exception as e:
        raise PdfExtractionError(f"pdfplumber extraction failed: {e}")

    return ExtractedDocument(
        full_text="\n".join(full_text_parts),
        pages=pages,
        page_count=len(pages),
        extraction_method="pdfplumber",
    )


def extract(file_path: str) -> tuple[ExtractedDocument, list[BBox]]:
    """
    Run PyMuPDF extraction. Collect all bboxes for potential grounding later.
    Returns (extracted_doc, all_bboxes).
    The caller (orchestrator) decides whether to use pdfplumber text instead.
    """
    doc = extract_with_pymupdf(file_path)
    all_bboxes = [bbox for page in doc.pages for bbox in page.bboxes]
    log.info("pdf_extracted", method="pymupdf", pages=doc.page_count, chars=len(doc.full_text))
    return doc, all_bboxes

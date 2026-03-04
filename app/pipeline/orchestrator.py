"""
Pipeline orchestrator — chains all pipeline steps in order.

Flow:
  1. PDF extraction (PyMuPDF)
  2. Quality scoring → route to OCR if needed
  3. Section detection
  4. LangExtract structured extraction (verbatim, char-grounded)
  5. Normalization
  6. Confidence scoring
  7. Return CanonicalResume
"""
from __future__ import annotations
import asyncio
import structlog

from app.config import settings
from app.core.exceptions import ResumeParserError, LlmExtractionError
from app.schemas.canonical import CanonicalResume, PipelineTrace, DocumentMeta, Sections, ConfidenceSet, ApiCallCost
from app.schemas.internal import ExtractedDocument

from app.pipeline.steps import pdf_extractor, quality_scorer, ocr_client, section_detector
from app.pipeline.steps import langextract_extractor, normalizer, confidence_scorer

log = structlog.get_logger(__name__)


async def run(
    job_id: str,
    file_path: str,
    file_hash: str,
    force_ocr: bool = False,
) -> CanonicalResume:
    """
    Execute the full resume parsing pipeline.
    Returns a CanonicalResume. On partial failure, returns a low-confidence result
    with trace.errors populated rather than raising.
    """
    trace = PipelineTrace()

    # ── Step 1: PDF extraction ────────────────────────────────────────────────
    log.info("pipeline_step", step="pdf_extract", job_id=job_id)
    try:
        doc, all_bboxes = pdf_extractor.extract(file_path)
        trace.route.append("pymupdf")
    except ResumeParserError:
        raise
    except Exception as e:
        raise ResumeParserError(f"PDF extraction failed: {e}")

    # ── Step 2: Quality scoring ───────────────────────────────────────────────
    log.info("pipeline_step", step="quality_score", job_id=job_id)
    quality = quality_scorer.score(doc)
    doc.quality_score = quality
    doc.source_type = quality_scorer.classify_source_type(quality)
    trace.route.append("quality_score")

    # ── Step 3: OCR (conditional) ─────────────────────────────────────────────
    needs_ocr = force_ocr or (quality < settings.ocr_quality_threshold)
    if needs_ocr:
        log.info("pipeline_step", step="ocr", quality=quality, job_id=job_id)
        trace.route.append("mistral_ocr")
        if quality < settings.ocr_quality_threshold:
            trace.warnings.append(f"low_text_quality_fallback_to_ocr (score={quality})")
        try:
            doc = await ocr_client.run_ocr(file_path)
        except ResumeParserError as e:
            trace.errors.append(f"ocr_failed: {e}")
            trace.warnings.append("ocr_failed_continuing_with_pdf_text")
            # Continue with original low-quality extraction
    elif doc.extraction_method == "pymupdf" and quality < 0.75:
        # Try pdfplumber for potentially better column ordering
        try:
            plumber_doc = pdf_extractor.extract_with_pdfplumber(file_path, all_bboxes)
            plumber_quality = quality_scorer.score(plumber_doc)
            if plumber_quality > quality:
                doc = plumber_doc
                doc.quality_score = plumber_quality
                trace.route.append("pdfplumber_fallback")
                trace.warnings.append("pdfplumber_used_for_better_column_ordering")
        except Exception:
            pass  # pdfplumber fallback failure is silent

    # ── Step 4: Section detection ─────────────────────────────────────────────
    log.info("pipeline_step", step="section_detect", job_id=job_id)
    sections = section_detector.detect(doc.full_text)
    trace.route.append("section_detect")

    # Capture section-detector LLM cost (exact token counts from Gemini metadata)
    llm_usage = section_detector.pop_last_llm_usage()
    if llm_usage:
        trace.api_calls.append(ApiCallCost(
            step="section_detect",
            input_tokens=llm_usage["input_tokens"],
            output_tokens=llm_usage["output_tokens"],
            cost_usd=llm_usage["cost_usd"],
            note="exact",
        ))
        trace.total_cost_usd += llm_usage["cost_usd"]

    if not sections:
        trace.warnings.append("no_sections_detected_using_full_text")

    # ── Step 5: LangExtract structured extraction ─────────────────────────────
    log.info("pipeline_step", step="langextract", job_id=job_id)
    trace.route.append("langextract")

    try:
        loop = asyncio.get_event_loop()
        resume = await loop.run_in_executor(
            None, langextract_extractor.extract, sections, doc, job_id
        )
    except LlmExtractionError as e:
        trace.errors.append(f"langextract_failed: {e}")
        return _empty_result(job_id, doc, file_hash, trace)

    # Merge LangExtract cost into trace
    for api_call in resume.trace.api_calls:
        trace.api_calls.append(api_call)
        trace.total_cost_usd += api_call.cost_usd

    # Attach file hash to document meta
    resume = resume.model_copy(
        update={"document": resume.document.model_copy(update={"file_hash": file_hash})}
    )

    # ── Step 6: Normalization ─────────────────────────────────────────────────
    log.info("pipeline_step", step="normalize", job_id=job_id)
    resume = normalizer.normalize(resume)
    trace.route.append("normalize")

    # ── Step 7: Confidence scoring ────────────────────────────────────────────
    log.info("pipeline_step", step="confidence_score", job_id=job_id)
    resume = confidence_scorer.score(resume)
    trace.route.append("confidence_score")

    # Attach final trace
    resume = resume.model_copy(update={"trace": trace})

    log.info(
        "pipeline_complete",
        job_id=job_id,
        experience_count=len(resume.experience),
        overall_confidence=resume.confidence.overall,
    )
    return resume


def _empty_result(
    job_id: str,
    doc: ExtractedDocument,
    file_hash: str,
    trace: PipelineTrace,
) -> CanonicalResume:
    """Return a minimal result when extraction fails completely."""
    trace.warnings.append("extraction_failed_returning_empty_result")

    # Provide raw blocks so caller can debug
    raw_blocks = [
        {"page": p.page_number, "text": p.text[:2000]}
        for p in doc.pages
    ]

    return CanonicalResume(
        document=DocumentMeta(
            doc_id=job_id,
            pages=doc.page_count,
            source_type=doc.source_type,
            file_hash=file_hash,
        ),
        sections=Sections(),
        experience=[],
        experience_raw_blocks=raw_blocks,
        confidence=ConfidenceSet(overall=0.0),
        trace=trace,
    )

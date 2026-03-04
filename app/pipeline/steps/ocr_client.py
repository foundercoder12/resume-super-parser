"""
Mistral OCR integration.

Key design choices:
  - Only invoked when quality_score < threshold
  - Uploads as base64 data URI — no public hosting of PII
  - Returns Markdown text per page
  - Raises OcrError on failure (handled by orchestrator with retry)
"""
from __future__ import annotations
import base64
import structlog
import httpx

from app.config import settings
from app.core.exceptions import OcrError
from app.schemas.internal import ExtractedDocument, PageText

log = structlog.get_logger(__name__)

MISTRAL_OCR_URL = "https://api.mistral.ai/v1/ocr"
TIMEOUT_SECONDS = 180.0


async def run_ocr(file_path: str) -> ExtractedDocument:
    """Send PDF to Mistral OCR, return ExtractedDocument with Markdown text."""
    if not settings.mistral_api_key:
        raise OcrError("MISTRAL_API_KEY is not configured.")

    with open(file_path, "rb") as f:
        pdf_bytes = f.read()

    b64 = base64.b64encode(pdf_bytes).decode()
    data_uri = f"data:application/pdf;base64,{b64}"

    payload = {
        "model": "mistral-ocr-latest",
        "document": {
            "type": "document_url",
            "document_url": data_uri,
        },
        "include_image_base64": False,
    }

    log.info("ocr_request_start", file_path=file_path)

    try:
        async with httpx.AsyncClient(timeout=TIMEOUT_SECONDS) as client:
            resp = await client.post(
                MISTRAL_OCR_URL,
                headers={
                    "Authorization": f"Bearer {settings.mistral_api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
            )
            resp.raise_for_status()
            data = resp.json()
    except httpx.HTTPStatusError as e:
        raise OcrError(f"Mistral OCR HTTP error {e.response.status_code}: {e.response.text}")
    except httpx.RequestError as e:
        raise OcrError(f"Mistral OCR network error: {e}")

    raw_pages = data.get("pages", [])
    pages: list[PageText] = []
    cumulative_offset = 0
    full_parts: list[str] = []

    for i, page_data in enumerate(raw_pages):
        page_text = page_data.get("markdown", "") or ""
        pages.append(PageText(
            page_number=i,
            text=page_text,
            char_offset=cumulative_offset,
            bboxes=[],  # Mistral OCR does not provide char-level bboxes
        ))
        full_parts.append(page_text)
        cumulative_offset += len(page_text)

    full_text = "\n\n".join(full_parts)
    log.info("ocr_complete", pages=len(pages), chars=len(full_text))

    return ExtractedDocument(
        full_text=full_text,
        pages=pages,
        page_count=len(pages),
        extraction_method="mistral_ocr",
        quality_score=0.85,  # post-OCR assumed acceptable
        source_type="scanned",
    )

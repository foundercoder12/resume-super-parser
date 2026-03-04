"""
POST /v1/resumes:parse

Accepts a PDF file upload, validates it, deduplicates by file hash,
creates a Job record, and enqueues a Celery task.
"""
from __future__ import annotations
import uuid
from datetime import datetime, timedelta, timezone

import structlog
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
import redis.asyncio as aioredis

from app.config import settings
from app.core.hashing import sha256_hex
from app.db.models import Job, JobStatus
from app.db.session import AsyncSessionLocal
from app.dependencies import get_db, get_redis
from app.schemas.api import ParseJobResponse
from app.storage.file_store import file_store
from app.workers.tasks import process_resume_job

log = structlog.get_logger(__name__)

router = APIRouter()

DEDUPE_TTL_SECONDS = 86400 * 7  # 7 days
DEDUPE_KEY_PREFIX = "dedupe:file:"


@router.post("/resumes:parse", response_model=ParseJobResponse, status_code=status.HTTP_202_ACCEPTED)
async def parse_resume(
    file: UploadFile = File(..., description="Resume PDF file"),
    retain_days: int = Form(default=30, ge=1, le=365),
    force_ocr: bool = Form(default=False),
    db: AsyncSession = Depends(get_db),
    redis: aioredis.Redis = Depends(get_redis),
):
    # ── Validation ────────────────────────────────────────────────────────────
    if file.content_type not in ("application/pdf", "application/octet-stream"):
        raise HTTPException(status_code=400, detail="Only PDF files are accepted.")

    data = await file.read()

    if len(data) > settings.max_file_size_bytes:
        raise HTTPException(
            status_code=400,
            detail=f"File exceeds maximum size of {settings.max_file_size_mb}MB."
        )

    if len(data) < 100:
        raise HTTPException(status_code=400, detail="File appears to be empty or corrupted.")

    # ── Dedupe check ──────────────────────────────────────────────────────────
    file_hash = sha256_hex(data)
    dedupe_key = f"{DEDUPE_KEY_PREFIX}{file_hash}"
    existing_job_id = await redis.get(dedupe_key)

    if existing_job_id:
        log.info("dedupe_hit", file_hash=file_hash, existing_job_id=existing_job_id)
        return ParseJobResponse(
            job_id=uuid.UUID(existing_job_id),
            status="duplicate",
            message="This file has already been submitted. Returning existing job.",
            duplicate=True,
            poll_url=f"/v1/jobs/{existing_job_id}",
        )

    # ── Save file ─────────────────────────────────────────────────────────────
    filename = f"{file_hash}.pdf"
    store = file_store()
    file_path = store.save(data, filename)

    # ── Create job record ─────────────────────────────────────────────────────
    job_id = uuid.uuid4()
    retain_until = datetime.now(timezone.utc) + timedelta(days=retain_days)

    job = Job(
        id=job_id,
        status=JobStatus.PENDING,
        file_hash=file_hash,
        file_path=file_path,
        original_filename=file.filename or "resume.pdf",
        file_size_bytes=len(data),
        retain_until=retain_until,
    )
    db.add(job)
    await db.commit()

    # ── Store dedupe key ──────────────────────────────────────────────────────
    await redis.setex(dedupe_key, DEDUPE_TTL_SECONDS, str(job_id))

    # ── Enqueue Celery task ───────────────────────────────────────────────────
    task = process_resume_job.delay(str(job_id), force_ocr=force_ocr)
    job.celery_task_id = task.id
    await db.commit()

    log.info("job_created", job_id=str(job_id), file_hash=file_hash)

    return ParseJobResponse(
        job_id=job_id,
        status="pending",
        message="Resume submitted for processing.",
        duplicate=False,
        poll_url=f"/v1/jobs/{job_id}",
    )

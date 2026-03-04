"""
Celery tasks for resume processing.

The main task `process_resume_job`:
  1. Marks job as RUNNING
  2. Runs the pipeline orchestrator
  3. Persists canonical result to Document table
  4. Marks job as SUCCEEDED or FAILED
  5. Retries on transient errors (OCR/Gemini 5xx, network issues)
"""
from __future__ import annotations
import asyncio
import uuid
from datetime import datetime, timezone

import structlog
from celery import Task
from sqlalchemy import select

from app.workers.celery_app import celery_app
from app.db.models import Job, Document, JobStatus
from app.core.exceptions import ResumeParserError
from app.pipeline import orchestrator

log = structlog.get_logger(__name__)


def _run_async(coro):
    """Run an async coroutine from sync Celery task context."""
    return asyncio.get_event_loop().run_until_complete(coro)


@celery_app.task(
    bind=True,
    name="resume_parser.process_resume_job",
    max_retries=3,
    default_retry_delay=15,
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_backoff_max=60,
    retry_jitter=True,
)
def process_resume_job(self: Task, job_id: str, force_ocr: bool = False) -> dict:
    """
    Main Celery task: run the full parsing pipeline for a job.
    Returns the canonical result dict on success.
    """
    log.info("task_start", job_id=job_id, attempt=self.request.retries + 1)

    async def _run():
        from app.db.session import AsyncSessionLocal
        async with AsyncSessionLocal() as session:
            # Load job
            result = await session.execute(select(Job).where(Job.id == uuid.UUID(job_id)))
            job: Job | None = result.scalar_one_or_none()
            if job is None:
                log.error("job_not_found", job_id=job_id)
                return None

            # Mark running
            job.status = JobStatus.RUNNING
            job.started_at = datetime.now(timezone.utc)
            await session.commit()

            try:
                canonical = await orchestrator.run(
                    job_id=job_id,
                    file_path=job.file_path,
                    file_hash=job.file_hash,
                    force_ocr=force_ocr,
                )
            except ResumeParserError as e:
                job.status = JobStatus.FAILED
                job.error_code = e.error_code
                job.error_message = str(e)
                job.completed_at = datetime.now(timezone.utc)
                await session.commit()
                log.error("pipeline_failed", job_id=job_id, error_code=e.error_code)
                return None

            # Persist canonical result
            result_dict = canonical.model_dump(mode="json")
            doc = Document(
                job_id=uuid.UUID(job_id),
                page_count=canonical.document.pages,
                source_type=canonical.document.source_type,
                canonical_result=result_dict,
            )
            session.add(doc)

            job.status = JobStatus.SUCCEEDED
            job.pipeline_trace = canonical.trace.model_dump(mode="json")
            job.completed_at = datetime.now(timezone.utc)
            await session.commit()

            log.info(
                "task_complete",
                job_id=job_id,
                experience_count=len(canonical.experience),
                confidence=canonical.confidence.overall,
            )
            return result_dict

    return _run_async(_run())

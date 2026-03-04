"""
GET /v1/jobs/{job_id}          — job status
GET /v1/jobs/{job_id}/result   — canonical result (when succeeded)
"""
from __future__ import annotations
import uuid

import structlog
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.db.models import Job, JobStatus
from app.dependencies import get_db
from app.schemas.api import JobStatusResponse, JobResultResponse

log = structlog.get_logger(__name__)
router = APIRouter()


def _fmt_dt(dt) -> str | None:
    return dt.isoformat() if dt else None


@router.get("/jobs/{job_id}", response_model=JobStatusResponse)
async def get_job_status(
    job_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Job).where(Job.id == job_id))
    job: Job | None = result.scalar_one_or_none()
    if job is None:
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found.")

    return JobStatusResponse(
        job_id=job.id,
        status=job.status.value,
        created_at=_fmt_dt(job.created_at),
        started_at=_fmt_dt(job.started_at),
        completed_at=_fmt_dt(job.completed_at),
        error_code=job.error_code,
        error_message=job.error_message,
    )


@router.get("/jobs/{job_id}/result", response_model=JobResultResponse)
async def get_job_result(
    job_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Job)
        .options(selectinload(Job.document))
        .where(Job.id == job_id)
    )
    job: Job | None = result.scalar_one_or_none()

    if job is None:
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found.")

    if job.status in (JobStatus.PENDING, JobStatus.RUNNING):
        # 202 Accepted: still processing
        from fastapi.responses import JSONResponse
        return JSONResponse(
            status_code=status.HTTP_202_ACCEPTED,
            content={
                "job_id": str(job_id),
                "status": job.status.value,
                "result": None,
                "message": "Job is still processing. Poll again shortly.",
            },
        )

    if job.status == JobStatus.FAILED:
        return JobResultResponse(
            job_id=job.id,
            status="failed",
            result={
                "error_code": job.error_code,
                "error_message": job.error_message,
                "trace": job.pipeline_trace,
            },
        )

    if job.status == JobStatus.DUPLICATE:
        raise HTTPException(
            status_code=301,
            detail=f"This is a duplicate job. See original: /v1/jobs/{job.duplicate_of_id}/result",
        )

    # Succeeded
    if job.document is None:
        raise HTTPException(status_code=500, detail="Job succeeded but document record is missing.")

    return JobResultResponse(
        job_id=job.id,
        status="succeeded",
        result=job.document.canonical_result,
    )

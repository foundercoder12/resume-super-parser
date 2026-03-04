"""
GET /v1/metrics  — aggregated monitoring stats (no LLM, pure DB queries).

Metrics returned:
  summary       — total / succeeded / failed / success_rate / avg_parse_time /
                  avg_confidence / avg_cost / ocr_rate / duplicate_rate
  source_breakdown  — digital / scanned / hybrid counts
  failure_reasons   — [{error_code, count}] sorted descending
  daily_throughput  — [{date, count}] last 30 days
  recent_jobs       — last 20 jobs with status + timings
"""
from __future__ import annotations
from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, text

from app.db.models import Job, JobStatus, Document
from app.dependencies import get_db

router = APIRouter()


@router.get("/metrics", response_model=None)
async def get_metrics(db: AsyncSession = Depends(get_db)) -> dict[str, Any]:

    # ── Status counts ────────────────────────────────────────────────────────
    status_rows = (await db.execute(
        select(Job.status, func.count().label("n")).group_by(Job.status)
    )).all()
    counts: dict[str, int] = {row.status.value: row.n for row in status_rows}

    total     = sum(counts.values())
    succeeded = counts.get("succeeded", 0)
    failed    = counts.get("failed", 0)

    # ── Avg parse time (succeeded jobs only) ────────────────────────────────
    avg_parse_s = (await db.execute(
        select(
            func.avg(func.extract("epoch", Job.completed_at - Job.started_at))
        )
        .where(Job.status == JobStatus.SUCCEEDED)
        .where(Job.started_at.isnot(None))
        .where(Job.completed_at.isnot(None))
    )).scalar()

    # ── Failure reasons ──────────────────────────────────────────────────────
    fail_rows = (await db.execute(
        select(Job.error_code, func.count().label("n"))
        .where(Job.status == JobStatus.FAILED)
        .group_by(Job.error_code)
        .order_by(func.count().desc())
    )).all()
    failure_reasons = [
        {"error_code": r.error_code or "unknown", "count": r.n}
        for r in fail_rows
    ]

    # ── JSONB-based stats from documents ────────────────────────────────────
    # Avg overall confidence score
    avg_conf = (await db.execute(text(
        "SELECT AVG((canonical_result -> 'confidence' ->> 'overall')::float) "
        "FROM documents WHERE canonical_result IS NOT NULL"
    ))).scalar()

    # Avg total cost per parse
    avg_cost = (await db.execute(text(
        "SELECT AVG((canonical_result -> 'trace' ->> 'total_cost_usd')::float) "
        "FROM documents WHERE canonical_result IS NOT NULL"
    ))).scalar()

    # Count how many parses used OCR (route array contains 'mistral_ocr')
    ocr_count = (await db.execute(text(
        "SELECT COUNT(*) FROM documents "
        "WHERE canonical_result -> 'trace' -> 'route' ? 'mistral_ocr'"
    ))).scalar() or 0

    # ── Source type breakdown ─────────────────────────────────────────────────
    src_rows = (await db.execute(
        select(Document.source_type, func.count().label("n"))
        .group_by(Document.source_type)
    )).all()
    source_breakdown = {r.source_type: r.n for r in src_rows}

    # ── Daily throughput — last 30 days ─────────────────────────────────────
    daily_rows = (await db.execute(text(
        "SELECT DATE(created_at AT TIME ZONE 'UTC') AS day, COUNT(*) AS n "
        "FROM jobs "
        "WHERE created_at >= NOW() - INTERVAL '30 days' "
        "GROUP BY day ORDER BY day"
    ))).all()
    daily_throughput = [{"date": str(r.day), "count": r.n} for r in daily_rows]

    # ── Recent 20 jobs ───────────────────────────────────────────────────────
    recent_rows = (await db.execute(
        select(Job).order_by(Job.created_at.desc()).limit(20)
    )).scalars().all()

    recent_jobs = []
    for job in recent_rows:
        parse_s = None
        if job.started_at and job.completed_at:
            parse_s = round((job.completed_at - job.started_at).total_seconds(), 1)
        recent_jobs.append({
            "job_id":          str(job.id),
            "status":          job.status.value,
            "created_at":      job.created_at.isoformat() if job.created_at else None,
            "parse_time_s":    parse_s,
            "error_code":      job.error_code,
            "file_size_bytes": job.file_size_bytes,
        })

    return {
        "summary": {
            "total":           total,
            "succeeded":       succeeded,
            "failed":          failed,
            "pending":         counts.get("pending", 0),
            "running":         counts.get("running", 0),
            "duplicate":       counts.get("duplicate", 0),
            "success_rate":    round(succeeded / total * 100, 1) if total else 0.0,
            "duplicate_rate":  round(counts.get("duplicate", 0) / total * 100, 1) if total else 0.0,
            "avg_parse_time_s": round(avg_parse_s, 1) if avg_parse_s else None,
            "avg_confidence":  round(avg_conf, 3) if avg_conf else None,
            "avg_cost_usd":    round(avg_cost, 6) if avg_cost else None,
            "ocr_count":       ocr_count,
            "ocr_rate":        round(ocr_count / succeeded * 100, 1) if succeeded else 0.0,
        },
        "source_breakdown":  source_breakdown,
        "failure_reasons":   failure_reasons,
        "daily_throughput":  daily_throughput,
        "recent_jobs":       recent_jobs,
    }

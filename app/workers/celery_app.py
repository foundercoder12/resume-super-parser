from celery import Celery
from app.config import settings

celery_app = Celery(
    "resume_parser",
    broker=settings.redis_url,
    backend=settings.celery_result_backend,
    include=["app.workers.tasks"],
)

celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    task_acks_late=True,          # ack only after task completes (safe re-queue on crash)
    worker_prefetch_multiplier=1, # one task at a time per worker slot (fair for long tasks)
    task_soft_time_limit=120,     # 2 min soft limit → SoftTimeLimitExceeded raised
    task_time_limit=180,          # 3 min hard limit → SIGKILL
    result_expires=86400,         # 24h result retention in Redis
)

import uuid
import enum
from datetime import datetime, timezone

from sqlalchemy import Column, String, Integer, DateTime, Enum as SAEnum, ForeignKey, Text
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import relationship

from app.db.models.base import Base


class JobStatus(str, enum.Enum):
    PENDING   = "pending"
    RUNNING   = "running"
    SUCCEEDED = "succeeded"
    FAILED    = "failed"
    DUPLICATE = "duplicate"  # dedupe hit; points to original job


class Job(Base):
    __tablename__ = "jobs"

    id                = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    status            = Column(SAEnum(JobStatus), nullable=False, default=JobStatus.PENDING, index=True)
    file_hash         = Column(String(64), nullable=False, index=True)
    file_path         = Column(String(512), nullable=False)
    original_filename = Column(String(256), nullable=True)
    file_size_bytes   = Column(Integer, nullable=False)

    celery_task_id    = Column(String(128), nullable=True)

    # Self-referential FK for dedupe hits
    duplicate_of_id   = Column(UUID(as_uuid=True), ForeignKey("jobs.id"), nullable=True)

    created_at        = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    started_at        = Column(DateTime(timezone=True), nullable=True)
    completed_at      = Column(DateTime(timezone=True), nullable=True)

    error_code        = Column(String(64), nullable=True)
    error_message     = Column(Text, nullable=True)

    # Pipeline routing decisions, warnings (no PII)
    pipeline_trace    = Column(JSONB, nullable=True)

    retain_until      = Column(DateTime(timezone=True), nullable=True)

    document          = relationship("Document", back_populates="job", uselist=False, lazy="select")
    duplicate_of      = relationship("Job", remote_side="Job.id", foreign_keys=[duplicate_of_id])

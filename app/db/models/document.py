import uuid
from datetime import datetime, timezone

from sqlalchemy import Column, String, Integer, DateTime, ForeignKey
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import relationship

from app.db.models.base import Base


class Document(Base):
    __tablename__ = "documents"

    id               = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    job_id           = Column(UUID(as_uuid=True), ForeignKey("jobs.id"), nullable=False, unique=True)
    page_count       = Column(Integer, nullable=False)
    source_type      = Column(String(16), nullable=False)   # digital | scanned | hybrid
    created_at       = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    # Full canonical output stored as JSONB
    canonical_result = Column(JSONB, nullable=True)

    job = relationship("Job", back_populates="document")

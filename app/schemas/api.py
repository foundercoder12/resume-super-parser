from __future__ import annotations
import uuid
from typing import Any, Optional
from pydantic import BaseModel, Field


class ParseOptions(BaseModel):
    retain_days: int = Field(30, ge=1, le=365)
    force_ocr:   bool = False


class ParseJobResponse(BaseModel):
    job_id:     uuid.UUID
    status:     str
    message:    str
    duplicate:  bool = False
    poll_url:   str


class JobStatusResponse(BaseModel):
    job_id:        uuid.UUID
    status:        str
    created_at:    str
    started_at:    Optional[str] = None
    completed_at:  Optional[str] = None
    error_code:    Optional[str] = None
    error_message: Optional[str] = None


class JobResultResponse(BaseModel):
    job_id:  uuid.UUID
    status:  str
    result:  Optional[Any] = None   # CanonicalResume dict when succeeded

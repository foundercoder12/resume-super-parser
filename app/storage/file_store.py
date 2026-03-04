"""
File storage abstraction.

Supports:
  - local: writes to STORAGE_LOCAL_PATH on disk
  - s3:    (future) boto3-backed S3 storage

The interface is the same regardless of backend.
"""
from __future__ import annotations
import os
import uuid
import structlog
from pathlib import Path

from app.config import settings
from app.core.exceptions import StorageError

log = structlog.get_logger(__name__)


class LocalFileStore:
    def __init__(self, base_path: str):
        self.base = Path(base_path)
        self.base.mkdir(parents=True, exist_ok=True)

    def save(self, data: bytes, filename: str | None = None) -> str:
        """Save bytes to disk. Returns the relative path (used as file_path in DB)."""
        if not filename:
            filename = f"{uuid.uuid4()}.pdf"
        dest = self.base / filename
        try:
            dest.write_bytes(data)
        except OSError as e:
            raise StorageError(f"Failed to save file: {e}")
        log.info("file_saved", path=str(dest), size=len(data))
        return str(dest)

    def load(self, path: str) -> bytes:
        """Load bytes from disk."""
        try:
            return Path(path).read_bytes()
        except OSError as e:
            raise StorageError(f"Failed to load file {path}: {e}")

    def delete(self, path: str) -> None:
        try:
            os.remove(path)
        except OSError:
            pass


def get_file_store() -> LocalFileStore:
    if settings.storage_backend == "local":
        return LocalFileStore(settings.storage_local_path)
    raise NotImplementedError(f"Storage backend '{settings.storage_backend}' not yet implemented")


# Singleton
_store: LocalFileStore | None = None


def file_store() -> LocalFileStore:
    global _store
    if _store is None:
        _store = get_file_store()
    return _store

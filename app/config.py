from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # Database
    database_url: str = "postgresql+asyncpg://resume:resume@localhost:5432/resume_parser"

    # Redis / Celery
    redis_url: str = "redis://localhost:6379/0"
    celery_result_backend: str = "redis://localhost:6379/1"

    # Storage
    storage_backend: str = "local"
    storage_local_path: str = "/tmp/resume-uploads"
    storage_s3_bucket: str = ""
    aws_access_key_id: str = ""
    aws_secret_access_key: str = ""
    aws_region: str = "us-east-1"

    # External APIs
    mistral_api_key: str = ""
    gemini_api_key: str = ""

    # Pipeline tuning
    ocr_quality_threshold: float = Field(0.6, ge=0.0, le=1.0)
    max_file_size_mb: int = Field(20, ge=1)
    default_retain_days: int = Field(30, ge=1, le=365)

    # App
    app_env: str = "development"
    log_level: str = "INFO"

    @property
    def max_file_size_bytes(self) -> int:
        return self.max_file_size_mb * 1024 * 1024


settings = Settings()

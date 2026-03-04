"""initial schema

Revision ID: 0001
Revises:
Create Date: 2024-01-01 00:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from alembic import op

revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS \"uuid-ossp\"")

    op.execute("""
        CREATE TYPE jobstatus AS ENUM (
            'pending', 'running', 'succeeded', 'failed', 'duplicate'
        )
    """)

    op.create_table(
        "jobs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("uuid_generate_v4()")),
        sa.Column("status", sa.Enum("pending", "running", "succeeded", "failed", "duplicate",
                                    name="jobstatus"), nullable=False, server_default="pending"),
        sa.Column("file_hash", sa.String(64), nullable=False),
        sa.Column("file_path", sa.String(512), nullable=False),
        sa.Column("original_filename", sa.String(256), nullable=True),
        sa.Column("file_size_bytes", sa.Integer(), nullable=False),
        sa.Column("celery_task_id", sa.String(128), nullable=True),
        sa.Column("duplicate_of_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("jobs.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_code", sa.String(64), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("pipeline_trace", postgresql.JSONB(), nullable=True),
        sa.Column("retain_until", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_jobs_status", "jobs", ["status"])
    op.create_index("ix_jobs_file_hash", "jobs", ["file_hash"])

    op.create_table(
        "documents",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("uuid_generate_v4()")),
        sa.Column("job_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("jobs.id"), nullable=False, unique=True),
        sa.Column("page_count", sa.Integer(), nullable=False),
        sa.Column("source_type", sa.String(16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.Column("canonical_result", postgresql.JSONB(), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("documents")
    op.drop_table("jobs")
    op.execute("DROP TYPE IF EXISTS jobstatus")

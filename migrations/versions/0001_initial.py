"""Create account, job, and media tables.

Revision ID: 0001_initial
Revises:
Create Date: 2026-09-05
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0001_initial"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "accounts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "platform",
            sa.Enum("tiktok", name="account_platform", native_enum=False),
            nullable=False,
        ),
        sa.Column("platform_user_id", sa.String(length=128), nullable=True),
        sa.Column("handle", sa.String(length=128), nullable=True),
        sa.Column("session_file", sa.String(length=1024), nullable=False),
        sa.Column(
            "status",
            sa.Enum("active", "expired", name="account_status", native_enum=False),
            server_default="active",
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("session_file"),
        sa.UniqueConstraint("platform", "platform_user_id", name="uq_accounts_platform_user"),
    )
    op.create_index("ix_accounts_platform_status", "accounts", ["platform", "status"])

    op.create_table(
        "jobs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("source_url", sa.String(length=2048), nullable=False),
        sa.Column("canonical_url", sa.String(length=2048), nullable=False),
        sa.Column(
            "source_platform",
            sa.Enum("x", name="source_platform", native_enum=False),
            nullable=False,
        ),
        sa.Column(
            "destination_platform",
            sa.Enum("tiktok", name="destination_platform", native_enum=False),
            nullable=False,
        ),
        sa.Column("destination_account_id", sa.Uuid(), nullable=False),
        sa.Column("caption_override", sa.String(length=2200), nullable=True),
        sa.Column(
            "state",
            sa.Enum(
                "pending",
                "downloading",
                "downloaded",
                "uploading",
                "posted",
                "failed",
                "cancelled",
                name="job_state",
                native_enum=False,
            ),
            server_default="pending",
            nullable=False,
        ),
        sa.Column("attempt_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("worker_id", sa.String(length=128), nullable=True),
        sa.Column("claimed_at", sa.DateTime(), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(), nullable=True),
        sa.Column("cancel_requested_at", sa.DateTime(), nullable=True),
        sa.Column("error_code", sa.String(length=128), nullable=True),
        sa.Column("error_message", sa.String(length=1000), nullable=True),
        sa.Column("posted_url", sa.String(length=2048), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
        sa.CheckConstraint("attempt_count >= 0", name="ck_jobs_attempt_count"),
        sa.ForeignKeyConstraint(["destination_account_id"], ["accounts.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "destination_account_id", "canonical_url", name="uq_jobs_destination_url"
        ),
    )
    op.create_index("ix_jobs_account", "jobs", ["destination_account_id"])
    op.create_index("ix_jobs_queue", "jobs", ["state", "created_at"])

    op.create_table(
        "media",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("job_id", sa.Uuid(), nullable=False),
        sa.Column("path", sa.String(length=2048), nullable=False),
        sa.Column("mime_type", sa.String(length=128), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("checksum_sha256", sa.String(length=64), nullable=False),
        sa.Column("duration_seconds", sa.Float(), nullable=True),
        sa.Column("width", sa.Integer(), nullable=True),
        sa.Column("height", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint("size_bytes >= 0", name="ck_media_size"),
        sa.ForeignKeyConstraint(["job_id"], ["jobs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("job_id"),
    )


def downgrade() -> None:
    op.drop_table("media")
    op.drop_index("ix_jobs_queue", table_name="jobs")
    op.drop_index("ix_jobs_account", table_name="jobs")
    op.drop_table("jobs")
    op.drop_index("ix_accounts_platform_status", table_name="accounts")
    op.drop_table("accounts")

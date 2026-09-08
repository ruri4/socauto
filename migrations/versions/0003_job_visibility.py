"""Persist per-job TikTok visibility, defaulting existing jobs to private.

Revision ID: 0003_job_visibility
Revises: 0002_worker_results
Create Date: 2026-09-08
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003_job_visibility"
down_revision: str | None = "0002_worker_results"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    visibility_type = sa.Enum(
        "private",
        "public",
        name="job_visibility",
        native_enum=False,
    )
    op.add_column("jobs", sa.Column("visibility", visibility_type, nullable=True))
    op.execute(sa.text("UPDATE jobs SET visibility = 'private' WHERE visibility IS NULL"))
    with op.batch_alter_table("jobs") as batch:
        batch.alter_column(
            "visibility",
            existing_type=visibility_type,
            nullable=False,
            server_default="private",
        )


def downgrade() -> None:
    op.drop_column("jobs", "visibility")

"""Add reusable caption templates and immutable job template snapshots.

Revision ID: 0004_caption_templates
Revises: 0003_job_visibility
Create Date: 2026-09-08
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004_caption_templates"
down_revision: str | None = "0003_job_visibility"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "caption_templates",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=80, collation="NOCASE"), nullable=False),
        sa.Column("body", sa.String(length=2200), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name"),
    )
    mode_type = sa.Enum(
        "source",
        "override",
        "saved_template",
        "custom_template",
        name="job_caption_mode",
        native_enum=False,
    )
    op.add_column("jobs", sa.Column("caption_mode", mode_type, nullable=True))
    op.add_column(
        "jobs",
        sa.Column(
            "caption_template_id",
            sa.Uuid(),
        ),
    )
    op.add_column("jobs", sa.Column("caption_template_name_snapshot", sa.String(length=80)))
    op.add_column("jobs", sa.Column("caption_template_body_snapshot", sa.String(length=2200)))
    op.execute(
        sa.text(
            "UPDATE jobs SET caption_mode = CASE "
            "WHEN caption_override IS NULL THEN 'source' ELSE 'override' END"
        )
    )
    with op.batch_alter_table("jobs") as batch:
        batch.create_foreign_key(
            "fk_jobs_caption_template_id_caption_templates",
            "caption_templates",
            ["caption_template_id"],
            ["id"],
            ondelete="SET NULL",
        )
        batch.alter_column(
            "caption_mode", existing_type=mode_type, nullable=False, server_default="source"
        )


def downgrade() -> None:
    with op.batch_alter_table("jobs") as batch:
        batch.drop_constraint("fk_jobs_caption_template_id_caption_templates", type_="foreignkey")
        batch.drop_column("caption_template_body_snapshot")
        batch.drop_column("caption_template_name_snapshot")
        batch.drop_column("caption_template_id")
        batch.drop_column("caption_mode")
    op.drop_table("caption_templates")

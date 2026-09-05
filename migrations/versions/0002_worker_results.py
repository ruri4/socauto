"""Persist resolved captions and acknowledged publication identifiers."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002_worker_results"
down_revision: str | None = "0001_initial"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("jobs", sa.Column("resolved_caption", sa.String(), nullable=True))
    for name in ("creation_id", "video_id", "post_id"):
        op.add_column("jobs", sa.Column(name, sa.String(length=128), nullable=True))


def downgrade() -> None:
    for name in ("post_id", "video_id", "creation_id", "resolved_caption"):
        op.drop_column("jobs", name)

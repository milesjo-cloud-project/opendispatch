"""owners can disable a user's account

Revision ID: 0008_user_disable
Revises: 0007_tracking_and_attachments
Create Date: 2026-10-02

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0008_user_disable"
down_revision: Union[str, None] = "0007_tracking_and_attachments"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # NULL = can sign in. Everyone who exists today keeps their access.
    op.add_column("users", sa.Column("disabled_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("users", "disabled_at")

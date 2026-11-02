"""steering_docs table

Adds `steering_docs` — user-editable overrides for the meal-planning prompt and
per-member profiles, so the Steering tab's edits persist across deploys (the
baked files are read-only in the container). Additive; no existing table
touched. A missing row means "use the baked file default".

Revision ID: f6a7b8c9d0e1
Revises: e5f6a7b8c9d0
Create Date: 2026-11-02
"""
from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = "f6a7b8c9d0e1"
down_revision: Union[str, None] = "e5f6a7b8c9d0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "steering_docs",
        sa.Column("key", sa.String(length=80), primary_key=True),
        sa.Column("content", sa.Text(), nullable=False, server_default=""),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("steering_docs")

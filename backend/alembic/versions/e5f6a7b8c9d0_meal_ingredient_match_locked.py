"""meal_ingredient match_locked

Adds a boolean `match_locked` to meal_ingredients. When true, a human manually
set or cleared that line's inventory match via the ingredient-edit actions, and
recompute_reservations must respect that decision instead of re-deriving the
match. Additive and backfilled to false — safe on live data.

Revision ID: e5f6a7b8c9d0
Revises: d4e5f6a7b8c9
Create Date: 2026-11-02
"""
from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = "e5f6a7b8c9d0"
down_revision: Union[str, None] = "d4e5f6a7b8c9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # server_default false so existing rows backfill; keep the column non-null.
    op.add_column(
        "meal_ingredients",
        sa.Column("match_locked", sa.Boolean(), nullable=False,
                  server_default=sa.false()),
    )
    # Drop the server_default now the backfill is done, so the app's default
    # (False) is the single source of truth going forward.
    with op.batch_alter_table("meal_ingredients") as batch:
        batch.alter_column("match_locked", server_default=None)


def downgrade() -> None:
    op.drop_column("meal_ingredients", "match_locked")

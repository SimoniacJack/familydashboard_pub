"""inventory count/level tracking + meal reservation ledger

Revision ID: c3d4e5f6a7b8
Revises: b2c3d4e5f6a7
Create Date: 2026-11-01 16:18:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c3d4e5f6a7b8'
down_revision: Union[str, None] = 'b2c3d4e5f6a7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Additive columns with safe server defaults (safe over prod rows).
    op.add_column(
        'inventory_items',
        sa.Column('track_mode', sa.String(length=10), nullable=False, server_default='count'),
    )
    op.add_column(
        'inventory_items',
        sa.Column('count', sa.Integer(), nullable=False, server_default='1'),
    )
    op.add_column(
        'inventory_items',
        sa.Column('planned', sa.Integer(), nullable=False, server_default='0'),
    )

    # 2. Backfill track_mode from the previous `tracked` flag:
    #    - items that were level-tracked (tracked=true)  -> track_mode='level'
    #    - everything else (the old plain in/out items)   -> track_mode='count', count=1
    # Existing rows already got count=1 and planned=0 from the server defaults.
    op.execute(
        "UPDATE inventory_items SET track_mode = 'level' WHERE tracked = true"
    )
    op.execute(
        "UPDATE inventory_items SET track_mode = 'count', count = 1 WHERE tracked = false"
    )

    # 3. Reservation ledger.
    op.create_table(
        'meal_reservations',
        sa.Column('meal_key', sa.String(length=80), nullable=False),
        sa.Column('item_id', sa.String(length=60), nullable=False),
        sa.Column('qty', sa.Integer(), nullable=False, server_default='1'),
        sa.PrimaryKeyConstraint('meal_key', 'item_id'),
    )


def downgrade() -> None:
    op.drop_table('meal_reservations')
    op.drop_column('inventory_items', 'planned')
    op.drop_column('inventory_items', 'count')
    op.drop_column('inventory_items', 'track_mode')

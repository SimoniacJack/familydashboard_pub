"""inventory quantity levels: tracked + level + restock

Revision ID: b2c3d4e5f6a7
Revises: a1f2b3c4d5e6
Create Date: 2026-11-01 14:46:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b2c3d4e5f6a7'
down_revision: Union[str, None] = 'a1f2b3c4d5e6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Additive columns with server defaults — existing rows get sensible values
    # (untracked, full, no restock text), so this is safe over prod data.
    op.add_column(
        'inventory_items',
        sa.Column('tracked', sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column(
        'inventory_items',
        sa.Column('level', sa.String(length=10), nullable=False, server_default='full'),
    )
    op.add_column(
        'inventory_items',
        sa.Column('restock', sa.String(length=200), nullable=False, server_default=''),
    )


def downgrade() -> None:
    op.drop_column('inventory_items', 'restock')
    op.drop_column('inventory_items', 'level')
    op.drop_column('inventory_items', 'tracked')

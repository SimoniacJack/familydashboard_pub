"""shopping-to-inventory: filed items + sync cursor

Revision ID: a1f2b3c4d5e6
Revises: c28f9cc1951c
Create Date: 2026-11-01 13:20:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a1f2b3c4d5e6'
down_revision: Union[str, None] = 'c28f9cc1951c'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # New tables only — no changes to existing rows, safe over prod data.
    op.create_table(
        'filed_shopping_items',
        sa.Column('todoist_id', sa.String(length=60), nullable=False),
        sa.Column('name', sa.String(length=200), nullable=False, server_default=''),
        sa.Column('filed', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column('location', sa.String(length=40), nullable=True),
        sa.PrimaryKeyConstraint('todoist_id'),
    )
    op.create_table(
        'sync_state',
        sa.Column('key', sa.String(length=60), nullable=False),
        sa.Column('value', sa.String(length=300), nullable=False, server_default=''),
        sa.PrimaryKeyConstraint('key'),
    )


def downgrade() -> None:
    op.drop_table('sync_state')
    op.drop_table('filed_shopping_items')

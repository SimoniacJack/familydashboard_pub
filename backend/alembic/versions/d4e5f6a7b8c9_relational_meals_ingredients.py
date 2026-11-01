"""relational meals: promote meal fields, extract ingredients to rows, fold reservations

Revision ID: d4e5f6a7b8c9
Revises: c3d4e5f6a7b8
Create Date: 2026-11-01 21:06:00.000000

Promotes name/description/prep_minutes out of the `meal` JSON blob into real
columns on meal_slots + lunch_ideas, extracts each meal's `ingredients[]` array
into a new relational `meal_ingredients` table (one row per ingredient, with an
optional FK to the matched inventory item and a reserved_qty), and folds the old
`meal_reservations` ledger into those ingredient rows. The `meal` JSON column is
KEPT (transitional) so this is reversible and nothing is lost.
"""
from typing import Sequence, Union
import json
import uuid

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd4e5f6a7b8c9'
down_revision: Union[str, None] = 'c3d4e5f6a7b8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _ingredients_from_meal(meal_json):
    """Pull the ingredients list out of a stored `meal` JSON value, tolerating
    None, a JSON string, or an already-decoded dict."""
    if meal_json is None:
        return []
    meal = meal_json
    if isinstance(meal, str):
        try:
            meal = json.loads(meal)
        except (ValueError, TypeError):
            return []
    if not isinstance(meal, dict):
        return []
    ings = meal.get("ingredients") or []
    return ings if isinstance(ings, list) else []


def upgrade() -> None:
    conn = op.get_bind()

    # 1. Promote scalar meal fields to columns (nullable — backfilled next).
    for table in ("meal_slots", "lunch_ideas"):
        op.add_column(table, sa.Column('name', sa.String(length=200), nullable=True))
        op.add_column(table, sa.Column('description', sa.Text(), nullable=True))
        op.add_column(table, sa.Column('prep_minutes', sa.Integer(), nullable=True))

    # 2. Create the meal_ingredients table.
    op.create_table(
        'meal_ingredients',
        sa.Column('id', sa.String(length=60), nullable=False),
        sa.Column('slot_id', sa.String(length=60), nullable=True),
        sa.Column('lunch_id', sa.String(length=60), nullable=True),
        sa.Column('item', sa.String(length=200), nullable=False),
        sa.Column('quantity', sa.String(length=100), nullable=False, server_default=''),
        sa.Column('position', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('inventory_item_id', sa.String(length=60), nullable=True),
        sa.Column('reserved_qty', sa.Integer(), nullable=False, server_default='0'),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['slot_id'], ['meal_slots.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['lunch_id'], ['lunch_ideas.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['inventory_item_id'], ['inventory_items.id'], ondelete='SET NULL'),
        sa.CheckConstraint(
            '(slot_id IS NOT NULL) <> (lunch_id IS NOT NULL)',
            name='meal_ingredient_exactly_one_owner',
        ),
    )
    op.create_index('ix_meal_ingredients_slot_id', 'meal_ingredients', ['slot_id'])
    op.create_index('ix_meal_ingredients_lunch_id', 'meal_ingredients', ['lunch_id'])
    op.create_index('ix_meal_ingredients_inventory_item_id', 'meal_ingredients', ['inventory_item_id'])

    # 3. Backfill name/description/prep_minutes + ingredient rows from the JSON.
    ingredient_rows = []  # collected, inserted in one executemany

    def backfill(table, owner_col):
        rows = conn.execute(sa.text(f"SELECT id, meal FROM {table}")).fetchall()
        for row in rows:
            owner_id, meal = row[0], row[1]
            meal_dict = meal
            if isinstance(meal_dict, str):
                try:
                    meal_dict = json.loads(meal_dict)
                except (ValueError, TypeError):
                    meal_dict = None
            if isinstance(meal_dict, dict):
                conn.execute(
                    sa.text(
                        f"UPDATE {table} SET name = :n, description = :d, "
                        f"prep_minutes = :p WHERE id = :id"
                    ),
                    {
                        "n": meal_dict.get("name"),
                        "d": meal_dict.get("description"),
                        "p": meal_dict.get("prep_minutes"),
                        "id": owner_id,
                    },
                )
            for pos, ing in enumerate(_ingredients_from_meal(meal)):
                if not isinstance(ing, dict):
                    continue
                item = (ing.get("item") or "").strip()
                if not item:
                    continue
                ingredient_rows.append({
                    "id": str(uuid.uuid4()),
                    "slot_id": owner_id if owner_col == "slot_id" else None,
                    "lunch_id": owner_id if owner_col == "lunch_id" else None,
                    "item": item,
                    "quantity": (ing.get("quantity") or "").strip(),
                    "position": pos,
                })

    backfill("meal_slots", "slot_id")
    backfill("lunch_ideas", "lunch_id")

    if ingredient_rows:
        conn.execute(
            sa.text(
                "INSERT INTO meal_ingredients "
                "(id, slot_id, lunch_id, item, quantity, position, reserved_qty) "
                "VALUES (:id, :slot_id, :lunch_id, :item, :quantity, :position, 0)"
            ),
            ingredient_rows,
        )

    # 4. Fold existing meal_reservations into the ingredient rows. A reservation
    #    (meal_key, item_id, qty) maps onto the ingredient line(s) of that meal
    #    whose inventory match is item_id. We can't know which ingredient text
    #    matched, so we set inventory_item_id + reserved_qty on the FIRST
    #    unreserved ingredient line of that meal, matching the old qty. This is
    #    best-effort over transient reservation state; the next shopping-list
    #    push recomputes everything exactly anyway.
    insp = sa.inspect(conn)
    if 'meal_reservations' in insp.get_table_names():
        resvs = conn.execute(
            sa.text("SELECT meal_key, item_id, qty FROM meal_reservations")
        ).fetchall()
        for meal_key, item_id, qty in resvs:
            conn.execute(
                sa.text(
                    "UPDATE meal_ingredients SET inventory_item_id = :iid, "
                    "reserved_qty = :qty WHERE id = ("
                    "  SELECT id FROM meal_ingredients "
                    "  WHERE (slot_id = :mk OR lunch_id = :mk) "
                    "    AND inventory_item_id IS NULL "
                    "  ORDER BY position LIMIT 1)"
                ),
                {"iid": item_id, "qty": qty, "mk": meal_key},
            )
        op.drop_table('meal_reservations')


def downgrade() -> None:
    # Recreate the reservation ledger and repopulate from ingredient rows.
    op.create_table(
        'meal_reservations',
        sa.Column('meal_key', sa.String(length=80), nullable=False),
        sa.Column('item_id', sa.String(length=60), nullable=False),
        sa.Column('qty', sa.Integer(), nullable=False, server_default='1'),
        sa.PrimaryKeyConstraint('meal_key', 'item_id'),
    )
    conn = op.get_bind()
    # Rebuild reservations by summing reserved_qty per (meal, item).
    conn.execute(sa.text(
        "INSERT INTO meal_reservations (meal_key, item_id, qty) "
        "SELECT COALESCE(slot_id, lunch_id) AS meal_key, inventory_item_id, "
        "       SUM(reserved_qty) AS qty "
        "FROM meal_ingredients "
        "WHERE inventory_item_id IS NOT NULL AND reserved_qty > 0 "
        "GROUP BY COALESCE(slot_id, lunch_id), inventory_item_id"
    ))

    op.drop_index('ix_meal_ingredients_inventory_item_id', table_name='meal_ingredients')
    op.drop_index('ix_meal_ingredients_lunch_id', table_name='meal_ingredients')
    op.drop_index('ix_meal_ingredients_slot_id', table_name='meal_ingredients')
    op.drop_table('meal_ingredients')
    for table in ("meal_slots", "lunch_ideas"):
        op.drop_column(table, 'prep_minutes')
        op.drop_column(table, 'description')
        op.drop_column(table, 'name')

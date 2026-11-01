"""SQLAlchemy ORM models — mirrors the agreed ERD.

Temporal model:
  - WEEK is identified by its Monday (week_start, a date string).
  - DATE belongs to a week; we store `date` on day-scoped rows and derive the
    week from it rather than materialising empty WEEK/DATE rows.
  - CHORE / REMINDER are templates that materialise into *_INSTANCE rows.
"""
from datetime import datetime, date as date_cls
from sqlalchemy import (
    String, Integer, Text, DateTime, Date, ForeignKey, JSON, Boolean,
    CheckConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from db import Base


class Member(Base):
    __tablename__ = "members"

    id: Mapped[str] = mapped_column(String(50), primary_key=True)  # 'ada'
    name: Mapped[str] = mapped_column(String(100))
    role: Mapped[str] = mapped_column(String(20))  # adult | child
    color: Mapped[str] = mapped_column(String(30), default="")
    # Local path for now; becomes an S3 URL after AWS migration.
    markdown_url: Mapped[str] = mapped_column(String(500), default="")
    image_url: Mapped[str] = mapped_column(String(500), default="")


class Room(Base):
    __tablename__ = "rooms"

    id: Mapped[str] = mapped_column(String(50), primary_key=True)  # 'kitchen'
    name: Mapped[str] = mapped_column(String(100))
    floor: Mapped[str] = mapped_column(String(20))  # upstairs | downstairs
    sort_order: Mapped[int] = mapped_column(Integer, default=0)


class Chore(Base):
    __tablename__ = "chores"

    id: Mapped[str] = mapped_column(String(50), primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, default="")
    points: Mapped[int] = mapped_column(Integer, default=0)
    # A chore instance is scoped to a DAY, WEEK or MONTH (or a one-off job).
    frequency: Mapped[str] = mapped_column(String(20))  # daily | weekly | monthly | once
    assignable: Mapped[str] = mapped_column(String(20), default="all")  # all|children|adults
    assigned_to: Mapped[str | None] = mapped_column(ForeignKey("members.id"), nullable=True)
    room_id: Mapped[str | None] = mapped_column(ForeignKey("rooms.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    instances: Mapped[list["ChoreInstance"]] = relationship(
        back_populates="chore", cascade="all, delete-orphan"
    )


class ChoreInstance(Base):
    __tablename__ = "chore_instances"

    id: Mapped[str] = mapped_column(String(60), primary_key=True)
    chore_id: Mapped[str] = mapped_column(ForeignKey("chores.id", ondelete="CASCADE"))
    # A chore instance relates to a DAY, WEEK or MONTH. `period_type` says which,
    # and `period_key` is the canonical identifier for that period:
    #   day   -> 'YYYY-MM-DD'      (the date)
    #   week  -> 'YYYY-MM-DD'      (the Monday)
    #   month -> 'YYYY-MM'        (year-month)
    #   once  -> 'once'            (persists until done)
    period_type: Mapped[str] = mapped_column(String(10), default="week")
    period_key: Mapped[str] = mapped_column(String(20), index=True)
    status: Mapped[str] = mapped_column(String(20), default="pending")  # pending | done
    completed_by: Mapped[str | None] = mapped_column(ForeignKey("members.id"), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    points: Mapped[int] = mapped_column(Integer, default=0)  # snapshot at completion

    chore: Mapped["Chore"] = relationship(back_populates="instances")


class Reminder(Base):
    __tablename__ = "reminders"

    id: Mapped[str] = mapped_column(String(60), primary_key=True)
    member: Mapped[str | None] = mapped_column(ForeignKey("members.id"), nullable=True)  # null = family
    label: Mapped[str] = mapped_column(String(200))
    routine: Mapped[str] = mapped_column(String(20), default="anytime")  # morning | evening | anytime
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    instances: Mapped[list["ReminderInstance"]] = relationship(
        back_populates="reminder", cascade="all, delete-orphan"
    )


class ReminderInstance(Base):
    __tablename__ = "reminder_instances"

    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    reminder_id: Mapped[str] = mapped_column(ForeignKey("reminders.id", ondelete="CASCADE"))
    date: Mapped[date_cls] = mapped_column(Date, index=True)
    status: Mapped[str] = mapped_column(String(20), default="pending")  # pending | done
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    reminder: Mapped["Reminder"] = relationship(back_populates="instances")


class MealSlot(Base):
    __tablename__ = "meal_slots"

    id: Mapped[str] = mapped_column(String(60), primary_key=True)
    date: Mapped[date_cls] = mapped_column(Date, index=True)
    meal_type: Mapped[str] = mapped_column(String(20), default="dinner")
    status: Mapped[str] = mapped_column(String(20), default="pending")
    # Promoted scalar meal fields (were inside the `meal` JSON blob).
    name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    prep_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Transitional: the old JSON blob. Kept so a rollback can still read it and
    # so any not-yet-promoted field survives; serialization builds from the
    # columns + ingredient rows, not from here. Dropped in a later migration.
    meal: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    # Transient document data — never queried, correctly left as JSON.
    rejection_reasons: Mapped[list] = mapped_column(JSON, default=list)

    ingredients: Mapped[list["MealIngredient"]] = relationship(
        back_populates="slot", cascade="all, delete-orphan",
        order_by="MealIngredient.position",
    )


class LunchIdea(Base):
    __tablename__ = "lunch_ideas"

    id: Mapped[str] = mapped_column(String(60), primary_key=True)
    # Lunch ideas float within a week; not pinned to a date. Picked whenever.
    week_start: Mapped[date_cls] = mapped_column(Date, index=True)
    status: Mapped[str] = mapped_column(String(20), default="generated")
    name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    prep_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    meal: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    rejection_reasons: Mapped[list] = mapped_column(JSON, default=list)

    ingredients: Mapped[list["MealIngredient"]] = relationship(
        back_populates="lunch", cascade="all, delete-orphan",
        order_by="MealIngredient.position",
    )


class InventoryItem(Base):
    __tablename__ = "inventory_items"

    id: Mapped[str] = mapped_column(String(60), primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    location: Mapped[str] = mapped_column(String(40))
    note: Mapped[str] = mapped_column(String(300), default="")
    # Quantity tracking for staples you use up gradually (milk, pasta, flour).
    # Untracked items (default) behave as a plain in/out stock list.
    tracked: Mapped[bool] = mapped_column(Boolean, default=False)
    # One of: full | ok | low | out. Only meaningful when tracked=True.
    # low/out means "running out" -> auto-added to the shopping list.
    level: Mapped[str] = mapped_column(String(10), default="full")
    # Shopping-list text to use when restocking, e.g. "2L milk", "500g pasta".
    # Falls back to the item name when blank.
    restock: Mapped[str] = mapped_column(String(200), default="")
    # How this item's amount is expressed:
    #   "count" -> discrete units (cans, boxes): `count` holds how many.
    #   "level" -> indiscrete amount (rice, pasta): `level` (full/ok/low/out).
    track_mode: Mapped[str] = mapped_column(String(10), default="count")
    # Units physically on hand (count mode). Drops when a meal is cooked.
    count: Mapped[int] = mapped_column(Integer, default=1)
    # Units reserved by accepted meals on the calendar (count mode).
    # available = count - planned. Recomputed on every shopping-list push.
    planned: Mapped[int] = mapped_column(Integer, default=0)


class EventAssignment(Base):
    __tablename__ = "event_assignments"

    event_id: Mapped[str] = mapped_column(String(300), primary_key=True)
    # List of member ids (local override). JSON array keeps it simple.
    members: Mapped[list] = mapped_column(JSON, default=list)


class ShoppingItem(Base):
    """The master shopping list. Reconciled against scheduled-meal ingredients
    (minus inventory) on 'Update shopping list'. Manual items are preserved."""
    __tablename__ = "shopping_items"

    id: Mapped[str] = mapped_column(String(60), primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    norm: Mapped[str] = mapped_column(String(200), index=True)  # normalised name for matching
    quantity: Mapped[str] = mapped_column(String(100), default="")
    source: Mapped[str] = mapped_column(String(20), default="auto")  # auto | manual
    todoist_id: Mapped[str | None] = mapped_column(String(60), nullable=True)


class FiledShoppingItem(Base):
    """Record of a completed Todoist shopping task that has been handled, so the
    same completed task is never offered for filing (or filed) twice.
    `filed` is true once it was added to inventory; a dismissed item is recorded
    with filed=false so it stops reappearing in the 'just bought' list."""
    __tablename__ = "filed_shopping_items"

    todoist_id: Mapped[str] = mapped_column(String(60), primary_key=True)
    name: Mapped[str] = mapped_column(String(200), default="")
    filed: Mapped[bool] = mapped_column(default=True)
    location: Mapped[str | None] = mapped_column(String(40), nullable=True)


class SyncState(Base):
    """Tiny key/value store for integration cursors (e.g. the Todoist
    completed-tasks sync timestamp)."""
    __tablename__ = "sync_state"

    key: Mapped[str] = mapped_column(String(60), primary_key=True)
    value: Mapped[str] = mapped_column(String(300), default="")


class MealIngredient(Base):
    """One ingredient line of a meal — extracted from the old `meal.ingredients`
    JSON array into its own relational row.

    Ownership: a line belongs to EXACTLY ONE of a dinner slot or a floating
    lunch idea (the CHECK enforces it). Both FKs cascade, so deleting a meal
    deletes its ingredients — no orphans.

    This row also IS the reservation (the old MealReservation table is folded in
    here): `inventory_item_id` is the matched inventory line (nullable — a
    GPT/string suggestion the user can correct, persisted so it sticks), and
    `reserved_qty` is how many units this ingredient has reserved from that
    item. An item's `planned` is the SUM of reserved_qty across its ingredient
    rows, recomputed on every shopping-list push.
    """
    __tablename__ = "meal_ingredients"
    __table_args__ = (
        CheckConstraint(
            "(slot_id IS NOT NULL) <> (lunch_id IS NOT NULL)",
            name="meal_ingredient_exactly_one_owner",
        ),
    )

    id: Mapped[str] = mapped_column(String(60), primary_key=True)
    slot_id: Mapped[str | None] = mapped_column(
        ForeignKey("meal_slots.id", ondelete="CASCADE"), nullable=True, index=True)
    lunch_id: Mapped[str | None] = mapped_column(
        ForeignKey("lunch_ideas.id", ondelete="CASCADE"), nullable=True, index=True)
    item: Mapped[str] = mapped_column(String(200))
    quantity: Mapped[str] = mapped_column(String(100), default="")
    position: Mapped[int] = mapped_column(Integer, default=0)
    # Matched inventory line (nullable). SET NULL if the item is deleted, so the
    # ingredient line survives as unmatched rather than cascading the meal away.
    inventory_item_id: Mapped[str | None] = mapped_column(
        ForeignKey("inventory_items.id", ondelete="SET NULL"), nullable=True, index=True)
    # Units this ingredient has reserved from the matched count item (0 for
    # level items or unmatched lines). Folds in the old MealReservation.qty.
    reserved_qty: Mapped[int] = mapped_column(Integer, default=0)

    slot: Mapped["MealSlot | None"] = relationship(back_populates="ingredients")
    lunch: Mapped["LunchIdea | None"] = relationship(back_populates="ingredients")

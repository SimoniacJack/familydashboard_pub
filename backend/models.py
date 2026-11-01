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
    meal: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    rejection_reasons: Mapped[list] = mapped_column(JSON, default=list)


class LunchIdea(Base):
    __tablename__ = "lunch_ideas"

    id: Mapped[str] = mapped_column(String(60), primary_key=True)
    week_start: Mapped[date_cls] = mapped_column(Date, index=True)
    status: Mapped[str] = mapped_column(String(20), default="generated")
    meal: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    rejection_reasons: Mapped[list] = mapped_column(JSON, default=list)


class InventoryItem(Base):
    __tablename__ = "inventory_items"

    id: Mapped[str] = mapped_column(String(60), primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    location: Mapped[str] = mapped_column(String(40))
    note: Mapped[str] = mapped_column(String(300), default="")


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

"""One-off migration: load existing JSON data files into Postgres.

Run once after the Alembic schema is applied:
    ../.venv/bin/python import_json_to_db.py

Idempotent-ish: it clears each table before loading, so it can be re-run.
Members are sourced from the /familymembers/*.md profiles.
"""
import json
import os
import glob
import re
import uuid
from datetime import datetime

from db import session_scope, engine
from models import (
    Member, Chore, ChoreInstance, Reminder, ReminderInstance,
    MealSlot, LunchIdea, InventoryItem, EventAssignment, Room,
    ShoppingItem, Base,
)

ROOMS = [
    ("kitchen", "Kitchen", "downstairs", 1),
    ("hall", "Hall", "downstairs", 2),
    ("living_room", "Living room", "downstairs", 3),
    ("bathroom_down", "Bathroom", "downstairs", 4),
    ("office", "Office", "downstairs", 5),
    ("bedroom_1", "Bedroom 1", "upstairs", 6),
    ("bedroom_2", "Bedroom 2", "upstairs", 7),
    ("bedroom_3", "Bedroom 3", "upstairs", 8),
    ("main_bedroom", "Main bedroom", "upstairs", 9),
    ("bathroom_up", "Bathroom", "upstairs", 10),
]

HERE = os.path.dirname(os.path.abspath(__file__))
# Seed JSON. Ship your own under data/ ; an example set lives in data/example/.
DATA = os.path.join(HERE, "data", "_migrated_json")
if not os.path.isdir(DATA):
    DATA = os.path.join(HERE, "data", "example")
if not os.path.isdir(DATA):
    DATA = os.path.join(HERE, "data")
MEMBERS_DIR = os.path.join(HERE, "..", "familymembers")


def load_json(name):
    path = os.path.join(DATA, name)
    if not os.path.exists(path):
        return None
    with open(path) as f:
        return json.load(f)


def import_members(session):
    for fp in sorted(glob.glob(os.path.join(MEMBERS_DIR, "*.md"))):
        mid = os.path.splitext(os.path.basename(fp))[0].lower()
        with open(fp, encoding="utf-8") as f:
            content = f.read()
        role = "adult" if "**Role**: Adult" in content else "child"
        # Find an image file for this member (case-insensitive)
        image = ""
        for ext in ("png", "jpg", "jpeg", "webp"):
            for cand in (mid, mid.capitalize(), mid.upper()):
                if os.path.exists(os.path.join(MEMBERS_DIR, f"{cand}.{ext}")):
                    image = f"/api/members/{mid}/image"
                    break
        session.merge(Member(
            id=mid,
            name=mid.capitalize(),
            role=role,
            color="",  # set per-member in-app; frontend auto-assigns a fallback
            markdown_url=f"familymembers/{os.path.basename(fp)}",
            image_url=image,
        ))
    print("  members imported")


def import_rooms(session):
    for rid, name, floor, order in ROOMS:
        session.merge(Room(id=rid, name=name, floor=floor, sort_order=order))
    print(f"  {len(ROOMS)} rooms imported")


def import_chores(session):
    data = load_json("chores.json") or {}
    for c in data.get("chores", []):
        session.merge(Chore(
            id=c["id"],
            name=c["name"],
            description=c.get("description", ""),
            points=0,  # point scale reset (1pt = 10p); set real values in-app
            frequency=c.get("frequency", "weekly"),
            assignable=c.get("assignable", "all"),
            assigned_to=(c.get("assigned_to") or None),
            created_at=_parse_dt(c.get("created_at")),
            is_active=True,
        ))
    print(f"  {len(data.get('chores', []))} chores imported")


def import_reminders(session):
    data = load_json("reminders.json") or {}
    for r in data.get("reminders", []):
        label = r["label"]
        routines = r.get("routines") or ["morning"]
        # A reminder may recur in more than one routine (e.g. ["morning","evening"]).
        for i, routine in enumerate(routines):
            rid = r["id"] if i == 0 else f"{r['id']}-{routine}"
            session.merge(Reminder(id=rid, member=(r.get("member") or None),
                                   label=label, routine=routine, is_active=True))
    print(f"  {len(data.get('reminders', []))} reminders imported")


def import_inventory(session):
    data = load_json("inventory.json") or {}
    for it in data.get("items", []):
        session.merge(InventoryItem(
            id=it["id"],
            name=it["name"],
            location=it.get("location", "pantry"),
            note=it.get("note", ""),
        ))
    print(f"  {len(data.get('items', []))} inventory items imported")


def import_assignments(session):
    data = load_json("assignments.json") or {}
    overrides = data.get("overrides", {})
    for event_id, members in overrides.items():
        if isinstance(members, str):
            members = [members]
        session.merge(EventAssignment(event_id=event_id, members=members))
    print(f"  {len(overrides)} event assignments imported")


def import_meals(session):
    """Meals are week-specific and ephemeral; we skip migrating the current
    plan (it'll regenerate). Tables are created, just left empty."""
    print("  meals skipped (will regenerate)")


def _parse_dt(s):
    if not s:
        return datetime.utcnow()
    try:
        return datetime.fromisoformat(s)
    except ValueError:
        return datetime.utcnow()


def main():
    with session_scope() as session:
        # Clear in FK-safe order
        session.query(ChoreInstance).delete()
        session.query(ReminderInstance).delete()
        session.query(Chore).delete()
        session.query(Reminder).delete()
        session.query(InventoryItem).delete()
        session.query(EventAssignment).delete()
        session.query(MealSlot).delete()
        session.query(LunchIdea).delete()
        session.query(ShoppingItem).delete()
        session.query(Room).delete()
        session.query(Member).delete()
        session.flush()

        import_members(session)
        import_rooms(session)
        import_chores(session)
        import_reminders(session)
        import_inventory(session)
        import_assignments(session)
        import_meals(session)

    print("Import complete.")


if __name__ == "__main__":
    main()

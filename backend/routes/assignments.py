from flask import Blueprint, jsonify, request
from sqlalchemy import select

from db import session_scope
from models import EventAssignment, Member

assignments_bp = Blueprint("assignments", __name__)

# Map Google Calendar event colour IDs (1–11) to family member ids.
#  1 Lavender, 2 Sage, 3 Grape, 4 Flamingo, 5 Banana,
#  6 Tangerine, 7 Peacock, 8 Graphite, 9 Blueberry, 10 Basil, 11 Tomato
COLOR_TO_MEMBER = {
    "9": "jack",    # Blueberry
    "4": "hannah",  # Flamingo
    "10": "rafe",   # Basil
    "3": "ada",     # Grape
    "5": "kit",     # Banana
}


def _member_ids(session):
    return {m.id for m in session.scalars(select(Member)).all()}


def _from_name(summary, member_ids):
    if not summary:
        return None
    dash = summary.find(" - ")
    if dash == -1:
        return None
    candidate = summary[:dash].strip().lower()
    return candidate if candidate in member_ids else None


def resolve_assignment(event, overrides, member_ids):
    """Resolve an event's assignees as a LIST of member ids:
    1. local override  2. name prefix  3. Google colour  → else []."""
    eid = event.get("id")
    if eid and eid in overrides:
        ov = overrides[eid]
        if isinstance(ov, list):
            return [m for m in ov if m in member_ids]
        return [ov] if ov and ov in member_ids else []
    by_name = _from_name(event.get("summary"), member_ids)
    if by_name:
        return [by_name]
    color_id = event.get("color_id")
    if color_id and color_id in COLOR_TO_MEMBER:
        member = COLOR_TO_MEMBER[color_id]
        if member in member_ids:
            return [member]
    return []


def annotate_events(events):
    """Attach `assigned_to` (list of member ids) to each event and return it."""
    with session_scope() as session:
        rows = session.scalars(select(EventAssignment)).all()
        overrides = {r.event_id: r.members for r in rows}
        member_ids = _member_ids(session)
    for ev in events:
        ev["assigned_to"] = resolve_assignment(ev, overrides, member_ids)
    return events


@assignments_bp.route("/", methods=["POST"])
def set_assignment():
    """Set or clear the local override for an event.
    Body: {event_id, members}  (members null → remove override; [] → nobody)."""
    body = request.get_json() or {}
    event_id = body.get("event_id")
    if not event_id:
        return jsonify({"error": "event_id required"}), 400
    members = body.get("members")

    with session_scope() as session:
        row = session.get(EventAssignment, event_id)
        if members is None:
            if row:
                session.delete(row)
        else:
            if row:
                row.members = list(members)
            else:
                session.add(EventAssignment(event_id=event_id, members=list(members)))
    return jsonify({"event_id": event_id, "members": members})

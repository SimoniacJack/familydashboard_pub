from flask import Blueprint, jsonify, request
import uuid
from datetime import datetime
from sqlalchemy import select

from db import session_scope
from models import Chore, ChoreInstance, Room
from weeks import parse_date, day_key, week_key, month_key

chores_bp = Blueprint("chores", __name__)

# Map a chore frequency to the period_type its instances live at.
FREQ_TO_PERIOD = {"daily": "day", "weekly": "week", "monthly": "month", "once": "once"}


def _chore_dict(c):
    return {
        "id": c.id,
        "name": c.name,
        "description": c.description,
        "points": c.points,
        "frequency": c.frequency,
        "assignable": c.assignable,
        "assigned_to": c.assigned_to or "",
        "room_id": c.room_id or "",
        "created_at": c.created_at.isoformat() if c.created_at else None,
    }


def _instance_dict(inst, chore):
    return {
        "instance_id": inst.id,
        "chore_id": chore.id,
        "period_type": inst.period_type,
        "period_key": inst.period_key,
        "status": inst.status,
        "completed_by": inst.completed_by,
        "completed_at": inst.completed_at.isoformat() if inst.completed_at else None,
        "name": chore.name,
        "description": chore.description,
        "points": chore.points,
        "frequency": chore.frequency,
        "assignable": chore.assignable,
        "assigned_to": chore.assigned_to or "",
        "room_id": chore.room_id or "",
    }


def _get_or_create_instance(session, chore, period_type, period_key):
    inst = session.scalars(
        select(ChoreInstance).where(
            ChoreInstance.chore_id == chore.id,
            ChoreInstance.period_type == period_type,
            ChoreInstance.period_key == period_key,
        )
    ).first()
    if inst is None:
        inst = ChoreInstance(
            id=str(uuid.uuid4()),
            chore_id=chore.id,
            period_type=period_type,
            period_key=period_key,
            status="pending",
        )
        session.add(inst)
    return inst


def _ensure_for_date(session, d):
    """Materialise and return (instance, chore) pairs relevant to date `d`:
    that day's daily chores, the implied week's weekly chores, the implied
    month's monthly chores, and any open one-off jobs."""
    chores = session.scalars(select(Chore).where(Chore.is_active == True)).all()  # noqa: E712
    dk, wk, mk = day_key(d), week_key(d), month_key(d)

    result = []
    for chore in chores:
        freq = chore.frequency
        if freq == "daily":
            result.append((_get_or_create_instance(session, chore, "day", dk), chore))
        elif freq == "weekly":
            result.append((_get_or_create_instance(session, chore, "week", wk), chore))
        elif freq == "monthly":
            result.append((_get_or_create_instance(session, chore, "month", mk), chore))
        elif freq == "once":
            # One-off: a single instance that persists. Create on first sight;
            # always shown until done.
            inst = session.scalars(
                select(ChoreInstance).where(ChoreInstance.chore_id == chore.id)
            ).first()
            if inst is None:
                inst = _get_or_create_instance(session, chore, "once", "once")
            result.append((inst, chore))

    session.flush()
    return result


@chores_bp.route("/for-date", methods=["GET"])
def get_chores_for_date():
    """Return chore instances relevant to a selected date, bucketed by scope.
    Query: date=YYYY-MM-DD (defaults to today)."""
    ds = request.args.get("date")
    d = parse_date(ds) if ds else datetime.utcnow().date()
    with session_scope() as session:
        pairs = _ensure_for_date(session, d)
        buckets = {"day": [], "week": [], "month": [], "once": []}
        for inst, chore in pairs:
            buckets[inst.period_type].append(_instance_dict(inst, chore))
        return jsonify({"date": d.isoformat(), "buckets": buckets})


@chores_bp.route("/", methods=["GET"])
def get_chores():
    with session_scope() as session:
        chores = session.scalars(select(Chore).where(Chore.is_active == True)).all()  # noqa: E712
        return jsonify([_chore_dict(c) for c in chores])


@chores_bp.route("/", methods=["POST"])
def create_chore():
    body = request.get_json()
    freq = body.get("frequency", "weekly")
    if freq not in FREQ_TO_PERIOD:
        freq = "weekly"
    with session_scope() as session:
        chore = Chore(
            id=str(uuid.uuid4()),
            name=body["name"],
            description=body.get("description", ""),
            points=body.get("points", 0),
            frequency=freq,
            assignable=body.get("assignable", "all"),
            assigned_to=(body.get("assigned_to") or None),
            room_id=(body.get("room_id") or None),
            created_at=datetime.utcnow(),
            is_active=True,
        )
        session.add(chore)
        session.flush()
        return jsonify(_chore_dict(chore)), 201


@chores_bp.route("/<chore_id>", methods=["DELETE"])
def delete_chore(chore_id):
    with session_scope() as session:
        chore = session.get(Chore, chore_id)
        if chore:
            session.delete(chore)
    return jsonify({"ok": True})


@chores_bp.route("/instance/<instance_id>/complete", methods=["POST"])
def complete_instance(instance_id):
    body = request.get_json() or {}
    member_id = body.get("completed_by")
    with session_scope() as session:
        inst = session.get(ChoreInstance, instance_id)
        if not inst:
            return jsonify({"error": "Instance not found"}), 404
        chore = session.get(Chore, inst.chore_id)
        inst.status = "done"
        inst.completed_by = member_id
        inst.completed_at = datetime.utcnow()
        inst.points = chore.points if chore else 0
        session.flush()
        return jsonify(_instance_dict(inst, chore))


@chores_bp.route("/instance/<instance_id>/uncomplete", methods=["POST"])
def uncomplete_instance(instance_id):
    with session_scope() as session:
        inst = session.get(ChoreInstance, instance_id)
        if not inst:
            return jsonify({"error": "Instance not found"}), 404
        chore = session.get(Chore, inst.chore_id)
        inst.status = "pending"
        inst.completed_by = None
        inst.completed_at = None
        inst.points = 0
        session.flush()
        return jsonify(_instance_dict(inst, chore))


@chores_bp.route("/points", methods=["GET"])
def get_points():
    """Points per member from completed instances. 1 point = 10p."""
    with session_scope() as session:
        q = select(ChoreInstance).where(ChoreInstance.status == "done")
        totals = {}
        for inst in session.scalars(q).all():
            if inst.completed_by:
                totals[inst.completed_by] = totals.get(inst.completed_by, 0) + (inst.points or 0)
        return jsonify(totals)


@chores_bp.route("/rooms", methods=["GET"])
def get_rooms():
    with session_scope() as session:
        rooms = session.scalars(select(Room).order_by(Room.sort_order)).all()
        return jsonify([
            {"id": r.id, "name": r.name, "floor": r.floor} for r in rooms
        ])

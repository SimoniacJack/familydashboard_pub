from flask import Blueprint, jsonify, request
import uuid
from datetime import datetime
from sqlalchemy import select

from db import session_scope
from models import Reminder, ReminderInstance
from weeks import parse_date

reminders_bp = Blueprint("reminders", __name__)


def reminders_for_date(session, date_obj):
    """All active reminders annotated with done/instance for the given date.
    Lazily materialises a ReminderInstance per (reminder, date)."""
    reminders = session.scalars(
        select(Reminder).where(Reminder.is_active == True)  # noqa: E712
    ).all()

    existing = session.scalars(
        select(ReminderInstance).where(ReminderInstance.date == date_obj)
    ).all()
    by_reminder = {i.reminder_id: i for i in existing}

    out = []
    for r in reminders:
        inst = by_reminder.get(r.id)
        if inst is None:
            inst = ReminderInstance(
                id=str(uuid.uuid4()),
                reminder_id=r.id,
                date=date_obj,
                status="pending",
            )
            session.add(inst)
            by_reminder[r.id] = inst
        out.append({
            "id": r.id,
            "instance_id": inst.id,
            "member": r.member,
            "label": r.label,
            "routine": r.routine or "anytime",
            "done": inst.status == "done",
        })
    session.flush()
    return out


@reminders_bp.route("/", methods=["GET"])
def get_reminders():
    date_str = request.args.get("date", datetime.utcnow().strftime("%Y-%m-%d"))
    date_obj = parse_date(date_str)
    with session_scope() as session:
        return jsonify({"date": date_str, "reminders": reminders_for_date(session, date_obj)})


@reminders_bp.route("/", methods=["POST"])
def create_reminder():
    body = request.get_json()
    with session_scope() as session:
        r = Reminder(
            id=str(uuid.uuid4()),
            member=(body.get("member") or None),
            label=body["label"],
            routine=body.get("routine", "anytime"),
            is_active=True,
        )
        session.add(r)
        session.flush()
        return jsonify({"id": r.id, "member": r.member, "label": r.label, "routine": r.routine}), 201


@reminders_bp.route("/<reminder_id>", methods=["DELETE"])
def delete_reminder(reminder_id):
    with session_scope() as session:
        r = session.get(Reminder, reminder_id)
        if r:
            session.delete(r)  # cascades to instances
    return jsonify({"ok": True})


@reminders_bp.route("/<reminder_id>/toggle", methods=["POST"])
def toggle_reminder(reminder_id):
    body = request.get_json() or {}
    date_str = body.get("date", datetime.utcnow().strftime("%Y-%m-%d"))
    date_obj = parse_date(date_str)
    with session_scope() as session:
        inst = session.scalars(
            select(ReminderInstance).where(
                ReminderInstance.reminder_id == reminder_id,
                ReminderInstance.date == date_obj,
            )
        ).first()
        if inst is None:
            inst = ReminderInstance(
                id=str(uuid.uuid4()),
                reminder_id=reminder_id,
                date=date_obj,
                status="done",
                completed_at=datetime.utcnow(),
            )
            session.add(inst)
            done = True
        else:
            if inst.status == "done":
                inst.status = "pending"
                inst.completed_at = None
                done = False
            else:
                inst.status = "done"
                inst.completed_at = datetime.utcnow()
                done = True
        session.flush()
        return jsonify({"reminder_id": reminder_id, "date": date_str, "done": done})

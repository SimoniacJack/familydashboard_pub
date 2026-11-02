"""Steering editor — view/edit the AI meal-planning prompt and per-member
likes/dislikes from the UI. Edits are stored in `steering_docs` (DB) so they
persist across deploys; the baked files remain the default when no row exists.
"""
import os
from datetime import datetime

from flask import Blueprint, jsonify, request
from sqlalchemy import select

from db import session_scope
from models import SteeringDoc, Member

steering_bp = Blueprint("steering", __name__)

MEMBERS_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "familymembers")
PROMPT_FILE = os.path.join(os.path.dirname(__file__), "..", "prompts", "meal_planning.md")


def _baked_prompt():
    if os.path.exists(PROMPT_FILE):
        with open(PROMPT_FILE, "r", encoding="utf-8") as f:
            return f.read()
    return ""


def _baked_member(markdown_url):
    if not markdown_url:
        return ""
    path = os.path.join(os.path.dirname(__file__), "..", "..", markdown_url)
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    return ""


def _effective(session, key, baked):
    """(content, overridden) — DB row if present, else the baked default."""
    row = session.get(SteeringDoc, key)
    if row is not None and row.content.strip():
        return row.content, True
    return baked, False


@steering_bp.route("/", methods=["GET"])
def list_steering():
    """All editable steering docs: the meal-planning prompt + one per member."""
    docs = []
    with session_scope() as session:
        content, overridden = _effective(session, "meal_planning", _baked_prompt())
        docs.append({
            "key": "meal_planning",
            "title": "Meal-planning prompt",
            "kind": "prompt",
            "content": content,
            "overridden": overridden,
            "help": "Core instructions the AI follows when generating meals. Edit carefully.",
        })
        members = session.scalars(select(Member)).all()
        for m in members:
            key = f"member:{m.id}"
            content, overridden = _effective(session, key, _baked_member(m.markdown_url))
            docs.append({
                "key": key,
                "title": f"{m.name} — likes & dislikes",
                "kind": "member",
                "content": content,
                "overridden": overridden,
                "help": f"Steers meals for {m.name}. Plain text / markdown.",
            })
    return jsonify({"docs": docs})


@steering_bp.route("/<path:key>", methods=["PUT"])
def save_steering(key):
    """Upsert a steering doc. Body: {content}. An empty content deletes the
    override (reverts to the baked default)."""
    body = request.get_json(silent=True) or {}
    content = body.get("content", "")
    if not isinstance(content, str):
        return jsonify({"error": "content must be a string"}), 400
    with session_scope() as session:
        if content.strip() == "":
            row = session.get(SteeringDoc, key)
            if row is not None:
                session.delete(row)
            return jsonify({"ok": True, "key": key, "overridden": False})
        row = session.get(SteeringDoc, key)
        if row is None:
            row = SteeringDoc(key=key, content=content, updated_at=datetime.utcnow())
            session.add(row)
        else:
            row.content = content
            row.updated_at = datetime.utcnow()
    return jsonify({"ok": True, "key": key, "overridden": True})


@steering_bp.route("/<path:key>", methods=["DELETE"])
def revert_steering(key):
    """Delete the override so the baked default is used again."""
    with session_scope() as session:
        row = session.get(SteeringDoc, key)
        if row is not None:
            session.delete(row)
    return jsonify({"ok": True, "key": key, "overridden": False})

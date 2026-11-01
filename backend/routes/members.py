from flask import Blueprint, jsonify, send_file, abort
import os
from sqlalchemy import select

from db import session_scope
from models import Member

members_bp = Blueprint("members", __name__)

MEMBERS_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "familymembers")


def _find_image(name):
    for ext in ("png", "jpg", "jpeg", "webp"):
        for candidate in (name, name.capitalize(), name.lower(), name.upper()):
            path = os.path.join(MEMBERS_DIR, f"{candidate}.{ext}")
            if os.path.exists(path):
                return path
    return None


@members_bp.route("/")
def get_members():
    with session_scope() as session:
        members = session.scalars(select(Member)).all()
        return jsonify([
            {
                "id": m.id,
                "name": m.name,
                "role": m.role,
                "image": m.image_url or None,
            }
            for m in members
        ])


@members_bp.route("/<member_id>/image")
def get_member_image(member_id):
    if not member_id.isalnum():
        abort(404)
    path = _find_image(member_id)
    if not path:
        abort(404)
    return send_file(path)

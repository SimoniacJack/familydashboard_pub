from flask import Blueprint, jsonify, request
import uuid
from sqlalchemy import select

from db import session_scope
from models import InventoryItem

inventory_bp = Blueprint("inventory", __name__)

LOCATIONS = [
    "pantry",
    "fridge_inside",
    "freezer_inside",
    "fridge_outside",
    "freezer_outside",
]


def normalise(name):
    """Normalise an item name for matching: lowercase, trimmed, singular-ish."""
    n = (name or "").lower().strip()
    if len(n) > 3 and n.endswith("s") and not n.endswith("ss"):
        n = n[:-1]
    return n


def get_stocked_names():
    """Set of normalised names of everything currently in inventory."""
    with session_scope() as session:
        items = session.scalars(select(InventoryItem)).all()
        return {normalise(i.name) for i in items}


@inventory_bp.route("/", methods=["GET"])
def get_inventory():
    with session_scope() as session:
        items = session.scalars(select(InventoryItem)).all()
        grouped = {loc: [] for loc in LOCATIONS}
        for item in items:
            grouped.setdefault(item.location, []).append({
                "id": item.id,
                "name": item.name,
                "location": item.location,
                "note": item.note,
            })
        return jsonify({"locations": LOCATIONS, "items": grouped})


@inventory_bp.route("/", methods=["POST"])
def add_item():
    body = request.get_json()
    location = body.get("location", "pantry")
    if location not in LOCATIONS:
        return jsonify({"error": f"Invalid location '{location}'"}), 400
    with session_scope() as session:
        item = InventoryItem(
            id=str(uuid.uuid4()),
            name=body["name"].strip(),
            location=location,
            note=body.get("note", "").strip(),
        )
        session.add(item)
        session.flush()
        return jsonify({
            "id": item.id, "name": item.name, "location": item.location, "note": item.note,
        }), 201


@inventory_bp.route("/<item_id>", methods=["DELETE"])
def remove_item(item_id):
    with session_scope() as session:
        item = session.get(InventoryItem, item_id)
        if item:
            session.delete(item)
    return jsonify({"ok": True})

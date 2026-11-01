"""Master shopping list, reconciled against scheduled-meal needs.

The list is a single persistent Todoist project. On "update", we compute the
ingredients required by accepted meals that are NOT already in inventory, and
reconcile the Todoist list to match: add newly-needed auto items, remove auto
items no longer needed, and leave manually-added items untouched.

Auto items are tagged with the Todoist label "auto" so we only ever remove our
own additions, never the family's manual entries.
"""
from flask import Blueprint, jsonify, request
import os
import uuid
import requests as http_requests
from sqlalchemy import select

from db import session_scope
from models import ShoppingItem, MealSlot, LunchIdea
from routes.inventory import get_stocked_names, normalise

shopping_bp = Blueprint("shopping", __name__)

TODOIST = "https://api.todoist.com/api/v1"
PROJECT_NAME = "Family Shopping List"
AUTO_LABEL = "auto"


def _headers():
    token = os.environ.get("TODOIST_API_TOKEN")
    if not token:
        return None
    return {"Authorization": f"Bearer {token}"}


def _get_or_create_project(headers):
    r = http_requests.get(f"{TODOIST}/projects", headers=headers, timeout=10)
    r.raise_for_status()
    projects = r.json()
    projects = projects.get("results", projects) if isinstance(projects, dict) else projects
    for p in projects:
        if p["name"] == PROJECT_NAME:
            return p["id"]
    r = http_requests.post(f"{TODOIST}/projects", headers=headers, json={"name": PROJECT_NAME}, timeout=10)
    r.raise_for_status()
    return r.json()["id"]


def _tasks_in_project(headers, project_id):
    r = http_requests.get(f"{TODOIST}/tasks?project_id={project_id}", headers=headers, timeout=10)
    r.raise_for_status()
    tasks = r.json()
    return tasks.get("results", tasks) if isinstance(tasks, dict) else tasks


def _required_ingredients():
    """Ingredients needed by accepted meals, minus what's in inventory.
    Returns {normalised_name: {"item":..., "quantity":...}}."""
    with session_scope() as session:
        dinners = session.scalars(
            select(MealSlot).where(MealSlot.status == "accepted")
        ).all()
        lunches = session.scalars(
            select(LunchIdea).where(LunchIdea.status == "accepted")
        ).all()
        ingredients = {}
        for s in dinners:
            for ing in (s.meal or {}).get("ingredients", []):
                ingredients[normalise(ing["item"])] = ing
        for l in lunches:
            for ing in (l.meal or {}).get("ingredients", []):
                ingredients[normalise(ing["item"])] = ing

    stocked = get_stocked_names()
    return {k: v for k, v in ingredients.items() if k not in stocked}


@shopping_bp.route("/", methods=["GET"])
def get_list():
    """Return the master list as stored locally (auto + manual items)."""
    with session_scope() as session:
        items = session.scalars(select(ShoppingItem)).all()
        return jsonify([
            {"id": i.id, "name": i.name, "quantity": i.quantity, "source": i.source}
            for i in items
        ])


@shopping_bp.route("/items", methods=["POST"])
def add_manual_item():
    """Add a manual (e.g. non-grocery) item to the master list + Todoist."""
    body = request.get_json() or {}
    name = (body.get("name") or "").strip()
    if not name:
        return jsonify({"error": "name required"}), 400
    quantity = (body.get("quantity") or "").strip()
    headers = _headers()
    if not headers:
        return jsonify({"error": "TODOIST_API_TOKEN not set"}), 500

    project_id = _get_or_create_project(headers)
    content = f"{name} — {quantity}" if quantity else name
    r = http_requests.post(
        f"{TODOIST}/tasks",
        headers=headers,
        json={"content": content, "project_id": project_id},
        timeout=10,
    )
    r.raise_for_status()
    todoist_id = r.json()["id"]

    with session_scope() as session:
        session.add(ShoppingItem(
            id=str(uuid.uuid4()), name=name, norm=normalise(name),
            quantity=quantity, source="manual", todoist_id=todoist_id,
        ))
    return jsonify({"ok": True, "name": name, "source": "manual"}), 201


@shopping_bp.route("/items/<item_id>", methods=["DELETE"])
def remove_item(item_id):
    """Remove an item from the master list + Todoist (manual or auto)."""
    headers = _headers()
    with session_scope() as session:
        item = session.get(ShoppingItem, item_id)
        if not item:
            return jsonify({"error": "not found"}), 404
        if headers and item.todoist_id:
            http_requests.delete(f"{TODOIST}/tasks/{item.todoist_id}", headers=headers, timeout=10)
        session.delete(item)
    return jsonify({"ok": True})


@shopping_bp.route("/update", methods=["POST"])
def update_list():
    """Reconcile the auto portion of the master list against current needs.
    Manual items are preserved. Auto items are added/removed to match
    required-minus-inventory."""
    headers = _headers()
    if not headers:
        return jsonify({"error": "TODOIST_API_TOKEN not set"}), 500

    required = _required_ingredients()  # {norm: ingredient}
    project_id = _get_or_create_project(headers)

    added, removed = [], []
    with session_scope() as session:
        existing = session.scalars(select(ShoppingItem)).all()
        auto_by_norm = {i.norm: i for i in existing if i.source == "auto"}
        manual_norms = {i.norm for i in existing if i.source == "manual"}

        # 1. Remove auto items no longer required
        for norm, item in list(auto_by_norm.items()):
            if norm not in required:
                if item.todoist_id:
                    http_requests.delete(f"{TODOIST}/tasks/{item.todoist_id}", headers=headers, timeout=10)
                removed.append(item.name)
                session.delete(item)
                del auto_by_norm[norm]

        # 2. Add newly-required items (skip ones already present as manual/auto)
        for norm, ing in required.items():
            if norm in auto_by_norm or norm in manual_norms:
                continue
            content = f"{ing['item']} — {ing.get('quantity', '')}".strip(" —")
            r = http_requests.post(
                f"{TODOIST}/tasks",
                headers=headers,
                json={"content": content, "project_id": project_id, "labels": [AUTO_LABEL]},
                timeout=10,
            )
            r.raise_for_status()
            session.add(ShoppingItem(
                id=str(uuid.uuid4()), name=ing["item"], norm=norm,
                quantity=ing.get("quantity", ""), source="auto",
                todoist_id=r.json()["id"],
            ))
            added.append(ing["item"])

    return jsonify({
        "project": PROJECT_NAME,
        "added": added,
        "removed": removed,
        "added_count": len(added),
        "removed_count": len(removed),
    })

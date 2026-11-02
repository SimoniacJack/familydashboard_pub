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
from datetime import datetime, timedelta, timezone
import requests as http_requests
from sqlalchemy import select

from db import session_scope
from models import ShoppingItem, MealSlot, LunchIdea, FiledShoppingItem, SyncState
from routes.inventory import get_stocked_names, normalise, LOCATIONS, get_restock_needs, restock_or_add

shopping_bp = Blueprint("shopping", __name__)

TODOIST = "https://api.todoist.com/api/v1"
PROJECT_NAME = "Family Shopping List"
AUTO_LABEL = "auto"
COMPLETED_CURSOR_KEY = "todoist_completed_since"


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


def on_list_norms():
    """Normalised names of items currently on the Todoist shopping list (auto +
    manual + Google-Home additions). Reads through to Todoist so it reflects the
    live list. Returns a set; empty on any failure so callers degrade gracefully
    (an unknown list is treated as 'nothing on the list')."""
    headers = _headers()
    if not headers:
        return set()
    try:
        project_id = _get_or_create_project(headers)
        tasks = _tasks_in_project(headers, project_id)
    except http_requests.RequestException:
        return set()
    norms = set()
    for t in tasks:
        content = (t.get("content") or "")
        # Todoist content may be "Name — quantity"; match on the name part.
        name = content.split("—")[0].strip() if "—" in content else content.strip()
        if name:
            norms.add(normalise(name))
    return norms


def _required_ingredients():
    """Ingredients needed by accepted meals, minus what's in inventory, PLUS
    tracked staples that are running low/out (regardless of meals).
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
            for ing in s.ingredients:
                if ing.item:
                    ingredients[normalise(ing.item)] = {"item": ing.item, "quantity": ing.quantity}
        for l in lunches:
            for ing in l.ingredients:
                if ing.item:
                    ingredients[normalise(ing.item)] = {"item": ing.item, "quantity": ing.quantity}

    # Meal needs minus what's genuinely in stock (tracked low/out counts as not
    # in stock, so a meal that needs milk still adds it when milk is low).
    stocked = get_stocked_names()
    required = {k: v for k, v in ingredients.items() if k not in stocked}

    # Tracked staples running low/out are added regardless of any meal. A meal
    # entry already present keeps its quantity; otherwise use the restock text.
    for norm, text in get_restock_needs().items():
        required.setdefault(norm, {"item": text, "quantity": ""})

    return required


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


def reconcile_auto_items():
    """Reconcile the auto portion of the shopping list against current needs.
    Manual items are preserved. Auto items are added/removed to match
    required-minus-inventory. Returns {added, removed} or None if no Todoist
    token is configured (so callers can no-op silently)."""
    headers = _headers()
    if not headers:
        return None

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

    return {"added": added, "removed": removed}


@shopping_bp.route("/update", methods=["POST"])
def update_list():
    """Reconcile the auto portion of the master list against current needs.
    Manual items are preserved. Auto items are added/removed to match
    required-minus-inventory."""
    headers = _headers()
    if not headers:
        return jsonify({"error": "TODOIST_API_TOKEN not set"}), 500

    result = reconcile_auto_items()
    added, removed = result["added"], result["removed"]
    return jsonify({
        "project": PROJECT_NAME,
        "added": added,
        "removed": removed,
        "added_count": len(added),
        "removed_count": len(removed),
    })


@shopping_bp.route("/draft", methods=["POST"])
def draft_list():
    """Stage 1 of 'push to shopping list'. Recompute reservations from the
    currently-accepted meals, then return a DRAFT of what looks missing —
    unmatched ingredients, count-item shortfalls, and level items running low.
    Writes NOTHING to Todoist; the user reviews the draft, then calls
    /push-confirm. Body: {use_gpt?: bool}."""
    from routes.reservations import recompute_reservations

    body = request.get_json(silent=True) or {}
    use_gpt = body.get("use_gpt", True)

    with session_scope() as session:
        res = recompute_reservations(session, use_gpt=use_gpt)

        # Draft lines, de-duplicated by normalised name.
        draft = {}

        def add_line(name, quantity, reason):
            norm = normalise(name)
            if norm not in draft:
                draft[norm] = {"name": name, "quantity": quantity or "",
                               "reason": reason}

        # unmatched meal ingredients -> propose buying
        for u in res["unmatched"]:
            add_line(u["item"], u.get("quantity", ""), "not in inventory")
        # count-item shortfalls -> propose buying the shortfall
        for s in res["shortfalls"]:
            add_line(s["item"], "", "short in stock")

    # level items running low/out and any count items with no available units
    for norm, text in get_restock_needs().items():
        if norm not in draft:
            draft[norm] = {"name": text, "quantity": "", "reason": "running low"}

    lines = sorted(draft.values(), key=lambda d: d["name"].lower())
    return jsonify({
        "draft": lines,
        "reserved": res["reserved"],
        "used_gpt": res["used_gpt"],
        "counts": {"reserved": len(res["reserved"]),
                   "unmatched": len(res["unmatched"]),
                   "shortfalls": len(res["shortfalls"]),
                   "draft": len(lines)},
    })


@shopping_bp.route("/push-confirm", methods=["POST"])
def push_confirm():
    """Stage 2 of 'push to shopping list'. Write the user-confirmed draft lines
    to Todoist as auto items. Body: {items: [{name, quantity?}]}. Manual and
    Google-Home items are never touched; an item already on the list (manual or
    auto) is skipped so nothing is duplicated."""
    headers = _headers()
    if not headers:
        return jsonify({"error": "TODOIST_API_TOKEN not set"}), 500
    body = request.get_json() or {}
    items = body.get("items") or []
    if not isinstance(items, list):
        return jsonify({"error": "items must be a list"}), 400

    project_id = _get_or_create_project(headers)
    added = []
    with session_scope() as session:
        existing = session.scalars(select(ShoppingItem)).all()
        present = {i.norm for i in existing}
        for line in items:
            name = (line.get("name") or "").strip()
            if not name:
                continue
            norm = normalise(name)
            if norm in present:
                continue  # already on the list (manual or auto) — don't dup
            quantity = (line.get("quantity") or "").strip()
            content = f"{name} — {quantity}".strip(" —")
            r = http_requests.post(
                f"{TODOIST}/tasks",
                headers=headers,
                json={"content": content, "project_id": project_id, "labels": [AUTO_LABEL]},
                timeout=10,
            )
            r.raise_for_status()
            session.add(ShoppingItem(
                id=str(uuid.uuid4()), name=name, norm=norm,
                quantity=quantity, source="auto", todoist_id=r.json()["id"],
            ))
            present.add(norm)
            added.append(name)

    return jsonify({"project": PROJECT_NAME, "added": added, "added_count": len(added)})


# ──────────────────────────────────────────────────────────────────────────
# Shopping → Inventory flow
#
# Todoist is the source of truth (the family also manages the list via Google
# Home). The dashboard reads the live list from Todoist and can complete items
# through the API. A completed item (ticked here OR in Google Home) can be
# filed into inventory with a chosen location. Completed items are LEFT closed
# in Todoist, never deleted.
# ──────────────────────────────────────────────────────────────────────────


def _project_task_map(headers):
    """Return {todoist_id: task} for active tasks in the shopping project."""
    project_id = _get_or_create_project(headers)
    tasks = _tasks_in_project(headers, project_id)
    return project_id, {str(t["id"]): t for t in tasks}


@shopping_bp.route("/active", methods=["GET"])
def active_list():
    """Live active (uncompleted) tasks in the Todoist shopping project.
    Reads through to Todoist so Google-Home additions are reflected."""
    headers = _headers()
    if not headers:
        return jsonify({"error": "TODOIST_API_TOKEN not set"}), 500
    _project_id, task_map = _project_task_map(headers)
    items = [
        {"todoist_id": tid, "content": t.get("content", ""),
         "labels": t.get("labels", [])}
        for tid, t in task_map.items()
    ]
    items.sort(key=lambda i: i["content"].lower())
    return jsonify({"items": items})


@shopping_bp.route("/complete", methods=["POST"])
def complete_item():
    """Close a task in Todoist (so Google Home sees it done too). Does NOT add
    to inventory yet — the client then calls /file-to-inventory with a location.
    Returns the item so the UI can prompt for a location."""
    body = request.get_json() or {}
    todoist_id = str(body.get("todoist_id") or "").strip()
    name = (body.get("content") or body.get("name") or "").strip()
    if not todoist_id:
        return jsonify({"error": "todoist_id required"}), 400
    headers = _headers()
    if not headers:
        return jsonify({"error": "TODOIST_API_TOKEN not set"}), 500

    r = http_requests.post(f"{TODOIST}/tasks/{todoist_id}/close", headers=headers, timeout=10)
    r.raise_for_status()

    # Drop our local mirror row if present (auto/manual item now bought).
    with session_scope() as session:
        row = session.scalars(
            select(ShoppingItem).where(ShoppingItem.todoist_id == todoist_id)
        ).first()
        if row:
            if not name:
                name = row.name
            session.delete(row)

    return jsonify({"ok": True, "todoist_id": todoist_id, "name": name})


def _completed_tasks(headers, project_id, since):
    """Completed tasks in the project since `since` (UTC datetime).

    Uses the v1 completed-by-completion-date endpoint, which requires both
    `since` and `until`. Returns [] (not an error) if the endpoint is
    unavailable, so the dashboard-tick flow keeps working regardless.
    """
    params = {
        "project_id": project_id,
        "since": since.strftime("%Y-%m-%dT%H:%M:%S"),
        "until": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S"),
    }
    try:
        r = http_requests.get(
            f"{TODOIST}/tasks/completed/by_completion_date",
            headers=headers, params=params, timeout=10,
        )
        r.raise_for_status()
    except http_requests.RequestException:
        return []
    data = r.json()
    if isinstance(data, dict):
        return data.get("items") or data.get("results") or []
    return data or []


@shopping_bp.route("/completed-unfiled", methods=["GET"])
def completed_unfiled():
    """Tasks completed in Todoist (e.g. via Google Home) that have NOT yet been
    filed to inventory or dismissed. These are offered to the user with a
    location picker."""
    headers = _headers()
    if not headers:
        return jsonify({"error": "TODOIST_API_TOKEN not set"}), 500
    project_id = _get_or_create_project(headers)

    # Look back a bounded window (default 14 days) from a stored cursor.
    with session_scope() as session:
        cur = session.get(SyncState, COMPLETED_CURSOR_KEY)
        if cur and cur.value:
            try:
                since = datetime.fromisoformat(cur.value)
            except ValueError:
                since = datetime.now(timezone.utc) - timedelta(days=14)
        else:
            since = datetime.now(timezone.utc) - timedelta(days=14)
        handled = {f.todoist_id for f in session.scalars(select(FiledShoppingItem)).all()}

    completed = _completed_tasks(headers, project_id, since)
    items = [
        {"todoist_id": str(t["id"]), "content": t.get("content", "")}
        for t in completed
        if str(t["id"]) not in handled
    ]
    items.sort(key=lambda i: i["content"].lower())
    return jsonify({"items": items, "locations": LOCATIONS})


@shopping_bp.route("/file-to-inventory", methods=["POST"])
def file_to_inventory():
    """Add a (completed) item to inventory at a chosen location, and record it
    as filed so it is never offered or filed again. If a todoist_id is given it
    is marked handled; the task is LEFT completed in Todoist (not deleted)."""
    body = request.get_json() or {}
    name = (body.get("name") or body.get("content") or "").strip()
    location = (body.get("location") or "pantry").strip()
    todoist_id = str(body.get("todoist_id") or "").strip() or None
    note = (body.get("note") or "").strip()

    if not name:
        return jsonify({"error": "name required"}), 400
    if location not in LOCATIONS:
        return jsonify({"error": f"invalid location '{location}'"}), 400

    with session_scope() as session:
        # Shared helper: restocks an existing tracked item to full, else adds.
        item, _action = restock_or_add(session, name, location, note=note)
        if todoist_id:
            session.merge(FiledShoppingItem(
                todoist_id=todoist_id, name=name, filed=True, location=location,
            ))
        session.flush()
        result = {"id": item.id, "name": item.name, "location": item.location,
                  "level": item.level, "tracked": item.tracked}

    return jsonify({"ok": True, "item": result}), 201


@shopping_bp.route("/dismiss-completed", methods=["POST"])
def dismiss_completed():
    """Dismiss a completed item without filing it (e.g. a non-grocery task), so
    it stops appearing in the 'just bought' list."""
    body = request.get_json() or {}
    todoist_id = str(body.get("todoist_id") or "").strip()
    if not todoist_id:
        return jsonify({"error": "todoist_id required"}), 400
    with session_scope() as session:
        session.merge(FiledShoppingItem(
            todoist_id=todoist_id, name=(body.get("content") or "").strip(),
            filed=False, location=None,
        ))
    return jsonify({"ok": True})

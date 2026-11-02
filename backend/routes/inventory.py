from flask import Blueprint, jsonify, request
import os
import json
import uuid
import requests as http_requests
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

# Rough stock levels for LEVEL-mode items (rice, pasta, flour, milk...).
# low/out means "running out" -> auto-added to the shopping list on reconcile.
LEVELS = ["full", "ok", "low", "out"]
NEEDS_RESTOCK = {"low", "out"}

# How an item's amount is expressed.
#   count -> discrete units (cans, boxes); `count` holds how many, `planned`
#            how many are reserved by accepted meals; available = count-planned.
#   level -> indiscrete amount; `level` is full/ok/low/out.
TRACK_MODES = ["count", "level"]

# Open Food Facts: free, no API key, strong UK grocery coverage.
OFF_URL = "https://world.openfoodfacts.org/api/v2/product/{barcode}.json"
OFF_TIMEOUT = 8


def normalise(name):
    """Normalise an item name for matching: lowercase, trimmed, singular-ish."""
    n = (name or "").lower().strip()
    if len(n) > 3 and n.endswith("s") and not n.endswith("ss"):
        n = n[:-1]
    return n


def available(item):
    """Units free to reserve for the next meal (count mode): count - planned,
    floored at 0. Meaningless for level items (returns None)."""
    if item.track_mode != "count":
        return None
    return max(0, (item.count or 0) - (item.planned or 0))


def in_stock(item):
    """Is this item considered 'in stock' for shopping reconciliation?
    - count: has at least one AVAILABLE unit (count - planned > 0).
    - level: not low/out.
    """
    if item.track_mode == "count":
        return available(item) > 0
    return item.level not in NEEDS_RESTOCK


def _serialize(item):
    return {
        "id": item.id,
        "name": item.name,
        "location": item.location,
        "note": item.note,
        "track_mode": item.track_mode,
        # count-mode fields
        "count": item.count,
        "planned": item.planned,
        "available": available(item),
        # level-mode fields
        "level": item.level,
        "restock": item.restock,
        # legacy flag kept in sync (level mode == the old "tracked")
        "tracked": item.track_mode == "level",
    }


def restock_or_add(session, name, location, *, note="", track_mode="count",
                   count=1, level="full", restock=""):
    """Add an item, OR fold into an existing item of the same normalised name.

    Folding rule (used by the scanner and the shopping 'file to inventory'):
      - count mode existing -> count += `count` (bump how many we have).
      - level mode existing -> level reset to 'full' (restocked).
    Returns (item, action) where action is 'added', 'incremented', 'restocked'.
    """
    norm = normalise(name)
    existing = next(
        (i for i in session.scalars(select(InventoryItem)).all()
         if normalise(i.name) == norm),
        None,
    )
    if existing is not None:
        if existing.track_mode == "count":
            existing.count = (existing.count or 0) + max(1, int(count or 1))
            if location in LOCATIONS:
                existing.location = location
            if note:
                existing.note = note
            session.flush()
            return existing, "incremented"
        # level mode -> restock to full
        existing.level = "full"
        if location in LOCATIONS:
            existing.location = location
        if note:
            existing.note = note
        session.flush()
        return existing, "restocked"

    mode = track_mode if track_mode in TRACK_MODES else "count"
    item = InventoryItem(
        id=str(uuid.uuid4()), name=name.strip(), location=location,
        note=note.strip(), track_mode=mode,
        count=max(1, int(count or 1)) if mode == "count" else 1,
        planned=0,
        level=level if level in LEVELS else "full",
        restock=(restock or "").strip(),
        tracked=(mode == "level"),
    )
    session.add(item)
    session.flush()
    return item, "added"


def _lookup_barcode(barcode):
    """Resolve a barcode to a product name via Open Food Facts.
    Returns {found, name, brand}. Never raises — a lookup failure just means
    the UI falls back to manual entry."""
    try:
        r = http_requests.get(OFF_URL.format(barcode=barcode), timeout=OFF_TIMEOUT,
                              headers={"User-Agent": "FamilyDashboard/1.0"})
        r.raise_for_status()
        data = r.json()
    except (http_requests.RequestException, ValueError):
        return {"found": False, "name": "", "brand": ""}
    if data.get("status") != 1:
        return {"found": False, "name": "", "brand": ""}
    p = data.get("product", {}) or {}
    name = (p.get("product_name") or p.get("generic_name") or "").strip()
    brand = (p.get("brands") or "").split(",")[0].strip()
    return {"found": bool(name), "name": name, "brand": brand}


def get_stocked_names():
    """Normalised names counted as 'in stock' for shopping reconciliation."""
    with session_scope() as session:
        items = session.scalars(select(InventoryItem)).all()
        return {normalise(i.name) for i in items if in_stock(i)}


def get_restock_needs():
    """Items that need restocking, as {norm: shopping_text}:
      - level items at low/out,
      - count items with no available units (count - planned <= 0).
    Uses restock text when set, else the item name.
    """
    with session_scope() as session:
        items = session.scalars(select(InventoryItem)).all()
        needs = {}
        for i in items:
            short = (i.track_mode == "level" and i.level in NEEDS_RESTOCK) or \
                    (i.track_mode == "count" and available(i) <= 0)
            if short:
                needs[normalise(i.name)] = (i.restock.strip() or i.name)
        return needs


@inventory_bp.route("/", methods=["GET"])
def get_inventory():
    with session_scope() as session:
        items = session.scalars(select(InventoryItem)).all()
        grouped = {loc: [] for loc in LOCATIONS}
        for item in items:
            grouped.setdefault(item.location, []).append(_serialize(item))
        return jsonify({
            "locations": LOCATIONS, "levels": LEVELS,
            "track_modes": TRACK_MODES, "items": grouped,
        })


@inventory_bp.route("/", methods=["POST"])
def add_item():
    body = request.get_json() or {}
    location = body.get("location", "pantry")
    if location not in LOCATIONS:
        return jsonify({"error": f"Invalid location '{location}'"}), 400
    name = (body.get("name") or "").strip()
    if not name:
        return jsonify({"error": "name required"}), 400
    track_mode = (body.get("track_mode") or "count").strip()
    if track_mode not in TRACK_MODES:
        return jsonify({"error": f"Invalid track_mode '{track_mode}'"}), 400
    level = (body.get("level") or "full").strip()
    if level not in LEVELS:
        return jsonify({"error": f"Invalid level '{level}'"}), 400
    try:
        count = max(1, int(body.get("count", 1)))
    except (TypeError, ValueError):
        return jsonify({"error": "count must be an integer"}), 400
    with session_scope() as session:
        item = InventoryItem(
            id=str(uuid.uuid4()),
            name=name,
            location=location,
            note=body.get("note", "").strip(),
            track_mode=track_mode,
            count=count if track_mode == "count" else 1,
            planned=0,
            level=level,
            restock=(body.get("restock") or "").strip(),
            tracked=(track_mode == "level"),
        )
        session.add(item)
        session.flush()
        return jsonify(_serialize(item)), 201


@inventory_bp.route("/lookup/<barcode>", methods=["GET"])
def lookup_barcode(barcode):
    """Resolve a scanned barcode to a product name (Open Food Facts proxy).
    Always 200: {found, name, brand}. The client falls back to manual entry
    when found is false."""
    barcode = (barcode or "").strip()
    if not barcode.isdigit() or not (6 <= len(barcode) <= 14):
        return jsonify({"found": False, "name": "", "brand": "",
                        "error": "invalid barcode"}), 200
    return jsonify(_lookup_barcode(barcode)), 200


@inventory_bp.route("/scan-add", methods=["POST"])
def scan_add():
    """Add a scanned/looked-up item to inventory. Folds into an existing item
    of the same name: count mode increments, level mode restocks to full."""
    body = request.get_json() or {}
    name = (body.get("name") or "").strip()
    location = body.get("location", "pantry")
    if not name:
        return jsonify({"error": "name required"}), 400
    if location not in LOCATIONS:
        return jsonify({"error": f"Invalid location '{location}'"}), 400
    track_mode = (body.get("track_mode") or "count").strip()
    if track_mode not in TRACK_MODES:
        return jsonify({"error": f"Invalid track_mode '{track_mode}'"}), 400
    try:
        count = max(1, int(body.get("count", 1)))
    except (TypeError, ValueError):
        return jsonify({"error": "count must be an integer"}), 400
    with session_scope() as session:
        item, action = restock_or_add(
            session, name, location,
            note=(body.get("note") or "").strip(),
            track_mode=track_mode,
            count=count,
            restock=(body.get("restock") or "").strip(),
        )
        result = _serialize(item)
    return jsonify({"ok": True, "action": action, "item": result}), 201


@inventory_bp.route("/<item_id>", methods=["PATCH"])
def update_item(item_id):
    """Update an item's fields: level (full/ok/low/out), track_mode, count,
    restock, note, location. Used by the inventory UI toggles."""
    body = request.get_json() or {}
    with session_scope() as session:
        item = session.get(InventoryItem, item_id)
        if not item:
            return jsonify({"error": "not found"}), 404
        if "track_mode" in body:
            tm = (body.get("track_mode") or "").strip()
            if tm not in TRACK_MODES:
                return jsonify({"error": f"Invalid track_mode '{tm}'"}), 400
            item.track_mode = tm
            item.tracked = (tm == "level")
        if "level" in body:
            level = (body.get("level") or "").strip()
            if level not in LEVELS:
                return jsonify({"error": f"Invalid level '{level}'"}), 400
            item.level = level
        if "count" in body:
            try:
                item.count = max(0, int(body.get("count")))
            except (TypeError, ValueError):
                return jsonify({"error": "count must be an integer"}), 400
        if "restock" in body:
            item.restock = (body.get("restock") or "").strip()
        if "note" in body:
            item.note = (body.get("note") or "").strip()
        if "location" in body:
            loc = body.get("location")
            if loc not in LOCATIONS:
                return jsonify({"error": f"Invalid location '{loc}'"}), 400
            item.location = loc
        session.flush()
        return jsonify(_serialize(item))


@inventory_bp.route("/<item_id>/use", methods=["POST"])
def use_item(item_id):
    """Adjust a count item by a delta (default -1 = used one). Floors at 0.
    Also releases an equal amount of `planned` when consuming, so available
    stays correct. For level items, a body {level:...} sets the level instead."""
    body = request.get_json() or {}
    with session_scope() as session:
        item = session.get(InventoryItem, item_id)
        if not item:
            return jsonify({"error": "not found"}), 404
        if item.track_mode == "count":
            try:
                delta = int(body.get("delta", -1))
            except (TypeError, ValueError):
                return jsonify({"error": "delta must be an integer"}), 400
            item.count = max(0, (item.count or 0) + delta)
            if delta < 0:
                # Consuming units also releases that many reservations.
                item.planned = max(0, (item.planned or 0) + delta)
            if item.planned > item.count:
                item.planned = item.count
        else:
            lvl = (body.get("level") or "").strip()
            if lvl and lvl in LEVELS:
                item.level = lvl
        session.flush()
        return jsonify(_serialize(item))


@inventory_bp.route("/<item_id>", methods=["DELETE"])
def remove_item(item_id):
    with session_scope() as session:
        item = session.get(InventoryItem, item_id)
        if item:
            session.delete(item)
    return jsonify({"ok": True})


# ── Receipt scan (photo -> item list via GPT-4o vision) ─────────────────────
# One photo of a supermarket receipt returns a reviewable list of grocery
# items. No DB write happens here — the client shows a checklist and the user
# bulk-adds the kept items via /scan-add. GPT expands abbreviations ("HNZ BNS"
# -> "Heinz Beans") and drops non-grocery lines (totals, card, VAT).
RECEIPT_PROMPT = (
    "You are reading a photo of a UK supermarket till receipt. "
    "Return ONLY the grocery/food/household items a family would stock at home. "
    "Expand shop abbreviations into normal names (e.g. 'HNZ BNS 400G' -> "
    "'Heinz Baked Beans'). Drop everything that is not a stockable item: "
    "store name, date, totals, subtotal, VAT, change, card/cash lines, "
    "loyalty points, bag charges, multibuy discount lines. "
    "Respond with STRICT JSON only, no prose, in this exact shape: "
    '{"items":[{"name":"Heinz Baked Beans","quantity":2}]}. '
    "quantity is the number bought (default 1 when the line shows no count)."
)


@inventory_bp.route("/receipt-scan", methods=["POST"])
def receipt_scan():
    """Parse a receipt photo into a reviewable item list. Body:
      {image: "data:image/jpeg;base64,...."}  (a data URL or bare base64).
    Returns {ok, items:[{name, quantity}]}. Never writes to the DB — the client
    reviews then bulk-adds. 502 if the OCR/LLM call fails; 400 on bad input."""
    if not os.environ.get("OPENAI_API_KEY"):
        return jsonify({"error": "OpenAI not configured"}), 503
    body = request.get_json(silent=True) or {}
    image = (body.get("image") or "").strip()
    if not image:
        return jsonify({"error": "image required"}), 400
    # Accept a bare base64 string too — normalise to a data URL for the API.
    if not image.startswith("data:"):
        image = "data:image/jpeg;base64," + image
    try:
        from openai import OpenAI
        client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])
        resp = client.chat.completions.create(
            model="gpt-4o",
            messages=[{
                "role": "user",
                "content": [
                    {"type": "text", "text": RECEIPT_PROMPT},
                    {"type": "image_url", "image_url": {"url": image, "detail": "high"}},
                ],
            }],
            response_format={"type": "json_object"},
            max_tokens=1500,
            temperature=0,
        )
        raw = resp.choices[0].message.content or "{}"
        parsed = json.loads(raw)
    except Exception as exc:  # noqa: BLE001 — surface a clean error to the UI
        return jsonify({"error": f"receipt read failed: {exc}"}), 502

    items = []
    for it in (parsed.get("items") or []):
        name = (str(it.get("name") or "")).strip()
        if not name:
            continue
        try:
            qty = max(1, int(it.get("quantity", 1)))
        except (TypeError, ValueError):
            qty = 1
        items.append({"name": name, "quantity": qty})
    return jsonify({"ok": True, "items": items}), 200

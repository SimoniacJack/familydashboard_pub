from flask import Blueprint, jsonify, request
import json, os, uuid, glob
from datetime import datetime, timedelta
from openai import OpenAI
import requests as http_requests
from sqlalchemy import select

from routes.inventory import get_stocked_names, normalise
from routes.config import family_name
from db import session_scope
from models import MealSlot, LunchIdea, MealIngredient, InventoryItem
from weeks import parse_date

meals_bp = Blueprint("meals", __name__)

MEMBERS_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "familymembers")
PROMPT_FILE = os.path.join(os.path.dirname(__file__), "..", "prompts", "meal_planning.md")

def get_openai_client():
    return OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))

DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]

# ── Data helpers (DB-backed) ────────────────────────────────────────────────
# read_data/write_data preserve the original JSON shape
# ({slots, lunch_ideas, generated_at}) so the rest of this module and the
# calendar route keep working unchanged. Meals are now relational: scalar fields
# live in columns and ingredients in the meal_ingredients table, but the
# serialized shape handed to the frontend is identical to the old JSON blob.

def _ingredients_payload(owner):
    """Serialize an owner's ingredient rows back to the [{item, quantity}] shape
    the frontend and matcher expect, in position order."""
    return [{"item": ing.item, "quantity": ing.quantity}
            for ing in sorted(owner.ingredients, key=lambda i: i.position)]

def _meal_payload(owner):
    """Rebuild the `meal` dict (name/description/prep_minutes/ingredients) from
    columns + ingredient rows. Returns None when the meal is empty (pending)."""
    if owner.name is None and not owner.ingredients:
        return None
    return {
        "name": owner.name,
        "description": owner.description,
        "prep_minutes": owner.prep_minutes,
        "ingredients": _ingredients_payload(owner),
    }

def _slot_to_dict(s):
    date_obj = s.date
    return {
        "id": s.id,
        "day": DAYS[date_obj.weekday()],
        "date": date_obj.isoformat(),
        "display_date": f"{date_obj.day} {date_obj.strftime('%b')}",
        "meal_type": s.meal_type,
        "status": s.status,
        "meal": _meal_payload(s),
        "rejection_reasons": s.rejection_reasons or [],
        "calendar_events": [],
    }

def _lunch_to_dict(l):
    d = dict(_meal_payload(l) or {})
    d["id"] = l.id
    d["status"] = l.status
    d["week_start"] = l.week_start.isoformat() if l.week_start else None
    d["rejection_reasons"] = l.rejection_reasons or []
    return d

def read_data():
    with session_scope() as session:
        slots = session.scalars(select(MealSlot).order_by(MealSlot.date)).all()
        lunches = session.scalars(select(LunchIdea)).all()
        return {
            "slots": [_slot_to_dict(s) for s in slots],
            "lunch_ideas": [_lunch_to_dict(l) for l in lunches],
            "generated_at": None,
        }

def _sync_ingredients(owner, meal_dict, *, is_slot):
    """Replace an owner's ingredient rows from a meal dict, PRESERVING the
    stored inventory match + reserved_qty for a line whose (item, quantity) is
    unchanged — but ONLY while the meal is still accepted. A meal that is no
    longer accepted (rejected, regenerated, reverted) must not carry its old
    reservations onto the new rows: doing so left `planned`/`reserved_qty`
    stranded with no accepted meal behind them (the orphaned-reservation bug).
    Reservations are rebuilt from the accepted set by recompute_reservations."""
    keep_res = (getattr(owner, "status", None) == "accepted")
    old_by_key = {(i.item, i.quantity): i for i in list(owner.ingredients)}
    new_ings = (meal_dict or {}).get("ingredients", []) if meal_dict else []
    owner.ingredients.clear()  # delete-orphan removes rows no longer present
    for pos, ing in enumerate(new_ings):
        item = (ing.get("item") or "").strip()
        if not item:
            continue
        quantity = (ing.get("quantity") or "").strip()
        prev = old_by_key.get((item, quantity)) if keep_res else None
        row = MealIngredient(
            id=str(uuid.uuid4()), item=item, quantity=quantity, position=pos,
            inventory_item_id=prev.inventory_item_id if prev else None,
            reserved_qty=prev.reserved_qty if prev else 0,
            match_locked=prev.match_locked if prev else False,
        )
        owner.ingredients.append(row)

def write_data(data):
    """Persist the full meals state from the in-memory dict shape used
    throughout this module. UPSERTS rows (never delete-all), so ingredient
    inventory links + reservations survive a meal edit."""
    with session_scope() as session:
        slots = data.get("slots", [])
        lunches = data.get("lunch_ideas", [])
        want_slot_ids = {s["id"] for s in slots}
        want_lunch_ids = {l["id"] for l in lunches}

        # Remove slots/lunches no longer present (cascade drops their ingredients).
        for s in session.scalars(select(MealSlot)).all():
            if s.id not in want_slot_ids:
                session.delete(s)
        for l in session.scalars(select(LunchIdea)).all():
            if l.id not in want_lunch_ids:
                session.delete(l)
        session.flush()

        for s in slots:
            meal = s.get("meal") or {}
            obj = session.get(MealSlot, s["id"]) or MealSlot(id=s["id"])
            obj.date = parse_date(s["date"])
            obj.meal_type = s.get("meal_type", "dinner")
            obj.status = s.get("status", "pending")
            obj.name = meal.get("name")
            obj.description = meal.get("description")
            obj.prep_minutes = meal.get("prep_minutes")
            obj.rejection_reasons = s.get("rejection_reasons", [])
            session.add(obj)
            session.flush()  # ensure PK exists before attaching children
            _sync_ingredients(obj, meal, is_slot=True)

        # Lunch ideas float within a week; derive week_start from the slots when
        # present, else this week's Monday.
        if slots:
            ws = parse_date(slots[0]["date"])
            ws = ws - timedelta(days=ws.weekday())
        else:
            today = datetime.utcnow().date()
            ws = today - timedelta(days=today.weekday())
        for l in lunches:
            meal = {k: v for k, v in l.items()
                    if k not in ("id", "status", "rejection_reasons")}
            obj = session.get(LunchIdea, l["id"]) or LunchIdea(id=l["id"])
            obj.week_start = ws
            obj.status = l.get("status", "generated")
            obj.name = meal.get("name")
            obj.description = meal.get("description")
            obj.prep_minutes = meal.get("prep_minutes")
            obj.rejection_reasons = l.get("rejection_reasons", [])
            session.add(obj)
            session.flush()
            _sync_ingredients(obj, meal, is_slot=False)

        # Self-heal: drop any reservation not backed by an accepted meal and
        # rebuild `planned` from the accepted set (deterministic, no GPT).
        from routes.reservations import heal_orphan_reservations
        heal_orphan_reservations(session)

def _steering_override(key):
    """Return the DB-stored override content for a steering key, or None if the
    user hasn't edited it (so the baked file default is used)."""
    from models import SteeringDoc
    with session_scope() as session:
        row = session.get(SteeringDoc, key)
        return row.content if row and row.content.strip() else None


def load_member_profiles():
    """Per-member steering. A DB override (key 'member:<id>') wins over the
    baked familymembers/<file>.md; otherwise the file is used."""
    from models import Member
    profiles = []
    # DB-overridden members first (keyed by member id).
    overridden_files = set()
    with session_scope() as session:
        members = session.scalars(select(Member)).all()
        member_rows = [(m.id, m.markdown_url) for m in members]
    for mid, md_url in member_rows:
        override = _steering_override(f"member:{mid}")
        if override is not None:
            profiles.append(override)
            if md_url:
                overridden_files.add(os.path.basename(md_url))
    # Then any baked files not overridden.
    for filepath in glob.glob(os.path.join(MEMBERS_DIR, "*.md")):
        if os.path.basename(filepath) in overridden_files:
            continue
        with open(filepath, "r", encoding="utf-8") as f:
            profiles.append(f.read())
    return profiles

def load_meal_planning_rules():
    override = _steering_override("meal_planning")
    if override is not None:
        return override
    if os.path.exists(PROMPT_FILE):
        with open(PROMPT_FILE, "r", encoding="utf-8") as f:
            return f.read()
    return ""

def _slot_for_date(date_obj):
    return {
        "id": str(uuid.uuid4()),
        "day": DAYS[date_obj.weekday()],
        "date": date_obj.strftime("%Y-%m-%d"),
        "display_date": date_obj.strftime("%-d %b"),
        "meal_type": "dinner",
        "status": "pending",
        "meal": None,
        "rejection_reasons": [],
        "calendar_events": [],
    }

def build_slots(week_start=None):
    """Build 7 dinner slots (one per day). Defaults to next Monday's week, or
    the Monday of `week_start` (a date) if given."""
    if week_start is None:
        today = datetime.utcnow().date()
        days_until_monday = (7 - today.weekday()) % 7 or 7
        monday = today + timedelta(days=days_until_monday)
    else:
        monday = week_start - timedelta(days=week_start.weekday())
    return [_slot_for_date(monday + timedelta(days=i)) for i in range(7)]

# ── Google Calendar ───────────────────────────────────────────────────────────

def _parse_event(item):
    """Normalise a Google Calendar event item to our shape."""
    start = item.get("start", {})
    end = item.get("end", {})
    all_day = "date" in start and "dateTime" not in start
    return {
        "id": item.get("id"),
        "summary": item["summary"],
        "description": item.get("description", ""),
        "all_day": all_day,
        "start_time": None if all_day else start.get("dateTime"),
        "end_time": None if all_day else end.get("dateTime"),
        "color_id": item.get("colorId"),  # Google event colour (1–11) or None
        # the date this event belongs to (YYYY-MM-DD), for bucketing
        "_date": start.get("date") or (start.get("dateTime") or "")[:10],
    }

def fetch_calendar_range(start_date_str, num_days):
    """Fetch all events across a date range in ONE request, grouped by date.
    Returns {date_str: [events]}. Much faster than one request per day.
    """
    api_key = os.environ.get("GOOGLE_CALENDAR_API_KEY")
    calendar_id = os.environ.get("GOOGLE_CALENDAR_ID")
    start = datetime.strptime(start_date_str, "%Y-%m-%d")
    buckets = {
        (start + timedelta(days=i)).strftime("%Y-%m-%d"): []
        for i in range(num_days)
    }
    if not api_key or not calendar_id:
        return buckets
    try:
        time_min = f"{start_date_str}T00:00:00Z"
        time_max = (start + timedelta(days=num_days)).strftime("%Y-%m-%d") + "T00:00:00Z"
        resp = http_requests.get(
            f"https://www.googleapis.com/calendar/v3/calendars/{calendar_id}/events",
            params={
                "key": api_key,
                "timeMin": time_min,
                "timeMax": time_max,
                "singleEvents": "true",
                "orderBy": "startTime",
                "fields": "items(id,summary,description,start,end,colorId)",
            },
            timeout=8,
        )
        if resp.status_code == 200:
            for item in resp.json().get("items", []):
                if not item.get("summary"):
                    continue
                ev = _parse_event(item)
                d = ev.pop("_date")
                if d in buckets:
                    buckets[d].append(ev)
    except Exception:
        pass
    return buckets

def fetch_calendar_events(date_str):
    """Fetch Google Calendar events for a given date (YYYY-MM-DD).
    Returns a list of event objects with summary, start, end, all_day fields.
    Requires GOOGLE_CALENDAR_API_KEY and GOOGLE_CALENDAR_ID env vars.
    """
    api_key = os.environ.get("GOOGLE_CALENDAR_API_KEY")
    calendar_id = os.environ.get("GOOGLE_CALENDAR_ID")
    if not api_key or not calendar_id:
        return []
    try:
        time_min = f"{date_str}T00:00:00Z"
        time_max = f"{date_str}T23:59:59Z"
        resp = http_requests.get(
            f"https://www.googleapis.com/calendar/v3/calendars/{calendar_id}/events",
            params={
                "key": api_key,
                "timeMin": time_min,
                "timeMax": time_max,
                "singleEvents": "true",
                "orderBy": "startTime",
                "fields": "items(summary,start,end)",
            },
            timeout=5,
        )
        if resp.status_code == 200:
            items = resp.json().get("items", [])
            events = []
            for item in items:
                if not item.get("summary"):
                    continue
                start = item.get("start", {})
                end = item.get("end", {})
                all_day = "date" in start and "dateTime" not in start
                events.append({
                    "summary": item["summary"],
                    "all_day": all_day,
                    "start_time": None if all_day else start.get("dateTime"),
                    "end_time": None if all_day else end.get("dateTime"),
                })
            return events
    except Exception:
        pass
    return []

# ── Prompt builder ────────────────────────────────────────────────────────────

def _call_openai(prompt, temperature=0.8, timeout=60):
    """Send a prompt to GPT-4o and return the parsed JSON array."""
    response = get_openai_client().chat.completions.create(
        model="gpt-4o",
        messages=[{"role": "user", "content": prompt}],
        temperature=temperature,
        timeout=timeout,
    )
    raw = response.choices[0].message.content.strip()
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
    return json.loads(raw)

def build_dinner_prompt(slots_to_generate):
    profiles = load_member_profiles()
    profile_text = "\n\n---\n\n".join(profiles)
    rules = load_meal_planning_rules()

    slots_text = "\n".join(
        f"- {s['day']} {s['display_date']} Dinner ({s['date']})"
        + (f" | Calendar: {'; '.join(e['summary'] for e in s['calendar_events'])}" if s.get("calendar_events") else "")
        + (f" | Previously rejected: {'; '.join(s['rejection_reasons'])}" if s.get("rejection_reasons") else "")
        for s in slots_to_generate
    )

    return f"""You are a family meal planner. Generate DINNERS for the {family_name()} family.

MEAL PLANNING RULES:
{rules}

FAMILY MEMBER PROFILES:
{profile_text}

DINNERS TO GENERATE:
{slots_text}

Respond with a JSON array. Each item must have these exact fields:
- "day": the day name (e.g. "Monday")
- "date": the date string (e.g. "2024-11-04")
- "meal_type": "dinner"
- "name": meal name
- "description": one sentence description
- "prep_minutes": estimated total prep + cook time as an integer number of minutes
- "ingredients": array of objects with "item" (string) and "quantity" (string using metric units) fields

Return only valid JSON array, no markdown fences, no explanation."""

def build_lunch_prompt(count=3, rejection_reasons=None):
    profiles = load_member_profiles()
    profile_text = "\n\n---\n\n".join(profiles)
    rules = load_meal_planning_rules()
    rejection_note = ""
    if rejection_reasons:
        rejection_note = f"\nPreviously rejected lunch ideas (suggest different ones): {'; '.join(rejection_reasons)}"

    return f"""You are a family meal planner. Generate {count} LUNCH IDEAS for the {family_name()} family.

These are flexible lunch ideas for the week — they are NOT tied to a specific day. The family will pick from them across the week.

MEAL PLANNING RULES:
{rules}

FAMILY MEMBER PROFILES:
{profile_text}
{rejection_note}

Generate {count} varied lunch ideas that are quick and easy (most under 20 minutes).

Respond with a JSON array of exactly {count} items. Each item must have these exact fields:
- "name": lunch name
- "description": one sentence description
- "prep_minutes": estimated total prep + cook time as an integer number of minutes
- "ingredients": array of objects with "item" (string) and "quantity" (string using metric units) fields

Return only valid JSON array, no markdown fences, no explanation."""

# ── Routes ────────────────────────────────────────────────────────────────────

@meals_bp.route("/current", methods=["GET"])
def get_current():
    return jsonify(read_data())


@meals_bp.route("/status", methods=["GET"])
def meal_status():
    """Per-accepted-meal ingredient breakdown for the UI badges + detail.

    For every accepted dinner/lunch, classify each ingredient:
      - in_stock : matched to inventory and reserved/covered from stock
      - on_list  : not in stock, but currently on the Todoist shopping list
      - need     : not in stock and not on any list yet (nothing has it)

    A meal is `makeable` when every ingredient is in_stock. Reuses the
    reservation engine (no extra GPT spend beyond one recompute) and reads the
    live Todoist list once. Query: ?use_gpt=0 to force string matching."""
    from routes.reservations import recompute_reservations
    from routes.shopping import on_list_norms

    use_gpt = request.args.get("use_gpt", "1") != "0"

    with session_scope() as session:
        res = recompute_reservations(session, use_gpt=use_gpt)

        # Build per-meal, per-ingredient state from the reservation result.
        # reserved -> in_stock; unmatched/shortfall -> needs buying.
        reserved_keys = {(r["meal_key"], normalise(r["name"])) for r in res["reserved"]}
        # A level item matched (reserved_qty 0 but linked) also counts in_stock;
        # recompute stores the match on the row, so re-read accepted rows.
        from routes.reservations import accepted_meal_ingredients
        from routes.inventory import in_stock as item_in_stock
        in_stock_rows = set()
        for meal_key, ing in accepted_meal_ingredients(session):
            if ing.inventory_item_id is not None:
                inv = session.get(InventoryItem, ing.inventory_item_id)
                # count item: reserved_qty>0 means a unit is held for this meal.
                # level item: counts only if the item is actually in stock.
                if inv is not None and (
                    (inv.track_mode == "count" and (ing.reserved_qty or 0) > 0)
                    or (inv.track_mode == "level" and item_in_stock(inv))
                ):
                    in_stock_rows.add((meal_key, normalise(ing.item)))

        on_list = on_list_norms()

        # Gather each accepted meal's ingredient list (name order).
        meals = {}
        dinners = session.scalars(select(MealSlot).where(MealSlot.status == "accepted")).all()
        lunches = session.scalars(select(LunchIdea).where(LunchIdea.status == "accepted")).all()

        def classify(meal_key, name):
            key = (meal_key, normalise(name))
            if key in reserved_keys or key in in_stock_rows:
                return "in_stock"
            if normalise(name) in on_list:
                return "on_list"
            return "need"

        for owner in list(dinners) + list(lunches):
            ings = []
            for ing in sorted(owner.ingredients, key=lambda i: i.position):
                if not ing.item:
                    continue
                ings.append({"id": ing.id, "name": ing.item, "quantity": ing.quantity,
                             "state": classify(owner.id, ing.item)})
            makeable = bool(ings) and all(i["state"] == "in_stock" for i in ings)
            meals[owner.id] = {"makeable": makeable, "ingredients": ings}

    return jsonify({"meals": meals})


@meals_bp.route("/generate", methods=["POST"])
def generate():
    data = read_data()
    body = request.get_json(silent=True) or {}
    single_date = body.get("date")  # if set: propose a dinner for just this date

    # Single-day mode: ensure a slot for that date, generate only it, no lunches.
    if single_date:
        date_obj = parse_date(single_date)
        slot = next((s for s in data["slots"] if s["date"] == single_date), None)
        if slot is None:
            slot = _slot_for_date(date_obj)
            data["slots"].append(slot)
        slot["calendar_events"] = fetch_calendar_events(single_date)
        dinners = _call_openai(build_dinner_prompt([slot]))
        if dinners:
            slot["meal"] = dinners[0]
            slot["status"] = "generated"
        write_data(data)
        return jsonify(data)

    # First generation — build the 7 dinner slots
    if not data.get("slots"):
        data["slots"] = build_slots()
        data["generated_at"] = datetime.utcnow().isoformat()

    # Fetch calendar events for each date and attach to slots
    unique_dates = list({s["date"] for s in data["slots"]})
    calendar_map = {date: fetch_calendar_events(date) for date in unique_dates}
    for slot in data["slots"]:
        slot["calendar_events"] = calendar_map.get(slot["date"], [])

    pending = [s for s in data["slots"] if s["status"] == "pending"]

    # Generate dinners for pending slots
    if pending:
        dinners = _call_openai(build_dinner_prompt(pending))
        meal_map = {m["date"]: m for m in dinners}
        for slot in data["slots"]:
            if slot["status"] == "pending" and slot["date"] in meal_map:
                slot["meal"] = meal_map[slot["date"]]
                slot["status"] = "generated"

    # Generate lunch ideas if we don't have any yet
    if not pending and data.get("lunch_ideas"):
        # Nothing pending and lunches already exist
        write_data(data)
        return jsonify(data)

    write_data(data)
    return jsonify(data)

# ── Lunch idea routes ──────────────────────────────────────────────────────────

@meals_bp.route("/lunch/generate", methods=["POST"])
def generate_lunches():
    """Generate lunch ideas for the week, independent of dinners.

    Body: {count?: int} (default 3, clamped 1..10). Accepted lunches are KEPT;
    all non-accepted ones are replaced so the week ends up with `count` fresh
    ideas on top of whatever is already accepted. Rejection reasons already
    gathered steer the new ideas away from past rejects."""
    body = request.get_json(silent=True) or {}
    try:
        count = int(body.get("count", 3))
    except (TypeError, ValueError):
        count = 3
    count = max(1, min(10, count))

    data = read_data()
    kept = [l for l in data.get("lunch_ideas", []) if l.get("status") == "accepted"]
    # Steer away from anything previously rejected.
    prior_reasons = [r for l in data.get("lunch_ideas", [])
                     for r in l.get("rejection_reasons", [])]

    fresh_raw = _call_openai(
        build_lunch_prompt(count=count, rejection_reasons=prior_reasons or None)
    )
    fresh = [
        {
            "id": str(uuid.uuid4()),
            "status": "generated",  # generated | accepted | skipped
            "rejection_reasons": [],
            **idea,
        }
        for idea in fresh_raw
    ]

    data["lunch_ideas"] = kept + fresh
    write_data(data)
    return jsonify(data)


@meals_bp.route("/lunch/<lunch_id>/accept", methods=["POST"])
def accept_lunch(lunch_id):
    data = read_data()
    for idea in data["lunch_ideas"]:
        if idea["id"] == lunch_id:
            idea["status"] = "accepted"
            write_data(data)
            from routes.reservations import meal_draft_lines
            with session_scope() as session:
                draft = meal_draft_lines(session, lunch_id)
            return jsonify({"idea": idea, "draft": draft["draft"],
                            "used_gpt": draft["used_gpt"]})
    return jsonify({"error": "Lunch idea not found"}), 404

@meals_bp.route("/lunch/<lunch_id>/unaccept", methods=["POST"])
def unaccept_lunch(lunch_id):
    """Revert an accepted lunch back to 'generated' (review panel cancelled),
    then reconcile the shopping list."""
    data = read_data()
    for idea in data["lunch_ideas"]:
        if idea["id"] == lunch_id:
            if idea["status"] == "accepted":
                idea["status"] = "generated"
                write_data(data)
                from routes.shopping import reconcile_auto_items
                reconcile_auto_items()
            return jsonify(idea)
    return jsonify({"error": "Lunch idea not found"}), 404

@meals_bp.route("/lunch/<lunch_id>/reject", methods=["POST"])
def reject_lunch(lunch_id):
    data = read_data()
    body = request.get_json() or {}
    reason = body.get("reason", "").strip()

    idea = next((l for l in data["lunch_ideas"] if l["id"] == lunch_id), None)
    if not idea:
        return jsonify({"error": "Lunch idea not found"}), 404

    was_accepted = idea.get("status") == "accepted"
    # Collect all prior rejection reasons across lunch ideas to steer away
    all_reasons = idea.get("rejection_reasons", []) + ([reason] if reason else [])

    replacement = _call_openai(build_lunch_prompt(count=1, rejection_reasons=all_reasons), temperature=0.9)
    if replacement:
        new_idea = {
            "id": lunch_id,  # keep same id/slot
            "status": "generated",
            "rejection_reasons": all_reasons,
            **replacement[0],
        }
        idx = data["lunch_ideas"].index(idea)
        data["lunch_ideas"][idx] = new_idea
        write_data(data)
        # Rejecting an accepted lunch means its items may no longer be needed.
        if was_accepted:
            from routes.shopping import reconcile_auto_items
            reconcile_auto_items()
        return jsonify(new_idea)

    return jsonify({"error": "Could not regenerate"}), 500

# ── Ingredient-level editing (correct a meal's inventory/shopping links) ─────
# All operate on ONE MealIngredient row, then recompute reservations so
# `planned` stays honest, and return the refreshed per-meal status so the UI
# can re-render the ✅/🛒/⚠️ breakdown without a separate round-trip.

def _ingredient_owner_key(ing):
    return ing.slot_id or ing.lunch_id


def _meal_status_for(session, meal_key, *, use_gpt=False):
    """Recompute, then build the one meal's ingredient breakdown (same shape as
    /status) so an edit returns fresh state. Reads the live Todoist list once."""
    from routes.reservations import recompute_reservations, accepted_meal_ingredients
    from routes.shopping import on_list_norms
    from routes.inventory import in_stock as item_in_stock

    res = recompute_reservations(session, use_gpt=use_gpt)
    reserved_keys = {(r["meal_key"], normalise(r["name"])) for r in res["reserved"]}
    in_stock_rows = set()
    for mk, ing in accepted_meal_ingredients(session):
        if ing.inventory_item_id is not None:
            inv = session.get(InventoryItem, ing.inventory_item_id)
            if inv is not None and (
                (inv.track_mode == "count" and (ing.reserved_qty or 0) > 0)
                or (inv.track_mode == "level" and item_in_stock(inv))
            ):
                in_stock_rows.add((mk, normalise(ing.item)))
    on_list = on_list_norms()

    owner = session.get(MealSlot, meal_key) or session.get(LunchIdea, meal_key)
    if owner is None:
        return None

    def classify(name):
        key = (meal_key, normalise(name))
        if key in reserved_keys or key in in_stock_rows:
            return "in_stock"
        if normalise(name) in on_list:
            return "on_list"
        return "need"

    ings = []
    for ing in sorted(owner.ingredients, key=lambda i: i.position):
        if ing.item:
            ings.append({"id": ing.id, "name": ing.item, "quantity": ing.quantity,
                         "state": classify(ing.item)})
    makeable = bool(ings) and all(i["state"] == "in_stock" for i in ings)
    return {"meal_key": meal_key, "makeable": makeable, "ingredients": ings}


@meals_bp.route("/ingredient/<ing_id>/match", methods=["POST"])
def ingredient_match(ing_id):
    """Link an ingredient to an EXISTING inventory item the family has.
    Body: {inventory_item_id}. Recomputes so a count item reserves a unit."""
    body = request.get_json(silent=True) or {}
    inv_id = (body.get("inventory_item_id") or "").strip()
    with session_scope() as session:
        ing = session.get(MealIngredient, ing_id)
        if ing is None:
            return jsonify({"error": "ingredient not found"}), 404
        if not session.get(InventoryItem, inv_id):
            return jsonify({"error": "inventory item not found"}), 404
        ing.inventory_item_id = inv_id
        ing.reserved_qty = 0  # recompute will set the real reservation
        ing.match_locked = True
        session.flush()
        meal_key = _ingredient_owner_key(ing)
        status = _meal_status_for(session, meal_key)
    return jsonify({"ok": True, "status": status})


@meals_bp.route("/ingredient/<ing_id>/unmatch", methods=["POST"])
def ingredient_unmatch(ing_id):
    """Clear a wrong inventory match — the ingredient becomes 'needed'."""
    with session_scope() as session:
        ing = session.get(MealIngredient, ing_id)
        if ing is None:
            return jsonify({"error": "ingredient not found"}), 404
        ing.inventory_item_id = None
        ing.reserved_qty = 0
        ing.match_locked = True
        session.flush()
        meal_key = _ingredient_owner_key(ing)
        status = _meal_status_for(session, meal_key)
    return jsonify({"ok": True, "status": status})


@meals_bp.route("/ingredient/<ing_id>/add-to-inventory", methods=["POST"])
def ingredient_add_to_inventory(ing_id):
    """The family HAS this but it wasn't tracked — create the inventory item
    (or fold into an existing same-name one), link it, recompute.
    Body: {location?, track_mode?, count?}."""
    from routes.inventory import restock_or_add, LOCATIONS, TRACK_MODES
    body = request.get_json(silent=True) or {}
    location = (body.get("location") or "pantry").strip()
    if location not in LOCATIONS:
        return jsonify({"error": f"invalid location '{location}'"}), 400
    track_mode = (body.get("track_mode") or "count").strip()
    if track_mode not in TRACK_MODES:
        return jsonify({"error": f"invalid track_mode '{track_mode}'"}), 400
    try:
        count = max(1, int(body.get("count", 1)))
    except (TypeError, ValueError):
        return jsonify({"error": "count must be an integer"}), 400
    with session_scope() as session:
        ing = session.get(MealIngredient, ing_id)
        if ing is None:
            return jsonify({"error": "ingredient not found"}), 404
        item, _action = restock_or_add(session, ing.item, location,
                                       track_mode=track_mode, count=count)
        ing.inventory_item_id = item.id
        ing.reserved_qty = 0
        ing.match_locked = True
        session.flush()
        meal_key = _ingredient_owner_key(ing)
        status = _meal_status_for(session, meal_key)
    return jsonify({"ok": True, "status": status})


@meals_bp.route("/ingredient/<ing_id>/consume", methods=["POST"])
def ingredient_consume(ing_id):
    """The family used this item outside a meal: decrement the matched count
    item by `qty` (default 1) and release that many reservations, then
    recompute. Body: {qty?}. Only meaningful for a matched count item."""
    body = request.get_json(silent=True) or {}
    try:
        qty = max(1, int(body.get("qty", 1)))
    except (TypeError, ValueError):
        qty = 1
    with session_scope() as session:
        ing = session.get(MealIngredient, ing_id)
        if ing is None:
            return jsonify({"error": "ingredient not found"}), 404
        inv = session.get(InventoryItem, ing.inventory_item_id) if ing.inventory_item_id else None
        if inv is None or inv.track_mode != "count":
            return jsonify({"error": "not a matched count item"}), 400
        inv.count = max(0, (inv.count or 0) - qty)
        inv.planned = max(0, (inv.planned or 0) - qty)
        if inv.planned > inv.count:
            inv.planned = inv.count
        session.flush()
        meal_key = _ingredient_owner_key(ing)
        status = _meal_status_for(session, meal_key)
    return jsonify({"ok": True, "consumed": qty, "remaining": inv.count, "status": status})


@meals_bp.route("/ingredient/<ing_id>/to-shopping", methods=["POST"])
def ingredient_to_shopping(ing_id):
    """Put this one ingredient on the Todoist shopping list now (auto item).
    Skips if it's already on the list (manual or auto)."""
    from routes.shopping import _headers, _get_or_create_project, AUTO_LABEL, TODOIST
    from models import ShoppingItem
    headers = _headers()
    if not headers:
        return jsonify({"error": "TODOIST_API_TOKEN not set"}), 500
    with session_scope() as session:
        ing = session.get(MealIngredient, ing_id)
        if ing is None:
            return jsonify({"error": "ingredient not found"}), 404
        name, quantity = ing.item, ing.quantity
        norm = normalise(name)
        already = session.scalars(select(ShoppingItem).where(ShoppingItem.norm == norm)).first()
        meal_key = _ingredient_owner_key(ing)
        if already is None:
            project_id = _get_or_create_project(headers)
            content = f"{name} — {quantity}".strip(" —")
            r = http_requests.post(
                f"{TODOIST}/tasks", headers=headers,
                json={"content": content, "project_id": project_id, "labels": [AUTO_LABEL]},
                timeout=10)
            r.raise_for_status()
            session.add(ShoppingItem(id=str(uuid.uuid4()), name=name, norm=norm,
                                     quantity=quantity or "", source="auto",
                                     todoist_id=r.json()["id"]))
        status = _meal_status_for(session, meal_key)
    return jsonify({"ok": True, "status": status})


@meals_bp.route("/<slot_id>/accept", methods=["POST"])
def accept(slot_id):
    data = read_data()
    for slot in data["slots"]:
        if slot["id"] == slot_id:
            slot["status"] = "accepted"
            write_data(data)
            from routes.reservations import meal_draft_lines
            with session_scope() as session:
                draft = meal_draft_lines(session, slot_id)
            return jsonify({"slot": slot, "draft": draft["draft"],
                            "used_gpt": draft["used_gpt"]})
    return jsonify({"error": "Slot not found"}), 404

@meals_bp.route("/<slot_id>/unaccept", methods=["POST"])
def unaccept(slot_id):
    """Revert an accepted dinner back to 'generated' (the user cancelled the
    shopping-review panel). Reconcile so any items this meal added are pulled
    back off the list unless another accepted meal still needs them."""
    data = read_data()
    for slot in data["slots"]:
        if slot["id"] == slot_id:
            if slot["status"] == "accepted":
                slot["status"] = "generated"
                write_data(data)
                from routes.shopping import reconcile_auto_items
                reconcile_auto_items()
            return jsonify(slot)
    return jsonify({"error": "Slot not found"}), 404

@meals_bp.route("/<slot_id>/cooked", methods=["POST"])
def cooked(slot_id):
    """Mark an accepted dinner cooked: consume its reservations (count -= planned
    for each reserved item), then set the slot status to 'cooked'."""
    from routes.reservations import consume_meal
    with session_scope() as session:
        consumed = consume_meal(session, slot_id)
    data = read_data()
    for slot in data["slots"]:
        if slot["id"] == slot_id:
            slot["status"] = "cooked"
            write_data(data)
            return jsonify({"ok": True, "slot": slot, "consumed": consumed})
    return jsonify({"error": "Slot not found"}), 404


@meals_bp.route("/<slot_id>/skip", methods=["POST"])
def skip(slot_id):
    data = read_data()
    for slot in data["slots"]:
        if slot["id"] == slot_id:
            was_accepted = slot["status"] == "accepted"
            slot["status"] = "skipped"
            slot["meal"] = None
            write_data(data)
            # If a previously-accepted meal is skipped, pull its now-unneeded
            # items off the shopping list (reconcile keeps ones still needed).
            if was_accepted:
                from routes.shopping import reconcile_auto_items
                reconcile_auto_items()
            return jsonify(slot)
    return jsonify({"error": "Slot not found"}), 404

@meals_bp.route("/<slot_id>/reject", methods=["POST"])
def reject(slot_id):
    data = read_data()
    body = request.get_json()
    reason = body.get("reason", "").strip()

    slot = next((s for s in data["slots"] if s["id"] == slot_id), None)
    if not slot:
        return jsonify({"error": "Slot not found"}), 404

    was_accepted = slot["status"] == "accepted"
    slot["rejection_reasons"].append(reason)
    slot["status"] = "pending"
    slot["meal"] = None

    # Regenerate just this one dinner slot
    meals = _call_openai(build_dinner_prompt([slot]), temperature=0.9, timeout=30)
    if meals:
        slot["meal"] = meals[0]
        slot["status"] = "generated"

    write_data(data)
    # Rejecting an accepted meal means its items may no longer be needed.
    if was_accepted:
        from routes.shopping import reconcile_auto_items
        reconcile_auto_items()
    return jsonify(slot)

@meals_bp.route("/calendar-test", methods=["GET"])
def calendar_test():
    date = request.args.get("date", datetime.utcnow().strftime("%Y-%m-%d"))
    events = fetch_calendar_events(date)
    return jsonify({"date": date, "events": events, "api_key_set": bool(os.environ.get("GOOGLE_CALENDAR_API_KEY")), "calendar_id_set": bool(os.environ.get("GOOGLE_CALENDAR_ID"))})

@meals_bp.route("/reset", methods=["POST"])
def reset():
    write_data({"slots": [], "lunch_ideas": [], "generated_at": None})
    return jsonify({"ok": True})

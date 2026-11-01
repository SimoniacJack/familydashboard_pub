"""Ingredient -> inventory matching and meal reservation engine.

The 'push to shopping list' flow:
  1. gather ingredients from accepted meals (the ones 'on the calendar'),
  2. match each to an inventory line (batched GPT call, string fallback),
  3. recompute reservations from scratch (idempotent, never double-reserves),
  4. anything unmatched or short of stock becomes a DRAFT shopping line,
  5. the UI shows the draft; the user confirms before anything hits Todoist.

Matching is only ever a SUGGESTION. The draft review is the human gate, so a
wrong or missing match is corrected there, never silently acted on.
"""
import json
import os

from openai import OpenAI
from sqlalchemy import select

from models import InventoryItem, MealIngredient, MealSlot, LunchIdea
from routes.inventory import normalise, available


# ── Matching ───────────────────────────────────────────────────────────────

def string_match(ing_name, items):
    """Deterministic fallback: normalised exact, then substring either way.
    Returns an InventoryItem or None."""
    n = normalise(ing_name)
    if not n:
        return None
    by_norm = {normalise(i.name): i for i in items}
    if n in by_norm:
        return by_norm[n]
    # substring both directions (recipe 'tomatoes' vs 'chopped tomatoes')
    for i in items:
        inm = normalise(i.name)
        if n in inm or inm in n:
            return i
    return None


def _gpt_match(ingredient_names, items, *, client=None, model="gpt-4o", timeout=30):
    """Batched GPT match: one call maps every ingredient to an inventory id or
    null. Returns {ingredient_name: item_id|None}. Raises on any failure so the
    caller can fall back to string matching.

    GPT may ONLY return ids from the provided list; the caller validates every
    returned id against real inventory before trusting it.
    """
    inv_lines = "\n".join(f'{i.id}\t{i.name}' for i in items)
    ing_lines = "\n".join(f"- {n}" for n in ingredient_names)
    prompt = (
        "You match recipe ingredients to pantry inventory items.\n"
        "Return ONLY a JSON object mapping each ingredient (verbatim) to the id "
        "of the single best matching inventory item, or null if none is a "
        "genuine match. Use ONLY ids from the inventory list. Do not invent ids.\n\n"
        f"INVENTORY (id<TAB>name):\n{inv_lines}\n\n"
        f"INGREDIENTS:\n{ing_lines}\n\n"
        'Respond with JSON only, e.g. {"chopped tomatoes": "abc-123", "saffron": null}.'
    )
    client = client or OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))
    resp = client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        temperature=0,
        timeout=timeout,
        response_format={"type": "json_object"},
    )
    raw = resp.choices[0].message.content.strip()
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
    return json.loads(raw)


def match_ingredients(ingredient_names, items, *, use_gpt=True, client=None):
    """Map each ingredient name to an InventoryItem or None.

    Tries one batched GPT call; on ANY failure (no key, network, bad JSON,
    unknown id) falls back to deterministic string matching PER ingredient.
    Returns ({ingredient_name: item|None}, used_gpt: bool).
    """
    items = list(items)
    valid_ids = {i.id: i for i in items}
    result = {}
    used_gpt = False

    # Use GPT when asked and we have either an injected client (tests) or a key.
    have_key = bool(os.environ.get("OPENAI_API_KEY") or os.environ.get("OPENAI_API_TOKEN"))
    if use_gpt and items and ingredient_names and (client is not None or have_key):
        try:
            raw = _gpt_match(ingredient_names, items, client=client)
            used_gpt = True
            for name in ingredient_names:
                item_id = raw.get(name)
                # validate: must be a real inventory id, else fall back for this one
                if item_id in valid_ids:
                    result[name] = valid_ids[item_id]
                else:
                    result[name] = string_match(name, items)
            return result, used_gpt
        except Exception:
            used_gpt = False  # fall through to string matching

    for name in ingredient_names:
        result[name] = string_match(name, items)
    return result, used_gpt


# ── Accepted-meal ingredient gathering ──────────────────────────────────────

def accepted_meal_ingredients(session):
    """The MealIngredient rows of accepted meals ('on the calendar'), each
    paired with its owning meal id. Returns [(meal_key, MealIngredient)]."""
    pairs = []
    dinners = session.scalars(
        select(MealSlot).where(MealSlot.status == "accepted")
    ).all()
    lunches = session.scalars(
        select(LunchIdea).where(LunchIdea.status == "accepted")
    ).all()
    for s in dinners:
        for ing in s.ingredients:
            if ing.item:
                pairs.append((s.id, ing))
    for l in lunches:
        for ing in l.ingredients:
            if ing.item:
                pairs.append((l.id, ing))
    return pairs


# ── Reservation recompute (idempotent) ───────────────────────────────────────

def recompute_reservations(session, *, use_gpt=True, client=None, per_unit=1):
    """Rebuild ALL reservations from the currently-accepted meals.

    Reservations now live ON the ingredient rows (reserved_qty +
    inventory_item_id); `InventoryItem.planned` is their SUM per item. This is
    idempotent and the only writer of those fields: it clears the match +
    reserved_qty on EVERY ingredient row, then re-reserves for each accepted
    meal's count-matched ingredient, capped at available stock. A meal no longer
    accepted keeps no reservation (its rows are cleared and never re-reserved).
    A count item is reserved by at most the units it physically has, and never
    double-reserved because the per-item tally is rebuilt from zero each run.

    Returns a dict:
      {
        "reserved":  [{meal_key, item_id, name, qty}],
        "shortfalls": [{meal_key, item (name), have, needed}],
        "unmatched": [{meal_key, item (name), quantity}],
        "used_gpt": bool,
      }
    """
    items = session.scalars(select(InventoryItem)).all()
    count_items = [i for i in items if i.track_mode == "count"]

    # 1. Clear every ingredient's reservation + match, and reset planned to 0.
    for _mk, ing in accepted_meal_ingredients(session):
        ing.reserved_qty = 0
        ing.inventory_item_id = None
    # also clear any reservations left on non-accepted meals' rows
    for ing in session.scalars(select(MealIngredient)).all():
        ing.reserved_qty = 0
        ing.inventory_item_id = None
    for i in count_items:
        i.planned = 0
    session.flush()

    pairs = accepted_meal_ingredients(session)
    if not pairs:
        return {"reserved": [], "shortfalls": [], "unmatched": [], "used_gpt": False}

    # 2. Match ingredient names -> inventory items (batched, dedup names).
    unique_names = list({ing.item for _mk, ing in pairs})
    matches, used_gpt = match_ingredients(unique_names, items, use_gpt=use_gpt, client=client)

    reserved, shortfalls, unmatched = [], [], []
    # live available tracker so two meals cannot claim the same unit
    remaining = {i.id: available(i) for i in count_items}
    planned_tally = {i.id: 0 for i in count_items}

    for meal_key, ing in pairs:
        name = ing.item
        match = matches.get(name)
        if match is None:
            unmatched.append({"meal_key": meal_key, "item": name,
                              "quantity": ing.quantity})
            continue
        if match.track_mode != "count":
            # level item: store the match (so the UI knows it's accounted for)
            # but reserve no units — level has no discrete quantity maths.
            ing.inventory_item_id = match.id
            ing.reserved_qty = 0
            continue
        want = per_unit
        have = remaining.get(match.id, 0)
        take = min(want, have)
        # Persist the match + reserved units onto the ingredient row itself.
        ing.inventory_item_id = match.id
        ing.reserved_qty = take
        if take > 0:
            remaining[match.id] = have - take
            planned_tally[match.id] += take
            reserved.append({"meal_key": meal_key, "item_id": match.id,
                             "name": match.name, "qty": take})
        if take < want:
            shortfalls.append({"meal_key": meal_key, "item": name,
                               "have": take, "needed": want})

    # 3. Derive planned from the per-item tally (single source of truth).
    for i in count_items:
        i.planned = planned_tally.get(i.id, 0)

    session.flush()
    return {"reserved": reserved, "shortfalls": shortfalls,
            "unmatched": unmatched, "used_gpt": used_gpt}


def consume_meal(session, meal_key):
    """Mark a meal cooked: for each of its reserved ingredient lines, subtract
    the reserved qty from the item's physical count AND its planned, then clear
    the line's reservation. Returns [{item_id, name, used, remaining}]."""
    rows = session.scalars(
        select(MealIngredient).where(
            ((MealIngredient.slot_id == meal_key) | (MealIngredient.lunch_id == meal_key))
            & (MealIngredient.reserved_qty > 0)
            & (MealIngredient.inventory_item_id.is_not(None))
        )
    ).all()
    consumed = []
    for row in rows:
        item = session.get(InventoryItem, row.inventory_item_id)
        if item is not None:
            item.count = max(0, (item.count or 0) - row.reserved_qty)
            item.planned = max(0, (item.planned or 0) - row.reserved_qty)
            if item.planned > item.count:
                item.planned = item.count
            consumed.append({"item_id": item.id, "name": item.name,
                             "used": row.reserved_qty, "remaining": item.count})
        row.reserved_qty = 0
    session.flush()
    return consumed

"""Tests for the meal-reservation engine (count/level inventory).

In-memory SQLite, GPT matcher MONKEYPATCHED to a deterministic stub (no spend).
The real GPT schema is checked separately as an integration step before deploy.
Run from backend/:  pytest tests/
"""
import os
import sys
import uuid

os.environ["DATABASE_URL"] = "sqlite+pysqlite:///:memory:"
os.environ["TODOIST_API_TOKEN"] = "test-token"

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

import pytest  # noqa: E402
import db as dbmod  # noqa: E402
import models  # noqa: E402
from models import InventoryItem, MealSlot, MealIngredient  # noqa: E402
import routes.reservations as resv  # noqa: E402
from app import app as flask_app  # noqa: E402


@pytest.fixture()
def ctx(monkeypatch):
    models.Base.metadata.drop_all(dbmod.engine)
    models.Base.metadata.create_all(dbmod.engine)
    # Force string matching in the engine (deterministic, no GPT) unless a test
    # explicitly passes a stub client.
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_TOKEN", raising=False)
    flask_app.config.update(TESTING=True)
    c = flask_app.test_client()
    with c.session_transaction() as sess:
        sess["authed"] = True
    yield c


def _inv(session, name, count=1, mode="count"):
    it = InventoryItem(id=str(uuid.uuid4()), name=name, location="pantry",
                       track_mode=mode, count=count, planned=0, level="full")
    session.add(it)
    session.flush()
    return it.id


def _meal(session, key, ingredients, status="accepted"):
    slot = MealSlot(
        id=key, date=__import__("datetime").date(2026, 11, 2),
        meal_type="dinner", status=status, name="Test",
    )
    session.add(slot)
    session.flush()
    for pos, ing in enumerate(ingredients):
        session.add(MealIngredient(
            id=str(uuid.uuid4()), slot_id=key,
            item=ing["item"], quantity=ing.get("quantity", ""), position=pos,
        ))
    session.flush()


def _reserved_rows(session):
    """How many ingredient lines currently hold a reservation."""
    return session.query(MealIngredient).filter(
        MealIngredient.reserved_qty > 0).count()


def test_available_is_count_minus_planned(ctx):
    with dbmod.session_scope() as s:
        iid = _inv(s, "Chopped Tomatoes", count=3)
        it = s.get(InventoryItem, iid)
        it.planned = 1
        s.flush()
        assert resv.available(it) == 2


def test_recompute_reserves_matched_count_item(ctx):
    with dbmod.session_scope() as s:
        iid = _inv(s, "Chopped Tomatoes", count=3)
        _meal(s, "m1", [{"item": "chopped tomatoes", "quantity": "1 tin"}])
        res = resv.recompute_reservations(s, use_gpt=False)
        it = s.get(InventoryItem, iid)
        assert it.planned == 1
        assert resv.available(it) == 2
        assert len(res["reserved"]) == 1


def test_no_double_reserve_across_two_meals(ctx):
    with dbmod.session_scope() as s:
        iid = _inv(s, "Chopped Tomatoes", count=3)
        _meal(s, "m1", [{"item": "chopped tomatoes", "quantity": "1 tin"}])
        _meal(s, "m2", [{"item": "chopped tomatoes", "quantity": "1 tin"}])
        _meal(s, "m3", [{"item": "chopped tomatoes", "quantity": "1 tin"}])
        _meal(s, "m4", [{"item": "chopped tomatoes", "quantity": "1 tin"}])
        res = resv.recompute_reservations(s, use_gpt=False)
        it = s.get(InventoryItem, iid)
        # Only 3 physical cans -> planned capped at 3, never 4.
        assert it.planned == 3
        assert resv.available(it) == 0
        # The 4th meal is a shortfall (needed 1, had 0 left).
        assert any(sf["needed"] == 1 and sf["have"] == 0 for sf in res["shortfalls"])


def test_recompute_is_idempotent(ctx):
    with dbmod.session_scope() as s:
        iid = _inv(s, "Chopped Tomatoes", count=3)
        _meal(s, "m1", [{"item": "chopped tomatoes", "quantity": "1 tin"}])
        resv.recompute_reservations(s, use_gpt=False)
        resv.recompute_reservations(s, use_gpt=False)
        resv.recompute_reservations(s, use_gpt=False)
        it = s.get(InventoryItem, iid)
        assert it.planned == 1  # not 3 — rebuilt from scratch each time


def test_unaccepted_meal_releases_reservation(ctx):
    with dbmod.session_scope() as s:
        iid = _inv(s, "Chopped Tomatoes", count=3)
        _meal(s, "m1", [{"item": "chopped tomatoes", "quantity": "1 tin"}])
        resv.recompute_reservations(s, use_gpt=False)
        assert s.get(InventoryItem, iid).planned == 1
        # Meal skipped -> no longer accepted -> reservation released.
        s.get(MealSlot, "m1").status = "skipped"
        s.flush()
        resv.recompute_reservations(s, use_gpt=False)
        it = s.get(InventoryItem, iid)
        assert it.planned == 0
        assert _reserved_rows(s) == 0


def test_unmatched_ingredient_is_reported(ctx):
    with dbmod.session_scope() as s:
        _inv(s, "Chopped Tomatoes", count=3)
        _meal(s, "m1", [{"item": "saffron threads", "quantity": "a pinch"}])
        res = resv.recompute_reservations(s, use_gpt=False)
        assert any(u["item"] == "saffron threads" for u in res["unmatched"])


def test_cook_consumes_count_and_planned(ctx):
    with dbmod.session_scope() as s:
        iid = _inv(s, "Chopped Tomatoes", count=3)
        _meal(s, "m1", [{"item": "chopped tomatoes", "quantity": "1 tin"}])
        resv.recompute_reservations(s, use_gpt=False)
        it = s.get(InventoryItem, iid)
        assert it.count == 3 and it.planned == 1
        consumed = resv.consume_meal(s, "m1")
        it = s.get(InventoryItem, iid)
        assert it.count == 2 and it.planned == 0  # one can gone, reservation cleared
        assert consumed[0]["used"] == 1 and consumed[0]["remaining"] == 2
        assert _reserved_rows(s) == 0


def test_gpt_matcher_used_when_stub_client_given(ctx):
    # Stub GPT client returns a mapping; engine should trust validated ids.
    with dbmod.session_scope() as s:
        iid = _inv(s, "Cirio Chopped Tomatoes", count=2)

        class _StubClient:
            class chat:
                class completions:
                    @staticmethod
                    def create(**kw):
                        class _Msg:  # noqa
                            content = '{"tinned tomatoes": "%s"}' % iid
                        class _Choice:  # noqa
                            message = _Msg()
                        class _Resp:  # noqa
                            choices = [_Choice()]
                        return _Resp()

        matches, used = resv.match_ingredients(
            ["tinned tomatoes"],
            list(s.query(InventoryItem)),
            use_gpt=True, client=_StubClient(),
        )
        # GPT matched the fuzzy name to the real item the string matcher would miss.
        assert matches["tinned tomatoes"] is not None
        assert matches["tinned tomatoes"].id == iid
        assert used is True


def test_cascade_delete_removes_ingredients(ctx):
    # Deleting a meal must delete its ingredient rows (FK cascade), so no orphan
    # reservation can survive — the core fix of the redesign.
    with dbmod.session_scope() as s:
        _inv(s, "Chopped Tomatoes", count=3)
        _meal(s, "m1", [{"item": "chopped tomatoes", "quantity": "1 tin"}])
        resv.recompute_reservations(s, use_gpt=False)
        assert s.query(MealIngredient).count() == 1
        s.delete(s.get(MealSlot, "m1"))
        s.flush()
        assert s.query(MealIngredient).count() == 0


def test_stored_match_persists_across_write_data_edit(ctx):
    # Regression for the churn bug: editing a meal via write_data must NOT lose
    # the stored inventory match / reserved_qty for an unchanged ingredient line.
    import routes.meals as meals
    with dbmod.session_scope() as s:
        iid = _inv(s, "Chopped Tomatoes", count=3)
        _meal(s, "m1", [{"item": "chopped tomatoes", "quantity": "1 tin"}])
        resv.recompute_reservations(s, use_gpt=False)
        row = s.query(MealIngredient).filter_by(slot_id="m1").first()
        assert row.inventory_item_id == iid and row.reserved_qty == 1

    # Simulate a meal edit that keeps the same ingredient line but changes status.
    meals.write_data({
        "slots": [{
            "id": "m1", "date": "2026-11-02", "meal_type": "dinner",
            "status": "accepted",
            "meal": {"name": "Test edited",
                     "ingredients": [{"item": "chopped tomatoes", "quantity": "1 tin"}]},
            "rejection_reasons": [],
        }],
        "lunch_ideas": [],
    })

    with dbmod.session_scope() as s:
        row = s.query(MealIngredient).filter_by(slot_id="m1").first()
        # The stored match + reservation survived the write_data round-trip.
        assert row.inventory_item_id == iid
        assert row.reserved_qty == 1
        assert s.get(MealSlot, "m1").name == "Test edited"


def test_level_match_stored_without_reserving_units(ctx):
    with dbmod.session_scope() as s:
        _inv(s, "Basmati Rice", count=1, mode="level")
        _meal(s, "m1", [{"item": "basmati rice", "quantity": "200g"}])
        resv.recompute_reservations(s, use_gpt=False)
        row = s.query(MealIngredient).filter_by(slot_id="m1").first()
        # level item: match stored, but no discrete units reserved.
        assert row.inventory_item_id is not None
        assert row.reserved_qty == 0


# ── Orphaned-reservation bug: reject/regenerate must not strand `planned` ────

def test_reject_accepted_meal_clears_planned(ctx):
    import routes.meals as meals
    with dbmod.session_scope() as s:
        iid = _inv(s, "Chopped Tomatoes", count=2, mode="count")
        _meal(s, "m1", [{"item": "chopped tomatoes", "quantity": "1 tin"}], status="accepted")
        resv.recompute_reservations(s, use_gpt=False)
        assert s.get(InventoryItem, iid).planned == 1  # reserved by the accepted meal

    # Reject the meal: write_data with status flipped to 'generated'.
    meals.write_data({
        "slots": [{
            "id": "m1", "date": "2026-11-02", "meal_type": "dinner",
            "status": "generated",
            "meal": {"name": "Test", "ingredients": [{"item": "chopped tomatoes", "quantity": "1 tin"}]},
            "rejection_reasons": [],
        }],
        "lunch_ideas": [],
    })

    with dbmod.session_scope() as s:
        # No accepted meal now -> planned back to 0, no stranded reservation.
        assert s.get(InventoryItem, iid).planned == 0
        assert _reserved_rows(s) == 0


def test_heal_zeroes_level_item_and_unmatched_reservation(ctx):
    with dbmod.session_scope() as s:
        # A level item wrongly carrying planned, and an accepted meal row with a
        # reserved_qty but no inventory link — both must be healed to 0.
        lvl = InventoryItem(id="lvl1", name="Butter", location="pantry",
                            track_mode="level", count=2, planned=1, level="full")
        s.add(lvl)
        _meal(s, "m1", [{"item": "baking potatoes", "quantity": "4"}], status="accepted")
        s.flush()
        row = s.query(MealIngredient).filter_by(slot_id="m1").first()
        row.reserved_qty = 1  # reserved against nothing
        row.inventory_item_id = None
        s.flush()

        resv.heal_orphan_reservations(s)

        assert s.get(InventoryItem, "lvl1").planned == 0  # level never planned
        assert _reserved_rows(s) == 0  # the item-less reservation cleared


# ── Ingredient-level editing (backlog #2) ───────────────────────────────────

def test_ingredient_match_then_unmatch(ctx):
    with dbmod.session_scope() as s:
        iid = _inv(s, "Chopped Tomatoes", count=2, mode="count")
        _meal(s, "m1", [{"item": "chopped tomatoes", "quantity": "1 tin"}], status="accepted")
        ing_id = s.query(MealIngredient).filter_by(slot_id="m1").first().id

    # Match -> count item reserves a unit; the lock makes it survive recompute.
    r = ctx.post(f"/api/meals/ingredient/{ing_id}/match",
                 json={"inventory_item_id": iid})
    assert r.status_code == 200
    assert r.get_json()["status"]["ingredients"][0]["state"] == "in_stock"
    with dbmod.session_scope() as s:
        assert s.get(InventoryItem, iid).planned == 1

    # Unmatch -> becomes needed, planned released, and the lock stops recompute
    # re-linking it even though the names string-match.
    r = ctx.post(f"/api/meals/ingredient/{ing_id}/unmatch")
    assert r.status_code == 200
    assert r.get_json()["status"]["ingredients"][0]["state"] in ("need", "on_list")
    with dbmod.session_scope() as s:
        assert s.get(InventoryItem, iid).planned == 0


def test_ingredient_consume_decrements_by_qty(ctx):
    with dbmod.session_scope() as s:
        iid = _inv(s, "Eggs", count=12, mode="count")
        _meal(s, "m1", [{"item": "eggs", "quantity": "2"}], status="accepted")
        ing_id = s.query(MealIngredient).filter_by(slot_id="m1").first().id
    ctx.post(f"/api/meals/ingredient/{ing_id}/match", json={"inventory_item_id": iid})

    # Consume 3 outside a meal.
    r = ctx.post(f"/api/meals/ingredient/{ing_id}/consume", json={"qty": 3})
    assert r.status_code == 200
    body = r.get_json()
    assert body["consumed"] == 3
    with dbmod.session_scope() as s:
        assert s.get(InventoryItem, iid).count == 9


def test_ingredient_add_to_inventory_creates_and_links(ctx):
    with dbmod.session_scope() as s:
        _meal(s, "m1", [{"item": "pine nuts", "quantity": "50g"}], status="accepted")
        ing_id = s.query(MealIngredient).filter_by(slot_id="m1").first().id

    r = ctx.post(f"/api/meals/ingredient/{ing_id}/add-to-inventory",
                 json={"location": "pantry", "track_mode": "count", "count": 1})
    assert r.status_code == 200
    with dbmod.session_scope() as s:
        row = s.query(MealIngredient).filter_by(slot_id="m1").first()
        assert row.inventory_item_id is not None
        inv = s.get(InventoryItem, row.inventory_item_id)
        assert inv.name == "pine nuts"

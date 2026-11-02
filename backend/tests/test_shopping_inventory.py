"""Tests for the shopping -> inventory flow.

Uses an in-memory SQLite DB and a stubbed Todoist HTTP layer, so no live API
token or Postgres is needed. Run from backend/:  pytest tests/
"""
import os
import sys

# Point the app at a throwaway SQLite DB BEFORE importing anything that binds
# the engine at import time.
os.environ["DATABASE_URL"] = "sqlite+pysqlite:///:memory:"
os.environ["TODOIST_API_TOKEN"] = "test-token"

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))  # backend/ on path

import pytest  # noqa: E402
import db as dbmod  # noqa: E402
import models  # noqa: E402
import routes.shopping as shopping  # noqa: E402
from app import app as flask_app  # noqa: E402


@pytest.fixture()
def client(monkeypatch):
    # Fresh schema on the in-memory engine.
    models.Base.metadata.drop_all(dbmod.engine)
    models.Base.metadata.create_all(dbmod.engine)

    # Stub Todoist: project lookup, task close, and completed-tasks poll.
    monkeypatch.setattr(shopping, "_get_or_create_project", lambda h: "proj-1")
    monkeypatch.setattr(shopping, "_tasks_in_project", lambda h, p: [
        {"id": "t1", "content": "Milk", "labels": ["auto"]},
        {"id": "t2", "content": "Bread", "labels": []},
    ])

    class _Resp:
        def raise_for_status(self): pass
        def json(self): return {}

    monkeypatch.setattr(shopping.http_requests, "post", lambda *a, **k: _Resp())
    # Completed poll returns one item bought "in Google Home".
    monkeypatch.setattr(shopping, "_completed_tasks",
                        lambda h, p, since: [{"id": "t9", "content": "Eggs"}])

    flask_app.config.update(TESTING=True)
    with flask_app.test_client() as c:
        # The app now gates /api/* behind a session (cookie auth). Mark the test
        # client authed so these endpoint tests exercise the routes, not the gate.
        with c.session_transaction() as sess:
            sess["authed"] = True
        yield c


def test_active_list_reads_todoist(client):
    r = client.get("/api/shopping/active")
    assert r.status_code == 200
    names = sorted(i["content"] for i in r.get_json()["items"])
    assert names == ["Bread", "Milk"]


def test_complete_then_file_to_inventory(client):
    # Complete an item (closes in Todoist), then file it with a location.
    r = client.post("/api/shopping/complete", json={"todoist_id": "t1", "content": "Milk"})
    assert r.status_code == 200
    assert r.get_json()["name"] == "Milk"

    r = client.post("/api/shopping/file-to-inventory",
                    json={"todoist_id": "t1", "name": "Milk", "location": "fridge_inside"})
    assert r.status_code == 201
    item = r.get_json()["item"]
    assert item["location"] == "fridge_inside"

    # It now appears in inventory.
    inv = client.get("/api/inventory/").get_json()
    assert any(i["name"] == "Milk" for i in inv["items"]["fridge_inside"])


def test_file_rejects_bad_location(client):
    r = client.post("/api/shopping/file-to-inventory",
                    json={"name": "Milk", "location": "garage"})
    assert r.status_code == 400


def test_completed_unfiled_hides_handled_items(client):
    # Initially the Google-Home-completed item is offered.
    r = client.get("/api/shopping/completed-unfiled")
    assert [i["content"] for i in r.get_json()["items"]] == ["Eggs"]

    # File it → it disappears from the unfiled list.
    client.post("/api/shopping/file-to-inventory",
                json={"todoist_id": "t9", "name": "Eggs", "location": "pantry"})
    r = client.get("/api/shopping/completed-unfiled")
    assert r.get_json()["items"] == []


def test_dismiss_completed_hides_item(client):
    client.post("/api/shopping/dismiss-completed", json={"todoist_id": "t9", "content": "Eggs"})
    r = client.get("/api/shopping/completed-unfiled")
    assert r.get_json()["items"] == []


# ── Quantity levels ───────────────────────────────────────────────────────

def _add_inv(client, name, location="fridge_inside", track_mode="level",
             restock="", count=1):
    r = client.post("/api/inventory/", json={
        "name": name, "location": location, "track_mode": track_mode,
        "restock": restock, "count": count,
    })
    assert r.status_code == 201
    return r.get_json()


def test_level_patch_sets_level(client):
    item = _add_inv(client, "Milk", track_mode="level", restock="2L milk")
    assert item["track_mode"] == "level" and item["level"] == "full"
    r = client.patch(f"/api/inventory/{item['id']}", json={"level": "low"})
    assert r.status_code == 200 and r.get_json()["level"] == "low"


def test_level_patch_rejects_bad_level(client):
    item = _add_inv(client, "Milk", track_mode="level")
    r = client.patch(f"/api/inventory/{item['id']}", json={"level": "empty-ish"})
    assert r.status_code == 400


def test_tracked_full_counts_as_stocked(client):
    # A level item at full/ok is in stock -> NOT a restock need.
    _add_inv(client, "Pasta", location="pantry", track_mode="level", restock="500g pasta")
    from routes.inventory import get_restock_needs, get_stocked_names
    assert get_restock_needs() == {}
    assert "pasta" in get_stocked_names()


def test_tracked_low_is_a_restock_need(client):
    item = _add_inv(client, "Pasta", location="pantry", track_mode="level", restock="500g pasta")
    client.patch(f"/api/inventory/{item['id']}", json={"level": "low"})
    from routes.inventory import get_restock_needs, get_stocked_names
    assert get_restock_needs() == {"pasta": "500g pasta"}
    assert "pasta" not in get_stocked_names()


def test_reconcile_includes_low_staple(client):
    # No accepted meals, but a low level staple -> appears in required set.
    item = _add_inv(client, "Flour", location="pantry", track_mode="level", restock="1kg flour")
    client.patch(f"/api/inventory/{item['id']}", json={"level": "out"})
    required = shopping._required_ingredients()
    assert required.get("flour", {}).get("item") == "1kg flour"


def test_filing_restocks_existing_level_item(client):
    # A low level item, bought and filed, should return to full (not duplicate).
    item = _add_inv(client, "Milk", track_mode="level", restock="2L milk")
    client.patch(f"/api/inventory/{item['id']}", json={"level": "out"})
    r = client.post("/api/shopping/file-to-inventory",
                    json={"name": "Milk", "location": "fridge_inside"})
    assert r.status_code == 201
    assert r.get_json()["item"]["level"] == "full"
    inv = client.get("/api/inventory/").get_json()
    milks = [i for loc in inv["items"].values() for i in loc if i["name"] == "Milk"]
    assert len(milks) == 1 and milks[0]["level"] == "full"


# ── Barcode scan ──────────────────────────────────────────────────────────

def test_lookup_rejects_bad_barcode(client):
    r = client.get("/api/inventory/lookup/notabarcode")
    assert r.status_code == 200
    assert r.get_json()["found"] is False


def test_lookup_resolves_product(client, monkeypatch):
    import routes.inventory as inv_mod

    class _R:
        def raise_for_status(self): pass
        def json(self): return {
            "status": 1,
            "product": {"product_name": "Semi Skimmed Milk", "brands": "Tesco, Store"},
        }
    monkeypatch.setattr(inv_mod.http_requests, "get", lambda *a, **k: _R())
    r = client.get("/api/inventory/lookup/5000112345678")
    body = r.get_json()
    assert body["found"] is True
    assert body["name"] == "Semi Skimmed Milk"
    assert body["brand"] == "Tesco"  # first brand only


def test_lookup_handles_not_found(client, monkeypatch):
    import routes.inventory as inv_mod

    class _R:
        def raise_for_status(self): pass
        def json(self): return {"status": 0}
    monkeypatch.setattr(inv_mod.http_requests, "get", lambda *a, **k: _R())
    r = client.get("/api/inventory/lookup/5000112345678")
    assert r.get_json()["found"] is False


def test_scan_add_new_item(client):
    r = client.post("/api/inventory/scan-add",
                    json={"name": "Baked Beans", "location": "pantry"})
    assert r.status_code == 201
    assert r.get_json()["action"] == "added"
    inv = client.get("/api/inventory/").get_json()
    assert any(i["name"] == "Baked Beans" for i in inv["items"]["pantry"])


def test_scan_add_restocks_tracked(client):
    item = _add_inv(client, "Milk", track_mode="level", restock="2L milk")
    client.patch(f"/api/inventory/{item['id']}", json={"level": "out"})
    r = client.post("/api/inventory/scan-add",
                    json={"name": "Milk", "location": "fridge_inside"})
    assert r.status_code == 201
    body = r.get_json()
    assert body["action"] == "restocked"
    assert body["item"]["level"] == "full"
    inv = client.get("/api/inventory/").get_json()
    milks = [i for loc in inv["items"].values() for i in loc if i["name"] == "Milk"]
    assert len(milks) == 1


def test_scan_add_untracked_existing_is_noop(client):
    # A count item scanned again increments its count (3 cans = one line, +1).
    first = client.post("/api/inventory/scan-add",
                        json={"name": "Chopped Tomatoes", "location": "pantry"})
    assert first.get_json()["item"]["count"] == 1
    r = client.post("/api/inventory/scan-add",
                    json={"name": "Chopped Tomatoes", "location": "pantry", "count": 2})
    body = r.get_json()
    assert body["action"] == "incremented"
    assert body["item"]["count"] == 3  # 1 + 2
    inv = client.get("/api/inventory/").get_json()
    toms = [i for loc in inv["items"].values() for i in loc if i["name"] == "Chopped Tomatoes"]
    assert len(toms) == 1 and toms[0]["count"] == 3


# ── Per-meal accept → draft of that meal's unmatched ingredients ────────────

def _seed_dinner(status="generated"):
    """Seed one dinner slot with two ingredients via write_data."""
    import routes.meals as meals
    meals.write_data({
        "slots": [{
            "id": "d1", "date": "2026-11-02", "status": status,
            "rejection_reasons": [],
            "meal": {"name": "Pasta Bake", "description": "",
                     "ingredients": [
                         {"item": "Pasta", "quantity": "500g"},
                         {"item": "Cheddar", "quantity": "200g"},
                     ]},
        }],
        "lunch_ideas": [], "generated_at": None,
    })


def test_accept_dinner_returns_per_meal_draft(client, monkeypatch):
    # No GPT: deterministic string matching. Nothing in inventory -> both
    # ingredients are unmatched and come back as draft lines for THIS meal only.
    import routes.reservations as reservations
    monkeypatch.setattr(reservations, "match_ingredients",
                        lambda names, items, **k: ({n: None for n in names}, False))
    _seed_dinner()
    r = client.post("/api/meals/d1/accept")
    assert r.status_code == 200
    body = r.get_json()
    assert body["slot"]["status"] == "accepted"
    names = sorted(line["name"] for line in body["draft"])
    assert names == ["Cheddar", "Pasta"]


def test_accept_dinner_draft_empty_when_stocked(client, monkeypatch):
    # Both ingredients match inventory -> draft is empty (stock covers it).
    import routes.reservations as reservations
    _add_inv(client, "Pasta", location="pantry", track_mode="count", count=2)
    _add_inv(client, "Cheddar", location="fridge_inside", track_mode="count", count=2)
    inv_by_name = {}
    with dbmod.session_scope() as s:
        for it in s.query(models.InventoryItem).all():
            inv_by_name[it.name.lower()] = it.id
    monkeypatch.setattr(
        reservations, "match_ingredients",
        lambda names, items, **k: (
            {n: next((i for i in items if i.name.lower() == n.lower()), None) for n in names},
            False,
        ),
    )
    _seed_dinner()
    r = client.post("/api/meals/d1/accept")
    assert r.status_code == 200
    assert r.get_json()["draft"] == []


def test_reject_accepted_dinner_reconciles(client, monkeypatch):
    # Accepting then rejecting a dinner triggers a reconcile so its items drop.
    import routes.reservations as reservations
    monkeypatch.setattr(reservations, "match_ingredients",
                        lambda names, items, **k: ({n: None for n in names}, False))
    monkeypatch.setattr("routes.meals._call_openai", lambda *a, **k: [])
    called = {"reconcile": 0}
    import routes.shopping as shopmod
    orig = shopmod.reconcile_auto_items
    monkeypatch.setattr(shopmod, "reconcile_auto_items",
                        lambda: (called.__setitem__("reconcile", called["reconcile"] + 1), orig())[1])
    _seed_dinner()
    client.post("/api/meals/d1/accept")
    r = client.post("/api/meals/d1/reject", json={"reason": "no"})
    assert r.status_code == 200
    assert called["reconcile"] == 1  # reconcile ran because it was accepted


# ── Standalone lunch generation ─────────────────────────────────────────────

def test_generate_lunches_count_and_keeps_accepted(client, monkeypatch):
    # Seed one accepted lunch directly, then generate 2 fresh ones. The accepted
    # one survives; the result holds accepted + count fresh = 3.
    import routes.meals as meals
    meals.write_data({
        "slots": [],
        "lunch_ideas": [{
            "id": "keep-1", "status": "accepted", "rejection_reasons": [],
            "name": "Keep Me", "description": "", "ingredients": [],
        }],
        "generated_at": None,
    })
    # Stub the LLM: return `count` placeholder ideas.
    monkeypatch.setattr(
        meals, "_call_openai",
        lambda prompt, **k: [{"name": f"Lunch {i}", "description": "", "ingredients": []}
                             for i in range(2)],
    )
    r = client.post("/api/meals/lunch/generate", json={"count": 2})
    assert r.status_code == 200
    lunches = r.get_json()["lunch_ideas"]
    assert len(lunches) == 3  # 1 accepted kept + 2 fresh
    assert any(l["id"] == "keep-1" and l["status"] == "accepted" for l in lunches)
    assert sum(1 for l in lunches if l["status"] == "generated") == 2


def test_generate_lunches_clamps_count(client, monkeypatch):
    import routes.meals as meals
    meals.write_data({"slots": [], "lunch_ideas": [], "generated_at": None})
    captured = {}

    def fake_prompt(count=3, rejection_reasons=None):
        captured["count"] = count
        return "prompt"
    monkeypatch.setattr(meals, "build_lunch_prompt", fake_prompt)
    monkeypatch.setattr(meals, "_call_openai", lambda prompt, **k: [])

    client.post("/api/meals/lunch/generate", json={"count": 99})
    assert captured["count"] == 10  # clamped to max


# ── Cancelling the review panel reverts the accept ──────────────────────────

def test_unaccept_dinner_reverts_status(client, monkeypatch):
    # Accept then unaccept (review cancelled) -> status back to 'generated'.
    import routes.reservations as reservations
    monkeypatch.setattr(reservations, "match_ingredients",
                        lambda names, items, **k: ({n: None for n in names}, False))
    _seed_dinner()
    client.post("/api/meals/d1/accept")
    r = client.post("/api/meals/d1/unaccept")
    assert r.status_code == 200
    assert r.get_json()["status"] == "generated"


def test_unaccept_lunch_reverts_status(client):
    import routes.meals as meals
    meals.write_data({
        "slots": [],
        "lunch_ideas": [{
            "id": "l1", "status": "accepted", "rejection_reasons": [],
            "name": "Soup", "description": "", "ingredients": [],
        }],
        "generated_at": None,
    })
    r = client.post("/api/meals/lunch/l1/unaccept")
    assert r.status_code == 200
    assert r.get_json()["status"] == "generated"


# ── Receipt scan (photo -> item list via mocked GPT-4o vision) ──────────────

def test_receipt_scan_parses_items(client, monkeypatch):
    import routes.inventory as inv

    # Fake the OpenAI client so no network/key is needed.
    class _Msg:
        content = '{"items":[{"name":"Heinz Baked Beans","quantity":2},{"name":"Milk","quantity":1}]}'
    class _Choice:
        message = _Msg()
    class _Resp:
        choices = [_Choice()]
    class _Completions:
        def create(self, **k): return _Resp()
    class _Chat:
        completions = _Completions()
    class _FakeClient:
        def __init__(self, **k): self.chat = _Chat()

    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setattr(inv, "OpenAI", _FakeClient, raising=False)
    # inventory.py imports OpenAI lazily inside the view; patch the module ref.
    import openai
    monkeypatch.setattr(openai, "OpenAI", _FakeClient)

    r = client.post("/api/inventory/receipt-scan",
                    json={"image": "data:image/jpeg;base64,AAAA"})
    assert r.status_code == 200
    items = r.get_json()["items"]
    names = sorted(i["name"] for i in items)
    assert names == ["Heinz Baked Beans", "Milk"]
    beans = next(i for i in items if i["name"] == "Heinz Baked Beans")
    assert beans["quantity"] == 2


def test_receipt_scan_requires_image(client, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    r = client.post("/api/inventory/receipt-scan", json={})
    assert r.status_code == 400


def test_receipt_scan_no_key(client, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    r = client.post("/api/inventory/receipt-scan",
                    json={"image": "data:image/jpeg;base64,AAAA"})
    assert r.status_code == 503


def test_scan_add_folds_same_name(client):
    # Scanning the same item twice increments count, not a duplicate row.
    client.post("/api/inventory/scan-add",
                json={"name": "Beans", "location": "pantry", "track_mode": "count", "count": 2})
    r = client.post("/api/inventory/scan-add",
                    json={"name": "beans", "location": "pantry", "track_mode": "count", "count": 1})
    assert r.status_code == 201
    body = r.get_json()
    assert body["action"] == "incremented"
    assert body["item"]["count"] == 3


# ── Steering editor (backlog #6) ────────────────────────────────────────────

def test_steering_save_and_revert(client):
    # List returns the meal_planning doc (baked default, not overridden).
    r = client.get("/api/steering/")
    assert r.status_code == 200
    docs = {d["key"]: d for d in r.get_json()["docs"]}
    assert "meal_planning" in docs
    assert docs["meal_planning"]["overridden"] is False

    # Save an override.
    r = client.put("/api/steering/meal_planning", json={"content": "Only vegan meals."})
    assert r.status_code == 200
    assert r.get_json()["overridden"] is True

    # It now reads back as overridden with the new content.
    docs = {d["key"]: d for d in client.get("/api/steering/").get_json()["docs"]}
    assert docs["meal_planning"]["overridden"] is True
    assert docs["meal_planning"]["content"] == "Only vegan meals."

    # The meal loader now returns the override.
    import routes.meals as meals
    assert meals.load_meal_planning_rules() == "Only vegan meals."

    # Revert drops the override.
    r = client.delete("/api/steering/meal_planning")
    assert r.status_code == 200
    docs = {d["key"]: d for d in client.get("/api/steering/").get_json()["docs"]}
    assert docs["meal_planning"]["overridden"] is False


def test_steering_empty_content_reverts(client):
    client.put("/api/steering/meal_planning", json={"content": "temp"})
    # Saving empty content is treated as a revert.
    r = client.put("/api/steering/meal_planning", json={"content": "   "})
    assert r.status_code == 200
    assert r.get_json()["overridden"] is False


def test_steering_append_adds_line(client):
    # Append to the meal prompt -> content now ends with the bullet, overridden.
    r = client.post("/api/steering/meal_planning/append",
                    json={"addition": "- Avoid omelettes for Hannah"})
    assert r.status_code == 200
    assert r.get_json()["overridden"] is True
    docs = {d["key"]: d for d in client.get("/api/steering/").get_json()["docs"]}
    assert "Avoid omelettes for Hannah" in docs["meal_planning"]["content"]


def test_steering_suggest_mocked(client, monkeypatch):
    import routes.steering as steering

    class _Msg:
        content = '{"target_key":"meal_planning","target_title":"Meal-planning prompt","addition":"- Dislikes omelettes"}'
    class _Choice: message = _Msg()
    class _Resp: choices = [_Choice()]
    class _Completions:
        def create(self, **k): return _Resp()
    class _Chat: completions = _Completions()
    class _FakeClient:
        def __init__(self, **k): self.chat = _Chat()

    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    import openai
    monkeypatch.setattr(openai, "OpenAI", _FakeClient)

    r = client.post("/api/steering/suggest",
                    json={"reason": "Hannah hates omelettes", "meal_name": "Omelette"})
    assert r.status_code == 200
    body = r.get_json()
    assert body["target_key"] == "meal_planning"
    assert "omelette" in body["addition"].lower()

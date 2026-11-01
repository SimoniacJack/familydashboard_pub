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

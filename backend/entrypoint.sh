#!/bin/sh
set -e

# Wait for Postgres to accept connections (compose/EC2 may start it alongside).
echo "Waiting for database..."
python - <<'PY'
import os, time, sys
from sqlalchemy import create_engine, text
url = os.environ.get("DATABASE_URL", "postgresql+psycopg://familydash:familydash@db:5432/familydashboard")
for attempt in range(30):
    try:
        create_engine(url, pool_pre_ping=True).connect().execute(text("SELECT 1"))
        print("Database is up.")
        sys.exit(0)
    except Exception as e:
        print(f"  not ready ({attempt+1}/30): {e.__class__.__name__}")
        time.sleep(2)
print("Database did not become ready in time.", file=sys.stderr)
sys.exit(1)
PY

# Apply migrations
echo "Running migrations..."
alembic upgrade head

# Seed from legacy JSON only if the DB looks empty (first boot).
echo "Seeding if needed..."
python - <<'PY'
from sqlalchemy import select
from db import session_scope
from models import Member
with session_scope() as s:
    count = len(s.scalars(select(Member)).all())
if count == 0:
    print("  empty DB — importing seed data")
    import import_json_to_db
    import_json_to_db.main()
else:
    print(f"  {count} members present — skipping full seed")
PY

# Idempotent reference-data seed: ensure rooms exist even on an already-seeded
# DB (so schema-adding deploys don't leave reference tables empty).
echo "Ensuring reference data (rooms)..."
python - <<'PY'
from sqlalchemy import select
from db import session_scope
from models import Room
from import_json_to_db import ROOMS
with session_scope() as s:
    existing = {r.id for r in s.scalars(select(Room)).all()}
    added = 0
    for rid, name, floor, order in ROOMS:
        if rid not in existing:
            s.add(Room(id=rid, name=name, floor=floor, sort_order=order))
            added += 1
    print(f"  rooms ensured ({added} added)")
PY

echo "Starting gunicorn..."
# 1GB t3.micro: keep the footprint small. 2 threads give light concurrency
# without the memory cost of a second worker process.
exec gunicorn --bind 0.0.0.0:5000 --workers 1 --threads 4 --timeout 120 app:app

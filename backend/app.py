from flask import Flask, send_from_directory
from flask_cors import CORS
from dotenv import load_dotenv
import os

from routes.chores import chores_bp
from routes.members import members_bp
from routes.meals import meals_bp
from routes.calendar import calendar_bp
from routes.reminders import reminders_bp
from routes.inventory import inventory_bp
from routes.assignments import assignments_bp
from routes.shopping import shopping_bp

# Local dev loads secrets from git.env; in a container/EC2 they come from the
# environment (populated from AWS Secrets Manager). load_dotenv is a no-op if
# the file is absent, so this is safe in all environments.
load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), "..", "git.env"))

# Where the built frontend lives (Vite build output copied in by the Dockerfile).
STATIC_DIR = os.environ.get(
    "FRONTEND_DIST",
    os.path.join(os.path.dirname(__file__), "static"),
)

app = Flask(__name__, static_folder=None)

# In dev the Vite proxy handles cross-origin; in prod Flask serves the frontend
# same-origin so CORS isn't needed. Keep localhost origins allowed for dev.
CORS(app, origins=["http://localhost:5173", "http://127.0.0.1:5173"])

app.register_blueprint(chores_bp, url_prefix="/api/chores")
app.register_blueprint(members_bp, url_prefix="/api/members")
app.register_blueprint(meals_bp, url_prefix="/api/meals")
app.register_blueprint(calendar_bp, url_prefix="/api/calendar")
app.register_blueprint(reminders_bp, url_prefix="/api/reminders")
app.register_blueprint(inventory_bp, url_prefix="/api/inventory")
app.register_blueprint(assignments_bp, url_prefix="/api/assignments")
app.register_blueprint(shopping_bp, url_prefix="/api/shopping")


@app.route("/api/health")
def health():
    return {"status": "ok"}


# ── Serve the built frontend (production) ───────────────────────────────────
# Any non-/api path returns a static asset if it exists, else index.html so the
# single-page app can handle routing.
@app.route("/", defaults={"path": ""})
@app.route("/<path:path>")
def serve_frontend(path):
    if path.startswith("api/"):
        return {"error": "Not found"}, 404
    full = os.path.join(STATIC_DIR, path)
    if path and os.path.isfile(full):
        return send_from_directory(STATIC_DIR, path)
    index = os.path.join(STATIC_DIR, "index.html")
    if os.path.isfile(index):
        return send_from_directory(STATIC_DIR, "index.html")
    # No build present (pure-dev backend) — friendly hint.
    return {"status": "backend running; no frontend build present"}, 200


if __name__ == "__main__":
    app.run(debug=True, port=5000)

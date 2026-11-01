from flask import Flask, send_from_directory, request, jsonify, session
from flask_cors import CORS
from dotenv import load_dotenv
from datetime import timedelta
import os

from routes.chores import chores_bp
from routes.members import members_bp
from routes.meals import meals_bp
from routes.calendar import calendar_bp
from routes.reminders import reminders_bp
from routes.inventory import inventory_bp
from routes.assignments import assignments_bp
from routes.shopping import shopping_bp
from routes.auth import auth_bp, is_authed
from routes.config import config_bp

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

# ── Session / cookie auth ───────────────────────────────────────────────────
# Signed, HttpOnly session cookie keeps the family logged in for 30 days, so
# they type the shared password once instead of every visit (the old Basic Auth
# problem). SECRET_KEY signs the cookie — set in git.env / the prod environment.
app.config.update(
    SECRET_KEY=os.environ.get("SECRET_KEY", "dev-insecure-change-me"),
    PERMANENT_SESSION_LIFETIME=timedelta(days=30),
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    # Secure in prod (HTTPS via Caddy); allow plain http on localhost for dev.
    SESSION_COOKIE_SECURE=os.environ.get("COOKIE_SECURE", "1") == "1",
)

# In dev the Vite proxy handles cross-origin; in prod Flask serves the frontend
# same-origin so CORS isn't needed. Keep localhost origins allowed for dev, with
# credentials so the session cookie flows through the proxy.
CORS(app, origins=["http://localhost:5173", "http://127.0.0.1:5173"],
     supports_credentials=True)

# Endpoints reachable WITHOUT a session: the auth API itself and health.
_PUBLIC_API = {"/api/auth/login", "/api/auth/logout", "/api/auth/me", "/api/health", "/api/config/"}


@app.before_request
def require_login():
    """Gate every /api/* route behind a valid session (except the public set).
    Non-API paths (the SPA + its assets) are always served so the login page can
    load; the frontend shows login vs app based on /api/auth/me."""
    path = request.path
    if request.method == "OPTIONS":
        return  # CORS preflight
    if path.startswith("/api/"):
        if path in _PUBLIC_API:
            return
        if not is_authed():
            return jsonify({"error": "authentication required"}), 401
    # Non-API paths fall through — the SPA decides login vs app client-side.


app.register_blueprint(auth_bp, url_prefix="/api/auth")
app.register_blueprint(config_bp, url_prefix="/api/config")
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

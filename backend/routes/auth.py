"""Cookie-session auth for the single shared family login.

Replaces the old Caddy HTTP Basic Auth (which mobile browsers kept dropping,
forcing a re-type every visit). The family logs in ONCE with the shared
password; a signed HttpOnly session cookie then keeps them in for 30 days.

Password is verified against AUTH_PASSWORD_HASH (a Werkzeug scrypt/pbkdf2 hash,
set in git.env — never the plaintext). The cookie is signed with the app
SECRET_KEY. There is one shared identity, so there is no username — just the
password, matching how the family already thinks of "the dashboard login".
"""
import os

from flask import Blueprint, jsonify, request, session
from werkzeug.security import check_password_hash

auth_bp = Blueprint("auth", __name__)

# Session key set once the password has been verified.
SESSION_FLAG = "authed"


def _password_hash():
    """The shared-password hash. Werkzeug scrypt/pbkdf2 hashes contain '$',
    which docker's env_file parsing truncates — so we prefer a base64-wrapped
    form (AUTH_PASSWORD_HASH_B64) that is '$'-free, and fall back to the plain
    AUTH_PASSWORD_HASH for local dev (python-dotenv reads it literally)."""
    import base64
    b64 = os.environ.get("AUTH_PASSWORD_HASH_B64", "")
    if b64:
        try:
            return base64.b64decode(b64).decode("utf-8")
        except (ValueError, UnicodeDecodeError):
            pass
    return os.environ.get("AUTH_PASSWORD_HASH", "")


def is_authed():
    """True when the current request carries a valid signed session."""
    return bool(session.get(SESSION_FLAG))


@auth_bp.route("/login", methods=["POST"])
def login():
    """Verify the shared password and start a 30-day session. Body: {password}."""
    body = request.get_json(silent=True) or {}
    password = body.get("password") or ""
    hash_ = _password_hash()
    # No hash configured -> refuse rather than silently allowing everyone in.
    if not hash_:
        return jsonify({"error": "auth not configured"}), 500
    if not password or not check_password_hash(hash_, password):
        return jsonify({"error": "incorrect password"}), 401
    session.permanent = True            # honour PERMANENT_SESSION_LIFETIME
    session[SESSION_FLAG] = True
    return jsonify({"ok": True})


@auth_bp.route("/logout", methods=["POST"])
def logout():
    session.clear()
    return jsonify({"ok": True})


@auth_bp.route("/me", methods=["GET"])
def me():
    """Lightweight check the frontend calls on load to decide login vs app."""
    return jsonify({"authed": is_authed()})

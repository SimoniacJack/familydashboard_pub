"""Per-instance configuration that makes a deployment 'yours'.

The app is family-agnostic; an instance is configured by environment. FAMILY_NAME
is the one display string that personalises the UI and meal prompts (e.g.
"Parker", "Smith"). Everything else family-specific (members, chores, profiles)
is data in the database, not code.
"""
import os

from flask import Blueprint, jsonify

config_bp = Blueprint("config", __name__)


def family_name():
    """The family's display name, e.g. 'Parker'. Defaults to a neutral value so
    a fresh clone runs before it's configured."""
    return (os.environ.get("FAMILY_NAME") or "The Family").strip()


@config_bp.route("/", methods=["GET"])
def get_config():
    """Public instance config the frontend reads on load to brand the UI."""
    return jsonify({"family_name": family_name()})

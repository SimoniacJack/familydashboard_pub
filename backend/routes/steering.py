"""Steering editor — view/edit the AI meal-planning prompt and per-member
likes/dislikes from the UI. Edits are stored in `steering_docs` (DB) so they
persist across deploys; the baked files remain the default when no row exists.
"""
import os
from datetime import datetime

from flask import Blueprint, jsonify, request
from sqlalchemy import select

from db import session_scope
from models import SteeringDoc, Member

steering_bp = Blueprint("steering", __name__)

MEMBERS_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "familymembers")
PROMPT_FILE = os.path.join(os.path.dirname(__file__), "..", "prompts", "meal_planning.md")


def _baked_prompt():
    if os.path.exists(PROMPT_FILE):
        with open(PROMPT_FILE, "r", encoding="utf-8") as f:
            return f.read()
    return ""


def _baked_member(markdown_url):
    if not markdown_url:
        return ""
    path = os.path.join(os.path.dirname(__file__), "..", "..", markdown_url)
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    return ""


def _effective(session, key, baked):
    """(content, overridden) — DB row if present, else the baked default."""
    row = session.get(SteeringDoc, key)
    if row is not None and row.content.strip():
        return row.content, True
    return baked, False


@steering_bp.route("/", methods=["GET"])
def list_steering():
    """All editable steering docs: the meal-planning prompt + one per member."""
    docs = []
    with session_scope() as session:
        content, overridden = _effective(session, "meal_planning", _baked_prompt())
        docs.append({
            "key": "meal_planning",
            "title": "Meal-planning prompt",
            "kind": "prompt",
            "content": content,
            "overridden": overridden,
            "help": "Core instructions the AI follows when generating meals. Edit carefully.",
        })
        members = session.scalars(select(Member)).all()
        for m in members:
            key = f"member:{m.id}"
            content, overridden = _effective(session, key, _baked_member(m.markdown_url))
            docs.append({
                "key": key,
                "title": f"{m.name} — likes & dislikes",
                "kind": "member",
                "content": content,
                "overridden": overridden,
                "help": f"Steers meals for {m.name}. Plain text / markdown.",
            })
    return jsonify({"docs": docs})


@steering_bp.route("/<path:key>", methods=["PUT"])
def save_steering(key):
    """Upsert a steering doc. Body: {content}. An empty content deletes the
    override (reverts to the baked default)."""
    body = request.get_json(silent=True) or {}
    content = body.get("content", "")
    if not isinstance(content, str):
        return jsonify({"error": "content must be a string"}), 400
    with session_scope() as session:
        if content.strip() == "":
            row = session.get(SteeringDoc, key)
            if row is not None:
                session.delete(row)
            return jsonify({"ok": True, "key": key, "overridden": False})
        row = session.get(SteeringDoc, key)
        if row is None:
            row = SteeringDoc(key=key, content=content, updated_at=datetime.utcnow())
            session.add(row)
        else:
            row.content = content
            row.updated_at = datetime.utcnow()
    return jsonify({"ok": True, "key": key, "overridden": True})


@steering_bp.route("/<path:key>", methods=["DELETE"])
def revert_steering(key):
    """Delete the override so the baked default is used again."""
    with session_scope() as session:
        row = session.get(SteeringDoc, key)
        if row is not None:
            session.delete(row)
    return jsonify({"ok": True, "key": key, "overridden": False})


@steering_bp.route("/suggest", methods=["POST"])
def suggest_steering():
    """Given a meal-rejection reason, ask GPT which steering doc to amend and
    what one-line note to add — a specific member (member:<id>) or the general
    meal-planning prompt. Returns a PROPOSAL only; the user confirms, edits the
    target/text, and the existing PUT applies it. Never writes here.
    Body: {reason, meal_name?}."""
    import os
    import json as _json
    body = request.get_json(silent=True) or {}
    reason = (body.get("reason") or "").strip()
    meal_name = (body.get("meal_name") or "").strip()
    if not reason:
        return jsonify({"error": "reason required"}), 400
    if not os.environ.get("OPENAI_API_KEY"):
        return jsonify({"error": "OpenAI not configured"}), 503

    with session_scope() as session:
        members = [(m.id, m.name) for m in session.scalars(select(Member)).all()]
    member_list = "\n".join(f"- id={mid} name={name}" for mid, name in members)

    prompt = (
        "A family rejected a suggested meal. Turn the rejection into a durable "
        "steering note for an AI meal planner.\n\n"
        f"Rejected meal: {meal_name or '(unknown)'}\n"
        f"Reason given: {reason}\n\n"
        f"Family members:\n{member_list}\n\n"
        "Decide the single best place for this note:\n"
        "- a specific member, when the reason is about ONE person's taste "
        "(target_key 'member:<id>'),\n"
        "- the general prompt, when it is a whole-household rule "
        "(target_key 'meal_planning').\n"
        "Write 'addition' as ONE concise markdown bullet to append, e.g. "
        "'- Dislikes omelettes'. Keep it faithful to the reason; do not invent.\n"
        'Respond with STRICT JSON only: '
        '{"target_key": "...", "target_title": "...", "addition": "- ..."}.'
    )
    try:
        from openai import OpenAI
        client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])
        resp = client.chat.completions.create(
            model="gpt-4o",
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"},
            temperature=0,
            max_tokens=200,
        )
        parsed = _json.loads(resp.choices[0].message.content or "{}")
    except Exception as exc:  # noqa: BLE001
        return jsonify({"error": f"suggestion failed: {exc}"}), 502

    target_key = (parsed.get("target_key") or "meal_planning").strip()
    addition = (parsed.get("addition") or "").strip()
    # Validate target: either the prompt or a real member.
    valid_keys = {"meal_planning"} | {f"member:{mid}" for mid, _ in members}
    if target_key not in valid_keys:
        target_key = "meal_planning"
    title = ("Meal-planning prompt" if target_key == "meal_planning"
             else next((f"{name} — likes & dislikes" for mid, name in members
                        if f"member:{mid}" == target_key), target_key))
    return jsonify({"target_key": target_key, "target_title": title,
                    "addition": addition})


@steering_bp.route("/<path:key>/append", methods=["POST"])
def append_steering(key):
    """Append a line to a steering doc's CURRENT effective content (baked
    default + any override), persisting the result as an override. Used when
    the user confirms a GPT-proposed amendment. Body: {addition}."""
    body = request.get_json(silent=True) or {}
    addition = (body.get("addition") or "").strip()
    if not addition:
        return jsonify({"error": "addition required"}), 400
    with session_scope() as session:
        if key == "meal_planning":
            base = _baked_prompt()
        elif key.startswith("member:"):
            mid = key.split(":", 1)[1]
            m = session.get(Member, mid)
            base = _baked_member(m.markdown_url) if m else ""
        else:
            return jsonify({"error": "unknown steering key"}), 400
        row = session.get(SteeringDoc, key)
        current = row.content if (row and row.content.strip()) else base
        new_content = (current.rstrip() + "\n" + addition + "\n")
        if row is None:
            row = SteeringDoc(key=key, content=new_content, updated_at=datetime.utcnow())
            session.add(row)
        else:
            row.content = new_content
            row.updated_at = datetime.utcnow()
    return jsonify({"ok": True, "key": key, "overridden": True})

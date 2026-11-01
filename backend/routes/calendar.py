from flask import Blueprint, jsonify, request
from datetime import datetime, timedelta

from routes.meals import read_data, fetch_calendar_range, DAYS
from routes.assignments import annotate_events

calendar_bp = Blueprint("calendar", __name__)

def this_monday(today=None):
    """Monday of the current week (date object)."""
    today = today or datetime.utcnow()
    start = today - timedelta(days=today.weekday())
    return start.replace(hour=0, minute=0, second=0, microsecond=0)

@calendar_bp.route("/week", methods=["GET"])
def get_week():
    """Return calendar events + meal slots for a given week.
    Query param `week_start` (YYYY-MM-DD, a Monday) selects the week; defaults to this week.
    Meal slots only appear on the week they were generated for.
    """
    week_start_param = request.args.get("week_start")
    if week_start_param:
        first_date = datetime.strptime(week_start_param, "%Y-%m-%d")
    else:
        first_date = this_monday()

    data = read_data()
    slots = data.get("slots", [])

    # Map meal slots by date (they only land on their own week)
    slots_by_date = {}
    for slot in slots:
        slots_by_date.setdefault(slot["date"], []).append(slot)

    # The Monday this meal plan covers (if any) — used by the frontend to jump to it
    meal_week_start = None
    if slots:
        meal_week_start = min(s["date"] for s in slots)

    # One request for the whole week's events, bucketed by date
    events_by_date = fetch_calendar_range(first_date.strftime("%Y-%m-%d"), 7)

    days = []
    for i in range(7):
        date_obj = first_date + timedelta(days=i)
        date_str = date_obj.strftime("%Y-%m-%d")
        display_date = date_obj.strftime("%-d %b")
        day_name = DAYS[i]

        events = annotate_events(events_by_date.get(date_str, []))

        days.append({
            "day": day_name,
            "date": date_str,
            "display_date": display_date,
            "calendar_events": events,
            "slots": slots_by_date.get(date_str, []),
        })

    # Lunch ideas belong to the meal-plan week; only surface them when viewing it
    viewing_meal_week = meal_week_start is not None and meal_week_start == first_date.strftime("%Y-%m-%d")

    return jsonify({
        "week_start": first_date.strftime("%Y-%m-%d"),
        "this_week_start": this_monday().strftime("%Y-%m-%d"),
        "meal_week_start": meal_week_start,
        "days": days,
        "lunch_ideas": data.get("lunch_ideas", []) if viewing_meal_week else [],
        "generated_at": data.get("generated_at"),
        "has_slots": any(d["slots"] for d in days),
    })

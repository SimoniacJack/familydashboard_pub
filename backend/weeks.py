"""Week/date helpers shared across routes."""
from datetime import datetime, timedelta, date as date_cls


def monday_of(d):
    """Return the Monday (date) of the week containing date `d`."""
    return d - timedelta(days=d.weekday())


def this_monday():
    return monday_of(datetime.utcnow().date())


def parse_date(s):
    """Parse 'YYYY-MM-DD' to a date object."""
    return datetime.strptime(s, "%Y-%m-%d").date()


def week_dates(week_start):
    """Return the 7 date objects for a week beginning `week_start` (a date)."""
    return [week_start + timedelta(days=i) for i in range(7)]


def is_monthly_due_week(week_start):
    """A monthly chore is shown on the week that contains the 1st of a month.
    Returns True if `week_start`..+6 spans a 1st-of-month."""
    for d in week_dates(week_start):
        if d.day == 1:
            return True
    return False


def day_key(d):
    """Canonical period key for a DAY-scoped instance: 'YYYY-MM-DD'."""
    return d.strftime("%Y-%m-%d")


def week_key(d):
    """Canonical period key for a WEEK-scoped instance: the Monday 'YYYY-MM-DD'."""
    return monday_of(d).strftime("%Y-%m-%d")


def month_key(d):
    """Canonical period key for a MONTH-scoped instance: 'YYYY-MM'."""
    return d.strftime("%Y-%m")

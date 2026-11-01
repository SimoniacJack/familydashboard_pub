#!/usr/bin/env python3
"""Minimal Todoist helper for the FamilyDashboard feature list.

Usage:
    todoist.py list                      # list open tasks (JSON)
    todoist.py comment <task_id> <text>  # add a comment to a task
    todoist.py close <task_id>           # mark a task complete

Reads TODOIST_API_TOKEN from git.env (CR-safe).
"""
import json
import os
import sys
import urllib.request
import urllib.error

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
API = "https://api.todoist.com/api/v1"
PROJECT_ID = "6hv8r6qHPmr8FW9v"  # FamilyDashboard project


def token():
    with open(os.path.join(REPO, "git.env")) as f:
        for line in f:
            line = line.strip().replace("\r", "")
            if line.startswith("TODOIST_API_TOKEN="):
                return line.split("=", 1)[1]
    raise SystemExit("TODOIST_API_TOKEN not found in git.env")


def req(method, path, body=None):
    url = f"{API}{path}"
    data = json.dumps(body).encode() if body is not None else None
    r = urllib.request.Request(url, data=data, method=method)
    r.add_header("Authorization", f"Bearer {token()}")
    if data:
        r.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(r) as resp:
            raw = resp.read().decode()
            return json.loads(raw) if raw.strip() else {}
    except urllib.error.HTTPError as e:
        raise SystemExit(f"Todoist API {e.code}: {e.read().decode()}")


def list_tasks():
    out = req("GET", f"/tasks?project_id={PROJECT_ID}")
    tasks = out.get("results", out) if isinstance(out, dict) else out
    slim = [
        {
            "id": t["id"],
            "content": t["content"],
            "description": t.get("description", ""),
            "priority": t.get("priority", 1),
        }
        for t in tasks
    ]
    print(json.dumps(slim, indent=2))


def comment(task_id, text):
    req("POST", "/comments", {"task_id": task_id, "content": text})
    print(f"commented on {task_id}")


def close(task_id):
    req("POST", f"/tasks/{task_id}/close")
    print(f"closed {task_id}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        raise SystemExit(__doc__)
    cmd = sys.argv[1]
    if cmd == "list":
        list_tasks()
    elif cmd == "comment":
        comment(sys.argv[2], sys.argv[3])
    elif cmd == "close":
        close(sys.argv[2])
    else:
        raise SystemExit(__doc__)

# Family Dashboard

A web app for a family to stay organised: shared calendar, weekly meal planning, chores, reminders, inventory, and a shopping list.

Self-hosted: each family runs their own instance and configures it with their
own family name, members, and API keys (see Setup below). Nothing in this repo
is specific to any one family.

## Stack

- **Frontend**: React / JavaScript (Vite)
- **Backend**: Python / Flask
- **Database**: PostgreSQL (SQLAlchemy ORM + Alembic migrations)
- **AI**: OpenAI GPT-4o for meal plan generation
- **Shopping list**: Todoist REST API
- **Deployment**: single host running Docker Compose (Flask + Postgres + Caddy)

## Project Structure

```
familydashboard/
├── frontend/        # React frontend (Vite)
├── backend/         # Flask API, SQLAlchemy models, Alembic migrations
├── familymembers/   # Per-member profile markdown (steers meal planning)
├── infra/           # Terraform / deployment config
└── .kiro/           # Agent steering docs
```

## Getting Started (dev)

Requires Python 3, Node, and a local Postgres.

```
# Backend
cd backend
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
export DATABASE_URL=postgresql://localhost/familydashboard   # or use the dev default
alembic upgrade head
python import_json_to_db.py   # seed from legacy JSON (optional)
flask run

# Frontend
cd frontend
npm install
npm run dev
```

Config and secrets (OpenAI key, Todoist token, DB URL) are read from environment variables; see `git.env` (gitignored).

## Setup — make it yours

This is a generic app; your family is configuration + data on top.

1. **Config.** Copy `.env.example` to `git.env` (dev) or set the vars in your
   environment (prod). At minimum set `FAMILY_NAME`, `SECRET_KEY`,
   `AUTH_PASSWORD_HASH_B64`, and `OPENAI_API_KEY`. Google Calendar and Todoist
   are optional.
2. **Family members.** Add each person in the app, and optionally drop a
   `familymembers/<name>.md` profile (copy an `example-*.md`) + a photo. Your
   real profiles are gitignored — they never enter the repo.
3. **Database.** `alembic upgrade head` creates the schema. The app starts empty;
   add your rooms, chores, reminders and inventory through the UI.
4. **Run.** `docker compose up` (Flask + Postgres + Caddy), or run the backend
   and `npm run dev` in `frontend/` for local development.

No family's data ships in this repo — only the code and example templates.

## Support

If this project is useful to your family and you'd like to support its
development:

[![Buy Me a Coffee](https://img.shields.io/badge/Buy%20Me%20a%20Coffee-support-FFDD00?logo=buy-me-a-coffee&logoColor=black)](https://www.buymeacoffee.com/jfpjacka)

> Replace `jfpjacka` with your Buy Me a Coffee handle (from your BMC page
> URL, e.g. `buymeacoffee.com/janedoe` → `janedoe`).

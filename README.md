# Family Dashboard

A web app for a family to stay organised: shared calendar, weekly meal planning, chores, reminders, inventory, and a shopping list.

Self-hosted — you deploy your own instance (see below).

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

# ── Stage 1: build the frontend ─────────────────────────────────────────────
FROM node:22-alpine AS frontend
WORKDIR /app/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# ── Stage 2: Python backend + built frontend ────────────────────────────────
FROM python:3.12-slim AS app
WORKDIR /app

# System deps for psycopg (libpq) — runtime only.
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 \
    && rm -rf /var/lib/apt/lists/*

# Python deps
COPY backend/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt gunicorn

# Backend source
COPY backend/ ./backend/
# Family member profiles (meal planning + member images) live outside backend/
COPY familymembers/ ./familymembers/

# Built frontend from stage 1 → served by Flask
COPY --from=frontend /app/frontend/dist ./backend/static

ENV FRONTEND_DIST=/app/backend/static
ENV PYTHONUNBUFFERED=1
WORKDIR /app/backend

RUN chmod +x entrypoint.sh

EXPOSE 5000

# Entrypoint waits for the DB, migrates, seeds if empty, then starts gunicorn.
# (gunicorn worker/thread counts are set inside entrypoint.sh — tuned for a
#  small 1GB instance.)
CMD ["./entrypoint.sh"]

#!/usr/bin/env bash
# Shared config + helpers for the deploy/rollback/todoist scripts.
# Source this: . "$(dirname "$0")/_common.sh"
set -euo pipefail

# ── Paths ───────────────────────────────────────────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
VENV_PY="$REPO_ROOT/.venv/bin/python"
VENV_AWS="$REPO_ROOT/.venv/bin/aws"
KEY="$REPO_ROOT/infra/familydashboard.pem"

# ── Infra values ────────────────────────────────────────────────────────────
# Set these in your environment (or a sourced, gitignored infra.env) to match
# your own deployment. Defaults are placeholders — override them.
AWS_REGION="${AWS_REGION:-eu-west-2}"
ECR_REGISTRY="${ECR_REGISTRY:-<account-id>.dkr.ecr.${AWS_REGION}.amazonaws.com}"
ECR_REPO="${ECR_REPO:-$ECR_REGISTRY/familydashboard}"
EC2_HOST="${EC2_HOST:-ubuntu@your-server-ip}"   # e.g. ubuntu@203.0.113.10
APP_URL="${APP_URL:-https://your-domain.example.org}"
COMPOSE="/opt/app/docker-compose.prod.yml"

# ── docker: use sudo only if the daemon isn't reachable without it ──────────
if docker info >/dev/null 2>&1; then
  DOCKER="docker"
else
  DOCKER="sudo docker"
fi

# ── Load AWS creds from git.env, stripping Windows CR line endings ──────────
load_aws_creds() {
  set -a
  # shellcheck disable=SC1090
  source <(grep -E '^AWS_' "$REPO_ROOT/git.env" | tr -d '\r')
  set +a
}

# ── Load the Todoist token (CR-safe) ────────────────────────────────────────
todoist_token() {
  grep -E '^TODOIST_API_TOKEN=' "$REPO_ROOT/git.env" | cut -d= -f2- | tr -d '\r'
}

ssh_ec2() {
  ssh -o StrictHostKeyChecking=no -o ConnectTimeout=20 -i "$KEY" "$EC2_HOST" "$@"
}

ecr_login_local() {
  load_aws_creds
  "$VENV_AWS" ecr get-login-password --region "$AWS_REGION" \
    | $DOCKER login --username AWS --password-stdin "$ECR_REGISTRY" >/dev/null 2>&1
}

log()  { printf '\033[1;36m==>\033[0m %s\n' "$*"; }
ok()   { printf '\033[1;32m  ✓\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m  ! \033[0m%s\n' "$*"; }
die()  { printf '\033[1;31m  ✗ %s\033[0m\n' "$*" >&2; exit 1; }

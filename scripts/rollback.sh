#!/usr/bin/env bash
# Roll the app back to the previously-deployed image tag (recorded by redeploy.sh).
# Optionally pass an explicit tag:  scripts/rollback.sh <git-short-sha>
#
. "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/_common.sh"

TARGET="${1:-}"
if [ -z "$TARGET" ]; then
  TARGET=$(ssh_ec2 "cat /opt/app/.previous_tag 2>/dev/null || echo none")
fi

[ "$TARGET" = "none" ] || [ -z "$TARGET" ] && die "No rollback target found. Pass a tag explicitly: scripts/rollback.sh <tag>"

log "Rolling back to image tag: $TARGET"

# Point the app service at the specific tag via a compose override, then restart.
ssh_ec2 "
  set -e
  cd /opt/app
  aws ecr get-login-password --region $AWS_REGION | sudo docker login --username AWS --password-stdin $ECR_REGISTRY >/dev/null 2>&1
  sudo docker pull $ECR_REPO:$TARGET
  # Retag locally as :latest so the existing compose (which uses :latest) picks it up
  sudo docker tag $ECR_REPO:$TARGET $ECR_REPO:latest
  sudo docker compose -f $COMPOSE up -d >/dev/null 2>&1
  echo '$TARGET' | sudo tee /opt/app/.deployed_tag >/dev/null
"
ok "rolled back to $TARGET"

log "Health check"
for i in $(seq 1 20); do
  code=$(curl -s -m 10 -o /dev/null -w '%{http_code}' -u "${BASIC_AUTH_USER:-admin}:${BASIC_AUTH_PASS:-}" "$APP_URL/api/health" || true)
  if [ "$code" = "200" ]; then ok "healthy after rollback"; exit 0; fi
  sleep 3
done
die "Still unhealthy after rollback (HTTP: $code). Manual intervention needed."

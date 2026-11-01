#!/usr/bin/env bash
# Build → push → deploy → health-check, in one command.
# Tags each image with the git short SHA (for rollback) and 'latest'.
#
#   scripts/redeploy.sh
#
. "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/_common.sh"

cd "$REPO_ROOT"

TAG="$(git rev-parse --short HEAD 2>/dev/null || date +%s)"
IMAGE_SHA="$ECR_REPO:$TAG"
IMAGE_LATEST="$ECR_REPO:latest"

log "Building image ($TAG)"
$DOCKER build -t "$IMAGE_SHA" -t "$IMAGE_LATEST" . >/dev/null
ok "built $IMAGE_SHA"

log "Pushing to ECR"
ecr_login_local
$DOCKER push "$IMAGE_SHA" >/dev/null
$DOCKER push "$IMAGE_LATEST" >/dev/null
ok "pushed $TAG + latest"

log "Recording current image as rollback target"
# Save the tag that is about to be replaced, so rollback.sh can find it.
PREV=$(ssh_ec2 "cat /opt/app/.deployed_tag 2>/dev/null || echo none")
ssh_ec2 "echo '$PREV' | sudo tee /opt/app/.previous_tag >/dev/null; echo '$TAG' | sudo tee /opt/app/.deployed_tag >/dev/null"
ok "previous=$PREV  new=$TAG"

log "Deploying on EC2 (pull + recreate)"
ssh_ec2 "
  set -e
  cd /opt/app
  aws ecr get-login-password --region $AWS_REGION | sudo docker login --username AWS --password-stdin $ECR_REGISTRY >/dev/null 2>&1
  sudo docker compose -f $COMPOSE pull app >/dev/null 2>&1
  sudo docker compose -f $COMPOSE up -d >/dev/null 2>&1
" 
ok "containers recreated"

log "Health check"
for i in $(seq 1 20); do
  code=$(curl -s -m 10 -o /dev/null -w '%{http_code}' -u "${BASIC_AUTH_USER:-admin}:${BASIC_AUTH_PASS:-}" "$APP_URL/api/health" || true)
  if [ "$code" = "200" ]; then
    ok "healthy (HTTP 200) at $APP_URL"
    echo
    echo "Deployed tag: $TAG"
    exit 0
  fi
  sleep 3
done

die "Health check FAILED after deploy (last HTTP: $code). Consider: scripts/rollback.sh"

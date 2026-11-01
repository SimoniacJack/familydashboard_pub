#!/usr/bin/env bash
# Nightly Postgres backup -> S3. Runs ON the EC2 host (via cron). Uses the
# instance IAM role for S3 (no credentials on the box). Dumps the Postgres
# container, gzips, and uploads a timestamped object. Safe to run by hand too.
set -euo pipefail

BUCKET="familydashboard-backups-YOUR_AWS_ACCOUNT_ID"
REGION="eu-west-2"
DB_CONTAINER="app-db-1"
DB_USER="familydash"
DB_NAME="familydashboard"

TS="$(date -u +%Y-%m-%dT%H-%M-%SZ)"
KEY="backups/${DB_NAME}-${TS}.sql.gz"
TMP="$(mktemp /tmp/dbbackup-XXXXXX.sql.gz)"
trap 'rm -f "$TMP"' EXIT

echo "[$(date -u)] dumping ${DB_NAME} from ${DB_CONTAINER}..."
sudo docker exec "$DB_CONTAINER" pg_dump -U "$DB_USER" "$DB_NAME" | gzip -9 > "$TMP"

SIZE="$(du -h "$TMP" | cut -f1)"
echo "[$(date -u)] uploading ${SIZE} -> s3://${BUCKET}/${KEY}"
aws s3 cp "$TMP" "s3://${BUCKET}/${KEY}" --region "$REGION"

echo "[$(date -u)] backup complete: s3://${BUCKET}/${KEY}"

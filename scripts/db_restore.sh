#!/usr/bin/env bash
# Restore a Postgres backup from S3 into the running container. Runs ON the EC2.
# RUN BY HAND, never automatically — this OVERWRITES the live database.
#
#   ./db_restore.sh                  # list available backups
#   ./db_restore.sh <s3-key>         # restore that backup (prompts to confirm)
#
# Example: ./db_restore.sh backups/familydashboard-2026-11-02T03-00-00Z.sql.gz
set -euo pipefail

BUCKET="familydashboard-backups-YOUR_AWS_ACCOUNT_ID"
REGION="eu-west-2"
DB_CONTAINER="app-db-1"
DB_USER="familydash"
DB_NAME="familydashboard"

if [ $# -eq 0 ]; then
  echo "Available backups (newest last):"
  aws s3 ls "s3://${BUCKET}/backups/" --region "$REGION" | sort
  echo
  echo "Usage: $0 <s3-key>   e.g. $0 backups/${DB_NAME}-<timestamp>.sql.gz"
  exit 0
fi

KEY="$1"
echo "!! This will OVERWRITE the live '${DB_NAME}' database with: s3://${BUCKET}/${KEY}"
read -r -p "Type 'restore' to continue: " confirm
[ "$confirm" = "restore" ] || { echo "aborted"; exit 1; }

TMP="$(mktemp /tmp/dbrestore-XXXXXX.sql.gz)"
trap 'rm -f "$TMP"' EXIT

echo "downloading..."
aws s3 cp "s3://${BUCKET}/${KEY}" "$TMP" --region "$REGION"

echo "restoring into ${DB_CONTAINER}..."
# Drop & recreate the schema cleanly, then load the dump.
gunzip -c "$TMP" | sudo docker exec -i "$DB_CONTAINER" psql -U "$DB_USER" -d "$DB_NAME"

echo "restore complete. Restart the app container if needed: sudo docker restart app-app-1"

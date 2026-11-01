#!/bin/bash
# End-to-end deploy helper. Run from the infra/ directory.
#   ./deploy.sh
# Requires: terraform, docker, awscli configured, terraform.tfvars filled in.
set -euo pipefail

cd "$(dirname "$0")"
REGION=$(grep -E '^aws_region' terraform.tfvars 2>/dev/null | cut -d'"' -f2 || echo "eu-west-2")

echo "==> 1/4  Provision ECR + infra (terraform apply)"
terraform init -input=false
terraform apply -auto-approve

ECR_URL=$(terraform output -raw ecr_repository_url)
REGISTRY=$(echo "$ECR_URL" | cut -d/ -f1)
echo "    ECR: $ECR_URL"

echo "==> 2/4  Build the image locally"
docker build -t "$ECR_URL:latest" ..

echo "==> 3/4  Push to ECR"
aws ecr get-login-password --region "$REGION" | docker login --username AWS --password-stdin "$REGISTRY"
docker push "$ECR_URL:latest"

echo "==> 4/4  Restart the app on the instance to pull the new image"
echo "    (On first deploy the instance may already be pulling via user-data.)"
echo
echo "Done. App URL:"
terraform output -raw app_url
echo
echo "If the app isn't up yet, SSH in and run:"
echo "  docker compose -f /opt/app/docker-compose.prod.yml up -d"

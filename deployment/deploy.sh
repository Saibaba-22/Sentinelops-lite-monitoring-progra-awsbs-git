#!/usr/bin/env bash
#
# SentinelOps-Lite — AWS Elastic Beanstalk deployment helper
#
# What it does:
#   1. Builds the Python application Docker image.
#   2. Pushes it to Amazon ECR (creating the repository if needed).
#   3. Injects the pushed image URI into deployment/Dockerrun.aws.json.
#   4. Packages the source bundle (excluding dev artifacts) and deploys
#      it to an Elastic Beanstalk Multi-container Docker environment.
#
# Prerequisites:
#   - AWS CLI v2 configured (aws configure) with ecr:*, elasticbeanstalk:* perms
#   - Docker daemon running
#   - (optional) Elastic Beanstalk CLI: `pip install awsebcli`
#   - An EB application + Multi-container Docker environment already created
#
# Usage:
#   ./deployment/deploy.sh
#   APP_NAME=my-app ENV_NAME=my-env AWS_REGION=us-east-1 ./deployment/deploy.sh
#
set -euo pipefail

# ---- Configuration (override via environment) -------------------------------
APP_NAME="${APP_NAME:-sentinelops-lite}"
ENV_NAME="${ENV_NAME:-sentinelops-lite-prod}"
AWS_REGION="${AWS_REGION:-us-east-1}"
IMAGE_NAME="${IMAGE_NAME:-sentinelops-lite}"
IMAGE_TAG="${IMAGE_TAG:-latest}"
PLATFORM="${PLATFORM:-Docker running on 64bit Amazon Linux 2023}"

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DOCKERRUN="${ROOT_DIR}/deployment/Dockerrun.aws.json"
BUNDLE="${ROOT_DIR}/deployment/.bundle/Dockerrun.zip"

echo "==> Building application image"
docker build -f "${ROOT_DIR}/docker/Dockerfile" -t "${IMAGE_NAME}:${IMAGE_TAG}" "${ROOT_DIR}"

echo "==> Authenticating to Amazon ECR"
aws ecr get-login-password --region "${AWS_REGION}" \
  | docker login --username AWS --password-stdin "$(aws sts get-caller-identity --query Account --output text).dkr.ecr.${AWS_REGION}.amazonaws.com"

ACCOUNT_ID="$(aws sts get-caller-identity --query Account --output text)"
ECR_URI="${ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com/${IMAGE_NAME}:${IMAGE_TAG}"

echo "==> Ensuring ECR repository exists"
aws ecr describe-repositories --repository-names "${IMAGE_NAME}" --region "${AWS_REGION}" >/dev/null 2>&1 \
  || aws ecr create-repository --repository-name "${IMAGE_NAME}" --region "${AWS_REGION}" >/dev/null

echo "==> Tagging and pushing image -> ${ECR_URI}"
docker tag "${IMAGE_NAME}:${IMAGE_TAG}" "${ECR_URI}"
docker push "${ECR_URI}"

echo "==> Injecting image URI into Dockerrun.aws.json"
if [[ "$OSTYPE" == "darwin"* ]]; then
  sed -i '' "s|REPLACE_WITH_ECR_IMAGE_URI|${ECR_URI}|g" "${DOCKERRUN}"
else
  sed -i "s|REPLACE_WITH_ECR_IMAGE_URI|${ECR_URI}|g" "${DOCKERRUN}"
fi

echo "==> Packaging source bundle"
rm -rf "${ROOT_DIR}/deployment/.bundle"
mkdir -p "${ROOT_DIR}/deployment/.bundle"
(
  cd "${ROOT_DIR}"
  zip -r -q "${BUNDLE}" \
    app.py agent.py agent_monitor.py requirements.txt test_app.py \
    monitoring docker deployment static templates \
    --exclude "*.pyc" --exclude "__pycache__/*" --exclude "*.md" \
    --exclude "logs/*" --exclude "docs/*" --exclude ".git/*"
)

echo "==> Deploying to Elastic Beanstalk (${APP_NAME}/${ENV_NAME})"
if command -v eb >/dev/null 2>&1; then
  eb deploy "${ENV_NAME}" --label "build-$(date +%Y%m%d-%H%M%S)"
else
  echo "EB CLI not found. Upload '${BUNDLE}' manually via the EB Console,"
  echo "or install it:  pip install awsebcli"
fi

echo "==> Done."

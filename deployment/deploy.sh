#!/usr/bin/env bash
#
# SentinelOps-Lite — AWS Elastic Beanstalk deployment helper (Docker Hub)
#
# What it does:
#   1. Builds the Python application Docker image.
#   2. Logs in to Docker Hub and PUSHES the image (no AWS ECR needed).
#   3. Injects the Docker Hub image URI into deployment/Dockerrun.aws.json.
#   4. Packages the source bundle and deploys it to an Elastic Beanstalk
#      Multi-container Docker environment.
#
# Prerequisites:
#   - Docker daemon available (e.g. GitHub-hosted ubuntu-latest).
#   - AWS CLI v2 + EB CLI configured (aws configure) with perms for EB.
#   - An EB application + Multi-container Docker environment already created.
#
# Required env:
#   APP_NAME, ENV_NAME, AWS_REGION        (EB)
#   DOCKERHUB_USERNAME, DOCKERHUB_TOKEN    (Docker Hub push auth)
#   Optional: IMAGE_NAME, IMAGE_TAG, PLATFORM
#
set -euo pipefail

APP_NAME="${APP_NAME:-sentinelops-lite}"
ENV_NAME="${ENV_NAME:-sentinelops-lite-prod}"
AWS_REGION="${AWS_REGION:-us-east-1}"
IMAGE_NAME="${IMAGE_NAME:-sentinelops-lite}"
IMAGE_TAG="${IMAGE_TAG:-latest}"
DOCKERHUB_USERNAME="${DOCKERHUB_USERNAME:?Set DOCKERHUB_USERNAME}"
DOCKERHUB_TOKEN="${DOCKERHUB_TOKEN:?Set DOCKERHUB_TOKEN}"
PLATFORM="${PLATFORM:-Multi-container Docker running on 64bit Amazon Linux 2023}"

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DOCKERRUN="${ROOT_DIR}/deployment/Dockerrun.aws.json"
BUNDLE="${ROOT_DIR}/deployment/.bundle/Dockerrun.zip"

DOCKERHUB_IMAGE="${DOCKERHUB_USERNAME}/${IMAGE_NAME}:${IMAGE_TAG}"

echo "==> Building application image"
docker build -f "${ROOT_DIR}/docker/Dockerfile" -t "${DOCKERHUB_IMAGE}" "${ROOT_DIR}"

echo "==> Authenticating to Docker Hub"
echo "${DOCKERHUB_TOKEN}" | docker login -u "${DOCKERHUB_USERNAME}" --password-stdin

echo "==> Pushing image -> ${DOCKERHUB_IMAGE}"
docker push "${DOCKERHUB_IMAGE}"

echo "==> Injecting Docker Hub image URI into Dockerrun.aws.json"
if [[ "$OSTYPE" == "darwin"* ]]; then
  sed -i '' "s|REPLACE_WITH_ECR_IMAGE_URI|${DOCKERHUB_IMAGE}|g" "${DOCKERRUN}"
else
  sed -i "s|REPLACE_WITH_ECR_IMAGE_URI|${DOCKERHUB_IMAGE}|g" "${DOCKERRUN}"
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

echo "==> Initialising EB CLI in this directory"
# Non-interactive init: sets platform + region + application.
eb init -p "${PLATFORM}" -r "${AWS_REGION}" "${APP_NAME}"

echo "==> Deploying to Elastic Beanstalk (${APP_NAME}/${ENV_NAME})"
if command -v eb >/dev/null 2>&1; then
  eb deploy "${ENV_NAME}" --label "build-$(date +%Y%m%d-%H%M%S)"
else
  echo "EB CLI not found. Upload '${BUNDLE}' manually via the EB Console."
fi

echo "==> Done."

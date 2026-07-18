#!/usr/bin/env bash
#
# SentinelOps-Lite — AWS Elastic Beanstalk deployment helper (Docker Hub)
#
# What it does:
#   1. Builds the Python application Docker image.
#   2. Logs in to Docker Hub and PUSHES the image (no AWS ECR needed).
#   3. Injects the Docker Hub image URI into the root Dockerrun.aws.json (v2).
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
IMAGE_NAME=$(basename "$GITHUB_REPOSITORY" | tr '[:upper:]' '[:lower:]')
IMAGE_TAG="${GITHUB_SHA:-latest}"
IMAGE_TAG="${IMAGE_TAG:0:7}"
DOCKERHUB_USERNAME="${DOCKERHUB_USERNAME:?Set DOCKERHUB_USERNAME}"
DOCKERHUB_TOKEN="${DOCKERHUB_TOKEN:?Set DOCKERHUB_TOKEN}"
PLATFORM="${PLATFORM:-}"

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# The ECS ("running ECS") platform uses a Dockerrun.aws.json v2 (ECS task
# definition) at the repo root. deploy.sh injects the built image URI into the
# app container's image field. The file MUST sit at the repo root so `eb deploy`
# packages it at the bundle root. (docker-compose.yml is kept for local dev only.)
DOCKERRUN_FILE="${ROOT_DIR}/Dockerrun.aws.json"

DOCKERHUB_IMAGE="${DOCKERHUB_USERNAME}/${IMAGE_NAME}:${IMAGE_TAG}"
echo "Docker image: ${DOCKERHUB_IMAGE}"
echo "Repository: ${GITHUB_REPOSITORY}"
echo "Commit: ${GITHUB_SHA}"

echo "==> Building application image"
docker build -f "${ROOT_DIR}/docker/Dockerfile" -t "${DOCKERHUB_IMAGE}" "${ROOT_DIR}"

echo "==> Authenticating to Docker Hub"
echo "${DOCKERHUB_TOKEN}" | docker login -u "${DOCKERHUB_USERNAME}" --password-stdin

echo "==> Pushing image -> ${DOCKERHUB_IMAGE}"
docker push "${DOCKERHUB_IMAGE}"

echo "==> Injecting Docker Hub image URI into Dockerrun.aws.json (v2)"
if [[ "$OSTYPE" == "darwin"* ]]; then
  sed -i '' "s|REPLACE_WITH_ECR_IMAGE_URI|${DOCKERHUB_IMAGE}|g" "${DOCKERRUN_FILE}"
else
  sed -i "s|REPLACE_WITH_ECR_IMAGE_URI|${DOCKERHUB_IMAGE}|g" "${DOCKERRUN_FILE}"
fi

echo "========================================="
echo "Dockerrun.aws.json after replacement:"
cat "${DOCKERRUN_FILE}"
echo "========================================="

# `eb deploy` packages the current (repo) directory itself, so no manual
# bundling is needed — Dockerrun.aws.json and .ebextensions are already at the
# repo root (see above). Just make sure the AWS CLI is available.

# Ensure the AWS CLI is available (used to query the exact platform name).
if ! command -v aws >/dev/null 2>&1; then
  echo "==> AWS CLI not found — installing"
  pip install -q awscli || pip install -q aws-cli
fi

# Detect the EXACT multi-container Docker (ECS) platform for this region and USE it.
# NOTE: AWS rebranded "Multi-container Docker" to "running ECS" on newer regions
# (e.g. us-east-1). Dockerrun.aws.json v2 works on BOTH, but the literal string
# "Multi-container Docker" no longer exists there, so a naive match returns empty.
# We match "running ECS" first (preferring Amazon Linux 2023), then fall back to
# the legacy "Multi-container Docker" name. No hardcoded platform anywhere.
if [ -z "${PLATFORM}" ]; then
  detect_platform() {
    local region="$1"
    local candidates=(
      "SolutionStacks[?contains(@, 'running ECS') && contains(@, 'Amazon Linux 2023')] | [0]"
      "SolutionStacks[?contains(@, 'running ECS')] | [0]"
      "SolutionStacks[?contains(@, 'Multi-container Docker')] | [0]"
    )
    for q in "${candidates[@]}"; do
      local p
      p=$(aws elasticbeanstalk list-available-solution-stacks \
            --region "${region}" --query "${q}" --output text 2>/dev/null)
      if [ -n "${p}" ] && [ "${p}" != "None" ]; then
        echo "${p}"
        return 0
      fi
    done
    return 1
  }
  echo "==> Detecting multi-container Docker (ECS) platform in ${AWS_REGION}"
  PLATFORM=$(detect_platform "${AWS_REGION}") || true
  if [ -z "${PLATFORM}" ] || [ "${PLATFORM}" = "None" ]; then
    echo "ERROR: could not auto-detect a multi-container Docker (ECS) platform in ${AWS_REGION}."
    echo "This region has no multi-container Docker platform. Available Docker platforms:"
    aws elasticbeanstalk list-available-solution-stacks \
      --region "${AWS_REGION}" \
      --query "SolutionStacks[?contains(@, 'Docker')]" --output text 2>/dev/null || true
    exit 1
  fi
  echo "   detected and using: ${PLATFORM}"
fi

echo "==> Initialising EB CLI in this directory"
eb init -p "${PLATFORM}" -r "${AWS_REGION}" "${APP_NAME}"

echo "==> Ensuring environment '${ENV_NAME}' exists"
if ! eb status "${ENV_NAME}" >/dev/null 2>&1; then
  echo "   environment not found — creating (single-instance, free-tier friendly)"
  eb create "${ENV_NAME}" --platform "${PLATFORM}" --region "${AWS_REGION}" --single --instance-type t3.small
fi

echo "==> Deploying to Elastic Beanstalk (${APP_NAME}/${ENV_NAME})"
echo "===== Files in repository root ====="
ls -la

echo "===== App image in Dockerrun ====="
grep '"image"' Dockerrun.aws.json
eb deploy "${ENV_NAME}" --label "build-$(date +%Y%m%d-%H%M%S)"

echo "==> Done."

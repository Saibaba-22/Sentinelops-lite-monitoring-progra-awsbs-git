#!/usr/bin/env bash
# SentinelOps-Lite — AWS Elastic Beanstalk deployment helper (Docker Hub)
set -euo pipefail

APP_NAME="${APP_NAME:-sentinelops-lite}"
ENV_NAME="${ENV_NAME:-sentinelops-lite-prod}"
AWS_REGION="${AWS_REGION:-us-east-1}"
IMAGE_NAME="${IMAGE_NAME:-sentinelops-lite}"
IMAGE_TAG="${IMAGE_TAG:-latest}"
DOCKERHUB_USERNAME="${DOCKERHUB_USERNAME:?Set DOCKERHUB_USERNAME}"
DOCKERHUB_TOKEN="${DOCKERHUB_TOKEN:?Set DOCKERHUB_TOKEN}"
PLATFORM="${PLATFORM:-}"

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# Dockerrun.aws.json and .ebextensions MUST sit at the REPO ROOT so that
# `eb deploy` packages them at the root of the source bundle.
DOCKERRUN="${ROOT_DIR}/Dockerrun.aws.json"

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

# Ensure the AWS CLI is available.
if ! command -v aws >/dev/null 2>&1; then
  echo "==> AWS CLI not found — installing"
  pip install -q awscli || pip install -q aws-cli
fi

# Detect the EXACT multi-container Docker (ECS) platform for this region.
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
        echo "${p}"; return 0
      fi
    done
    return 1
  }
  echo "==> Detecting multi-container Docker (ECS) platform in ${AWS_REGION}"
  PLATFORM=$(detect_platform "${AWS_REGION}") || true
  if [ -z "${PLATFORM}" ] || [ "${PLATFORM}" = "None" ]; then
    echo "ERROR: could not auto-detect a multi-container Docker (ECS) platform in ${AWS_REGION}."
    aws elasticbeanstalk list-available-solution-stacks \
      --region "${AWS_REGION}" --query "SolutionStacks[?contains(@, 'Docker')]" --output text 2>/dev/null || true
    exit 1
  fi
  echo "   detected and using: ${PLATFORM}"
fi

echo "==> Initialising EB CLI in this directory"
eb init -p "${PLATFORM}" -r "${AWS_REGION}" "${APP_NAME}"

echo "==> Ensuring environment '${ENV_NAME}' exists"
if ! eb status "${ENV_NAME}" >/dev/null 2>&1; then
  eb create "${ENV_NAME}" --platform "${PLATFORM}" --region "${AWS_REGION}" --single --instance-type t3.micro
fi

echo "==> Deploying to Elastic Beanstalk (${APP_NAME}/${ENV_NAME})"
eb deploy "${ENV_NAME}" --label "build-$(date +%Y%m%d-%H%M%S)"
echo "==> Done."
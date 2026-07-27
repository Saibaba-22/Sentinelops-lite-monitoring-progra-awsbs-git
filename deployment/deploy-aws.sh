#!/usr/bin/env bash
#
# SentinelOps-Lite — AWS Elastic Beanstalk deployment helper (Docker Hub)
#
# What it does:
#   1. Builds the Python application Docker image.
#   2. Logs in to Docker Hub and PUSHES the image.
#   3. Resolves EB CNAME and injects Docker Hub image URI + monitoring URLs
#      into docker-compose.yml (the file EB reads for multi-container).
#   4. Selects AWS-specific nginx config.
#   5. Deploys to an Elastic Beanstalk Multi-container Docker environment.
#
# Required env:
#   APP_NAME, ENV_NAME, AWS_REGION        (EB)
#   DOCKERHUB_USERNAME, DOCKERHUB_TOKEN    (Docker Hub push auth)

set -euo pipefail

APP_NAME="${APP_NAME:-sentinelops-lite}"
ENV_NAME="${ENV_NAME:-sentinelops-lite-prod}"
AWS_REGION="${AWS_REGION:-us-east-1}"
IMAGE_NAME="${REPOSITORY:?Set REPOSITORY}"
IMAGE_TAG="${GITHUB_SHA:0:7}"
DOCKERHUB_USERNAME="${DOCKERHUB_USERNAME:?Set DOCKERHUB_USERNAME}"
DOCKERHUB_TOKEN="${DOCKERHUB_TOKEN:?Set DOCKERHUB_TOKEN}"
PLATFORM="${PLATFORM:-}"

export DOCKERHUB_USERNAME
export IMAGE_NAME
export IMAGE_TAG

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
COMPOSE_FILE="${ROOT_DIR}/docker-compose.yml"

DOCKERHUB_IMAGE="${DOCKERHUB_USERNAME}/${IMAGE_NAME}:${IMAGE_TAG}"

echo "===================================="
echo "DOCKERHUB_USERNAME=${DOCKERHUB_USERNAME}"
echo "IMAGE_NAME=${IMAGE_NAME}"
echo "IMAGE_TAG=${IMAGE_TAG}"
echo "DOCKERHUB_IMAGE=${DOCKERHUB_IMAGE}"
echo "===================================="

# ─── Build & Push ───

echo "==> Building application image"
docker build -f "${ROOT_DIR}/docker/Dockerfile" -t "${DOCKERHUB_IMAGE}" "${ROOT_DIR}"

echo "==> Authenticating to Docker Hub"
echo "${DOCKERHUB_TOKEN}" | docker login -u "${DOCKERHUB_USERNAME}" --password-stdin

echo "==> Pushing image -> ${DOCKERHUB_IMAGE}"
docker push "${DOCKERHUB_IMAGE}"

# ─── Resolve EB CNAME for monitoring URLs ───

echo "==> Resolving EB environment CNAME for monitoring URLs"
EB_CNAME=$(aws elasticbeanstalk describe-environments \
  --application-name "${APP_NAME}" \
  --environment-names "${ENV_NAME}" \
  --region "${AWS_REGION}" \
  --query 'Environments[0].CNAME' \
  --output text 2>/dev/null || echo "")

if [ -z "${EB_CNAME}" ] || [ "${EB_CNAME}" = "None" ]; then
  echo "WARNING: Could not resolve EB CNAME. Monitoring URLs will remain placeholders."
  PROM_URL="replace_with_prometheus_url"
  GF_DOMAIN="replace_with_gf_server_domain"
  GF_ROOT_URL="replace_with_gf_server_root_url"
else
  echo "   EB CNAME: ${EB_CNAME}"
  PROM_URL="http://${EB_CNAME}/prometheus/"
  GF_DOMAIN="${EB_CNAME}"
  GF_ROOT_URL="http://${EB_CNAME}/grafana/"
  echo "   PROMETHEUS_URL:    ${PROM_URL}"
  echo "   GF_SERVER_DOMAIN:  ${GF_DOMAIN}"
  echo "   GF_SERVER_ROOT_URL: ${GF_ROOT_URL}"
fi

# ─── Select AWS nginx config ───

echo "==> Selecting AWS nginx config"
cp "${ROOT_DIR}/docker/nginx/nginx-aws.conf" "${ROOT_DIR}/docker/nginx/default.conf"

# ─── Update docker-compose.yml ───

echo "==> Replacing placeholders in docker-compose.yml"

# Image placeholder
sed -i "s|replace_with_dockerhub_image_uri|${DOCKERHUB_IMAGE}|g" "${COMPOSE_FILE}"

# Monitoring URL placeholders
sed -i "s|replace_with_prometheus_url|${PROM_URL}|g" "${COMPOSE_FILE}"
sed -i "s|replace_with_gf_server_domain|${GF_DOMAIN}|g" "${COMPOSE_FILE}"
sed -i "s|replace_with_gf_server_root_url|${GF_ROOT_URL}|g" "${COMPOSE_FILE}"

# App env placeholders
sed -i "s|replace_with_build_number|${GITHUB_SHA}|g" "${COMPOSE_FILE}"
sed -i "s|replace_with_environment|production|g" "${COMPOSE_FILE}"

# ─── Verify no placeholders remain ───

echo "========== VERIFY COMPOSE =========="

for placeholder in \
  "replace_with_dockerhub_image_uri" \
  "replace_with_prometheus_url" \
  "replace_with_gf_server_domain" \
  "replace_with_gf_server_root_url" \
  "replace_with_build_number" \
  "replace_with_environment"; do
  if grep -q "${placeholder}" "${COMPOSE_FILE}" 2>/dev/null; then
    echo "ERROR: Placeholder '${placeholder}' still exists!"
    exit 1
  fi
done
echo "✅ All placeholders replaced successfully."

echo "========== Images =========="
grep "image:" "${COMPOSE_FILE}"

echo "========== Monitoring URLs =========="
grep "PROMETHEUS_URL" "${COMPOSE_FILE}"
grep "GF_SERVER" "${COMPOSE_FILE}"

echo "========== FINAL COMPOSE =========="
cat "${COMPOSE_FILE}"

# ─── EB CLI Setup & Deploy ───

if ! command -v aws >/dev/null 2>&1; then
  echo "==> AWS CLI not found — installing"
  pip install -q awscli || pip install -q aws-cli
fi

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
    echo "ERROR: could not auto-detect platform in ${AWS_REGION}."
    exit 1
  fi
  echo "   detected: ${PLATFORM}"
fi

echo "==> Initialising EB CLI"
eb init -p "${PLATFORM}" -r "${AWS_REGION}" "${APP_NAME}"

echo "==> Ensuring environment '${ENV_NAME}' exists"
if ! eb status "${ENV_NAME}" >/dev/null 2>&1; then
  echo "   creating..."
  eb create "${ENV_NAME}" --platform "${PLATFORM}" --region "${AWS_REGION}" --single --instance-type c7i.flex.large
fi

echo "==> Deploying to Elastic Beanstalk (${APP_NAME}/${ENV_NAME})"
echo "===== App image ====="
grep "image:" "${COMPOSE_FILE}"

echo "===== Monitoring URLs ====="
grep "PROMETHEUS_URL" "${COMPOSE_FILE}" || echo "No PROMETHEUS_URL"
grep "GF_SERVER" "${COMPOSE_FILE}" || echo "No GF_SERVER"

eb deploy "${ENV_NAME}" --label "build-$(date +%Y%m%d-%H%M%S)"

echo "==> Done. ✅"
echo ""
echo "========== ACCESS URLs =========="
if [ -n "${EB_CNAME}" ] && [ "${EB_CNAME}" != "None" ]; then
  echo "App:          http://${EB_CNAME}/"
  echo "Prometheus:   http://${EB_CNAME}/prometheus/"
  echo "Grafana:      http://${EB_CNAME}/grafana/"
  echo "Monitor:      http://${EB_CNAME}/monitor/status"
  echo "  Login: admin / admin123"
  echo "  ✅ Dashboards auto-loaded — data shows immediately!"
fi

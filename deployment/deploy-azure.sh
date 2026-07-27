#!/usr/bin/env bash
#
# SentinelOps-Lite — Azure App Service deployment helper (Docker Hub)
#
# What it does:
#   1. Builds the Python application Docker image.
#   2. Logs in to Docker Hub and PUSHES the image.
#   3. Resolves Azure App Service hostname for monitoring URLs.
#   4. Injects image URI + monitoring URLs into docker-compose.azure.yml.
#   5. Deploys multi-container (app + prometheus + grafana + nginx + node-exporter)
#      to Azure App Service via docker-compose.
#
# Prerequisites:
#   - Docker daemon available (e.g. GitHub-hosted ubuntu-latest).
#   - Azure CLI logged in (az login) with perms for App Service.
#   - App Service plan (Linux, Docker) already created.
#
# Required env:
#   AZURE_WEBAPP_NAME, AZURE_RESOURCE_GROUP    (Azure)
#   DOCKERHUB_USERNAME, DOCKERHUB_TOKEN         (Docker Hub push auth)

set -euo pipefail

AZURE_WEBAPP_NAME="${AZURE_WEBAPP_NAME:?Set AZURE_WEBAPP_NAME}"
AZURE_RESOURCE_GROUP="${AZURE_RESOURCE_GROUP:?Set AZURE_RESOURCE_GROUP}"
IMAGE_NAME="${REPOSITORY:?Set REPOSITORY}"
IMAGE_TAG="${GITHUB_SHA:0:7}"
DOCKERHUB_USERNAME="${DOCKERHUB_USERNAME:?Set DOCKERHUB_USERNAME}"
DOCKERHUB_TOKEN="${DOCKERHUB_TOKEN:?Set DOCKERHUB_TOKEN}"

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
COMPOSE_FILE="${ROOT_DIR}/docker-compose.azure.yml"
NGINX_SRC="${ROOT_DIR}/docker/nginx/nginx-azure.conf"
NGINX_DST="${ROOT_DIR}/docker/nginx/default.conf"

DOCKERHUB_IMAGE="${DOCKERHUB_USERNAME}/${IMAGE_NAME}:${IMAGE_TAG}"

echo "===================================="
echo "DOCKERHUB_USERNAME=${DOCKERHUB_USERNAME}"
echo "IMAGE_NAME=${IMAGE_NAME}"
echo "IMAGE_TAG=${IMAGE_TAG}"
echo "DOCKERHUB_IMAGE=${DOCKERHUB_IMAGE}"
echo "AZURE_WEBAPP_NAME=${AZURE_WEBAPP_NAME}"
echo "AZURE_RESOURCE_GROUP=${AZURE_RESOURCE_GROUP}"
echo "===================================="

# ─── Build & Push ───

echo "==> Building application image"
docker build -f "${ROOT_DIR}/docker/Dockerfile" -t "${DOCKERHUB_IMAGE}" "${ROOT_DIR}"

echo "==> Authenticating to Docker Hub"
echo "${DOCKERHUB_TOKEN}" | docker login -u "${DOCKERHUB_USERNAME}" --password-stdin

echo "==> Pushing image -> ${DOCKERHUB_IMAGE}"
docker push "${DOCKERHUB_IMAGE}"

# ─── Resolve Azure hostname for monitoring URLs ───

echo "==> Resolving Azure App Service hostname"
AZURE_HOSTNAME=$(az webapp show \
  --name "${AZURE_WEBAPP_NAME}" \
  --resource-group "${AZURE_RESOURCE_GROUP}" \
  --query defaultHostName \
  -o tsv 2>/dev/null || echo "")

if [ -z "${AZURE_HOSTNAME}" ]; then
  echo "WARNING: Could not resolve Azure hostname. Using placeholder."
  PROM_URL="replace_with_prometheus_url"
  GF_DOMAIN="replace_with_gf_server_domain"
  GF_ROOT_URL="replace_with_gf_server_root_url"
  APP_URL="https://replace_with_app_url"
else
  echo "   Azure Hostname: ${AZURE_HOSTNAME}"
  PROM_URL="https://${AZURE_HOSTNAME}/prometheus/"
  GF_DOMAIN="${AZURE_HOSTNAME}"
  GF_ROOT_URL="https://${AZURE_HOSTNAME}/grafana/"
  APP_URL="https://${AZURE_HOSTNAME}/"
  echo "   PROMETHEUS_URL:    ${PROM_URL}"
  echo "   GF_SERVER_DOMAIN:  ${GF_DOMAIN}"
  echo "   GF_SERVER_ROOT_URL: ${GF_ROOT_URL}"
fi

# ─── Select nginx config for Azure ───

echo "==> Selecting Azure nginx config"
cp "${NGINX_SRC}" "${NGINX_DST}"

# ─── Update docker-compose.azure.yml ───

echo "==> Updating docker-compose.azure.yml with image and URLs"

sed -i "s|replace_with_dockerhub_image_uri|${DOCKERHUB_IMAGE}|g" "${COMPOSE_FILE}"
sed -i "s|replace_with_prometheus_url|${PROM_URL}|g" "${COMPOSE_FILE}"
sed -i "s|replace_with_gf_server_domain|${GF_DOMAIN}|g" "${COMPOSE_FILE}"
sed -i "s|replace_with_gf_server_root_url|${GF_ROOT_URL}|g" "${COMPOSE_FILE}"
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
grep "GRAFANA" "${COMPOSE_FILE}"

echo "========== FINAL COMPOSE =========="
cat "${COMPOSE_FILE}"

# ─── Deploy to Azure App Service ───

echo "==> Deploying to Azure App Service (${AZURE_WEBAPP_NAME})"

az webapp config container set \
  --name "${AZURE_WEBAPP_NAME}" \
  --resource-group "${AZURE_RESOURCE_GROUP}" \
  --multicontainer-config-type COMPOSE \
  --multicontainer-config-file "${COMPOSE_FILE}"

echo "==> Restarting Azure App Service"
az webapp restart \
  --name "${AZURE_WEBAPP_NAME}" \
  --resource-group "${AZURE_RESOURCE_GROUP}"

echo "==> Done. ✅"
echo ""
echo "========== ACCESS URLs =========="
if [ -n "${AZURE_HOSTNAME}" ]; then
  echo "App:          ${APP_URL}"
  echo "Prometheus:   ${PROM_URL}"
  echo "Grafana:      ${GF_ROOT_URL}"
  echo "  Login: admin / admin123"
  echo "  ✅ Dashboards auto-loaded — data shows immediately!"
fi

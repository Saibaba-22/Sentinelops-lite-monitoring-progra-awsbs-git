#!/usr/bin/env bash
#
# SentinelOps-Lite — Azure App Service deployment helper (Docker Hub)
#
# What it does:
#   1. Builds the Python application Docker image.
#   2. Logs in to Docker Hub and PUSHES the image.
#   3. Resolves Azure App Service hostname for monitoring URLs.
#   4. Injects image URI + monitoring URLs into docker-compose.azure.yml.
#   5. Deploys multi-container (app + prometheus + grafana + nginx)
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
#   GITHUB_SHA                                  (set by GitHub Actions)
#   REPOSITORY                                  (Docker Hub repo name)

set -euo pipefail

# ─── Required Variables ───
AZURE_WEBAPP_NAME="${AZURE_WEBAPP_NAME:?Set AZURE_WEBAPP_NAME}"
AZURE_RESOURCE_GROUP="${AZURE_RESOURCE_GROUP:?Set AZURE_RESOURCE_GROUP}"
IMAGE_NAME="${DOCKERHUB_REPOSITORY:-${REPOSITORY:?Set REPOSITORY}}"
IMAGE_TAG="${GITHUB_SHA}"
DOCKERHUB_USERNAME="${DOCKERHUB_USERNAME:?Set DOCKERHUB_USERNAME}"
DOCKERHUB_TOKEN="${DOCKERHUB_TOKEN:?Set DOCKERHUB_TOKEN}"
GRAFANA_ADMIN_PASSWORD="${GRAFANA_ADMIN_PASSWORD:?Set GRAFANA_ADMIN_PASSWORD}"
MONITOR_TOKEN="${MONITOR_TOKEN_AZURE:-${MONITOR_TOKEN:?Set MONITOR_TOKEN}}"

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
COMPOSE_SRC="${ROOT_DIR}/docker/docker-compose.azure.yml"
COMPOSE_TMP="/tmp/docker-compose.azure.yml"
NGINX_SRC="${ROOT_DIR}/docker/nginx/nginx-azure.conf"
NGINX_DST="${ROOT_DIR}/docker/nginx/default.conf"

APP_IMAGE="docker.io/${DOCKERHUB_USERNAME}/${IMAGE_NAME}:${IMAGE_TAG}"
NGINX_IMAGE="docker.io/${DOCKERHUB_USERNAME}/${IMAGE_NAME}:nginx-${IMAGE_TAG}"
PROMETHEUS_IMAGE="docker.io/${DOCKERHUB_USERNAME}/${IMAGE_NAME}:prometheus-${IMAGE_TAG}"
GRAFANA_IMAGE="docker.io/${DOCKERHUB_USERNAME}/${IMAGE_NAME}:grafana-${IMAGE_TAG}"

echo "===================================="
echo "DOCKERHUB_USERNAME  = ${DOCKERHUB_USERNAME}"
echo "IMAGE_NAME          = ${IMAGE_NAME}"
echo "IMAGE_TAG           = ${IMAGE_TAG}"
echo "APP_IMAGE           = ${APP_IMAGE}"
echo "AZURE_WEBAPP_NAME   = ${AZURE_WEBAPP_NAME}"
echo "AZURE_RESOURCE_GROUP= ${AZURE_RESOURCE_GROUP}"
echo "===================================="

# ─── Select nginx config for Azure ───
echo "==> Selecting Azure nginx config"
if [ -f "${NGINX_SRC}" ]; then
  cp "${NGINX_SRC}" "${NGINX_DST}"
  echo "   Using nginx-azure.conf"
else
  echo "   nginx-azure.conf not found, using nginx.conf"
  cp "${ROOT_DIR}/docker/nginx/nginx.conf" "${NGINX_DST}"
fi

# ─── Resolve Azure hostname for monitoring URLs ───
echo "==> Resolving Azure App Service hostname"
AZURE_HOSTNAME=$(az webapp show \
  --name "${AZURE_WEBAPP_NAME}" \
  --resource-group "${AZURE_RESOURCE_GROUP}" \
  --query defaultHostName \
  -o tsv 2>/dev/null || echo "")

if [ -z "${AZURE_HOSTNAME}" ]; then
  echo "ERROR: Could not resolve Azure hostname. Exiting."
  exit 1
fi

echo "   Azure Hostname      : ${AZURE_HOSTNAME}"
PROM_URL="https://${AZURE_HOSTNAME}/prometheus/"
GF_DOMAIN="${AZURE_HOSTNAME}"
GF_ROOT_URL="https://${AZURE_HOSTNAME}/grafana/"
APP_URL="https://${AZURE_HOSTNAME}"

echo "   PROMETHEUS_URL      : ${PROM_URL}"
echo "   GF_SERVER_DOMAIN    : ${GF_DOMAIN}"
echo "   GF_SERVER_ROOT_URL  : ${GF_ROOT_URL}"

# ─── Copy compose file to tmp and replace all placeholders ───
echo "==> Copying compose file to /tmp and replacing placeholders"
cp "${COMPOSE_SRC}" "${COMPOSE_TMP}"

sed -i \
  -e "s|__APP_IMAGE__|${APP_IMAGE}|g" \
  -e "s|__NGINX_IMAGE__|${NGINX_IMAGE}|g" \
  -e "s|__PROMETHEUS_IMAGE__|${PROMETHEUS_IMAGE}|g" \
  -e "s|__GRAFANA_IMAGE__|${GRAFANA_IMAGE}|g" \
  -e "s|__BUILD_NUMBER__|${GITHUB_SHA}|g" \
  -e "s|__ENVIRONMENT__|production|g" \
  -e "s|__GF_SERVER_DOMAIN__|${GF_DOMAIN}|g" \
  -e "s|__GF_SERVER_ROOT_URL__|${GF_ROOT_URL}|g" \
  -e "s|__PROMETHEUS_URL__|${PROM_URL}|g" \
  "${COMPOSE_TMP}"

# ─── Verify no placeholders remain ───
echo "==> Verifying all placeholders replaced"
UNRESOLVED=0
for placeholder in \
  "__APP_IMAGE__" \
  "__NGINX_IMAGE__" \
  "__PROMETHEUS_IMAGE__" \
  "__GRAFANA_IMAGE__" \
  "__BUILD_NUMBER__" \
  "__ENVIRONMENT__" \
  "__GF_SERVER_DOMAIN__" \
  "__GF_SERVER_ROOT_URL__" \
  "__PROMETHEUS_URL__" \
  "replace_with_"; do
  if grep -q "${placeholder}" "${COMPOSE_TMP}" 2>/dev/null; then
    echo "ERROR: Placeholder '${placeholder}' still exists in compose file!"
    UNRESOLVED=1
  fi
done

if [ "${UNRESOLVED}" = "1" ]; then
  echo "Unresolved placeholders found. Aborting."
  exit 1
fi
echo "✅ All placeholders replaced successfully."

# ─── Show final compose for debug ───
echo "========== Images =========="
grep "image:" "${COMPOSE_TMP}"

echo "========== Monitoring URLs =========="
grep -E "PROMETHEUS_URL|GRAFANA|GF_SERVER" "${COMPOSE_TMP}" || true

echo "========== FINAL COMPOSE =========="
cat "${COMPOSE_TMP}"

# ─── Configure Azure App Settings ───
echo "==> Setting Azure App Service application settings"
az webapp config appsettings set \
  --name "${AZURE_WEBAPP_NAME}" \
  --resource-group "${AZURE_RESOURCE_GROUP}" \
  --settings \
    WEBSITES_PORT=80 \
    WEBSITES_CONTAINER_START_TIME_LIMIT=1800 \
    DOCKER_REGISTRY_SERVER_URL=https://index.docker.io \
    DOCKER_REGISTRY_SERVER_USERNAME="${DOCKERHUB_USERNAME}" \
    DOCKER_REGISTRY_SERVER_PASSWORD="${DOCKERHUB_TOKEN}" \
    BUILD_NUMBER="${GITHUB_SHA}" \
    ENVIRONMENT=production \
    MONITOR_TOKEN="${MONITOR_TOKEN}" \
    GF_SECURITY_ADMIN_PASSWORD="${GRAFANA_ADMIN_PASSWORD}" \
    GF_SERVER_DOMAIN="${GF_DOMAIN}" \
    GF_SERVER_ROOT_URL="${GF_ROOT_URL}"

# ─── Deploy to Azure App Service ───
echo "==> Deploying to Azure App Service (${AZURE_WEBAPP_NAME})"
az webapp config container set \
  --name "${AZURE_WEBAPP_NAME}" \
  --resource-group "${AZURE_RESOURCE_GROUP}" \
  --multicontainer-config-type COMPOSE \
  --multicontainer-config-file "${COMPOSE_TMP}"

echo "==> Restarting Azure App Service"
az webapp restart \
  --name "${AZURE_WEBAPP_NAME}" \
  --resource-group "${AZURE_RESOURCE_GROUP}"

# ─── Health Check ───
echo "==> Waiting for app to be healthy..."
for attempt in $(seq 1 30); do
  code=$(curl -ksS -o /dev/null -w '%{http_code}' "${APP_URL}/health" || true)
  echo "Attempt ${attempt}/30: HTTP ${code}"
  if [ "${code}" = "200" ]; then
    echo "✅ App is healthy!"
    break
  fi
  if [ "${attempt}" = "30" ]; then
    echo "ERROR: App did not become healthy after 30 attempts."
    exit 1
  fi
  sleep 10
done

echo "==> Done. ✅"
echo ""
echo "========== ACCESS URLs =========="
echo "App:        ${APP_URL}"
echo "Prometheus: ${PROM_URL}"
echo "Grafana:    ${GF_ROOT_URL}"
echo "  Login:    admin / [your GRAFANA_ADMIN_PASSWORD]"
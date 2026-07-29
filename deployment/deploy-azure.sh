#!/usr/bin/env bash
set -euo pipefail

AZURE_WEBAPP_NAME="${AZURE_WEBAPP_NAME:?Set AZURE_WEBAPP_NAME}"
AZURE_RESOURCE_GROUP="${AZURE_RESOURCE_GROUP:?Set AZURE_RESOURCE_GROUP}"
IMAGE_NAME="${DOCKERHUB_REPOSITORY:-${REPOSITORY:?Set DOCKERHUB_REPOSITORY or REPOSITORY}}"
IMAGE_TAG="${GITHUB_SHA:?Set GITHUB_SHA}"
DOCKERHUB_USERNAME="${DOCKERHUB_USERNAME:?Set DOCKERHUB_USERNAME}"
DOCKERHUB_TOKEN="${DOCKERHUB_TOKEN:?Set DOCKERHUB_TOKEN}"
GRAFANA_ADMIN_PASSWORD="${GRAFANA_ADMIN_PASSWORD:?Set GRAFANA_ADMIN_PASSWORD}"
MONITOR_TOKEN="${MONITOR_TOKEN_AZURE:-${MONITOR_TOKEN:-}}"

if [ -z "${MONITOR_TOKEN}" ]; then
  echo "ERROR: Set MONITOR_TOKEN_AZURE or MONITOR_TOKEN"
  exit 1
fi

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
COMPOSE_SRC="${ROOT_DIR}/docker/docker-compose.azure.yml"
COMPOSE_TMP="/tmp/docker-compose.azure.yml"

APP_IMAGE="docker.io/${DOCKERHUB_USERNAME}/${IMAGE_NAME}:${IMAGE_TAG}"
NGINX_IMAGE="docker.io/${DOCKERHUB_USERNAME}/${IMAGE_NAME}:nginx-${IMAGE_TAG}"
PROMETHEUS_IMAGE="docker.io/${DOCKERHUB_USERNAME}/${IMAGE_NAME}:prometheus-${IMAGE_TAG}"
GRAFANA_IMAGE="docker.io/${DOCKERHUB_USERNAME}/${IMAGE_NAME}:grafana-${IMAGE_TAG}"

echo "====================================================="
echo " SentinelOps-Lite — Azure Deployment"
echo "====================================================="
echo "APP_IMAGE            = ${APP_IMAGE}"
echo "NGINX_IMAGE          = ${NGINX_IMAGE}"
echo "PROMETHEUS_IMAGE     = ${PROMETHEUS_IMAGE}"
echo "GRAFANA_IMAGE        = ${GRAFANA_IMAGE}"
echo "AZURE_WEBAPP_NAME    = ${AZURE_WEBAPP_NAME}"
echo "AZURE_RESOURCE_GROUP = ${AZURE_RESOURCE_GROUP}"
echo "====================================================="

if [ ! -f "${COMPOSE_SRC}" ]; then
  echo "ERROR: Missing ${COMPOSE_SRC}"
  exit 1
fi

# ─── Resolve Azure hostname ───
echo "==> Resolving Azure App Service hostname"
AZURE_HOSTNAME=$(az webapp show \
  --name "${AZURE_WEBAPP_NAME}" \
  --resource-group "${AZURE_RESOURCE_GROUP}" \
  --query defaultHostName \
  -o tsv 2>/dev/null || echo "")

if [ -z "${AZURE_HOSTNAME}" ]; then
  echo "ERROR: Could not resolve Azure hostname."
  exit 1
fi

APP_URL="https://${AZURE_HOSTNAME}"
GF_DOMAIN="${AZURE_HOSTNAME}"
GF_ROOT_URL="https://${AZURE_HOSTNAME}/grafana/"

echo "   Hostname           : ${AZURE_HOSTNAME}"
echo "   App URL            : ${APP_URL}"
echo "   GF_SERVER_DOMAIN   : ${GF_DOMAIN}"
echo "   GF_SERVER_ROOT_URL : ${GF_ROOT_URL}"

# ─── Replace placeholders ───
echo "==> Preparing docker-compose.azure.yml"
cp "${COMPOSE_SRC}" "${COMPOSE_TMP}"

sed -i \
  -e "s|__APP_IMAGE__|${APP_IMAGE}|g" \
  -e "s|__NGINX_IMAGE__|${NGINX_IMAGE}|g" \
  -e "s|__PROMETHEUS_IMAGE__|${PROMETHEUS_IMAGE}|g" \
  -e "s|__GRAFANA_IMAGE__|${GRAFANA_IMAGE}|g" \
  -e "s|__BUILD_NUMBER__|${IMAGE_TAG}|g" \
  -e "s|__ENVIRONMENT__|production|g" \
  -e "s|__GF_SERVER_DOMAIN__|${GF_DOMAIN}|g" \
  -e "s|__GF_SERVER_ROOT_URL__|${GF_ROOT_URL}|g" \
  -e "s|__MONITOR_TOKEN__|${MONITOR_TOKEN}|g" \
  -e "s|__GRAFANA_ADMIN_PASSWORD__|${GRAFANA_ADMIN_PASSWORD}|g" \
  "${COMPOSE_TMP}"

# Catch any leftover shell-style vars
sed -i \
  -e "s|\${MONITOR_TOKEN}|${MONITOR_TOKEN}|g" \
  -e "s|\${GF_SECURITY_ADMIN_PASSWORD}|${GRAFANA_ADMIN_PASSWORD}|g" \
  "${COMPOSE_TMP}"

# ─── Verify ───
echo "==> Verifying all placeholders resolved"
FAILED=0
for marker in "__APP_IMAGE__" "__NGINX_IMAGE__" "__PROMETHEUS_IMAGE__" "__GRAFANA_IMAGE__" \
  "__BUILD_NUMBER__" "__ENVIRONMENT__" "__GF_SERVER_DOMAIN__" "__GF_SERVER_ROOT_URL__" \
  "__MONITOR_TOKEN__" "__GRAFANA_ADMIN_PASSWORD__" "replace_with_"; do
  if grep -q "${marker}" "${COMPOSE_TMP}" 2>/dev/null; then
    echo "ERROR: Unresolved placeholder '${marker}'"
    FAILED=1
  fi
done
if [ "${FAILED}" = "1" ]; then
  cat "${COMPOSE_TMP}"
  exit 1
fi
echo "✅ All placeholders replaced."

echo "========== Final Compose =========="
cat "${COMPOSE_TMP}"
echo ""

# ─── App Settings ───
echo "==> Setting Azure App Service app settings"
az webapp config appsettings set \
  --name "${AZURE_WEBAPP_NAME}" \
  --resource-group "${AZURE_RESOURCE_GROUP}" \
  --settings \
    "WEBSITES_PORT=80" \
    "WEBSITES_WEB_CONTAINER_NAME=nginx" \
    "WEBSITES_CONTAINER_START_TIME_LIMIT=1800" \
    "DOCKER_REGISTRY_SERVER_URL=https://index.docker.io" \
    "DOCKER_REGISTRY_SERVER_USERNAME=${DOCKERHUB_USERNAME}" \
    "DOCKER_REGISTRY_SERVER_PASSWORD=${DOCKERHUB_TOKEN}" \
    "BUILD_NUMBER=${IMAGE_TAG}" \
    "ENVIRONMENT=production" \
    "MONITOR_TOKEN=${MONITOR_TOKEN}" \
    "GF_SECURITY_ADMIN_PASSWORD=${GRAFANA_ADMIN_PASSWORD}" \
    "GF_SERVER_DOMAIN=${GF_DOMAIN}" \
    "GF_SERVER_ROOT_URL=${GF_ROOT_URL}" \
  --output none

echo "✅ App settings configured."

# ─── Deploy ───
echo "==> Deploying to Azure App Service"
az webapp config container set \
  --name "${AZURE_WEBAPP_NAME}" \
  --resource-group "${AZURE_RESOURCE_GROUP}" \
  --multicontainer-config-type COMPOSE \
  --multicontainer-config-file "${COMPOSE_TMP}" \
  --output none

echo "==> Restarting Azure App Service"
az webapp restart \
  --name "${AZURE_WEBAPP_NAME}" \
  --resource-group "${AZURE_RESOURCE_GROUP}"

echo "==> Waiting 60 seconds for containers to start..."
sleep 60

# ─── Health Check ───
HEALTH_PATH="${APP_HEALTH_PATH:-/health}"
echo "==> Health check: ${APP_URL}${HEALTH_PATH}"
for attempt in $(seq 1 30); do
  code=$(curl -ksS -o /dev/null -w '%{http_code}' \
    --max-time 15 "${APP_URL}${HEALTH_PATH}" || true)
  echo "  Attempt ${attempt}/30: HTTP ${code}"
  if [ "${code}" = "200" ]; then
    echo "✅ App is healthy!"
    break
  fi
  if [ "${attempt}" = "30" ]; then
    echo "❌ App not healthy after 30 attempts."
    echo "==> Container logs:"
    az webapp log tail \
      --name "${AZURE_WEBAPP_NAME}" \
      --resource-group "${AZURE_RESOURCE_GROUP}" \
      --timeout 20 2>/dev/null || true
    exit 1
  fi
  sleep 10
done

echo ""
echo "====================================================="
echo " ✅ Azure Deployment Complete"
echo "====================================================="
echo "App:        ${APP_URL}"
echo "Health:     ${APP_URL}/health"
echo "Metrics:    ${APP_URL}/metrics"
echo "Prometheus: ${APP_URL}/prometheus/"
echo "Grafana:    ${APP_URL}/grafana/"
echo "  Login:    admin / [GRAFANA_ADMIN_PASSWORD]"
echo "====================================================="
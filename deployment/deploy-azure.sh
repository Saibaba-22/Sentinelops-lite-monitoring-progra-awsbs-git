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

# ─── AI Agent Monitor + GitHub collector ───
GEMINI_API_KEY="${GEMINI_API_KEY:-}"
AI_PROVIDER="${AI_PROVIDER:-gemini}"
AI_MODEL="${AI_MODEL:-gemini-2.5-flash}"
GH_METRICS_TOKEN="${GH_METRICS_TOKEN:-}"
GH_METRICS_REPO="${GH_METRICS_REPO:-}"

if [ -z "${MONITOR_TOKEN}" ]; then
  echo "ERROR: Set MONITOR_TOKEN_AZURE or MONITOR_TOKEN"
  exit 1
fi

# ─── Validate all critical secrets are non-empty ───
echo "==> Validating secrets are present"
SECRETS_FAILED=0

if [ -z "${DOCKERHUB_TOKEN}" ]; then
  echo "ERROR: DOCKERHUB_TOKEN is empty"
  SECRETS_FAILED=1
fi
if [ -z "${GRAFANA_ADMIN_PASSWORD}" ]; then
  echo "ERROR: GRAFANA_ADMIN_PASSWORD is empty"
  SECRETS_FAILED=1
fi
if [ -z "${MONITOR_TOKEN}" ]; then
  echo "ERROR: MONITOR_TOKEN is empty"
  SECRETS_FAILED=1
fi

# Show lengths only (not values) for security
echo "   DOCKERHUB_TOKEN length        : ${#DOCKERHUB_TOKEN}"
echo "   GRAFANA_ADMIN_PASSWORD length : ${#GRAFANA_ADMIN_PASSWORD}"
echo "   MONITOR_TOKEN length          : ${#MONITOR_TOKEN}"
echo "   GEMINI_API_KEY length         : ${#GEMINI_API_KEY}"
echo "   GH_METRICS_TOKEN length       : ${#GH_METRICS_TOKEN}"
echo "   GH_METRICS_REPO               : ${GH_METRICS_REPO}"

if [ "${SECRETS_FAILED}" = "1" ]; then
  echo "ERROR: One or more required secrets are empty. Aborting."
  exit 1
fi
echo "✅ All secrets are present."

# ─── Warn if optional AI/collector vars are missing (non-fatal) ───
if [ -z "${GEMINI_API_KEY}" ]; then
  echo "⚠️  GEMINI_API_KEY is empty — AI features will be disabled."
fi
if [ -z "${GH_METRICS_TOKEN}" ] || [ -z "${GH_METRICS_REPO}" ]; then
  echo "⚠️  GH_METRICS_TOKEN or GH_METRICS_REPO empty — GitHub auto-collector will be disabled."
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
echo "AI_MODEL             = ${AI_MODEL}"
echo "AI_PROVIDER          = ${AI_PROVIDER}"
echo "GH_METRICS_REPO      = ${GH_METRICS_REPO}"
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
  -e "s|__GEMINI_API_KEY__|${GEMINI_API_KEY}|g" \
  -e "s|__AI_PROVIDER__|${AI_PROVIDER}|g" \
  -e "s|__AI_MODEL__|${AI_MODEL}|g" \
  -e "s|__GH_METRICS_TOKEN__|${GH_METRICS_TOKEN}|g" \
  -e "s|__GH_METRICS_REPO__|${GH_METRICS_REPO}|g" \
  "${COMPOSE_TMP}"

sed -i \
  -e "s|\${MONITOR_TOKEN}|${MONITOR_TOKEN}|g" \
  -e "s|\${GF_SECURITY_ADMIN_PASSWORD}|${GRAFANA_ADMIN_PASSWORD}|g" \
  "${COMPOSE_TMP}"

# ─── Verify no placeholders remain ───
echo "==> Verifying all placeholders resolved"
FAILED=0
for marker in \
  "__APP_IMAGE__" "__NGINX_IMAGE__" "__PROMETHEUS_IMAGE__" "__GRAFANA_IMAGE__" \
  "__BUILD_NUMBER__" "__ENVIRONMENT__" "__GF_SERVER_DOMAIN__" "__GF_SERVER_ROOT_URL__" \
  "__MONITOR_TOKEN__" "__GRAFANA_ADMIN_PASSWORD__" \
  "__GEMINI_API_KEY__" "__AI_PROVIDER__" "__AI_MODEL__" \
  "__GH_METRICS_TOKEN__" "__GH_METRICS_REPO__" \
  "replace_with_"; do
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

# ─── Configure Azure App Settings ───
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
    "GEMINI_API_KEY=${GEMINI_API_KEY}" \
    "GOOGLE_API_KEY=${GEMINI_API_KEY}" \
    "AI_PROVIDER=${AI_PROVIDER}" \
    "AI_MODEL=${AI_MODEL}" \
    "GITHUB_TOKEN_METRICS=${GH_METRICS_TOKEN}" \
    "GITHUB_REPO=${GH_METRICS_REPO}" \
    "GITHUB_POLL_INTERVAL=60" \
    "TARGET_CLOUD=azure" \
  --output none

echo "✅ App settings configured."

# ─── Verify DOCKER_REGISTRY_SERVER_PASSWORD was saved ───
echo "==> Verifying Docker registry password was saved"
SAVED_PWD=$(az webapp config appsettings list \
  --name "${AZURE_WEBAPP_NAME}" \
  --resource-group "${AZURE_RESOURCE_GROUP}" \
  --query "[?name=='DOCKER_REGISTRY_SERVER_PASSWORD'].value | [0]" \
  -o tsv 2>/dev/null || echo "")

if [ -z "${SAVED_PWD}" ]; then
  echo "WARNING: DOCKER_REGISTRY_SERVER_PASSWORD appears empty in Azure."
  echo "         Trying alternate method to set registry credentials..."
  az webapp config container set \
    --name "${AZURE_WEBAPP_NAME}" \
    --resource-group "${AZURE_RESOURCE_GROUP}" \
    --docker-registry-server-url "https://index.docker.io" \
    --docker-registry-server-user "${DOCKERHUB_USERNAME}" \
    --docker-registry-server-password "${DOCKERHUB_TOKEN}" \
    --output none
  echo "✅ Registry credentials set via container config."
else
  echo "✅ DOCKER_REGISTRY_SERVER_PASSWORD is saved in Azure."
fi

# ─── Deploy using sitecontainers API (Azure's new multi-container) ───
echo "==> Deploying via sitecontainers API"

# Clean up any existing sitecontainers first (idempotent)
for CN in nginx app prometheus grafana node-exporter; do
  az webapp sitecontainers delete \
    --name "${AZURE_WEBAPP_NAME}" \
    --resource-group "${AZURE_RESOURCE_GROUP}" \
    --container-name "${CN}" \
    --output none 2>/dev/null || true
done
echo "✅ Old sitecontainers cleaned up"

# ── 1. NGINX (main container, receives external port 80) ──
echo "==> Creating nginx sitecontainer"
az webapp sitecontainers create \
  --name "${AZURE_WEBAPP_NAME}" \
  --resource-group "${AZURE_RESOURCE_GROUP}" \
  --container-name "nginx" \
  --image "${NGINX_IMAGE}" \
  --target-port 80 \
  --is-main true \
  --registry-url "https://index.docker.io" \
  --registry-username "${DOCKERHUB_USERNAME}" \
  --registry-password "${DOCKERHUB_TOKEN}" \
  --output none

# ── 2. APP (Flask) ──
echo "==> Creating app sitecontainer"
az webapp sitecontainers create \
  --name "${AZURE_WEBAPP_NAME}" \
  --resource-group "${AZURE_RESOURCE_GROUP}" \
  --container-name "app" \
  --image "${APP_IMAGE}" \
  --target-port 5000 \
  --is-main false \
  --registry-url "https://index.docker.io" \
  --registry-username "${DOCKERHUB_USERNAME}" \
  --registry-password "${DOCKERHUB_TOKEN}" \
  --environment-variables \
    PORT=5000 \
    APP_VERSION=1.0.0 \
    "BUILD_NUMBER=${IMAGE_TAG}" \
    ENVIRONMENT=production \
    METRICS_INTERVAL=5 \
    PYTHONPATH=/app \
    TARGET_CLOUD=azure \
    "MONITOR_TOKEN=${MONITOR_TOKEN}" \
    "GEMINI_API_KEY=${GEMINI_API_KEY}" \
    "GOOGLE_API_KEY=${GEMINI_API_KEY}" \
    "AI_PROVIDER=${AI_PROVIDER}" \
    "AI_MODEL=${AI_MODEL}" \
    "GITHUB_TOKEN_METRICS=${GH_METRICS_TOKEN}" \
    "GITHUB_REPO=${GH_METRICS_REPO}" \
    GITHUB_POLL_INTERVAL=60 \
  --output none

# ── 3. PROMETHEUS ──
echo "==> Creating prometheus sitecontainer"
az webapp sitecontainers create \
  --name "${AZURE_WEBAPP_NAME}" \
  --resource-group "${AZURE_RESOURCE_GROUP}" \
  --container-name "prometheus" \
  --image "${PROMETHEUS_IMAGE}" \
  --target-port 9090 \
  --is-main false \
  --registry-url "https://index.docker.io" \
  --registry-username "${DOCKERHUB_USERNAME}" \
  --registry-password "${DOCKERHUB_TOKEN}" \
  --output none

# ── 4. GRAFANA ──
echo "==> Creating grafana sitecontainer"
az webapp sitecontainers create \
  --name "${AZURE_WEBAPP_NAME}" \
  --resource-group "${AZURE_RESOURCE_GROUP}" \
  --container-name "grafana" \
  --image "${GRAFANA_IMAGE}" \
  --target-port 3000 \
  --is-main false \
  --registry-url "https://index.docker.io" \
  --registry-username "${DOCKERHUB_USERNAME}" \
  --registry-password "${DOCKERHUB_TOKEN}" \
  --environment-variables \
    GF_SECURITY_ADMIN_USER=admin \
    "GF_SECURITY_ADMIN_PASSWORD=${GRAFANA_ADMIN_PASSWORD}" \
    GF_USERS_ALLOW_SIGN_UP=false \
    "GF_SERVER_DOMAIN=${GF_DOMAIN}" \
    "GF_SERVER_ROOT_URL=${GF_ROOT_URL}" \
    GF_SERVER_SUB_PATH=/grafana/ \
    GF_SERVER_SERVE_FROM_SUB_PATH=true \
    GF_SERVER_ENABLE_GZIP=true \
    GF_SECURITY_ALLOW_EMBEDDING=true \
    GF_SECURITY_COOKIE_SECURE=false \
    GF_SECURITY_COOKIE_SAMESITE=disabled \
    "GF_LIVE_ALLOWED_ORIGINS=*" \
    GF_AUTH_ANONYMOUS_ENABLED=false \
    "PROMETHEUS_URL=http://prometheus:9090/prometheus/" \
  --output none

# ── 5. NODE-EXPORTER (public image, no registry auth) ──
echo "==> Creating node-exporter sitecontainer"
az webapp sitecontainers create \
  --name "${AZURE_WEBAPP_NAME}" \
  --resource-group "${AZURE_RESOURCE_GROUP}" \
  --container-name "node-exporter" \
  --image "prom/node-exporter:v1.8.0" \
  --target-port 9100 \
  --is-main false \
  --output none

echo "✅ All 5 sitecontainers created"

# Restart to ensure clean state
echo "==> Restarting Azure App Service"
az webapp restart \
  --name "${AZURE_WEBAPP_NAME}" \
  --resource-group "${AZURE_RESOURCE_GROUP}"

echo "==> Waiting 90 seconds for containers to start and pull images..."
sleep 90

# ─── Health Check ───
HEALTH_PATH="${APP_HEALTH_PATH:-/health}"
echo "==> Health check: ${APP_URL}${HEALTH_PATH}"
for attempt in $(seq 1 30); do
  code=$(curl -ksS -o /dev/null -w '%{http_code}' \
    --max-time 20 "${APP_URL}${HEALTH_PATH}" || true)
  echo "  Attempt ${attempt}/30: HTTP ${code}"
  if [ "${code}" = "200" ]; then
    echo "✅ App is healthy!"
    break
  fi
  if [ "${attempt}" = "30" ]; then
    echo "❌ App not healthy after 30 attempts."
    echo ""
    echo "==> Fetching recent Azure logs for diagnosis:"
    az webapp log tail \
      --name "${AZURE_WEBAPP_NAME}" \
      --resource-group "${AZURE_RESOURCE_GROUP}" \
      --timeout 30 2>/dev/null || true
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
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

# ─── AI + collector ───
GEMINI_API_KEY="${GEMINI_API_KEY:-}"
AI_PROVIDER="${AI_PROVIDER:-gemini}"
AI_MODEL="${AI_MODEL:-gemini-2.5-flash}"
GH_METRICS_TOKEN="${GH_METRICS_TOKEN:-}"
GH_METRICS_REPO="${GH_METRICS_REPO:-}"

[ -z "${MONITOR_TOKEN}" ] && { echo "ERROR: Set MONITOR_TOKEN_AZURE or MONITOR_TOKEN"; exit 1; }

echo "==> Validating secrets"
[ -z "${DOCKERHUB_TOKEN}" ]        && { echo "ERROR: DOCKERHUB_TOKEN empty"; exit 1; }
[ -z "${GRAFANA_ADMIN_PASSWORD}" ] && { echo "ERROR: GRAFANA_ADMIN_PASSWORD empty"; exit 1; }
echo "   DOCKERHUB_TOKEN length        : ${#DOCKERHUB_TOKEN}"
echo "   GRAFANA_ADMIN_PASSWORD length : ${#GRAFANA_ADMIN_PASSWORD}"
echo "   MONITOR_TOKEN length          : ${#MONITOR_TOKEN}"
echo "   GEMINI_API_KEY length         : ${#GEMINI_API_KEY}"
echo "   GH_METRICS_TOKEN length       : ${#GH_METRICS_TOKEN}"
echo "   GH_METRICS_REPO               : ${GH_METRICS_REPO}"
echo "✅ Secrets present."

# ─── Image URIs ───
APP_IMAGE="docker.io/${DOCKERHUB_USERNAME}/${IMAGE_NAME}:${IMAGE_TAG}"
NGINX_IMAGE="docker.io/${DOCKERHUB_USERNAME}/${IMAGE_NAME}:nginx-${IMAGE_TAG}"
PROMETHEUS_IMAGE="docker.io/${DOCKERHUB_USERNAME}/${IMAGE_NAME}:prometheus-${IMAGE_TAG}"
GRAFANA_IMAGE="docker.io/${DOCKERHUB_USERNAME}/${IMAGE_NAME}:grafana-${IMAGE_TAG}"

echo "====================================================="
echo " SentinelOps-Lite — Azure Sitecontainers Deployment"
echo "====================================================="
echo "APP_IMAGE            = ${APP_IMAGE}"
echo "NGINX_IMAGE          = ${NGINX_IMAGE}"
echo "PROMETHEUS_IMAGE     = ${PROMETHEUS_IMAGE}"
echo "GRAFANA_IMAGE        = ${GRAFANA_IMAGE}"
echo "AZURE_WEBAPP_NAME    = ${AZURE_WEBAPP_NAME}"
echo "AZURE_RESOURCE_GROUP = ${AZURE_RESOURCE_GROUP}"
echo "====================================================="

# ─── Resolve Azure hostname ───
echo "==> Resolving Azure hostname"
AZURE_HOSTNAME=$(az webapp show \
  --name "${AZURE_WEBAPP_NAME}" \
  --resource-group "${AZURE_RESOURCE_GROUP}" \
  --query defaultHostName -o tsv 2>/dev/null || echo "")

[ -z "${AZURE_HOSTNAME}" ] && { echo "ERROR: Cannot resolve hostname."; exit 1; }
APP_URL="https://${AZURE_HOSTNAME}"
GF_DOMAIN="${AZURE_HOSTNAME}"
GF_ROOT_URL="https://${AZURE_HOSTNAME}/grafana/"
echo "   Hostname: ${AZURE_HOSTNAME}"

# ─── App-level settings (all containers inherit these + registry creds) ───
echo "==> Setting Azure App Service settings"
az webapp config appsettings set \
  --name "${AZURE_WEBAPP_NAME}" \
  --resource-group "${AZURE_RESOURCE_GROUP}" \
  --settings \
    "WEBSITES_PORT=80" \
    "WEBSITES_CONTAINER_START_TIME_LIMIT=1800" \
    "DOCKER_REGISTRY_SERVER_URL=https://index.docker.io" \
    "DOCKER_REGISTRY_SERVER_USERNAME=${DOCKERHUB_USERNAME}" \
    "DOCKER_REGISTRY_SERVER_PASSWORD=${DOCKERHUB_TOKEN}" \
    "BUILD_NUMBER=${IMAGE_TAG}" \
    "ENVIRONMENT=production" \
    "TARGET_CLOUD=azure" \
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
  --output none
echo "✅ App settings set."

# ─── Also set container registry creds explicitly ───
echo "==> Setting container registry credentials"
az webapp config container set \
  --name "${AZURE_WEBAPP_NAME}" \
  --resource-group "${AZURE_RESOURCE_GROUP}" \
  --container-registry-url "https://index.docker.io" \
  --container-registry-user "${DOCKERHUB_USERNAME}" \
  --container-registry-password "${DOCKERHUB_TOKEN}" \
  --output none
echo "✅ Registry credentials set."

# ─── Deploy sitecontainers ───
echo "==> Deploying via sitecontainers API"

# Cleanup old
for CN in main nginx app prometheus grafana node-exporter; do
  az webapp sitecontainers delete \
    --name "${AZURE_WEBAPP_NAME}" \
    --resource-group "${AZURE_RESOURCE_GROUP}" \
    --container-name "${CN}" \
    --output none 2>/dev/null || true
done
echo "✅ Old sitecontainers cleaned"

# 1. NGINX
echo "==> Creating nginx sitecontainer"
az webapp sitecontainers create \
  --name "${AZURE_WEBAPP_NAME}" \
  --resource-group "${AZURE_RESOURCE_GROUP}" \
  --container-name "nginx" \
  --image "${NGINX_IMAGE}" \
  --target-port 80 \
  --is-main true \
  --output none
echo "   ✅ nginx created"

# 2. APP
echo "==> Creating app sitecontainer"
az webapp sitecontainers create \
  --name "${AZURE_WEBAPP_NAME}" \
  --resource-group "${AZURE_RESOURCE_GROUP}" \
  --container-name "app" \
  --image "${APP_IMAGE}" \
  --target-port 5000 \
  --is-main false \
  --output none
echo "   ✅ app created"

# 3. PROMETHEUS
echo "==> Creating prometheus sitecontainer"
az webapp sitecontainers create \
  --name "${AZURE_WEBAPP_NAME}" \
  --resource-group "${AZURE_RESOURCE_GROUP}" \
  --container-name "prometheus" \
  --image "${PROMETHEUS_IMAGE}" \
  --target-port 9090 \
  --is-main false \
  --output none
echo "   ✅ prometheus created"

# 4. GRAFANA
echo "==> Creating grafana sitecontainer"
az webapp sitecontainers create \
  --name "${AZURE_WEBAPP_NAME}" \
  --resource-group "${AZURE_RESOURCE_GROUP}" \
  --container-name "grafana" \
  --image "${GRAFANA_IMAGE}" \
  --target-port 3000 \
  --is-main false \
  --output none
echo "   ✅ grafana created"

# 5. NODE-EXPORTER (public image)
echo "==> Creating node-exporter sitecontainer"
az webapp sitecontainers create \
  --name "${AZURE_WEBAPP_NAME}" \
  --resource-group "${AZURE_RESOURCE_GROUP}" \
  --container-name "node-exporter" \
  --image "prom/node-exporter:v1.8.0" \
  --target-port 9100 \
  --is-main false \
  --output none
echo "   ✅ node-exporter created"

echo "✅ All 5 sitecontainers created"

echo "==> Listing deployed sitecontainers"
az webapp sitecontainers list \
  --name "${AZURE_WEBAPP_NAME}" \
  --resource-group "${AZURE_RESOURCE_GROUP}" \
  -o table

echo "==> Restarting Azure App Service"
az webapp restart \
  --name "${AZURE_WEBAPP_NAME}" \
  --resource-group "${AZURE_RESOURCE_GROUP}"

echo "==> Waiting 120 seconds for containers to pull and start..."
sleep 120

# ─── Health check ───
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
    echo "==> Fetching Azure logs:"
    az webapp log tail \
      --name "${AZURE_WEBAPP_NAME}" \
      --resource-group "${AZURE_RESOURCE_GROUP}" 2>/dev/null | head -100 || true
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
echo "====================================================="
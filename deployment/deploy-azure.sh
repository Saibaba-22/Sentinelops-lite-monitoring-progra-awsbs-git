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

# ─── Deploy sitecontainers via REST API (works around CLI flag bugs) ───
echo "==> Getting subscription ID"
SUB_ID=$(az account show --query id -o tsv)
BASE_URI="https://management.azure.com/subscriptions/${SUB_ID}/resourceGroups/${AZURE_RESOURCE_GROUP}/providers/Microsoft.Web/sites/${AZURE_WEBAPP_NAME}/sitecontainers"

# Helper function to create a sitecontainer with proper auth
create_sitecontainer() {
  local NAME="$1"
  local IMAGE="$2"
  local PORT="$3"
  local IS_MAIN="$4"
  local USE_AUTH="${5:-true}"
  local ENV_JSON="${6:-[]}"

  echo "==> Creating ${NAME} sitecontainer (auth=${USE_AUTH})"

  if [ "$USE_AUTH" = "true" ]; then
    AUTH_BLOCK="\"authType\": \"UserCredentials\", \"userName\": \"${DOCKERHUB_USERNAME}\", \"passwordSecret\": \"${DOCKERHUB_TOKEN}\","
  else
    AUTH_BLOCK="\"authType\": \"Anonymous\","
  fi

  cat > /tmp/sitecontainer.json <<EOF
{
  "properties": {
    "image": "${IMAGE}",
    "targetPort": "${PORT}",
    "isMain": ${IS_MAIN},
    ${AUTH_BLOCK}
    "environmentVariables": ${ENV_JSON}
  }
}
EOF

  az rest \
    --method PUT \
    --uri "${BASE_URI}/${NAME}?api-version=2023-12-01" \
    --body @/tmp/sitecontainer.json \
    --output none

  echo "   ✅ ${NAME} created"
}

# Env vars for app container
APP_ENV=$(cat <<EOF
[
  {"name": "PORT", "value": "5000"},
  {"name": "APP_VERSION", "value": "1.0.0"},
  {"name": "BUILD_NUMBER", "value": "${IMAGE_TAG}"},
  {"name": "ENVIRONMENT", "value": "production"},
  {"name": "METRICS_INTERVAL", "value": "5"},
  {"name": "PYTHONPATH", "value": "/app"},
  {"name": "TARGET_CLOUD", "value": "azure"},
  {"name": "MONITOR_TOKEN", "value": "${MONITOR_TOKEN}"},
  {"name": "GEMINI_API_KEY", "value": "${GEMINI_API_KEY}"},
  {"name": "GOOGLE_API_KEY", "value": "${GEMINI_API_KEY}"},
  {"name": "AI_PROVIDER", "value": "${AI_PROVIDER}"},
  {"name": "AI_MODEL", "value": "${AI_MODEL}"},
  {"name": "GITHUB_TOKEN_METRICS", "value": "${GH_METRICS_TOKEN}"},
  {"name": "GITHUB_REPO", "value": "${GH_METRICS_REPO}"},
  {"name": "GITHUB_POLL_INTERVAL", "value": "60"}
]
EOF
)

# Env vars for grafana container
GRAFANA_ENV=$(cat <<EOF
[
  {"name": "GF_SECURITY_ADMIN_USER", "value": "admin"},
  {"name": "GF_SECURITY_ADMIN_PASSWORD", "value": "${GRAFANA_ADMIN_PASSWORD}"},
  {"name": "GF_USERS_ALLOW_SIGN_UP", "value": "false"},
  {"name": "GF_SERVER_DOMAIN", "value": "${GF_DOMAIN}"},
  {"name": "GF_SERVER_ROOT_URL", "value": "${GF_ROOT_URL}"},
  {"name": "GF_SERVER_SUB_PATH", "value": "/grafana/"},
  {"name": "GF_SERVER_SERVE_FROM_SUB_PATH", "value": "true"},
  {"name": "GF_SERVER_ENABLE_GZIP", "value": "true"},
  {"name": "GF_SECURITY_ALLOW_EMBEDDING", "value": "true"},
  {"name": "GF_SECURITY_COOKIE_SECURE", "value": "false"},
  {"name": "GF_SECURITY_COOKIE_SAMESITE", "value": "disabled"},
  {"name": "GF_LIVE_ALLOWED_ORIGINS", "value": "*"},
  {"name": "GF_AUTH_ANONYMOUS_ENABLED", "value": "false"},
  {"name": "PROMETHEUS_URL", "value": "http://localhost:9090/prometheus/"}
]
EOF
)

# Cleanup (include 'main')
for CN in main nginx app prometheus grafana node-exporter; do
  az rest \
    --method DELETE \
    --uri "${BASE_URI}/${CN}?api-version=2023-12-01" \
    --output none 2>/dev/null || true
done
echo "✅ Old sitecontainers cleaned"

# Create all 5
create_sitecontainer "nginx"         "${NGINX_IMAGE}"      "80"   "true"  "true"  "[]"

echo "==> Creating app sitecontainer (with full env vars)"

cat > /tmp/app-sitecontainer.json <<EOF
{
  "properties": {
    "image": "${APP_IMAGE}",
    "targetPort": "5000",
    "isMain": false,
    "authType": "UserCredentials",
    "userName": "${DOCKERHUB_USERNAME}",
    "passwordSecret": "${DOCKERHUB_TOKEN}",
    "environmentVariables": [
      {"name": "PORT",                     "value": "5000"},
      {"name": "APP_VERSION",              "value": "1.0.0"},
      {"name": "BUILD_NUMBER",             "value": "${IMAGE_TAG}"},
      {"name": "ENVIRONMENT",              "value": "production"},
      {"name": "METRICS_INTERVAL",         "value": "5"},
      {"name": "PYTHONPATH",               "value": "/app"},
      {"name": "TARGET_CLOUD",             "value": "azure"},
      {"name": "MONITOR_TOKEN",            "value": "${MONITOR_TOKEN}"},
      {"name": "GEMINI_API_KEY",           "value": "${GEMINI_API_KEY}"},
      {"name": "GOOGLE_API_KEY",           "value": "${GEMINI_API_KEY}"},
      {"name": "AI_PROVIDER",              "value": "${AI_PROVIDER}"},
      {"name": "AI_MODEL",                 "value": "${AI_MODEL}"},
      {"name": "GITHUB_TOKEN_METRICS",     "value": "${GH_METRICS_TOKEN}"},
      {"name": "GITHUB_REPO",              "value": "${GH_METRICS_REPO}"},
      {"name": "GITHUB_POLL_INTERVAL",     "value": "60"}
    ]
  }
}
EOF

if command -v jq >/dev/null 2>&1; then
  jq empty /tmp/app-sitecontainer.json || { echo "❌ Invalid JSON"; cat /tmp/app-sitecontainer.json; exit 1; }
fi

az rest \
  --method PUT \
  --uri "${BASE_URI}/app?api-version=2023-12-01" \
  --body @/tmp/app-sitecontainer.json \
  --output none

echo "   ✅ app sitecontainer created with 15 env vars"

create_sitecontainer "prometheus"    "${PROMETHEUS_IMAGE}" "9090" "false" "true"  "[]"

# ─── GRAFANA — write JSON to file to avoid bash quoting bugs ───
echo "==> Creating grafana sitecontainer (with full env vars)"

cat > /tmp/grafana-sitecontainer.json <<EOF
{
  "properties": {
    "image": "${GRAFANA_IMAGE}",
    "targetPort": "3000",
    "isMain": false,
    "authType": "UserCredentials",
    "userName": "${DOCKERHUB_USERNAME}",
    "passwordSecret": "${DOCKERHUB_TOKEN}",
    "environmentVariables": [
      {"name": "GF_SECURITY_ADMIN_USER",           "value": "admin"},
      {"name": "GF_SECURITY_ADMIN_PASSWORD",       "value": "${GRAFANA_ADMIN_PASSWORD}"},
      {"name": "GF_USERS_ALLOW_SIGN_UP",           "value": "false"},
      {"name": "GF_SERVER_DOMAIN",                 "value": "${GF_DOMAIN}"},
      {"name": "GF_SERVER_ROOT_URL",               "value": "${GF_ROOT_URL}"},
      {"name": "GF_SERVER_SUB_PATH",               "value": "/grafana/"},
      {"name": "GF_SERVER_SERVE_FROM_SUB_PATH",    "value": "true"},
      {"name": "GF_SERVER_ENABLE_GZIP",            "value": "true"},
      {"name": "GF_SECURITY_ALLOW_EMBEDDING",      "value": "true"},
      {"name": "GF_SECURITY_COOKIE_SECURE",        "value": "false"},
      {"name": "GF_SECURITY_COOKIE_SAMESITE",      "value": "disabled"},
      {"name": "GF_LIVE_ALLOWED_ORIGINS",          "value": "*"},
      {"name": "GF_AUTH_ANONYMOUS_ENABLED",        "value": "false"},
      {"name": "PROMETHEUS_URL",                   "value": "http://localhost:9090/prometheus/"}
    ]
  }
}
EOF

# Validate JSON before sending
if command -v jq >/dev/null 2>&1; then
  jq empty /tmp/grafana-sitecontainer.json || { echo "❌ Invalid JSON"; cat /tmp/grafana-sitecontainer.json; exit 1; }
fi

az rest \
  --method PUT \
  --uri "${BASE_URI}/grafana?api-version=2023-12-01" \
  --body @/tmp/grafana-sitecontainer.json \
  --output none

echo "   ✅ grafana sitecontainer created with 14 env vars"

create_sitecontainer "node-exporter" "prom/node-exporter:v1.8.0" "9100" "false" "false" "[]"

echo "✅ All 5 sitecontainers created with auth + env"

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
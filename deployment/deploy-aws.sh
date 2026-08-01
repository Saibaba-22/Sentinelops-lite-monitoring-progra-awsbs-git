#!/usr/bin/env bash
# Deploy the already-built application image to an AWS EB Multi-container Docker environment.
# Required: APP_NAME, ENV_NAME, AWS_REGION, DOCKERHUB_USERNAME,
#           DOCKERHUB_REPOSITORY or REPOSITORY, GRAFANA_ADMIN_PASSWORD.
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
APP_NAME="${APP_NAME:?Set APP_NAME}"
ENV_NAME="${ENV_NAME:?Set ENV_NAME}"
AWS_REGION="${AWS_REGION:?Set AWS_REGION}"
DOCKERHUB_USERNAME="${DOCKERHUB_USERNAME:?Set DOCKERHUB_USERNAME}"
IMAGE_REPOSITORY="${DOCKERHUB_REPOSITORY:-${REPOSITORY:?Set DOCKERHUB_REPOSITORY or REPOSITORY}}"
IMAGE_TAG="${IMAGE_TAG:-${GITHUB_SHA:?Set IMAGE_TAG or GITHUB_SHA}}"
GRAFANA_ADMIN_PASSWORD="${GRAFANA_ADMIN_PASSWORD:?Set GRAFANA_ADMIN_PASSWORD}"
MONITOR_TOKEN_AWS="${MONITOR_TOKEN_AWS:-}"

command -v aws  >/dev/null || { echo "AWS CLI is required" >&2; exit 1; }
command -v eb   >/dev/null || { echo "EB CLI is required: pip install awsebcli" >&2; exit 1; }

BASE_IMAGE="docker.io/${DOCKERHUB_USERNAME}/${IMAGE_REPOSITORY}"
IMAGE="${BASE_IMAGE}:${IMAGE_TAG}"

# ── Resolve EB environment ────────────────────────────────────
CNAME="$(aws elasticbeanstalk describe-environments \
  --application-name "$APP_NAME" --environment-names "$ENV_NAME" \
  --region "$AWS_REGION" --query 'Environments[0].CNAME' --output text)"
test -n "$CNAME" && test "$CNAME" != "None" || { echo "Could not resolve EB CNAME" >&2; exit 1; }

PLATFORM="$(aws elasticbeanstalk describe-environments \
  --application-name "$APP_NAME" --environment-names "$ENV_NAME" \
  --region "$AWS_REGION" --query 'Environments[0].SolutionStackName' --output text)"
test -n "$PLATFORM" && test "$PLATFORM" != "None" || { echo "Could not resolve EB platform" >&2; exit 1; }

BASE_URL="${AWS_BASE_URL:-http://${CNAME}}"
export CNAME BASE_URL GRAFANA_ADMIN_PASSWORD MONITOR_TOKEN_AWS

# ── Set EB environment variables ──────────────────────────────
python - <<'PY'
import json, os
values = {
    "APP_VERSION": "1.0.0",
    "BUILD_NUMBER": os.environ.get("GITHUB_SHA", os.environ.get("IMAGE_TAG", "local")),
    "ENVIRONMENT": "production",
    "METRICS_INTERVAL": "5",
    "MONITOR_TOKEN": os.environ.get("MONITOR_TOKEN_AWS", ""),
    "GF_SECURITY_ADMIN_PASSWORD": os.environ["GRAFANA_ADMIN_PASSWORD"],
    "GF_SERVER_DOMAIN": os.environ["CNAME"],
    "GF_SERVER_ROOT_URL": os.environ["BASE_URL"].rstrip("/") + "/grafana/",
    "PROMETHEUS_URL": "http://prometheus:9090/prometheus",
}
options = [{"Namespace": "aws:elasticbeanstalk:application:environment", "OptionName": k, "Value": v} for k, v in values.items()]
with open("/tmp/eb-options.json", "w", encoding="utf-8") as handle:
    json.dump(options, handle)
PY

aws elasticbeanstalk update-environment \
  --application-name "$APP_NAME" --environment-name "$ENV_NAME" \
  --region "$AWS_REGION" --option-settings file:///tmp/eb-options.json >/dev/null

echo "Waiting for environment to be Ready..."
aws elasticbeanstalk wait environment-updated \
  --application-name "$APP_NAME" --environment-names "$ENV_NAME"

# ── Render Dockerrun.aws.json with real image URIs ───────────
python - <<'PY'
import json, os
from pathlib import Path

sha        = os.environ.get("GITHUB_SHA", os.environ.get("IMAGE_TAG", "local"))
user       = os.environ["DOCKERHUB_USERNAME"]
repo       = os.environ["IMAGE_REPOSITORY"]
base_image = f"docker.io/{user}/{repo}"
base_url   = os.environ["BASE_URL"].rstrip("/")
cname      = os.environ["CNAME"]

image_map = {
    "app":           f"{base_image}:{sha}",
    "nginx":         f"{base_image}:nginx-{sha}",
    "prometheus":    f"{base_image}:prometheus-{sha}",
    "grafana":       f"{base_image}:grafana-{sha}",
    "node-exporter": "prom/node-exporter:v1.8.0",
}

env_map = {
    "app": {
        "PORT": "5000", "APP_VERSION": "1.0.0", "BUILD_NUMBER": sha,
        "ENVIRONMENT": "production", "METRICS_INTERVAL": "5",
        "MONITOR_TOKEN": os.environ.get("MONITOR_TOKEN_AWS", ""),
        "PYTHONPATH": "/app",
        "PROMETHEUS_URL": "http://prometheus:9090/prometheus",
    },
    "grafana": {
        "GF_SECURITY_ADMIN_USER": "admin",
        "GF_SECURITY_ADMIN_PASSWORD": os.environ["GRAFANA_ADMIN_PASSWORD"],
        "GF_USERS_ALLOW_SIGN_UP": "false",
        "GF_SERVER_DOMAIN": cname,
        "GF_SERVER_ROOT_URL": f"{base_url}/grafana/",
        "GF_SERVER_SUB_PATH": "/grafana/",
        "GF_SERVER_SERVE_FROM_SUB_PATH": "true",
        "PROMETHEUS_URL": "http://prometheus:9090/prometheus/",
    },
}

path = Path("Dockerrun.aws.json")
manifest = json.loads(path.read_text(encoding="utf-8"))

for container in manifest.get("containerDefinitions", []):
    name = container.get("name")
    if name in image_map:
        container["image"] = image_map[name]
        print(f"  image [{name}]: → {image_map[name]}")
    if name in env_map:
        existing = {e["name"]: e for e in container.get("environment", [])}
        for key, value in env_map[name].items():
            existing[key] = {"name": key, "value": str(value)}
        container["environment"] = list(existing.values())
    if name == "prometheus":
        container["command"] = [
            "--config.file=/etc/prometheus/prometheus.yml",
            "--web.external-url=/prometheus/",
            "--web.route-prefix=/prometheus/",
        ]

for volume in manifest.get("volumes", []):
    if volume.get("name") == "nginx-conf":
        volume["host"]["sourcePath"] = "/var/app/current/docker/nginx-ecs"
        print(f"  vol   [nginx-conf]: → /var/app/current/docker/nginx-ecs")

path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
print("Dockerrun.aws.json rendered successfully.")
PY

# ── Prepare nginx config ──────────────────────────────────────
source="docker/nginx/nginx-aws.conf"
[ -f "$source" ] || source="docker/nginx/nginx.conf"
mkdir -p docker/nginx-ecs
cp "$source" docker/nginx-ecs/default.conf
echo "Nginx config: $source → docker/nginx-ecs/default.conf"

# ── Check for unreplaced placeholders ─────────────────────────
if grep -E "replace_with" Dockerrun.aws.json; then
  echo "ERROR: Unreplaced placeholders still present." >&2
  exit 1
fi

# ── Deploy ────────────────────────────────────────────────────
eb init "$APP_NAME" --region "$AWS_REGION" --platform "$PLATFORM"
eb use "$ENV_NAME"

eb deploy "$ENV_NAME" \
  --label "manual-${IMAGE_TAG:0:12}" \
  --timeout 30

echo ""
echo "✅ Deployed successfully!"
echo "App:         ${BASE_URL}"
echo "Prometheus:  ${BASE_URL}/prometheus/"
echo "Grafana:     ${BASE_URL}/grafana/"
echo "Health:      ${BASE_URL}/health"
echo "Metrics:     ${BASE_URL}/metrics"
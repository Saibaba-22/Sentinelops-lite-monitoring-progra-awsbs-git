#!/usr/bin/env bash
# Deploy the already-built application image to an AWS EB Docker/Compose environment.
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

command -v aws >/dev/null || { echo "AWS CLI is required" >&2; exit 1; }
command -v eb >/dev/null || { echo "EB CLI is required: pip install awsebcli" >&2; exit 1; }

IMAGE="docker.io/${DOCKERHUB_USERNAME}/${IMAGE_REPOSITORY}:${IMAGE_TAG}"
CNAME="$(aws elasticbeanstalk describe-environments \
  --application-name "$APP_NAME" --environment-names "$ENV_NAME" \
  --region "$AWS_REGION" --query 'Environments[0].CNAME' --output text)"
test -n "$CNAME" && test "$CNAME" != "None" || { echo "Could not resolve EB CNAME" >&2; exit 1; }
BASE_URL="${AWS_BASE_URL:-http://${CNAME}}"

export CNAME BASE_URL GRAFANA_ADMIN_PASSWORD MONITOR_TOKEN_AWS
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
}
options = [{"Namespace": "aws:elasticbeanstalk:application:environment", "OptionName": k, "Value": v} for k, v in values.items()]
with open("/tmp/eb-options.json", "w", encoding="utf-8") as handle:
    json.dump(options, handle)
PY
aws elasticbeanstalk update-environment --application-name "$APP_NAME" --environment-name "$ENV_NAME" --region "$AWS_REGION" --option-settings file:///tmp/eb-options.json >/dev/null

sed -i "s|__APP_IMAGE__|${IMAGE}|g" "$ROOT_DIR/docker-compose.yml"
if grep -q '__APP_IMAGE__' "$ROOT_DIR/docker-compose.yml"; then
  echo "Image placeholder remains" >&2
  exit 1
fi

eb init "$APP_NAME" --region "$AWS_REGION" --platform "Docker running on 64bit Amazon Linux 2"
eb use "$ENV_NAME"
git -C "$ROOT_DIR" add docker-compose.yml docker/nginx/nginx.conf
( cd "$ROOT_DIR" && eb deploy "$ENV_NAME" --staged --label "manual-${IMAGE_TAG:0:12}" --timeout 30 )

echo "App: ${BASE_URL}"
echo "Prometheus: ${BASE_URL}/prometheus/"
echo "Grafana: ${BASE_URL}/grafana/"

# Deployment Guide — AWS Elastic Beanstalk (Multi-container Docker)

This guide deploys the full stack (Flask app + Prometheus + Grafana + Node
Exporter + Nginx) to a single Elastic Beanstalk **Multi-container Docker**
environment.

## Prerequisites

- AWS CLI v2 configured (`aws configure`) with ECR + Elastic Beanstalk permissions.
- Docker daemon available locally (to build & push the app image).
- (Optional) Elastic Beanstalk CLI: `pip install awsebcli`.
- An EB **Application** and a **Multi-container Docker** environment already created.

```bash
eb init sentinelops-lite --platform "Docker running on 64bit Amazon Linux 2023"
eb create sentinelops-lite-prod --single
```

## Step 1 — Build & push the app image to ECR

`deployment/deploy.sh` does this for you, but the manual steps are:

```bash
AWS_REGION=us-east-1
ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
aws ecr create-repository --repository-name sentinelops-lite --region $AWS_REGION || true
aws ecr get-login-password --region $AWS_REGION | docker login --username AWS --password-stdin $ACCOUNT_ID.dkr.ecr.$AWS_REGION.amazonaws.com
docker build -f docker/Dockerfile -t sentinelops-lite:latest .
docker tag sentinelops-lite:latest $ACCOUNT_ID.dkr.ecr.$AWS_REGION.amazonaws.com/sentinelops-lite:latest
docker push $ACCOUNT_ID.dkr.ecr.$AWS_REGION.amazonaws.com/sentinelops-lite:latest
```

## Step 2 — Wire the image into Dockerrun

`deployment/Dockerrun.aws.json` contains `"image": "REPLACE_WITH_ECR_IMAGE_URI"`.
Replace it with your pushed URI (the script does this automatically):

```bash
sed -i "s|REPLACE_WITH_ECR_IMAGE_URI|$ACCOUNT_ID.dkr.ecr.$AWS_REGION.amazonaws.com/sentinelops-lite:latest|g" deployment/Dockerrun.aws.json
```

## Step 3 — Set environment properties (secrets)

In the EB Console → *Configuration → Environment properties*, or via CLI:

```bash
eb setenv GEMINI_API_KEY=... GF_SECURITY_ADMIN_PASSWORD=... APP_VERSION=1.0.0 ENVIRONMENT=production
```

> The app reads `GEMINI_API_KEY` and Grafana reads `GF_SECURITY_ADMIN_PASSWORD`
> from the environment — **nothing secret is hard-coded** in the repo.

## Step 4 — Deploy

```bash
./deployment/deploy.sh
# or, if you prefer the EB CLI directly:
eb deploy sentinelops-lite-prod
```

`deploy.sh` builds, pushes, injects the image URI, zips the source bundle
(excluding dev artifacts) and runs `eb deploy`.

## What gets deployed

| Container | Port | Role |
|-----------|------|------|
| nginx | 80 | Public reverse proxy → app |
| app | 5000 | Flask application |
| prometheus | 9090 | Scraper + TSDB + rules |
| grafana | 3000 | Dashboards (auto-provisioned) |
| node-exporter | 9100 | Host metrics |

Grafana dashboards and the Prometheus config are mounted from the bundle via the
volumes declared in `Dockerrun.aws.json` and the `.ebextensions` files.

## Post-deploy checks

1. EB health turns **Green** (health check `/health` on port 80).
2. Open the environment URL → you see the pipeline UI; `/dashboard` shows live metrics.
3. Grafana at `<env-url>:3000` shows the four provisioned dashboards.
4. Prometheus at `<env-url>:9090` lists `flask-app`, `node-exporter`, `prometheus` targets as **UP**.

## Single-container alternative

If you only need the Flask app (no Prometheus/Grafana in EB), use the
`deployment/Procfile` with the *Python* or *Docker* (single) platform instead of
`Dockerrun.aws.json`.

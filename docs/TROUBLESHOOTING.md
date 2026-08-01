# Troubleshooting Guide

## The app won't start locally
- **`ModuleNotFoundError: agent_monitor`** — run commands from the project root
  (`ai-monitoring-platform/`). `app.py` adds the root to `sys.path`.
- **`ImportError: google.genai`** — this is only needed by `agent.py` (the CI
  gate), not by the web app or tests. `pip install -r requirements.txt` resolves it.
- **Port in use** — set `PORT=8000 python app.py` or stop the other process.

## `/metrics` is empty or missing custom metrics
- Confirm the route returns `text/plain`. The fix `content_type=CONTENT_TYPE_LATEST`
  prevents a doubled `charset`.
- Metrics are registered at import time in `monitoring/metrics.py`. If you use
  Flask's reloader (`debug=True`), metrics persist across reloads because each
  reload is a new process.

## Grafana shows "Datasource not found" / no dashboards
- Verify `monitoring/grafana/provisioning/datasources/datasource.yml` sets
  `uid: prometheus` and the dashboards reference that uid.
- In Docker, the four domain dashboards are mounted to
  `/etc/grafana/provisioning/dashboards/domain` and the provider path is
  `/etc/grafana/provisioning/dashboards` — all five JSON files must land there.
- Check Grafana logs: `docker compose logs grafana`.

## Prometheus targets are DOWN
- `flask-app` must be reachable at `app:5000` from the Prometheus container
  (same Docker network / EB task). Use the service name, not `localhost`.
- `node-exporter` needs host proc/sys mounts; on some platforms metrics may
  reflect the container, not the physical host — the app's own `system_*` metrics
  cover the host OS regardless.
- Validate the config: `docker compose exec prometheus promtool check config /etc/prometheus/prometheus.yml`.

## HTML dashboard shows "Disconnected"
- It polls `/api/status` on the **same origin**. If you open `dashboard.html`
  directly from disk (file://), the fetch will fail — access it via
  `http://<host>/dashboard`.
- Chart.js is loaded from a CDN; the browser needs internet access for charts
  (gauges/badges still work).

## EB deployment fails
- **`REPLACE_WITH_ECR_IMAGE_URI` still present** → run `deploy.sh` (it sed-replaces it)
  or replace manually before `eb deploy`.
- **Health check failing** → ensure the nginx container is essential and proxies
  `/health` to the app; EB health URL is `/health` (see `.ebextensions/01-nginx.config`).
- **Grafana admin password prompt loop** → set `GF_SECURITY_ADMIN_PASSWORD` as an
  EB environment property; Grafana reads it at startup.
- **Logs missing** → container logs appear under `/var/log/containers/` and are
  streamed to CloudWatch when `StreamLogs` is enabled (see `02-logging.config`).

## Tests fail
- `test_health` expects `text/html`; keep `/health` returning HTML (not JSON).
- Run from the project root: `pytest -q`. The background metrics thread starts on
  import — that is expected and harmless in tests.

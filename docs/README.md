# SentinelOps-Lite — AI Monitoring Platform

A production-ready Python (Flask) application with **end-to-end observability**:
Prometheus scrapes custom application / system / AI-agent / deployment metrics,
Grafana visualises them through auto-provisioned dashboards, and a standalone
HTML dashboard shows everything live in the browser. The whole stack deploys to
**AWS Elastic Beanstalk** (Multi-container Docker) with a single command.

---

## 1. Features

| Area | What you get |
|------|--------------|
| **System** | CPU, memory, disk usage/IO, network in/out, load average, uptime, boot time, process count, open FDs, logged-in users, hostname/IPs. |
| **Application** | Requests/sec, success/failed, error rate, latency (p95/p99), status codes, active sessions/users, Python RSS/CPU, threads, exceptions, restarts, uptime. |
| **AI Agent** | State (idle/running/waiting/approved/rejected/failed), task outcomes, token usage, API calls (success/failed), response time, decisions, queue size, accuracy, execution time. |
| **Deployment** | Version, build number, environment, uptime, restart count, container status. |
| **Visualisation** | Grafana (4 dashboards) + a self-contained dark/glassmorphic HTML dashboard with live gauges, charts, badges and progress bars. |
| **Alerting** | Prometheus alert rules for infra/app/agent/deployment; recording rules for fast queries. |

---

## 2. Architecture

See [`architecture.svg`](./architecture.svg) and [`monitoring-flow.svg`](./monitoring-flow.svg).

```
Browser ─▶ Nginx (:80) ─▶ Flask App (:5000)
                               │  /metrics  ─▶ Prometheus (:9090) ─▶ Grafana (:3000)
                               │  /api/status ─▶ HTML Dashboard (live, 5s)
              Node Exporter (:9100) ─▶ Prometheus
              agent.py (CI gate) ─▶ POST /monitor/status ─▶ Flask App
```

All containers run together inside one Elastic Beanstalk environment.

---

## 3. Project Structure

```
ai-monitoring-platform/
├── app.py                      # Entry point (imports `application` from agent_monitor)
├── agent.py                    # AI Agent CI release-gate (Gemini approve/reject)
├── agent_monitor.py            # Core Flask app: routes + Prometheus metrics
├── requirements.txt
├── test_app.py
├── monitoring/
│   ├── metrics.py              # All Prometheus metric definitions + collectors
│   ├── collectors.py           # JSON /api/status snapshot
│   ├── agent_state.py          # Persisted agent state (logs/agent_stats.json)
│   ├── prometheus/             # prometheus.yml, alert.rules.yml, recording.rules.yml
│   └── grafana/                # datasource + dashboards (auto-provisioned)
├── docker/                     # Dockerfile, docker-compose.yml, nginx.conf
├── deployment/                 # Dockerrun.aws.json, Procfile, .ebextensions, deploy.sh
├── static/                     # css/ + js/ for the HTML dashboard
├── templates/                  # index.html (pipeline UI) + dashboard.html
├── docs/                       # README, diagrams, deployment & troubleshooting guides
└── logs/
```

> **Note on `agent_monitor.py`**: your `app.py` imports `application` from
> `agent_monitor`, so the web app lives there. `agent.py` is the separate CI
> release-gate script that POSTs decisions to `/monitor/status`.

---

## 4. Local Quick Start (Docker)

```bash
cp .env.example .env            # add GEMINI_API_KEY, set GRAFANA_PASSWORD
docker compose -f docker/docker-compose.yml up --build
```

| Service | URL |
|---------|-----|
| App / HTML dashboard | http://localhost/  (nginx)  ·  http://localhost:5000/dashboard |
| Prometheus | http://localhost:9090 |
| Grafana | http://localhost:3000  (admin / your password) |
| Node Exporter | http://localhost:9100/metrics |

Or run the app directly (no Docker):

```bash
pip install -r requirements.txt
python app.py                  # http://localhost:5000
```

---

## 5. HTTP Endpoints

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/` | Pipeline UI (`templates/index.html`). |
| GET | `/api` | Health/info JSON. |
| GET | `/health` | Lightweight HTML health probe (LB/tests). |
| GET | `/metrics` | **Prometheus exposition format** (scraped). |
| GET | `/api/status` | Aggregated JSON snapshot for the HTML dashboard. |
| GET | `/agent/status` | Latest AI-agent state (JSON). |
| POST | `/monitor/status` | Receiver for `agent.py` (status, tokens, …). |
| GET | `/dashboard` | Standalone monitoring dashboard. |

---

## 6. Configuration (environment variables)

| Variable | Default | Notes |
|----------|---------|-------|
| `PORT` | `5000` | Gunicorn/Flask bind port. |
| `APP_VERSION` | `1.0.0` | Deployment version (exposed as metric). |
| `BUILD_NUMBER` | `local` | Build number. |
| `ENVIRONMENT` | `development` | deployment_info label. |
| `METRICS_INTERVAL` | `5` | Background gauge refresh (seconds). |
| `GEMINI_API_KEY` | — | Required by `agent.py`. |
| `MONITOR_API_URL` | `http://localhost:5000/monitor/status` | Where `agent.py` posts. |
| `GRAFANA_PASSWORD` | — | Set via EB env / `.env` (no hard-coded secret). |

---

## 7. Dashboards

- **Grafana** auto-provisions the Prometheus datasource and four dashboards:
  *Infrastructure*, *Application*, *AI Agent*, *Deployment* (plus an *Overview*).
- **HTML dashboard** (`/dashboard`) fetches `/api/status` every 10s and renders
  gauges, progress bars, health badges, rolling charts and historical graphs.

---

## 8. Testing

```bash
pip install -r requirements.txt
pytest -q
```

Covers routing, the `/metrics` exposition, the `/api/status` snapshot and the
`/monitor/status` agent receiver.

---

## 9. Deployment

See [`DEPLOYMENT.md`](./DEPLOYMENT.md) for the full Elastic Beanstalk walkthrough
(`deploy.sh` builds, pushes to ECR and deploys). For problems, see
[`TROUBLESHOOTING.md`](./TROUBLESHOOTING.md).

---

## 10. Coding Standards

Clean modular design, env-driven config, no hard-coded secrets, reusable metric
definitions in `monitoring/metrics.py`, and documentation for every layer.

"""
agent_monitor.py double success
================
Standalone AI-Agent & Pipeline monitoring module for any Flask project.

USAGE — add these lines to your main app.py / application.py:
────────────────────────────────────────────────────────────────
    from agent_monitor import application, monitor_bp, scanner_bp
    application.register_blueprint(monitor_bp)
    application.register_blueprint(scanner_bp)
────────────────────────────────────────────────────────────────

Routes exposed (ALL return HTML with navigation)
─────────────────────────────────────────────────
  GET       /monitor/dashboard   → full interactive dashboard
  GET|POST  /monitor/status      → webhook status page
  GET       /scanner/scan        → project scan results (HTML)
  GET       /scanner/health      → health check (HTML)
<<<<<<< HEAD
=======

add this in app.py or application.py main file 
from flask import render_template, Response, request

@application.route("/monitor/status", methods=["GET", "POST"])
def monitor_status():
#    CI / monitoring webhook.
    Delegates entirely to agent_monitor.handle_monitor_status().
#    from agent_monitor import handle_monitor_status
#    return handle_monitor_status()
>>>>>>> 22a34e63d08307fef2b1fff6762bfa892f2580ef
"""
# ══════════════════════════════════════════════════════════════════════════════
# IMPORTS
# ══════════════════════════════════════════════════════════════════════════════

import os
import re
import sys
import json
import glob
import datetime
import ast
import time as _time
from pathlib import Path

from flask import Flask, Blueprint, request, Response


<<<<<<< HEAD
# ══════════════════════════════════════════════════════════════════════════════
# FLASK APPLICATION
# ══════════════════════════════════════════════════════════════════════════════

BASE_DIR = Path(__file__).resolve().parent

=======
# FLASK APPLICATION


BASE_DIR = Path(__file__).resolve().parent


>>>>>>> 22a34e63d08307fef2b1fff6762bfa892f2580ef
application = Flask(
    __name__,
    template_folder=str(BASE_DIR / "templates"),
    static_folder=str(BASE_DIR / "static"),
)
application.secret_key = os.environ.get("FLASK_SECRET", "sentinelops-lite-key")

<<<<<<< HEAD
=======

>>>>>>> 22a34e63d08307fef2b1fff6762bfa892f2580ef
monitor_bp = Blueprint("monitor", __name__, url_prefix="/monitor")
scanner_bp = Blueprint("scanner", __name__, url_prefix="/scanner")


# ── LOAD CUSTOM METRICS ──────────────────────────────────────
<<<<<<< HEAD
from monitoring.metrics import (
    start_metrics_updater,
    update_metrics,
=======
# This import registers all custom Prometheus metrics (app_*, system_*, agent_*)
# in the default registry so generate_latest() exposes them at /metrics.
from monitoring.metrics import (
    start_metrics_updater,
    update_metrics,
    # Agent metrics
>>>>>>> 22a34e63d08307fef2b1fff6762bfa892f2580ef
    agent_state,
    agent_last_decision,
    agent_last_run_timestamp_seconds,
    agent_token_usage_total,
    agent_prompt_tokens_total,
    agent_completion_tokens_total,
    agent_api_calls_total,
    agent_tasks_total,
    agent_execution_time_seconds,
    agent_execution_duration_seconds,
    agent_api_key_count,
    agent_model_info,
)

<<<<<<< HEAD
update_metrics()
=======

# Run initial metric collection immediately
update_metrics()


# Start background thread to refresh process/system metrics every 5 seconds
>>>>>>> 22a34e63d08307fef2b1fff6762bfa892f2580ef
start_metrics_updater(interval=5)


# ── AGENT METRICS UPDATER ────────────────────────────────────
def _update_agent_metrics(payload: dict) -> None:
    """Update Prometheus agent metrics from a webhook payload."""
    try:
        agent_name = payload.get("agent_name", payload.get("pipeline", "pipeline"))
        stage      = payload.get("stage", payload.get("step", "deploy"))
        cloud      = payload.get("cloud", "unknown")
        status     = payload.get("status", "unknown")
        decision   = payload.get("decision", "none")
        provider   = payload.get("provider", "unknown")
        model      = payload.get("model", "unknown")

        result = "success" if status in ("success", "ok", "passed") else "failed"

<<<<<<< HEAD
=======
        # Record the agent ran
>>>>>>> 22a34e63d08307fef2b1fff6762bfa892f2580ef
        agent_last_run_timestamp_seconds.labels(
            agent_name=agent_name, stage=stage, cloud=cloud
        ).set(_time.time())

<<<<<<< HEAD
=======
        # Set agent state
>>>>>>> 22a34e63d08307fef2b1fff6762bfa892f2580ef
        for s in ("idle", "running", "approved", "rejected", "failed", "healthy"):
            agent_state.labels(
                agent_name=agent_name, stage=stage, cloud=cloud, state=s
            ).set(1 if s == ("healthy" if result == "success" else "failed") else 0)

<<<<<<< HEAD
=======
        # Count the task
>>>>>>> 22a34e63d08307fef2b1fff6762bfa892f2580ef
        agent_tasks_total.labels(
            agent_name=agent_name, stage=stage, cloud=cloud, result=result
        ).inc()

<<<<<<< HEAD
=======
        # Record decision
>>>>>>> 22a34e63d08307fef2b1fff6762bfa892f2580ef
        for d in ("none", "approved", "rejected", "failed", "healthy", "pass", "fail"):
            agent_last_decision.labels(
                agent_name=agent_name, stage=stage, cloud=cloud, decision=d
            ).set(1 if d == decision else 0)

<<<<<<< HEAD
        tokens            = payload.get("tokens", {})
=======
        # Token usage
        tokens = payload.get("tokens", {})
>>>>>>> 22a34e63d08307fef2b1fff6762bfa892f2580ef
        prompt_tokens     = int(tokens.get("prompt", tokens.get("prompt_tokens", 0)))
        completion_tokens = int(tokens.get("completion", tokens.get("completion_tokens", 0)))
        total_tokens      = prompt_tokens + completion_tokens

        if total_tokens > 0:
            agent_prompt_tokens_total.labels(
                agent_name=agent_name, stage=stage, cloud=cloud,
                provider=provider, model=model
            ).inc(prompt_tokens)
            agent_completion_tokens_total.labels(
                agent_name=agent_name, stage=stage, cloud=cloud,
                provider=provider, model=model
            ).inc(completion_tokens)
            agent_token_usage_total.labels(
                agent_name=agent_name, stage=stage, cloud=cloud,
                provider=provider, model=model
            ).inc(total_tokens)

<<<<<<< HEAD
=======
        # API call
>>>>>>> 22a34e63d08307fef2b1fff6762bfa892f2580ef
        agent_api_calls_total.labels(
            agent_name=agent_name, stage=stage, cloud=cloud,
            provider=provider, model=model, status=result
        ).inc()

<<<<<<< HEAD
=======
        # Execution time
>>>>>>> 22a34e63d08307fef2b1fff6762bfa892f2580ef
        exec_time = payload.get("execution_time", payload.get("duration", 0))
        if exec_time:
            exec_time = float(exec_time)
            agent_execution_time_seconds.labels(
                agent_name=agent_name, stage=stage, cloud=cloud
            ).set(exec_time)
            agent_execution_duration_seconds.labels(
                agent_name=agent_name, stage=stage, cloud=cloud
            ).observe(exec_time)

<<<<<<< HEAD
=======
        # API key count
>>>>>>> 22a34e63d08307fef2b1fff6762bfa892f2580ef
        api_keys = payload.get("api_keys", payload.get("api_key_count", 0))
        if api_keys:
            agent_api_key_count.labels(
                agent_name=agent_name, stage=stage, cloud=cloud, provider=provider
            ).set(int(api_keys))

<<<<<<< HEAD
=======
        # Model info
>>>>>>> 22a34e63d08307fef2b1fff6762bfa892f2580ef
        agent_model_info.labels(
            agent_name=agent_name, stage=stage, cloud=cloud
        ).info({"provider": provider, "model": model})

    except Exception:
        pass


<<<<<<< HEAD
# ══════════════════════════════════════════════════════════════════════════════
# SHARED NAV BAR + PAGE WRAPPER
# ══════════════════════════════════════════════════════════════════════════════

def wrap_page(title, body_content, active=""):
    nav_items = [
        {"url": "/",                  "label": "🏠 Home",           "key": "home"},
        {"url": "/monitor/dashboard", "label": "📊 Dashboard",      "key": "dashboard"},
        {"url": "/scanner/scan",      "label": "🔍 Scan Results",   "key": "scan"},
        {"url": "/scanner/health",    "label": "💚 Health Check",   "key": "health"},
        {"url": "/monitor/status",    "label": "📡 Webhook Status", "key": "status"},
=======
# ──────────────────────────────────────────────────────────────

# ══════════════════════════════════════════════════════════════════════════════
# SHARED NAV BAR + PAGE WRAPPER (used by ALL pages)
# ══════════════════════════════════════════════════════════════════════════════

def wrap_page(title, body_content, active=""):
    """Wrap any page content with full HTML, nav bar, and consistent styling."""
    nav_items = [
        {"url": "/", "label": "🏠 Home", "key": "home"},
        {"url": "/monitor/dashboard", "label": "📊 Dashboard", "key": "dashboard"},
        {"url": "/scanner/scan", "label": "🔍 Scan Results", "key": "scan"},
        {"url": "/scanner/health", "label": "💚 Health Check", "key": "health"},
        {"url": "/monitor/status", "label": "📡 Webhook Status", "key": "status"},
>>>>>>> 22a34e63d08307fef2b1fff6762bfa892f2580ef
    ]

    nav_html = ""
    for item in nav_items:
        active_cls = "active" if item["key"] == active else ""
        nav_html += f'<a href="{item["url"]}" class="nav-btn {active_cls}">{item["label"]}</a>'

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{title} — SentinelOps</title>
<style>
*,*::before,*::after{{box-sizing:border-box;margin:0;padding:0}}
:root{{
  --bg:#f8fdf8;--card:#ffffff;--border:#d4e8d4;--accent:#2d8a4e;
  --accent2:#1a6834;--accent-light:#e8f5e8;--text:#1a2e1a;
  --text-secondary:#4a6a4a;--shadow:0 2px 12px rgba(45,138,78,.08);
  --shadow-hover:0 4px 24px rgba(45,138,78,.14);--radius:12px;
  --gradient:linear-gradient(135deg,#2d8a4e 0%,#1a6834 100%);
}}
html{{scroll-behavior:smooth}}
<<<<<<< HEAD
body{{font-family:'Segoe UI',system-ui,-apple-system,sans-serif;background:var(--bg);color:var(--text);line-height:1.6;min-height:100vh;}}
.header{{background:var(--gradient);color:#fff;padding:20px 32px;position:sticky;top:0;z-index:100;box-shadow:0 4px 20px rgba(0,0,0,.15);}}
.header-inner{{max-width:1400px;margin:0 auto;display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:12px}}
.header h1{{font-size:1.5rem;font-weight:700;letter-spacing:-.5px;display:flex;align-items:center;gap:10px}}
.header h1 .icon{{font-size:1.8rem}}
.nav-bar{{background:#fff;border-bottom:2px solid var(--border);padding:8px 32px;position:sticky;top:68px;z-index:99;box-shadow:0 2px 8px rgba(0,0,0,.05);}}
.nav-inner{{max-width:1400px;margin:0 auto;display:flex;gap:8px;flex-wrap:wrap;align-items:center}}
.nav-btn{{display:inline-flex;align-items:center;gap:6px;padding:8px 18px;border-radius:8px;font-size:.85rem;font-weight:600;color:var(--text-secondary);text-decoration:none;border:1px solid var(--border);background:#fff;transition:all .2s ease;cursor:pointer;}}
.nav-btn:hover{{background:var(--accent-light);color:var(--accent);border-color:var(--accent);transform:translateY(-1px)}}
.nav-btn.active{{background:var(--accent);color:#fff;border-color:var(--accent)}}
.nav-btn.active:hover{{background:var(--accent2)}}
.container{{max-width:1400px;margin:0 auto;padding:24px 20px 60px}}
.card{{background:var(--card);border:1px solid var(--border);border-radius:var(--radius);padding:24px;margin-bottom:16px;box-shadow:var(--shadow);transition:all .3s ease;}}
.card:hover{{box-shadow:var(--shadow-hover)}}
.stats-grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:16px;margin-bottom:32px}}
.stat-card{{background:var(--card);border:1px solid var(--border);border-radius:var(--radius);padding:20px 24px;box-shadow:var(--shadow);transition:all .3s ease;position:relative;overflow:hidden;}}
=======
body{{
  font-family:'Segoe UI',system-ui,-apple-system,sans-serif;
  background:var(--bg);color:var(--text);line-height:1.6;min-height:100vh;
}}

/* ═══ HEADER ═══ */
.header{{
  background:var(--gradient);color:#fff;padding:20px 32px;
  position:sticky;top:0;z-index:100;
  box-shadow:0 4px 20px rgba(0,0,0,.15);
}}
.header-inner{{max-width:1400px;margin:0 auto;display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:12px}}
.header h1{{font-size:1.5rem;font-weight:700;letter-spacing:-.5px;display:flex;align-items:center;gap:10px}}
.header h1 .icon{{font-size:1.8rem}}

/* ═══ NAV BAR ═══ */
.nav-bar{{
  background:#fff;border-bottom:2px solid var(--border);padding:8px 32px;
  position:sticky;top:68px;z-index:99;box-shadow:0 2px 8px rgba(0,0,0,.05);
}}
.nav-inner{{max-width:1400px;margin:0 auto;display:flex;gap:8px;flex-wrap:wrap;align-items:center}}
.nav-btn{{
  display:inline-flex;align-items:center;gap:6px;
  padding:8px 18px;border-radius:8px;font-size:.85rem;font-weight:600;
  color:var(--text-secondary);text-decoration:none;
  border:1px solid var(--border);background:#fff;
  transition:all .2s ease;cursor:pointer;
}}
.nav-btn:hover{{background:var(--accent-light);color:var(--accent);border-color:var(--accent);transform:translateY(-1px)}}
.nav-btn.active{{background:var(--accent);color:#fff;border-color:var(--accent)}}
.nav-btn.active:hover{{background:var(--accent2)}}

/* ═══ CONTAINER ═══ */
.container{{max-width:1400px;margin:0 auto;padding:24px 20px 60px}}

/* ═══ CARDS ═══ */
.card{{
  background:var(--card);border:1px solid var(--border);border-radius:var(--radius);
  padding:24px;margin-bottom:16px;box-shadow:var(--shadow);transition:all .3s ease;
}}
.card:hover{{box-shadow:var(--shadow-hover)}}

/* ═══ STAT CARDS ═══ */
.stats-grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:16px;margin-bottom:32px}}
.stat-card{{
  background:var(--card);border:1px solid var(--border);border-radius:var(--radius);
  padding:20px 24px;box-shadow:var(--shadow);transition:all .3s ease;
  position:relative;overflow:hidden;
}}
>>>>>>> 22a34e63d08307fef2b1fff6762bfa892f2580ef
.stat-card::before{{content:'';position:absolute;top:0;left:0;width:4px;height:100%;background:var(--gradient)}}
.stat-card:hover{{transform:translateY(-2px);box-shadow:var(--shadow-hover)}}
.stat-card .stat-icon{{font-size:2rem;margin-bottom:8px}}
.stat-card .stat-value{{font-size:2rem;font-weight:800;color:var(--accent)}}
.stat-card .stat-label{{font-size:.82rem;color:var(--text-secondary);font-weight:500;text-transform:uppercase;letter-spacing:.5px}}
<<<<<<< HEAD
.section{{margin-bottom:36px}}
.section-title{{font-size:1.25rem;font-weight:700;color:var(--accent2);display:flex;align-items:center;gap:10px;margin-bottom:16px;padding-bottom:10px;border-bottom:2px solid var(--border);}}
=======

/* ═══ SECTION ═══ */
.section{{margin-bottom:36px}}
.section-title{{
  font-size:1.25rem;font-weight:700;color:var(--accent2);
  display:flex;align-items:center;gap:10px;margin-bottom:16px;
  padding-bottom:10px;border-bottom:2px solid var(--border);
}}

/* ═══ PIPELINE CARD ═══ */
>>>>>>> 22a34e63d08307fef2b1fff6762bfa892f2580ef
.pipeline-card{{border-left:4px solid var(--accent)}}
.pipeline-status{{display:inline-flex;align-items:center;gap:5px;padding:3px 12px;border-radius:20px;font-size:.75rem;font-weight:600}}
.pipeline-status.running{{background:#d4edda;color:#155724}}
.pipeline-status.detected{{background:#fff3cd;color:#856404}}
.config-file-tag{{background:var(--accent-light);color:var(--accent2);padding:3px 10px;border-radius:6px;font-size:.78rem;font-family:monospace;display:inline-block;margin:2px}}
<<<<<<< HEAD
.char-grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(280px,1fr));gap:12px}}
.char-card{{background:var(--accent-light);border:1px solid var(--border);border-radius:10px;padding:14px 18px;display:flex;align-items:flex-start;gap:12px;transition:all .25s ease;}}
=======

/* ═══ CHARS ═══ */
.char-grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(280px,1fr));gap:12px}}
.char-card{{
  background:var(--accent-light);border:1px solid var(--border);
  border-radius:10px;padding:14px 18px;display:flex;align-items:flex-start;gap:12px;transition:all .25s ease;
}}
>>>>>>> 22a34e63d08307fef2b1fff6762bfa892f2580ef
.char-card:hover{{transform:scale(1.02);background:#d8f0d8}}
.char-icon{{font-size:1.6rem;flex-shrink:0}}
.char-info h4{{font-weight:700;color:var(--accent2);font-size:.92rem}}
.char-info p{{font-size:.8rem;color:var(--text-secondary);margin-top:2px}}
<<<<<<< HEAD
.file-tree-header{{display:grid;grid-template-columns:30px 1fr 1fr 80px;gap:8px;padding:10px 12px;background:var(--accent);color:#fff;border-radius:var(--radius) var(--radius) 0 0;font-weight:700;font-size:.82rem;}}
.file-row{{display:grid;grid-template-columns:30px 1fr 1fr 80px;gap:8px;padding:8px 12px;border-bottom:1px solid #eef4ee;align-items:center;font-size:.82rem;transition:background .15s;}}
.file-row:hover{{background:var(--accent-light)}}
.file-row.main-file{{background:#e0f2e0;font-weight:600}}
=======

/* ═══ FILE TREE ═══ */
.file-tree-header{{
  display:grid;grid-template-columns:30px 1fr 1fr 80px;gap:8px;
  padding:10px 12px;background:var(--accent);color:#fff;
  border-radius:var(--radius) var(--radius) 0 0;font-weight:700;font-size:.82rem;
}}
.file-row{{
  display:grid;grid-template-columns:30px 1fr 1fr 80px;gap:8px;
  padding:8px 12px;border-bottom:1px solid #eef4ee;align-items:center;
  font-size:.82rem;transition:background .15s;
}}
.file-row:hover{{background:var(--accent-light)}}
.file-row.main-file{{background:#e0f2e0;font-weight:600}}

/* ═══ AGENT DETAIL ═══ */
>>>>>>> 22a34e63d08307fef2b1fff6762bfa892f2580ef
.agent-card{{border-left:4px solid #2d8a4e}}
.model-detail{{background:#f0f8f0;border:1px solid var(--border);border-radius:10px;padding:18px;margin-top:12px}}
.model-detail h4{{color:var(--accent2);font-size:1rem;margin-bottom:12px}}
.detail-grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(240px,1fr));gap:12px}}
.detail-box{{background:#fff;border:1px solid var(--border);border-radius:8px;padding:14px}}
.detail-box h5{{font-size:.78rem;text-transform:uppercase;letter-spacing:.5px;color:var(--accent);margin-bottom:8px}}
.detail-row{{display:flex;justify-content:space-between;padding:3px 0;font-size:.82rem;border-bottom:1px solid #f0f0f0}}
.detail-row:last-child{{border-bottom:none}}
.detail-label{{color:var(--text-secondary)}}
.detail-value{{font-weight:600;color:var(--text)}}
<<<<<<< HEAD
=======

/* ═══ GAUGE ═══ */
>>>>>>> 22a34e63d08307fef2b1fff6762bfa892f2580ef
.gauge-container{{display:flex;align-items:center;gap:12px;margin:8px 0}}
.gauge-bar{{flex:1;height:10px;background:#e0e0e0;border-radius:5px;overflow:hidden}}
.gauge-fill{{height:100%;border-radius:5px;transition:width 1s ease;background:var(--gradient)}}
.gauge-fill.warn{{background:linear-gradient(90deg,#f0ad4e,#d9534f)}}
.gauge-text{{font-size:.78rem;font-weight:600;color:var(--accent);min-width:50px;text-align:right}}
<<<<<<< HEAD
=======

/* ═══ TAGS ═══ */
>>>>>>> 22a34e63d08307fef2b1fff6762bfa892f2580ef
.tag{{display:inline-flex;align-items:center;gap:4px;padding:3px 10px;border-radius:6px;font-size:.75rem;font-weight:600;margin:2px}}
.tag.provider{{background:#d4edda;color:#155724}}
.tag.model{{background:#cce5ff;color:#004085}}
.tag.pattern{{background:#fff3cd;color:#856404}}
.tag.env{{background:#f8d7da;color:#721c24}}
<<<<<<< HEAD
.json-box{{background:#1a2e1a;color:#a8d8a8;padding:20px;border-radius:var(--radius);font-family:'Cascadia Code','Fira Code',monospace;font-size:.82rem;overflow-x:auto;white-space:pre-wrap;word-break:break-word;max-height:600px;overflow-y:auto;line-height:1.5;}}
.json-key{{color:#8be9fd}}.json-str{{color:#50fa7b}}.json-num{{color:#ffb86c}}.json-bool{{color:#ff79c6}}.json-null{{color:#6272a4}}
=======

/* ═══ JSON BOX ═══ */
.json-box{{
  background:#1a2e1a;color:#a8d8a8;padding:20px;border-radius:var(--radius);
  font-family:'Cascadia Code','Fira Code',monospace;font-size:.82rem;
  overflow-x:auto;white-space:pre-wrap;word-break:break-word;
  max-height:600px;overflow-y:auto;line-height:1.5;
}}
.json-key{{color:#8be9fd}}
.json-str{{color:#50fa7b}}
.json-num{{color:#ffb86c}}
.json-bool{{color:#ff79c6}}
.json-null{{color:#6272a4}}

/* ═══ STATUS PAGE ═══ */
>>>>>>> 22a34e63d08307fef2b1fff6762bfa892f2580ef
.status-ok{{color:#28a745;font-size:3rem;font-weight:800}}
.status-card{{text-align:center;padding:40px}}
.status-icon{{font-size:4rem;margin-bottom:16px}}
.webhook-form{{max-width:600px;margin:20px auto}}
<<<<<<< HEAD
.webhook-form textarea{{width:100%;height:120px;padding:12px;border:1px solid var(--border);border-radius:8px;font-family:monospace;font-size:.85rem;resize:vertical;}}
.webhook-form button{{margin-top:12px;padding:10px 24px;background:var(--gradient);color:#fff;border:none;border-radius:8px;font-weight:600;cursor:pointer;font-size:.9rem;transition:all .2s;}}
.webhook-form button:hover{{transform:translateY(-1px);box-shadow:var(--shadow-hover)}}
#webhookResult{{margin-top:16px}}
.tabs{{display:flex;gap:4px;margin-bottom:20px;border-bottom:2px solid var(--border)}}
.tab{{padding:10px 20px;cursor:pointer;font-weight:600;font-size:.88rem;color:var(--text-secondary);border-bottom:3px solid transparent;transition:all .2s;margin-bottom:-2px;}}
=======
.webhook-form textarea{{
  width:100%;height:120px;padding:12px;border:1px solid var(--border);
  border-radius:8px;font-family:monospace;font-size:.85rem;resize:vertical;
}}
.webhook-form button{{
  margin-top:12px;padding:10px 24px;background:var(--gradient);color:#fff;
  border:none;border-radius:8px;font-weight:600;cursor:pointer;font-size:.9rem;
  transition:all .2s;
}}
.webhook-form button:hover{{transform:translateY(-1px);box-shadow:var(--shadow-hover)}}
#webhookResult{{margin-top:16px}}

/* ═══ TABS ═══ */
.tabs{{display:flex;gap:4px;margin-bottom:20px;border-bottom:2px solid var(--border)}}
.tab{{
  padding:10px 20px;cursor:pointer;font-weight:600;font-size:.88rem;
  color:var(--text-secondary);border-bottom:3px solid transparent;
  transition:all .2s;margin-bottom:-2px;
}}
>>>>>>> 22a34e63d08307fef2b1fff6762bfa892f2580ef
.tab:hover{{color:var(--accent)}}
.tab.active{{color:var(--accent);border-bottom-color:var(--accent)}}
.tab-content{{display:none}}
.tab-content.active{{display:block}}
<<<<<<< HEAD
.empty-state{{text-align:center;padding:40px;color:var(--text-secondary);background:var(--accent-light);border-radius:var(--radius)}}
.empty-state .empty-icon{{font-size:3rem;margin-bottom:12px}}
.page-footer{{text-align:center;padding:20px;color:var(--text-secondary);font-size:.78rem;border-top:1px solid var(--border);margin-top:40px}}
.badge{{display:inline-flex;align-items:center;gap:5px;padding:4px 14px;border-radius:20px;font-size:.78rem;font-weight:600;background:rgba(255,255,255,.2);color:#fff}}
@media(max-width:768px){{
  .header{{padding:12px 16px}}.header h1{{font-size:1.1rem}}
  .nav-bar{{padding:6px 16px}}.nav-btn{{padding:6px 12px;font-size:.78rem}}
  .stats-grid{{grid-template-columns:repeat(2,1fr)}}
  .char-grid{{grid-template-columns:1fr}}.detail-grid{{grid-template-columns:1fr}}
  .file-row{{grid-template-columns:24px 1fr 80px}}.file-row .f-purpose{{display:none}}
  .file-tree-header{{grid-template-columns:24px 1fr 80px}}.file-tree-header .fh-purpose{{display:none}}
}}
</style>
</head>
<body>
=======

/* ═══ LOADING ═══ */
.spinner{{width:48px;height:48px;border:4px solid var(--border);border-top-color:var(--accent);border-radius:50%;animation:spin .8s linear infinite;margin:0 auto 16px}}
@keyframes spin{{to{{transform:rotate(360deg)}}}}

/* ═══ EMPTY ═══ */
.empty-state{{text-align:center;padding:40px;color:var(--text-secondary);background:var(--accent-light);border-radius:var(--radius)}}
.empty-state .empty-icon{{font-size:3rem;margin-bottom:12px}}

/* ═══ FOOTER ═══ */
.page-footer{{text-align:center;padding:20px;color:var(--text-secondary);font-size:.78rem;border-top:1px solid var(--border);margin-top:40px}}

/* ═══ BADGE ═══ */
.badge{{display:inline-flex;align-items:center;gap:5px;padding:4px 14px;border-radius:20px;font-size:.78rem;font-weight:600;background:rgba(255,255,255,.2);color:#fff}}
.badge.live{{animation:pulse-badge 2s infinite}}
@keyframes pulse-badge{{0%,100%{{opacity:1}}50%{{opacity:.6}}}}

/* ═══ RESPONSIVE ═══ */
@media(max-width:768px){{
  .header{{padding:12px 16px}}
  .header h1{{font-size:1.1rem}}
  .nav-bar{{padding:6px 16px}}
  .nav-btn{{padding:6px 12px;font-size:.78rem}}
  .stats-grid{{grid-template-columns:repeat(2,1fr)}}
  .char-grid{{grid-template-columns:1fr}}
  .detail-grid{{grid-template-columns:1fr}}
  .file-row{{grid-template-columns:24px 1fr 80px}}
  .file-row .f-purpose{{display:none}}
  .file-tree-header{{grid-template-columns:24px 1fr 80px}}
  .file-tree-header .fh-purpose{{display:none}}
}}

.refresh-btn{{
  background:rgba(255,255,255,.2);color:#fff;border:1px solid rgba(255,255,255,.3);
  padding:8px 18px;border-radius:8px;cursor:pointer;font-weight:600;font-size:.85rem;
  transition:all .2s;display:flex;align-items:center;gap:6px;
}}
.refresh-btn:hover{{background:rgba(255,255,255,.35)}}
</style>
</head>
<body>

<!-- HEADER -->
>>>>>>> 22a34e63d08307fef2b1fff6762bfa892f2580ef
<div class="header">
  <div class="header-inner">
    <h1><span class="icon">🛡️</span> SentinelOps Monitor</h1>
    <div style="display:flex;align-items:center;gap:8px">
      <span class="badge">🕐 {datetime.datetime.now().strftime('%H:%M:%S')}</span>
    </div>
  </div>
</div>
<<<<<<< HEAD
<div class="nav-bar">
  <div class="nav-inner">{nav_html}</div>
</div>
<div class="container">
{body_content}
</div>
<div class="page-footer">
  🛡️ SentinelOps Lite — AI Agent & Pipeline Monitor &nbsp;|&nbsp; Scanned at {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S UTC')}
</div>
=======

<!-- NAV BAR -->
<div class="nav-bar">
  <div class="nav-inner">
    {nav_html}
  </div>
</div>

<!-- CONTENT -->
<div class="container">
{body_content}
</div>

<!-- FOOTER -->
<div class="page-footer">
  🛡️ SentinelOps Lite — AI Agent & Pipeline Monitor &nbsp;|&nbsp; Scanned at {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S UTC')}
</div>

>>>>>>> 22a34e63d08307fef2b1fff6762bfa892f2580ef
</body>
</html>"""


# ══════════════════════════════════════════════════════════════════════════════
# PIPELINE DETECTOR
# ══════════════════════════════════════════════════════════════════════════════

PIPELINE_SIGNATURES = {
    "GitHub Actions": {
        "files": [".github/workflows/*.yml", ".github/workflows/*.yaml"],
        "env_vars": ["GITHUB_ACTIONS", "GITHUB_WORKFLOW", "GITHUB_RUN_ID"],
        "description": "GitHub's built-in CI/CD platform that automates build, test, and deploy workflows directly from your GitHub repository using YAML workflow files.",
    },
    "Azure DevOps": {
        "files": ["azure-pipelines.yml", "azure-pipelines.yaml", ".azure-pipelines/*.yml"],
        "env_vars": ["TF_BUILD", "BUILD_BUILDID", "SYSTEM_TEAMFOUNDATIONCOLLECTIONURI"],
        "description": "Microsoft's enterprise CI/CD service offering pipelines, boards, repos, and artifacts — tightly integrated with Azure cloud services.",
    },
    "Jenkins": {
        "files": ["Jenkinsfile", "jenkins/*.groovy"],
        "env_vars": ["JENKINS_URL", "BUILD_ID", "JENKINS_HOME"],
        "description": "Open-source automation server that enables developers to build, test, and deploy software with hundreds of plugins for CI/CD pipelines.",
    },
    "GitLab CI": {
        "files": [".gitlab-ci.yml"],
        "env_vars": ["GITLAB_CI", "CI_PIPELINE_ID"],
        "description": "GitLab's integrated CI/CD that runs pipelines defined in .gitlab-ci.yml for automated testing and deployment.",
    },
    "CircleCI": {
        "files": [".circleci/config.yml"],
        "env_vars": ["CIRCLECI", "CIRCLE_BUILD_NUM"],
        "description": "Cloud-native CI/CD platform that automates the software development process using intelligent caching and parallelism.",
    },
    "Travis CI": {
        "files": [".travis.yml"],
        "env_vars": ["TRAVIS", "TRAVIS_BUILD_ID"],
        "description": "Hosted continuous integration service used to build and test software projects hosted on GitHub and Bitbucket.",
    },
    "Bitbucket Pipelines": {
        "files": ["bitbucket-pipelines.yml"],
        "env_vars": ["BITBUCKET_PIPELINE_UUID", "BITBUCKET_BUILD_NUMBER"],
        "description": "Atlassian's integrated CI/CD for Bitbucket Cloud, running builds in Docker containers.",
    },
    "AWS CodePipeline": {
        "files": ["buildspec.yml", "buildspec.yaml", "appspec.yml"],
        "env_vars": ["CODEBUILD_BUILD_ID", "CODEBUILD_SOURCE_VERSION"],
        "description": "AWS fully managed continuous delivery service for fast and reliable application and infrastructure updates.",
    },
}


def detect_pipelines():
    results = []
    for name, sig in PIPELINE_SIGNATURES.items():
        found_files = []
        for pattern in sig["files"]:
            found_files.extend(glob.glob(str(BASE_DIR / pattern), recursive=True))
        running_env = [v for v in sig["env_vars"] if os.environ.get(v)]
        if found_files or running_env:
            pipeline_display_name = _extract_pipeline_name(name, found_files)
            results.append({
<<<<<<< HEAD
                "platform":        name,
                "pipeline_name":   pipeline_display_name,
                "description":     sig["description"],
                "config_files":    [str(Path(f).relative_to(BASE_DIR)) for f in found_files],
=======
                "platform": name,
                "pipeline_name": pipeline_display_name,
                "description": sig["description"],
                "config_files": [str(Path(f).relative_to(BASE_DIR)) for f in found_files],
>>>>>>> 22a34e63d08307fef2b1fff6762bfa892f2580ef
                "active_env_vars": running_env,
                "is_running_here": len(running_env) > 0,
            })
    return results


def _extract_pipeline_name(platform, files):
    for f in files:
        try:
            with open(f, "r", encoding="utf-8", errors="ignore") as fh:
                content = fh.read()
            if platform in ("GitHub Actions", "Azure DevOps"):
                m = re.search(r'^name:\s*(.+)', content, re.MULTILINE)
                if m:
                    return m.group(1).strip().strip('"').strip("'")
            elif platform == "Jenkins":
                return "Jenkinsfile Pipeline"
            elif platform == "GitLab CI":
                return "GitLab CI Pipeline"
        except Exception:
            pass
    return f"{platform} Pipeline"


# ══════════════════════════════════════════════════════════════════════════════
<<<<<<< HEAD
# AI PROVIDER FULL METRICS DATABASE
=======
# AI AGENT DETECTOR
>>>>>>> 22a34e63d08307fef2b1fff6762bfa892f2580ef
# ══════════════════════════════════════════════════════════════════════════════

AI_PROVIDER_FULL_METRICS = {
    "OpenAI": {
<<<<<<< HEAD
        "imports":  ["openai", "OpenAI", "AsyncOpenAI"],
        "env_keys": ["OPENAI_API_KEY", "OPENAI_KEY", "OPENAI_ORG_ID"],
        "website":  "https://platform.openai.com",
        "models": {
            "gpt-4o": {
                "full_name": "GPT-4o", "type": "Chat / Multimodal",
                "context_window": 128000, "max_output_tokens": 16384,
                "input_cost_per_1k": 0.005, "output_cost_per_1k": 0.015,
                "rate_limits": {"rpm": 500, "rpd": 10000, "tpm": 30000, "tpd": 1000000},
                "features": ["vision", "function_calling", "json_mode", "streaming"],
                "training_cutoff": "Oct 2023", "latency": "medium",
            },
            "gpt-4o-mini": {
                "full_name": "GPT-4o Mini", "type": "Chat / Lightweight",
                "context_window": 128000, "max_output_tokens": 16384,
                "input_cost_per_1k": 0.000150, "output_cost_per_1k": 0.000600,
                "rate_limits": {"rpm": 500, "rpd": 10000, "tpm": 200000, "tpd": 2000000},
                "features": ["vision", "function_calling", "json_mode", "streaming"],
                "training_cutoff": "Oct 2023", "latency": "fast",
            },
            "gpt-4-turbo": {
                "full_name": "GPT-4 Turbo", "type": "Chat",
                "context_window": 128000, "max_output_tokens": 4096,
                "input_cost_per_1k": 0.010, "output_cost_per_1k": 0.030,
                "rate_limits": {"rpm": 500, "rpd": 10000, "tpm": 30000, "tpd": 1000000},
                "features": ["vision", "function_calling", "json_mode", "streaming"],
                "training_cutoff": "Apr 2024", "latency": "medium",
            },
            "gpt-4": {
                "full_name": "GPT-4", "type": "Chat",
                "context_window": 8192, "max_output_tokens": 8192,
                "input_cost_per_1k": 0.030, "output_cost_per_1k": 0.060,
                "rate_limits": {"rpm": 500, "rpd": 10000, "tpm": 10000, "tpd": 300000},
                "features": ["function_calling", "json_mode"],
                "training_cutoff": "Sep 2021", "latency": "slow",
            },
            "gpt-3.5-turbo": {
                "full_name": "GPT-3.5 Turbo", "type": "Chat",
                "context_window": 16385, "max_output_tokens": 4096,
                "input_cost_per_1k": 0.0005, "output_cost_per_1k": 0.0015,
                "rate_limits": {"rpm": 3500, "rpd": 10000, "tpm": 90000, "tpd": 2000000},
                "features": ["function_calling", "json_mode", "streaming"],
                "training_cutoff": "Sep 2021", "latency": "fast",
            },
            "o1-preview": {
                "full_name": "O1 Preview", "type": "Reasoning",
                "context_window": 128000, "max_output_tokens": 32768,
                "input_cost_per_1k": 0.015, "output_cost_per_1k": 0.060,
                "rate_limits": {"rpm": 500, "rpd": 10000, "tpm": 30000, "tpd": 1000000},
                "features": ["reasoning", "streaming"],
                "training_cutoff": "Oct 2023", "latency": "very_slow",
            },
            "o1-mini": {
                "full_name": "O1 Mini", "type": "Reasoning / Lightweight",
                "context_window": 128000, "max_output_tokens": 65536,
                "input_cost_per_1k": 0.003, "output_cost_per_1k": 0.012,
                "rate_limits": {"rpm": 500, "rpd": 10000, "tpm": 200000, "tpd": 2000000},
                "features": ["reasoning", "streaming"],
                "training_cutoff": "Oct 2023", "latency": "slow",
            },
            "o3-mini": {
                "full_name": "O3 Mini", "type": "Reasoning / Fast",
                "context_window": 200000, "max_output_tokens": 100000,
                "input_cost_per_1k": 0.0011, "output_cost_per_1k": 0.0044,
                "rate_limits": {"rpm": 500, "rpd": 10000, "tpm": 200000, "tpd": 2000000},
                "features": ["reasoning", "function_calling", "streaming"],
                "training_cutoff": "Oct 2023", "latency": "fast",
=======
        "imports": ["openai", "OpenAI", "AsyncOpenAI"],
        "env_keys": ["OPENAI_API_KEY", "OPENAI_KEY", "OPENAI_ORG_ID"],
        "website": "https://platform.openai.com",
        "models": {
            "gpt-4o": {
                "full_name": "GPT-4o",
                "type": "Chat / Multimodal",
                "context_window": 128000,
                "max_output_tokens": 16384,
                "input_cost_per_1k": 0.005,
                "output_cost_per_1k": 0.015,
                "rate_limits": {"rpm": 500, "rpd": 10000, "tpm": 30000, "tpd": 1000000},
                "features": ["vision", "function_calling", "json_mode", "streaming"],
                "training_cutoff": "Oct 2023",
                "latency": "medium",
            },
            "gpt-4o-mini": {
                "full_name": "GPT-4o Mini",
                "type": "Chat / Lightweight",
                "context_window": 128000,
                "max_output_tokens": 16384,
                "input_cost_per_1k": 0.000150,
                "output_cost_per_1k": 0.000600,
                "rate_limits": {"rpm": 500, "rpd": 10000, "tpm": 200000, "tpd": 2000000},
                "features": ["vision", "function_calling", "json_mode", "streaming"],
                "training_cutoff": "Oct 2023",
                "latency": "fast",
            },
            "gpt-4-turbo": {
                "full_name": "GPT-4 Turbo",
                "type": "Chat",
                "context_window": 128000,
                "max_output_tokens": 4096,
                "input_cost_per_1k": 0.010,
                "output_cost_per_1k": 0.030,
                "rate_limits": {"rpm": 500, "rpd": 10000, "tpm": 30000, "tpd": 1000000},
                "features": ["vision", "function_calling", "json_mode", "streaming"],
                "training_cutoff": "Apr 2024",
                "latency": "medium",
            },
            "gpt-4": {
                "full_name": "GPT-4",
                "type": "Chat",
                "context_window": 8192,
                "max_output_tokens": 8192,
                "input_cost_per_1k": 0.030,
                "output_cost_per_1k": 0.060,
                "rate_limits": {"rpm": 500, "rpd": 10000, "tpm": 10000, "tpd": 300000},
                "features": ["function_calling", "json_mode"],
                "training_cutoff": "Sep 2021",
                "latency": "slow",
            },
            "gpt-3.5-turbo": {
                "full_name": "GPT-3.5 Turbo",
                "type": "Chat",
                "context_window": 16385,
                "max_output_tokens": 4096,
                "input_cost_per_1k": 0.0005,
                "output_cost_per_1k": 0.0015,
                "rate_limits": {"rpm": 3500, "rpd": 10000, "tpm": 90000, "tpd": 2000000},
                "features": ["function_calling", "json_mode", "streaming"],
                "training_cutoff": "Sep 2021",
                "latency": "fast",
            },
            "o1-preview": {
                "full_name": "O1 Preview",
                "type": "Reasoning",
                "context_window": 128000,
                "max_output_tokens": 32768,
                "input_cost_per_1k": 0.015,
                "output_cost_per_1k": 0.060,
                "rate_limits": {"rpm": 500, "rpd": 10000, "tpm": 30000, "tpd": 1000000},
                "features": ["reasoning", "streaming"],
                "training_cutoff": "Oct 2023",
                "latency": "very_slow",
            },
            "o1-mini": {
                "full_name": "O1 Mini",
                "type": "Reasoning / Lightweight",
                "context_window": 128000,
                "max_output_tokens": 65536,
                "input_cost_per_1k": 0.003,
                "output_cost_per_1k": 0.012,
                "rate_limits": {"rpm": 500, "rpd": 10000, "tpm": 200000, "tpd": 2000000},
                "features": ["reasoning", "streaming"],
                "training_cutoff": "Oct 2023",
                "latency": "slow",
            },
            "o3-mini": {
                "full_name": "O3 Mini",
                "type": "Reasoning / Fast",
                "context_window": 200000,
                "max_output_tokens": 100000,
                "input_cost_per_1k": 0.0011,
                "output_cost_per_1k": 0.0044,
                "rate_limits": {"rpm": 500, "rpd": 10000, "tpm": 200000, "tpd": 2000000},
                "features": ["reasoning", "function_calling", "streaming"],
                "training_cutoff": "Oct 2023",
                "latency": "fast",
>>>>>>> 22a34e63d08307fef2b1fff6762bfa892f2580ef
            },
        },
    },

    "Anthropic (Claude)": {
<<<<<<< HEAD
        "imports":  ["anthropic", "Anthropic", "AsyncAnthropic"],
        "env_keys": ["ANTHROPIC_API_KEY"],
        "website":  "https://console.anthropic.com",
        "models": {
            "claude-3-5-sonnet-20241022": {
                "full_name": "Claude 3.5 Sonnet", "type": "Chat / Flagship",
                "context_window": 200000, "max_output_tokens": 8192,
                "input_cost_per_1k": 0.003, "output_cost_per_1k": 0.015,
                "rate_limits": {"rpm": 1000, "rpd": 50000, "tpm": 80000, "tpd": 5000000},
                "features": ["vision", "tool_use", "streaming", "json_mode"],
                "training_cutoff": "Apr 2024", "latency": "medium",
            },
            "claude-3-5-haiku-20241022": {
                "full_name": "Claude 3.5 Haiku", "type": "Chat / Fast",
                "context_window": 200000, "max_output_tokens": 8192,
                "input_cost_per_1k": 0.0008, "output_cost_per_1k": 0.004,
                "rate_limits": {"rpm": 4000, "rpd": 200000, "tpm": 400000, "tpd": 10000000},
                "features": ["vision", "tool_use", "streaming"],
                "training_cutoff": "Jul 2024", "latency": "fast",
            },
            "claude-3-opus-20240229": {
                "full_name": "Claude 3 Opus", "type": "Chat / Most Capable",
                "context_window": 200000, "max_output_tokens": 4096,
                "input_cost_per_1k": 0.015, "output_cost_per_1k": 0.075,
                "rate_limits": {"rpm": 1000, "rpd": 50000, "tpm": 40000, "tpd": 1000000},
                "features": ["vision", "tool_use", "streaming"],
                "training_cutoff": "Aug 2023", "latency": "slow",
            },
            "claude-3-haiku-20240307": {
                "full_name": "Claude 3 Haiku", "type": "Chat / Fastest",
                "context_window": 200000, "max_output_tokens": 4096,
                "input_cost_per_1k": 0.00025, "output_cost_per_1k": 0.00125,
                "rate_limits": {"rpm": 4000, "rpd": 200000, "tpm": 400000, "tpd": 10000000},
                "features": ["vision", "tool_use", "streaming"],
                "training_cutoff": "Aug 2023", "latency": "very_fast",
            },
            "claude-3-sonnet-20240229": {
                "full_name": "Claude 3 Sonnet", "type": "Chat / Balanced",
                "context_window": 200000, "max_output_tokens": 4096,
                "input_cost_per_1k": 0.003, "output_cost_per_1k": 0.015,
                "rate_limits": {"rpm": 1000, "rpd": 50000, "tpm": 80000, "tpd": 5000000},
                "features": ["vision", "tool_use", "streaming"],
                "training_cutoff": "Aug 2023", "latency": "medium",
=======
        "imports": ["anthropic", "Anthropic", "AsyncAnthropic"],
        "env_keys": ["ANTHROPIC_API_KEY"],
        "website": "https://console.anthropic.com",
        "models": {
            "claude-3-5-sonnet-20241022": {
                "full_name": "Claude 3.5 Sonnet",
                "type": "Chat / Flagship",
                "context_window": 200000,
                "max_output_tokens": 8192,
                "input_cost_per_1k": 0.003,
                "output_cost_per_1k": 0.015,
                "rate_limits": {"rpm": 1000, "rpd": 50000, "tpm": 80000, "tpd": 5000000},
                "features": ["vision", "tool_use", "streaming", "json_mode"],
                "training_cutoff": "Apr 2024",
                "latency": "medium",
            },
            "claude-3-5-haiku-20241022": {
                "full_name": "Claude 3.5 Haiku",
                "type": "Chat / Fast",
                "context_window": 200000,
                "max_output_tokens": 8192,
                "input_cost_per_1k": 0.0008,
                "output_cost_per_1k": 0.004,
                "rate_limits": {"rpm": 4000, "rpd": 200000, "tpm": 400000, "tpd": 10000000},
                "features": ["vision", "tool_use", "streaming"],
                "training_cutoff": "Jul 2024",
                "latency": "fast",
            },
            "claude-3-opus-20240229": {
                "full_name": "Claude 3 Opus",
                "type": "Chat / Most Capable",
                "context_window": 200000,
                "max_output_tokens": 4096,
                "input_cost_per_1k": 0.015,
                "output_cost_per_1k": 0.075,
                "rate_limits": {"rpm": 1000, "rpd": 50000, "tpm": 40000, "tpd": 1000000},
                "features": ["vision", "tool_use", "streaming"],
                "training_cutoff": "Aug 2023",
                "latency": "slow",
            },
            "claude-3-haiku-20240307": {
                "full_name": "Claude 3 Haiku",
                "type": "Chat / Fastest",
                "context_window": 200000,
                "max_output_tokens": 4096,
                "input_cost_per_1k": 0.00025,
                "output_cost_per_1k": 0.00125,
                "rate_limits": {"rpm": 4000, "rpd": 200000, "tpm": 400000, "tpd": 10000000},
                "features": ["vision", "tool_use", "streaming"],
                "training_cutoff": "Aug 2023",
                "latency": "very_fast",
            },
            "claude-3-sonnet-20240229": {
                "full_name": "Claude 3 Sonnet",
                "type": "Chat / Balanced",
                "context_window": 200000,
                "max_output_tokens": 4096,
                "input_cost_per_1k": 0.003,
                "output_cost_per_1k": 0.015,
                "rate_limits": {"rpm": 1000, "rpd": 50000, "tpm": 80000, "tpd": 5000000},
                "features": ["vision", "tool_use", "streaming"],
                "training_cutoff": "Aug 2023",
                "latency": "medium",
>>>>>>> 22a34e63d08307fef2b1fff6762bfa892f2580ef
            },
        },
    },

    "Google Gemini": {
<<<<<<< HEAD
        "imports":  ["google.generativeai", "genai", "vertexai", "google.ai.generativelanguage"],
        "env_keys": ["GOOGLE_API_KEY", "GEMINI_API_KEY", "GOOGLE_APPLICATION_CREDENTIALS"],
        "website":  "https://aistudio.google.com",
        "models": {
            "gemini-1.5-pro": {
                "full_name": "Gemini 1.5 Pro", "type": "Chat / Multimodal",
                "context_window": 2097152, "max_output_tokens": 8192,
                "input_cost_per_1k": 0.00125, "output_cost_per_1k": 0.005,
                "rate_limits": {"rpm": 360, "rpd": 50000, "tpm": 4000000, "tpd": 0},
                "features": ["vision", "audio", "video", "function_calling", "streaming"],
                "training_cutoff": "Nov 2023", "latency": "medium",
            },
            "gemini-1.5-flash": {
                "full_name": "Gemini 1.5 Flash", "type": "Chat / Fast Multimodal",
                "context_window": 1048576, "max_output_tokens": 8192,
                "input_cost_per_1k": 0.000075, "output_cost_per_1k": 0.000300,
                "rate_limits": {"rpm": 1000, "rpd": 100000, "tpm": 4000000, "tpd": 0},
                "features": ["vision", "audio", "function_calling", "streaming"],
                "training_cutoff": "Nov 2023", "latency": "fast",
            },
            "gemini-2.0-flash": {
                "full_name": "Gemini 2.0 Flash", "type": "Chat / Next Gen",
                "context_window": 1048576, "max_output_tokens": 8192,
                "input_cost_per_1k": 0.000100, "output_cost_per_1k": 0.000400,
                "rate_limits": {"rpm": 1000, "rpd": 100000, "tpm": 4000000, "tpd": 0},
                "features": ["vision", "audio", "function_calling", "streaming"],
                "training_cutoff": "Jan 2025", "latency": "fast",
            },
            "gemini-pro": {
                "full_name": "Gemini Pro", "type": "Chat",
                "context_window": 32760, "max_output_tokens": 8192,
                "input_cost_per_1k": 0.0005, "output_cost_per_1k": 0.0015,
                "rate_limits": {"rpm": 60, "rpd": 1500, "tpm": 32000, "tpd": 0},
                "features": ["function_calling", "streaming"],
                "training_cutoff": "Feb 2023", "latency": "medium",
=======
        "imports": ["google.generativeai", "genai", "vertexai", "google.ai.generativelanguage"],
        "env_keys": ["GOOGLE_API_KEY", "GEMINI_API_KEY", "GOOGLE_APPLICATION_CREDENTIALS"],
        "website": "https://aistudio.google.com",
        "models": {
            "gemini-1.5-pro": {
                "full_name": "Gemini 1.5 Pro",
                "type": "Chat / Multimodal",
                "context_window": 2097152,
                "max_output_tokens": 8192,
                "input_cost_per_1k": 0.00125,
                "output_cost_per_1k": 0.005,
                "rate_limits": {"rpm": 360, "rpd": 50000, "tpm": 4000000, "tpd": 0},
                "features": ["vision", "audio", "video", "function_calling", "streaming"],
                "training_cutoff": "Nov 2023",
                "latency": "medium",
            },
            "gemini-1.5-flash": {
                "full_name": "Gemini 1.5 Flash",
                "type": "Chat / Fast Multimodal",
                "context_window": 1048576,
                "max_output_tokens": 8192,
                "input_cost_per_1k": 0.000075,
                "output_cost_per_1k": 0.000300,
                "rate_limits": {"rpm": 1000, "rpd": 100000, "tpm": 4000000, "tpd": 0},
                "features": ["vision", "audio", "function_calling", "streaming"],
                "training_cutoff": "Nov 2023",
                "latency": "fast",
            },
            "gemini-2.0-flash": {
                "full_name": "Gemini 2.0 Flash",
                "type": "Chat / Next Gen",
                "context_window": 1048576,
                "max_output_tokens": 8192,
                "input_cost_per_1k": 0.000100,
                "output_cost_per_1k": 0.000400,
                "rate_limits": {"rpm": 1000, "rpd": 100000, "tpm": 4000000, "tpd": 0},
                "features": ["vision", "audio", "function_calling", "streaming"],
                "training_cutoff": "Jan 2025",
                "latency": "fast",
            },
            "gemini-pro": {
                "full_name": "Gemini Pro",
                "type": "Chat",
                "context_window": 32760,
                "max_output_tokens": 8192,
                "input_cost_per_1k": 0.0005,
                "output_cost_per_1k": 0.0015,
                "rate_limits": {"rpm": 60, "rpd": 1500, "tpm": 32000, "tpd": 0},
                "features": ["function_calling", "streaming"],
                "training_cutoff": "Feb 2023",
                "latency": "medium",
>>>>>>> 22a34e63d08307fef2b1fff6762bfa892f2580ef
            },
        },
    },

    "Azure OpenAI": {
<<<<<<< HEAD
        "imports":  ["openai.AzureOpenAI", "AzureOpenAI", "AsyncAzureOpenAI"],
        "env_keys": ["AZURE_OPENAI_API_KEY", "AZURE_OPENAI_ENDPOINT", "AZURE_OPENAI_DEPLOYMENT"],
        "website":  "https://portal.azure.com",
        "models": {
            "gpt-4o": {
                "full_name": "GPT-4o (Azure)", "type": "Chat / Multimodal",
                "context_window": 128000, "max_output_tokens": 16384,
                "input_cost_per_1k": 0.005, "output_cost_per_1k": 0.015,
                "rate_limits": {"rpm": 600, "rpd": 14400, "tpm": 600000, "tpd": 0},
                "features": ["vision", "function_calling", "json_mode", "streaming"],
                "training_cutoff": "Oct 2023", "latency": "medium",
            },
            "gpt-4": {
                "full_name": "GPT-4 (Azure)", "type": "Chat",
                "context_window": 8192, "max_output_tokens": 8192,
                "input_cost_per_1k": 0.030, "output_cost_per_1k": 0.060,
                "rate_limits": {"rpm": 600, "rpd": 14400, "tpm": 600000, "tpd": 0},
                "features": ["function_calling"],
                "training_cutoff": "Sep 2021", "latency": "slow",
            },
            "gpt-35-turbo": {
                "full_name": "GPT-3.5 Turbo (Azure)", "type": "Chat",
                "context_window": 16385, "max_output_tokens": 4096,
                "input_cost_per_1k": 0.0005, "output_cost_per_1k": 0.0015,
                "rate_limits": {"rpm": 600, "rpd": 14400, "tpm": 600000, "tpd": 0},
                "features": ["function_calling", "streaming"],
                "training_cutoff": "Sep 2021", "latency": "fast",
=======
        "imports": ["openai.AzureOpenAI", "AzureOpenAI", "AsyncAzureOpenAI"],
        "env_keys": ["AZURE_OPENAI_API_KEY", "AZURE_OPENAI_ENDPOINT", "AZURE_OPENAI_DEPLOYMENT"],
        "website": "https://portal.azure.com",
        "models": {
            "gpt-4o": {
                "full_name": "GPT-4o (Azure)",
                "type": "Chat / Multimodal",
                "context_window": 128000,
                "max_output_tokens": 16384,
                "input_cost_per_1k": 0.005,
                "output_cost_per_1k": 0.015,
                "rate_limits": {"rpm": 600, "rpd": 14400, "tpm": 600000, "tpd": 0},
                "features": ["vision", "function_calling", "json_mode", "streaming"],
                "training_cutoff": "Oct 2023",
                "latency": "medium",
            },
            "gpt-4": {
                "full_name": "GPT-4 (Azure)",
                "type": "Chat",
                "context_window": 8192,
                "max_output_tokens": 8192,
                "input_cost_per_1k": 0.030,
                "output_cost_per_1k": 0.060,
                "rate_limits": {"rpm": 600, "rpd": 14400, "tpm": 600000, "tpd": 0},
                "features": ["function_calling"],
                "training_cutoff": "Sep 2021",
                "latency": "slow",
            },
            "gpt-35-turbo": {
                "full_name": "GPT-3.5 Turbo (Azure)",
                "type": "Chat",
                "context_window": 16385,
                "max_output_tokens": 4096,
                "input_cost_per_1k": 0.0005,
                "output_cost_per_1k": 0.0015,
                "rate_limits": {"rpm": 600, "rpd": 14400, "tpm": 600000, "tpd": 0},
                "features": ["function_calling", "streaming"],
                "training_cutoff": "Sep 2021",
                "latency": "fast",
>>>>>>> 22a34e63d08307fef2b1fff6762bfa892f2580ef
            },
        },
    },

    "Hugging Face": {
<<<<<<< HEAD
        "imports":  ["transformers", "huggingface_hub", "HfApi", "AutoModelForCausalLM", "pipeline"],
        "env_keys": ["HF_TOKEN", "HUGGINGFACE_TOKEN", "HF_API_TOKEN"],
        "website":  "https://huggingface.co",
        "models": {
            "meta-llama/Llama-3-70b": {
                "full_name": "Llama 3 70B", "type": "Open Source LLM",
                "context_window": 8192, "max_output_tokens": 8192,
                "input_cost_per_1k": 0.0009, "output_cost_per_1k": 0.0009,
                "rate_limits": {"rpm": 30, "rpd": 1000, "tpm": 500000, "tpd": 0},
                "features": ["streaming", "function_calling"],
                "training_cutoff": "Dec 2023", "latency": "medium",
            },
            "mistralai/Mistral-7B": {
                "full_name": "Mistral 7B", "type": "Open Source LLM",
                "context_window": 32768, "max_output_tokens": 32768,
                "input_cost_per_1k": 0.0002, "output_cost_per_1k": 0.0002,
                "rate_limits": {"rpm": 30, "rpd": 1000, "tpm": 500000, "tpd": 0},
                "features": ["streaming"],
                "training_cutoff": "Sep 2023", "latency": "fast",
=======
        "imports": ["transformers", "huggingface_hub", "HfApi", "AutoModelForCausalLM", "pipeline"],
        "env_keys": ["HF_TOKEN", "HUGGINGFACE_TOKEN", "HF_API_TOKEN"],
        "website": "https://huggingface.co",
        "models": {
            "meta-llama/Llama-3-70b": {
                "full_name": "Llama 3 70B",
                "type": "Open Source LLM",
                "context_window": 8192,
                "max_output_tokens": 8192,
                "input_cost_per_1k": 0.0009,
                "output_cost_per_1k": 0.0009,
                "rate_limits": {"rpm": 30, "rpd": 1000, "tpm": 500000, "tpd": 0},
                "features": ["streaming", "function_calling"],
                "training_cutoff": "Dec 2023",
                "latency": "medium",
            },
            "mistralai/Mistral-7B": {
                "full_name": "Mistral 7B",
                "type": "Open Source LLM",
                "context_window": 32768,
                "max_output_tokens": 32768,
                "input_cost_per_1k": 0.0002,
                "output_cost_per_1k": 0.0002,
                "rate_limits": {"rpm": 30, "rpd": 1000, "tpm": 500000, "tpd": 0},
                "features": ["streaming"],
                "training_cutoff": "Sep 2023",
                "latency": "fast",
>>>>>>> 22a34e63d08307fef2b1fff6762bfa892f2580ef
            },
        },
    },

    "Cohere": {
<<<<<<< HEAD
        "imports":  ["cohere", "Client"],
        "env_keys": ["COHERE_API_KEY", "CO_API_KEY"],
        "website":  "https://dashboard.cohere.com",
        "models": {
            "command-r-plus": {
                "full_name": "Command R+", "type": "Chat / RAG",
                "context_window": 128000, "max_output_tokens": 4096,
                "input_cost_per_1k": 0.003, "output_cost_per_1k": 0.015,
                "rate_limits": {"rpm": 1000, "rpd": 50000, "tpm": 2000000, "tpd": 0},
                "features": ["rag", "tool_use", "streaming", "json_mode"],
                "training_cutoff": "Mar 2024", "latency": "medium",
            },
            "command-r": {
                "full_name": "Command R", "type": "Chat / RAG",
                "context_window": 128000, "max_output_tokens": 4096,
                "input_cost_per_1k": 0.0005, "output_cost_per_1k": 0.0015,
                "rate_limits": {"rpm": 1000, "rpd": 50000, "tpm": 2000000, "tpd": 0},
                "features": ["rag", "tool_use", "streaming"],
                "training_cutoff": "Mar 2024", "latency": "fast",
=======
        "imports": ["cohere", "Client"],
        "env_keys": ["COHERE_API_KEY", "CO_API_KEY"],
        "website": "https://dashboard.cohere.com",
        "models": {
            "command-r-plus": {
                "full_name": "Command R+",
                "type": "Chat / RAG",
                "context_window": 128000,
                "max_output_tokens": 4096,
                "input_cost_per_1k": 0.003,
                "output_cost_per_1k": 0.015,
                "rate_limits": {"rpm": 1000, "rpd": 50000, "tpm": 2000000, "tpd": 0},
                "features": ["rag", "tool_use", "streaming", "json_mode"],
                "training_cutoff": "Mar 2024",
                "latency": "medium",
            },
            "command-r": {
                "full_name": "Command R",
                "type": "Chat / RAG",
                "context_window": 128000,
                "max_output_tokens": 4096,
                "input_cost_per_1k": 0.0005,
                "output_cost_per_1k": 0.0015,
                "rate_limits": {"rpm": 1000, "rpd": 50000, "tpm": 2000000, "tpd": 0},
                "features": ["rag", "tool_use", "streaming"],
                "training_cutoff": "Mar 2024",
                "latency": "fast",
>>>>>>> 22a34e63d08307fef2b1fff6762bfa892f2580ef
            },
        },
    },

    "Groq": {
<<<<<<< HEAD
        "imports":  ["groq", "Groq", "AsyncGroq"],
        "env_keys": ["GROQ_API_KEY"],
        "website":  "https://console.groq.com",
        "models": {
            "llama3-70b-8192": {
                "full_name": "LLaMA3 70B (Groq)", "type": "Chat / Ultra Fast",
                "context_window": 8192, "max_output_tokens": 8192,
                "input_cost_per_1k": 0.00059, "output_cost_per_1k": 0.00079,
                "rate_limits": {"rpm": 30, "rpd": 14400, "tpm": 6000, "tpd": 500000},
                "features": ["streaming", "function_calling"],
                "training_cutoff": "Dec 2023", "latency": "ultra_fast",
            },
            "mixtral-8x7b-32768": {
                "full_name": "Mixtral 8x7B (Groq)", "type": "Chat / MoE",
                "context_window": 32768, "max_output_tokens": 32768,
                "input_cost_per_1k": 0.00027, "output_cost_per_1k": 0.00027,
                "rate_limits": {"rpm": 30, "rpd": 14400, "tpm": 5000, "tpd": 500000},
                "features": ["streaming", "function_calling"],
                "training_cutoff": "Sep 2023", "latency": "ultra_fast",
=======
        "imports": ["groq", "Groq", "AsyncGroq"],
        "env_keys": ["GROQ_API_KEY"],
        "website": "https://console.groq.com",
        "models": {
            "llama3-70b-8192": {
                "full_name": "LLaMA3 70B (Groq)",
                "type": "Chat / Ultra Fast",
                "context_window": 8192,
                "max_output_tokens": 8192,
                "input_cost_per_1k": 0.00059,
                "output_cost_per_1k": 0.00079,
                "rate_limits": {"rpm": 30, "rpd": 14400, "tpm": 6000, "tpd": 500000},
                "features": ["streaming", "function_calling"],
                "training_cutoff": "Dec 2023",
                "latency": "ultra_fast",
            },
            "mixtral-8x7b-32768": {
                "full_name": "Mixtral 8x7B (Groq)",
                "type": "Chat / MoE",
                "context_window": 32768,
                "max_output_tokens": 32768,
                "input_cost_per_1k": 0.00027,
                "output_cost_per_1k": 0.00027,
                "rate_limits": {"rpm": 30, "rpd": 14400, "tpm": 5000, "tpd": 500000},
                "features": ["streaming", "function_calling"],
                "training_cutoff": "Sep 2023",
                "latency": "ultra_fast",
>>>>>>> 22a34e63d08307fef2b1fff6762bfa892f2580ef
            },
        },
    },

    "LangChain": {
<<<<<<< HEAD
        "imports":  ["langchain", "langchain_openai", "langchain_anthropic",
                     "langchain_google_genai", "langchain_community", "langchain_core"],
        "env_keys": ["LANGCHAIN_API_KEY", "LANGCHAIN_TRACING_V2", "LANGCHAIN_PROJECT"],
        "website":  "https://smith.langchain.com",
        "models":   {},
    },

    "CrewAI": {
        "imports":  ["crewai", "Crew", "Agent", "Task"],
        "env_keys": ["CREWAI_API_KEY"],
        "website":  "https://crewai.com",
        "models":   {},
    },

    "AutoGen": {
        "imports":  ["autogen", "pyautogen", "AssistantAgent", "UserProxyAgent"],
        "env_keys": ["AUTOGEN_USE_DOCKER"],
        "website":  "https://microsoft.github.io/autogen",
        "models":   {},
    },
}


AI_AGENT_CHARACTERISTICS = [
    {"trait": "Autonomy",                  "icon": "🤖", "desc": "Operates independently without constant human intervention"},
    {"trait": "Perception",                "icon": "👁️", "desc": "Senses environment through APIs, data feeds, or sensors"},
    {"trait": "Reasoning",                 "icon": "🧠", "desc": "Processes information and makes decisions using LLM or logic"},
    {"trait": "Action",                    "icon": "⚡", "desc": "Executes tasks — API calls, code generation, deployments"},
    {"trait": "Memory",                    "icon": "💾", "desc": "Retains context across interactions (short/long-term)"},
    {"trait": "Tool Use",                  "icon": "🔧", "desc": "Invokes external tools, functions, or plugins"},
    {"trait": "Planning",                  "icon": "📋", "desc": "Breaks complex goals into ordered sub-tasks"},
    {"trait": "Reactivity",                "icon": "🔄", "desc": "Responds dynamically to changes in environment"},
    {"trait": "Communication",             "icon": "💬", "desc": "Interacts with humans or other agents via messages"},
    {"trait": "Goal-Oriented",             "icon": "🎯", "desc": "Driven by explicit objectives or reward signals"},
    {"trait": "Learning",                  "icon": "📈", "desc": "Improves behaviour over time from feedback or data"},
    {"trait": "Multi-Agent Collaboration", "icon": "🤝", "desc": "Coordinates with other agents to solve tasks"},
]


# ══════════════════════════════════════════════════════════════════════════════
# AI AGENT SCANNER
# ══════════════════════════════════════════════════════════════════════════════

=======
        "imports": ["langchain", "langchain_openai", "langchain_anthropic",
                    "langchain_google_genai", "langchain_community", "langchain_core"],
        "env_keys": ["LANGCHAIN_API_KEY", "LANGCHAIN_TRACING_V2", "LANGCHAIN_PROJECT"],
        "website": "https://smith.langchain.com",
        "models": {},
    },

    "CrewAI": {
        "imports": ["crewai", "Crew", "Agent", "Task"],
        "env_keys": ["CREWAI_API_KEY"],
        "website": "https://crewai.com",
        "models": {},
    },

    "AutoGen": {
        "imports": ["autogen", "pyautogen", "AssistantAgent", "UserProxyAgent"],
        "env_keys": ["AUTOGEN_USE_DOCKER"],
        "website": "https://microsoft.github.io/autogen",
        "models": {},
    },
}

AI_AGENT_CHARACTERISTICS = [
    {"trait": "Autonomy", "icon": "🤖", "desc": "Operates independently without constant human intervention"},
    {"trait": "Perception", "icon": "👁️", "desc": "Senses environment through APIs, data feeds, or sensors"},
    {"trait": "Reasoning", "icon": "🧠", "desc": "Processes information and makes decisions using LLM or logic"},
    {"trait": "Action", "icon": "⚡", "desc": "Executes tasks — API calls, code generation, deployments"},
    {"trait": "Memory", "icon": "💾", "desc": "Retains context across interactions (short/long-term)"},
    {"trait": "Tool Use", "icon": "🔧", "desc": "Invokes external tools, functions, or plugins"},
    {"trait": "Planning", "icon": "📋", "desc": "Breaks complex goals into ordered sub-tasks"},
    {"trait": "Reactivity", "icon": "🔄", "desc": "Responds dynamically to changes in environment"},
    {"trait": "Communication", "icon": "💬", "desc": "Interacts with humans or other agents via messages"},
    {"trait": "Goal-Oriented", "icon": "🎯", "desc": "Driven by explicit objectives or reward signals"},
    {"trait": "Learning", "icon": "📈", "desc": "Improves behaviour over time from feedback or data"},
    {"trait": "Multi-Agent Collaboration", "icon": "🤝", "desc": "Coordinates with other agents to solve tasks"},
]

>>>>>>> 22a34e63d08307fef2b1fff6762bfa892f2580ef
def _scan_python_file(filepath):
    results = {
        "providers_found":   [],
        "models_found":      [],
        "imports_found":     [],
        "env_vars_used":     [],
        "token_configs":     [],
        "agent_patterns":    [],
        "raw_model_strings": [],
    }

    try:
        with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
            content = f.read()
    except Exception:
        return results

<<<<<<< HEAD
    # ── Extract imports ────────────────────────────────────────────────────
=======
    # ── Imports ────────────────────────────────────────────────────────────
>>>>>>> 22a34e63d08307fef2b1fff6762bfa892f2580ef
    try:
        tree = ast.parse(content)
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    results["imports_found"].append(alias.name)
            elif isinstance(node, ast.ImportFrom) and node.module:
                results["imports_found"].append(node.module)
                for alias in node.names:
<<<<<<< HEAD
                    results["imports_found"].append(f"{node.module}.{alias.name}")
=======
                    results["imports_found"].append(
                        f"{node.module}.{alias.name}"
                    )
>>>>>>> 22a34e63d08307fef2b1fff6762bfa892f2580ef
    except SyntaxError:
        for groups in re.findall(
            r'^\s*(?:from\s+([\w.]+)\s+import|import\s+([\w.]+))',
            content, re.MULTILINE,
        ):
            for g in groups:
                if g:
                    results["imports_found"].append(g)

<<<<<<< HEAD
    # ── Extract configured params from code ───────────────────────────────
=======
    # ── Configured params ──────────────────────────────────────────────────
>>>>>>> 22a34e63d08307fef2b1fff6762bfa892f2580ef
    configured = {}
    for key, pattern in [
        ("max_tokens",        r'max_tokens\s*[=:]\s*(\d+)'),
        ("temperature",       r'temperature\s*[=:]\s*([\d.]+)'),
        ("top_p",             r'top_p\s*[=:]\s*([\d.]+)'),
        ("timeout",           r'timeout\s*[=:]\s*(\d+)'),
        ("max_retries",       r'max_retries\s*[=:]\s*(\d+)'),
        ("frequency_penalty", r'frequency_penalty\s*[=:]\s*([\d.]+)'),
        ("presence_penalty",  r'presence_penalty\s*[=:]\s*([\d.]+)'),
    ]:
        m = re.findall(pattern, content)
        if m:
            configured[key] = (
<<<<<<< HEAD
                int(m[0]) if key in ("max_tokens", "timeout", "max_retries")
                else float(m[0])
            )

    # ── Extract raw model= strings ────────────────────────────────────────
    raw_models = re.findall(r'model\s*[=:]\s*["\']([^"\']+)["\']', content)
    results["raw_model_strings"] = list(set(raw_models))

    # ── Match providers then models ───────────────────────────────────────
=======
                int(m[0])
                if key in ("max_tokens", "timeout", "max_retries")
                else float(m[0])
            )

    # ── Raw model strings ──────────────────────────────────────────────────
    raw_models = re.findall(r'model\s*[=:]\s*["\']([^"\']+)["\']', content)
    results["raw_model_strings"] = list(set(raw_models))

    # ── Match providers then models ────────────────────────────────────────
>>>>>>> 22a34e63d08307fef2b1fff6762bfa892f2580ef
    for provider_name, provider_info in AI_PROVIDER_FULL_METRICS.items():

        provider_matched = any(
            imp in found
            for imp in provider_info["imports"]
            for found in results["imports_found"]
        )
        for ek in provider_info["env_keys"]:
            if ek in content:
                results["env_vars_used"].append(ek)
                provider_matched = True

        if not provider_matched:
            continue

        results["providers_found"].append(provider_name)

        for model_key, model_metrics in provider_info.get("models", {}).items():
<<<<<<< HEAD
=======

>>>>>>> 22a34e63d08307fef2b1fff6762bfa892f2580ef
            model_hit = (
                model_key in content
                or any(model_key in rm for rm in results["raw_model_strings"])
                or any(rm in model_key for rm in results["raw_model_strings"])
            )
            if not model_hit:
                continue

            rl       = model_metrics["rate_limits"]
            in_cost  = model_metrics["input_cost_per_1k"]
            out_cost = model_metrics["output_cost_per_1k"]
<<<<<<< HEAD
            max_tok  = configured.get("max_tokens", model_metrics["max_output_tokens"])
            est_hourly = (
                rl.get("rpm", 0) * 60
                * (model_metrics["context_window"] / 1000 * in_cost
                   + max_tok / 1000 * out_cost)
=======
            max_tok  = configured.get(
                "max_tokens", model_metrics["max_output_tokens"]
            )
            est_hourly = (
                rl.get("rpm", 0) * 60
                * (
                    model_metrics["context_window"] / 1000 * in_cost
                    + max_tok / 1000 * out_cost
                )
>>>>>>> 22a34e63d08307fef2b1fff6762bfa892f2580ef
            )

            results["models_found"].append({
                # Identity
                "provider":        provider_name,
                "model":           model_key,
                "full_name":       model_metrics["full_name"],
                "model_type":      model_metrics["type"],
                "website":         provider_info["website"],
                "training_cutoff": model_metrics["training_cutoff"],
                "latency_class":   model_metrics["latency"],
                "features":        model_metrics["features"],
                # Token limits
                "token_limits": {
<<<<<<< HEAD
                    "context_window":        model_metrics["context_window"],
                    "max_output_tokens":     model_metrics["max_output_tokens"],
                    "configured_max_tokens": configured.get("max_tokens", "Default"),
                    "temperature":           configured.get("temperature", "Default"),
                    "top_p":                 configured.get("top_p", "Default"),
                    "frequency_penalty":     configured.get("frequency_penalty", "Default"),
                    "presence_penalty":      configured.get("presence_penalty", "Default"),
=======
                    "context_window":      model_metrics["context_window"],
                    "max_output_tokens":   model_metrics["max_output_tokens"],
                    "configured_max_tokens": configured.get("max_tokens", "Default"),
                    "temperature":         configured.get("temperature", "Default"),
                    "top_p":               configured.get("top_p", "Default"),
                    "frequency_penalty":   configured.get("frequency_penalty", "Default"),
                    "presence_penalty":    configured.get("presence_penalty", "Default"),
>>>>>>> 22a34e63d08307fef2b1fff6762bfa892f2580ef
                },
                # Rate limits
                "rate_limits": {
                    "requests_per_minute": rl.get("rpm", "Unknown"),
                    "requests_per_day":    rl.get("rpd", "Unknown"),
                    "tokens_per_minute":   rl.get("tpm", "Unknown"),
                    "tokens_per_day":      rl.get("tpd", "Unknown"),
                    "est_per_hour":        rl.get("rpm", 0) * 60,
                },
                # Costs
                "costs": {
                    "input_per_1k":   f"${in_cost:.6f}",
                    "output_per_1k":  f"${out_cost:.6f}",
                    "per_1m_input":   f"${in_cost  * 1000:.4f}",
                    "per_1m_output":  f"${out_cost * 1000:.4f}",
                    "est_max_hourly": f"${est_hourly:.4f}",
                },
<<<<<<< HEAD
                # Found in code
                "found_in_code": {
                    "raw_model_strings": results["raw_model_strings"],
                    "env_vars_used":     [ek for ek in provider_info["env_keys"] if ek in content],
=======
                # What was found in code
                "found_in_code": {
                    "raw_model_strings": results["raw_model_strings"],
                    "env_vars_used": [
                        ek for ek in provider_info["env_keys"]
                        if ek in content
                    ],
>>>>>>> 22a34e63d08307fef2b1fff6762bfa892f2580ef
                    "configured_params": configured,
                },
            })

        # backward-compat token_configs
        for tm in re.findall(r'max_tokens\s*[=:]\s*(\d+)', content):
<<<<<<< HEAD
            results["token_configs"].append({"provider": provider_name, "max_tokens_configured": int(tm)})
        for t in re.findall(r'temperature\s*[=:]\s*([\d.]+)', content):
            results["token_configs"].append({"provider": provider_name, "temperature": float(t)})
=======
            results["token_configs"].append(
                {"provider": provider_name, "max_tokens_configured": int(tm)}
            )
        for t in re.findall(r'temperature\s*[=:]\s*([\d.]+)', content):
            results["token_configs"].append(
                {"provider": provider_name, "temperature": float(t)}
            )
>>>>>>> 22a34e63d08307fef2b1fff6762bfa892f2580ef

    # ── Agent patterns ─────────────────────────────────────────────────────
    for pattern, label in [
        (r'class\s+(\w*[Aa]gent\w*)\s*[\(:]',            "Class-based Agent"),
        (r'Agent\s*\(',                                    "Agent instantiation"),
        (r'CrewAI|Crew\s*\(',                             "CrewAI Agent"),
        (r'AssistantAgent|UserProxyAgent',                 "AutoGen Agent"),
        (r'AgentExecutor',                                 "LangChain Agent"),
        (r'create_react_agent|create_openai_tools_agent',  "LangChain ReAct Agent"),
        (r'tool\s*=|tools\s*=\s*\[',                      "Tool-using Agent"),
        (r'memory\s*=|Memory\s*\(',                        "Memory-enabled Agent"),
        (r'vector_store|VectorStore|Chroma|Pinecone|FAISS',"RAG Agent"),
    ]:
        if re.search(pattern, content):
            results["agent_patterns"].append(label)

    return results

<<<<<<< HEAD

=======
>>>>>>> 22a34e63d08307fef2b1fff6762bfa892f2580ef
def _infer_purpose(filepath, model_dict, scan_result):
    fp       = filepath.lower()
    patterns = scan_result.get("agent_patterns", [])
    mtype    = model_dict.get("model_type", "").lower()

<<<<<<< HEAD
    if "monitor"   in fp:                              return "Monitoring, health-check analysis, or alerting"
    if "chat"      in fp:                              return "Conversational AI / chatbot functionality"
    if "agent"     in fp:                              return "Autonomous AI agent task execution"
    if "embed"     in mtype:                           return "Text embedding for semantic search or RAG"
    if "rag"       in " ".join(patterns).lower():      return "Retrieval-Augmented Generation (RAG)"
    if "tool"      in " ".join(patterns).lower():      return "Tool-augmented reasoning and function calling"
    if any(p in patterns for p in ["CrewAI Agent", "AutoGen Agent"]):
                                                       return "Multi-agent collaboration and task orchestration"
    if "reasoning" in mtype:                           return "Complex multi-step reasoning"
    return "AI-powered text generation and analysis"


FILE_PURPOSES = {
    "app.py":              "Flask application entry point — defines routes and WSGI startup",
    "application.py":      "Alternative Flask/Django entry point",
    "agent_monitor.py":    "AI Agent & Pipeline monitoring module (this file)",
    "manage.py":           "Django management commands entry point",
    "wsgi.py":             "WSGI configuration for production servers",
    "settings.py":         "Application configuration and settings",
    "config.py":           "Application configuration module",
    "models.py":           "Database models / ORM definitions",
    "views.py":            "View functions / route handlers",
    "urls.py":             "URL routing configuration",
    "tasks.py":            "Background task definitions (Celery/RQ)",
    "utils.py":            "Utility functions and helpers",
    "requirements.txt":    "Python package dependencies",
    "Dockerfile":          "Docker container build instructions",
    "docker-compose.yml":  "Multi-container Docker orchestration",
    "Makefile":            "Build automation commands",
    "Procfile":            "Process declarations for Heroku/PaaS",
    ".env":                "Environment variables (secrets, config)",
    "README.md":           "Project documentation and overview",
    "Jenkinsfile":         "Jenkins pipeline definition",
    "azure-pipelines.yml": "Azure DevOps pipeline config",
    ".gitlab-ci.yml":      "GitLab CI pipeline config",
    ".travis.yml":         "Travis CI pipeline config",
    "buildspec.yml":       "AWS CodeBuild build specification",
}

=======
    if "monitor"   in fp: return "Monitoring, health-check analysis, or alerting"
    if "chat"      in fp: return "Conversational AI / chatbot functionality"
    if "agent"     in fp: return "Autonomous AI agent task execution"
    if "embed"     in mtype: return "Text embedding for semantic search or RAG"
    if "rag"       in " ".join(patterns).lower(): return "Retrieval-Augmented Generation (RAG)"
    if "tool"      in " ".join(patterns).lower(): return "Tool-augmented reasoning and function calling"
    if any(p in patterns for p in ["CrewAI Agent", "AutoGen Agent"]):
        return "Multi-agent collaboration and task orchestration"
    if "reasoning" in mtype: return "Complex multi-step reasoning"
    return "AI-powered text generation and analysis"

FILE_PURPOSES = {
    "app.py": "Flask application entry point — defines routes and WSGI startup",
    "application.py": "Alternative Flask/Django entry point",
    "agent_monitor.py": "AI Agent & Pipeline monitoring module (this file)",
    "manage.py": "Django management commands entry point",
    "wsgi.py": "WSGI configuration for production servers",
    "settings.py": "Application configuration and settings",
    "config.py": "Application configuration module",
    "models.py": "Database models / ORM definitions",
    "views.py": "View functions / route handlers",
    "urls.py": "URL routing configuration",
    "tasks.py": "Background task definitions (Celery/RQ)",
    "utils.py": "Utility functions and helpers",
    "requirements.txt": "Python package dependencies",
    "Dockerfile": "Docker container build instructions",
    "docker-compose.yml": "Multi-container Docker orchestration",
    "Makefile": "Build automation commands",
    "Procfile": "Process declarations for Heroku/PaaS",
    ".env": "Environment variables (secrets, config)",
    "README.md": "Project documentation and overview",
    "Jenkinsfile": "Jenkins pipeline definition",
    "azure-pipelines.yml": "Azure DevOps pipeline config",
    ".gitlab-ci.yml": "GitLab CI pipeline config",
    ".travis.yml": "Travis CI pipeline config",
    "buildspec.yml": "AWS CodeBuild build specification",
}

# ── DELETE old scan_project() and REPLACE ────────────────────────────────────
>>>>>>> 22a34e63d08307fef2b1fff6762bfa892f2580ef

def scan_project():
    scan_time = datetime.datetime.now(datetime.timezone.utc).isoformat()
    skip_dirs = {
        ".git", "__pycache__", "node_modules", ".venv", "venv", "env",
        ".tox", ".mypy_cache", ".pytest_cache", "dist", "build", ".eggs",
    }

    file_tree = []
    py_files  = []

    for root, dirs, files in os.walk(BASE_DIR):
<<<<<<< HEAD
        dirs[:] = [d for d in dirs if d not in skip_dirs and not d.endswith(".egg-info")]
        rel_root = Path(root).relative_to(BASE_DIR)
        for fname in sorted(files):
            rel_path = str(rel_root / fname) if str(rel_root) != "." else fname
            ext      = Path(fname).suffix.lower()
            purpose  = FILE_PURPOSES.get(fname, "")
            if not purpose:
                purpose = {
                    ".py":   "Python module",           ".html": "HTML template",
                    ".css":  "Stylesheet",              ".js":   "JavaScript module",
                    ".yml":  "YAML configuration",      ".yaml": "YAML configuration",
                    ".json": "JSON data / configuration",".md":  "Markdown documentation",
                    ".txt":  "Text file",               ".sh":   "Shell script",
                    ".sql":  "SQL database script",     ".toml": "TOML configuration",
                }.get(ext, "Project file")

            is_main = fname in ("app.py", "application.py", "manage.py",
                                "wsgi.py", "agent_monitor.py", "main.py")
            file_tree.append({
                "path":      rel_path,
                "name":      fname,
                "purpose":   purpose,
                "is_main":   is_main,
                "extension": ext,
                "size":      os.path.getsize(os.path.join(root, fname)),
=======
        dirs[:] = [
            d for d in dirs
            if d not in skip_dirs and not d.endswith(".egg-info")
        ]
        rel_root = Path(root).relative_to(BASE_DIR)
        for fname in sorted(files):
            rel_path = (
                str(rel_root / fname) if str(rel_root) != "." else fname
            )
            ext     = Path(fname).suffix.lower()
            purpose = FILE_PURPOSES.get(fname, "")
            if not purpose:
                purpose = {
                    ".py": "Python module", ".html": "HTML template",
                    ".css": "Stylesheet",   ".js":   "JavaScript module",
                    ".yml": "YAML configuration", ".yaml": "YAML configuration",
                    ".json": "JSON data / configuration",
                    ".md":  "Markdown documentation",
                    ".txt": "Text file",   ".sh":   "Shell script",
                    ".sql": "SQL database script",
                    ".toml":"TOML configuration",
                }.get(ext, "Project file")

            is_main = fname in (
                "app.py", "application.py", "manage.py",
                "wsgi.py", "agent_monitor.py", "main.py",
            )
            file_tree.append({
                "path": rel_path, "name": fname, "purpose": purpose,
                "is_main": is_main, "extension": ext,
                "size": os.path.getsize(os.path.join(root, fname)),
>>>>>>> 22a34e63d08307fef2b1fff6762bfa892f2580ef
            })
            if ext == ".py":
                py_files.append(os.path.join(root, fname))

    file_tree.sort(key=lambda x: (not x["is_main"], x["path"]))

    agents        = []
    all_providers = set()
    all_models    = []

    for pyf in py_files:
        scan_result = _scan_python_file(pyf)

        if not scan_result["providers_found"] and not scan_result["agent_patterns"]:
            continue

        rel = str(Path(pyf).relative_to(BASE_DIR))

<<<<<<< HEAD
=======
        # Build model_details with full metrics + purpose
>>>>>>> 22a34e63d08307fef2b1fff6762bfa892f2580ef
        model_details = []
        for m in scan_result["models_found"]:
            model_details.append({
                **m,
                "why_used":   _infer_purpose(rel, m, scan_result),
                "where_used": rel,
            })

        agents.append({
            "script":            rel,
            "providers":         list(set(scan_result["providers_found"])),
            "models":            scan_result["models_found"],
            "patterns":          list(set(scan_result["agent_patterns"])),
            "env_vars":          list(set(scan_result["env_vars_used"])),
            "token_configs":     scan_result["token_configs"],
            "model_details":     model_details,
            "raw_model_strings": scan_result["raw_model_strings"],
        })

        all_providers.update(scan_result["providers_found"])
        all_models.extend(scan_result["models_found"])

    pipelines = detect_pipelines()

    active_env = {}
    for prov_info in AI_PROVIDER_FULL_METRICS.values():
        for ek in prov_info["env_keys"]:
            val = os.environ.get(ek)
            if val:
<<<<<<< HEAD
                masked = val[:4] + "****" + val[-4:] if len(val) > 8 else "****"
                active_env[ek] = masked

    return {
        "scan_time":               scan_time,
        "project_root":            str(BASE_DIR),
        "pipelines":               pipelines,
        "ai_agent_characteristics": AI_AGENT_CHARACTERISTICS,
        "file_tree":               file_tree,
        "agents":                  agents,
=======
                masked = (
                    val[:4] + "****" + val[-4:]
                    if len(val) > 8 else "****"
                )
                active_env[ek] = masked

    return {
        "scan_time":    scan_time,
        "project_root": str(BASE_DIR),
        "pipelines":    pipelines,
        "ai_agent_characteristics": AI_AGENT_CHARACTERISTICS,
        "file_tree":    file_tree,
        "agents":       agents,
>>>>>>> 22a34e63d08307fef2b1fff6762bfa892f2580ef
        "summary": {
            "total_files":        len(file_tree),
            "python_files":       len(py_files),
            "ai_agents_found":    len(agents),
            "providers":          list(all_providers),
            "models_used":        len(all_models),
            "pipelines_detected": len(pipelines),
        },
        "active_env_keys": active_env,
    }

<<<<<<< HEAD

# ══════════════════════════════════════════════════════════════════════════════
# ROUTE: /monitor/status
# ══════════════════════════════════════════════════════════════════════════════

def handle_monitor_status():
    now = datetime.datetime.now(datetime.timezone.utc).isoformat()

    if request.method == "POST":
        data        = request.get_json(silent=True) or {}
=======
# ══════════════════════════════════════════════════════════════════════════════
# ROUTE: /monitor/status  (GET + POST)
# ══════════════════════════════════════════════════════════════════════════════

def handle_monitor_status():
    """Handle both GET and POST for /monitor/status."""
    now = datetime.datetime.now(datetime.timezone.utc).isoformat()

    if request.method == "POST":
        data = request.get_json(silent=True) or {}
>>>>>>> 22a34e63d08307fef2b1fff6762bfa892f2580ef
        result_json = json.dumps({"status": "ok", "received": data, "timestamp": now}, indent=2)
        body = f"""
        <div class="section">
          <div class="section-title">📡 Webhook Status — POST Received</div>
          <div class="card status-card">
            <div class="status-icon">✅</div>
            <div class="status-ok">POST Received Successfully</div>
            <p style="color:var(--text-secondary);margin-top:8px">Payload processed at {now}</p>
          </div>
          <div class="card">
            <h3 style="margin-bottom:12px;color:var(--accent2)">📦 Response</h3>
            <div class="json-box">{_colorize_json(result_json)}</div>
          </div>
        </div>
        <div class="section">
          <div class="section-title">🧪 Send Another Webhook</div>
          {_webhook_form()}
        </div>"""
        return wrap_page("Webhook Status", body, active="status")

<<<<<<< HEAD
=======
    # GET request
>>>>>>> 22a34e63d08307fef2b1fff6762bfa892f2580ef
    body = f"""
    <div class="section">
      <div class="section-title">📡 Webhook Status Endpoint</div>
      <div class="card status-card">
        <div class="status-icon">📡</div>
        <p style="font-size:1.2rem;font-weight:700;color:var(--accent)">Monitor Webhook Ready</p>
        <p style="color:var(--text-secondary);margin-top:8px">
<<<<<<< HEAD
          Accepts <strong>GET</strong> (this page) and <strong>POST</strong> (webhook data).
=======
          This endpoint accepts both <strong>GET</strong> (this page) and <strong>POST</strong> (webhook data).
>>>>>>> 22a34e63d08307fef2b1fff6762bfa892f2580ef
        </p>
        <p style="color:var(--text-secondary);margin-top:4px">Current time: {now}</p>
      </div>
    </div>
    <div class="section">
      <div class="section-title">🧪 Test Webhook (Send POST)</div>
      {_webhook_form()}
    </div>
    <div class="section">
      <div class="section-title">📋 cURL Example</div>
      <div class="card">
<<<<<<< HEAD
        <div class="json-box">curl -X POST {request.url} \\
=======
        <div class="json-box">curl -X POST {request.url}  \\
>>>>>>> 22a34e63d08307fef2b1fff6762bfa892f2580ef
  -H "Content-Type: application/json" \\
  -d '{{"pipeline":"ci-build","status":"success","build":"42"}}'</div>
      </div>
    </div>"""
    return wrap_page("Webhook Status", body, active="status")


def _webhook_form():
    return """
    <div class="card">
      <div class="webhook-form">
<<<<<<< HEAD
        <label style="font-weight:600;color:var(--accent2);display:block;margin-bottom:8px">📝 JSON Payload:</label>
=======
        <label style="font-weight:600;color:var(--accent2);display:block;margin-bottom:8px">
          📝 JSON Payload:
        </label>
>>>>>>> 22a34e63d08307fef2b1fff6762bfa892f2580ef
        <textarea id="webhookPayload">{
  "pipeline": "my-ci-pipeline",
  "status": "success",
  "build_number": "42",
  "branch": "main"
}</textarea>
        <button onclick="sendWebhook()">🚀 Send POST Request</button>
        <div id="webhookResult"></div>
      </div>
    </div>
    <script>
    async function sendWebhook(){
<<<<<<< HEAD
      const payload   = document.getElementById('webhookPayload').value;
=======
      const payload = document.getElementById('webhookPayload').value;
>>>>>>> 22a34e63d08307fef2b1fff6762bfa892f2580ef
      const resultDiv = document.getElementById('webhookResult');
      resultDiv.innerHTML = '<p style="color:var(--accent)">⏳ Sending...</p>';
      try{
        let parsed = JSON.parse(payload);
<<<<<<< HEAD
        const r = await fetch('/monitor/status',{
          method:'POST',headers:{'Content-Type':'application/json'},
          body:JSON.stringify(parsed)
        });
        const text = await r.text();
        resultDiv.innerHTML='<div class="card" style="margin-top:12px;border-left:4px solid #28a745"><h4 style="color:#28a745;margin-bottom:8px">✅ Response (Status '+r.status+')</h4><div class="json-box">'+text+'</div></div>';
      }catch(e){
        resultDiv.innerHTML='<div class="card" style="margin-top:12px;border-left:4px solid #dc3545"><h4 style="color:#dc3545">❌ Error</h4><p>'+e.message+'</p></div>';
=======
        const r = await fetch('/monitor/status', {
          method: 'POST',
          headers: {'Content-Type': 'application/json'},
          body: JSON.stringify(parsed)
        });
        const text = await r.text();
        resultDiv.innerHTML = '<div class="card" style="margin-top:12px;border-left:4px solid #28a745"><h4 style="color:#28a745;margin-bottom:8px">✅ Response (Status ' + r.status + ')</h4><div class="json-box">' + text + '</div></div>';
      }catch(e){
        resultDiv.innerHTML = '<div class="card" style="margin-top:12px;border-left:4px solid #dc3545"><h4 style="color:#dc3545">❌ Error</h4><p>' + e.message + '</p></div>';
>>>>>>> 22a34e63d08307fef2b1fff6762bfa892f2580ef
      }
    }
    </script>"""


def _colorize_json(json_str):
<<<<<<< HEAD
    s = json_str.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    s = re.sub(r'"([^"]+)"(\s*:)', r'<span class="json-key">"\1"</span>\2', s)
    s = re.sub(r':\s*"([^"]*)"',   r': <span class="json-str">"\1"</span>', s)
    s = re.sub(r':\s*(\d+\.?\d*)', r': <span class="json-num">\1</span>', s)
    s = re.sub(r':\s*(true|false)', r': <span class="json-bool">\1</span>', s)
    s = re.sub(r':\s*(null)',        r': <span class="json-null">\1</span>', s)
    return s


# ══════════════════════════════════════════════════════════════════════════════
# HELPERS
# ══════════════════════════════════════════════════════════════════════════════

def _stat_card(icon, value, label):
    return (f'<div class="stat-card"><div class="stat-icon">{icon}</div>'
            f'<div class="stat-value">{value}</div>'
            f'<div class="stat-label">{label}</div></div>')


def _fmt(val):
    if val is None or val in ("Unknown", "Default"):
        return val or "—"
    if isinstance(val, float):
        return f"{val:,.0f}"
    if isinstance(val, int):
        return f"{val:,}"
    return str(val)


def _render_model_details(model_details):
    """Full metrics card for every detected model — used by scanner_scan and monitor_dashboard."""
    if not model_details:
        return """
        <div style="background:#fff8e1;border:1px solid #ffe082;border-radius:8px;padding:14px;margin-top:10px">
=======
    """Simple JSON syntax highlighting for HTML."""
    s = json_str.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    s = re.sub(r'"([^"]+)"(\s*:)', r'<span class="json-key">"\1"</span>\2', s)
    s = re.sub(r':\s*"([^"]*)"', r': <span class="json-str">"\1"</span>', s)
    s = re.sub(r':\s*(\d+\.?\d*)', r': <span class="json-num">\1</span>', s)
    s = re.sub(r':\s*(true|false)', r': <span class="json-bool">\1</span>', s)
    s = re.sub(r':\s*(null)', r': <span class="json-null">\1</span>', s)
    return s

# ── ADD this new function (place it near the other helpers like _stat_card) ───

def _render_model_details(model_details):
    """Full metrics card for every detected model — used by both routes."""
    if not model_details:
        return """
        <div style="background:#fff8e1;border:1px solid #ffe082;
                    border-radius:8px;padding:14px;margin-top:10px">
>>>>>>> 22a34e63d08307fef2b1fff6762bfa892f2580ef
          <strong>⚠️ Provider detected but no specific model string matched.</strong><br>
          <span style="font-size:.83rem;color:var(--text-secondary)">
            Model may be set via environment variable or config file.
          </span>
        </div>"""

    html = ""
    for md in model_details:
<<<<<<< HEAD
        tl   = md.get("token_limits",  {})
        rl   = md.get("rate_limits",   {})
        cost = md.get("costs",         {})
=======
        tl   = md.get("token_limits", {})
        rl   = md.get("rate_limits",  {})
        cost = md.get("costs",        {})
>>>>>>> 22a34e63d08307fef2b1fff6762bfa892f2580ef
        fic  = md.get("found_in_code", {})
        cfg  = fic.get("configured_params", {})

        latency_color = {
            "ultra_fast": "#28a745", "very_fast": "#5cb85c",
            "fast":       "#2d8a4e", "medium":    "#f0ad4e",
            "slow":       "#d9534f", "very_slow": "#c9302c",
        }.get(md.get("latency_class", ""), "#6c757d")

<<<<<<< HEAD
        features_html = "".join(
            f'<span class="tag model">✅ {f}</span>'
            for f in md.get("features", [])
        )

        env_tags = "".join(
            f'<span class="tag env">🔐 {e}</span>'
            for e in fic.get("env_vars_used", [])
        ) or '<span style="font-size:.78rem;color:var(--text-secondary)">None found</span>'

        ctx = tl.get("context_window", 0) or 0
        rpm = rl.get("requests_per_minute", 0) or 0
=======
        features_html = "".join([
            f'<span class="tag model">✅ {f}</span>'
            for f in md.get("features", [])
        ])

        env_tags = "".join([
            f'<span class="tag env">🔐 {e}</span>'
            for e in fic.get("env_vars_used", [])
        ]) or '<span style="font-size:.78rem;color:var(--text-secondary)">None found</span>'
>>>>>>> 22a34e63d08307fef2b1fff6762bfa892f2580ef

        html += f"""
        <div class="model-detail" style="margin-bottom:16px">

          <!-- Model header -->
<<<<<<< HEAD
          <div style="display:flex;justify-content:space-between;align-items:center;
                      flex-wrap:wrap;gap:8px;margin-bottom:14px;padding-bottom:12px;
=======
          <div style="display:flex;justify-content:space-between;
                      align-items:center;flex-wrap:wrap;gap:8px;
                      margin-bottom:14px;padding-bottom:12px;
>>>>>>> 22a34e63d08307fef2b1fff6762bfa892f2580ef
                      border-bottom:1px solid var(--border)">
            <div>
              <span style="font-size:1.05rem;font-weight:800;color:var(--accent2)">
                🧠 {md.get('full_name', md.get('model','Unknown'))}
              </span>
              <span style="font-size:.8rem;color:var(--text-secondary);margin-left:8px">
                ({md.get('provider','')})
              </span>
            </div>
            <div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap">
              <span style="background:{latency_color};color:#fff;padding:3px 12px;
                           border-radius:12px;font-size:.75rem;font-weight:700">
                ⚡ {md.get('latency_class','').replace('_',' ').title()}
              </span>
              <span class="tag provider">📂 {md.get('model_type','')}</span>
              <a href="{md.get('website','#')}" target="_blank"
                 style="font-size:.75rem;color:var(--accent);text-decoration:none">
                🌐 Docs ↗
              </a>
            </div>
          </div>

          <!-- Purpose bar -->
<<<<<<< HEAD
          <div style="margin-bottom:12px;padding:8px 12px;background:var(--accent-light);
                      border-radius:8px;font-size:.85rem;color:var(--accent2)">
=======
          <div style="margin-bottom:12px;padding:8px 12px;
                      background:var(--accent-light);border-radius:8px;font-size:.85rem">
>>>>>>> 22a34e63d08307fef2b1fff6762bfa892f2580ef
            🎯 <strong>Purpose:</strong> {md.get('why_used','AI-powered text generation')}
            &nbsp;|&nbsp; 📄 <strong>File:</strong> {md.get('where_used','')}
            &nbsp;|&nbsp; 🗓️ <strong>Cutoff:</strong> {md.get('training_cutoff','')}
          </div>

          <div class="detail-grid">

            <!-- TOKEN LIMITS -->
            <div class="detail-box">
              <h5>🎟️ Token Limits</h5>
<<<<<<< HEAD
              <div class="detail-row"><span class="detail-label">Context Window</span>
                <span class="detail-value">{_fmt(tl.get('context_window'))} tokens</span></div>
              <div class="detail-row"><span class="detail-label">Max Output</span>
                <span class="detail-value">{_fmt(tl.get('max_output_tokens'))} tokens</span></div>
              <div class="detail-row"><span class="detail-label">Configured max_tokens</span>
                <span class="detail-value">{_fmt(tl.get('configured_max_tokens'))}</span></div>
              <div class="detail-row"><span class="detail-label">Temperature</span>
                <span class="detail-value">{tl.get('temperature','Default')}</span></div>
              <div class="detail-row"><span class="detail-label">Top-P</span>
                <span class="detail-value">{tl.get('top_p','Default')}</span></div>
              <div class="detail-row"><span class="detail-label">Freq Penalty</span>
                <span class="detail-value">{tl.get('frequency_penalty','Default')}</span></div>
              <div class="detail-row"><span class="detail-label">Presence Penalty</span>
                <span class="detail-value">{tl.get('presence_penalty','Default')}</span></div>
              <div style="margin-top:10px">
                <div style="font-size:.7rem;color:var(--text-secondary);margin-bottom:4px">Context window scale</div>
                <div class="gauge-bar" style="height:8px">
                  <div class="gauge-fill" style="width:{min(100, ctx/20000):.0f}%"></div>
=======
              <div class="detail-row">
                <span class="detail-label">Context Window</span>
                <span class="detail-value">{_fmt(tl.get('context_window'))} tokens</span>
              </div>
              <div class="detail-row">
                <span class="detail-label">Max Output</span>
                <span class="detail-value">{_fmt(tl.get('max_output_tokens'))} tokens</span>
              </div>
              <div class="detail-row">
                <span class="detail-label">Configured max_tokens</span>
                <span class="detail-value">{_fmt(tl.get('configured_max_tokens'))}</span>
              </div>
              <div class="detail-row">
                <span class="detail-label">Temperature</span>
                <span class="detail-value">{tl.get('temperature','Default')}</span>
              </div>
              <div class="detail-row">
                <span class="detail-label">Top-P</span>
                <span class="detail-value">{tl.get('top_p','Default')}</span>
              </div>
              <div class="detail-row">
                <span class="detail-label">Freq Penalty</span>
                <span class="detail-value">{tl.get('frequency_penalty','Default')}</span>
              </div>
              <div class="detail-row">
                <span class="detail-label">Presence Penalty</span>
                <span class="detail-value">{tl.get('presence_penalty','Default')}</span>
              </div>
              <div style="margin-top:10px">
                <div style="font-size:.7rem;color:var(--text-secondary);margin-bottom:4px">
                  Context window scale
                </div>
                <div class="gauge-bar" style="height:8px">
                  <div class="gauge-fill"
                       style="width:{min(100,(tl.get('context_window',0) or 0)/20000):.0f}%">
                  </div>
>>>>>>> 22a34e63d08307fef2b1fff6762bfa892f2580ef
                </div>
              </div>
            </div>

            <!-- RATE LIMITS -->
            <div class="detail-box">
              <h5>⏱️ Rate Limits</h5>
<<<<<<< HEAD
              <div class="detail-row"><span class="detail-label">Requests / Minute</span>
                <span class="detail-value">{_fmt(rl.get('requests_per_minute'))}</span></div>
              <div class="detail-row"><span class="detail-label">Requests / Hour (est.)</span>
                <span class="detail-value">{_fmt(rl.get('est_per_hour'))}</span></div>
              <div class="detail-row"><span class="detail-label">Requests / Day</span>
                <span class="detail-value">{_fmt(rl.get('requests_per_day'))}</span></div>
              <div class="detail-row"><span class="detail-label">Tokens / Minute</span>
                <span class="detail-value">{_fmt(rl.get('tokens_per_minute'))}</span></div>
              <div class="detail-row"><span class="detail-label">Tokens / Day</span>
                <span class="detail-value">{_fmt(rl.get('tokens_per_day'))}</span></div>
              <div style="margin-top:10px">
                <div class="gauge-container">
                  <div class="gauge-bar">
                    <div class="gauge-fill" style="width:{min(100, rpm/40):.0f}%"></div>
                  </div>
                  <span class="gauge-text">{rpm} rpm</span>
=======
              <div class="detail-row">
                <span class="detail-label">Requests / Minute</span>
                <span class="detail-value">{_fmt(rl.get('requests_per_minute'))}</span>
              </div>
              <div class="detail-row">
                <span class="detail-label">Requests / Hour (est.)</span>
                <span class="detail-value">{_fmt(rl.get('est_per_hour'))}</span>
              </div>
              <div class="detail-row">
                <span class="detail-label">Requests / Day</span>
                <span class="detail-value">{_fmt(rl.get('requests_per_day'))}</span>
              </div>
              <div class="detail-row">
                <span class="detail-label">Tokens / Minute</span>
                <span class="detail-value">{_fmt(rl.get('tokens_per_minute'))}</span>
              </div>
              <div class="detail-row">
                <span class="detail-label">Tokens / Day</span>
                <span class="detail-value">{_fmt(rl.get('tokens_per_day'))}</span>
              </div>
              <div style="margin-top:10px">
                <div class="gauge-container">
                  <div class="gauge-bar">
                    <div class="gauge-fill"
                         style="width:{min(100,(rl.get('requests_per_minute',0) or 0)/40):.0f}%">
                    </div>
                  </div>
                  <span class="gauge-text">{rl.get('requests_per_minute','?')} rpm</span>
>>>>>>> 22a34e63d08307fef2b1fff6762bfa892f2580ef
                </div>
              </div>
            </div>

            <!-- COSTS -->
            <div class="detail-box">
              <h5>💰 Cost</h5>
<<<<<<< HEAD
              <div class="detail-row"><span class="detail-label">Input / 1K tokens</span>
                <span class="detail-value">{cost.get('input_per_1k','—')}</span></div>
              <div class="detail-row"><span class="detail-label">Output / 1K tokens</span>
                <span class="detail-value">{cost.get('output_per_1k','—')}</span></div>
              <div class="detail-row"><span class="detail-label">Per 1M input tokens</span>
                <span class="detail-value">{cost.get('per_1m_input','—')}</span></div>
              <div class="detail-row"><span class="detail-label">Per 1M output tokens</span>
                <span class="detail-value">{cost.get('per_1m_output','—')}</span></div>
              <div class="detail-row"><span class="detail-label">Est. Max Hourly</span>
                <span class="detail-value" style="color:#d9534f;font-weight:800">
                  {cost.get('est_max_hourly','—')}
                </span></div>
=======
              <div class="detail-row">
                <span class="detail-label">Input / 1K tokens</span>
                <span class="detail-value">{cost.get('input_per_1k','—')}</span>
              </div>
              <div class="detail-row">
                <span class="detail-label">Output / 1K tokens</span>
                <span class="detail-value">{cost.get('output_per_1k','—')}</span>
              </div>
              <div class="detail-row">
                <span class="detail-label">Per 1M input tokens</span>
                <span class="detail-value">{cost.get('per_1m_input','—')}</span>
              </div>
              <div class="detail-row">
                <span class="detail-label">Per 1M output tokens</span>
                <span class="detail-value">{cost.get('per_1m_output','—')}</span>
              </div>
              <div class="detail-row">
                <span class="detail-label">Est. Max Hourly</span>
                <span class="detail-value" style="color:#d9534f;font-weight:800">
                  {cost.get('est_max_hourly','—')}
                </span>
              </div>
>>>>>>> 22a34e63d08307fef2b1fff6762bfa892f2580ef
              <div style="font-size:.7rem;color:var(--text-secondary);margin-top:6px">
                * At full RPM × max context tokens
              </div>
            </div>

            <!-- FOUND IN CODE -->
            <div class="detail-box">
              <h5>🔍 Found In Code</h5>
<<<<<<< HEAD
              <div class="detail-row"><span class="detail-label">Model strings</span>
                <span class="detail-value" style="font-size:.78rem">
                  {', '.join(fic.get('raw_model_strings',[])) or '—'}
                </span></div>
              <div class="detail-row"><span class="detail-label">Configured params</span>
                <span class="detail-value" style="font-size:.78rem">
                  {', '.join([f'{k}={v}' for k,v in cfg.items()]) or 'None (defaults)'}
                </span></div>
              <div style="margin-top:10px">
                <div style="font-size:.72rem;font-weight:700;text-transform:uppercase;
                             color:var(--accent);margin-bottom:6px">API Keys referenced</div>
=======
              <div class="detail-row">
                <span class="detail-label">Model strings</span>
                <span class="detail-value" style="font-size:.78rem">
                  {', '.join(fic.get('raw_model_strings',[])) or '—'}
                </span>
              </div>
              <div class="detail-row">
                <span class="detail-label">Configured params</span>
                <span class="detail-value" style="font-size:.78rem">
                  {', '.join([f'{k}={v}' for k,v in cfg.items()]) or 'None (defaults)'}
                </span>
              </div>
              <div style="margin-top:10px">
                <div style="font-size:.72rem;font-weight:700;text-transform:uppercase;
                             color:var(--accent);margin-bottom:6px">
                  API Keys referenced
                </div>
>>>>>>> 22a34e63d08307fef2b1fff6762bfa892f2580ef
                {env_tags}
              </div>
            </div>

          </div><!-- /detail-grid -->

          <!-- Features -->
          <div style="margin-top:12px;padding-top:10px;border-top:1px solid var(--border)">
            <span style="font-size:.75rem;font-weight:700;color:var(--accent2);
                         text-transform:uppercase;letter-spacing:.5px;margin-right:8px">
              ✨ Features:
            </span>
            {features_html or '<span style="font-size:.8rem;color:var(--text-secondary)">—</span>'}
          </div>

        </div>"""

    return html

<<<<<<< HEAD

# ══════════════════════════════════════════════════════════════════════════════
# ROUTE: /scanner/scan
=======
# ══════════════════════════════════════════════════════════════════════════════
# ROUTE: /scanner/scan  (HTML)
>>>>>>> 22a34e63d08307fef2b1fff6762bfa892f2580ef
# ══════════════════════════════════════════════════════════════════════════════

@scanner_bp.get("/scan")
def scanner_scan():
<<<<<<< HEAD
    data   = scan_project()
    pretty = json.dumps(data, indent=2, default=str)
    s      = data["summary"]

    stats_html = "".join([
        _stat_card("🚀", s["pipelines_detected"], "Pipelines"),
        _stat_card("🤖", s["ai_agents_found"],    "AI Agents"),
        _stat_card("🧠", s["models_used"],         "Models"),
        _stat_card("📦", s["total_files"],          "Total Files"),
        _stat_card("🐍", s["python_files"],         "Python Files"),
        _stat_card("🔑", len(data["active_env_keys"]), "API Keys"),
    ])

    # ── Pipelines ──────────────────────────────────────────────────────────
    pip_html = ""
    if data["pipelines"]:
        for p in data["pipelines"]:
            status  = ('<span class="pipeline-status running">● Running Here</span>'
                       if p["is_running_here"]
                       else '<span class="pipeline-status detected">◉ Detected</span>')
            configs = "".join(f'<span class="config-file-tag">📄 {f}</span>'
                              for f in p["config_files"])
            pip_html += f"""
            <div class="card pipeline-card">
              <div style="display:flex;justify-content:space-between;align-items:center;
                          flex-wrap:wrap;gap:8px;margin-bottom:8px">
                <span style="font-weight:700;font-size:1.05rem;color:var(--accent2)">
                  🏗️ {p['platform']} — {p['pipeline_name']}
                </span>
                {status}
              </div>
              <p style="color:var(--text-secondary);font-size:.88rem;margin-bottom:8px">
                {p['description']}
              </p>
=======
    data = scan_project()
    pretty = json.dumps(data, indent=2, default=str)

    s = data["summary"]
    stats_html = "".join([
        _stat_card("🚀", s["pipelines_detected"], "Pipelines"),
        _stat_card("🤖", s["ai_agents_found"], "AI Agents"),
        _stat_card("🧠", s["models_used"], "Models"),
        _stat_card("📦", s["total_files"], "Total Files"),
        _stat_card("🐍", s["python_files"], "Python Files"),
        _stat_card("🔑", len(data["active_env_keys"]), "API Keys"),
    ])

    # Pipelines section
    pip_html = ""
    if data["pipelines"]:
        for p in data["pipelines"]:
            status = '<span class="pipeline-status running">● Running Here</span>' if p["is_running_here"] else '<span class="pipeline-status detected">◉ Detected</span>'
            configs = "".join([f'<span class="config-file-tag">📄 {f}</span>' for f in p["config_files"]])
            pip_html += f"""
            <div class="card pipeline-card">
              <div style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:8px;margin-bottom:8px">
                <span style="font-weight:700;font-size:1.05rem;color:var(--accent2)">🏗️ {p['platform']} — {p['pipeline_name']}</span>
                {status}
              </div>
              <p style="color:var(--text-secondary);font-size:.88rem;margin-bottom:8px">{p['description']}</p>
>>>>>>> 22a34e63d08307fef2b1fff6762bfa892f2580ef
              <div>{configs}</div>
            </div>"""
    else:
        pip_html = '<div class="empty-state"><div class="empty-icon">🔍</div><p>No pipelines detected</p></div>'

<<<<<<< HEAD
    # ── Agents ─────────────────────────────────────────────────────────────
    agents_html = ""
    if data["agents"]:
        for agent in data["agents"]:
            provs = "".join(f'<span class="tag provider">🏢 {p}</span>' for p in agent["providers"])
            pats  = "".join(f'<span class="tag pattern">⚙️ {p}</span>' for p in agent["patterns"])
            envs  = "".join(f'<span class="tag env">🔐 {e}</span>'     for e in agent["env_vars"])

            models_html = _render_model_details(agent.get("model_details", []))

            agents_html += f"""
            <div class="card agent-card">
              <div style="font-weight:700;font-size:1.05rem;color:var(--accent2);margin-bottom:12px">
                📜 {agent['script']}
              </div>
=======
    # Agents section
    agents_html = ""
    if data["agents"]:
        for agent in data["agents"]:
            provs = "".join([f'<span class="tag provider">🏢 {p}</span>' for p in agent["providers"]])
            pats = "".join([f'<span class="tag pattern">⚙️ {p}</span>' for p in agent["patterns"]])
            envs = "".join([f'<span class="tag env">🔐 {e}</span>' for e in agent["env_vars"]])

        models_html = _render_model_details(agent.get("model_details", []))
        
            agents_html += f"""
            <div class="card agent-card">
              <div style="font-weight:700;font-size:1.05rem;color:var(--accent2);margin-bottom:12px">📜 {agent['script']}</div>
>>>>>>> 22a34e63d08307fef2b1fff6762bfa892f2580ef
              <div style="margin-bottom:8px">{provs}</div>
              <div style="margin-bottom:8px">{pats}</div>
              <div style="margin-bottom:8px">{envs}</div>
              {models_html}
            </div>"""
    else:
        agents_html = '<div class="empty-state"><div class="empty-icon">🤖</div><p>No AI agents detected</p></div>'

<<<<<<< HEAD
    # ── Files ──────────────────────────────────────────────────────────────
    file_icon_map = {
        ".py": "🐍", ".html": "🌐", ".css": "🎨", ".js": "⚡",
        ".yml": "📋", ".yaml": "📋", ".json": "📦",
        ".md": "📝", ".txt": "📄", ".sh": "💻", ".sql": "🗄️",
    }
    files_html = ('<div class="file-tree-header"><span></span><span>File</span>'
                  '<span class="fh-purpose">Purpose</span>'
                  '<span style="text-align:right">Size</span></div>')
    for f in data["file_tree"]:
        icon     = file_icon_map.get(f["extension"], "📄")
        cls      = "file-row main-file" if f["is_main"] else "file-row"
        star     = "⭐ " if f["is_main"] else ""
        size_str = (f'{f["size"]}B'               if f["size"] < 1024
                    else f'{f["size"]/1024:.1f}KB' if f["size"] < 1048576
                    else f'{f["size"]/1048576:.1f}MB')
        files_html += (f'<div class="{cls}">'
                       f'<span style="text-align:center">{icon}</span>'
                       f'<span>{star}{f["path"]}</span>'
                       f'<span class="f-purpose" style="color:var(--text-secondary);font-size:.78rem">{f["purpose"]}</span>'
                       f'<span style="text-align:right;font-size:.75rem;color:var(--text-secondary)">{size_str}</span>'
                       f'</div>')
=======
    # Files section
    file_icon_map = {".py": "🐍", ".html": "🌐", ".css": "🎨", ".js": "⚡", ".yml": "📋",
                     ".yaml": "📋", ".json": "📦", ".md": "📝", ".txt": "📄", ".sh": "💻", ".sql": "🗄️"}
    files_html = '<div class="file-tree-header"><span></span><span>File</span><span class="fh-purpose">Purpose</span><span style="text-align:right">Size</span></div>'
    for f in data["file_tree"]:
        icon = file_icon_map.get(f["extension"], "📄")
        cls = "file-row main-file" if f["is_main"] else "file-row"
        star = "⭐ " if f["is_main"] else ""
        size_str = f'{f["size"]}B' if f["size"] < 1024 else f'{f["size"]/1024:.1f}KB' if f["size"] < 1048576 else f'{f["size"]/1048576:.1f}MB'
        files_html += f'<div class="{cls}"><span style="text-align:center">{icon}</span><span>{star}{f["path"]}</span><span class="f-purpose" style="color:var(--text-secondary);font-size:.78rem">{f["purpose"]}</span><span style="text-align:right;font-size:.75rem;color:var(--text-secondary)">{size_str}</span></div>'
>>>>>>> 22a34e63d08307fef2b1fff6762bfa892f2580ef

    body = f"""
    <div class="stats-grid">{stats_html}</div>

    <div class="section">
      <div class="section-title">🚀 Detected Pipelines</div>
      {pip_html}
    </div>

    <div class="section">
<<<<<<< HEAD
      <div class="section-title">🤖 AI Agents ({s['ai_agents_found']})</div>
=======
      <div class="section-title">🤖 AI Agents</div>
>>>>>>> 22a34e63d08307fef2b1fff6762bfa892f2580ef
      {agents_html}
    </div>

    <div class="section">
      <div class="section-title">📁 Project Files ({s['total_files']})</div>
      <div class="card" style="padding:0;overflow:hidden">
        {files_html}
      </div>
    </div>

    <div class="section">
      <div class="section-title">📋 Raw JSON Data</div>
      <div class="card">
        <div class="json-box">{_colorize_json(pretty)}</div>
      </div>
    </div>"""

    return wrap_page("Scan Results", body, active="scan")


# ══════════════════════════════════════════════════════════════════════════════
<<<<<<< HEAD
# ROUTE: /scanner/health
=======
# ROUTE: /scanner/health (HTML)
>>>>>>> 22a34e63d08307fef2b1fff6762bfa892f2580ef
# ══════════════════════════════════════════════════════════════════════════════

@scanner_bp.get("/health")
def scanner_health():
<<<<<<< HEAD
    now  = datetime.datetime.now(datetime.timezone.utc).isoformat()
    data = scan_project()
    s    = data["summary"]

    checks = [
        ("Module Loaded",       "agent_monitor.py", True),
        ("Flask Application",   "Running",           True),
        ("Scanner Blueprint",   "Registered",        True),
        ("Monitor Blueprint",   "Registered",        True),
        ("Python Files Scanned", str(s["python_files"]),       True),
        ("Pipelines Detected",   str(s["pipelines_detected"]), True),
        ("AI Agents Found",      str(s["ai_agents_found"]),    True),
        ("API Keys Active",      str(len(data["active_env_keys"])),
         len(data["active_env_keys"]) > 0),
=======
    now = datetime.datetime.now(datetime.timezone.utc).isoformat()
    data = scan_project()
    s = data["summary"]

    checks = [
        ("Module Loaded", "agent_monitor.py", True),
        ("Flask Application", "Running", True),
        ("Scanner Blueprint", "Registered", True),
        ("Monitor Blueprint", "Registered", True),
        ("Python Files Scanned", str(s["python_files"]), True),
        ("Pipelines Detected", str(s["pipelines_detected"]), True),
        ("AI Agents Found", str(s["ai_agents_found"]), True),
        ("API Keys Active", str(len(data["active_env_keys"])), len(data["active_env_keys"]) > 0),
>>>>>>> 22a34e63d08307fef2b1fff6762bfa892f2580ef
    ]

    checks_html = ""
    for label, value, ok in checks:
        icon = "✅" if ok else "⚠️"
        checks_html += f"""
        <div class="detail-row">
          <span class="detail-label">{icon} {label}</span>
          <span class="detail-value">{value}</span>
        </div>"""

    body = f"""
    <div class="card status-card">
      <div class="status-icon">💚</div>
      <div class="status-ok">HEALTHY</div>
      <p style="color:var(--text-secondary);margin-top:8px">All systems operational — {now}</p>
    </div>

    <div class="stats-grid" style="margin-top:24px">
      {_stat_card("🚀", s["pipelines_detected"], "Pipelines")}
<<<<<<< HEAD
      {_stat_card("🤖", s["ai_agents_found"],    "Agents")}
      {_stat_card("📦", s["total_files"],          "Files")}
      {_stat_card("🐍", s["python_files"],         "Python")}
=======
      {_stat_card("🤖", s["ai_agents_found"], "Agents")}
      {_stat_card("📦", s["total_files"], "Files")}
      {_stat_card("🐍", s["python_files"], "Python")}
>>>>>>> 22a34e63d08307fef2b1fff6762bfa892f2580ef
    </div>

    <div class="section">
      <div class="section-title">🔍 Health Checks</div>
      <div class="card">
        <div class="detail-box" style="border:none;padding:0">
          {checks_html}
        </div>
      </div>
    </div>

    <div class="section">
      <div class="section-title">📋 Response JSON</div>
      <div class="card">
        <div class="json-box">{_colorize_json(json.dumps({"status":"healthy","module":"agent_monitor","timestamp":now,"summary":s}, indent=2))}</div>
      </div>
    </div>"""

    return wrap_page("Health Check", body, active="health")


# ══════════════════════════════════════════════════════════════════════════════
<<<<<<< HEAD
# ROUTE: /monitor/dashboard
=======
# ROUTE: /monitor/dashboard  (FULL INTERACTIVE DASHBOARD)
>>>>>>> 22a34e63d08307fef2b1fff6762bfa892f2580ef
# ══════════════════════════════════════════════════════════════════════════════

@monitor_bp.get("/dashboard")
def monitor_dashboard():
    data = scan_project()
<<<<<<< HEAD
    s    = data["summary"]

    stats_html = "".join([
        _stat_card("🚀", s["pipelines_detected"],      "Pipelines"),
        _stat_card("🤖", s["ai_agents_found"],         "AI Agents"),
        _stat_card("🧠", s["models_used"],              "Models"),
        _stat_card("📦", s["total_files"],               "Total Files"),
        _stat_card("🐍", s["python_files"],              "Python Files"),
        _stat_card("🔑", len(data["active_env_keys"]),  "API Keys"),
    ])

    # ── Pipelines tab ──────────────────────────────────────────────────────
    pip_cards = ""
    if data["pipelines"]:
        for p in data["pipelines"]:
            status   = ('<span class="pipeline-status running">● Running Here</span>'
                        if p["is_running_here"]
                        else '<span class="pipeline-status detected">◉ Detected</span>')
            configs  = "".join(f'<span class="config-file-tag">📄 {f}</span>' for f in p["config_files"])
            env_tags = "".join(f'<span class="tag env">🔐 {v}</span>'          for v in p["active_env_vars"])
            pip_cards += f"""
            <div class="card pipeline-card">
              <div style="display:flex;justify-content:space-between;align-items:center;
                          flex-wrap:wrap;gap:8px;margin-bottom:8px">
                <span style="font-weight:700;font-size:1.05rem;color:var(--accent2)">
                  🏗️ {p['platform']} — {p['pipeline_name']}
                </span>
                {status}
              </div>
              <p style="color:var(--text-secondary);font-size:.88rem;margin-bottom:10px">
                {p['description']}
              </p>
=======
    s = data["summary"]

    stats_html = "".join([
        _stat_card("🚀", s["pipelines_detected"], "Pipelines"),
        _stat_card("🤖", s["ai_agents_found"], "AI Agents"),
        _stat_card("🧠", s["models_used"], "Models"),
        _stat_card("📦", s["total_files"], "Total Files"),
        _stat_card("🐍", s["python_files"], "Python Files"),
        _stat_card("🔑", len(data["active_env_keys"]), "API Keys"),
    ])

    # ── Pipelines tab ──
    pip_cards = ""
    if data["pipelines"]:
        for p in data["pipelines"]:
            status = '<span class="pipeline-status running">● Running Here</span>' if p["is_running_here"] else '<span class="pipeline-status detected">◉ Detected</span>'
            configs = "".join([f'<span class="config-file-tag">📄 {f}</span>' for f in p["config_files"]])
            env_tags = "".join([f'<span class="tag env">🔐 {v}</span>' for v in p["active_env_vars"]])
            pip_cards += f"""
            <div class="card pipeline-card">
              <div style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:8px;margin-bottom:8px">
                <span style="font-weight:700;font-size:1.05rem;color:var(--accent2)">🏗️ {p['platform']} — {p['pipeline_name']}</span>
                {status}
              </div>
              <p style="color:var(--text-secondary);font-size:.88rem;margin-bottom:10px">{p['description']}</p>
>>>>>>> 22a34e63d08307fef2b1fff6762bfa892f2580ef
              <div style="margin-bottom:6px">{configs}</div>
              <div>{env_tags}</div>
            </div>"""
    else:
<<<<<<< HEAD
        pip_cards = ('<div class="empty-state"><div class="empty-icon">🔍</div>'
                     '<p style="font-weight:700">No CI/CD pipelines detected</p>'
                     '<p style="margin-top:4px;font-size:.85rem">Add a workflow file to get started</p></div>')

    # ── Agents tab ─────────────────────────────────────────────────────────
    agents_cards = ""
    if data["agents"]:
        for idx, agent in enumerate(data["agents"]):
            provs = "".join(f'<span class="tag provider">🏢 {p}</span>' for p in agent["providers"])
            pats  = "".join(f'<span class="tag pattern">⚙️ {p}</span>' for p in agent["patterns"])
            envs  = "".join(f'<span class="tag env">🔐 {e}</span>'     for e in agent["env_vars"])

            models_html = _render_model_details(agent.get("model_details", []))

            agents_cards += f"""
            <div class="card agent-card">
              <div style="display:flex;justify-content:space-between;align-items:center;
                          flex-wrap:wrap;gap:8px;margin-bottom:12px">
                <span style="font-weight:700;font-size:1.05rem;color:var(--accent2)">
                  📜 {agent['script']}
                </span>
=======
        pip_cards = '<div class="empty-state"><div class="empty-icon">🔍</div><p style="font-weight:700">No CI/CD pipelines detected</p><p style="margin-top:4px;font-size:.85rem">Add a workflow file to get started</p></div>'

    # ── Agents tab ──
    agents_cards = ""
    if data["agents"]:
        for idx, agent in enumerate(data["agents"]):
            provs = "".join([f'<span class="tag provider">🏢 {p}</span>' for p in agent["providers"]])
            pats = "".join([f'<span class="tag pattern">⚙️ {p}</span>' for p in agent["patterns"]])
            envs = "".join([f'<span class="tag env">🔐 {e}</span>' for e in agent["env_vars"]])

models_html = _render_model_details(agent.get("model_details", []))
                toks = md.get("tokens", {})
                rh = md.get("rate_limits_hourly", {})
                rd = md.get("rate_limits_daily", {})

                max_h = rh.get("est_per_hour", 0) if isinstance(rh.get("est_per_hour"), (int, float)) else 0
                max_d = rd.get("requests_per_day", 0) if isinstance(rd.get("requests_per_day"), (int, float)) else 0
                inp = toks.get("max_input", 0) if isinstance(toks.get("max_input"), (int, float)) else 0
                out = toks.get("max_output", 0) if isinstance(toks.get("max_output"), (int, float)) else 0

                bar_inp_h = min(100, (inp / 2000)) if inp else 10
                bar_out_h = min(100, (out / 500)) if out else 10

                models_html += f"""
                <div class="model-detail">
                  <h4>🧠 {md['model_name']} <span style="font-weight:400;font-size:.85rem">({md['provider']})</span></h4>
                  <div class="detail-grid">
                    <div class="detail-box">
                      <h5>🏷️ Identity</h5>
                      <div class="detail-row"><span class="detail-label">Model</span><span class="detail-value">{md['model_name']}</span></div>
                      <div class="detail-row"><span class="detail-label">Provider</span><span class="detail-value">{md['provider']}</span></div>
                      <div class="detail-row"><span class="detail-label">Script</span><span class="detail-value">{md['where_used']}</span></div>
                      <div class="detail-row"><span class="detail-label">Purpose</span><span class="detail-value">{md['why_used']}</span></div>
                    </div>
                    <div class="detail-box">
                      <h5>🎟️ Token Limits</h5>
                      <div class="detail-row"><span class="detail-label">Max Input</span><span class="detail-value">{_fmt(toks.get('max_input'))}</span></div>
                      <div class="detail-row"><span class="detail-label">Max Output</span><span class="detail-value">{_fmt(toks.get('max_output'))}</span></div>
                      <div class="detail-row"><span class="detail-label">Configured</span><span class="detail-value">{_fmt(toks.get('configured_max_tokens'))}</span></div>
                      <div class="detail-row"><span class="detail-label">Temperature</span><span class="detail-value">{toks.get('temperature') or 'Default'}</span></div>
                      <div style="display:flex;gap:6px;margin-top:10px;height:40px;align-items:flex-end">
                        <div style="flex:1;background:var(--gradient);border-radius:4px 4px 0 0;height:{bar_inp_h}%;min-height:4px" title="Input tokens"></div>
                        <div style="flex:1;background:linear-gradient(135deg,#1a6834,#4caf50);border-radius:4px 4px 0 0;height:{bar_out_h}%;min-height:4px" title="Output tokens"></div>
                      </div>
                      <div style="display:flex;gap:6px;font-size:.65rem;color:var(--text-secondary)"><span style="flex:1;text-align:center">Input</span><span style="flex:1;text-align:center">Output</span></div>
                    </div>
                    <div class="detail-box">
                      <h5>⏱️ Hourly Rate</h5>
                      <div class="detail-row"><span class="detail-label">RPM</span><span class="detail-value">{_fmt(rh.get('requests_per_minute'))}</span></div>
                      <div class="detail-row"><span class="detail-label">Per Hour</span><span class="detail-value">{_fmt(rh.get('est_per_hour'))}</span></div>
                      <div class="detail-row"><span class="detail-label">Window</span><span class="detail-value">{rh.get('window','—')}</span></div>
                      <div class="gauge-container"><div class="gauge-bar"><div class="gauge-fill" style="width:25%"></div></div><span class="gauge-text">25%</span></div>
                    </div>
                    <div class="detail-box">
                      <h5>📅 Daily Rate</h5>
                      <div class="detail-row"><span class="detail-label">RPD</span><span class="detail-value">{_fmt(rd.get('requests_per_day'))}</span></div>
                      <div class="detail-row"><span class="detail-label">Window</span><span class="detail-value">{rd.get('window','—')}</span></div>
                      <div class="gauge-container"><div class="gauge-bar"><div class="gauge-fill" style="width:12%"></div></div><span class="gauge-text">12%</span></div>
                    </div>
                  </div>
                </div>"""

            agents_cards += f"""
            <div class="card agent-card">
              <div style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:8px;margin-bottom:12px">
                <span style="font-weight:700;font-size:1.05rem;color:var(--accent2)">📜 {agent['script']}</span>
>>>>>>> 22a34e63d08307fef2b1fff6762bfa892f2580ef
                <span style="font-size:.8rem;color:var(--text-secondary)">Agent #{idx+1}</span>
              </div>
              <div style="margin-bottom:8px">{provs}</div>
              {f'<div style="margin-bottom:8px">{pats}</div>' if pats else ''}
              {f'<div style="margin-bottom:8px">{envs}</div>' if envs else ''}
              {models_html}
            </div>"""
    else:
<<<<<<< HEAD
        agents_cards = ('<div class="empty-state"><div class="empty-icon">🤖</div>'
                        '<p style="font-weight:700">No AI agents detected</p></div>')

    # ── Characteristics tab ────────────────────────────────────────────────
    chars_html = "".join(f"""
        <div class="char-card">
          <div class="char-icon">{c['icon']}</div>
          <div class="char-info"><h4>{c['trait']}</h4><p>{c['desc']}</p></div>
        </div>""" for c in AI_AGENT_CHARACTERISTICS)

    # ── Files tab ──────────────────────────────────────────────────────────
    file_icon_map = {
        ".py": "🐍", ".html": "🌐", ".css": "🎨", ".js": "⚡",
        ".yml": "📋", ".yaml": "📋", ".json": "📦",
        ".md": "📝", ".txt": "📄", ".sh": "💻",
    }
    files_rows = ""
    for f in data["file_tree"]:
        icon = file_icon_map.get(f["extension"], "📄")
        cls  = "file-row main-file" if f["is_main"] else "file-row"
        star = "⭐ " if f["is_main"] else ""
        sz   = (f'{f["size"]}B'               if f["size"] < 1024
                else f'{f["size"]/1024:.1f}KB' if f["size"] < 1048576
                else f'{f["size"]/1048576:.1f}MB')
        files_rows += (f'<div class="{cls}">'
                       f'<span style="text-align:center">{icon}</span>'
                       f'<span>{star}{f["path"]}</span>'
                       f'<span class="f-purpose" style="color:var(--text-secondary);font-size:.78rem">{f["purpose"]}</span>'
                       f'<span style="text-align:right;font-size:.75rem;color:var(--text-secondary)">{sz}</span>'
                       f'</div>')
=======
        agents_cards = '<div class="empty-state"><div class="empty-icon">🤖</div><p style="font-weight:700">No AI agents detected</p></div>'

    # ── Characteristics tab ──
    chars_html = "".join([f"""
        <div class="char-card">
          <div class="char-icon">{c['icon']}</div>
          <div class="char-info"><h4>{c['trait']}</h4><p>{c['desc']}</p></div>
        </div>""" for c in AI_AGENT_CHARACTERISTICS])

    # ── Files tab ──
    file_icon_map = {".py": "🐍", ".html": "🌐", ".css": "🎨", ".js": "⚡", ".yml": "📋",
                     ".yaml": "📋", ".json": "📦", ".md": "📝", ".txt": "📄", ".sh": "💻"}
    files_rows = ""
    for f in data["file_tree"]:
        icon = file_icon_map.get(f["extension"], "📄")
        cls = "file-row main-file" if f["is_main"] else "file-row"
        star = "⭐ " if f["is_main"] else ""
        sz = f'{f["size"]}B' if f["size"] < 1024 else f'{f["size"]/1024:.1f}KB'
        files_rows += f'<div class="{cls}"><span style="text-align:center">{icon}</span><span>{star}{f["path"]}</span><span class="f-purpose" style="color:var(--text-secondary);font-size:.78rem">{f["purpose"]}</span><span style="text-align:right;font-size:.75rem;color:var(--text-secondary)">{sz}</span></div>'
>>>>>>> 22a34e63d08307fef2b1fff6762bfa892f2580ef

    body = f"""
    <div class="stats-grid">{stats_html}</div>

    <div class="tabs">
      <div class="tab active" onclick="switchTab('pipelines')" data-tab="pipelines">🚀 Pipelines</div>
<<<<<<< HEAD
      <div class="tab" onclick="switchTab('agents')"    data-tab="agents">🤖 AI Agents</div>
      <div class="tab" onclick="switchTab('chars')"     data-tab="chars">🧬 Agent Traits</div>
      <div class="tab" onclick="switchTab('files')"     data-tab="files">📁 Files</div>
=======
      <div class="tab" onclick="switchTab('agents')" data-tab="agents">🤖 AI Agents</div>
      <div class="tab" onclick="switchTab('chars')" data-tab="chars">🧬 Agent Traits</div>
      <div class="tab" onclick="switchTab('files')" data-tab="files">📁 Files</div>
>>>>>>> 22a34e63d08307fef2b1fff6762bfa892f2580ef
    </div>

    <div class="tab-content active" id="tab-pipelines">
      <div class="section">
        <div class="section-title">🚀 Detected CI/CD Pipelines</div>
        {pip_cards}
      </div>
    </div>

    <div class="tab-content" id="tab-agents">
      <div class="section">
        <div class="section-title">🤖 AI Agents Found ({s['ai_agents_found']})</div>
        {agents_cards}
      </div>
    </div>

    <div class="tab-content" id="tab-chars">
      <div class="section">
        <div class="section-title">🧬 AI Agent Characteristics — Identification Traits</div>
        <p style="color:var(--text-secondary);margin-bottom:16px;font-size:.88rem">
<<<<<<< HEAD
          An AI agent is identified by exhibiting several of these core traits.
=======
          An AI agent is identified by exhibiting several of these core traits. The scanner checks code patterns for each.
>>>>>>> 22a34e63d08307fef2b1fff6762bfa892f2580ef
        </p>
        <div class="char-grid">{chars_html}</div>
      </div>
    </div>

    <div class="tab-content" id="tab-files">
      <div class="section">
        <div class="section-title">📁 Project File Structure ({s['total_files']} files)</div>
        <div class="card" style="padding:0;overflow:hidden">
<<<<<<< HEAD
          <div class="file-tree-header">
            <span></span><span>File</span>
            <span class="fh-purpose">Purpose</span>
            <span style="text-align:right">Size</span>
          </div>
=======
          <div class="file-tree-header"><span></span><span>File</span><span class="fh-purpose">Purpose</span><span style="text-align:right">Size</span></div>
>>>>>>> 22a34e63d08307fef2b1fff6762bfa892f2580ef
          {files_rows}
        </div>
      </div>
    </div>

    <script>
    function switchTab(name){{
      document.querySelectorAll('.tab').forEach(t=>t.classList.toggle('active',t.dataset.tab===name));
      document.querySelectorAll('.tab-content').forEach(c=>c.classList.toggle('active',c.id==='tab-'+name));
    }}
    </script>"""

<<<<<<< HEAD
    return wrap_page("Dashboard", body, active="dashboard")
=======
    return wrap_page("Dashboard", body, active="dashboard")


# ══════════════════════════════════════════════════════════════════════════════
# HELPERS
# ══════════════════════════════════════════════════════════════════════════════

def _stat_card(icon, value, label):
    return f"""<div class="stat-card"><div class="stat-icon">{icon}</div><div class="stat-value">{value}</div><div class="stat-label">{label}</div></div>"""


def _fmt(val):
    if val is None or val == "Unknown" or val == "Default":
        return val or "—"
    if isinstance(val, (int, float)):
        return f"{val:,.0f}" if isinstance(val, float) else f"{val:,}"
    return str(val)
>>>>>>> 22a34e63d08307fef2b1fff6762bfa892f2580ef

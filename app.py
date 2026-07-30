"""
app.py
======
Flask entry point for SentinelOps-Lite.
Only routes and redirections live here.
All logic lives in agent_monitor.py.
"""

import os
import sys
from pathlib import Path

from flask import render_template, Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

# ── path setup ────────────────────────────────────────────────
BASE_DIR = Path(__file__).resolve().parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

# ── import application and blueprint from agent_monitor ───────
from agent_monitor import application, monitor_bp, scanner_bp

# ── register blueprints ───────────────────────────────────────
application.register_blueprint(monitor_bp)
application.register_blueprint(scanner_bp)


# ══════════════════════════════════════════════════════════════
# ROUTES  —  only links and redirections live here
# ══════════════════════════════════════════════════════════════

@application.get("/")
def home():
    """Main dashboard page."""
    return render_template("index.html")


@application.post("/monitor/status")
def monitor_status():
    """
    CI / monitoring webhook.
    Delegates entirely to agent_monitor.handle_monitor_status().
    """
    from agent_monitor import handle_monitor_status
    return handle_monitor_status()

@application.get("/metrics")
def prometheus_metrics():
    """Prometheus scrape endpoint."""
    return Response(
        generate_latest(),
        content_type=CONTENT_TYPE_LATEST,
    )

# ══════════════════════════════════════════════════════════════
# WSGI entry point
# ══════════════════════════════════════════════════════════════

if __name__ == "__main__":
    port  = int(os.environ.get("PORT", "5000"))
    debug = os.environ.get("FLASK_DEBUG") == "1"
    application.run(host="0.0.0.0", port=port, debug=debug)
"""
debug_routes.py — Optional diagnostic endpoints
================================================

Registered automatically by app.py IF this file exists.
Delete or rename this file in production to disable.

All endpoints are exposed under /debug/* to avoid polluting main routes.

┌────────────────┬──────────────────────────────────────────────────────┐
│ Endpoint       │ Purpose (when to use)                                │
├────────────────┼──────────────────────────────────────────────────────┤
│ /debug/state   │ Snapshot: components, PIDs, DB path, active config   │
│                │ USE WHEN: dashboard shows nothing → check if _db,    │
│                │ _scanner, _monitor are initialized                   │
├────────────────┼──────────────────────────────────────────────────────┤
│ /debug/db      │ Raw SELECT from detected_files (5 rows)              │
│                │ USE WHEN: verify DB has data + inspect column names  │
├────────────────┼──────────────────────────────────────────────────────┤
│ /debug/data    │ Runs _get_data() and reports what dashboard receives │
│                │ USE WHEN: DB has rows but dashboard shows zero →     │
│                │ isolates bug to _get_data() or HTMLBuilder           │
├────────────────┼──────────────────────────────────────────────────────┤
│ /debug/rescan  │ Force re-scan of project. Returns file counts.       │
│                │ USE WHEN: DB is empty after redeploy / new files     │
├────────────────┼──────────────────────────────────────────────────────┤
│ /debug/monitor │ Inspects ResourceMonitor internals (sim thread,      │
│                │ token log, request log). Confirms background thread. │
│                │ USE WHEN: Tok/Min = 0 → is the sim loop running?     │
├────────────────┼──────────────────────────────────────────────────────┤
│ /debug/ci      │ Lists current CI-agent Prometheus label values       │
│                │ USE WHEN: Grafana CI-agent panels show "No data"     │
├────────────────┼──────────────────────────────────────────────────────┤
│ /debug/env     │ Sanitized env vars (redacts *_KEY, *_TOKEN)          │
│                │ USE WHEN: wrong AI_MODEL / SCAN_PATH / etc.          │
└────────────────┴──────────────────────────────────────────────────────┘
"""
from __future__ import annotations

import os
import traceback
from flask import Blueprint, jsonify

from app import (
    _db, _scanner, _monitor, _HTMLBuilder,
    _IMPORT_ERROR, _CFG, BASE_DIR, _get_data,
    ci_agent_status, ci_agent_tokens_total,
)

debug_bp = Blueprint("debug", __name__, url_prefix="/debug")


# ── /debug/state ─────────────────────────────────────────────────────
# WHY: single snapshot of all live components. First check when something
# breaks. Confirms agent_monitor imported and components initialized.
@debug_bp.get("/state")
def state():
    return jsonify({
        "pid":           os.getpid(),
        "_db":           str(_db),
        "_db_path":      getattr(_db, "db_path", None),
        "_scanner":      str(_scanner),
        "_monitor":      str(_monitor),
        "_HTMLBuilder":  str(_HTMLBuilder),
        "_IMPORT_ERROR": _IMPORT_ERROR,
        "BASE_DIR":      str(BASE_DIR),
        "SCAN_PATH":     _CFG["scan_path"],
        "cwd":           os.getcwd(),
        "AI_MODEL":      _CFG["ai_model"],
        "AI_PROVIDER":   _CFG["ai_provider"],
    })


# ── /debug/db ────────────────────────────────────────────────────────
# WHY: proves DB has rows + shows real column names. Use before blaming
# HTMLBuilder for missing fields.
@debug_bp.get("/db")
def db():
    if _db is None:
        return jsonify({"error": "_db is None"}), 500
    try:
        cnt  = _db.execute("SELECT COUNT(*) AS c FROM detected_files", fetch=True)
        rows = _db.execute("SELECT * FROM detected_files LIMIT 5",     fetch=True)
        return jsonify({
            "total_rows": dict(cnt[0])["c"] if cnt else 0,
            "sample":     [dict(r) for r in (rows or [])],
        })
    except Exception as e:
        return jsonify({"error": str(e), "tb": traceback.format_exc()}), 500


# ── /debug/data ──────────────────────────────────────────────────────
# WHY: runs the EXACT function dashboard routes use. If /debug/db returns
# rows but this returns 0 → bug is in _get_data() or _monitor. This route
# is what caught the missing get_all_metrics() AttributeError.
@debug_bp.get("/data")
def data():
    try:
        files, metrics = _get_data()
        return jsonify({
            "files_count":   len(files),
            "files_sample":  files[:3],
            "system":        metrics.get("system", {}),
            "tokens_keys":   list(metrics.get("tokens",   {}).keys())[:5],
            "requests_keys": list(metrics.get("requests", {}).keys())[:5],
        })
    except Exception as e:
        return jsonify({"error": str(e), "tb": traceback.format_exc()}), 500


# ── /debug/rescan ────────────────────────────────────────────────────
# WHY: manually kick off a scan without visiting the /scan HTML page.
# Handy for cron/curl checks after deploy.
@debug_bp.get("/rescan")
def rescan():
    if _scanner is None:
        return jsonify({"error": "_scanner is None"}), 500
    try:
        target = _CFG["scan_path"] or str(BASE_DIR)
        files  = _scanner.scan_project(target)
        return jsonify({
            "path":    target,
            "scanned": len(files),
            "ai":      sum(1 for f in files if f.get("is_ai_agent")),
            "sc":      sum(1 for f in files if f.get("is_script")),
            "mn":      sum(1 for f in files if f.get("is_main_file")),
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ── /debug/monitor ───────────────────────────────────────────────────
# WHY: sanity-check the ResourceMonitor background thread. If tok_log is
# empty but monitoring=true → _sim() query returns nothing. If monitoring
# =false → thread died or never started.
@debug_bp.get("/monitor")
def monitor():
    if _monitor is None:
        return jsonify({"error": "_monitor is None"}), 500
    tok = getattr(_monitor, "_tok_log", {})
    req = getattr(_monitor, "_req_log", {})
    return jsonify({
        "monitoring":     getattr(_monitor, "monitoring", None),
        "tok_log_files":  list(tok.keys())[:10],
        "tok_log_counts": {k: len(v) for k, v in list(tok.items())[:10]},
        "req_log_files":  list(req.keys())[:10],
        "metrics_system": _monitor.metrics.get("system", {}),
        "tokens_agg":     dict(_monitor.metrics.get("tokens", {})),
    })


# ── /debug/ci ────────────────────────────────────────────────────────
# WHY: confirms your 3 CI agents (pre/during/post) have actually POSTed
# to /monitor/status. If empty → Grafana CI panels will show "No data"
# because Prometheus has no labelled samples yet.
@debug_bp.get("/ci")
def ci():
    def _labels(counter):
        try:
            return [
                {"agent": k[0], "stage": k[1],
                 "value": counter.labels(*k)._value.get()}
                for k in counter._metrics.keys()
            ]
        except Exception:
            return []
    return jsonify({
        "ci_agent_status":         _labels(ci_agent_status),
        "ci_agent_tokens_total":   _labels(ci_agent_tokens_total),
    })


# ── /debug/env ───────────────────────────────────────────────────────
# WHY: verify which env vars actually reached the container. Redacts
# anything with KEY/TOKEN/SECRET/PASSWORD in the name.
@debug_bp.get("/env")
def env():
    redact = ("KEY", "TOKEN", "SECRET", "PASSWORD")
    return jsonify({
        k: ("<redacted>" if any(r in k.upper() for r in redact) else v)
        for k, v in os.environ.items()
    })
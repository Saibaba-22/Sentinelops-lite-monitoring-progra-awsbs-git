"""
agent_monitor.py
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

# ══════════════════════════════════════════════════════════════════════════════
# FLASK APPLICATION
# ══════════════════════════════════════════════════════════════════════════════

BASE_DIR = Path(__file__).resolve().parent

application = Flask(
    __name__,
    template_folder=str(BASE_DIR / "templates"),
    static_folder=str(BASE_DIR / "static"),
)
application.secret_key = os.environ.get("FLASK_SECRET", "sentinelops-lite-key")

monitor_bp = Blueprint("monitor", __name__, url_prefix="/monitor")
scanner_bp = Blueprint("scanner", __name__, url_prefix="/scanner")

# ── LOAD CUSTOM METRICS ──────────────────────────────────────
from monitoring.metrics import (
    start_metrics_updater,
    update_metrics,
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

update_metrics()
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

        agent_last_run_timestamp_seconds.labels(
            agent_name=agent_name, stage=stage, cloud=cloud
        ).set(_time.time())

        for s in ("idle", "running", "approved", "rejected", "failed", "healthy"):
            agent_state.labels(
                agent_name=agent_name, stage=stage, cloud=cloud, state=s
            ).set(1 if s == ("healthy" if result == "success" else "failed") else 0)

        agent_tasks_total.labels(
            agent_name=agent_name, stage=stage, cloud=cloud, result=result
        ).inc()

        for d in ("none", "approved", "rejected", "failed", "healthy", "pass", "fail"):
            agent_last_decision.labels(
                agent_name=agent_name, stage=stage, cloud=cloud, decision=d
            ).set(1 if d == decision else 0)

        tokens            = payload.get("tokens", {})
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

        agent_api_calls_total.labels(
            agent_name=agent_name, stage=stage, cloud=cloud,
            provider=provider, model=model, status=result
        ).inc()

        exec_time = payload.get("execution_time", payload.get("duration", 0))
        if exec_time:
            exec_time = float(exec_time)
            agent_execution_time_seconds.labels(
                agent_name=agent_name, stage=stage, cloud=cloud
            ).set(exec_time)
            agent_execution_duration_seconds.labels(
                agent_name=agent_name, stage=stage, cloud=cloud
            ).observe(exec_time)

        api_keys = payload.get("api_keys", payload.get("api_key_count", 0))
        if api_keys:
            agent_api_key_count.labels(
                agent_name=agent_name, stage=stage, cloud=cloud, provider=provider
            ).set(int(api_keys))

        agent_model_info.labels(
            agent_name=agent_name, stage=stage, cloud=cloud
        ).info({"provider": provider, "model": model})

    except Exception:
        pass


# ══════════════════════════════════════════════════════════════════════════════
# PAGE WRAPPER — CSS is a plain string (NOT f-string) to avoid decimal errors
# ══════════════════════════════════════════════════════════════════════════════

_CSS = """
*,*::before,*::after{box-sizing:border-box;margin:0;padding:0}
:root{
  --bg:#f8fdf8;--card:#ffffff;--border:#d4e8d4;--accent:#2d8a4e;
  --accent2:#1a6834;--accent-light:#e8f5e8;--text:#1a2e1a;
  --text-secondary:#4a6a4a;
  --shadow:0 2px 12px rgba(45,138,78,0.08);
  --shadow-hover:0 4px 24px rgba(45,138,78,0.14);
  --radius:12px;
  --gradient:linear-gradient(135deg,#2d8a4e 0%,#1a6834 100%);
}
html{scroll-behavior:smooth}
body{
  font-family:'Segoe UI',system-ui,-apple-system,sans-serif;
  background:var(--bg);color:var(--text);line-height:1.6;min-height:100vh;
}
.header{
  background:var(--gradient);color:#fff;padding:20px 32px;
  position:sticky;top:0;z-index:100;
  box-shadow:0 4px 20px rgba(0,0,0,0.15);
}
.header-inner{
  max-width:1400px;margin:0 auto;display:flex;
  align-items:center;justify-content:space-between;flex-wrap:wrap;gap:12px;
}
.header h1{
  font-size:1.5rem;font-weight:700;letter-spacing:-0.5px;
  display:flex;align-items:center;gap:10px;
}
.header h1 .icon{font-size:1.8rem}
.nav-bar{
  background:#fff;border-bottom:2px solid var(--border);
  padding:8px 32px;position:sticky;top:68px;z-index:99;
  box-shadow:0 2px 8px rgba(0,0,0,0.05);
}
.nav-inner{
  max-width:1400px;margin:0 auto;
  display:flex;gap:8px;flex-wrap:wrap;align-items:center;
}
.nav-btn{
  display:inline-flex;align-items:center;gap:6px;
  padding:8px 18px;border-radius:8px;font-size:0.85rem;font-weight:600;
  color:var(--text-secondary);text-decoration:none;
  border:1px solid var(--border);background:#fff;
  transition:all 0.2s ease;cursor:pointer;
}
.nav-btn:hover{
  background:var(--accent-light);color:var(--accent);
  border-color:var(--accent);transform:translateY(-1px);
}
.nav-btn.active{background:var(--accent);color:#fff;border-color:var(--accent)}
.nav-btn.active:hover{background:var(--accent2)}
.container{max-width:1400px;margin:0 auto;padding:24px 20px 60px}
.card{
  background:var(--card);border:1px solid var(--border);
  border-radius:var(--radius);padding:24px;margin-bottom:16px;
  box-shadow:var(--shadow);transition:all 0.3s ease;
}
.card:hover{box-shadow:var(--shadow-hover)}
.stats-grid{
  display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));
  gap:16px;margin-bottom:32px;
}
.stat-card{
  background:var(--card);border:1px solid var(--border);
  border-radius:var(--radius);padding:20px 24px;
  box-shadow:var(--shadow);transition:all 0.3s ease;
  position:relative;overflow:hidden;
}
.stat-card::before{
  content:'';position:absolute;top:0;left:0;
  width:4px;height:100%;background:var(--gradient);
}
.stat-card:hover{transform:translateY(-2px);box-shadow:var(--shadow-hover)}
.stat-card .stat-icon{font-size:2rem;margin-bottom:8px}
.stat-card .stat-value{font-size:2rem;font-weight:800;color:var(--accent)}
.stat-card .stat-label{
  font-size:0.82rem;color:var(--text-secondary);
  font-weight:500;text-transform:uppercase;letter-spacing:0.5px;
}
.section{margin-bottom:36px}
.section-title{
  font-size:1.25rem;font-weight:700;color:var(--accent2);
  display:flex;align-items:center;gap:10px;
  margin-bottom:16px;padding-bottom:10px;
  border-bottom:2px solid var(--border);
}
.pipeline-card{border-left:4px solid var(--accent)}
.pipeline-status{
  display:inline-flex;align-items:center;gap:5px;
  padding:3px 12px;border-radius:20px;font-size:0.75rem;font-weight:600;
}
.pipeline-status.running{background:#d4edda;color:#155724}
.pipeline-status.detected{background:#fff3cd;color:#856404}
.config-file-tag{
  background:var(--accent-light);color:var(--accent2);
  padding:3px 10px;border-radius:6px;font-size:0.78rem;
  font-family:monospace;display:inline-block;margin:2px;
}
.char-grid{
  display:grid;
  grid-template-columns:repeat(auto-fill,minmax(280px,1fr));gap:12px;
}
.char-card{
  background:var(--accent-light);border:1px solid var(--border);
  border-radius:10px;padding:14px 18px;
  display:flex;align-items:flex-start;gap:12px;transition:all 0.25s ease;
}
.char-card:hover{transform:scale(1.02);background:#d8f0d8}
.char-icon{font-size:1.6rem;flex-shrink:0}
.char-info h4{font-weight:700;color:var(--accent2);font-size:0.92rem}
.char-info p{font-size:0.8rem;color:var(--text-secondary);margin-top:2px}
.file-tree-header{
  display:grid;grid-template-columns:30px 1fr 1fr 80px;gap:8px;
  padding:10px 12px;background:var(--accent);color:#fff;
  border-radius:var(--radius) var(--radius) 0 0;
  font-weight:700;font-size:0.82rem;
}
.file-row{
  display:grid;grid-template-columns:30px 1fr 1fr 80px;gap:8px;
  padding:8px 12px;border-bottom:1px solid #eef4ee;
  align-items:center;font-size:0.82rem;transition:background 0.15s;
}
.file-row:hover{background:var(--accent-light)}
.file-row.main-file{background:#e0f2e0;font-weight:600}
.agent-card{border-left:4px solid #2d8a4e}
.model-detail{
  background:#f0f8f0;border:1px solid var(--border);
  border-radius:10px;padding:18px;margin-top:12px;
}
.model-detail h4{color:var(--accent2);font-size:1rem;margin-bottom:12px}
.detail-grid{
  display:grid;
  grid-template-columns:repeat(auto-fit,minmax(240px,1fr));gap:12px;
}
.detail-box{
  background:#fff;border:1px solid var(--border);
  border-radius:8px;padding:14px;
}
.detail-box h5{
  font-size:0.78rem;text-transform:uppercase;letter-spacing:0.5px;
  color:var(--accent);margin-bottom:8px;
}
.detail-row{
  display:flex;justify-content:space-between;
  padding:3px 0;font-size:0.82rem;border-bottom:1px solid #f0f0f0;
}
.detail-row:last-child{border-bottom:none}
.detail-label{color:var(--text-secondary)}
.detail-value{font-weight:600;color:var(--text)}
.gauge-container{display:flex;align-items:center;gap:12px;margin:8px 0}
.gauge-bar{flex:1;height:10px;background:#e0e0e0;border-radius:5px;overflow:hidden}
.gauge-fill{
  height:100%;border-radius:5px;
  transition:width 1s ease;background:var(--gradient);
}
.gauge-fill.warn{background:linear-gradient(90deg,#f0ad4e,#d9534f)}
.gauge-text{
  font-size:0.78rem;font-weight:600;color:var(--accent);
  min-width:50px;text-align:right;
}
.tag{
  display:inline-flex;align-items:center;gap:4px;
  padding:3px 10px;border-radius:6px;
  font-size:0.75rem;font-weight:600;margin:2px;
}
.tag.provider{background:#d4edda;color:#155724}
.tag.model{background:#cce5ff;color:#004085}
.tag.pattern{background:#fff3cd;color:#856404}
.tag.env{background:#f8d7da;color:#721c24}
.json-box{
  background:#1a2e1a;color:#a8d8a8;padding:20px;
  border-radius:var(--radius);
  font-family:'Cascadia Code','Fira Code',monospace;
  font-size:0.82rem;overflow-x:auto;white-space:pre-wrap;
  word-break:break-word;max-height:600px;overflow-y:auto;line-height:1.5;
}
.json-key{color:#8be9fd}
.json-str{color:#50fa7b}
.json-num{color:#ffb86c}
.json-bool{color:#ff79c6}
.json-null{color:#6272a4}
.status-ok{color:#28a745;font-size:3rem;font-weight:800}
.status-card{text-align:center;padding:40px}
.status-icon{font-size:4rem;margin-bottom:16px}
.webhook-form{max-width:600px;margin:20px auto}
.webhook-form textarea{
  width:100%;height:120px;padding:12px;
  border:1px solid var(--border);border-radius:8px;
  font-family:monospace;font-size:0.85rem;resize:vertical;
}
.webhook-form button{
  margin-top:12px;padding:10px 24px;
  background:var(--gradient);color:#fff;border:none;
  border-radius:8px;font-weight:600;cursor:pointer;
  font-size:0.9rem;transition:all 0.2s;
}
.webhook-form button:hover{
  transform:translateY(-1px);box-shadow:var(--shadow-hover);
}
#webhookResult{margin-top:16px}
.tabs{
  display:flex;gap:4px;margin-bottom:20px;
  border-bottom:2px solid var(--border);
}
.tab{
  padding:10px 20px;cursor:pointer;font-weight:600;font-size:0.88rem;
  color:var(--text-secondary);border-bottom:3px solid transparent;
  transition:all 0.2s;margin-bottom:-2px;
}
.tab:hover{color:var(--accent)}
.tab.active{color:var(--accent);border-bottom-color:var(--accent)}
.tab-content{display:none}
.tab-content.active{display:block}
.spinner{
  width:48px;height:48px;border:4px solid var(--border);
  border-top-color:var(--accent);border-radius:50%;
  animation:spin 0.8s linear infinite;margin:0 auto 16px;
}
@keyframes spin{to{transform:rotate(360deg)}}
.empty-state{
  text-align:center;padding:40px;color:var(--text-secondary);
  background:var(--accent-light);border-radius:var(--radius);
}
.empty-state .empty-icon{font-size:3rem;margin-bottom:12px}
.page-footer{
  text-align:center;padding:20px;color:var(--text-secondary);
  font-size:0.78rem;border-top:1px solid var(--border);margin-top:40px;
}
.badge{
  display:inline-flex;align-items:center;gap:5px;padding:4px 14px;
  border-radius:20px;font-size:0.78rem;font-weight:600;
  background:rgba(255,255,255,0.2);color:#fff;
}
.refresh-btn{
  background:rgba(255,255,255,0.2);color:#fff;
  border:1px solid rgba(255,255,255,0.3);
  padding:8px 18px;border-radius:8px;cursor:pointer;
  font-weight:600;font-size:0.85rem;
  transition:all 0.2s;display:flex;align-items:center;gap:6px;
}
.refresh-btn:hover{background:rgba(255,255,255,0.35)}
@media(max-width:768px){
  .header{padding:12px 16px}
  .header h1{font-size:1.1rem}
  .nav-bar{padding:6px 16px}
  .nav-btn{padding:6px 12px;font-size:0.78rem}
  .stats-grid{grid-template-columns:repeat(2,1fr)}
  .char-grid{grid-template-columns:1fr}
  .detail-grid{grid-template-columns:1fr}
  .file-row{grid-template-columns:24px 1fr 80px}
  .file-row .f-purpose{display:none}
  .file-tree-header{grid-template-columns:24px 1fr 80px}
  .file-tree-header .fh-purpose{display:none}
}
"""


def wrap_page(title, body_content, active=""):
    """Wrap any page content with full HTML, nav bar, and consistent styling."""
    nav_items = [
        {"url": "/",                  "label": "🏠 Home",           "key": "home"},
        {"url": "/monitor/dashboard", "label": "📊 Dashboard",      "key": "dashboard"},
        {"url": "/scanner/scan",      "label": "🔍 Scan Results",   "key": "scan"},
        {"url": "/scanner/health",    "label": "💚 Health Check",   "key": "health"},
        {"url": "/monitor/status",    "label": "📡 Webhook Status", "key": "status"},
    ]

    nav_html = ""
    for item in nav_items:
        active_cls = "active" if item["key"] == active else ""
        nav_html += f'<a href="{item["url"]}" class="nav-btn {active_cls}">{item["label"]}</a>'

    now_time = datetime.datetime.now().strftime("%H:%M:%S")
    now_full = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S UTC")

    return (
        "<!DOCTYPE html>\n"
        '<html lang="en">\n'
        "<head>\n"
        '<meta charset="UTF-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1.0">\n'
        f"<title>{title} \u2014 SentinelOps</title>\n"
        "<style>\n"
        + _CSS +
        "\n</style>\n"
        "</head>\n"
        "<body>\n"
        '<div class="header">\n'
        '  <div class="header-inner">\n'
        '    <h1><span class="icon">\U0001f6e1\ufe0f</span> SentinelOps Monitor</h1>\n'
        '    <div style="display:flex;align-items:center;gap:8px">\n'
        f'      <span class="badge">\U0001f550 {now_time}</span>\n'
        "    </div>\n"
        "  </div>\n"
        "</div>\n"
        '<div class="nav-bar">\n'
        f'  <div class="nav-inner">{nav_html}</div>\n'
        "</div>\n"
        '<div class="container">\n'
        f"{body_content}\n"
        "</div>\n"
        '<div class="page-footer">\n'
        f"  \U0001f6e1\ufe0f SentinelOps Lite \u2014 AI Agent &amp; Pipeline Monitor"
        f" &nbsp;|&nbsp; Scanned at {now_full}\n"
        "</div>\n"
        "</body>\n"
        "</html>"
    )


# ══════════════════════════════════════════════════════════════════════════════
# PIPELINE DETECTOR
# ══════════════════════════════════════════════════════════════════════════════

PIPELINE_SIGNATURES = {
    "GitHub Actions": {
        "files": [".github/workflows/*.yml", ".github/workflows/*.yaml"],
        "env_vars": ["GITHUB_ACTIONS", "GITHUB_WORKFLOW", "GITHUB_RUN_ID"],
        "description": (
            "GitHub's built-in CI/CD platform that automates build, test, and deploy "
            "workflows directly from your GitHub repository using YAML workflow files."
        ),
    },
    "Azure DevOps": {
        "files": ["azure-pipelines.yml", "azure-pipelines.yaml", ".azure-pipelines/*.yml"],
        "env_vars": ["TF_BUILD", "BUILD_BUILDID", "SYSTEM_TEAMFOUNDATIONCOLLECTIONURI"],
        "description": (
            "Microsoft's enterprise CI/CD service offering pipelines, boards, repos, "
            "and artifacts — tightly integrated with Azure cloud services."
        ),
    },
    "Jenkins": {
        "files": ["Jenkinsfile", "jenkins/*.groovy"],
        "env_vars": ["JENKINS_URL", "BUILD_ID", "JENKINS_HOME"],
        "description": (
            "Open-source automation server that enables developers to build, test, "
            "and deploy software with hundreds of plugins for CI/CD pipelines."
        ),
    },
    "GitLab CI": {
        "files": [".gitlab-ci.yml"],
        "env_vars": ["GITLAB_CI", "CI_PIPELINE_ID"],
        "description": (
            "GitLab's integrated CI/CD that runs pipelines defined in "
            ".gitlab-ci.yml for automated testing and deployment."
        ),
    },
    "CircleCI": {
        "files": [".circleci/config.yml"],
        "env_vars": ["CIRCLECI", "CIRCLE_BUILD_NUM"],
        "description": (
            "Cloud-native CI/CD platform that automates the software development "
            "process using intelligent caching and parallelism."
        ),
    },
    "Travis CI": {
        "files": [".travis.yml"],
        "env_vars": ["TRAVIS", "TRAVIS_BUILD_ID"],
        "description": (
            "Hosted continuous integration service used to build and test "
            "software projects hosted on GitHub and Bitbucket."
        ),
    },
    "Bitbucket Pipelines": {
        "files": ["bitbucket-pipelines.yml"],
        "env_vars": ["BITBUCKET_PIPELINE_UUID", "BITBUCKET_BUILD_NUMBER"],
        "description": (
            "Atlassian's integrated CI/CD for Bitbucket Cloud, "
            "running builds in Docker containers."
        ),
    },
    "AWS CodePipeline": {
        "files": ["buildspec.yml", "buildspec.yaml", "appspec.yml"],
        "env_vars": ["CODEBUILD_BUILD_ID", "CODEBUILD_SOURCE_VERSION"],
        "description": (
            "AWS fully managed continuous delivery service for fast and "
            "reliable application and infrastructure updates."
        ),
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
            results.append({
                "platform":        name,
                "pipeline_name":   _extract_pipeline_name(name, found_files),
                "description":     sig["description"],
                "config_files":    [str(Path(f).relative_to(BASE_DIR)) for f in found_files],
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
                m = re.search(r"^name:\s*(.+)", content, re.MULTILINE)
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
# AI PROVIDER FULL METRICS DATABASE
# ══════════════════════════════════════════════════════════════════════════════

AI_PROVIDER_FULL_METRICS = {
    "OpenAI": {
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
                "input_cost_per_1k": 0.00015, "output_cost_per_1k": 0.0006,
                "rate_limits": {"rpm": 500, "rpd": 10000, "tpm": 200000, "tpd": 2000000},
                "features": ["vision", "function_calling", "json_mode", "streaming"],
                "training_cutoff": "Oct 2023", "latency": "fast",
            },
            "gpt-4-turbo": {
                "full_name": "GPT-4 Turbo", "type": "Chat",
                "context_window": 128000, "max_output_tokens": 4096,
                "input_cost_per_1k": 0.01, "output_cost_per_1k": 0.03,
                "rate_limits": {"rpm": 500, "rpd": 10000, "tpm": 30000, "tpd": 1000000},
                "features": ["vision", "function_calling", "json_mode", "streaming"],
                "training_cutoff": "Apr 2024", "latency": "medium",
            },
            "gpt-4": {
                "full_name": "GPT-4", "type": "Chat",
                "context_window": 8192, "max_output_tokens": 8192,
                "input_cost_per_1k": 0.03, "output_cost_per_1k": 0.06,
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
                "input_cost_per_1k": 0.015, "output_cost_per_1k": 0.06,
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
            },
        },
    },

    "Anthropic (Claude)": {
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
            },
        },
    },

    "Google Gemini": {
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
                "input_cost_per_1k": 0.000075, "output_cost_per_1k": 0.0003,
                "rate_limits": {"rpm": 1000, "rpd": 100000, "tpm": 4000000, "tpd": 0},
                "features": ["vision", "audio", "function_calling", "streaming"],
                "training_cutoff": "Nov 2023", "latency": "fast",
            },
            "gemini-2.0-flash": {
                "full_name": "Gemini 2.0 Flash", "type": "Chat / Next Gen",
                "context_window": 1048576, "max_output_tokens": 8192,
                "input_cost_per_1k": 0.0001, "output_cost_per_1k": 0.0004,
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
            },
        },
    },

    "Azure OpenAI": {
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
                "input_cost_per_1k": 0.03, "output_cost_per_1k": 0.06,
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
            },
        },
    },

    "Hugging Face": {
        "imports":  ["transformers", "huggingface_hub", "HfApi",
                     "AutoModelForCausalLM", "pipeline"],
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
            },
        },
    },

    "Cohere": {
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
            },
        },
    },

    "Groq": {
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
            },
        },
    },

    "LangChain": {
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
    {"trait": "Autonomy",                  "icon": "\U0001f916", "desc": "Operates independently without constant human intervention"},
    {"trait": "Perception",                "icon": "\U0001f441\ufe0f", "desc": "Senses environment through APIs, data feeds, or sensors"},
    {"trait": "Reasoning",                 "icon": "\U0001f9e0", "desc": "Processes information and makes decisions using LLM or logic"},
    {"trait": "Action",                    "icon": "\u26a1", "desc": "Executes tasks — API calls, code generation, deployments"},
    {"trait": "Memory",                    "icon": "\U0001f4be", "desc": "Retains context across interactions (short/long-term)"},
    {"trait": "Tool Use",                  "icon": "\U0001f527", "desc": "Invokes external tools, functions, or plugins"},
    {"trait": "Planning",                  "icon": "\U0001f4cb", "desc": "Breaks complex goals into ordered sub-tasks"},
    {"trait": "Reactivity",                "icon": "\U0001f504", "desc": "Responds dynamically to changes in environment"},
    {"trait": "Communication",             "icon": "\U0001f4ac", "desc": "Interacts with humans or other agents via messages"},
    {"trait": "Goal-Oriented",             "icon": "\U0001f3af", "desc": "Driven by explicit objectives or reward signals"},
    {"trait": "Learning",                  "icon": "\U0001f4c8", "desc": "Improves behaviour over time from feedback or data"},
    {"trait": "Multi-Agent Collaboration", "icon": "\U0001f91d", "desc": "Coordinates with other agents to solve tasks"},
]


# ══════════════════════════════════════════════════════════════════════════════
# AI AGENT SCANNER
# ══════════════════════════════════════════════════════════════════════════════

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

    # ── Extract imports ────────────────────────────────────────────────────
    try:
        tree = ast.parse(content)
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    results["imports_found"].append(alias.name)
            elif isinstance(node, ast.ImportFrom) and node.module:
                results["imports_found"].append(node.module)
                for alias in node.names:
                    results["imports_found"].append(f"{node.module}.{alias.name}")
    except SyntaxError:
        for groups in re.findall(
            r"^\s*(?:from\s+([\w.]+)\s+import|import\s+([\w.]+))",
            content, re.MULTILINE,
        ):
            for g in groups:
                if g:
                    results["imports_found"].append(g)

    # ── Extract configured params ──────────────────────────────────────────
    configured = {}
    for key, pattern in [
        ("max_tokens",        r"max_tokens\s*[=:]\s*(\d+)"),
        ("temperature",       r"temperature\s*[=:]\s*([\d.]+)"),
        ("top_p",             r"top_p\s*[=:]\s*([\d.]+)"),
        ("timeout",           r"timeout\s*[=:]\s*(\d+)"),
        ("max_retries",       r"max_retries\s*[=:]\s*(\d+)"),
        ("frequency_penalty", r"frequency_penalty\s*[=:]\s*([\d.]+)"),
        ("presence_penalty",  r"presence_penalty\s*[=:]\s*([\d.]+)"),
    ]:
        m = re.findall(pattern, content)
        if m:
            configured[key] = (
                int(m[0]) if key in ("max_tokens", "timeout", "max_retries")
                else float(m[0])
            )

    # ── Raw model strings ──────────────────────────────────────────────────
    raw_models = re.findall(r'model\s*[=:]\s*["\']([^"\']+)["\']', content)
    results["raw_model_strings"] = list(set(raw_models))

    # ── Match providers then models ────────────────────────────────────────
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
            max_tok  = configured.get("max_tokens", model_metrics["max_output_tokens"])
            est_hourly = (
                rl.get("rpm", 0) * 60
                * (model_metrics["context_window"] / 1000 * in_cost
                   + max_tok / 1000 * out_cost)
            )

            results["models_found"].append({
                "provider":        provider_name,
                "model":           model_key,
                "full_name":       model_metrics["full_name"],
                "model_type":      model_metrics["type"],
                "website":         provider_info["website"],
                "training_cutoff": model_metrics["training_cutoff"],
                "latency_class":   model_metrics["latency"],
                "features":        model_metrics["features"],
                "token_limits": {
                    "context_window":        model_metrics["context_window"],
                    "max_output_tokens":     model_metrics["max_output_tokens"],
                    "configured_max_tokens": configured.get("max_tokens", "Default"),
                    "temperature":           configured.get("temperature", "Default"),
                    "top_p":                 configured.get("top_p", "Default"),
                    "frequency_penalty":     configured.get("frequency_penalty", "Default"),
                    "presence_penalty":      configured.get("presence_penalty", "Default"),
                },
                "rate_limits": {
                    "requests_per_minute": rl.get("rpm", "Unknown"),
                    "requests_per_day":    rl.get("rpd", "Unknown"),
                    "tokens_per_minute":   rl.get("tpm", "Unknown"),
                    "tokens_per_day":      rl.get("tpd", "Unknown"),
                    "est_per_hour":        rl.get("rpm", 0) * 60,
                },
                "costs": {
                    "input_per_1k":   f"${in_cost:.6f}",
                    "output_per_1k":  f"${out_cost:.6f}",
                    "per_1m_input":   f"${in_cost * 1000:.4f}",
                    "per_1m_output":  f"${out_cost * 1000:.4f}",
                    "est_max_hourly": f"${est_hourly:.4f}",
                },
                "found_in_code": {
                    "raw_model_strings": results["raw_model_strings"],
                    "env_vars_used":     [ek for ek in provider_info["env_keys"] if ek in content],
                    "configured_params": configured,
                },
            })

        for tm in re.findall(r"max_tokens\s*[=:]\s*(\d+)", content):
            results["token_configs"].append({"provider": provider_name, "max_tokens_configured": int(tm)})
        for t in re.findall(r"temperature\s*[=:]\s*([\d.]+)", content):
            results["token_configs"].append({"provider": provider_name, "temperature": float(t)})

    # ── Agent patterns ─────────────────────────────────────────────────────
    for pattern, label in [
        (r"class\s+(\w*[Aa]gent\w*)\s*[\(:]",            "Class-based Agent"),
        (r"Agent\s*\(",                                    "Agent instantiation"),
        (r"CrewAI|Crew\s*\(",                             "CrewAI Agent"),
        (r"AssistantAgent|UserProxyAgent",                 "AutoGen Agent"),
        (r"AgentExecutor",                                 "LangChain Agent"),
        (r"create_react_agent|create_openai_tools_agent",  "LangChain ReAct Agent"),
        (r"tool\s*=|tools\s*=\s*\[",                      "Tool-using Agent"),
        (r"memory\s*=|Memory\s*\(",                        "Memory-enabled Agent"),
        (r"vector_store|VectorStore|Chroma|Pinecone|FAISS","RAG Agent"),
    ]:
        if re.search(pattern, content):
            results["agent_patterns"].append(label)

    return results


def _infer_purpose(filepath, model_dict, scan_result):
    fp       = filepath.lower()
    patterns = scan_result.get("agent_patterns", [])
    mtype    = model_dict.get("model_type", "").lower()

    if "monitor"   in fp:                         return "Monitoring, health-check analysis, or alerting"
    if "chat"      in fp:                         return "Conversational AI / chatbot functionality"
    if "agent"     in fp:                         return "Autonomous AI agent task execution"
    if "embed"     in mtype:                      return "Text embedding for semantic search or RAG"
    if "rag"       in " ".join(patterns).lower(): return "Retrieval-Augmented Generation (RAG)"
    if "tool"      in " ".join(patterns).lower(): return "Tool-augmented reasoning and function calling"
    if any(p in patterns for p in ["CrewAI Agent", "AutoGen Agent"]):
        return "Multi-agent collaboration and task orchestration"
    if "reasoning" in mtype:                      return "Complex multi-step reasoning"
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


def scan_project():
    scan_time = datetime.datetime.now(datetime.timezone.utc).isoformat()
    skip_dirs = {
        ".git", "__pycache__", "node_modules", ".venv", "venv", "env",
        ".tox", ".mypy_cache", ".pytest_cache", "dist", "build", ".eggs",
    }

    file_tree = []
    py_files  = []

    for root, dirs, files in os.walk(BASE_DIR):
        dirs[:] = [d for d in dirs if d not in skip_dirs and not d.endswith(".egg-info")]
        rel_root = Path(root).relative_to(BASE_DIR)
        for fname in sorted(files):
            rel_path = str(rel_root / fname) if str(rel_root) != "." else fname
            ext      = Path(fname).suffix.lower()
            purpose  = FILE_PURPOSES.get(fname, "")
            if not purpose:
                purpose = {
                    ".py":   "Python module",            ".html": "HTML template",
                    ".css":  "Stylesheet",               ".js":   "JavaScript module",
                    ".yml":  "YAML configuration",       ".yaml": "YAML configuration",
                    ".json": "JSON data / configuration", ".md":   "Markdown documentation",
                    ".txt":  "Text file",                ".sh":   "Shell script",
                    ".sql":  "SQL database script",      ".toml": "TOML configuration",
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

    pipelines  = detect_pipelines()
    active_env = {}
    for prov_info in AI_PROVIDER_FULL_METRICS.values():
        for ek in prov_info["env_keys"]:
            val = os.environ.get(ek)
            if val:
                masked = val[:4] + "****" + val[-4:] if len(val) > 8 else "****"
                active_env[ek] = masked

    return {
        "scan_time":               scan_time,
        "project_root":            str(BASE_DIR),
        "pipelines":               pipelines,
        "ai_agent_characteristics": AI_AGENT_CHARACTERISTICS,
        "file_tree":               file_tree,
        "agents":                  agents,
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


# ══════════════════════════════════════════════════════════════════════════════
# HELPERS
# ══════════════════════════════════════════════════════════════════════════════

def _stat_card(icon, value, label):
    return (
        f'<div class="stat-card">'
        f'<div class="stat-icon">{icon}</div>'
        f'<div class="stat-value">{value}</div>'
        f'<div class="stat-label">{label}</div>'
        f'</div>'
    )


def _fmt(val):
    if val is None or val in ("Unknown", "Default"):
        return val or "\u2014"
    if isinstance(val, float):
        return f"{val:,.0f}"
    if isinstance(val, int):
        return f"{val:,}"
    return str(val)


def _colorize_json(json_str):
    s = json_str.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    s = re.sub(r'"([^"]+)"(\s*:)', r'<span class="json-key">"\1"</span>\2', s)
    s = re.sub(r':\s*"([^"]*)"',   r': <span class="json-str">"\1"</span>', s)
    s = re.sub(r':\s*(\d+\.?\d*)', r': <span class="json-num">\1</span>', s)
    s = re.sub(r':\s*(true|false)', r': <span class="json-bool">\1</span>', s)
    s = re.sub(r':\s*(null)',        r': <span class="json-null">\1</span>', s)
    return s


def _render_model_details(model_details):
    """Full metrics card for every detected model."""
    if not model_details:
        return (
            '<div style="background:#fff8e1;border:1px solid #ffe082;'
            'border-radius:8px;padding:14px;margin-top:10px">'
            '<strong>\u26a0\ufe0f Provider detected but no specific model string matched.</strong><br>'
            '<span style="font-size:0.83rem;color:var(--text-secondary)">'
            'Model may be set via environment variable or config file.'
            '</span></div>'
        )

    html = ""
    for md in model_details:
        tl   = md.get("token_limits",  {})
        rl   = md.get("rate_limits",   {})
        cost = md.get("costs",         {})
        fic  = md.get("found_in_code", {})
        cfg  = fic.get("configured_params", {})

        latency_color = {
            "ultra_fast": "#28a745", "very_fast": "#5cb85c",
            "fast":       "#2d8a4e", "medium":    "#f0ad4e",
            "slow":       "#d9534f", "very_slow": "#c9302c",
        }.get(md.get("latency_class", ""), "#6c757d")

        features_html = "".join(
            f'<span class="tag model">\u2705 {f}</span>'
            for f in md.get("features", [])
        )

        env_tags = "".join(
            f'<span class="tag env">\U0001f510 {e}</span>'
            for e in fic.get("env_vars_used", [])
        ) or '<span style="font-size:0.78rem;color:var(--text-secondary)">None found</span>'

        ctx = tl.get("context_window", 0) or 0
        rpm = rl.get("requests_per_minute", 0) or 0

        html += (
            '<div class="model-detail" style="margin-bottom:16px">'

            # header
            '<div style="display:flex;justify-content:space-between;align-items:center;'
            'flex-wrap:wrap;gap:8px;margin-bottom:14px;padding-bottom:12px;'
            'border-bottom:1px solid var(--border)">'
            '<div>'
            f'<span style="font-size:1.05rem;font-weight:800;color:var(--accent2)">'
            f'\U0001f9e0 {md.get("full_name", md.get("model","Unknown"))}</span>'
            f'<span style="font-size:0.8rem;color:var(--text-secondary);margin-left:8px">'
            f'({md.get("provider","")})</span>'
            '</div>'
            '<div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap">'
            f'<span style="background:{latency_color};color:#fff;padding:3px 12px;'
            f'border-radius:12px;font-size:0.75rem;font-weight:700">'
            f'\u26a1 {md.get("latency_class","").replace("_"," ").title()}</span>'
            f'<span class="tag provider">\U0001f4c2 {md.get("model_type","")}</span>'
            f'<a href="{md.get("website","#")}" target="_blank" '
            f'style="font-size:0.75rem;color:var(--accent);text-decoration:none">'
            f'\U0001f310 Docs \u2197</a>'
            '</div></div>'

            # purpose bar
            f'<div style="margin-bottom:12px;padding:8px 12px;background:var(--accent-light);'
            f'border-radius:8px;font-size:0.85rem;color:var(--accent2)">'
            f'\U0001f3af <strong>Purpose:</strong> {md.get("why_used","AI-powered text generation")}'
            f' &nbsp;|&nbsp; \U0001f4c4 <strong>File:</strong> {md.get("where_used","")}'
            f' &nbsp;|&nbsp; \U0001f5d3\ufe0f <strong>Cutoff:</strong> {md.get("training_cutoff","")}'
            f'</div>'

            '<div class="detail-grid">'

            # token limits
            '<div class="detail-box"><h5>\U0001f39f\ufe0f Token Limits</h5>'
            f'<div class="detail-row"><span class="detail-label">Context Window</span>'
            f'<span class="detail-value">{_fmt(tl.get("context_window"))} tokens</span></div>'
            f'<div class="detail-row"><span class="detail-label">Max Output</span>'
            f'<span class="detail-value">{_fmt(tl.get("max_output_tokens"))} tokens</span></div>'
            f'<div class="detail-row"><span class="detail-label">Configured max_tokens</span>'
            f'<span class="detail-value">{_fmt(tl.get("configured_max_tokens"))}</span></div>'
            f'<div class="detail-row"><span class="detail-label">Temperature</span>'
            f'<span class="detail-value">{tl.get("temperature","Default")}</span></div>'
            f'<div class="detail-row"><span class="detail-label">Top-P</span>'
            f'<span class="detail-value">{tl.get("top_p","Default")}</span></div>'
            f'<div class="detail-row"><span class="detail-label">Freq Penalty</span>'
            f'<span class="detail-value">{tl.get("frequency_penalty","Default")}</span></div>'
            f'<div class="detail-row"><span class="detail-label">Presence Penalty</span>'
            f'<span class="detail-value">{tl.get("presence_penalty","Default")}</span></div>'
            '<div style="margin-top:10px">'
            '<div style="font-size:0.7rem;color:var(--text-secondary);margin-bottom:4px">'
            'Context window scale</div>'
            '<div class="gauge-bar" style="height:8px">'
            f'<div class="gauge-fill" style="width:{min(100, ctx // 20000)}%"></div>'
            '</div></div></div>'

            # rate limits
            '<div class="detail-box"><h5>\u23f1\ufe0f Rate Limits</h5>'
            f'<div class="detail-row"><span class="detail-label">Requests / Minute</span>'
            f'<span class="detail-value">{_fmt(rl.get("requests_per_minute"))}</span></div>'
            f'<div class="detail-row"><span class="detail-label">Requests / Hour (est.)</span>'
            f'<span class="detail-value">{_fmt(rl.get("est_per_hour"))}</span></div>'
            f'<div class="detail-row"><span class="detail-label">Requests / Day</span>'
            f'<span class="detail-value">{_fmt(rl.get("requests_per_day"))}</span></div>'
            f'<div class="detail-row"><span class="detail-label">Tokens / Minute</span>'
            f'<span class="detail-value">{_fmt(rl.get("tokens_per_minute"))}</span></div>'
            f'<div class="detail-row"><span class="detail-label">Tokens / Day</span>'
            f'<span class="detail-value">{_fmt(rl.get("tokens_per_day"))}</span></div>'
            '<div style="margin-top:10px"><div class="gauge-container">'
            '<div class="gauge-bar">'
            f'<div class="gauge-fill" style="width:{min(100, rpm // 40)}%"></div>'
            '</div>'
            f'<span class="gauge-text">{rpm} rpm</span>'
            '</div></div></div>'

            # costs
            '<div class="detail-box"><h5>\U0001f4b0 Cost</h5>'
            f'<div class="detail-row"><span class="detail-label">Input / 1K tokens</span>'
            f'<span class="detail-value">{cost.get("input_per_1k","\u2014")}</span></div>'
            f'<div class="detail-row"><span class="detail-label">Output / 1K tokens</span>'
            f'<span class="detail-value">{cost.get("output_per_1k","\u2014")}</span></div>'
            f'<div class="detail-row"><span class="detail-label">Per 1M input tokens</span>'
            f'<span class="detail-value">{cost.get("per_1m_input","\u2014")}</span></div>'
            f'<div class="detail-row"><span class="detail-label">Per 1M output tokens</span>'
            f'<span class="detail-value">{cost.get("per_1m_output","\u2014")}</span></div>'
            f'<div class="detail-row"><span class="detail-label">Est. Max Hourly</span>'
            f'<span class="detail-value" style="color:#d9534f;font-weight:800">'
            f'{cost.get("est_max_hourly","\u2014")}</span></div>'
            '<div style="font-size:0.7rem;color:var(--text-secondary);margin-top:6px">'
            '* At full RPM x max context tokens</div></div>'

            # found in code
            '<div class="detail-box"><h5>\U0001f50d Found In Code</h5>'
            f'<div class="detail-row"><span class="detail-label">Model strings</span>'
            f'<span class="detail-value" style="font-size:0.78rem">'
            f'{", ".join(fic.get("raw_model_strings",[])) or "\u2014"}</span></div>'
            f'<div class="detail-row"><span class="detail-label">Configured params</span>'
            f'<span class="detail-value" style="font-size:0.78rem">'
            f'{", ".join([f"{k}={v}" for k,v in cfg.items()]) or "None (defaults)"}</span></div>'
            '<div style="margin-top:10px">'
            '<div style="font-size:0.72rem;font-weight:700;text-transform:uppercase;'
            'color:var(--accent);margin-bottom:6px">API Keys referenced</div>'
            f'{env_tags}</div></div>'

            '</div>'  # /detail-grid

            # features
            '<div style="margin-top:12px;padding-top:10px;border-top:1px solid var(--border)">'
            '<span style="font-size:0.75rem;font-weight:700;color:var(--accent2);'
            'text-transform:uppercase;letter-spacing:0.5px;margin-right:8px">'
            '\u2728 Features:</span>'
            f'{features_html or "<span style=\\"font-size:0.8rem;color:var(--text-secondary)\\">\u2014</span>"}'
            '</div>'

            '</div>'  # /model-detail
        )

    return html


def _webhook_form():
    return """
    <div class="card">
      <div class="webhook-form">
        <label style="font-weight:600;color:var(--accent2);display:block;margin-bottom:8px">
          JSON Payload:
        </label>
        <textarea id="webhookPayload">{
  "pipeline": "my-ci-pipeline",
  "status": "success",
  "build_number": "42",
  "branch": "main"
}</textarea>
        <button onclick="sendWebhook()">Send POST Request</button>
        <div id="webhookResult"></div>
      </div>
    </div>
    <script>
    async function sendWebhook(){
      var payload   = document.getElementById('webhookPayload').value;
      var resultDiv = document.getElementById('webhookResult');
      resultDiv.innerHTML = '<p style="color:var(--accent)">Sending...</p>';
      try{
        var parsed = JSON.parse(payload);
        var r = await fetch('/monitor/status',{
          method:'POST',
          headers:{'Content-Type':'application/json'},
          body:JSON.stringify(parsed)
        });
        var text = await r.text();
        resultDiv.innerHTML = '<div class="card" style="margin-top:12px;border-left:4px solid #28a745">'
          + '<h4 style="color:#28a745;margin-bottom:8px">Response (Status ' + r.status + ')</h4>'
          + '<div class="json-box">' + text + '</div></div>';
      }catch(e){
        resultDiv.innerHTML = '<div class="card" style="margin-top:12px;border-left:4px solid #dc3545">'
          + '<h4 style="color:#dc3545">Error</h4><p>' + e.message + '</p></div>';
      }
    }
    </script>"""


# ══════════════════════════════════════════════════════════════════════════════
# ROUTE: /monitor/status
# ══════════════════════════════════════════════════════════════════════════════

def handle_monitor_status():
    now = datetime.datetime.now(datetime.timezone.utc).isoformat()

    if request.method == "POST":
        data        = request.get_json(silent=True) or {}
        result_json = json.dumps({"status": "ok", "received": data, "timestamp": now}, indent=2)
        body = (
            '<div class="section">'
            '<div class="section-title">Webhook Status — POST Received</div>'
            '<div class="card status-card">'
            '<div class="status-icon">\u2705</div>'
            '<div class="status-ok">POST Received Successfully</div>'
            f'<p style="color:var(--text-secondary);margin-top:8px">Payload processed at {now}</p>'
            '</div>'
            '<div class="card">'
            '<h3 style="margin-bottom:12px;color:var(--accent2)">Response</h3>'
            f'<div class="json-box">{_colorize_json(result_json)}</div>'
            '</div></div>'
            '<div class="section">'
            '<div class="section-title">Send Another Webhook</div>'
            f'{_webhook_form()}</div>'
        )
        return wrap_page("Webhook Status", body, active="status")

    body = (
        '<div class="section">'
        '<div class="section-title">Webhook Status Endpoint</div>'
        '<div class="card status-card">'
        '<div class="status-icon">\U0001f4e1</div>'
        '<p style="font-size:1.2rem;font-weight:700;color:var(--accent)">Monitor Webhook Ready</p>'
        '<p style="color:var(--text-secondary);margin-top:8px">'
        'Accepts <strong>GET</strong> (this page) and <strong>POST</strong> (webhook data).</p>'
        f'<p style="color:var(--text-secondary);margin-top:4px">Current time: {now}</p>'
        '</div></div>'
        '<div class="section">'
        '<div class="section-title">Test Webhook (Send POST)</div>'
        f'{_webhook_form()}</div>'
        '<div class="section">'
        '<div class="section-title">cURL Example</div>'
        '<div class="card">'
        f'<div class="json-box">curl -X POST {request.url} \\\n'
        '  -H "Content-Type: application/json" \\\n'
        '  -d \'{"pipeline":"ci-build","status":"success","build":"42"}\''
        '</div></div></div>'
    )
    return wrap_page("Webhook Status", body, active="status")


# ══════════════════════════════════════════════════════════════════════════════
# ROUTE: /scanner/scan
# ══════════════════════════════════════════════════════════════════════════════

@scanner_bp.get("/scan")
def scanner_scan():
    data   = scan_project()
    pretty = json.dumps(data, indent=2, default=str)
    s      = data["summary"]

    stats_html = "".join([
        _stat_card("\U0001f680", s["pipelines_detected"],     "Pipelines"),
        _stat_card("\U0001f916", s["ai_agents_found"],        "AI Agents"),
        _stat_card("\U0001f9e0", s["models_used"],            "Models"),
        _stat_card("\U0001f4e6", s["total_files"],             "Total Files"),
        _stat_card("\U0001f40d", s["python_files"],            "Python Files"),
        _stat_card("\U0001f511", len(data["active_env_keys"]), "API Keys"),
    ])

    # ── Pipelines ──────────────────────────────────────────────────────────
    pip_html = ""
    if data["pipelines"]:
        for p in data["pipelines"]:
            status  = (
                '<span class="pipeline-status running">Running Here</span>'
                if p["is_running_here"]
                else '<span class="pipeline-status detected">Detected</span>'
            )
            configs = "".join(
                f'<span class="config-file-tag">{f}</span>'
                for f in p["config_files"]
            )
            pip_html += (
                '<div class="card pipeline-card">'
                '<div style="display:flex;justify-content:space-between;align-items:center;'
                'flex-wrap:wrap;gap:8px;margin-bottom:8px">'
                f'<span style="font-weight:700;font-size:1.05rem;color:var(--accent2)">'
                f'{p["platform"]} \u2014 {p["pipeline_name"]}</span>'
                f'{status}</div>'
                f'<p style="color:var(--text-secondary);font-size:0.88rem;margin-bottom:8px">'
                f'{p["description"]}</p>'
                f'<div>{configs}</div>'
                '</div>'
            )
    else:
        pip_html = (
            '<div class="empty-state">'
            '<div class="empty-icon">\U0001f50d</div>'
            '<p>No pipelines detected</p></div>'
        )

    # ── Agents ─────────────────────────────────────────────────────────────
    agents_html = ""
    if data["agents"]:
        for agent in data["agents"]:
            provs = "".join(f'<span class="tag provider">{p}</span>' for p in agent["providers"])
            pats  = "".join(f'<span class="tag pattern">{p}</span>'  for p in agent["patterns"])
            envs  = "".join(f'<span class="tag env">{e}</span>'      for e in agent["env_vars"])

            models_html = _render_model_details(agent.get("model_details", []))

            agents_html += (
                '<div class="card agent-card">'
                f'<div style="font-weight:700;font-size:1.05rem;color:var(--accent2);margin-bottom:12px">'
                f'{agent["script"]}</div>'
                f'<div style="margin-bottom:8px">{provs}</div>'
                f'<div style="margin-bottom:8px">{pats}</div>'
                f'<div style="margin-bottom:8px">{envs}</div>'
                f'{models_html}'
                '</div>'
            )
    else:
        agents_html = (
            '<div class="empty-state">'
            '<div class="empty-icon">\U0001f916</div>'
            '<p>No AI agents detected</p></div>'
        )

    # ── Files ──────────────────────────────────────────────────────────────
    file_icon_map = {
        ".py": "\U0001f40d", ".html": "\U0001f310", ".css": "\U0001f3a8",
        ".js": "\u26a1",     ".yml": "\U0001f4cb",  ".yaml": "\U0001f4cb",
        ".json": "\U0001f4e6",".md": "\U0001f4dd",  ".txt": "\U0001f4c4",
        ".sh": "\U0001f4bb", ".sql": "\U0001f5c4\ufe0f",
    }
    files_html = (
        '<div class="file-tree-header">'
        '<span></span><span>File</span>'
        '<span class="fh-purpose">Purpose</span>'
        '<span style="text-align:right">Size</span>'
        '</div>'
    )
    for f in data["file_tree"]:
        icon     = file_icon_map.get(f["extension"], "\U0001f4c4")
        cls      = "file-row main-file" if f["is_main"] else "file-row"
        star     = "\u2b50 " if f["is_main"] else ""
        size_str = (
            f'{f["size"]}B'               if f["size"] < 1024
            else f'{f["size"] / 1024:.1f}KB' if f["size"] < 1048576
            else f'{f["size"] / 1048576:.1f}MB'
        )
        files_html += (
            f'<div class="{cls}">'
            f'<span style="text-align:center">{icon}</span>'
            f'<span>{star}{f["path"]}</span>'
            f'<span class="f-purpose" style="color:var(--text-secondary);font-size:0.78rem">'
            f'{f["purpose"]}</span>'
            f'<span style="text-align:right;font-size:0.75rem;color:var(--text-secondary)">'
            f'{size_str}</span>'
            '</div>'
        )

    body = (
        f'<div class="stats-grid">{stats_html}</div>'

        '<div class="section">'
        '<div class="section-title">Detected Pipelines</div>'
        f'{pip_html}</div>'

        f'<div class="section">'
        f'<div class="section-title">AI Agents ({s["ai_agents_found"]})</div>'
        f'{agents_html}</div>'

        f'<div class="section">'
        f'<div class="section-title">Project Files ({s["total_files"]})</div>'
        '<div class="card" style="padding:0;overflow:hidden">'
        f'{files_html}</div></div>'

        '<div class="section">'
        '<div class="section-title">Raw JSON Data</div>'
        '<div class="card">'
        f'<div class="json-box">{_colorize_json(pretty)}</div>'
        '</div></div>'
    )

    return wrap_page("Scan Results", body, active="scan")


# ══════════════════════════════════════════════════════════════════════════════
# ROUTE: /scanner/health
# ══════════════════════════════════════════════════════════════════════════════

@scanner_bp.get("/health")
def scanner_health():
    now  = datetime.datetime.now(datetime.timezone.utc).isoformat()
    data = scan_project()
    s    = data["summary"]

    checks = [
        ("Module Loaded",        "agent_monitor.py",              True),
        ("Flask Application",    "Running",                        True),
        ("Scanner Blueprint",    "Registered",                     True),
        ("Monitor Blueprint",    "Registered",                     True),
        ("Python Files Scanned", str(s["python_files"]),           True),
        ("Pipelines Detected",   str(s["pipelines_detected"]),     True),
        ("AI Agents Found",      str(s["ai_agents_found"]),        True),
        ("API Keys Active",      str(len(data["active_env_keys"])),
         len(data["active_env_keys"]) > 0),
    ]

    checks_html = ""
    for label, value, ok in checks:
        icon = "\u2705" if ok else "\u26a0\ufe0f"
        checks_html += (
            '<div class="detail-row">'
            f'<span class="detail-label">{icon} {label}</span>'
            f'<span class="detail-value">{value}</span>'
            '</div>'
        )

    health_json = json.dumps({
        "status":    "healthy",
        "module":    "agent_monitor",
        "timestamp": now,
        "summary":   s,
    }, indent=2)

    body = (
        '<div class="card status-card">'
        '<div class="status-icon">\U0001f49a</div>'
        '<div class="status-ok">HEALTHY</div>'
        f'<p style="color:var(--text-secondary);margin-top:8px">All systems operational \u2014 {now}</p>'
        '</div>'

        f'<div class="stats-grid" style="margin-top:24px">'
        f'{_stat_card(chr(0x1F680), s["pipelines_detected"], "Pipelines")}'
        f'{_stat_card(chr(0x1F916), s["ai_agents_found"],    "Agents")}'
        f'{_stat_card(chr(0x1F4E6), s["total_files"],         "Files")}'
        f'{_stat_card(chr(0x1F40D), s["python_files"],         "Python")}'
        f'</div>'

        '<div class="section">'
        '<div class="section-title">Health Checks</div>'
        '<div class="card">'
        f'<div class="detail-box" style="border:none;padding:0">{checks_html}</div>'
        '</div></div>'

        '<div class="section">'
        '<div class="section-title">Response JSON</div>'
        '<div class="card">'
        f'<div class="json-box">{_colorize_json(health_json)}</div>'
        '</div></div>'
    )

    return wrap_page("Health Check", body, active="health")


# ══════════════════════════════════════════════════════════════════════════════
# ROUTE: /monitor/dashboard
# ══════════════════════════════════════════════════════════════════════════════

@monitor_bp.get("/dashboard")
def monitor_dashboard():
    data = scan_project()
    s    = data["summary"]

    stats_html = "".join([
        _stat_card("\U0001f680", s["pipelines_detected"],     "Pipelines"),
        _stat_card("\U0001f916", s["ai_agents_found"],        "AI Agents"),
        _stat_card("\U0001f9e0", s["models_used"],            "Models"),
        _stat_card("\U0001f4e6", s["total_files"],             "Total Files"),
        _stat_card("\U0001f40d", s["python_files"],            "Python Files"),
        _stat_card("\U0001f511", len(data["active_env_keys"]), "API Keys"),
    ])

    # ── Pipelines tab ──────────────────────────────────────────────────────
    pip_cards = ""
    if data["pipelines"]:
        for p in data["pipelines"]:
            status   = (
                '<span class="pipeline-status running">Running Here</span>'
                if p["is_running_here"]
                else '<span class="pipeline-status detected">Detected</span>'
            )
            configs  = "".join(
                f'<span class="config-file-tag">{f}</span>'
                for f in p["config_files"]
            )
            env_tags = "".join(
                f'<span class="tag env">{v}</span>'
                for v in p["active_env_vars"]
            )
            pip_cards += (
                '<div class="card pipeline-card">'
                '<div style="display:flex;justify-content:space-between;align-items:center;'
                'flex-wrap:wrap;gap:8px;margin-bottom:8px">'
                f'<span style="font-weight:700;font-size:1.05rem;color:var(--accent2)">'
                f'{p["platform"]} \u2014 {p["pipeline_name"]}</span>'
                f'{status}</div>'
                f'<p style="color:var(--text-secondary);font-size:0.88rem;margin-bottom:10px">'
                f'{p["description"]}</p>'
                f'<div style="margin-bottom:6px">{configs}</div>'
                f'<div>{env_tags}</div>'
                '</div>'
            )
    else:
        pip_cards = (
            '<div class="empty-state">'
            '<div class="empty-icon">\U0001f50d</div>'
            '<p style="font-weight:700">No CI/CD pipelines detected</p>'
            '<p style="margin-top:4px;font-size:0.85rem">Add a workflow file to get started</p>'
            '</div>'
        )

    # ── Agents tab ─────────────────────────────────────────────────────────
    agents_cards = ""
    if data["agents"]:
        for idx, agent in enumerate(data["agents"]):
            provs = "".join(f'<span class="tag provider">{p}</span>' for p in agent["providers"])
            pats  = "".join(f'<span class="tag pattern">{p}</span>'  for p in agent["patterns"])
            envs  = "".join(f'<span class="tag env">{e}</span>'      for e in agent["env_vars"])

            models_html = _render_model_details(agent.get("model_details", []))

            agents_cards += (
                '<div class="card agent-card">'
                '<div style="display:flex;justify-content:space-between;align-items:center;'
                'flex-wrap:wrap;gap:8px;margin-bottom:12px">'
                f'<span style="font-weight:700;font-size:1.05rem;color:var(--accent2)">'
                f'{agent["script"]}</span>'
                f'<span style="font-size:0.8rem;color:var(--text-secondary)">Agent #{idx+1}</span>'
                '</div>'
                f'<div style="margin-bottom:8px">{provs}</div>'
                + (f'<div style="margin-bottom:8px">{pats}</div>' if pats else "")
                + (f'<div style="margin-bottom:8px">{envs}</div>' if envs else "")
                + models_html
                + '</div>'
            )
    else:
        agents_cards = (
            '<div class="empty-state">'
            '<div class="empty-icon">\U0001f916</div>'
            '<p style="font-weight:700">No AI agents detected</p>'
            '</div>'
        )

    # ── Characteristics tab ────────────────────────────────────────────────
    chars_html = "".join(
        f'<div class="char-card">'
        f'<div class="char-icon">{c["icon"]}</div>'
        f'<div class="char-info"><h4>{c["trait"]}</h4><p>{c["desc"]}</p></div>'
        f'</div>'
        for c in AI_AGENT_CHARACTERISTICS
    )

    # ── Files tab ──────────────────────────────────────────────────────────
    file_icon_map = {
        ".py": "\U0001f40d", ".html": "\U0001f310", ".css": "\U0001f3a8",
        ".js": "\u26a1",     ".yml": "\U0001f4cb",  ".yaml": "\U0001f4cb",
        ".json": "\U0001f4e6",".md": "\U0001f4dd",  ".txt": "\U0001f4c4",
        ".sh": "\U0001f4bb",
    }
    files_rows = ""
    for f in data["file_tree"]:
        icon = file_icon_map.get(f["extension"], "\U0001f4c4")
        cls  = "file-row main-file" if f["is_main"] else "file-row"
        star = "\u2b50 " if f["is_main"] else ""
        sz   = (
            f'{f["size"]}B'               if f["size"] < 1024
            else f'{f["size"] / 1024:.1f}KB' if f["size"] < 1048576
            else f'{f["size"] / 1048576:.1f}MB'
        )
        files_rows += (
            f'<div class="{cls}">'
            f'<span style="text-align:center">{icon}</span>'
            f'<span>{star}{f["path"]}</span>'
            f'<span class="f-purpose" style="color:var(--text-secondary);font-size:0.78rem">'
            f'{f["purpose"]}</span>'
            f'<span style="text-align:right;font-size:0.75rem;color:var(--text-secondary)">'
            f'{sz}</span>'
            '</div>'
        )

    tab_js = (
        "function switchTab(name){"
        "document.querySelectorAll('.tab').forEach(function(t){"
        "t.classList.toggle('active',t.dataset.tab===name)});"
        "document.querySelectorAll('.tab-content').forEach(function(c){"
        "c.classList.toggle('active',c.id==='tab-'+name)});}"
    )

    body = (
        f'<div class="stats-grid">{stats_html}</div>'

        '<div class="tabs">'
        '<div class="tab active" onclick="switchTab(\'pipelines\')" data-tab="pipelines">Pipelines</div>'
        '<div class="tab" onclick="switchTab(\'agents\')" data-tab="agents">AI Agents</div>'
        '<div class="tab" onclick="switchTab(\'chars\')" data-tab="chars">Agent Traits</div>'
        '<div class="tab" onclick="switchTab(\'files\')" data-tab="files">Files</div>'
        '</div>'

        '<div class="tab-content active" id="tab-pipelines">'
        '<div class="section">'
        '<div class="section-title">Detected CI/CD Pipelines</div>'
        f'{pip_cards}</div></div>'

        '<div class="tab-content" id="tab-agents">'
        '<div class="section">'
        f'<div class="section-title">AI Agents Found ({s["ai_agents_found"]})</div>'
        f'{agents_cards}</div></div>'

        '<div class="tab-content" id="tab-chars">'
        '<div class="section">'
        '<div class="section-title">AI Agent Characteristics</div>'
        '<p style="color:var(--text-secondary);margin-bottom:16px;font-size:0.88rem">'
        'An AI agent is identified by exhibiting several of these core traits.</p>'
        f'<div class="char-grid">{chars_html}</div>'
        '</div></div>'

        '<div class="tab-content" id="tab-files">'
        '<div class="section">'
        f'<div class="section-title">Project File Structure ({s["total_files"]} files)</div>'
        '<div class="card" style="padding:0;overflow:hidden">'
        '<div class="file-tree-header">'
        '<span></span><span>File</span>'
        '<span class="fh-purpose">Purpose</span>'
        '<span style="text-align:right">Size</span>'
        '</div>'
        f'{files_rows}</div></div></div>'

        f'<script>{tab_js}</script>'
    )

    return wrap_page("Dashboard", body, active="dashboard")
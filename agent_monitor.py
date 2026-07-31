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

add this in app.py or application.py main file 
from flask import render_template, Response, request

@application.route("/monitor/status", methods=["GET", "POST"])
def monitor_status():
#    CI / monitoring webhook.
    Delegates entirely to agent_monitor.handle_monitor_status().
    """
#    from agent_monitor import handle_monitor_status
#    return handle_monitor_status()

# IMPORTS
# ══════════════════════════════════════════════════════════════════════════════

import os
import re
import sys
import json
import glob
import datetime
import ast
from pathlib import Path
from flask import Flask, Blueprint, request, Response

# FLASK APPLICATION

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
# This import registers all custom Prometheus metrics (app_*, system_*, agent_*)
# in the default registry so generate_latest() exposes them at /metrics.
from monitoring.metrics import start_metrics_updater, update_metrics

# Run initial metric collection immediately
update_metrics()

# Start background thread to refresh process/system metrics every 5 seconds
start_metrics_updater(interval=5)
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
.stat-card::before{{content:'';position:absolute;top:0;left:0;width:4px;height:100%;background:var(--gradient)}}
.stat-card:hover{{transform:translateY(-2px);box-shadow:var(--shadow-hover)}}
.stat-card .stat-icon{{font-size:2rem;margin-bottom:8px}}
.stat-card .stat-value{{font-size:2rem;font-weight:800;color:var(--accent)}}
.stat-card .stat-label{{font-size:.82rem;color:var(--text-secondary);font-weight:500;text-transform:uppercase;letter-spacing:.5px}}

/* ═══ SECTION ═══ */
.section{{margin-bottom:36px}}
.section-title{{
  font-size:1.25rem;font-weight:700;color:var(--accent2);
  display:flex;align-items:center;gap:10px;margin-bottom:16px;
  padding-bottom:10px;border-bottom:2px solid var(--border);
}}

/* ═══ PIPELINE CARD ═══ */
.pipeline-card{{border-left:4px solid var(--accent)}}
.pipeline-status{{display:inline-flex;align-items:center;gap:5px;padding:3px 12px;border-radius:20px;font-size:.75rem;font-weight:600}}
.pipeline-status.running{{background:#d4edda;color:#155724}}
.pipeline-status.detected{{background:#fff3cd;color:#856404}}
.config-file-tag{{background:var(--accent-light);color:var(--accent2);padding:3px 10px;border-radius:6px;font-size:.78rem;font-family:monospace;display:inline-block;margin:2px}}

/* ═══ CHARS ═══ */
.char-grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(280px,1fr));gap:12px}}
.char-card{{
  background:var(--accent-light);border:1px solid var(--border);
  border-radius:10px;padding:14px 18px;display:flex;align-items:flex-start;gap:12px;transition:all .25s ease;
}}
.char-card:hover{{transform:scale(1.02);background:#d8f0d8}}
.char-icon{{font-size:1.6rem;flex-shrink:0}}
.char-info h4{{font-weight:700;color:var(--accent2);font-size:.92rem}}
.char-info p{{font-size:.8rem;color:var(--text-secondary);margin-top:2px}}

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

/* ═══ GAUGE ═══ */
.gauge-container{{display:flex;align-items:center;gap:12px;margin:8px 0}}
.gauge-bar{{flex:1;height:10px;background:#e0e0e0;border-radius:5px;overflow:hidden}}
.gauge-fill{{height:100%;border-radius:5px;transition:width 1s ease;background:var(--gradient)}}
.gauge-fill.warn{{background:linear-gradient(90deg,#f0ad4e,#d9534f)}}
.gauge-text{{font-size:.78rem;font-weight:600;color:var(--accent);min-width:50px;text-align:right}}

/* ═══ TAGS ═══ */
.tag{{display:inline-flex;align-items:center;gap:4px;padding:3px 10px;border-radius:6px;font-size:.75rem;font-weight:600;margin:2px}}
.tag.provider{{background:#d4edda;color:#155724}}
.tag.model{{background:#cce5ff;color:#004085}}
.tag.pattern{{background:#fff3cd;color:#856404}}
.tag.env{{background:#f8d7da;color:#721c24}}

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
.status-ok{{color:#28a745;font-size:3rem;font-weight:800}}
.status-card{{text-align:center;padding:40px}}
.status-icon{{font-size:4rem;margin-bottom:16px}}
.webhook-form{{max-width:600px;margin:20px auto}}
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
.tab:hover{{color:var(--accent)}}
.tab.active{{color:var(--accent);border-bottom-color:var(--accent)}}
.tab-content{{display:none}}
.tab-content.active{{display:block}}

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
<div class="header">
  <div class="header-inner">
    <h1><span class="icon">🛡️</span> SentinelOps Monitor</h1>
    <div style="display:flex;align-items:center;gap:8px">
      <span class="badge">🕐 {datetime.datetime.now().strftime('%H:%M:%S')}</span>
    </div>
  </div>
</div>

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
                "platform": name,
                "pipeline_name": pipeline_display_name,
                "description": sig["description"],
                "config_files": [str(Path(f).relative_to(BASE_DIR)) for f in found_files],
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
# AI AGENT DETECTOR
# ══════════════════════════════════════════════════════════════════════════════

AI_PROVIDER_PATTERNS = {
    "OpenAI": {
        "imports": ["openai", "OpenAI"],
        "env_keys": ["OPENAI_API_KEY", "OPENAI_KEY"],
        "models": ["gpt-4", "gpt-4o", "gpt-4o-mini", "gpt-4-turbo", "gpt-3.5-turbo",
                    "o1-preview", "o1-mini", "o3-mini", "text-embedding-ada", "text-embedding-3"],
        "token_limits": {
            "gpt-4": {"input": 8192, "output": 8192},
            "gpt-4o": {"input": 128000, "output": 16384},
            "gpt-4o-mini": {"input": 128000, "output": 16384},
            "gpt-4-turbo": {"input": 128000, "output": 4096},
            "gpt-3.5-turbo": {"input": 16385, "output": 4096},
            "o1-preview": {"input": 128000, "output": 32768},
            "o1-mini": {"input": 128000, "output": 65536},
            "o3-mini": {"input": 200000, "output": 100000},
        },
        "rate_limits": {
            "gpt-4": {"rpm": 500, "rpd": 10000},
            "gpt-4o": {"rpm": 500, "rpd": 10000},
            "gpt-4o-mini": {"rpm": 500, "rpd": 10000},
            "gpt-4-turbo": {"rpm": 500, "rpd": 10000},
            "gpt-3.5-turbo": {"rpm": 3500, "rpd": 10000},
            "o1-preview": {"rpm": 500, "rpd": 10000},
            "o1-mini": {"rpm": 500, "rpd": 10000},
            "o3-mini": {"rpm": 500, "rpd": 10000},
        },
    },
    "Anthropic (Claude)": {
        "imports": ["anthropic", "Anthropic"],
        "env_keys": ["ANTHROPIC_API_KEY"],
        "models": ["claude-3-opus", "claude-3-sonnet", "claude-3-haiku",
                    "claude-3.5-sonnet", "claude-3.5-haiku", "claude-2"],
        "token_limits": {
            "claude-3-opus": {"input": 200000, "output": 4096},
            "claude-3-sonnet": {"input": 200000, "output": 4096},
            "claude-3-haiku": {"input": 200000, "output": 4096},
            "claude-3.5-sonnet": {"input": 200000, "output": 8192},
            "claude-3.5-haiku": {"input": 200000, "output": 8192},
        },
        "rate_limits": {
            "claude-3-opus": {"rpm": 1000, "rpd": 50000},
            "claude-3-sonnet": {"rpm": 1000, "rpd": 50000},
            "claude-3-haiku": {"rpm": 4000, "rpd": 200000},
            "claude-3.5-sonnet": {"rpm": 1000, "rpd": 50000},
            "claude-3.5-haiku": {"rpm": 4000, "rpd": 200000},
        },
    },
    "Google Gemini": {
        "imports": ["google.generativeai", "genai", "vertexai"],
        "env_keys": ["GOOGLE_API_KEY", "GEMINI_API_KEY", "GOOGLE_APPLICATION_CREDENTIALS"],
        "models": ["gemini-pro", "gemini-1.5-pro", "gemini-1.5-flash", "gemini-ultra", "gemini-2.0-flash"],
        "token_limits": {
            "gemini-pro": {"input": 32760, "output": 8192},
            "gemini-1.5-pro": {"input": 2097152, "output": 8192},
            "gemini-1.5-flash": {"input": 1048576, "output": 8192},
            "gemini-2.0-flash": {"input": 1048576, "output": 8192},
        },
        "rate_limits": {
            "gemini-pro": {"rpm": 60, "rpd": 1500},
            "gemini-1.5-pro": {"rpm": 360, "rpd": 50000},
            "gemini-1.5-flash": {"rpm": 1000, "rpd": 100000},
            "gemini-2.0-flash": {"rpm": 1000, "rpd": 100000},
        },
    },
    "Azure OpenAI": {
        "imports": ["openai.AzureOpenAI", "AzureOpenAI"],
        "env_keys": ["AZURE_OPENAI_API_KEY", "AZURE_OPENAI_ENDPOINT"],
        "models": ["gpt-4", "gpt-4o", "gpt-35-turbo"],
        "token_limits": {"gpt-4": {"input": 8192, "output": 8192}, "gpt-4o": {"input": 128000, "output": 16384}},
        "rate_limits": {"gpt-4": {"rpm": 600, "rpd": 14400}, "gpt-4o": {"rpm": 600, "rpd": 14400}},
    },
    "Hugging Face": {
        "imports": ["transformers", "huggingface_hub", "HfApi"],
        "env_keys": ["HF_TOKEN", "HUGGINGFACE_TOKEN"],
        "models": ["llama", "mistral", "falcon", "bloom", "starcoder"],
        "token_limits": {}, "rate_limits": {},
    },
    "Cohere": {
        "imports": ["cohere"],
        "env_keys": ["COHERE_API_KEY", "CO_API_KEY"],
        "models": ["command", "command-r", "command-r-plus"],
        "token_limits": {"command-r-plus": {"input": 128000, "output": 4096}, "command-r": {"input": 128000, "output": 4096}},
        "rate_limits": {"command-r-plus": {"rpm": 1000, "rpd": 50000}, "command-r": {"rpm": 1000, "rpd": 50000}},
    },
    "Groq": {
        "imports": ["groq"],
        "env_keys": ["GROQ_API_KEY"],
        "models": ["llama3", "mixtral", "gemma"],
        "token_limits": {"llama3-70b": {"input": 8192, "output": 8192}, "mixtral-8x7b": {"input": 32768, "output": 32768}},
        "rate_limits": {"llama3-70b": {"rpm": 30, "rpd": 14400}, "mixtral-8x7b": {"rpm": 30, "rpd": 14400}},
    },
    "LangChain": {
        "imports": ["langchain", "langchain_openai", "langchain_anthropic", "langchain_google_genai", "langchain_community"],
        "env_keys": ["LANGCHAIN_API_KEY", "LANGCHAIN_TRACING_V2"],
        "models": [], "token_limits": {}, "rate_limits": {},
    },
    "CrewAI": {"imports": ["crewai"], "env_keys": [], "models": [], "token_limits": {}, "rate_limits": {}},
    "AutoGen": {"imports": ["autogen", "pyautogen"], "env_keys": [], "models": [], "token_limits": {}, "rate_limits": {}},
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


def _scan_python_file(filepath):
    results = {"providers_found": [], "models_found": [], "imports_found": [],
               "env_vars_used": [], "token_configs": [], "agent_patterns": []}
    try:
        with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
            content = f.read()
    except Exception:
        return results

    try:
        tree = ast.parse(content)
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    results["imports_found"].append(alias.name)
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    results["imports_found"].append(node.module)
                    for alias in node.names:
                        results["imports_found"].append(f"{node.module}.{alias.name}")
    except SyntaxError:
        import_patterns = re.findall(r'^\s*(?:from\s+([\w.]+)\s+import|import\s+([\w.]+))', content, re.MULTILINE)
        for groups in import_patterns:
            for g in groups:
                if g:
                    results["imports_found"].append(g)

    for provider_name, provider_info in AI_PROVIDER_PATTERNS.items():
        provider_match = False
        for imp in provider_info["imports"]:
            if any(imp in found_imp for found_imp in results["imports_found"]):
                provider_match = True
                break
        for env_key in provider_info["env_keys"]:
            if env_key in content:
                results["env_vars_used"].append(env_key)
                provider_match = True
        if not provider_match:
            continue

        results["providers_found"].append(provider_name)
        for model in provider_info.get("models", []):
            if model in content:
                results["models_found"].append({
                    "provider": provider_name, "model": model,
                    "token_limits": provider_info.get("token_limits", {}).get(model, {}),
                    "rate_limits": provider_info.get("rate_limits", {}).get(model, {}),
                })
        token_matches = re.findall(r'max_tokens\s*[=:]\s*(\d+)', content)
        for tm in token_matches:
            results["token_configs"].append({"provider": provider_name, "max_tokens_configured": int(tm)})
        temp_matches = re.findall(r'temperature\s*[=:]\s*([\d.]+)', content)
        for t in temp_matches:
            results["token_configs"].append({"provider": provider_name, "temperature": float(t)})

    agent_class_patterns = [
        (r'class\s+(\w*[Aa]gent\w*)\s*[\(:]', "Class-based Agent"),
        (r'Agent\s*\(', "Agent instantiation"),
        (r'CrewAI|Crew\s*\(', "CrewAI Agent"),
        (r'AssistantAgent|UserProxyAgent', "AutoGen Agent"),
        (r'AgentExecutor', "LangChain Agent"),
        (r'create_react_agent|create_openai_tools_agent', "LangChain ReAct Agent"),
        (r'tool\s*=|tools\s*=\s*\[', "Tool-using Agent"),
    ]
    for pattern, label in agent_class_patterns:
        if re.search(pattern, content):
            results["agent_patterns"].append(label)
    return results


def _infer_purpose(filepath, model, scan_result):
    fp = filepath.lower()
    patterns = scan_result.get("agent_patterns", [])
    if "monitor" in fp: return "Monitoring, health-check analysis, or alerting"
    if "chat" in fp: return "Conversational AI / chatbot functionality"
    if "agent" in fp: return "Autonomous AI agent task execution"
    if "embed" in model.lower(): return "Text embedding for semantic search or RAG"
    if "tool" in " ".join(patterns).lower(): return "Tool-augmented reasoning and function calling"
    if any(p in patterns for p in ["CrewAI Agent", "AutoGen Agent"]): return "Multi-agent collaboration and task orchestration"
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


def scan_project():
    scan_time = datetime.datetime.now(datetime.timezone.utc).isoformat()
    skip_dirs = {".git", "__pycache__", "node_modules", ".venv", "venv", "env",
                 ".tox", ".mypy_cache", ".pytest_cache", "dist", "build", ".eggs"}

    file_tree = []
    py_files = []

    for root, dirs, files in os.walk(BASE_DIR):
        dirs[:] = [d for d in dirs if d not in skip_dirs and not d.endswith(".egg-info")]
        rel_root = Path(root).relative_to(BASE_DIR)
        for fname in sorted(files):
            rel_path = str(rel_root / fname) if str(rel_root) != "." else fname
            ext = Path(fname).suffix.lower()
            purpose = FILE_PURPOSES.get(fname, "")
            if not purpose:
                ext_map = {".py": "Python module", ".html": "HTML template", ".css": "Stylesheet",
                           ".js": "JavaScript module", ".yml": "YAML configuration", ".yaml": "YAML configuration",
                           ".json": "JSON data / configuration", ".md": "Markdown documentation",
                           ".txt": "Text file", ".sh": "Shell script", ".sql": "SQL database script",
                           ".toml": "TOML configuration"}
                purpose = ext_map.get(ext, "Project file")
            is_main = fname in ("app.py", "application.py", "manage.py", "wsgi.py", "agent_monitor.py", "main.py")
            file_tree.append({"path": rel_path, "name": fname, "purpose": purpose,
                              "is_main": is_main, "extension": ext,
                              "size": os.path.getsize(os.path.join(root, fname))})
            if ext == ".py":
                py_files.append(os.path.join(root, fname))

    file_tree.sort(key=lambda x: (not x["is_main"], x["path"]))

    agents = []
    all_providers = set()
    all_models = []

    for pyf in py_files:
        scan_result = _scan_python_file(pyf)
        if scan_result["providers_found"] or scan_result["agent_patterns"]:
            rel = str(Path(pyf).relative_to(BASE_DIR))
            model_details = []
            for m in scan_result["models_found"]:
                tl = m.get("token_limits", {})
                rl = m.get("rate_limits", {})
                configured_tokens = None
                configured_temp = None
                for tc in scan_result["token_configs"]:
                    if tc["provider"] == m["provider"]:
                        if "max_tokens_configured" in tc: configured_tokens = tc["max_tokens_configured"]
                        if "temperature" in tc: configured_temp = tc["temperature"]
                model_details.append({
                    "model_name": m["model"], "provider": m["provider"],
                    "where_used": rel, "why_used": _infer_purpose(rel, m["model"], scan_result),
                    "tokens": {"max_input": tl.get("input", "Unknown"), "max_output": tl.get("output", "Unknown"),
                               "configured_max_tokens": configured_tokens or "Default", "temperature": configured_temp},
                    "rate_limits_hourly": {"requests_per_minute": rl.get("rpm", "Unknown"),
                                           "est_per_hour": rl.get("rpm", 0) * 60 if rl.get("rpm") else "Unknown",
                                           "window": "Rolling 60-second window"},
                    "rate_limits_daily": {"requests_per_day": rl.get("rpd", "Unknown"), "window": "UTC 00:00 – 23:59"},
                })
            agents.append({
                "script": rel, "providers": list(set(scan_result["providers_found"])),
                "models": scan_result["models_found"], "patterns": list(set(scan_result["agent_patterns"])),
                "env_vars": list(set(scan_result["env_vars_used"])), "token_configs": scan_result["token_configs"],
                "model_details": model_details,
            })
            all_providers.update(scan_result["providers_found"])
            all_models.extend(scan_result["models_found"])

    pipelines = detect_pipelines()

    active_env = {}
    for prov_info in AI_PROVIDER_PATTERNS.values():
        for ek in prov_info["env_keys"]:
            val = os.environ.get(ek)
            if val:
                masked = val[:4] + "****" + val[-4:] if len(val) > 8 else "****"
                active_env[ek] = masked

    return {
        "scan_time": scan_time, "project_root": str(BASE_DIR), "pipelines": pipelines,
        "ai_agent_characteristics": AI_AGENT_CHARACTERISTICS, "file_tree": file_tree,
        "agents": agents,
        "summary": {"total_files": len(file_tree), "python_files": len(py_files),
                     "ai_agents_found": len(agents), "providers": list(all_providers),
                     "models_used": len(all_models), "pipelines_detected": len(pipelines)},
        "active_env_keys": active_env,
    }


# ══════════════════════════════════════════════════════════════════════════════
# ROUTE: /monitor/status  (GET + POST)
# ══════════════════════════════════════════════════════════════════════════════

def handle_monitor_status():
    """Handle both GET and POST for /monitor/status."""
    now = datetime.datetime.now(datetime.timezone.utc).isoformat()

    if request.method == "POST":
        data = request.get_json(silent=True) or {}
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

    # GET request
    body = f"""
    <div class="section">
      <div class="section-title">📡 Webhook Status Endpoint</div>
      <div class="card status-card">
        <div class="status-icon">📡</div>
        <p style="font-size:1.2rem;font-weight:700;color:var(--accent)">Monitor Webhook Ready</p>
        <p style="color:var(--text-secondary);margin-top:8px">
          This endpoint accepts both <strong>GET</strong> (this page) and <strong>POST</strong> (webhook data).
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
        <div class="json-box">curl -X POST {request.url}  \\
  -H "Content-Type: application/json" \\
  -d '{{"pipeline":"ci-build","status":"success","build":"42"}}'</div>
      </div>
    </div>"""
    return wrap_page("Webhook Status", body, active="status")


def _webhook_form():
    return """
    <div class="card">
      <div class="webhook-form">
        <label style="font-weight:600;color:var(--accent2);display:block;margin-bottom:8px">
          📝 JSON Payload:
        </label>
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
      const payload = document.getElementById('webhookPayload').value;
      const resultDiv = document.getElementById('webhookResult');
      resultDiv.innerHTML = '<p style="color:var(--accent)">⏳ Sending...</p>';
      try{
        let parsed = JSON.parse(payload);
        const r = await fetch('/monitor/status', {
          method: 'POST',
          headers: {'Content-Type': 'application/json'},
          body: JSON.stringify(parsed)
        });
        const text = await r.text();
        resultDiv.innerHTML = '<div class="card" style="margin-top:12px;border-left:4px solid #28a745"><h4 style="color:#28a745;margin-bottom:8px">✅ Response (Status ' + r.status + ')</h4><div class="json-box">' + text + '</div></div>';
      }catch(e){
        resultDiv.innerHTML = '<div class="card" style="margin-top:12px;border-left:4px solid #dc3545"><h4 style="color:#dc3545">❌ Error</h4><p>' + e.message + '</p></div>';
      }
    }
    </script>"""


def _colorize_json(json_str):
    """Simple JSON syntax highlighting for HTML."""
    s = json_str.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    s = re.sub(r'"([^"]+)"(\s*:)', r'<span class="json-key">"\1"</span>\2', s)
    s = re.sub(r':\s*"([^"]*)"', r': <span class="json-str">"\1"</span>', s)
    s = re.sub(r':\s*(\d+\.?\d*)', r': <span class="json-num">\1</span>', s)
    s = re.sub(r':\s*(true|false)', r': <span class="json-bool">\1</span>', s)
    s = re.sub(r':\s*(null)', r': <span class="json-null">\1</span>', s)
    return s


# ══════════════════════════════════════════════════════════════════════════════
# ROUTE: /scanner/scan  (HTML)
# ══════════════════════════════════════════════════════════════════════════════

@scanner_bp.get("/scan")
def scanner_scan():
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
              <div>{configs}</div>
            </div>"""
    else:
        pip_html = '<div class="empty-state"><div class="empty-icon">🔍</div><p>No pipelines detected</p></div>'

    # Agents section
    agents_html = ""
    if data["agents"]:
        for agent in data["agents"]:
            provs = "".join([f'<span class="tag provider">🏢 {p}</span>' for p in agent["providers"]])
            pats = "".join([f'<span class="tag pattern">⚙️ {p}</span>' for p in agent["patterns"]])
            envs = "".join([f'<span class="tag env">🔐 {e}</span>' for e in agent["env_vars"]])

            models_html = ""
            for md in agent.get("model_details", []):
                toks = md.get("tokens", {})
                rh = md.get("rate_limits_hourly", {})
                rd = md.get("rate_limits_daily", {})
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
                      <h5>🎟️ Tokens</h5>
                      <div class="detail-row"><span class="detail-label">Max Input</span><span class="detail-value">{_fmt(toks.get('max_input'))}</span></div>
                      <div class="detail-row"><span class="detail-label">Max Output</span><span class="detail-value">{_fmt(toks.get('max_output'))}</span></div>
                      <div class="detail-row"><span class="detail-label">Configured</span><span class="detail-value">{_fmt(toks.get('configured_max_tokens'))}</span></div>
                      <div class="detail-row"><span class="detail-label">Temperature</span><span class="detail-value">{toks.get('temperature') or 'Default'}</span></div>
                    </div>
                    <div class="detail-box">
                      <h5>⏱️ Hourly Limits</h5>
                      <div class="detail-row"><span class="detail-label">RPM</span><span class="detail-value">{_fmt(rh.get('requests_per_minute'))}</span></div>
                      <div class="detail-row"><span class="detail-label">Per Hour</span><span class="detail-value">{_fmt(rh.get('est_per_hour'))}</span></div>
                      <div class="detail-row"><span class="detail-label">Window</span><span class="detail-value">{rh.get('window','—')}</span></div>
                    </div>
                    <div class="detail-box">
                      <h5>📅 Daily Limits</h5>
                      <div class="detail-row"><span class="detail-label">RPD</span><span class="detail-value">{_fmt(rd.get('requests_per_day'))}</span></div>
                      <div class="detail-row"><span class="detail-label">Window</span><span class="detail-value">{rd.get('window','—')}</span></div>
                    </div>
                  </div>
                </div>"""

            agents_html += f"""
            <div class="card agent-card">
              <div style="font-weight:700;font-size:1.05rem;color:var(--accent2);margin-bottom:12px">📜 {agent['script']}</div>
              <div style="margin-bottom:8px">{provs}</div>
              <div style="margin-bottom:8px">{pats}</div>
              <div style="margin-bottom:8px">{envs}</div>
              {models_html}
            </div>"""
    else:
        agents_html = '<div class="empty-state"><div class="empty-icon">🤖</div><p>No AI agents detected</p></div>'

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

    body = f"""
    <div class="stats-grid">{stats_html}</div>

    <div class="section">
      <div class="section-title">🚀 Detected Pipelines</div>
      {pip_html}
    </div>

    <div class="section">
      <div class="section-title">🤖 AI Agents</div>
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
# ROUTE: /scanner/health (HTML)
# ══════════════════════════════════════════════════════════════════════════════

@scanner_bp.get("/health")
def scanner_health():
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
      {_stat_card("🤖", s["ai_agents_found"], "Agents")}
      {_stat_card("📦", s["total_files"], "Files")}
      {_stat_card("🐍", s["python_files"], "Python")}
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
# ROUTE: /monitor/dashboard  (FULL INTERACTIVE DASHBOARD)
# ══════════════════════════════════════════════════════════════════════════════

@monitor_bp.get("/dashboard")
def monitor_dashboard():
    data = scan_project()
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
              <div style="margin-bottom:6px">{configs}</div>
              <div>{env_tags}</div>
            </div>"""
    else:
        pip_cards = '<div class="empty-state"><div class="empty-icon">🔍</div><p style="font-weight:700">No CI/CD pipelines detected</p><p style="margin-top:4px;font-size:.85rem">Add a workflow file to get started</p></div>'

    # ── Agents tab ──
    agents_cards = ""
    if data["agents"]:
        for idx, agent in enumerate(data["agents"]):
            provs = "".join([f'<span class="tag provider">🏢 {p}</span>' for p in agent["providers"]])
            pats = "".join([f'<span class="tag pattern">⚙️ {p}</span>' for p in agent["patterns"]])
            envs = "".join([f'<span class="tag env">🔐 {e}</span>' for e in agent["env_vars"]])

            models_html = ""
            for md in agent.get("model_details", []):
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
                <span style="font-size:.8rem;color:var(--text-secondary)">Agent #{idx+1}</span>
              </div>
              <div style="margin-bottom:8px">{provs}</div>
              {f'<div style="margin-bottom:8px">{pats}</div>' if pats else ''}
              {f'<div style="margin-bottom:8px">{envs}</div>' if envs else ''}
              {models_html}
            </div>"""
    else:
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

    body = f"""
    <div class="stats-grid">{stats_html}</div>

    <div class="tabs">
      <div class="tab active" onclick="switchTab('pipelines')" data-tab="pipelines">🚀 Pipelines</div>
      <div class="tab" onclick="switchTab('agents')" data-tab="agents">🤖 AI Agents</div>
      <div class="tab" onclick="switchTab('chars')" data-tab="chars">🧬 Agent Traits</div>
      <div class="tab" onclick="switchTab('files')" data-tab="files">📁 Files</div>
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
          An AI agent is identified by exhibiting several of these core traits. The scanner checks code patterns for each.
        </p>
        <div class="char-grid">{chars_html}</div>
      </div>
    </div>

    <div class="tab-content" id="tab-files">
      <div class="section">
        <div class="section-title">📁 Project File Structure ({s['total_files']} files)</div>
        <div class="card" style="padding:0;overflow:hidden">
          <div class="file-tree-header"><span></span><span>File</span><span class="fh-purpose">Purpose</span><span style="text-align:right">Size</span></div>
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
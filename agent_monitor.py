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

Routes exposed
──────────────
  GET  /monitor/dashboard   → full interactive dashboard (HTML/CSS/JS embedded)
  POST /monitor/status      → webhook / CI heartbeat
  GET  /scanner/scan        → live repo scan JSON
  GET  /scanner/health      → health-check JSON
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
import subprocess
import importlib
import ast
from pathlib import Path
from collections import defaultdict

from flask import Flask, Blueprint, request, jsonify, Response
from prometheus_flask_exporter import PrometheusMetrics 

# ══════════════════════════════════════════════════════════════════════════════
# FLASK APPLICATION (shared with app.py)
# ══════════════════════════════════════════════════════════════════════════════

BASE_DIR = Path(__file__).resolve().parent

application = Flask(
    __name__,
    template_folder=str(BASE_DIR / "templates"),
    static_folder=str(BASE_DIR / "static"),
)
metrics = PrometheusMetrics(application) 
application.secret_key = os.environ.get("FLASK_SECRET", "sentinelops-lite-key")

monitor_bp = Blueprint("monitor", __name__, url_prefix="/monitor")
scanner_bp = Blueprint("scanner", __name__, url_prefix="/scanner")

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
    """Scan the repo for every known CI/CD platform."""
    results = []
    for name, sig in PIPELINE_SIGNATURES.items():
        found_files = []
        for pattern in sig["files"]:
            found_files.extend(glob.glob(str(BASE_DIR / pattern), recursive=True))

        running_env = [v for v in sig["env_vars"] if os.environ.get(v)]

        if found_files or running_env:
            # Parse pipeline name from file content
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
    """Try to pull a human-readable pipeline name from config files."""
    for f in files:
        try:
            with open(f, "r", encoding="utf-8", errors="ignore") as fh:
                content = fh.read()
            if platform == "GitHub Actions":
                m = re.search(r'^name:\s*(.+)', content, re.MULTILINE)
                if m:
                    return m.group(1).strip().strip('"').strip("'")
            elif platform == "Azure DevOps":
                m = re.search(r'^name:\s*(.+)', content, re.MULTILINE)
                if m:
                    return m.group(1).strip()
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
                    "gpt-3.5", "o1-preview", "o1-mini", "o3-mini", "text-davinci",
                    "text-embedding-ada", "text-embedding-3"],
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
                    "claude-3.5-sonnet", "claude-3.5-haiku", "claude-2", "claude-instant"],
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
        "models": ["gemini-pro", "gemini-1.5-pro", "gemini-1.5-flash", "gemini-ultra",
                    "gemini-2.0-flash"],
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
        "models": ["gpt-4", "gpt-4o", "gpt-35-turbo", "gpt-4-turbo"],
        "token_limits": {
            "gpt-4": {"input": 8192, "output": 8192},
            "gpt-4o": {"input": 128000, "output": 16384},
        },
        "rate_limits": {
            "gpt-4": {"rpm": 600, "rpd": 14400},
            "gpt-4o": {"rpm": 600, "rpd": 14400},
        },
    },
    "Hugging Face": {
        "imports": ["transformers", "huggingface_hub", "HfApi"],
        "env_keys": ["HF_TOKEN", "HUGGINGFACE_TOKEN", "HF_API_KEY"],
        "models": ["llama", "mistral", "falcon", "bloom", "starcoder"],
        "token_limits": {},
        "rate_limits": {},
    },
    "Cohere": {
        "imports": ["cohere"],
        "env_keys": ["COHERE_API_KEY", "CO_API_KEY"],
        "models": ["command", "command-r", "command-r-plus", "embed"],
        "token_limits": {
            "command-r-plus": {"input": 128000, "output": 4096},
            "command-r": {"input": 128000, "output": 4096},
        },
        "rate_limits": {
            "command-r-plus": {"rpm": 1000, "rpd": 50000},
            "command-r": {"rpm": 1000, "rpd": 50000},
        },
    },
    "Groq": {
        "imports": ["groq"],
        "env_keys": ["GROQ_API_KEY"],
        "models": ["llama3", "mixtral", "gemma"],
        "token_limits": {
            "llama3-70b": {"input": 8192, "output": 8192},
            "mixtral-8x7b": {"input": 32768, "output": 32768},
        },
        "rate_limits": {
            "llama3-70b": {"rpm": 30, "rpd": 14400},
            "mixtral-8x7b": {"rpm": 30, "rpd": 14400},
        },
    },
    "LangChain": {
        "imports": ["langchain", "langchain_openai", "langchain_anthropic",
                     "langchain_google_genai", "langchain_community"],
        "env_keys": ["LANGCHAIN_API_KEY", "LANGCHAIN_TRACING_V2"],
        "models": [],
        "token_limits": {},
        "rate_limits": {},
    },
    "CrewAI": {
        "imports": ["crewai"],
        "env_keys": [],
        "models": [],
        "token_limits": {},
        "rate_limits": {},
    },
    "AutoGen": {
        "imports": ["autogen", "pyautogen"],
        "env_keys": [],
        "models": [],
        "token_limits": {},
        "rate_limits": {},
    },
}

# AI agent behavioural characteristics
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
    """Deep-scan a single Python file for AI agent usage."""
    results = {
        "providers_found": [],
        "models_found": [],
        "imports_found": [],
        "env_vars_used": [],
        "token_configs": [],
        "api_calls": [],
        "agent_patterns": [],
    }

    try:
        with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
            content = f.read()
    except Exception:
        return results

    # Parse AST for accurate import detection
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
        # Fallback to regex
        import_patterns = re.findall(
            r'^\s*(?:from\s+([\w.]+)\s+import|import\s+([\w.]+))', content, re.MULTILINE
        )
        for groups in import_patterns:
            for g in groups:
                if g:
                    results["imports_found"].append(g)

    # Check each provider
    for provider_name, provider_info in AI_PROVIDER_PATTERNS.items():
        provider_match = False

        # Check imports
        for imp in provider_info["imports"]:
            if any(imp in found_imp for found_imp in results["imports_found"]):
                provider_match = True
                break

        # Check env var references in source
        for env_key in provider_info["env_keys"]:
            if env_key in content:
                results["env_vars_used"].append(env_key)
                provider_match = True

        if not provider_match:
            continue

        results["providers_found"].append(provider_name)

        # Detect models
        for model in provider_info.get("models", []):
            if model in content:
                results["models_found"].append({
                    "provider": provider_name,
                    "model": model,
                    "token_limits": provider_info.get("token_limits", {}).get(model, {}),
                    "rate_limits": provider_info.get("rate_limits", {}).get(model, {}),
                })

        # Detect token / max_tokens usage
        token_matches = re.findall(
            r'max_tokens\s*[=:]\s*(\d+)', content
        )
        for tm in token_matches:
            results["token_configs"].append({
                "provider": provider_name,
                "max_tokens_configured": int(tm),
            })

        # Detect temperature, top_p etc.
        temp_matches = re.findall(r'temperature\s*[=:]\s*([\d.]+)', content)
        for t in temp_matches:
            results["token_configs"].append({
                "provider": provider_name,
                "temperature": float(t),
            })

    # Detect agent patterns (class-based agents, CrewAI agents, etc.)
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


def scan_project():
    """Scan the entire project directory for AI agents and pipeline info."""
    scan_time = datetime.datetime.now(datetime.timezone.utc).isoformat()

    # ── File tree ──────────────────────────────────────────────
    file_tree = []
    skip_dirs = {".git", "__pycache__", "node_modules", ".venv", "venv", "env",
                 ".tox", ".mypy_cache", ".pytest_cache", "dist", "build",
                 ".eggs", "*.egg-info"}

    FILE_PURPOSES = {
        "app.py": "Flask application entry point — defines routes and WSGI startup",
        "application.py": "Alternative Flask/Django entry point",
        "agent_monitor.py": "AI Agent & Pipeline monitoring module (this file)",
        "manage.py": "Django management commands entry point",
        "wsgi.py": "WSGI configuration for production servers",
        "asgi.py": "ASGI configuration for async servers",
        "settings.py": "Application configuration and settings",
        "config.py": "Application configuration module",
        "models.py": "Database models / ORM definitions",
        "views.py": "View functions / route handlers",
        "urls.py": "URL routing configuration",
        "forms.py": "Form definitions and validation",
        "tasks.py": "Background task definitions (Celery/RQ)",
        "utils.py": "Utility functions and helpers",
        "helpers.py": "Helper functions",
        "requirements.txt": "Python package dependencies",
        "Pipfile": "Pipenv dependency specification",
        "pyproject.toml": "Modern Python project configuration",
        "setup.py": "Package setup and distribution config",
        "setup.cfg": "Package setup configuration",
        "Dockerfile": "Docker container build instructions",
        "docker-compose.yml": "Multi-container Docker orchestration",
        "Makefile": "Build automation commands",
        "Procfile": "Process declarations for Heroku/PaaS",
        ".env": "Environment variables (secrets, config)",
        ".env.example": "Environment variables template",
        "README.md": "Project documentation and overview",
        "LICENSE": "Software license declaration",
        ".gitignore": "Git ignore patterns",
        "Jenkinsfile": "Jenkins pipeline definition",
        "azure-pipelines.yml": "Azure DevOps pipeline config",
        "bitbucket-pipelines.yml": "Bitbucket pipeline config",
        ".gitlab-ci.yml": "GitLab CI pipeline config",
        ".travis.yml": "Travis CI pipeline config",
        "buildspec.yml": "AWS CodeBuild build specification",
        "appspec.yml": "AWS CodeDeploy deployment specification",
        "serverless.yml": "Serverless Framework configuration",
        "terraform.tf": "Terraform infrastructure definition",
    }

    py_files = []

    for root, dirs, files in os.walk(BASE_DIR):
        dirs[:] = [d for d in dirs if d not in skip_dirs and not d.endswith(".egg-info")]
        rel_root = Path(root).relative_to(BASE_DIR)

        for fname in sorted(files):
            rel_path = str(rel_root / fname) if str(rel_root) != "." else fname
            ext = Path(fname).suffix.lower()

            purpose = FILE_PURPOSES.get(fname, "")
            if not purpose:
                if ext == ".py":
                    purpose = "Python module"
                elif ext == ".html":
                    purpose = "HTML template"
                elif ext == ".css":
                    purpose = "Stylesheet"
                elif ext == ".js":
                    purpose = "JavaScript module"
                elif ext in (".yml", ".yaml"):
                    purpose = "YAML configuration"
                elif ext == ".json":
                    purpose = "JSON data / configuration"
                elif ext == ".toml":
                    purpose = "TOML configuration"
                elif ext == ".md":
                    purpose = "Markdown documentation"
                elif ext == ".txt":
                    purpose = "Text file"
                elif ext == ".sh":
                    purpose = "Shell script"
                elif ext == ".sql":
                    purpose = "SQL database script"

            is_main = fname in ("app.py", "application.py", "manage.py", "wsgi.py",
                                "agent_monitor.py", "main.py")

            file_tree.append({
                "path": rel_path,
                "name": fname,
                "purpose": purpose,
                "is_main": is_main,
                "extension": ext,
                "size": os.path.getsize(os.path.join(root, fname)),
            })

            if ext == ".py":
                py_files.append(os.path.join(root, fname))

    # Sort: main files first, then alphabetical
    file_tree.sort(key=lambda x: (not x["is_main"], x["path"]))

    # ── AI Agent scan ──────────────────────────────────────────
    agents = []
    all_providers = set()
    all_models = []

    for pyf in py_files:
        scan_result = _scan_python_file(pyf)
        if scan_result["providers_found"] or scan_result["agent_patterns"]:
            rel = str(Path(pyf).relative_to(BASE_DIR))
            agent_entry = {
                "script": rel,
                "providers": list(set(scan_result["providers_found"])),
                "models": scan_result["models_found"],
                "patterns": list(set(scan_result["agent_patterns"])),
                "env_vars": list(set(scan_result["env_vars_used"])),
                "token_configs": scan_result["token_configs"],
            }

            # Build per-model detail cards
            model_details = []
            for m in scan_result["models_found"]:
                provider_info = AI_PROVIDER_PATTERNS.get(m["provider"], {})
                tl = m.get("token_limits", {})
                rl = m.get("rate_limits", {})

                # Find configured max_tokens for this provider
                configured_tokens = None
                configured_temp = None
                for tc in scan_result["token_configs"]:
                    if tc["provider"] == m["provider"]:
                        if "max_tokens_configured" in tc:
                            configured_tokens = tc["max_tokens_configured"]
                        if "temperature" in tc:
                            configured_temp = tc["temperature"]

                model_details.append({
                    "model_name": m["model"],
                    "provider": m["provider"],
                    "where_used": rel,
                    "why_used": _infer_purpose(rel, m["model"], scan_result),
                    "tokens": {
                        "max_input": tl.get("input", "Unknown"),
                        "max_output": tl.get("output", "Unknown"),
                        "configured_max_tokens": configured_tokens or "Default",
                        "temperature": configured_temp,
                    },
                    "rate_limits_hourly": {
                        "requests_per_minute": rl.get("rpm", "Unknown"),
                        "est_per_hour": rl.get("rpm", 0) * 60 if rl.get("rpm") else "Unknown",
                        "window": "Rolling 60-second window",
                    },
                    "rate_limits_daily": {
                        "requests_per_day": rl.get("rpd", "Unknown"),
                        "window": "UTC 00:00 – 23:59",
                    },
                })

            agent_entry["model_details"] = model_details
            agents.append(agent_entry)
            all_providers.update(scan_result["providers_found"])
            all_models.extend(scan_result["models_found"])

    # ── Pipeline detection ─────────────────────────────────────
    pipelines = detect_pipelines()

    # ── Active env detection ───────────────────────────────────
    active_env = {}
    for prov_info in AI_PROVIDER_PATTERNS.values():
        for ek in prov_info["env_keys"]:
            val = os.environ.get(ek)
            if val:
                masked = val[:4] + "****" + val[-4:] if len(val) > 8 else "****"
                active_env[ek] = masked

    return {
        "scan_time": scan_time,
        "project_root": str(BASE_DIR),
        "pipelines": pipelines,
        "ai_agent_characteristics": AI_AGENT_CHARACTERISTICS,
        "file_tree": file_tree,
        "agents": agents,
        "summary": {
            "total_files": len(file_tree),
            "python_files": len(py_files),
            "ai_agents_found": len(agents),
            "providers": list(all_providers),
            "models_used": len(all_models),
            "pipelines_detected": len(pipelines),
        },
        "active_env_keys": active_env,
    }


def _infer_purpose(filepath, model, scan_result):
    """Infer why a model is used based on file name and patterns."""
    fp = filepath.lower()
    patterns = scan_result.get("agent_patterns", [])

    if "monitor" in fp:
        return "Monitoring, health-check analysis, or alerting"
    if "chat" in fp:
        return "Conversational AI / chatbot functionality"
    if "agent" in fp:
        return "Autonomous AI agent task execution"
    if "embed" in model.lower():
        return "Text embedding for semantic search or RAG"
    if "tool" in " ".join(patterns).lower():
        return "Tool-augmented reasoning and function calling"
    if any(p in patterns for p in ["CrewAI Agent", "AutoGen Agent"]):
        return "Multi-agent collaboration and task orchestration"
    if "langchain" in " ".join(patterns).lower():
        return "LLM chain orchestration and prompt management"
    return "AI-powered text generation and analysis"


# ══════════════════════════════════════════════════════════════════════════════
# ROUTE HANDLERS
# ══════════════════════════════════════════════════════════════════════════════

def handle_monitor_status():
    """Handle POST /monitor/status from CI webhooks."""
    data = request.get_json(silent=True) or {}
    return jsonify({
        "status": "ok",
        "received": data,
        "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    })


@scanner_bp.get("/scan")
def scanner_scan():
    """Return full project scan as JSON."""
    return jsonify(scan_project())


@scanner_bp.get("/health")
def scanner_health():
    """Quick health check."""
    return jsonify({"status": "healthy", "module": "agent_monitor",
                    "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat()})


# ══════════════════════════════════════════════════════════════════════════════
# DASHBOARD — full HTML/CSS/JS embedded
# ══════════════════════════════════════════════════════════════════════════════

DASHBOARD_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>SentinelOps — AI Agent & Pipeline Monitor</title>
<style>
/* ══════════════ RESET & BASE ══════════════ */
*,*::before,*::after{box-sizing:border-box;margin:0;padding:0}
:root{
  --bg:#f8fdf8;--card:#ffffff;--border:#d4e8d4;--accent:#2d8a4e;
  --accent2:#1a6834;--accent-light:#e8f5e8;--text:#1a2e1a;
  --text-secondary:#4a6a4a;--shadow:0 2px 12px rgba(45,138,78,.08);
  --shadow-hover:0 4px 24px rgba(45,138,78,.14);--radius:12px;
  --gradient:linear-gradient(135deg,#2d8a4e 0%,#1a6834 100%);
}
html{scroll-behavior:smooth}
body{
  font-family:'Segoe UI',system-ui,-apple-system,sans-serif;
  background:var(--bg);color:var(--text);line-height:1.6;
  min-height:100vh;
}

/* ══════════════ HEADER ══════════════ */
.header{
  background:var(--gradient);color:#fff;padding:28px 32px;
  position:sticky;top:0;z-index:100;
  box-shadow:0 4px 20px rgba(0,0,0,.15);
}
.header-inner{max-width:1400px;margin:0 auto;display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:16px}
.header h1{font-size:1.7rem;font-weight:700;letter-spacing:-.5px;display:flex;align-items:center;gap:10px}
.header h1 span.icon{font-size:2rem}
.header-badges{display:flex;gap:8px;flex-wrap:wrap}
.badge{
  display:inline-flex;align-items:center;gap:5px;
  padding:4px 14px;border-radius:20px;font-size:.78rem;font-weight:600;
  background:rgba(255,255,255,.2);color:#fff;backdrop-filter:blur(4px);
}
.badge.live{background:rgba(255,255,255,.25);animation:pulse-badge 2s infinite}
@keyframes pulse-badge{0%,100%{opacity:1}50%{opacity:.6}}

/* ══════════════ CONTAINER ══════════════ */
.container{max-width:1400px;margin:0 auto;padding:24px 20px 60px}

/* ══════════════ STAT CARDS ══════════════ */
.stats-grid{
  display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));
  gap:16px;margin-bottom:32px;
}
.stat-card{
  background:var(--card);border:1px solid var(--border);border-radius:var(--radius);
  padding:20px 24px;box-shadow:var(--shadow);transition:all .3s ease;
  position:relative;overflow:hidden;
}
.stat-card::before{
  content:'';position:absolute;top:0;left:0;width:4px;height:100%;
  background:var(--gradient);
}
.stat-card:hover{transform:translateY(-2px);box-shadow:var(--shadow-hover)}
.stat-card .stat-icon{font-size:2rem;margin-bottom:8px}
.stat-card .stat-value{font-size:2rem;font-weight:800;color:var(--accent)}
.stat-card .stat-label{font-size:.82rem;color:var(--text-secondary);font-weight:500;text-transform:uppercase;letter-spacing:.5px}

/* ══════════════ SECTIONS ══════════════ */
.section{margin-bottom:36px}
.section-title{
  font-size:1.25rem;font-weight:700;color:var(--accent2);
  display:flex;align-items:center;gap:10px;margin-bottom:16px;
  padding-bottom:10px;border-bottom:2px solid var(--border);
}
.section-title .sec-icon{font-size:1.4rem}

/* ══════════════ CARDS ══════════════ */
.card{
  background:var(--card);border:1px solid var(--border);border-radius:var(--radius);
  padding:24px;margin-bottom:16px;box-shadow:var(--shadow);
  transition:all .3s ease;
}
.card:hover{box-shadow:var(--shadow-hover)}
.card-header{display:flex;align-items:center;justify-content:space-between;margin-bottom:16px;flex-wrap:wrap;gap:8px}
.card-title{font-size:1.1rem;font-weight:700;color:var(--accent2);display:flex;align-items:center;gap:8px}
.card-subtitle{font-size:.82rem;color:var(--text-secondary)}

/* ══════════════ PIPELINE CARD ══════════════ */
.pipeline-card{border-left:4px solid var(--accent)}
.pipeline-status{
  display:inline-flex;align-items:center;gap:5px;padding:3px 12px;
  border-radius:20px;font-size:.75rem;font-weight:600;
}
.pipeline-status.running{background:#d4edda;color:#155724}
.pipeline-status.detected{background:#fff3cd;color:#856404}
.config-files{display:flex;flex-wrap:wrap;gap:6px;margin-top:8px}
.config-file-tag{
  background:var(--accent-light);color:var(--accent2);
  padding:3px 10px;border-radius:6px;font-size:.78rem;font-family:monospace;
}

/* ══════════════ CHARACTERISTICS ══════════════ */
.char-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(280px,1fr));gap:12px}
.char-card{
  background:var(--accent-light);border:1px solid var(--border);
  border-radius:10px;padding:14px 18px;display:flex;align-items:flex-start;gap:12px;
  transition:all .25s ease;
}
.char-card:hover{transform:scale(1.02);background:#d8f0d8}
.char-icon{font-size:1.6rem;flex-shrink:0;margin-top:2px}
.char-info h4{font-weight:700;color:var(--accent2);font-size:.92rem}
.char-info p{font-size:.8rem;color:var(--text-secondary);margin-top:2px}

/* ══════════════ FILE TREE ══════════════ */
.file-tree{font-family:'Cascadia Code','Fira Code',monospace;font-size:.82rem}
.file-row{
  display:grid;grid-template-columns:24px 1fr 1fr 80px;gap:8px;
  padding:8px 12px;border-bottom:1px solid #eef4ee;align-items:center;
  transition:background .15s;
}
.file-row:hover{background:var(--accent-light)}
.file-row.main-file{background:#e0f2e0;font-weight:600}
.file-row .f-icon{text-align:center;font-size:1rem}
.file-row .f-path{color:var(--text);word-break:break-all}
.file-row .f-purpose{color:var(--text-secondary);font-size:.78rem;font-family:'Segoe UI',sans-serif}
.file-row .f-size{color:var(--text-secondary);font-size:.75rem;text-align:right}
.file-tree-header{
  display:grid;grid-template-columns:24px 1fr 1fr 80px;gap:8px;
  padding:10px 12px;background:var(--accent);color:#fff;
  border-radius:var(--radius) var(--radius) 0 0;font-weight:700;font-size:.82rem;
}

/* ══════════════ AGENT DETAIL ══════════════ */
.agent-card{border-left:4px solid #2d8a4e}
.model-detail{
  background:#f0f8f0;border:1px solid var(--border);border-radius:10px;
  padding:18px;margin-top:12px;
}
.model-detail h4{color:var(--accent2);font-size:1rem;margin-bottom:12px;display:flex;align-items:center;gap:6px}
.detail-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:12px}
.detail-box{background:#fff;border:1px solid var(--border);border-radius:8px;padding:14px}
.detail-box h5{font-size:.78rem;text-transform:uppercase;letter-spacing:.5px;color:var(--accent);margin-bottom:8px;display:flex;align-items:center;gap:5px}
.detail-box .detail-row{display:flex;justify-content:space-between;padding:3px 0;font-size:.82rem;border-bottom:1px solid #f0f0f0}
.detail-box .detail-row:last-child{border-bottom:none}
.detail-box .detail-label{color:var(--text-secondary)}
.detail-box .detail-value{font-weight:600;color:var(--text)}

/* ══════════════ MINI BAR CHART ══════════════ */
.bar-chart{display:flex;align-items:flex-end;gap:3px;height:60px;margin-top:8px}
.bar{
  flex:1;background:var(--gradient);border-radius:4px 4px 0 0;
  min-width:8px;transition:height .5s ease;position:relative;
}
.bar:hover{opacity:.8}
.bar-label{
  position:absolute;bottom:-18px;left:50%;transform:translateX(-50%);
  font-size:.6rem;color:var(--text-secondary);white-space:nowrap;
}

/* ══════════════ USAGE GAUGE ══════════════ */
.gauge-container{display:flex;align-items:center;gap:12px;margin:8px 0}
.gauge-bar{flex:1;height:10px;background:#e0e0e0;border-radius:5px;overflow:hidden;position:relative}
.gauge-fill{height:100%;border-radius:5px;transition:width 1s ease;background:var(--gradient)}
.gauge-fill.warn{background:linear-gradient(90deg,#f0ad4e,#d9534f)}
.gauge-text{font-size:.78rem;font-weight:600;color:var(--accent);min-width:50px;text-align:right}

/* ══════════════ TAGS ══════════════ */
.tag{
  display:inline-flex;align-items:center;gap:4px;
  padding:3px 10px;border-radius:6px;font-size:.75rem;font-weight:600;margin:2px;
}
.tag.provider{background:#d4edda;color:#155724}
.tag.model{background:#cce5ff;color:#004085}
.tag.pattern{background:#fff3cd;color:#856404}
.tag.env{background:#f8d7da;color:#721c24}

/* ══════════════ LOADING ══════════════ */
.loading{text-align:center;padding:60px 20px}
.spinner{
  width:48px;height:48px;border:4px solid var(--border);
  border-top-color:var(--accent);border-radius:50%;
  animation:spin .8s linear infinite;margin:0 auto 16px;
}
@keyframes spin{to{transform:rotate(360deg)}}

/* ══════════════ NO DATA ══════════════ */
.empty-state{
  text-align:center;padding:40px;color:var(--text-secondary);
  background:var(--accent-light);border-radius:var(--radius);
}
.empty-state .empty-icon{font-size:3rem;margin-bottom:12px}

/* ══════════════ RESPONSIVE ══════════════ */
@media(max-width:768px){
  .header{padding:16px}
  .header h1{font-size:1.2rem}
  .stats-grid{grid-template-columns:repeat(2,1fr)}
  .char-grid{grid-template-columns:1fr}
  .detail-grid{grid-template-columns:1fr}
  .file-row{grid-template-columns:24px 1fr 80px;font-size:.75rem}
  .file-row .f-purpose{display:none}
}

/* ══════════════ REFRESH BTN ══════════════ */
.refresh-btn{
  background:rgba(255,255,255,.2);color:#fff;border:1px solid rgba(255,255,255,.3);
  padding:8px 18px;border-radius:8px;cursor:pointer;font-weight:600;font-size:.85rem;
  transition:all .2s;display:flex;align-items:center;gap:6px;
}
.refresh-btn:hover{background:rgba(255,255,255,.35)}
.refresh-btn.spinning .r-icon{animation:spin .8s linear infinite}

/* ══════════════ TOOLTIP ══════════════ */
.tooltip-wrap{position:relative;cursor:help}
.tooltip-wrap .tooltip{
  display:none;position:absolute;bottom:calc(100% + 8px);left:50%;transform:translateX(-50%);
  background:#1a2e1a;color:#fff;padding:8px 12px;border-radius:8px;font-size:.75rem;
  white-space:nowrap;z-index:10;box-shadow:0 4px 12px rgba(0,0,0,.2);
}
.tooltip-wrap:hover .tooltip{display:block}

/* ══════════════ TABS ══════════════ */
.tabs{display:flex;gap:4px;margin-bottom:20px;border-bottom:2px solid var(--border);padding-bottom:0}
.tab{
  padding:10px 20px;cursor:pointer;font-weight:600;font-size:.88rem;
  color:var(--text-secondary);border-bottom:3px solid transparent;
  transition:all .2s;margin-bottom:-2px;
}
.tab:hover{color:var(--accent)}
.tab.active{color:var(--accent);border-bottom-color:var(--accent)}
.tab-content{display:none}
.tab-content.active{display:block}
</style>
</head>
<body>

<div class="header">
  <div class="header-inner">
    <h1><span class="icon">🛡️</span> SentinelOps — AI Agent & Pipeline Monitor</h1>
    <div style="display:flex;align-items:center;gap:12px">
      <div class="header-badges" id="headerBadges"></div>
      <button class="refresh-btn" onclick="loadData()" id="refreshBtn">
        <span class="r-icon">🔄</span> Refresh
      </button>
    </div>
  </div>
</div>

<div class="container">
  <!-- Loading -->
  <div id="loading" class="loading">
    <div class="spinner"></div>
    <p style="font-weight:600;color:var(--accent)">Scanning project…</p>
    <p style="font-size:.85rem;color:var(--text-secondary);margin-top:4px">Detecting pipelines, agents & files</p>
  </div>

  <!-- Dashboard content (hidden until data loads) -->
  <div id="dashboard" style="display:none">

    <!-- Stats Row -->
    <div class="stats-grid" id="statsGrid"></div>

    <!-- Tabs -->
    <div class="tabs">
      <div class="tab active" data-tab="pipelines" onclick="switchTab('pipelines')">🚀 Pipelines</div>
      <div class="tab" data-tab="agents" onclick="switchTab('agents')">🤖 AI Agents</div>
      <div class="tab" data-tab="characteristics" onclick="switchTab('characteristics')">🧬 Agent Traits</div>
      <div class="tab" data-tab="files" onclick="switchTab('files')">📁 Project Files</div>
    </div>

    <!-- Tab: Pipelines -->
    <div class="tab-content active" id="tab-pipelines"></div>

    <!-- Tab: AI Agents -->
    <div class="tab-content" id="tab-agents"></div>

    <!-- Tab: Characteristics -->
    <div class="tab-content" id="tab-characteristics"></div>

    <!-- Tab: Files -->
    <div class="tab-content" id="tab-files"></div>

  </div>
</div>

<script>
// ══════════════ STATE ══════════════
let DATA = null;

// ══════════════ LOAD ══════════════
async function loadData(){
  const btn = document.getElementById('refreshBtn');
  btn.classList.add('spinning');
  try{
    const r = await fetch('/scanner/scan');
    DATA = await r.json();
    render();
  }catch(e){
    document.getElementById('loading').innerHTML = `
      <div class="empty-state">
        <div class="empty-icon">⚠️</div>
        <p style="font-weight:700;font-size:1.1rem">Failed to load scan data</p>
        <p style="margin-top:8px">${e.message}</p>
      </div>`;
  }finally{
    btn.classList.remove('spinning');
  }
}

// ══════════════ RENDER ══════════════
function render(){
  document.getElementById('loading').style.display='none';
  document.getElementById('dashboard').style.display='block';
  renderBadges();
  renderStats();
  renderPipelines();
  renderAgents();
  renderCharacteristics();
  renderFiles();
}

// ══════════════ BADGES ══════════════
function renderBadges(){
  const el = document.getElementById('headerBadges');
  let h = '';
  if(DATA.pipelines.length){
    DATA.pipelines.forEach(p=>{
      const cls = p.is_running_here ? 'live' : '';
      h += `<span class="badge ${cls}">${p.is_running_here?'🟢':'🔵'} ${p.platform}</span>`;
    });
  }
  h += `<span class="badge">📊 ${DATA.summary.ai_agents_found} Agent${DATA.summary.ai_agents_found!==1?'s':''}</span>`;
  h += `<span class="badge">📁 ${DATA.summary.total_files} Files</span>`;
  el.innerHTML = h;
}

// ══════════════ STATS ══════════════
function renderStats(){
  const s = DATA.summary;
  const items = [
    {icon:'🚀',value:s.pipelines_detected,label:'Pipelines Detected'},
    {icon:'🤖',value:s.ai_agents_found,label:'AI Agent Scripts'},
    {icon:'🧠',value:s.models_used,label:'Models Detected'},
    {icon:'📦',value:s.total_files,label:'Total Files'},
    {icon:'🐍',value:s.python_files,label:'Python Files'},
    {icon:'🔑',value:Object.keys(DATA.active_env_keys).length,label:'Active API Keys'},
  ];
  document.getElementById('statsGrid').innerHTML = items.map(i=>`
    <div class="stat-card">
      <div class="stat-icon">${i.icon}</div>
      <div class="stat-value">${i.value}</div>
      <div class="stat-label">${i.label}</div>
    </div>`).join('');
}

// ══════════════ PIPELINES ══════════════
function renderPipelines(){
  const el = document.getElementById('tab-pipelines');
  if(!DATA.pipelines.length){
    el.innerHTML = `<div class="empty-state"><div class="empty-icon">🔍</div>
      <p style="font-weight:700">No CI/CD pipelines detected</p>
      <p style="margin-top:4px;font-size:.85rem">Add a workflow file to get started (.github/workflows/, Jenkinsfile, etc.)</p></div>`;
    return;
  }
  el.innerHTML = `<div class="section"><div class="section-title"><span class="sec-icon">🚀</span> Detected CI/CD Pipelines</div>`
    + DATA.pipelines.map(p=>{
      const status = p.is_running_here
        ? '<span class="pipeline-status running">● Running Here</span>'
        : '<span class="pipeline-status detected">◉ Detected</span>';
      const envBadges = p.active_env_vars.map(v=>`<span class="tag env">🔐 ${v}</span>`).join('');
      const configTags = p.config_files.map(f=>`<span class="config-file-tag">📄 ${f}</span>`).join('');
      return `
        <div class="card pipeline-card">
          <div class="card-header">
            <div class="card-title">🏗️ ${p.platform} — ${p.pipeline_name}</div>
            ${status}
          </div>
          <p style="color:var(--text-secondary);font-size:.88rem;margin-bottom:12px">${p.description}</p>
          ${configTags ? '<div style="margin-bottom:8px"><strong style="font-size:.78rem;color:var(--accent)">Config Files:</strong><div class="config-files">'+configTags+'</div></div>' : ''}
          ${envBadges ? '<div><strong style="font-size:.78rem;color:var(--accent)">Active Env Vars:</strong><div style="margin-top:4px">'+envBadges+'</div></div>' : ''}
        </div>`;
    }).join('') + '</div>';
}

// ══════════════ AGENTS ══════════════
function renderAgents(){
  const el = document.getElementById('tab-agents');
  if(!DATA.agents.length){
    el.innerHTML = `<div class="empty-state"><div class="empty-icon">🤖</div>
      <p style="font-weight:700">No AI agents detected in this project</p>
      <p style="margin-top:4px;font-size:.85rem">Add OpenAI, Anthropic, Gemini, LangChain, or other AI imports to your Python files</p></div>`;
    return;
  }

  let html = '<div class="section"><div class="section-title"><span class="sec-icon">🤖</span> AI Agents Found in Project</div>';

  DATA.agents.forEach((agent, idx)=>{
    const provTags = agent.providers.map(p=>`<span class="tag provider">🏢 ${p}</span>`).join('');
    const patTags = agent.patterns.map(p=>`<span class="tag pattern">⚙️ ${p}</span>`).join('');
    const envTags = agent.env_vars.map(e=>`<span class="tag env">🔐 ${e}</span>`).join('');

    html += `
    <div class="card agent-card">
      <div class="card-header">
        <div class="card-title">📜 ${agent.script}</div>
        <div class="card-subtitle">Agent Script #${idx+1}</div>
      </div>
      <div style="margin-bottom:12px">
        <strong style="font-size:.78rem;color:var(--accent)">Providers:</strong> ${provTags}
      </div>
      ${patTags ? '<div style="margin-bottom:12px"><strong style="font-size:.78rem;color:var(--accent)">Agent Patterns:</strong> '+patTags+'</div>' : ''}
      ${envTags ? '<div style="margin-bottom:12px"><strong style="font-size:.78rem;color:var(--accent)">Env Vars Referenced:</strong> '+envTags+'</div>' : ''}
    `;

    // Model details
    if(agent.model_details && agent.model_details.length){
      agent.model_details.forEach(md=>{
        const toks = md.tokens || {};
        const rh = md.rate_limits_hourly || {};
        const rd = md.rate_limits_daily || {};

        // Gauge: estimate usage (simulated — replace with real tracking)
        const maxH = rh.est_per_hour || 0;
        const maxD = rd.requests_per_day || 0;
        const usedH = Math.floor(Math.random() * Math.min(maxH, 100)); // placeholder
        const usedD = Math.floor(Math.random() * Math.min(maxD, 500)); // placeholder
        const pctH = maxH ? Math.min((usedH/maxH)*100,100) : 0;
        const pctD = maxD ? Math.min((usedD/maxD)*100,100) : 0;

        html += `
        <div class="model-detail">
          <h4>🧠 Model: <span style="color:var(--accent)">${md.model_name}</span></h4>
          <div class="detail-grid">

            <!-- Identity -->
            <div class="detail-box">
              <h5>🏷️ Identity</h5>
              <div class="detail-row"><span class="detail-label">Model</span><span class="detail-value">${md.model_name}</span></div>
              <div class="detail-row"><span class="detail-label">Provider</span><span class="detail-value">${md.provider}</span></div>
              <div class="detail-row"><span class="detail-label">Script</span><span class="detail-value">${md.where_used}</span></div>
              <div class="detail-row"><span class="detail-label">Purpose</span><span class="detail-value">${md.why_used}</span></div>
            </div>

            <!-- Tokens -->
            <div class="detail-box">
              <h5>🎟️ Token Limits</h5>
              <div class="detail-row"><span class="detail-label">Max Input</span><span class="detail-value">${fmtNum(toks.max_input)}</span></div>
              <div class="detail-row"><span class="detail-label">Max Output</span><span class="detail-value">${fmtNum(toks.max_output)}</span></div>
              <div class="detail-row"><span class="detail-label">Configured max_tokens</span><span class="detail-value">${fmtNum(toks.configured_max_tokens)}</span></div>
              <div class="detail-row"><span class="detail-label">Temperature</span><span class="detail-value">${toks.temperature ?? 'Default'}</span></div>
              <div class="bar-chart">
                ${toks.max_input && toks.max_input!=='Unknown' ? `<div class="bar" style="height:${Math.min(100,toks.max_input/2000)}%;" title="Input: ${fmtNum(toks.max_input)}"></div>`:''}
                ${toks.max_output && toks.max_output!=='Unknown' ? `<div class="bar" style="height:${Math.min(100,toks.max_output/500)}%;background:linear-gradient(135deg,#1a6834,#4caf50)" title="Output: ${fmtNum(toks.max_output)}"></div>`:''}
              </div>
            </div>

            <!-- Hourly Rate -->
            <div class="detail-box">
              <h5>⏱️ Hourly Rate Limits</h5>
              <div class="detail-row"><span class="detail-label">Requests/min</span><span class="detail-value">${fmtNum(rh.requests_per_minute)}</span></div>
              <div class="detail-row"><span class="detail-label">Est. per hour</span><span class="detail-value">${fmtNum(rh.est_per_hour)}</span></div>
              <div class="detail-row"><span class="detail-label">Window</span><span class="detail-value">${rh.window||'—'}</span></div>
              <div class="detail-row"><span class="detail-label">Used (est.)</span><span class="detail-value">${usedH} reqs</span></div>
              <div class="gauge-container">
                <div class="gauge-bar"><div class="gauge-fill ${pctH>80?'warn':''}" style="width:${pctH}%"></div></div>
                <span class="gauge-text">${pctH.toFixed(0)}%</span>
              </div>
            </div>

            <!-- Daily Rate -->
            <div class="detail-box">
              <h5>📅 Daily Rate Limits</h5>
              <div class="detail-row"><span class="detail-label">Requests/day</span><span class="detail-value">${fmtNum(rd.requests_per_day)}</span></div>
              <div class="detail-row"><span class="detail-label">Window</span><span class="detail-value">${rd.window||'—'}</span></div>
              <div class="detail-row"><span class="detail-label">Used (est.)</span><span class="detail-value">${usedD} reqs</span></div>
              <div class="gauge-container">
                <div class="gauge-bar"><div class="gauge-fill ${pctD>80?'warn':''}" style="width:${pctD}%"></div></div>
                <span class="gauge-text">${pctD.toFixed(0)}%</span>
              </div>
            </div>

          </div>
        </div>`;
      });
    }

    html += '</div>'; // close agent-card
  });

  html += '</div>';
  el.innerHTML = html;
}

// ══════════════ CHARACTERISTICS ══════════════
function renderCharacteristics(){
  const el = document.getElementById('tab-characteristics');
  const chars = DATA.ai_agent_characteristics || [];
  el.innerHTML = `
    <div class="section">
      <div class="section-title"><span class="sec-icon">🧬</span> AI Agent Characteristics — How They Are Identified</div>
      <p style="color:var(--text-secondary);margin-bottom:16px;font-size:.88rem">
        An AI agent is identified by exhibiting several of these core traits. The scanner looks for code patterns matching each characteristic.
      </p>
      <div class="char-grid">
        ${chars.map(c=>`
          <div class="char-card">
            <div class="char-icon">${c.icon}</div>
            <div class="char-info">
              <h4>${c.trait}</h4>
              <p>${c.desc}</p>
            </div>
          </div>`).join('')}
      </div>
    </div>`;
}

// ══════════════ FILE TREE ══════════════
function renderFiles(){
  const el = document.getElementById('tab-files');
  const files = DATA.file_tree || [];
  if(!files.length){
    el.innerHTML = '<div class="empty-state"><div class="empty-icon">📁</div><p>No files found</p></div>';
    return;
  }

  const fileIcon = ext => {
    const map = {'.py':'🐍','.html':'🌐','.css':'🎨','.js':'⚡','.yml':'📋','.yaml':'📋',
      '.json':'📦','.md':'📝','.txt':'📄','.sh':'💻','.sql':'🗄️','.toml':'⚙️',
      '.cfg':'⚙️','.ini':'⚙️','.env':'🔐','':'📄'};
    return map[ext] || '📄';
  };

  let html = `
    <div class="section">
      <div class="section-title"><span class="sec-icon">📁</span> Project File Structure (${files.length} files)</div>
      <div class="file-tree">
        <div class="file-tree-header">
          <span></span><span>File Path</span><span>Purpose</span><span style="text-align:right">Size</span>
        </div>
        ${files.map(f=>`
          <div class="file-row ${f.is_main?'main-file':''}">
            <span class="f-icon">${fileIcon(f.extension)}</span>
            <span class="f-path">${f.is_main?'⭐ ':''}${f.path}</span>
            <span class="f-purpose">${f.purpose}</span>
            <span class="f-size">${fmtBytes(f.size)}</span>
          </div>`).join('')}
      </div>
    </div>`;
  el.innerHTML = html;
}

// ══════════════ TABS ══════════════
function switchTab(name){
  document.querySelectorAll('.tab').forEach(t=>t.classList.toggle('active',t.dataset.tab===name));
  document.querySelectorAll('.tab-content').forEach(c=>c.classList.toggle('active',c.id==='tab-'+name));
}

// ══════════════ HELPERS ══════════════
function fmtNum(n){
  if(n===null||n===undefined||n==='Unknown'||n==='Default')return n||'—';
  if(typeof n==='string')return n;
  return n.toLocaleString();
}
function fmtBytes(b){
  if(b<1024)return b+' B';
  if(b<1048576)return (b/1024).toFixed(1)+' KB';
  return (b/1048576).toFixed(1)+' MB';
}

// ══════════════ INIT ══════════════
document.addEventListener('DOMContentLoaded', loadData);
</script>
</body>
</html>"""


@monitor_bp.get("/dashboard")
def monitor_dashboard():
    """Serve the fully embedded monitoring dashboard."""
    return Response(DASHBOARD_HTML, mimetype="text/html")
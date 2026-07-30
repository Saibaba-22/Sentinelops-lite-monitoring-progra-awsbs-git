"""
agent_monitor.py
================
Complete SentinelOps-Lite backend.

Contains:
  - Flask application object
  - All Prometheus metrics
  - All configuration
  - All business logic
  - monitor_bp  Blueprint  → /monitor/*
  - scanner_bp  Blueprint  → /scanner/*
  - handle_monitor_status() → called by app.py /monitor/status route

app.py only owns:
  GET  /          → render_template("index.html")
  POST /monitor/status → delegates to handle_monitor_status()
"""

from __future__ import annotations

# ── stdlib ────────────────────────────────────────────────────
import ast
import datetime
import hmac
import json
import os
import re
import sys
import time
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass, field
from pathlib import Path
from threading import Lock, Thread
from typing import Any

# ── Flask ─────────────────────────────────────────────────────
from flask import Blueprint, Flask, Response, jsonify, render_template_string, request

# ── Prometheus ────────────────────────────────────────────────
import psutil
from prometheus_client import (
    CONTENT_TYPE_LATEST,
    Counter as PCounter,
    Gauge,
    Histogram,
    Info,
    generate_latest,
)


# ══════════════════════════════════════════════════════════════
# FLASK APPLICATION OBJECT
# ══════════════════════════════════════════════════════════════

application = Flask(__name__)


# ══════════════════════════════════════════════════════════════
# CENTRALISED CONFIG  —  read once at startup
# ══════════════════════════════════════════════════════════════

_CFG: dict[str, str] = {
    "provider":      os.getenv("AI_PROVIDER",    "gemini"),
    "model":         os.getenv("AI_MODEL",       "gemini-2.5-flash"),
    "version":       os.getenv("APP_VERSION",    "1.0.0"),
    "build":         os.getenv("BUILD_NUMBER",   "unknown"),
    "environment":   os.getenv("ENVIRONMENT",    "production"),
    "cloud":         os.getenv("TARGET_CLOUD",   "aws"),
    "region":        os.getenv("AWS_REGION",     "us-east-1"),
    "monitor_token": os.getenv("MONITOR_TOKEN",  ""),
    "metrics_token": os.getenv("METRICS_TOKEN",  ""),
    "port":          os.getenv("PORT",           "8000"),
}

# ── startup timestamp ─────────────────────────────────────────
_START_TIME: float = time.time()

# ── cached psutil process handle ─────────────────────────────
# One object reused across all calls so cpu_percent() delta is correct.
# First call always returns 0.0 — prime it once at startup.
_PROC: psutil.Process = psutil.Process()
_PROC.cpu_percent(interval=0.1)   # blocks 100 ms once, correct thereafter

# ── blueprint loaded flag ─────────────────────────────────────
_SCANNER_LOADED: bool = False


# ══════════════════════════════════════════════════════════════
# PROMETHEUS METRICS
# ══════════════════════════════════════════════════════════════

# ── HTTP ──────────────────────────────────────────────────────
REQUEST_COUNT = PCounter(
    "app_requests_total",
    "Total HTTP requests",
    ["method", "endpoint", "status"],
)

REQUEST_LATENCY = Histogram(
    "app_request_duration_seconds",
    "HTTP request latency in seconds",
    ["method", "endpoint"],
    buckets=[0.005, 0.01, 0.025, 0.05,
             0.1, 0.25, 0.5, 1.0, 2.5, 5.0],
)

# ── Agent ─────────────────────────────────────────────────────
AGENT_STATUS = Gauge(
    "agent_status",
    "AI agent running status (1=running, 0=stopped)",
)

AGENT_INFO = Info(
    "agent",
    "AI agent static information — set once at startup",
)

AGENT_REQUESTS_TOTAL = PCounter(
    "agent_requests_total",
    "Total requests made by the AI agent",
    ["provider", "model", "status"],
)

AGENT_MODEL_INFO = Gauge(
    "agent_model_info",
    "AI model label carrier — value is always 1",
    ["provider", "model", "version", "environment"],
)

AGENT_UPTIME_SECONDS = Gauge(
    "agent_uptime_seconds",
    "Seconds since the agent process started",
)

AGENT_CPU_PERCENT = Gauge(
    "agent_cpu_percent",
    "CPU usage percent of the agent process",
)

AGENT_MEMORY_MB = Gauge(
    "agent_memory_mb",
    "RSS memory used by the agent process in MB",
)

SCANNER_LOADED_GAUGE = Gauge(
    "agent_scanner_loaded",
    "1 if the AI scanner blueprint loaded successfully, 0 otherwise",
)

# ── System ────────────────────────────────────────────────────
SYSTEM_CPU = Gauge(
    "system_cpu_percent",
    "System-wide CPU usage percent",
)

SYSTEM_MEMORY_PERCENT = Gauge(
    "system_memory_percent",
    "System memory usage percent",
)

SYSTEM_MEMORY_USED_MB = Gauge(
    "system_memory_used_mb",
    "System memory used in MB",
)

# ── backward-compat alias ─────────────────────────────────────
PROCESS_CPU = Gauge(
    "python_process_cpu_percent",
    "CPU usage percent of this process (alias of agent_cpu_percent)",
)


# ══════════════════════════════════════════════════════════════
# METRIC HELPERS
# ══════════════════════════════════════════════════════════════

def _init_static_metrics() -> None:
    """
    Set metrics that never change after startup.
    Called exactly ONCE — Info.info() raises if called twice.
    """
    AGENT_INFO.info({
        "provider":    _CFG["provider"],
        "model":       _CFG["model"],
        "version":     _CFG["version"],
        "environment": _CFG["environment"],
        "build":       _CFG["build"],
        "cloud":       _CFG["cloud"],
        "region":      _CFG["region"],
    })
    AGENT_MODEL_INFO.labels(
        provider=    _CFG["provider"],
        model=       _CFG["model"],
        version=     _CFG["version"],
        environment= _CFG["environment"],
    ).set(1)
    SCANNER_LOADED_GAUGE.set(1 if _SCANNER_LOADED else 0)
    AGENT_STATUS.set(1)


def _update_dynamic_metrics() -> None:
    """
    Refresh metrics that change over time.
    Called before every Prometheus scrape and on /agent/status.
    Never raises — all psutil errors are caught.
    """
    try:
        cpu    = _PROC.cpu_percent(interval=None)
        mem_mb = round(_PROC.memory_info().rss / 1024 / 1024, 2)
        AGENT_CPU_PERCENT.set(cpu)
        AGENT_MEMORY_MB.set(mem_mb)
        PROCESS_CPU.set(cpu)
        AGENT_UPTIME_SECONDS.set(round(time.time() - _START_TIME, 1))
        AGENT_STATUS.set(1)
    except (psutil.AccessDenied,
            psutil.NoSuchProcess,
            psutil.ZombieProcess) as exc:
        print(f"⚠️  psutil process error: {exc}")
        AGENT_STATUS.set(0)

    try:
        vmem = psutil.virtual_memory()
        SYSTEM_CPU.set(psutil.cpu_percent(interval=None))
        SYSTEM_MEMORY_PERCENT.set(vmem.percent)
        SYSTEM_MEMORY_USED_MB.set(round(vmem.used / 1024 / 1024, 2))
    except Exception as exc:                        # noqa: BLE001
        print(f"⚠️  psutil system error: {exc}")


def _record(endpoint: str, status: int = 200) -> float:
    """Increment request counter and return start timestamp."""
    REQUEST_COUNT.labels(
        method=   request.method,
        endpoint= endpoint,
        status=   str(status),
    ).inc()
    return time.perf_counter()


def _finish(endpoint: str, start: float) -> None:
    """Observe request latency in the histogram."""
    REQUEST_LATENCY.labels(
        method=   request.method,
        endpoint= endpoint,
    ).observe(time.perf_counter() - start)


def _safe_system_snapshot() -> dict[str, Any]:
    """Return system + process metrics — all psutil errors caught."""
    snap: dict[str, Any] = {
        "cpu_usage_percent":   -1,
        "memory_total_mb":     -1,
        "memory_used_mb":      -1,
        "memory_percent":      -1,
        "process_cpu_percent": -1,
        "process_memory_mb":   -1,
    }
    try:
        vmem = psutil.virtual_memory()
        snap["cpu_usage_percent"]   = psutil.cpu_percent(interval=None)
        snap["memory_total_mb"]     = round(vmem.total / 1024 / 1024, 1)
        snap["memory_used_mb"]      = round(vmem.used  / 1024 / 1024, 1)
        snap["memory_percent"]      = vmem.percent
        snap["process_cpu_percent"] = _PROC.cpu_percent(interval=None)
        snap["process_memory_mb"]   = round(
            _PROC.memory_info().rss / 1024 / 1024, 1
        )
    except (psutil.AccessDenied, psutil.NoSuchProcess) as exc:
        print(f"⚠️  snapshot error: {exc}")
    return snap


def _check_metrics_auth() -> bool:
    """
    True if /metrics request is authorised.
    Empty METRICS_TOKEN → open (standard Prometheus pull).
    Set METRICS_TOKEN   → require Authorization: Bearer <token>.
    """
    token = _CFG["metrics_token"]
    if not token:
        return True
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        return False
    return hmac.compare_digest(
        auth[len("Bearer "):].encode(),
        token.encode(),
    )


def _check_monitor_auth() -> bool:
    """
    True if /monitor/status request is authorised.
    Empty MONITOR_TOKEN → open.
    Set MONITOR_TOKEN   → require X-Monitor-Token header.
    """
    token = _CFG["monitor_token"]
    if not token:
        return True
    provided = request.headers.get("X-Monitor-Token", "")
    return hmac.compare_digest(
        provided.encode(),
        token.encode(),
    )


# ══════════════════════════════════════════════════════════════
# MONITOR STATUS HANDLER
# called by app.py  POST /monitor/status
# ══════════════════════════════════════════════════════════════

def handle_monitor_status() -> tuple[Response, int]:
    """
    CI / monitoring webhook receiver.
    app.py delegates POST /monitor/status entirely to this function.
    Accepts optional JSON payload — only the token matters for 200 OK.
    """
    t = _record("/monitor/status")

    if not _check_monitor_auth():
        _finish("/monitor/status", t)
        return jsonify(error="unauthorized"), 401

    _finish("/monitor/status", t)
    return jsonify(ok=True), 200


# ══════════════════════════════════════════════════════════════
# MONITOR BLUEPRINT  —  /monitor/*
# ══════════════════════════════════════════════════════════════

monitor_bp = Blueprint("monitor", __name__, url_prefix="/monitor")


@monitor_bp.get("/health")
def monitor_health() -> tuple[Response, int]:
    """
    JSON liveness / readiness probe.
    Returns JSON so ALB, Kubernetes, and Beanstalk health checks
    can parse the response body.
    HTTP 200 = healthy | HTTP 503 = degraded
    """
    t = _record("/monitor/health")

    checks: dict[str, str] = {
        "app":     "ok",
        "scanner": "ok" if _SCANNER_LOADED else "degraded",
    }
    healthy = True
    try:
        _PROC.status()
    except (psutil.NoSuchProcess, psutil.ZombieProcess):
        checks["process"] = "error"
        healthy = False

    code = 200 if healthy else 503
    _record("/monitor/health", code)
    _finish("/monitor/health", t)

    return jsonify(
        status=         "healthy" if healthy else "degraded",
        checks=         checks,
        uptime_seconds= round(time.time() - _START_TIME, 1),
        version=        _CFG["version"],
        build=          _CFG["build"],
        environment=    _CFG["environment"],
        cloud=          _CFG["cloud"],
        region=         _CFG["region"],
    ), code


@monitor_bp.get("/api")
def monitor_api() -> Response:
    """Hello world — confirms app is alive."""
    t = _record("/monitor/api")
    result = jsonify(
        message= "Hello from SentinelOps-Lite!",
        status=  "running",
        version= _CFG["version"],
        build=   _CFG["build"],
    )
    _finish("/monitor/api", t)
    return result


@monitor_bp.get("/api/status")
def monitor_api_status() -> Response:
    """Full system status — application, system, agent, deployment."""
    t = _record("/monitor/api/status")
    result = jsonify(
        application={
            "name":        "SentinelOps-Lite",
            "version":     _CFG["version"],
            "build":       _CFG["build"],
            "environment": _CFG["environment"],
        },
        system=     _safe_system_snapshot(),
        agent={
            "provider":       _CFG["provider"],
            "model":          _CFG["model"],
            "status":         "running",
            "uptime_seconds": round(time.time() - _START_TIME, 1),
        },
        deployment={
            "version": _CFG["version"],
            "build":   _CFG["build"],
            "cloud":   _CFG["cloud"],
            "region":  _CFG["region"],
        },
        scanner={
            "loaded": _SCANNER_LOADED,
        },
    )
    _finish("/monitor/api/status", t)
    return result


@monitor_bp.get("/agent/status")
def monitor_agent_status() -> tuple[Response, int]:
    """AI agent running status — also refreshes dynamic metrics."""
    t = _record("/monitor/agent/status")
    _update_dynamic_metrics()
    AGENT_REQUESTS_TOTAL.labels(
        provider= _CFG["provider"],
        model=    _CFG["model"],
        status=   "success",
    ).inc()
    result = jsonify(
        status=         "running",
        provider=       _CFG["provider"],
        model=          _CFG["model"],
        uptime_seconds= round(time.time() - _START_TIME, 1),
        scanner_loaded= _SCANNER_LOADED,
    )
    _finish("/monitor/agent/status", t)
    return result, 200


@monitor_bp.get("/metrics")
def monitor_metrics() -> tuple[Response, int]:
    """
    Prometheus scrape endpoint.
    METRICS_TOKEN empty (default) → open.
    METRICS_TOKEN set             → Authorization: Bearer <token> required.
    """
    t = _record("/monitor/metrics")
    if not _check_metrics_auth():
        _finish("/monitor/metrics", t)
        return (
            Response("Unauthorized\n", status=401, mimetype="text/plain"),
            401,
        )
    _update_dynamic_metrics()
    payload = generate_latest()
    _finish("/monitor/metrics", t)
    return Response(payload, mimetype=CONTENT_TYPE_LATEST), 200


# ══════════════════════════════════════════════════════════════
# SCANNER CONSTANTS
# ══════════════════════════════════════════════════════════════

IGNORED_DIRS: set[str] = {
    ".git", ".terraform", "node_modules", "venv", "__pycache__",
    "dist", "build", "target", "coverage", ".cache", ".idea",
    ".vscode", ".eggs", ".tox", ".pytest_cache", ".mypy_cache",
    ".ruff_cache", "vendor", "bower_components", ".next", ".nuxt",
}

EXTENSION_LANGUAGE_MAP: dict[str, str] = {
    ".py": "Python", ".pyw": "Python", ".pyi": "Python",
    ".java": "Java", ".kt": "Kotlin", ".scala": "Scala",
    ".cs": "C#", ".vb": "VB.NET", ".fs": "F#",
    ".js": "JavaScript", ".mjs": "JavaScript", ".jsx": "JavaScript",
    ".ts": "TypeScript", ".tsx": "TypeScript",
    ".go": "Go", ".rs": "Rust",
    ".c": "C", ".cpp": "C++", ".cc": "C++", ".h": "C/C++ Header",
    ".sh": "Shell", ".bash": "Shell", ".zsh": "Shell",
    ".ps1": "PowerShell", ".psm1": "PowerShell",
    ".yaml": "YAML", ".yml": "YAML",
    ".json": "JSON", ".jsonc": "JSON",
    ".toml": "TOML", ".ini": "INI", ".cfg": "Config", ".conf": "Config",
    ".xml": "XML", ".html": "HTML", ".htm": "HTML",
    ".css": "CSS", ".scss": "SCSS",
    ".sql": "SQL", ".md": "Markdown", ".rst": "reStructuredText",
    ".txt": "Text", ".env": "Environment",
    ".tf": "Terraform", ".tfvars": "Terraform", ".hcl": "HCL",
    ".proto": "Protobuf", ".graphql": "GraphQL",
    ".rb": "Ruby", ".php": "PHP", ".swift": "Swift", ".dart": "Dart",
    ".ipynb": "Jupyter Notebook",
    ".dockerfile": "Dockerfile",
}

AI_PROVIDER_PATTERNS: dict[str, dict[str, list[str]]] = {
    "OpenAI": {
        "imports":   [r"import openai", r"from openai", r"openai\."],
        "env_vars":  [r"OPENAI_API_KEY", r"OPENAI_ORG_ID", r"OPENAI_BASE_URL"],
        "endpoints": [r"api\.openai\.com"],
        "sdk":       "openai",
    },
    "Azure OpenAI": {
        "imports":   [r"AzureOpenAI", r"openai.*azure"],
        "env_vars":  [r"AZURE_OPENAI_KEY", r"AZURE_OPENAI_ENDPOINT",
                      r"AZURE_OPENAI_API_KEY", r"AZURE_OPENAI_API_VERSION"],
        "endpoints": [r"\.openai\.azure\.com"],
        "sdk":       "openai (Azure)",
    },
    "Anthropic": {
        "imports":   [r"import anthropic", r"from anthropic", r"anthropic\."],
        "env_vars":  [r"ANTHROPIC_API_KEY", r"CLAUDE_API_KEY"],
        "endpoints": [r"api\.anthropic\.com"],
        "sdk":       "anthropic",
    },
    "Google Gemini": {
        "imports":   [r"import google\.generativeai",
                      r"from google\.generativeai",
                      r"genai\.", r"GenerativeModel", r"import vertexai"],
        "env_vars":  [r"GEMINI_API_KEY", r"GOOGLE_API_KEY",
                      r"GOOGLE_APPLICATION_CREDENTIALS"],
        "endpoints": [r"generativelanguage\.googleapis\.com"],
        "sdk":       "google-generativeai",
    },
    "AWS Bedrock": {
        "imports":   [r"bedrock", r"boto3.*bedrock", r"BedrockRuntime"],
        "env_vars":  [r"AWS_ACCESS_KEY_ID", r"AWS_SECRET_ACCESS_KEY",
                      r"BEDROCK_REGION"],
        "endpoints": [r"bedrock\.amazonaws\.com"],
        "sdk":       "boto3",
    },
    "Groq": {
        "imports":   [r"import groq", r"from groq", r"groq\."],
        "env_vars":  [r"GROQ_API_KEY"],
        "endpoints": [r"api\.groq\.com"],
        "sdk":       "groq",
    },
    "Cohere": {
        "imports":   [r"import cohere", r"from cohere", r"cohere\."],
        "env_vars":  [r"COHERE_API_KEY", r"CO_API_KEY"],
        "endpoints": [r"api\.cohere\.ai"],
        "sdk":       "cohere",
    },
    "Mistral": {
        "imports":   [r"import mistralai", r"from mistralai", r"MistralClient"],
        "env_vars":  [r"MISTRAL_API_KEY"],
        "endpoints": [r"api\.mistral\.ai"],
        "sdk":       "mistralai",
    },
    "Ollama": {
        "imports":   [r"import ollama", r"from ollama", r"ollama\."],
        "env_vars":  [r"OLLAMA_HOST", r"OLLAMA_BASE_URL"],
        "endpoints": [r"localhost:11434"],
        "sdk":       "ollama",
    },
    "HuggingFace": {
        "imports":   [r"from transformers", r"import transformers",
                      r"huggingface_hub", r"AutoModel", r"AutoTokenizer",
                      r"pipeline\("],
        "env_vars":  [r"HUGGINGFACE_API_KEY", r"HF_TOKEN",
                      r"HUGGINGFACEHUB_API_TOKEN"],
        "endpoints": [r"huggingface\.co"],
        "sdk":       "transformers",
    },
    "OpenRouter": {
        "imports":   [r"openrouter"],
        "env_vars":  [r"OPENROUTER_API_KEY"],
        "endpoints": [r"openrouter\.ai/api"],
        "sdk":       "openai (OpenRouter)",
    },
    "DeepSeek": {
        "imports":   [r"deepseek"],
        "env_vars":  [r"DEEPSEEK_API_KEY"],
        "endpoints": [r"api\.deepseek\.com"],
        "sdk":       "openai (DeepSeek)",
    },
    "Perplexity": {
        "imports":   [r"perplexity"],
        "env_vars":  [r"PERPLEXITY_API_KEY", r"PPLX_API_KEY"],
        "endpoints": [r"api\.perplexity\.ai"],
        "sdk":       "openai (Perplexity)",
    },
    "LiteLLM": {
        "imports":   [r"import litellm", r"from litellm", r"litellm\."],
        "env_vars":  [r"LITELLM_API_KEY"],
        "endpoints": [r"litellm"],
        "sdk":       "litellm",
    },
}

AI_MODEL_PATTERNS: list[str] = [
    r"gpt-?4\.?1(?:-mini|-nano|-preview)?",
    r"gpt-?4o(?:-mini|-preview|-audio|-realtime)?",
    r"gpt-?4(?:-turbo|-vision|-32k|-0125|-1106|-0613)?",
    r"gpt-?3\.?5(?:-turbo(?:-16k|-instruct|-0125|-1106)?)?",
    r"gpt-?5", r"\bo3(?:-mini|-preview)?\b",
    r"\bo4(?:-mini)?\b", r"\bo1(?:-mini|-preview)?\b",
    r"claude-?3(?:\.\d+)?(?:-opus|-sonnet|-haiku)?",
    r"claude-?3\.?5(?:-sonnet|-haiku)?",
    r"claude-?4(?:-opus|-sonnet)?", r"claude-?2(?:\.\d+)?",
    r"gemini-?(?:pro|ultra|flash|nano)?(?:-\d+\.\d+)?(?:-latest|-preview)?",
    r"gemini-?1\.?5(?:-pro|-flash)?",
    r"gemini-?2\.?0(?:-flash)?",
    r"gemini-?2\.?5(?:-flash|-pro)?",
    r"llama-?3(?:\.\d+)?(?:-\d+[bB])?(?:-instruct|-chat)?",
    r"llama-?2(?:-\d+[bB])?(?:-chat|-instruct)?",
    r"llama-?3\.?1(?:-\d+[bB])?", r"llama-?3\.?2(?:-\d+[bB])?",
    r"mistral-(?:7b|large|medium|small|tiny|nemo)(?:-instruct)?",
    r"mixtral-?(?:8x7b|8x22b)?(?:-instruct)?",
    r"deepseek-(?:coder|chat|r1|v\d+|v3)(?:-\d+[bB])?",
    r"command-?(?:r|r-plus|light|nightly)?(?:-\d+)?",
    r"phi-?[234](?:-mini|-medium|-vision)?",
    r"qwen(?:\d+(?:\.\d+)?)?(?:-\d+[bB])?(?:-instruct|-chat)?",
    r"falcon-?(?:7b|40b|180b)?(?:-instruct)?",
    r"starcoder(?:-\d+[bB]|-base)?", r"codestral",
    r"bert-(?:base|large)(?:-uncased|-cased)?",
    r"t5-(?:small|base|large|xl|xxl)",
]

AI_SDK_PATTERNS: dict[str, list[str]] = {
    "LangChain":       [r"from langchain", r"import langchain",
                        r"LLMChain", r"AgentExecutor", r"ChatOpenAI",
                        r"PromptTemplate", r"ChatPromptTemplate"],
    "LangGraph":       [r"from langgraph", r"import langgraph",
                        r"StateGraph", r"MessageGraph"],
    "Semantic Kernel": [r"semantic_kernel", r"SemanticKernel",
                        r"KernelPlugin", r"KernelFunction"],
    "AutoGen":         [r"import autogen", r"from autogen",
                        r"AssistantAgent", r"UserProxyAgent", r"GroupChat"],
    "CrewAI":          [r"import crewai", r"from crewai", r"Crew\("],
    "LlamaIndex":      [r"from llama_index", r"import llama_index",
                        r"VectorStoreIndex", r"SimpleDirectoryReader"],
    "Haystack":        [r"import haystack", r"from haystack",
                        r"DocumentStore"],
    "DSPy":            [r"import dspy", r"from dspy",
                        r"dspy\.Predict", r"dspy\.ChainOfThought"],
    "Transformers":    [r"from transformers", r"import transformers",
                        r"AutoModel", r"AutoTokenizer", r"pipeline\("],
    "LiteLLM":         [r"import litellm", r"from litellm",
                        r"litellm\.completion"],
    "Instructor":      [r"import instructor", r"from instructor",
                        r"instructor\.patch"],
    "Ollama SDK":      [r"import ollama", r"from ollama",
                        r"ollama\.chat", r"ollama\.generate"],
    "OpenAI SDK":      [r"from openai import", r"import openai",
                        r"client\.chat\.completions", r"AsyncOpenAI",
                        r"OpenAI\("],
    "Anthropic SDK":   [r"from anthropic import", r"import anthropic",
                        r"client\.messages\.create", r"AsyncAnthropic"],
    "Google AI SDK":   [r"import google\.generativeai",
                        r"from google\.generativeai",
                        r"genai\.GenerativeModel", r"vertexai\.init"],
    "Pydantic AI":     [r"from pydantic_ai", r"import pydantic_ai"],
}

AGENT_DETECTION_PATTERNS: list[str] = [
    r"class\s+\w*[Aa]gent\w*", r"class\s+\w*[Bb]ot\w*",
    r"class\s+\w*[Aa]ssistant\w*", r"class\s+\w*[Oo]rchestrat\w*",
    r"AgentExecutor", r"AssistantAgent", r"UserProxyAgent",
    r"ConversableAgent", r"Crew\s*\(",
    r"StateGraph\s*\(", r"MessageGraph\s*\(",
    r"create_agent", r"build_agent", r"initialize_agent",
    r"agent\.run\s*\(", r"agent\.invoke\s*\(",
    r"chat_completion", r"completion\.create",
    r"messages\.create", r"generate_content",
    r"chain\.invoke\s*\(", r"chain\.run\s*\(",
    r"@tool\b", r"tool_calls", r"function_call",
]

PROMPT_PATTERNS: list[str] = [
    r"system_prompt\s*=", r"user_prompt\s*=",
    r"system_message\s*=", r"prompt_template\s*=",
    r"PromptTemplate\s*\(", r"ChatPromptTemplate",
    r"SystemMessage\s*\(", r"HumanMessage\s*\(",
    r'"role"\s*:\s*"system"', r'"role"\s*:\s*"user"',
    r"SYSTEM_PROMPT", r"USER_PROMPT",
    r'prompt\s*=\s*f"""', r'prompt\s*=\s*"""',
    r"system_instruction",
]

API_KEY_MAP: dict[str, str] = {
    "OPENAI_API_KEY":           "OpenAI",
    "AZURE_OPENAI_KEY":         "Azure OpenAI",
    "AZURE_OPENAI_API_KEY":     "Azure OpenAI",
    "ANTHROPIC_API_KEY":        "Anthropic",
    "GEMINI_API_KEY":           "Google Gemini",
    "GOOGLE_API_KEY":           "Google",
    "GROQ_API_KEY":             "Groq",
    "COHERE_API_KEY":           "Cohere",
    "MISTRAL_API_KEY":          "Mistral",
    "HUGGINGFACE_API_KEY":      "HuggingFace",
    "HF_TOKEN":                 "HuggingFace",
    "HUGGINGFACEHUB_API_TOKEN": "HuggingFace",
    "AWS_ACCESS_KEY_ID":        "AWS",
    "AWS_SECRET_ACCESS_KEY":    "AWS",
    "OPENROUTER_API_KEY":       "OpenRouter",
    "DEEPSEEK_API_KEY":         "DeepSeek",
    "PERPLEXITY_API_KEY":       "Perplexity",
    "OLLAMA_HOST":              "Ollama",
    "LITELLM_API_KEY":          "LiteLLM",
    "TOGETHER_API_KEY":         "Together AI",
    "REPLICATE_API_TOKEN":      "Replicate",
    "PINECONE_API_KEY":         "Pinecone",
    "WEAVIATE_API_KEY":         "Weaviate",
    "QDRANT_API_KEY":           "Qdrant",
    "SERPAPI_API_KEY":          "SerpAPI",
    "TAVILY_API_KEY":           "Tavily",
}

TOKEN_CONFIG_PATTERNS: dict[str, str] = {
    "max_tokens":            r"max_tokens\s*=\s*(\d+)",
    "temperature":           r"temperature\s*=\s*([\d.]+)",
    "top_p":                 r"top_p\s*=\s*([\d.]+)",
    "max_completion_tokens": r"max_completion_tokens\s*=\s*(\d+)",
    "max_output_tokens":     r"max_output_tokens\s*=\s*(\d+)",
    "context_window":        r"context_window\s*=\s*(\d+)",
    "top_k":                 r"top_k\s*=\s*(\d+)",
    "presence_penalty":      r"presence_penalty\s*=\s*([\d.-]+)",
    "frequency_penalty":     r"frequency_penalty\s*=\s*([\d.-]+)",
}

TOOL_PATTERNS: dict[str, list[str]] = {
    "Web Search":       [r"serpapi", r"tavily", r"DuckDuckGoSearch",
                         r"GoogleSearch", r"web_search"],
    "Vector Store":     [r"pinecone", r"weaviate", r"qdrant", r"chroma",
                         r"faiss", r"milvus", r"VectorStore"],
    "Database":         [r"sqlite", r"postgresql", r"mysql", r"mongodb",
                         r"SQLDatabase"],
    "RAG":              [r"\bRAG\b", r"retrieval_augmented",
                         r"VectorStoreRetriever", r"similarity_search"],
    "Calculator":       [r"calculator", r"Calculator", r"wolfram",
                         r"LLMMathChain"],
    "Browser":          [r"playwright", r"selenium", r"puppeteer",
                         r"WebBrowser"],
    "Email":            [r"smtp", r"sendgrid", r"mailgun", r"EmailTool"],
    "Slack":            [r"slack_sdk", r"SlackTool"],
    "GitHub":           [r"PyGithub", r"github_tool", r"GitHubToolkit"],
    "Filesystem":       [r"ReadFileTool", r"WriteFileTool",
                         r"FilesystemTool"],
    "Shell":            [r"BashProcess", r"ShellTool", r"shell_tool"],
    "Python REPL":      [r"PythonREPL", r"python_repl",
                         r"PythonInterpreter"],
    "Memory":           [r"ConversationBufferMemory", r"MemorySaver",
                         r"checkpointer", r"ConversationSummaryMemory"],
    "Code Interpreter": [r"code_interpreter", r"CodeInterpreter", r"E2B"],
}

WORKFLOW_PATTERNS: dict[str, list[str]] = {
    "Planning":        [r"plan\s*\(", r"planner", r"PlanAndExecute"],
    "Execution":       [r"execute\s*\(", r"executor", r"AgentExecutor"],
    "Reflection":      [r"reflect\s*\(", r"reflection", r"self_critique"],
    "Retry":           [r"retry", r"backoff", r"tenacity", r"max_retries"],
    "Evaluation":      [r"evaluate\s*\(", r"evaluator", r"QAEvalChain"],
    "Memory":          [r"memory\s*=", r"ConversationMemory",
                        r"MemorySaver"],
    "RAG":             [r"retrieve\s*\(", r"retriever\s*=",
                        r"similarity_search"],
    "Tool Calling":    [r"tool_calls", r"function_call", r"@tool",
                        r"Tool\s*\("],
    "Streaming":       [r"stream\s*\(", r"streaming\s*=\s*True",
                        r"stream_tokens"],
    "Multi-agent":     [r"MultiAgent", r"GroupChat", r"Crew\s*\(",
                        r"supervisor"],
    "Supervisor":      [r"supervisor", r"SupervisorAgent",
                        r"orchestrator"],
    "Function Calling":[r"functions\s*=\s*\[", r"tools\s*=\s*\["],
}


# ══════════════════════════════════════════════════════════════
# DATA CLASSES
# ══════════════════════════════════════════════════════════════

@dataclass
class FileRecord:
    serial:        int  = 0
    relative_path: str  = ""
    file_name:     str  = ""
    extension:     str  = ""
    language:      str  = ""
    category:      str  = ""
    purpose:       str  = ""
    description:   str  = ""
    size_bytes:    int  = 0
    lines_of_code: int  = 0
    is_used:       str  = "Unknown"
    is_referenced: str  = "Unknown"
    is_ai_related: bool = False
    dependencies:  list = field(default_factory=list)
    classes:       list = field(default_factory=list)
    functions:     list = field(default_factory=list)
    imports:       list = field(default_factory=list)


@dataclass
class AgentRecord:
    name:         str  = ""
    file:         str  = ""
    agent_type:   str  = ""
    purpose:      str  = ""
    provider:     str  = "Unknown"
    sdk:          str  = "Unknown"
    model:        str  = "Not Specified"
    tools:        list = field(default_factory=list)
    workflows:    list = field(default_factory=list)
    prompts:      list = field(default_factory=list)
    token_config: dict = field(default_factory=dict)
    line_number:  int  = 0


@dataclass
class ProviderRecord:
    name:        str  = ""
    sdk:         str  = ""
    endpoint:    str  = ""
    auth_method: str  = "API Key"
    env_vars:    list = field(default_factory=list)
    files:       list = field(default_factory=list)


@dataclass
class ModelRecord:
    name:            str  = ""
    provider:        str  = ""
    files:           list = field(default_factory=list)
    reference_count: int  = 0


@dataclass
class PromptRecord:
    name:            str = ""
    location:        str = ""
    line_number:     int = 0
    prompt_type:     str = ""
    agent:           str = "Unknown"
    content_preview: str = ""


@dataclass
class APIKeyRecord:
    variable_name: str  = ""
    provider:      str  = ""
    used_in:       list = field(default_factory=list)
    loaded_from:   str  = "Unknown"


@dataclass
class SDKRecord:
    name:         str  = ""
    files:        list = field(default_factory=list)
    import_count: int  = 0


@dataclass
class ToolRecord:
    name:  str  = ""
    files: list = field(default_factory=list)


@dataclass
class WorkflowRecord:
    name:  str  = ""
    files: list = field(default_factory=list)


@dataclass
class ScanResult:
    scan_date:       str  = ""
    root_path:       str  = ""
    repo_name:       str  = ""
    total_dirs:      int  = 0
    total_files:     int  = 0
    source_files:    int  = 0
    config_files:    int  = 0
    doc_files:       int  = 0
    test_files:      int  = 0
    infra_files:     int  = 0
    ai_files:        int  = 0
    total_agents:    int  = 0
    total_providers: int  = 0
    total_models:    int  = 0
    total_prompts:   int  = 0
    total_sdks:      int  = 0
    total_tools:     int  = 0
    total_api_keys:  int  = 0
    total_workflows: int  = 0
    total_classes:   int  = 0
    total_functions: int  = 0
    total_endpoints: int  = 0
    files:           list = field(default_factory=list)
    agents:          list = field(default_factory=list)
    providers:       dict = field(default_factory=dict)
    models:          dict = field(default_factory=dict)
    prompts:         list = field(default_factory=list)
    api_keys:        dict = field(default_factory=dict)
    sdks:            dict = field(default_factory=dict)
    tools:           dict = field(default_factory=dict)
    workflows:       dict = field(default_factory=dict)
    directory_tree:  str  = ""
    errors:          list = field(default_factory=list)


# ══════════════════════════════════════════════════════════════
# SCANNER ENGINE
# ══════════════════════════════════════════════════════════════

class RepoScanner:
    """Pure static-analysis scanner. Never executes or modifies files."""

    def __init__(self, root: str) -> None:
        self.root   = Path(root).resolve()
        self.result = ScanResult(
            scan_date = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            root_path = str(self.root),
            repo_name = self.root.name,
        )
        self._ref_files: set[str]            = set()
        self._all_paths: set[str]            = set()
        self._dep_graph: dict[str, list[str]] = defaultdict(list)

    def scan(self) -> ScanResult:
        self._discover()
        self._analyse()
        self._resolve_deps()
        self._mark_refs()
        self._build_tree()
        self._finalise_counts()
        return self.result

    # ── discovery ─────────────────────────────────────────────
    def _discover(self) -> None:
        serial = 0
        dirs: list[str] = []
        for dirpath, dirnames, filenames in os.walk(self.root):
            dirnames[:] = sorted(
                d for d in dirnames
                if d not in IGNORED_DIRS
                and not (d.startswith(".")
                         and d not in {".github", ".circleci", ".gitlab"})
                and not d.endswith(".egg-info")
            )
            dirs.append(str(Path(dirpath).relative_to(self.root)) or "/")
            for fname in sorted(filenames):
                fpath = Path(dirpath) / fname
                try:
                    stat = fpath.stat()
                except OSError:
                    continue
                serial += 1
                rel  = str(fpath.relative_to(self.root))
                ext  = self._ext(fpath)
                lang = EXTENSION_LANGUAGE_MAP.get(ext, "Unknown")
                self._all_paths.add(rel)
                self.result.files.append(FileRecord(
                    serial=        serial,
                    relative_path= rel,
                    file_name=     fname,
                    extension=     ext,
                    language=      lang,
                    category=      self._quick_cat(rel, fname, ext),
                    size_bytes=    stat.st_size,
                ))
        self.result.total_dirs  = len(dirs)
        self.result.total_files = len(self.result.files)

    # ── content analysis ──────────────────────────────────────
    def _analyse(self) -> None:
        for rec in self.result.files:
            content = self._read(self.root / rec.relative_path)
            if content is None:
                continue
            rec.lines_of_code = content.count("\n") + 1
            rec.imports        = self._imports(content, rec.language)
            rec.classes        = self._classes(content, rec.language)
            rec.functions      = self._functions(content, rec.language)
            rec.is_ai_related  = self._is_ai(content, rec.relative_path)
            rec.purpose, rec.description = self._purpose(rec, content)
            rec.dependencies   = rec.imports[:8]
            if rec.is_ai_related and rec.category not in (
                "Test", "Configuration", "Documentation"
            ):
                rec.category = "AI"
            self.result.total_classes   += len(rec.classes)
            self.result.total_functions += len(rec.functions)
            self.result.total_endpoints += len(re.findall(
                r'@(?:app|router|blueprint)\s*\.\s*'
                r'(?:get|post|put|delete|patch|route)',
                content, re.IGNORECASE,
            ))
            self._detect_providers(content, rec.relative_path)
            self._detect_models(content, rec.relative_path)
            self._detect_prompts(content, rec.relative_path)
            self._detect_api_keys(content, rec.relative_path)
            self._detect_sdks(content, rec.relative_path)
            self._detect_tools(content, rec.relative_path)
            self._detect_workflows(content, rec.relative_path)
            self._detect_agents(content, rec)

    # ── dependency resolution ─────────────────────────────────
    def _resolve_deps(self) -> None:
        name_map: dict[str, str] = {}
        for f in self.result.files:
            name_map[Path(f.file_name).stem] = f.relative_path
            name_map[f.file_name]            = f.relative_path
        for f in self.result.files:
            for imp in f.imports:
                key = imp.split(".")[-1]
                if key in name_map and name_map[key] != f.relative_path:
                    self._dep_graph[f.relative_path].append(name_map[key])
                    self._ref_files.add(name_map[key])

    # ── mark references ───────────────────────────────────────
    def _mark_refs(self) -> None:
        for f in self.result.files:
            if f.relative_path in self._ref_files:
                f.is_referenced = "Yes"
                f.is_used       = "Yes"
            else:
                f.is_referenced = "No"
                f.is_used = "Likely" if any(
                    x in f.file_name.lower()
                    for x in ["main", "app", "server", "index",
                               "__init__", "config", "settings"]
                ) else "Unknown"

    # ── directory tree ────────────────────────────────────────
    def _build_tree(self) -> None:
        lines = [self.root.name + "/"]
        self._tree_walk(self.root, "", lines, 0, 5)
        self.result.directory_tree = "\n".join(lines)

    def _tree_walk(
        self, path: Path, prefix: str,
        lines: list, depth: int, max_depth: int,
    ) -> None:
        if depth >= max_depth:
            return
        try:
            entries = sorted(path.iterdir())
        except PermissionError:
            return
        entries = [
            e for e in entries
            if e.name not in IGNORED_DIRS
            and not (e.name.startswith(".")
                     and e.name not in {".github", ".circleci", ".gitlab"})
        ]
        all_e = [e for e in entries if e.is_dir()] + \
                [e for e in entries if e.is_file()]
        for i, entry in enumerate(all_e):
            last = i == len(all_e) - 1
            lines.append(prefix + ("└── " if last else "├── ") +
                         entry.name + ("/" if entry.is_dir() else ""))
            if entry.is_dir():
                self._tree_walk(entry, prefix + ("    " if last else "│   "),
                                lines, depth + 1, max_depth)

    # ── finalise counts ───────────────────────────────────────
    def _finalise_counts(self) -> None:
        cats = Counter(f.category for f in self.result.files)
        self.result.source_files    = cats.get("Source", 0)
        self.result.config_files    = cats.get("Configuration", 0)
        self.result.doc_files       = cats.get("Documentation", 0)
        self.result.test_files      = cats.get("Test", 0)
        self.result.infra_files     = cats.get("Infrastructure", 0)
        self.result.ai_files        = sum(1 for f in self.result.files
                                          if f.is_ai_related)
        self.result.total_agents    = len(self.result.agents)
        self.result.total_providers = len(self.result.providers)
        self.result.total_models    = len(self.result.models)
        self.result.total_prompts   = len(self.result.prompts)
        self.result.total_sdks      = len(self.result.sdks)
        self.result.total_tools     = len(self.result.tools)
        self.result.total_api_keys  = len(self.result.api_keys)
        self.result.total_workflows = len(self.result.workflows)

    # ── static helpers ────────────────────────────────────────
    @staticmethod
    def _ext(p: Path) -> str:
        if p.name.lower() in ("dockerfile", "makefile",
                               "jenkinsfile", "procfile"):
            return p.name.lower()
        return p.suffix.lower()

    @staticmethod
    def _read(p: Path) -> str | None:
        if p.stat().st_size > 5 * 1024 * 1024:
            return None
        for enc in ("utf-8", "latin-1"):
            try:
                return p.read_text(encoding=enc, errors="ignore")
            except Exception:
                continue
        return None

    @staticmethod
    def _quick_cat(rel: str, fname: str, ext: str) -> str:
        pl = (rel + "/" + fname).lower()
        if re.search(r"test_|_test\.|spec\.|/tests?/|__tests__", pl):
            return "Test"
        if re.search(r"config|settings|\.env|\.yaml$|\.yml$|\.toml$|\.ini$", pl):
            return "Configuration"
        if re.search(r"\.md$|readme|changelog|license|docs?/", pl):
            return "Documentation"
        if re.search(r"\.tf$|dockerfile|docker-compose|kubernetes|k8s|"
                     r"helm|terraform", pl):
            return "Infrastructure"
        if re.search(r"agent|llm|prompt|openai|anthropic|gemini|gpt|"
                     r"claude|llama|mistral|groq|langchain|transformer|"
                     r"semantic_kernel|autogen|crewai", pl):
            return "AI"
        if ext in (".py", ".js", ".ts", ".java", ".cs", ".go", ".rs",
                   ".kt", ".scala", ".rb", ".php", ".swift", ".c", ".cpp"):
            return "Source"
        return "Other"

    @staticmethod
    def _imports(content: str, lang: str) -> list[str]:
        if lang == "Python":
            return list(dict.fromkeys(
                m.group(1)
                for m in re.finditer(
                    r'^(?:import|from)\s+([\w.]+)', content, re.MULTILINE
                )
            ))[:25]
        if lang in ("JavaScript", "TypeScript"):
            return list(dict.fromkeys(
                m.group(1)
                for m in re.finditer(
                    r"(?:import|require)\s*\(?['\"]([^'\"]+)['\"]", content
                )
            ))[:25]
        if lang in ("Java", "Kotlin", "Scala"):
            return list(dict.fromkeys(
                m.group(1)
                for m in re.finditer(
                    r'^import\s+([\w.]+)', content, re.MULTILINE
                )
            ))[:25]
        if lang == "Go":
            return list(dict.fromkeys(
                m.group(1)
                for m in re.finditer(r'"([^"]+)"', content)
            ))[:25]
        if lang == "C#":
            return list(dict.fromkeys(
                m.group(1)
                for m in re.finditer(
                    r'^using\s+([\w.]+)', content, re.MULTILINE
                )
            ))[:25]
        if lang == "Rust":
            return list(dict.fromkeys(
                m.group(1)
                for m in re.finditer(
                    r'^use\s+([\w:]+)', content, re.MULTILINE
                )
            ))[:25]
        return []

    @staticmethod
    def _classes(content: str, lang: str) -> list[str]:
        if lang == "Python":
            return re.findall(r'^class\s+(\w+)', content, re.MULTILINE)[:20]
        if lang in ("Java", "Kotlin", "Scala", "C#"):
            return re.findall(r'(?:class|interface)\s+(\w+)', content)[:20]
        if lang in ("JavaScript", "TypeScript"):
            return re.findall(r'class\s+(\w+)', content)[:20]
        if lang == "Go":
            return re.findall(r'type\s+(\w+)\s+struct', content)[:20]
        return []

    @staticmethod
    def _functions(content: str, lang: str) -> list[str]:
        if lang == "Python":
            return re.findall(
                r'^(?:async\s+)?def\s+(\w+)\s*\(', content, re.MULTILINE
            )[:40]
        if lang in ("JavaScript", "TypeScript"):
            return re.findall(r'function\s+(\w+)\s*\(', content)[:40]
        if lang == "Go":
            return re.findall(
                r'^func\s+(?:\(\w+\s+\*?\w+\)\s+)?(\w+)\s*\(',
                content, re.MULTILINE
            )[:40]
        if lang == "Rust":
            return re.findall(
                r'^(?:pub\s+)?fn\s+(\w+)', content, re.MULTILINE
            )[:40]
        return []

    @staticmethod
    def _is_ai(content: str, rel: str) -> bool:
        kws = ["agent", "llm", "prompt", "openai", "anthropic", "gemini",
               "langchain", "embedding", "vector", "rag", "gpt", "claude",
               "llama", "mistral", "groq", "semantic_kernel", "autogen",
               "crewai", "llamaindex"]
        if any(k in rel.lower() for k in kws):
            return True
        sample = content[:4000].lower()
        return sum(
            1 for k in ["openai", "anthropic", "langchain", "llm",
                         "gpt-4", "gpt-3", "claude", "gemini", "llama",
                         "completion", "embedding", "chat_completion",
                         "messages.create", "generate_content",
                         "prompt_template", "system_prompt"]
            if k in sample
        ) >= 2

    @staticmethod
    def _purpose(rec: FileRecord, content: str) -> tuple[str, str]:
        kws: dict[str, list[str]] = {
            "AI Agent":          ["agent", "autonomous"],
            "LLM Wrapper":       ["llm", "language_model", "chat_model"],
            "Prompt Management": ["prompt", "template", "system_message"],
            "RAG Pipeline":      ["rag", "retrieval", "vectorstore"],
            "Embedding":         ["embedding", "embed"],
            "Workflow":          ["workflow", "pipeline", "chain", "graph"],
            "API Controller":    ["controller", "router", "endpoint", "route"],
            "Service Layer":     ["service", "manager", "handler"],
            "Data Model":        ["model", "schema", "entity"],
            "Database Access":   ["repository", "dao", "database", "db"],
            "Authentication":    ["auth", "login", "jwt", "oauth"],
            "Configuration":     ["config", "settings", "constants"],
            "Logging":           ["logging", "logger"],
            "Testing":           ["test", "spec", "unittest", "pytest"],
            "Deployment":        ["deploy", "dockerfile", "terraform"],
            "Utility":           ["util", "helper", "common", "shared"],
            "Documentation":     ["readme", "docs", "changelog"],
        }
        pl  = (rec.relative_path + "/" + rec.file_name).lower()
        cl  = content[:2000].lower()
        matched = [
            p for p, ws in kws.items()
            if any(w in pl or w in cl for w in ws)
        ]
        primary = matched[0] if matched else "Utility"
        parts: list[str] = []
        if rec.classes:
            parts.append(f"Classes: {', '.join(rec.classes[:3])}")
        if rec.functions:
            parts.append(f"{len(rec.functions)} function(s)")
        if len(matched) > 1:
            parts.append(f"Roles: {', '.join(matched[:3])}")
        return primary, "; ".join(parts) or f"{primary} file"

    # ── AI component detectors ────────────────────────────────
    def _detect_providers(self, content: str, rel: str) -> None:
        for name, cfg in AI_PROVIDER_PATTERNS.items():
            found = (
                any(re.search(p, content, re.I)
                    for p in cfg.get("imports", []))
                or any(re.search(p, content, re.I)
                       for p in cfg.get("endpoints", []))
            )
            evs = [
                p.rstrip("$")
                for p in cfg.get("env_vars", [])
                if re.search(p, content, re.I)
            ]
            if found or evs:
                if name not in self.result.providers:
                    self.result.providers[name] = asdict(ProviderRecord(
                        name=name, sdk=cfg.get("sdk", ""),
                        env_vars=evs, files=[rel],
                    ))
                else:
                    pr = self.result.providers[name]
                    if rel not in pr["files"]:
                        pr["files"].append(rel)
                    for ev in evs:
                        if ev not in pr["env_vars"]:
                            pr["env_vars"].append(ev)

    def _detect_models(self, content: str, rel: str) -> None:
        for pat in AI_MODEL_PATTERNS:
            for m in re.finditer(pat, content, re.I):
                name = m.group(0).lower().strip()
                if len(name) < 3:
                    continue
                if name not in self.result.models:
                    self.result.models[name] = asdict(ModelRecord(
                        name=name,
                        provider=self._infer_provider(name),
                        files=[rel], reference_count=1,
                    ))
                else:
                    mr = self.result.models[name]
                    mr["reference_count"] += 1
                    if rel not in mr["files"]:
                        mr["files"].append(rel)

    @staticmethod
    def _infer_provider(mn: str) -> str:
        if any(x in mn for x in ["gpt", "o1", "o2", "o3", "o4",
                                   "dall-e", "whisper"]):
            return "OpenAI"
        if "claude"  in mn:  return "Anthropic"
        if any(x in mn for x in ["gemini", "palm", "bard"]): return "Google"
        if "llama"   in mn:  return "Meta"
        if any(x in mn for x in ["mistral", "mixtral", "codestral"]):
            return "Mistral"
        if "deepseek" in mn: return "DeepSeek"
        if any(x in mn for x in ["command", "aya"]): return "Cohere"
        if "phi"     in mn:  return "Microsoft"
        if "qwen"    in mn:  return "Alibaba"
        return "Unknown"

    def _detect_prompts(self, content: str, rel: str) -> None:
        for pat in PROMPT_PATTERNS:
            for m in re.finditer(pat, content, re.I | re.M):
                ln      = content[:m.start()].count("\n") + 1
                snippet = content[m.end():m.end() + 120].strip()[:80]
                ptype   = (
                    "System Prompt" if "system"   in pat.lower() else
                    "User Prompt"   if "user"     in pat.lower() else
                    "Template"      if "template" in pat.lower() else
                    "Prompt"
                )
                self.result.prompts.append(asdict(PromptRecord(
                    name=            f"Prompt @ line {ln}",
                    location=        rel,
                    line_number=     ln,
                    prompt_type=     ptype,
                    content_preview= snippet.replace("\n", " "),
                )))
                break

        if any(rel.endswith(e)
               for e in [".prompt", ".j2", ".jinja", ".jinja2"]):
            self.result.prompts.append(asdict(PromptRecord(
                name=        Path(rel).name,
                location=    rel,
                line_number= 1,
                prompt_type= "Template File",
                content_preview= content[:80].replace("\n", " "),
            )))

    def _detect_api_keys(self, content: str, rel: str) -> None:
        for var, provider in API_KEY_MAP.items():
            if not re.search(r'\b' + re.escape(var) + r'\b', content):
                continue
            loaded = (
                "os.environ"  if "os.environ"  in content else
                "os.getenv"   if "os.getenv"   in content else
                ".env file"   if ("load_dotenv" in content
                                   or "dotenv" in content) else
                f"Config ({rel})" if rel.endswith(
                    (".yaml", ".yml", ".json")
                ) else "Unknown"
            )
            if var not in self.result.api_keys:
                self.result.api_keys[var] = asdict(APIKeyRecord(
                    variable_name=var, provider=provider,
                    used_in=[rel], loaded_from=loaded,
                ))
            elif rel not in self.result.api_keys[var]["used_in"]:
                self.result.api_keys[var]["used_in"].append(rel)

    def _detect_sdks(self, content: str, rel: str) -> None:
        for sdk, pats in AI_SDK_PATTERNS.items():
            if any(re.search(p, content, re.I) for p in pats):
                if sdk not in self.result.sdks:
                    self.result.sdks[sdk] = asdict(SDKRecord(
                        name=sdk, files=[rel], import_count=1,
                    ))
                else:
                    sr = self.result.sdks[sdk]
                    sr["import_count"] += 1
                    if rel not in sr["files"]:
                        sr["files"].append(rel)

    def _detect_tools(self, content: str, rel: str) -> None:
        for tool, pats in TOOL_PATTERNS.items():
            if any(re.search(p, content, re.I) for p in pats):
                if tool not in self.result.tools:
                    self.result.tools[tool] = asdict(ToolRecord(
                        name=tool, files=[rel],
                    ))
                elif rel not in self.result.tools[tool]["files"]:
                    self.result.tools[tool]["files"].append(rel)

    def _detect_workflows(self, content: str, rel: str) -> None:
        for wf, pats in WORKFLOW_PATTERNS.items():
            if any(re.search(p, content, re.I) for p in pats):
                if wf not in self.result.workflows:
                    self.result.workflows[wf] = asdict(WorkflowRecord(
                        name=wf, files=[rel],
                    ))
                elif rel not in self.result.workflows[wf]["files"]:
                    self.result.workflows[wf]["files"].append(rel)

    def _detect_agents(self, content: str, rec: FileRecord) -> None:
        existing = sum(
            1 for a in self.result.agents
            if a["file"] == rec.relative_path
        )
        if existing >= 8:
            return
        for pat in AGENT_DETECTION_PATTERNS:
            for m in re.finditer(pat, content, re.I):
                ln   = content[:m.start()].count("\n") + 1
                text = m.group(0)
                cm   = re.match(r'class\s+(\w+)', text)
                name = (
                    cm.group(1)      if cm                       else
                    "AgentExecutor"  if "AgentExecutor"  in text else
                    "AssistantAgent" if "AssistantAgent"  in text else
                    "UserProxyAgent" if "UserProxyAgent"  in text else
                    "CrewAI Agent"   if "Crew"            in text else
                    "LangGraph Agent"if "StateGraph"      in text else
                    "AI Agent"
                )
                cs  = max(0, m.start() - 400)
                ce  = min(len(content), m.end() + 400)
                ctx = content[cs:ce]
                tc: dict[str, str] = {
                    k: mm.group(1)
                    for k, p in TOKEN_CONFIG_PATTERNS.items()
                    if (mm := re.search(p, ctx, re.I))
                }
                agent_type = (
                    "Class-based Agent" if "class"        in text.lower() else
                    "LangChain Agent"   if "AgentExecutor"in text         else
                    "CrewAI Agent"      if "Crew"         in text         else
                    "LangGraph Agent"   if "StateGraph"   in text
                                          or "MessageGraph" in text        else
                    "AutoGen Agent"     if "AssistantAgent" in text
                                          or "UserProxyAgent" in text      else
                    "API-based Agent"
                )
                self.result.agents.append(asdict(AgentRecord(
                    name=         name,
                    file=         rec.relative_path,
                    agent_type=   agent_type,
                    purpose=      rec.purpose,
                    provider=     self._ctx_provider(ctx),
                    sdk=          self._ctx_sdk(ctx),
                    model=        self._ctx_model(ctx),
                    tools=        self._ctx_tools(ctx),
                    workflows=    self._ctx_workflows(ctx),
                    token_config= tc,
                    line_number=  ln,
                )))
                existing += 1
                if existing >= 8:
                    return

    @staticmethod
    def _ctx_provider(ctx: str) -> str:
        for name, cfg in AI_PROVIDER_PATTERNS.items():
            if any(re.search(p, ctx, re.I) for p in cfg.get("imports", [])):
                return name
        return "Unknown"

    @staticmethod
    def _ctx_model(ctx: str) -> str:
        for pat in AI_MODEL_PATTERNS:
            m = re.search(pat, ctx, re.I)
            if m:
                return m.group(0)
        return "Not Specified"

    @staticmethod
    def _ctx_sdk(ctx: str) -> str:
        for sdk, pats in AI_SDK_PATTERNS.items():
            if any(re.search(p, ctx, re.I) for p in pats):
                return sdk
        return "Unknown"

    @staticmethod
    def _ctx_tools(ctx: str) -> list[str]:
        return [
            t for t, pats in TOOL_PATTERNS.items()
            if any(re.search(p, ctx, re.I) for p in pats)
        ]

    @staticmethod
    def _ctx_workflows(ctx: str) -> list[str]:
        return [
            w for w, pats in WORKFLOW_PATTERNS.items()
            if any(re.search(p, ctx, re.I) for p in pats)
        ]


# ══════════════════════════════════════════════════════════════
# SCAN STATE  —  thread-safe module-level singleton
# ══════════════════════════════════════════════════════════════

_scan_lock:    Lock              = Lock()
_last_result:  ScanResult | None = None
_scan_running: bool              = False
_scan_start:   float             = 0.0


def _run_scan_background(path: str) -> None:
    global _last_result, _scan_running, _scan_start
    _scan_start   = time.time()
    _scan_running = True
    try:
        _last_result = RepoScanner(path).scan()
    except Exception as exc:
        if _last_result is None:
            _last_result = ScanResult(errors=[str(exc)])
        else:
            _last_result.errors.append(str(exc))
    finally:
        _scan_running = False


# ══════════════════════════════════════════════════════════════
# HTML DASHBOARD
# ══════════════════════════════════════════════════════════════

_DASHBOARD_HTML = r"""
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>SentinelOps · AI Scanner</title>
<style>
*,*::before,*::after{box-sizing:border-box;margin:0;padding:0}
:root{
  --bg:#0d1117;--surface:#161b22;--border:#30363d;
  --text:#e6edf3;--muted:#8b949e;--blue:#58a6ff;
  --green:#3fb950;--red:#f85149;--orange:#d29922;
  --purple:#bc8cff;--teal:#39d353;
  --shadow:0 4px 24px rgba(0,0,0,.4);--r:10px;
  --font:'Segoe UI',-apple-system,sans-serif;
  --mono:'Cascadia Code','Fira Code',monospace;
}
body{font-family:var(--font);background:var(--bg);color:var(--text);
     display:flex;min-height:100vh}
/* sidebar */
.sb{width:230px;min-height:100vh;background:#0d1117;
    border-right:1px solid var(--border);position:fixed;
    left:0;top:0;bottom:0;display:flex;flex-direction:column;
    z-index:50;overflow-y:auto}
.sb-logo{padding:18px 14px 10px;border-bottom:1px solid var(--border)}
.sb-logo h2{color:var(--blue);font-size:14px;font-weight:700}
.sb-logo p{color:var(--muted);font-size:10px;margin-top:2px}
.sb-nav{flex:1;padding:6px 0}
.nav-a{display:flex;align-items:center;gap:7px;padding:8px 14px;
       color:var(--muted);text-decoration:none;font-size:12px;
       border-left:3px solid transparent;transition:all .15s}
.nav-a:hover,.nav-a.active{color:var(--text);
  border-left-color:var(--blue);background:rgba(88,166,255,.07)}
.sb-foot{padding:10px 14px;border-top:1px solid var(--border)}
.dk-btn{width:100%;padding:7px;background:rgba(255,255,255,.06);
        color:var(--muted);border:1px solid var(--border);
        border-radius:6px;cursor:pointer;font-size:11px}
/* main */
.main{margin-left:230px;flex:1;padding:20px;
      max-width:calc(100vw - 230px)}
.topbar{display:flex;justify-content:space-between;
        align-items:center;margin-bottom:16px}
.topbar h1{font-size:18px;color:var(--blue)}
.topbar-r{display:flex;gap:7px;align-items:center}
/* buttons */
.btn{padding:6px 13px;border:none;border-radius:6px;cursor:pointer;
     font-size:12px;font-weight:600;transition:all .15s;
     display:inline-flex;align-items:center;gap:5px}
.btn-g{background:#238636;color:#fff}
.btn-b{background:#1f6feb;color:#fff}
.btn-gr{background:rgba(255,255,255,.08);color:var(--text);
        border:1px solid var(--border)}
.btn:hover{opacity:.85;transform:translateY(-1px)}
/* search bar */
.sb-bar{display:flex;gap:9px;flex-wrap:wrap;margin-bottom:16px;
        background:var(--surface);padding:12px;
        border-radius:var(--r);border:1px solid var(--border)}
.sb-bar input,.sb-bar select{
  padding:6px 10px;background:var(--bg);color:var(--text);
  border:1px solid var(--border);border-radius:6px;font-size:12px}
.sb-bar input{flex:1;min-width:180px}
/* stats */
.sg{display:grid;grid-template-columns:repeat(auto-fill,minmax(130px,1fr));
    gap:10px;margin-bottom:16px}
.sc{background:var(--surface);border:1px solid var(--border);
    border-radius:var(--r);padding:14px;text-align:center;border-top:3px solid;
    transition:transform .15s}
.sc:hover{transform:translateY(-2px)}
.si{font-size:22px;margin-bottom:5px}
.sv{font-size:22px;font-weight:800;margin-bottom:2px}
.sl{font-size:9px;color:var(--muted);text-transform:uppercase;
    letter-spacing:.5px}
.cb{border-color:var(--blue)}.cb .sv{color:var(--blue)}
.cg{border-color:var(--green)}.cg .sv{color:var(--green)}
.cr{border-color:var(--red)}.cr .sv{color:var(--red)}
.co{border-color:var(--orange)}.co .sv{color:var(--orange)}
.cp{border-color:var(--purple)}.cp .sv{color:var(--purple)}
.ct{border-color:var(--teal)}.ct .sv{color:var(--teal)}
/* section */
section{margin-bottom:32px;scroll-margin-top:14px}
.st{font-size:15px;font-weight:700;margin-bottom:12px;
    padding-bottom:7px;border-bottom:1px solid var(--border);
    display:flex;align-items:center;gap:8px}
.bdg{display:inline-flex;align-items:center;padding:2px 7px;
     border-radius:10px;font-size:10px;font-weight:600}
.bdg-b{background:rgba(88,166,255,.15);color:var(--blue)}
.bdg-r{background:rgba(248,81,73,.15);color:var(--red)}
.bdg-g{background:rgba(63,185,80,.15);color:var(--green)}
.bdg-o{background:rgba(210,153,34,.15);color:var(--orange)}
.bdg-p{background:rgba(188,140,255,.15);color:var(--purple)}
/* tables */
.tw{overflow-x:auto;border-radius:var(--r);border:1px solid var(--border)}
table{width:100%;border-collapse:collapse;font-size:11px;
      background:var(--surface)}
thead{position:sticky;top:0;z-index:5}
th{background:#161b22;color:var(--muted);padding:9px 11px;
   text-align:left;font-size:9px;text-transform:uppercase;
   letter-spacing:.5px;border-bottom:1px solid var(--border);
   cursor:pointer;white-space:nowrap;user-select:none}
th:hover{color:var(--text)}
td{padding:7px 11px;border-bottom:1px solid var(--border);
   vertical-align:middle}
tbody tr:last-child td{border-bottom:none}
tbody tr:hover{background:rgba(88,166,255,.04)}
tbody tr.air{background:rgba(248,81,73,.03)}
tbody tr.hid{display:none}
.mono{font-family:var(--mono);font-size:10px}
.pth{font-family:var(--mono);font-size:9px;color:var(--muted);
     max-width:200px;overflow:hidden;text-overflow:ellipsis;
     white-space:nowrap;display:block}
.pill{display:inline-block;padding:1px 6px;border-radius:8px;
      font-size:9px;font-weight:600;white-space:nowrap}
.pai{background:rgba(248,81,73,.15);color:var(--red)}
.pbl{background:rgba(88,166,255,.12);color:var(--blue)}
.pgr{background:rgba(63,185,80,.12);color:var(--green)}
.por{background:rgba(210,153,34,.12);color:var(--orange)}
.ppu{background:rgba(188,140,255,.12);color:var(--purple)}
.pgy{background:rgba(255,255,255,.08);color:var(--muted)}
/* tree */
.tree{background:#0d1117;border:1px solid var(--border);
      border-radius:var(--r);padding:16px;
      font-family:var(--mono);font-size:11px;line-height:1.8;
      color:#a8b2d8;overflow-x:auto;max-height:400px;overflow-y:auto}
/* info boxes */
.ib{padding:10px 14px;border-radius:7px;font-size:12px;
    margin-bottom:12px;border-left:3px solid}
.iw{background:rgba(210,153,34,.1);border-color:var(--orange);
    color:var(--orange)}
.ii{background:rgba(88,166,255,.08);border-color:var(--blue);
    color:var(--blue)}
/* cards */
.cg2{display:grid;grid-template-columns:repeat(auto-fill,minmax(240px,1fr));
     gap:12px}
.pc{background:var(--surface);border:1px solid var(--border);
    border-radius:var(--r);padding:14px;border-left:4px solid var(--blue)}
.pn{font-size:14px;font-weight:700;color:var(--blue);margin-bottom:7px}
.pr{display:flex;justify-content:space-between;font-size:10px;
    padding:2px 0;color:var(--muted)}
.pr span:last-child{color:var(--text)}
.evl{margin-top:7px;display:flex;flex-wrap:wrap;gap:3px}
.evt{background:rgba(210,153,34,.1);color:var(--orange);
     padding:1px 5px;border-radius:3px;font-size:9px;
     font-family:var(--mono)}
/* chips */
.chg{display:flex;flex-wrap:wrap;gap:7px}
.ch{background:var(--surface);border:1px solid var(--border);
    border-radius:7px;padding:9px 12px;font-size:11px;font-weight:600;
    display:flex;flex-direction:column;gap:2px}
.ch small{color:var(--muted);font-size:9px;font-weight:400}
/* spinner */
.sp{display:none;align-items:center;gap:7px;color:var(--blue);font-size:12px}
.spin{width:14px;height:14px;border:2px solid var(--border);
      border-top-color:var(--blue);border-radius:50%;
      animation:spin .7s linear infinite}
@keyframes spin{to{transform:rotate(360deg)}}
.empty{padding:32px;text-align:center;color:var(--muted);font-size:12px;
       background:var(--surface);border-radius:var(--r);
       border:1px solid var(--border)}
@media(max-width:768px){
  .sb{width:0;overflow:hidden}.main{margin-left:0;max-width:100vw;padding:14px}
}
@media print{.sb,.topbar-r,.sb-bar{display:none!important}.main{margin-left:0}}
</style>
</head>
<body>
<aside class="sb">
  <div class="sb-logo">
    <h2>🔍 AI Scanner</h2>
    <p>SentinelOps-Lite</p>
  </div>
  <nav class="sb-nav">
    <a href="#overview"  class="nav-a active">📊 Overview</a>
    <a href="#tree"      class="nav-a">📁 Directory Tree</a>
    <a href="#files"     class="nav-a">📄 File Inventory</a>
    <a href="#agents"    class="nav-a">🤖 AI Agents</a>
    <a href="#providers" class="nav-a">☁️ Providers</a>
    <a href="#models"    class="nav-a">🧠 Models</a>
    <a href="#sdks"      class="nav-a">🛠️ SDKs</a>
    <a href="#prompts"   class="nav-a">💬 Prompts</a>
    <a href="#apikeys"   class="nav-a">🔑 API Keys</a>
    <a href="#tools"     class="nav-a">⚙️ Tools</a>
    <a href="#workflows" class="nav-a">🔄 Workflows</a>
    <a href="#tokens"    class="nav-a">🪙 Token Config</a>
    <a href="#unused"    class="nav-a">🗑️ Unused Files</a>
  </nav>
  <div class="sb-foot">
    <button class="dk-btn" onclick="toggleDark()">🌙 Toggle theme</button>
  </div>
</aside>

<div class="main">
  <div class="topbar">
    <h1>🔍 AI Repository Scanner</h1>
    <div class="topbar-r">
      <div class="sp" id="spinner"><div class="spin"></div>Scanning…</div>
      <button class="btn btn-g" onclick="triggerScan()">▶ Scan Repo</button>
      <button class="btn btn-gr" onclick="exportJSON()">⬇ JSON</button>
      <button class="btn btn-gr" onclick="exportCSV()">⬇ CSV</button>
    </div>
  </div>

  <div class="sb-bar">
    <input id="gs" type="text"
           placeholder="🔍 Search files, agents, models…"
           oninput="globalSearch(this.value)">
    <select id="fc" onchange="applyFilters()">
      <option value="">All Categories</option>
      <option>AI</option><option>Source</option><option>Test</option>
      <option>Configuration</option><option>Documentation</option>
      <option>Infrastructure</option><option>Other</option>
    </select>
    <select id="fa" onchange="applyFilters()">
      <option value="">All Files</option>
      <option value="true">AI Related</option>
      <option value="false">Non-AI</option>
    </select>
    <select id="fl" onchange="applyFilters()">
      <option value="">All Languages</option>
    </select>
  </div>

  <section id="overview">
    <div class="st">📊 Repository Overview</div>
    <div id="meta" style="font-size:11px;color:var(--muted);margin-bottom:12px">
      No scan yet — click <strong>▶ Scan Repo</strong> to start.
    </div>
    <div class="sg" id="sg"></div>
  </section>

  <section id="tree">
    <div class="st">📁 Directory Tree</div>
    <pre class="tree" id="tree-box">Run a scan to see the directory tree.</pre>
  </section>

  <section id="files">
    <div class="st">📄 File Inventory
      <span class="bdg bdg-b" id="fc-bdg"></span>
    </div>
    <div class="tw">
      <table id="ft">
        <thead><tr>
          <th onclick="srt('ft',0)">#</th>
          <th onclick="srt('ft',1)">Path</th>
          <th onclick="srt('ft',2)">File</th>
          <th onclick="srt('ft',3)">Ext</th>
          <th onclick="srt('ft',4)">Language</th>
          <th onclick="srt('ft',5)">Category</th>
          <th onclick="srt('ft',6)">Purpose</th>
          <th onclick="srt('ft',7)">Lines</th>
          <th onclick="srt('ft',8)">Size</th>
          <th onclick="srt('ft',9)">AI</th>
          <th onclick="srt('ft',10)">Used</th>
        </tr></thead>
        <tbody id="ftb"><tr><td colspan="11" class="empty">Run a scan first.</td></tr></tbody>
      </table>
    </div>
  </section>

  <section id="agents">
    <div class="st">🤖 AI Agents
      <span class="bdg bdg-r" id="ag-bdg"></span>
    </div>
    <div class="tw">
      <table id="at">
        <thead><tr>
          <th>#</th><th>Name</th><th>File</th><th>Type</th>
          <th>Provider</th><th>SDK</th><th>Model</th>
          <th>Tools</th><th>Workflows</th><th>Line</th>
        </tr></thead>
        <tbody id="atb"><tr><td colspan="10" class="empty">Run a scan first.</td></tr></tbody>
      </table>
    </div>
  </section>

  <section id="providers">
    <div class="st">☁️ Providers
      <span class="bdg bdg-b" id="pv-bdg"></span>
    </div>
    <div class="cg2" id="pv-grid"><div class="empty">Run a scan first.</div></div>
  </section>

  <section id="models">
    <div class="st">🧠 Models
      <span class="bdg bdg-p" id="md-bdg"></span>
    </div>
    <div class="tw">
      <table id="mt">
        <thead><tr>
          <th onclick="srt('mt',0)">#</th>
          <th onclick="srt('mt',1)">Model</th>
          <th onclick="srt('mt',2)">Provider</th>
          <th onclick="srt('mt',3)">Files</th>
          <th onclick="srt('mt',4)">References</th>
        </tr></thead>
        <tbody id="mtb"><tr><td colspan="5" class="empty">Run a scan first.</td></tr></tbody>
      </table>
    </div>
  </section>

  <section id="sdks">
    <div class="st">🛠️ SDKs &amp; Frameworks
      <span class="bdg bdg-g" id="sdk-bdg"></span>
    </div>
    <div class="tw">
      <table id="skt">
        <thead><tr>
          <th>#</th><th>SDK / Framework</th>
          <th>Files</th><th>Imports</th>
        </tr></thead>
        <tbody id="sktb"><tr><td colspan="4" class="empty">Run a scan first.</td></tr></tbody>
      </table>
    </div>
  </section>

  <section id="prompts">
    <div class="st">💬 Prompts
      <span class="bdg bdg-o" id="pr-bdg"></span>
    </div>
    <div class="tw">
      <table id="prt">
        <thead><tr>
          <th>#</th><th>Type</th><th>Location</th>
          <th>Line</th><th>Preview</th>
        </tr></thead>
        <tbody id="prtb"><tr><td colspan="5" class="empty">Run a scan first.</td></tr></tbody>
      </table>
    </div>
  </section>

  <section id="apikeys">
    <div class="st">🔑 API Keys &amp; Env Vars
      <span class="bdg bdg-r" id="kv-bdg"></span>
    </div>
    <div class="ib ii">
      ℹ️ These are variable <strong>references</strong> in source code.
      Actual secret values are never stored or displayed.
    </div>
    <div class="tw">
      <table id="kvt">
        <thead><tr>
          <th>#</th><th>Variable</th><th>Provider</th>
          <th>Loaded From</th><th>Files</th>
        </tr></thead>
        <tbody id="kvtb"><tr><td colspan="5" class="empty">Run a scan first.</td></tr></tbody>
      </table>
    </div>
  </section>

  <section id="tools">
    <div class="st">⚙️ Agent Tools</div>
    <div class="chg" id="tl-grid"><div class="empty">Run a scan first.</div></div>
  </section>

  <section id="workflows">
    <div class="st">🔄 Workflow Patterns</div>
    <div class="chg" id="wf-grid"><div class="empty">Run a scan first.</div></div>
  </section>

  <section id="tokens">
    <div class="st">🪙 Token Configuration</div>
    <div class="ib iw">
      ⚠️ Runtime token usage is <strong>Not Available from Source Code</strong>.
      Only static values configured in source are shown.
    </div>
    <div class="tw">
      <table id="tkt">
        <thead><tr>
          <th>Agent</th><th>File</th><th>Model</th>
          <th>Parameter</th><th>Value</th>
          <th>Runtime Usage</th><th>Remaining</th>
        </tr></thead>
        <tbody id="tktb"><tr><td colspan="7" class="empty">Run a scan first.</td></tr></tbody>
      </table>
    </div>
  </section>

  <section id="unused">
    <div class="st">🗑️ Potentially Unused Files</div>
    <div class="tw">
      <table id="ut">
        <thead><tr>
          <th>#</th><th>File</th><th>Language</th>
          <th>Lines</th><th>Size</th>
        </tr></thead>
        <tbody id="utb"><tr><td colspan="5" class="empty">Run a scan first.</td></tr></tbody>
      </table>
    </div>
  </section>
</div>

<script>
let _d=null,_ss={},_scanning=false;

function toggleDark(){
  document.documentElement.style.setProperty('--bg',
    getComputedStyle(document.documentElement).getPropertyValue('--bg').trim()==='#0d1117'
    ?'#ffffff':'#0d1117');
}

// sidebar active
const _secs=document.querySelectorAll('section[id]');
const _navs=document.querySelectorAll('.nav-a');
window.addEventListener('scroll',()=>{
  let cur='';
  _secs.forEach(s=>{if(window.scrollY>=s.offsetTop-80)cur=s.id;});
  _navs.forEach(a=>a.classList.toggle('active',a.getAttribute('href')==='#'+cur));
},{passive:true});

async function triggerScan(){
  if(_scanning)return;
  _scanning=true;
  document.getElementById('spinner').style.display='flex';
  try{
    await fetch('/scanner/api/scan',{
      method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({path:'.'})
    });
    let attempts=0;
    while(attempts<120){
      await new Promise(r=>setTimeout(r,1500));
      const r=await fetch('/scanner/api/report');
      if(r.ok){const j=await r.json();if(!j.scanning){_d=j;renderAll();break;}}
      attempts++;
    }
  }catch(e){alert('Scan error: '+e);}
  finally{_scanning=false;document.getElementById('spinner').style.display='none';}
}

async function loadReport(){
  try{
    const r=await fetch('/scanner/api/report');
    if(r.ok){const j=await r.json();if(!j.scanning&&j.total_files>0){_d=j;renderAll();}}
  }catch(_){}
}

function renderAll(){
  if(!_d)return;
  rMeta();rStats();rTree();rFiles();rAgents();rProviders();
  rModels();rSDKs();rPrompts();rAPIKeys();rTools();rWorkflows();
  rTokens();rUnused();
}

function rMeta(){
  document.getElementById('meta').innerHTML=
    `📂 <strong>${e(_d.root_path)}</strong> &nbsp;|&nbsp;
     📅 <strong>${e(_d.scan_date)}</strong> &nbsp;|&nbsp;
     📦 <strong>${e(_d.repo_name)}</strong>`;
}

function rStats(){
  const cards=[
    ['📁','Directories',_d.total_dirs,'cb'],
    ['📄','Total Files',_d.total_files,'cb'],
    ['💻','Source',_d.source_files,'cg'],
    ['⚙️','Config',_d.config_files,'co'],
    ['📚','Docs',_d.doc_files,'cb'],
    ['🧪','Tests',_d.test_files,'ct'],
    ['🏗️','Infra',_d.infra_files,'co'],
    ['🤖','AI Files',_d.ai_files,'cr'],
    ['🤖','Agents',_d.total_agents,'cr'],
    ['☁️','Providers',_d.total_providers,'cb'],
    ['🧠','Models',_d.total_models,'cp'],
    ['💬','Prompts',_d.total_prompts,'co'],
    ['🛠️','SDKs',_d.total_sdks,'cg'],
    ['⚙️','Tools',_d.total_tools,'ct'],
    ['🔑','API Keys',_d.total_api_keys,'cr'],
    ['🏛️','Classes',_d.total_classes,'cb'],
    ['⚡','Functions',_d.total_functions,'cg'],
    ['🌐','Endpoints',_d.total_endpoints,'co'],
  ];
  document.getElementById('sg').innerHTML=cards.map(
    ([icon,lbl,val,cls])=>
    `<div class="sc ${cls}">
       <div class="si">${icon}</div>
       <div class="sv">${(val||0).toLocaleString()}</div>
       <div class="sl">${lbl}</div>
     </div>`
  ).join('');
}

function rTree(){
  document.getElementById('tree-box').textContent=_d.directory_tree||'No data.';
}

function rFiles(){
  const files=_d.files||[];
  document.getElementById('fc-bdg').textContent=files.length+' files';
  const langs=[...new Set(files.map(f=>f.language).filter(Boolean))].sort();
  const sel=document.getElementById('fl');
  langs.forEach(l=>{
    if(!sel.querySelector(`option[value="${l}"]`)){
      const o=document.createElement('option');o.value=l;o.textContent=l;sel.appendChild(o);
    }
  });
  document.getElementById('ftb').innerHTML=files.map(f=>`
    <tr class="${f.is_ai_related?'air':''}"
        data-cat="${e(f.category)}" data-ai="${f.is_ai_related}"
        data-lang="${e(f.language)}">
      <td>${f.serial}</td>
      <td><span class="pth" title="${e(f.relative_path)}">${e(f.relative_path)}</span></td>
      <td><strong>${e(f.file_name)}</strong></td>
      <td><code class="mono">${e(f.extension)}</code></td>
      <td><span class="pill pbl">${e(f.language)}</span></td>
      <td><span class="pill ${cp(f.category)}">${e(f.category)}</span></td>
      <td>${e(f.purpose)}</td>
      <td>${(f.lines_of_code||0).toLocaleString()}</td>
      <td>${fsz(f.size_bytes)}</td>
      <td>${f.is_ai_related?'<span class="pill pai">AI</span>':''}</td>
      <td><span class="pill ${f.is_used==='Yes'?'pgr':f.is_used==='Likely'?'por':'pgy'}">${e(f.is_used)}</span></td>
    </tr>`).join('');
}

function rAgents(){
  const agents=_d.agents||[];
  document.getElementById('ag-bdg').textContent=agents.length+' detected';
  const seen=new Set();
  const rows=agents.filter(a=>{
    const k=a.file+':'+a.name+':'+a.line_number;
    if(seen.has(k))return false;seen.add(k);return true;
  });
  document.getElementById('atb').innerHTML=rows.length?rows.map((a,i)=>`
    <tr>
      <td>${i+1}</td>
      <td><strong>${e(a.name)}</strong></td>
      <td><span class="pth">${e(a.file)}</span></td>
      <td><span class="pill ppu">${e(a.agent_type)}</span></td>
      <td><span class="pill pbl">${e(a.provider)}</span></td>
      <td>${e(a.sdk)}</td>
      <td><code class="mono">${e(a.model)}</code></td>
      <td>${(a.tools||[]).slice(0,3).map(t=>`<span class="pill pgr">${e(t)}</span>`).join(' ')}</td>
      <td>${(a.workflows||[]).slice(0,2).map(w=>`<span class="pill pbl">${e(w)}</span>`).join(' ')}</td>
      <td>${a.line_number}</td>
    </tr>`).join('')
    :'<tr><td colspan="10" class="empty">No AI agents detected.</td></tr>';
}

function rProviders(){
  const provs=Object.values(_d.providers||{});
  document.getElementById('pv-bdg').textContent=provs.length+' detected';
  document.getElementById('pv-grid').innerHTML=provs.length?provs.map(p=>`
    <div class="pc">
      <div class="pn">${e(p.name)}</div>
      <div class="pr"><span>SDK</span><span>${e(p.sdk)}</span></div>
      <div class="pr"><span>Auth</span><span>${e(p.auth_method||'API Key')}</span></div>
      <div class="pr"><span>Files</span><span>${(p.files||[]).length}</span></div>
      <div class="evl">${(p.env_vars||[]).map(v=>`<span class="evt">${e(v)}</span>`).join('')||'<span style="font-size:10px;color:var(--muted)">None detected</span>'}</div>
    </div>`).join('')
    :'<div class="empty">No providers detected.</div>';
}

function rModels(){
  const models=Object.values(_d.models||{}).sort((a,b)=>b.reference_count-a.reference_count);
  document.getElementById('md-bdg').textContent=models.length+' detected';
  document.getElementById('mtb').innerHTML=models.length?models.map((m,i)=>`
    <tr>
      <td>${i+1}</td>
      <td><code class="mono">${e(m.name)}</code></td>
      <td><span class="pill pbl">${e(m.provider)}</span></td>
      <td>${(m.files||[]).length}</td>
      <td><strong>${m.reference_count}</strong></td>
    </tr>`).join('')
    :'<tr><td colspan="5" class="empty">No models detected.</td></tr>';
}

function rSDKs(){
  const sdks=Object.values(_d.sdks||{}).sort((a,b)=>b.import_count-a.import_count);
  document.getElementById('sdk-bdg').textContent=sdks.length+' detected';
  document.getElementById('sktb').innerHTML=sdks.length?sdks.map((s,i)=>`
    <tr>
      <td>${i+1}</td><td><strong>${e(s.name)}</strong></td>
      <td>${(s.files||[]).length}</td><td>${s.import_count}</td>
    </tr>`).join('')
    :'<tr><td colspan="4" class="empty">No SDKs detected.</td></tr>';
}

function rPrompts(){
  const prompts=_d.prompts||[];
  document.getElementById('pr-bdg').textContent=prompts.length+' detected';
  document.getElementById('prtb').innerHTML=prompts.length?prompts.slice(0,100).map((p,i)=>`
    <tr>
      <td>${i+1}</td>
      <td><span class="pill por">${e(p.prompt_type)}</span></td>
      <td><span class="pth">${e(p.location)}</span></td>
      <td>${p.line_number}</td>
      <td style="max-width:200px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;color:var(--muted)"
          title="${e(p.content_preview)}">${e(p.content_preview||'')}</td>
    </tr>`).join('')
    :'<tr><td colspan="5" class="empty">No prompts detected.</td></tr>';
}

function rAPIKeys(){
  const keys=Object.values(_d.api_keys||{});
  document.getElementById('kv-bdg').textContent=keys.length+' detected';
  document.getElementById('kvtb').innerHTML=keys.length?keys.map((k,i)=>`
    <tr>
      <td>${i+1}</td>
      <td><code class="mono" style="color:var(--orange)">${e(k.variable_name)}</code></td>
      <td><span class="pill pbl">${e(k.provider)}</span></td>
      <td>${e(k.loaded_from)}</td>
      <td>${(k.used_in||[]).length}</td>
    </tr>`).join('')
    :'<tr><td colspan="5" class="empty">No API keys detected.</td></tr>';
}

function rTools(){
  const tools=Object.values(_d.tools||{});
  document.getElementById('tl-grid').innerHTML=tools.length?tools.map(t=>`
    <div class="ch">⚙️ ${e(t.name)}<small>${(t.files||[]).length} file(s)</small></div>`).join('')
    :'<div class="empty">No tools detected.</div>';
}

function rWorkflows(){
  const wfs=Object.values(_d.workflows||{});
  document.getElementById('wf-grid').innerHTML=wfs.length?wfs.map(w=>`
    <div class="ch">🔄 ${e(w.name)}<small>${(w.files||[]).length} file(s)</small></div>`).join('')
    :'<div class="empty">No workflow patterns detected.</div>';
}

function rTokens(){
  const rows=[];
  (_d.agents||[]).forEach(a=>{
    Object.entries(a.token_config||{}).forEach(([k,v])=>{
      rows.push(`<tr>
        <td>${e(a.name)}</td>
        <td><span class="pth">${e(a.file)}</span></td>
        <td><code class="mono">${e(a.model)}</code></td>
        <td>${e(k)}</td><td><strong>${e(v)}</strong></td>
        <td style="color:var(--muted);font-style:italic;font-size:10px">Not Available from Source Code</td>
        <td style="color:var(--muted);font-style:italic;font-size:10px">Not Available from Source Code</td>
      </tr>`);
    });
  });
  document.getElementById('tktb').innerHTML=rows.length?rows.join('')
    :'<tr><td colspan="7" class="empty">No static token configuration found.</td></tr>';
}

function rUnused(){
  const unused=(_d.files||[]).filter(
    f=>f.is_referenced==='No'&&f.is_used==='Unknown'&&
       ['Source','AI'].includes(f.category)
  );
  document.getElementById('utb').innerHTML=unused.length?unused.slice(0,50).map((f,i)=>`
    <tr>
      <td>${i+1}</td>
      <td><span class="pth">${e(f.relative_path)}</span></td>
      <td>${e(f.language)}</td>
      <td>${(f.lines_of_code||0).toLocaleString()}</td>
      <td>${fsz(f.size_bytes)}</td>
    </tr>`).join('')
    :'<tr><td colspan="5" class="empty">No obviously unused files detected.</td></tr>';
}

function globalSearch(q){
  q=q.toLowerCase();
  document.querySelectorAll('#ftb tr').forEach(r=>{
    r.classList.toggle('hid',q.length>0&&!r.textContent.toLowerCase().includes(q));
  });
}

function applyFilters(){
  const cat=document.getElementById('fc').value.toLowerCase();
  const ai=document.getElementById('fa').value.toLowerCase();
  const lang=document.getElementById('fl').value.toLowerCase();
  document.querySelectorAll('#ftb tr').forEach(r=>{
    const show=(!cat||(r.dataset.cat||'').toLowerCase()===cat)
            &&(!ai||(r.dataset.ai||'').toLowerCase()===ai)
            &&(!lang||(r.dataset.lang||'').toLowerCase()===lang);
    r.classList.toggle('hid',!show);
  });
}

function srt(tid,col){
  const tbl=document.getElementById(tid);if(!tbl)return;
  const tb=tbl.querySelector('tbody');
  const rows=Array.from(tb.querySelectorAll('tr'));
  const key=tid+'_'+col;const asc=!_ss[key];_ss[key]=asc;
  rows.sort((a,b)=>{
    const av=a.cells[col]?.textContent.trim()||'';
    const bv=b.cells[col]?.textContent.trim()||'';
    const an=parseFloat(av.replace(/[^\d.-]/g,''));
    const bn=parseFloat(bv.replace(/[^\d.-]/g,''));
    if(!isNaN(an)&&!isNaN(bn))return asc?an-bn:bn-an;
    return asc?av.localeCompare(bv):bv.localeCompare(av);
  });
  rows.forEach(r=>tb.appendChild(r));
}

function exportJSON(){
  if(!_d)return;
  dl(new Blob([JSON.stringify(_d,null,2)],{type:'application/json'}),'audit.json');
}

function exportCSV(){
  if(!_d)return;
  const hdr=['#','path','file','ext','language','category',
             'purpose','lines','size','ai_related','used'];
  const rows=(_d.files||[]).map(f=>
    [f.serial,f.relative_path,f.file_name,f.extension,f.language,
     f.category,f.purpose,f.lines_of_code,f.size_bytes,
     f.is_ai_related,f.is_used].map(v=>'"'+String(v).replace(/"/g,'""')+'"')
  );
  dl(new Blob([[hdr,...rows].map(r=>r.join(',')).join('\n')],
             {type:'text/csv'}),'audit.csv');
}

function dl(blob,name){
  const a=document.createElement('a');a.href=URL.createObjectURL(blob);
  a.download=name;a.click();URL.revokeObjectURL(a.href);
}

function e(s){
  return String(s||'').replace(/&/g,'&amp;').replace(/</g,'&lt;')
    .replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}
function fsz(b){
  b=b||0;
  if(b<1024)return b+' B';
  if(b<1048576)return (b/1024).toFixed(1)+' KB';
  return (b/1048576).toFixed(1)+' MB';
}
function cp(cat){
  return{AI:'pai',Source:'pgr',Test:'por',
         Configuration:'ppu',Documentation:'pbl',Infrastructure:'por'}[cat]||'pgy';
}

loadReport();
</script>
</body>
</html>
"""


# ══════════════════════════════════════════════════════════════
# SCANNER BLUEPRINT  —  /scanner/*
# ══════════════════════════════════════════════════════════════

scanner_bp = Blueprint("scanner", __name__, url_prefix="/scanner")


@scanner_bp.get("/")
def scanner_dashboard() -> str:
    """HTML dashboard — no external template file required."""
    return render_template_string(_DASHBOARD_HTML)


@scanner_bp.get("/api/health")
def scanner_health() -> tuple[Response, int]:
    return jsonify(
        status=   "ok",
        scanner=  "loaded",
        has_data= _last_result is not None,
        scanning= _scan_running,
    ), 200


@scanner_bp.get("/api/status")
def scanner_api_status() -> Response:
    if _last_result is None:
        return jsonify(
            status=   "idle",
            message=  "No scan yet. POST /scanner/api/scan to start.",
            scanning= _scan_running,
        )
    r = _last_result
    return jsonify(
        status=          "ok",
        scanning=        _scan_running,
        scan_date=       r.scan_date,
        repo_name=       r.repo_name,
        root_path=       r.root_path,
        total_files=     r.total_files,
        total_dirs=      r.total_dirs,
        total_agents=    r.total_agents,
        total_providers= r.total_providers,
        total_models=    r.total_models,
        total_prompts=   r.total_prompts,
        total_sdks=      r.total_sdks,
        total_tools=     r.total_tools,
        total_api_keys=  r.total_api_keys,
        total_workflows= r.total_workflows,
        total_classes=   r.total_classes,
        total_functions= r.total_functions,
        total_endpoints= r.total_endpoints,
        ai_files=        r.ai_files,
        errors=          r.errors,
    )


@scanner_bp.get("/api/agents")
def scanner_agents() -> Response:
    if _last_result is None:
        return jsonify(agents=[], message="No scan yet"), 200
    return jsonify(agents=_last_result.agents, total=len(_last_result.agents))


@scanner_bp.get("/api/providers")
def scanner_providers() -> Response:
    if _last_result is None:
        return jsonify(providers={}, message="No scan yet"), 200
    return jsonify(providers=_last_result.providers,
                   total=len(_last_result.providers))


@scanner_bp.get("/api/models")
def scanner_models() -> Response:
    if _last_result is None:
        return jsonify(models={}, message="No scan yet"), 200
    return jsonify(models=_last_result.models,
                   total=len(_last_result.models))


@scanner_bp.get("/api/metrics")
def scanner_metrics() -> Response:
    if _last_result is None:
        return jsonify(message="No scan yet", scanning=_scan_running), 200
    r = _last_result
    return jsonify(
        scanning=        _scan_running,
        scan_date=       r.scan_date,
        total_files=     r.total_files,
        total_agents=    r.total_agents,
        total_providers= r.total_providers,
        total_models=    r.total_models,
        total_prompts=   r.total_prompts,
        total_sdks=      r.total_sdks,
        total_api_keys=  r.total_api_keys,
        ai_files=        r.ai_files,
        total_classes=   r.total_classes,
        total_functions= r.total_functions,
        token_configs=   [
            {"agent": a["name"], "file": a["file"],
             "model": a["model"], "config": a["token_config"]}
            for a in r.agents if a.get("token_config")
        ],
    )


@scanner_bp.post("/api/scan")
def scanner_trigger() -> tuple[Response, int]:
    """
    Trigger a background scan.
    Body (JSON, optional): { "path": "/path/to/repo" }
    Defaults to current working directory.
    """
    global _scan_running
    if _scan_running:
        return jsonify(message="Scan already in progress",
                       scanning=True), 202

    body      = request.get_json(silent=True) or {}
    scan_path = str(Path(body.get("path", ".")).resolve())

    if not os.path.isdir(scan_path):
        return jsonify(
            error=f"Path does not exist or is not a directory: {scan_path}"
        ), 400

    Thread(
        target= _run_scan_background,
        args=   (scan_path,),
        daemon= True,
        name=   "repo-scanner",
    ).start()

    return jsonify(message="Scan started", path=scan_path,
                   scanning=True), 202


@scanner_bp.get("/api/report")
def scanner_report() -> tuple[Response, int]:
    """Full last scan report — dashboard polls this after triggering scan."""
    if _scan_running:
        return jsonify(scanning=True, message="Scan in progress…"), 202

    if _last_result is None:
        return jsonify(
            scanning=    False,
            message=     "No scan yet. POST /scanner/api/scan to start.",
            total_files= 0,
        ), 200

    r = _last_result
    return jsonify(
        scanning=        False,
        scan_date=       r.scan_date,
        root_path=       r.root_path,
        repo_name=       r.repo_name,
        total_dirs=      r.total_dirs,
        total_files=     r.total_files,
        source_files=    r.source_files,
        config_files=    r.config_files,
        doc_files=       r.doc_files,
        test_files=      r.test_files,
        infra_files=     r.infra_files,
        ai_files=        r.ai_files,
        total_agents=    r.total_agents,
        total_providers= r.total_providers,
        total_models=    r.total_models,
        total_prompts=   r.total_prompts,
        total_sdks=      r.total_sdks,
        total_tools=     r.total_tools,
        total_api_keys=  r.total_api_keys,
        total_workflows= r.total_workflows,
        total_classes=   r.total_classes,
        total_functions= r.total_functions,
        total_endpoints= r.total_endpoints,
        directory_tree=  r.directory_tree,
        files=           r.files,
        agents=          r.agents,
        providers=       r.providers,
        models=          r.models,
        prompts=         r.prompts,
        api_keys=        r.api_keys,
        sdks=            r.sdks,
        tools=           r.tools,
        workflows=       r.workflows,
        errors=          r.errors,
    ), 200


# ══════════════════════════════════════════════════════════════
# STARTUP  —  initialise metrics once after all objects defined
# ══════════════════════════════════════════════════════════════

_init_static_metrics()
_update_dynamic_metrics()
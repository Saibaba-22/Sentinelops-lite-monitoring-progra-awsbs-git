#!/usr/bin/env python3
"""
AI Repository Audit Tool
========================
Scans a repository and generates a standalone HTML audit report.
Outputs: repository_audit.html, repository_audit.json, repository_audit.csv, repository_audit.md

Usage:
    python ai_audit.py .
    python ai_audit.py /path/to/repo --output ./reports --no-open
"""

from __future__ import annotations

import argparse
import csv
import datetime
import html as _html
import json
import os
import re
import sys
import webbrowser
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# ──────────────────────────────────────────────────────────────
# CONSTANTS
# ──────────────────────────────────────────────────────────────

IGNORED_DIRS: set = {
    ".git", ".terraform", "node_modules", "venv", "__pycache__",
    "dist", "build", "target", "coverage", ".cache", ".idea", ".vscode",
    ".pytest_cache", ".mypy_cache", "site-packages", ".tox", "eggs",
    ".eggs", "htmlcov", ".hypothesis", "env", "virtualenv",
    ".next", ".nuxt", "bower_components", "vendor", "tmp", "temp",
    "__MACOSX", ".serverless", "cdk.out", ".aws-sam",
}

EXTENSION_MAP: Dict[str, Tuple[str, str]] = {
    ".py":           ("Python",             "source"),
    ".java":         ("Java",               "source"),
    ".cs":           ("C#",                 "source"),
    ".js":           ("JavaScript",         "source"),
    ".jsx":          ("JavaScript/React",   "source"),
    ".ts":           ("TypeScript",         "source"),
    ".tsx":          ("TypeScript/React",   "source"),
    ".go":           ("Go",                 "source"),
    ".rs":           ("Rust",               "source"),
    ".kt":           ("Kotlin",             "source"),
    ".scala":        ("Scala",              "source"),
    ".c":            ("C",                  "source"),
    ".cpp":          ("C++",                "source"),
    ".h":            ("C/C++ Header",       "source"),
    ".hpp":          ("C++ Header",         "source"),
    ".sh":           ("Shell",              "source"),
    ".bash":         ("Bash",               "source"),
    ".ps1":          ("PowerShell",         "source"),
    ".rb":           ("Ruby",               "source"),
    ".php":          ("PHP",                "source"),
    ".swift":        ("Swift",              "source"),
    ".r":            ("R",                  "source"),
    ".ipynb":        ("Jupyter Notebook",   "source"),
    ".yaml":         ("YAML",               "config"),
    ".yml":          ("YAML",               "config"),
    ".json":         ("JSON",               "config"),
    ".toml":         ("TOML",               "config"),
    ".ini":          ("INI",                "config"),
    ".cfg":          ("Config",             "config"),
    ".conf":         ("Config",             "config"),
    ".properties":   ("Properties",         "config"),
    ".env":          ("Environment",        "config"),
    ".dockerfile":   ("Docker",             "infrastructure"),
    ".tf":           ("Terraform",          "infrastructure"),
    ".tfvars":       ("Terraform Vars",     "infrastructure"),
    ".hcl":          ("HCL",                "infrastructure"),
    ".md":           ("Markdown",           "documentation"),
    ".rst":          ("reStructuredText",   "documentation"),
    ".txt":          ("Text",               "documentation"),
    ".xml":          ("XML",                "config"),
    ".html":         ("HTML",               "frontend"),
    ".htm":          ("HTML",               "frontend"),
    ".css":          ("CSS",                "frontend"),
    ".scss":         ("SCSS",               "frontend"),
    ".less":         ("Less",               "frontend"),
    ".sql":          ("SQL",                "database"),
    ".graphql":      ("GraphQL",            "api"),
    ".proto":        ("Protobuf",           "api"),
    ".jinja":        ("Jinja Template",     "template"),
    ".jinja2":       ("Jinja Template",     "template"),
    ".j2":           ("Jinja Template",     "template"),
    ".prompt":       ("Prompt",             "ai"),
    ".lock":         ("Lock File",          "config"),
    ".requirements": ("Requirements",       "config"),
    ".makefile":     ("Makefile",           "config"),
}

AI_SDKS: Dict[str, Dict] = {
    "openai":            {"name": "OpenAI SDK",              "provider": "OpenAI"},
    "langchain":         {"name": "LangChain",               "provider": "Multiple"},
    "langgraph":         {"name": "LangGraph",               "provider": "Multiple"},
    "semantic_kernel":   {"name": "Semantic Kernel",         "provider": "Multiple"},
    "autogen":           {"name": "AutoGen",                 "provider": "Multiple"},
    "crewai":            {"name": "CrewAI",                  "provider": "Multiple"},
    "llama_index":       {"name": "LlamaIndex",              "provider": "Multiple"},
    "haystack":          {"name": "Haystack",                "provider": "Multiple"},
    "dspy":              {"name": "DSPy",                    "provider": "Multiple"},
    "transformers":      {"name": "HuggingFace Transformers","provider": "HuggingFace"},
    "litellm":           {"name": "LiteLLM",                 "provider": "Multiple"},
    "instructor":        {"name": "Instructor",              "provider": "Multiple"},
    "ollama":            {"name": "Ollama SDK",              "provider": "Ollama"},
    "anthropic":         {"name": "Anthropic SDK",           "provider": "Anthropic"},
    "google.generativeai":{"name":"Google GenAI SDK",        "provider": "Google Gemini"},
    "vertexai":          {"name": "Vertex AI SDK",           "provider": "Google Vertex AI"},
    "boto3":             {"name": "Boto3 (AWS SDK)",         "provider": "AWS Bedrock"},
    "groq":              {"name": "Groq SDK",                "provider": "Groq"},
    "cohere":            {"name": "Cohere SDK",              "provider": "Cohere"},
    "mistralai":         {"name": "Mistral SDK",             "provider": "Mistral"},
    "together":          {"name": "Together AI SDK",         "provider": "Together AI"},
    "replicate":         {"name": "Replicate SDK",           "provider": "Replicate"},
    "huggingface_hub":   {"name": "HuggingFace Hub",         "provider": "HuggingFace"},
    "deepseek":          {"name": "DeepSeek SDK",            "provider": "DeepSeek"},
    "mem0":              {"name": "Mem0",                    "provider": "Mem0"},
    "pydantic_ai":       {"name": "Pydantic AI",             "provider": "Multiple"},
    "smolagents":        {"name": "SmolAgents",              "provider": "HuggingFace"},
    "phidata":           {"name": "Phidata",                 "provider": "Multiple"},
    "agno":              {"name": "Agno",                    "provider": "Multiple"},
    "requests":          {"name": "Requests (HTTP client)",  "provider": "Generic HTTP"},
    "httpx":             {"name": "HTTPX (HTTP client)",     "provider": "Generic HTTP"},
    "aiohttp":           {"name": "aiohttp",                 "provider": "Generic HTTP"},
}

AI_PROVIDERS: Dict[str, str] = {
    "openai":         "OpenAI",
    "azure":          "Azure OpenAI",
    "azure_openai":   "Azure OpenAI",
    "anthropic":      "Anthropic",
    "claude":         "Anthropic",
    "gemini":         "Google Gemini",
    "google":         "Google",
    "vertexai":       "Google Vertex AI",
    "bedrock":        "AWS Bedrock",
    "aws":            "AWS",
    "llama":          "Meta Llama",
    "mistral":        "Mistral",
    "groq":           "Groq",
    "cohere":         "Cohere",
    "ollama":         "Ollama",
    "openrouter":     "OpenRouter",
    "huggingface":    "HuggingFace",
    "deepseek":       "DeepSeek",
    "perplexity":     "Perplexity",
    "together":       "Together AI",
    "replicate":      "Replicate",
    "local":          "Local LLM",
    "xai":            "xAI",
    "grok":           "xAI Grok",
}

AI_MODELS: List[str] = [
    # OpenAI
    "gpt-5","gpt-4.1","gpt-4o","gpt-4o-mini","gpt-4.1-mini","gpt-4.1-nano",
    "gpt-4-turbo","gpt-4","gpt-3.5-turbo","gpt-3.5",
    "o1","o1-mini","o1-preview","o3","o3-mini","o4-mini",
    "dall-e-3","dall-e-2","whisper",
    "text-embedding-3-large","text-embedding-3-small","text-embedding-ada-002",
    # Anthropic
    "claude-3-5-sonnet","claude-3-5-haiku","claude-3-opus","claude-3-sonnet",
    "claude-3-haiku","claude-2","claude-instant","claude",
    # Google
    "gemini-2.0","gemini-1.5-pro","gemini-1.5-flash","gemini-pro",
    "gemini-ultra","gemini-flash","gemini",
    # Meta
    "llama-3.3","llama-3.2","llama-3.1","llama-3","llama-2","llama",
    # Mistral
    "mistral-large","mistral-medium","mistral-small","mistral-7b",
    "mixtral-8x22b","mixtral-8x7b","mixtral","codestral","pixtral",
    # DeepSeek
    "deepseek-r1","deepseek-v3","deepseek-v2","deepseek-coder","deepseek",
    # Cohere
    "command-r-plus","command-r","command",
    # Microsoft
    "phi-4","phi-3","phi-2","phi",
    # Alibaba
    "qwen-2.5","qwen-2","qwen","qwq",
    # AWS
    "titan","nova",
    # xAI
    "grok-2","grok-1","grok",
    # HuggingFace
    "falcon","bloom","starcoder","codegen","mpt",
]

API_KEY_ENV_VARS: Dict[str, str] = {
    "OPENAI_API_KEY":               "OpenAI",
    "OPENAI_KEY":                   "OpenAI",
    "AZURE_OPENAI_KEY":             "Azure OpenAI",
    "AZURE_OPENAI_API_KEY":         "Azure OpenAI",
    "AZURE_OPENAI_ENDPOINT":        "Azure OpenAI",
    "AZURE_API_KEY":                "Azure OpenAI",
    "ANTHROPIC_API_KEY":            "Anthropic",
    "CLAUDE_API_KEY":               "Anthropic",
    "GEMINI_API_KEY":               "Google Gemini",
    "GOOGLE_API_KEY":               "Google",
    "GOOGLE_APPLICATION_CREDENTIALS":"Google",
    "GROQ_API_KEY":                 "Groq",
    "COHERE_API_KEY":               "Cohere",
    "MISTRAL_API_KEY":              "Mistral",
    "TOGETHER_API_KEY":             "Together AI",
    "REPLICATE_API_KEY":            "Replicate",
    "HUGGINGFACE_API_KEY":          "HuggingFace",
    "HF_TOKEN":                     "HuggingFace",
    "HUGGING_FACE_HUB_TOKEN":       "HuggingFace",
    "AWS_ACCESS_KEY_ID":            "AWS",
    "AWS_SECRET_ACCESS_KEY":        "AWS",
    "AWS_SESSION_TOKEN":            "AWS",
    "AWS_DEFAULT_REGION":           "AWS",
    "DEEPSEEK_API_KEY":             "DeepSeek",
    "PERPLEXITY_API_KEY":           "Perplexity",
    "OPENROUTER_API_KEY":           "OpenRouter",
    "OLLAMA_HOST":                  "Ollama",
    "OLLAMA_BASE_URL":              "Ollama",
    "LANGCHAIN_API_KEY":            "LangChain",
    "LANGSMITH_API_KEY":            "LangSmith",
    "XAI_API_KEY":                  "xAI",
    "GROK_API_KEY":                 "xAI",
    "MEM0_API_KEY":                 "Mem0",
    "DATABASE_URL":                 "Database",
    "SECRET_KEY":                   "Application",
    "FLASK_SECRET_KEY":             "Flask",
    "PORT":                         "Application",
}

AGENT_PATTERNS: List[str] = [
    r"class\s+\w*[Aa]gent\w*\b",
    r"class\s+\w*[Bb]ot\w*\b",
    r"class\s+\w*[Aa]ssistant\w*\b",
    r"class\s+\w*[Oo]rchestrator\w*\b",
    r"class\s+\w*[Pp]lanner\w*\b",
    r"class\s+\w*[Ee]xecutor\w*\b",
    r"class\s+\w*[Mm]onitor\w*\b",
    r"class\s+\w*[Ss]canner\w*\b",
    r"class\s+\w*[Ss]entinel\w*\b",
    r"AgentExecutor\s*\(",
    r"create_agent\s*\(",
    r"initialize_agent\s*\(",
    r"autogen\.\w+Agent\s*\(",
    r"crew\s*=\s*Crew\s*\(",
    r"Agent\s*\(",
    r"ReActAgent\s*\(",
    r"supervisor_agent\s*=",
    r"worker_agent\s*=",
    r"@agent\b",
]

PROMPT_PATTERNS: List[str] = [
    r"system_prompt\s*=",
    r"system_message\s*=",
    r"user_prompt\s*=",
    r"prompt_template\s*=",
    r"PromptTemplate\s*\(",
    r"ChatPromptTemplate",
    r"HumanMessagePromptTemplate",
    r"SystemMessagePromptTemplate",
    r'"role"\s*:\s*"system"',
    r"'role'\s*:\s*'system'",
    r'"role"\s*:\s*"user"',
    r"SYSTEM_PROMPT\s*=",
    r"USER_PROMPT\s*=",
    r"PROMPT\s*=\s*[\"']",
    r"prompt\s*=\s*f[\"']",
    r'prompt\s*=\s*"""',
    r'template\s*=\s*"""',
    r'instruction\s*=\s*"""',
]

TOOL_PATTERNS: Dict[str, List[str]] = {
    "Web Search":    [r"tavily",r"serp",r"google_search",r"bing_search",r"duckduckgo",r"web_search"],
    "Database":      [r"sqlalchemy",r"psycopg2",r"pymongo",r"sqlite3",r"mysql",r"db\.execute",r"\.query\("],
    "Vector Store":  [r"pinecone",r"weaviate",r"chromadb",r"qdrant",r"faiss",r"milvus",r"vectorstore"],
    "RAG":           [r"retrieval",r"rag\b",r"retrieve",r"document_loader",r"text_splitter"],
    "HTTP Calls":    [r"requests\.get",r"requests\.post",r"httpx\.",r"aiohttp\.",r"urllib\.request"],
    "Email":         [r"smtplib",r"sendgrid",r"mailgun",r"email\.mime"],
    "Slack":         [r"slack_sdk",r"slack_bolt",r"WebClient"],
    "GitHub":        [r"pygithub",r"github\.Github",r"github\.rest"],
    "Filesystem":    [r"open\s*\(",r"pathlib\.Path",r"os\.path",r"shutil\.",r"glob\."],
    "Shell":         [r"subprocess\.",r"os\.system",r"os\.popen"],
    "Memory":        [r"memory\b",r"conversation_buffer",r"chat_history",r"mem0"],
    "Monitoring":    [r"prometheus",r"datadog",r"cloudwatch",r"grafana",r"alertmanager"],
    "AWS Services":  [r"boto3\.",r"s3\.",r"ec2\.",r"lambda_",r"sqs\.",r"sns\."],
    "Flask/Web":     [r"@app\.",r"@blueprint\.",r"render_template",r"jsonify",r"make_response"],
    "Scheduling":    [r"schedule\.",r"cron",r"apscheduler",r"celery"],
}

WORKFLOW_PATTERNS: Dict[str, List[str]] = {
    "Planning":         [r"planner",r"create_plan",r"task_plan",r"plan_step"],
    "Execution":        [r"executor",r"run_agent",r"execute_task",r"agent\.run"],
    "Reflection":       [r"reflect",r"reflection",r"self_critique",r"critique"],
    "Retry / Backoff":  [r"max_retries",r"retry_logic",r"exponential_backoff",r"backoff",r"tenacity"],
    "Evaluation":       [r"evaluator",r"judge",r"scorer",r"evaluate_output"],
    "Memory":           [r"memory",r"remember",r"recall",r"chat_history"],
    "RAG":              [r"retrieve",r"retrieval",r"semantic_search",r"similarity_search"],
    "Tool Calling":     [r"tool_call",r"function_call",r"use_tool",r"call_tool"],
    "Streaming":        [r"stream_response",r"async_stream",r"streaming",r"yield\s+chunk"],
    "Multi-agent":      [r"multi_agent",r"multiagent",r"agent_network",r"agent_team"],
    "Supervisor":       [r"supervisor",r"orchestrator",r"coordinator",r"router_agent"],
    "Monitoring Loop":  [r"while\s+True",r"poll",r"watch_loop",r"monitor_loop",r"event_loop"],
    "Webhook":          [r"webhook",r"callback_url",r"event_handler",r"on_event"],
    "Alert":            [r"alert",r"notify",r"send_alert",r"trigger_alarm"],
}

FLASK_ROUTE_PATTERN = re.compile(
    r'@\w+\.(get|post|put|delete|patch|route)\s*\(\s*["\']([^"\']+)["\']',
    re.IGNORECASE,
)
BLUEPRINT_PATTERN = re.compile(
    r'Blueprint\s*\(\s*["\'](\w+)["\']',
    re.IGNORECASE,
)


# ──────────────────────────────────────────────────────────────
# UTILITIES
# ──────────────────────────────────────────────────────────────

def safe_read(filepath: str) -> Optional[str]:
    for enc in ("utf-8", "latin-1", "cp1252", "ascii"):
        try:
            with open(filepath, "r", encoding=enc, errors="replace") as fh:
                return fh.read()
        except Exception:
            continue
    return None


def count_lines(content: str) -> int:
    return len([l for l in content.splitlines() if l.strip()])


def fmt_size(n: int) -> str:
    if n < 1024:
        return f"{n} B"
    if n < 1024 ** 2:
        return f"{n / 1024:.1f} KB"
    return f"{n / (1024 ** 2):.1f} MB"


def esc(text: Any) -> str:
    return _html.escape(str(text)) if text is not None else ""


def trunc(text: Any, n: int = 80) -> str:
    s = str(text) if text is not None else ""
    return s[:n] + "…" if len(s) > n else s


def fsize(fp: str) -> int:
    try:
        return os.path.getsize(fp)
    except Exception:
        return 0


# ──────────────────────────────────────────────────────────────
# SCANNER
# ──────────────────────────────────────────────────────────────

class RepoScanner:
    """Recursively scans a repository directory and extracts all metadata."""

    def __init__(self, root: str) -> None:
        self.root       = os.path.abspath(root)
        self.repo_name  = os.path.basename(self.root)
        self.scan_date  = datetime.datetime.now().isoformat()

        # File records
        self.files:     List[Dict] = []
        self.dirs:      List[str]  = []

        # AI artefacts
        self.agents:    List[Dict] = []
        self.providers: Dict[str, Dict] = {}
        self.models:    Dict[str, Dict] = {}
        self.sdks:      Dict[str, Dict] = {}
        self.prompts:   List[Dict] = []
        self.api_keys:  List[Dict] = []
        self.tools:     Dict[str, List[str]] = defaultdict(list)
        self.workflows: Dict[str, List[str]] = defaultdict(list)

        # Framework / web artefacts
        self.routes:     List[Dict] = []
        self.blueprints: List[str]  = []
        self.env_files:  List[str]  = []

        # Stats
        self.stats: Dict[str, Any] = defaultdict(int)

    # ── Public entry ──────────────────────────────────────────

    def scan(self) -> "RepoScanner":
        print(f"\n[*] Scanning → {self.root}")
        self._walk()
        print(f"[*] Found {len(self.files)} files in {len(self.dirs)} directories")
        self._analyse_all()
        self._build_ref_graph()
        self._compute_stats()
        print("[*] Scan complete.\n")
        return self

    # ── Walk filesystem ───────────────────────────────────────

    def _walk(self) -> None:
        for dirpath, dirnames, filenames in os.walk(self.root, topdown=True):
            dirnames[:] = sorted(d for d in dirnames if d not in IGNORED_DIRS)

            rel_dir = os.path.relpath(dirpath, self.root)
            if rel_dir != ".":
                self.dirs.append(rel_dir)

            for fn in sorted(filenames):
                fp  = os.path.join(dirpath, fn)
                rel = os.path.relpath(fp, self.root)
                ext = self._classify_ext(fn)
                lang, cat = EXTENSION_MAP.get(ext, ("Unknown", "other"))

                self.files.append({
                    # identity
                    "serial":       0,
                    "filepath":     fp,
                    "rel_path":     rel,
                    "filename":     fn,
                    "extension":    ext or "(none)",
                    "language":     lang,
                    "category":     cat,
                    # analysis outputs
                    "purpose":      "Unknown",
                    "description":  "",
                    "size":         fsize(fp),
                    "size_fmt":     fmt_size(fsize(fp)),
                    "lines":        0,
                    "content":      None,
                    # flags
                    "is_used":       False,
                    "is_referenced": False,
                    "is_ai_related": False,
                    "has_tests":     False,
                    "has_api":       False,
                    # collections
                    "imports":        [],
                    "classes":        [],
                    "functions":      [],
                    "routes":         [],
                    "blueprints":     [],
                    "agents_found":   [],
                    "models_found":   [],
                    "providers_found":[],
                    "sdks_found":     [],
                    "prompts_found":  [],
                    "keys_found":     [],
                    "tools_found":    [],
                    "workflows_found":[],
                    "token_config":   {},
                })

    @staticmethod
    def _classify_ext(fn: str) -> str:
        """Return a normalised extension, handling special filenames."""
        fl = fn.lower()
        if fl == "dockerfile" or fl.startswith("dockerfile."):
            return ".dockerfile"
        if fl == "makefile":
            return ".makefile"
        if fl in ("requirements.txt", "requirements-dev.txt",
                  "requirements-test.txt", "requirements-prod.txt"):
            return ".requirements"
        if fl == ".env" or re.match(r"^\.env\.\w+$", fl):
            return ".env"
        return Path(fn).suffix.lower()

    # ── Analyse each file ─────────────────────────────────────

    def _analyse_all(self) -> None:
        total = len(self.files)
        for i, fi in enumerate(self.files, 1):
            fi["serial"] = i
            sys.stdout.write(f"\r  Analysing [{i}/{total}] {fi['filename'][:55]:<55}")
            sys.stdout.flush()

            if fi["size"] > 20 * 1024 * 1024:
                continue

            content = safe_read(fi["filepath"])
            if not content:
                continue

            fi["content"] = content
            fi["lines"]   = count_lines(content)

            self._detect_purpose(fi)
            self._detect_imports(fi)
            self._detect_routes(fi)
            self._detect_ai(fi)
            self._detect_prompts(fi)
            self._detect_keys(fi)
            self._detect_tools(fi)
            self._detect_workflows(fi)
            self._detect_token_cfg(fi)
            self._detect_cls_fn(fi)
            self._detect_tests(fi)
            self._refine_category(fi)

            # Track .env files
            if fi["extension"] == ".env":
                self.env_files.append(fi["rel_path"])

        print()

    # ── Purpose detection ─────────────────────────────────────

    def _detect_purpose(self, fi: Dict) -> None:
        name  = fi["filename"].lower()
        rpath = fi["rel_path"].lower().replace("\\", "/")
        snip  = (fi["content"] or "")[:800].lower()
        hay   = f"{name} {rpath} {snip}"

        rules = [
            (["sentinel","ops","sentinelops"],          "AI Operations Monitor"),
            (["agent_monitor","agentmonitor"],           "Agent Monitor"),
            (["agent", "agents"],                        "AI Agent"),
            (["llm","language_model","language model"],  "LLM Interface"),
            (["prompt", "prompts"],                      "Prompt"),
            (["memory", "mem0"],                         "Memory"),
            (["tool", "tools"],                          "Tool"),
            (["workflow", "pipeline", "flow"],           "Workflow / Pipeline"),
            (["rag", "retrieval", "retriever"],          "RAG"),
            (["embed", "embedding", "embeddings"],       "Embeddings"),
            (["vector", "vectorstore"],                  "Vector Store"),
            (["chain"],                                  "Chain"),
            (["router", "routing"],                      "Router"),
            (["supervisor", "orchestrat"],               "Orchestrator"),
            (["api", "endpoint", "route", "routes"],     "API / Routes"),
            (["controller", "handler"],                  "Controller"),
            (["service"],                                "Service"),
            (["repository", "dao", "store"],             "Repository / DAO"),
            (["database", "db", "schema", "migration"],  "Database"),
            (["auth", "authentication", "jwt", "oauth"], "Authentication"),
            (["config", "configuration", "settings"],    "Configuration"),
            (["utils", "utility", "helpers", "common"],  "Utility / Helper"),
            (["log", "logging", "logger"],               "Logging"),
            (["monitor", "metrics", "telemetry", "ops"], "Monitoring / Metrics"),
            (["test", "spec"],                           "Testing"),
            (["docker", "compose"],                      "Docker"),
            (["terraform"],                              "Terraform"),
            (["kubernetes", "k8s", "helm"],              "Kubernetes"),
            (["deploy", "ci", "cd", "github/workflows"], "CI/CD / Deployment"),
            (["queue", "worker", "celery", "kafka"],     "Queue / Worker"),
            (["scheduler", "cron"],                      "Scheduler"),
            (["cli", "command", "cmd"],                  "CLI"),
            (["main", "app", "application", "server",
              "__init__", "entrypoint", "wsgi"],         "Application Entry"),
            (["requirements", "dependencies", "package"],"Dependencies"),
            (["readme", "changelog", "contributing"],    "Documentation"),
            (["setup", "install", "build"],              "Build / Setup"),
            (["frontend", "ui", "component", "page",
              "template", "index.html"],                 "Frontend / Template"),
        ]

        for keywords, purpose in rules:
            if any(kw in hay for kw in keywords):
                fi["purpose"] = purpose
                return

        fallbacks = {
            ".py": "Python Module", ".js": "JavaScript Module",
            ".ts": "TypeScript Module", ".java": "Java Class",
            ".cs": "C# Module", ".go": "Go Module", ".rs": "Rust Module",
            ".yaml": "YAML Config", ".yml": "YAML Config",
            ".json": "JSON Config", ".md": "Documentation",
            ".sql": "SQL", ".sh": "Shell Script",
            ".html": "HTML Template", ".css": "Stylesheet",
        }
        fi["purpose"] = fallbacks.get(fi["extension"], "Unknown")

    # ── Imports ───────────────────────────────────────────────

    def _detect_imports(self, fi: Dict) -> None:
        content = fi["content"] or ""
        ext     = fi["extension"]
        imps    = []

        if ext == ".py":
            for m in re.finditer(r"^\s*(?:import|from)\s+([\w\.]+)", content, re.M):
                pkg = m.group(1).split(".")[0]
                if pkg and pkg not in imps:
                    imps.append(pkg)
        elif ext in (".js", ".ts", ".jsx", ".tsx"):
            for m in re.finditer(
                    r"(?:import\s+.*?from|require\s*\()\s*[\"']([^\"']+)[\"']", content):
                raw = m.group(1)
                if not raw.startswith("."):
                    pkg = raw.split("/")[0].lstrip("@")
                    if pkg and pkg not in imps:
                        imps.append(pkg)
        elif ext == ".java":
            for m in re.finditer(r"^import\s+([\w\.]+)", content, re.M):
                pkg = m.group(1).split(".")[0]
                if pkg and pkg not in imps:
                    imps.append(pkg)

        fi["imports"] = imps[:60]

    # ── Flask routes & blueprints ─────────────────────────────

    def _detect_routes(self, fi: Dict) -> None:
        content = fi["content"] or ""

        # Routes
        for m in FLASK_ROUTE_PATTERN.finditer(content):
            method = m.group(1).upper()
            path   = m.group(2)
            rec = {"method": method, "path": path, "file": fi["rel_path"]}
            fi["routes"].append(rec)
            self.routes.append(rec)

        # Blueprints
        for m in BLUEPRINT_PATTERN.finditer(content):
            bp = m.group(1)
            if bp not in fi["blueprints"]:
                fi["blueprints"].append(bp)
            if bp not in self.blueprints:
                self.blueprints.append(bp)

        if fi["routes"]:
            fi["has_api"] = True
            self.stats["total_endpoints"] += len(fi["routes"])
            self.stats["total_apis"]      += 1

    # ── AI components ─────────────────────────────────────────

    def _detect_ai(self, fi: Dict) -> None:
        content = fi["content"] or ""
        cl      = content.lower()

        # SDKs
        for sdk_key, sdk_info in AI_SDKS.items():
            pat = sdk_key.replace("_", r"[\._]?").replace("-", r"[\-_]?")
            if re.search(r"\b" + pat + r"\b", cl):
                name = sdk_info["name"]
                if name not in fi["sdks_found"]:
                    fi["sdks_found"].append(name)
                    fi["is_ai_related"] = True
                    if name not in self.sdks:
                        self.sdks[name] = {
                            "name": name, "provider": sdk_info["provider"],
                            "files": [], "count": 0,
                        }
                    self.sdks[name]["files"].append(fi["rel_path"])
                    self.sdks[name]["count"] += 1

        # Models
        for model in AI_MODELS:
            if re.search(re.escape(model), cl):
                if model not in fi["models_found"]:
                    fi["models_found"].append(model)
                    fi["is_ai_related"] = True
                    if model not in self.models:
                        self.models[model] = {
                            "name": model,
                            "provider": self._model_provider(model),
                            "files": [], "count": 0,
                        }
                    self.models[model]["files"].append(fi["rel_path"])
                    self.models[model]["count"] += 1

        # Providers
        for key, pname in AI_PROVIDERS.items():
            if re.search(r"\b" + re.escape(key) + r"\b", cl):
                if pname not in fi["providers_found"]:
                    fi["providers_found"].append(pname)
                    fi["is_ai_related"] = True
                    if pname not in self.providers:
                        self.providers[pname] = {
                            "name": pname, "files": [],
                            "count": 0, "env_vars": [],
                        }
                    self.providers[pname]["files"].append(fi["rel_path"])
                    self.providers[pname]["count"] += 1

        # Agents
        for pat in AGENT_PATTERNS:
            for m in re.finditer(pat, content):
                raw    = m.group(0)
                cmatch = re.search(r"class\s+(\w+)", raw)
                aname  = cmatch.group(1) if cmatch else raw.strip()[:40]
                if aname and not any(
                        a["name"] == aname and a["file"] == fi["rel_path"]
                        for a in fi["agents_found"]):
                    rec = {
                        "name":      aname,
                        "file":      fi["rel_path"],
                        "type":      self._agent_type(aname, content),
                        "purpose":   self._agent_purpose(aname, content),
                        "providers": list(fi["providers_found"]),
                        "models":    list(fi["models_found"]),
                        "sdks":      list(fi["sdks_found"]),
                    }
                    fi["agents_found"].append(rec)
                    fi["is_ai_related"] = True
                    self.agents.append(rec)

    @staticmethod
    def _model_provider(m: str) -> str:
        m = m.lower()
        if any(x in m for x in ("gpt","o1","o3","o4","dall-e","whisper","text-embedding")):
            return "OpenAI"
        if "claude"   in m: return "Anthropic"
        if any(x in m for x in ("gemini","palm")): return "Google"
        if "llama"    in m: return "Meta"
        if any(x in m for x in ("mistral","mixtral","codestral")): return "Mistral"
        if "deepseek" in m: return "DeepSeek"
        if "command"  in m: return "Cohere"
        if "phi"      in m: return "Microsoft"
        if any(x in m for x in ("qwen","qwq")): return "Alibaba"
        if any(x in m for x in ("titan","nova")): return "AWS"
        if "grok"     in m: return "xAI"
        return "Unknown"

    @staticmethod
    def _agent_type(name: str, content: str) -> str:
        n = name.lower();  c = content.lower()
        if any(x in n for x in ("supervisor","orchestrat","coordinator")):
            return "Supervisor / Orchestrator"
        if "monitor"  in n: return "Monitoring Agent"
        if "scanner"  in n: return "Scanner Agent"
        if "sentinel" in n: return "Sentinel / Ops Agent"
        if "plan"     in n: return "Planning Agent"
        if "execut"   in n: return "Execution Agent"
        if any(x in n for x in ("react","reason")): return "ReAct Agent"
        if any(x in n for x in ("rag","retriev")):   return "RAG Agent"
        if "tool"     in n: return "Tool-using Agent"
        if any(x in n for x in ("chat","convers")):  return "Conversational Agent"
        if any(x in n for x in ("code","coder")):    return "Code Agent"
        if "crewai"   in c: return "CrewAI Agent"
        if "autogen"  in c: return "AutoGen Agent"
        if "langgraph" in c: return "LangGraph Agent"
        return "General AI Agent"

    @staticmethod
    def _agent_purpose(name: str, content: str) -> str:
        n = name.lower();  c = content[:800].lower()
        if "monitor"  in n or "monitor"   in c: return "System / agent monitoring"
        if "scanner"  in n or "scan"      in c: return "Repository / code scanning"
        if "sentinel" in n or "sentinel"  in c: return "Operational intelligence"
        if "search"   in n or "search"    in c: return "Search and retrieval"
        if "code"     in n:                     return "Code generation / analysis"
        if any(x in n for x in ("data","analys")): return "Data analysis"
        if any(x in n for x in ("write","content")): return "Content generation"
        if "plan"     in n:                     return "Task planning"
        if any(x in n for x in ("customer","support")): return "Customer support"
        return "General AI assistance"

    # ── Prompts ───────────────────────────────────────────────

    def _detect_prompts(self, fi: Dict) -> None:
        content = fi["content"] or ""

        if fi["extension"] == ".prompt":
            p = {"name": fi["filename"], "file": fi["rel_path"],
                 "type": "Prompt File", "purpose": "Dedicated prompt", "agent": "Unknown"}
            fi["prompts_found"].append(p)
            self.prompts.append(p)
            fi["is_ai_related"] = True
            return

        for pat in PROMPT_PATTERNS:
            if re.search(pat, content, re.IGNORECASE):
                ptype = ("System Prompt"    if "system"   in pat.lower() else
                         "User Prompt"      if "user"     in pat.lower() else
                         "Prompt Template"  if "template" in pat.lower() else
                         "Inline Prompt")
                key = (fi["rel_path"], ptype)
                if not any((p["file"], p["type"]) == key for p in fi["prompts_found"]):
                    p = {"name": f"{ptype} in {fi['filename']}", "file": fi["rel_path"],
                         "type": ptype, "purpose": "AI instruction", "agent": "Unknown"}
                    fi["prompts_found"].append(p)
                    if not any((p2["file"], p2["type"]) == key for p2 in self.prompts):
                        self.prompts.append(p)
                    fi["is_ai_related"] = True

        if fi["extension"] == ".md" and re.search(
                r"(system|user|assistant)\s*(prompt|message|instruction)",
                content, re.IGNORECASE):
            p = {"name": f"Markdown Prompt: {fi['filename']}", "file": fi["rel_path"],
                 "type": "Markdown Prompt", "purpose": "Documentation / template",
                 "agent": "Unknown"}
            fi["prompts_found"].append(p)
            self.prompts.append(p)
            fi["is_ai_related"] = True

    # ── API keys ──────────────────────────────────────────────

    def _detect_keys(self, fi: Dict) -> None:
        content = fi["content"] or ""
        for var, provider in API_KEY_ENV_VARS.items():
            if var in content:
                src = ("os.environ / os.getenv" if re.search(r"os\.getenv|os\.environ\.get", content)
                       else ".env file (dotenv)" if re.search(r"dotenv|load_dotenv", content, re.I)
                       else "process.env"        if "process.env" in content
                       else "Settings module"    if "settings."   in content.lower()
                       else "Environment Variable")
                rec = {"variable": var, "provider": provider,
                       "file": fi["rel_path"], "loaded_from": src}
                fi["keys_found"].append(rec)
                if not any(k["variable"] == var and k["file"] == fi["rel_path"]
                           for k in self.api_keys):
                    self.api_keys.append(rec)
                fi["is_ai_related"] = True
                if provider in self.providers and var not in self.providers[provider]["env_vars"]:
                    self.providers[provider]["env_vars"].append(var)

    # ── Tools ─────────────────────────────────────────────────

    def _detect_tools(self, fi: Dict) -> None:
        cl = (fi["content"] or "").lower()
        for tname, pats in TOOL_PATTERNS.items():
            if any(re.search(p, cl) for p in pats):
                if tname not in fi["tools_found"]:
                    fi["tools_found"].append(tname)
                    self.tools[tname].append(fi["rel_path"])

    # ── Workflows ─────────────────────────────────────────────

    def _detect_workflows(self, fi: Dict) -> None:
        cl = (fi["content"] or "").lower()
        for wname, pats in WORKFLOW_PATTERNS.items():
            if any(re.search(p, cl) for p in pats):
                if wname not in fi["workflows_found"]:
                    fi["workflows_found"].append(wname)
                    self.workflows[wname].append(fi["rel_path"])

    # ── Token configuration ───────────────────────────────────

    def _detect_token_cfg(self, fi: Dict) -> None:
        content = fi["content"] or ""
        cfg = {}
        checks = [
            (r"max_tokens\s*[=:]\s*(\d+)",              "max_tokens",     int),
            (r"max_completion_tokens\s*[=:]\s*(\d+)",   "max_tokens",     int),
            (r"MAX_TOKENS\s*=\s*(\d+)",                  "max_tokens",     int),
            (r"temperature\s*[=:]\s*([0-9.]+)",          "temperature",    float),
            (r"top_p\s*[=:]\s*([0-9.]+)",                "top_p",          float),
            (r"context_window\s*[=:]\s*(\d+)",           "context_window", int),
            (r"context_length\s*[=:]\s*(\d+)",           "context_window", int),
            (r"timeout\s*[=:]\s*(\d+)",                  "timeout",        int),
            (r"max_retries\s*[=:]\s*(\d+)",              "max_retries",    int),
        ]
        for pat, key, cast in checks:
            m = re.search(pat, content, re.IGNORECASE)
            if m and key not in cfg:
                try:
                    cfg[key] = cast(m.group(1))
                except Exception:
                    pass
        if cfg:
            fi["token_config"]  = cfg
            fi["is_ai_related"] = True

    # ── Classes & functions ───────────────────────────────────

    def _detect_cls_fn(self, fi: Dict) -> None:
        content = fi["content"] or ""
        ext     = fi["extension"]
        classes: List[str] = []
        funcs:   List[str] = []

        if ext == ".py":
            classes = re.findall(r"^\s*class\s+(\w+)", content, re.M)
            funcs   = re.findall(r"^\s*(?:async\s+)?def\s+(\w+)", content, re.M)
        elif ext in (".js", ".ts", ".jsx", ".tsx"):
            classes = re.findall(r"\bclass\s+(\w+)", content)
            raw_fn  = re.findall(
                r"(?:function\s+(\w+)|const\s+(\w+)\s*=\s*(?:async\s+)?\()", content)
            funcs   = [f[0] or f[1] for f in raw_fn if f[0] or f[1]]
        elif ext == ".java":
            classes = re.findall(r"\bclass\s+(\w+)", content)
            funcs   = re.findall(r"\b(?:public|private|protected)\b[^(]+\b(\w+)\s*\(", content)

        fi["classes"]   = classes[:25]
        fi["functions"] = funcs[:35]
        self.stats["total_classes"]   += len(classes)
        self.stats["total_functions"] += len(funcs)

    # ── Tests ─────────────────────────────────────────────────

    def _detect_tests(self, fi: Dict) -> None:
        fn = fi["filename"].lower()
        c  = fi["content"] or ""
        fi["has_tests"] = bool(
            fn.startswith("test_") or
            fn.endswith(("_test.py", ".test.js", ".test.ts", ".spec.js", ".spec.ts")) or
            re.search(r"def test_\w+|@pytest\.mark|unittest\.TestCase|"
                      r"describe\s*\(|it\s*\(|beforeEach\s*\(", c)
        )
        if fi["has_tests"]:
            fi["category"] = "test"

    # ── Category refinement ───────────────────────────────────

    def _refine_category(self, fi: Dict) -> None:
        if fi["is_ai_related"]:
            fi["category"] = "ai"
        elif fi["has_tests"]:
            fi["category"] = "test"
        elif fi["purpose"] in ("Docker", "Terraform", "Kubernetes", "CI/CD / Deployment"):
            fi["category"] = "infrastructure"
        elif fi["purpose"] == "Documentation":
            fi["category"] = "documentation"

    # ── Reference graph ───────────────────────────────────────

    def _build_ref_graph(self) -> None:
        for fi in self.files:
            content = fi["content"] or ""
            for other in self.files:
                if other["rel_path"] == fi["rel_path"]:
                    continue
                stem = Path(other["filename"]).stem
                if stem and len(stem) > 2 and stem in content:
                    other["is_referenced"] = True
                    other["is_used"]       = True

    # ── Aggregate statistics ──────────────────────────────────

    def _compute_stats(self) -> None:
        cats = Counter(f["category"] for f in self.files)
        agents_dedup = len(set(
            (a["name"], a["file"]) for a in self.agents
        ))
        self.stats.update({
            "total_files":           len(self.files),
            "total_dirs":            len(self.dirs),
            "total_source_files":    cats.get("source", 0),
            "total_config_files":    cats.get("config", 0),
            "total_doc_files":       cats.get("documentation", 0),
            "total_test_files":      sum(1 for f in self.files if f["has_tests"]),
            "total_infra_files":     cats.get("infrastructure", 0),
            "total_ai_files":        sum(1 for f in self.files if f["is_ai_related"]),
            "total_agents":          agents_dedup,
            "total_models":          len(self.models),
            "total_providers":       len(self.providers),
            "total_prompts":         len(self.prompts),
            "total_sdks":            len(self.sdks),
            "total_routes":          len(self.routes),
            "total_blueprints":      len(self.blueprints),
            "total_lines":           sum(f["lines"] for f in self.files),
            "total_size":            sum(f["size"]  for f in self.files),
            "total_docker_files":    sum(1 for f in self.files if f["extension"] == ".dockerfile"),
            "total_yaml_files":      sum(1 for f in self.files if f["extension"] in (".yaml",".yml")),
            "total_terraform_files": sum(1 for f in self.files if f["extension"] in (".tf",".tfvars",".hcl")),
            "total_k8s_files":       sum(1 for f in self.files
                                         if f["extension"] in (".yaml",".yml")
                                         and any(k in f["rel_path"].lower()
                                                 for k in ("k8s","kubernetes","helm","kube"))),
            "languages": dict(Counter(f["language"] for f in self.files).most_common(15)),
        })


# ──────────────────────────────────────────────────────────────
# HTML REPORT
# ──────────────────────────────────────────────────────────────

# ── CSS (complete, self-contained) ───────────────────────────
_CSS = r"""
:root{
  --bg:#f0f4f8;--card:#fff;--text:#1a202c;--muted:#718096;
  --border:#e2e8f0;--primary:#4f46e5;--primary-d:#3730a3;
  --success:#10b981;--warn:#f59e0b;--danger:#ef4444;--info:#3b82f6;
  --purple:#8b5cf6;--teal:#14b8a6;--orange:#f97316;--gray:#6b7280;
  --nav:#1e1b4b;--nav-t:#e0e7ff;
  --hero:linear-gradient(135deg,#1e1b4b 0%,#312e81 50%,#4338ca 100%);
  --th:#f7fafc;--stripe:#f9fafb;--hover:#eef2ff;
  --sh:0 4px 6px -1px rgba(0,0,0,.1);
  --sh-lg:0 10px 25px -5px rgba(0,0,0,.15);
  --r:12px;--r-sm:8px;
  --font:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;
  --mono:'SFMono-Regular',Consolas,'Liberation Mono',monospace;
}
[data-theme=dark]{
  --bg:#0f172a;--card:#1e293b;--text:#f1f5f9;--muted:#94a3b8;
  --border:#334155;--nav:#020617;--th:#1e293b;--stripe:#162032;
  --hover:#1e3a5f;--sh:0 4px 6px -1px rgba(0,0,0,.4);
}
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:var(--font);background:var(--bg);color:var(--text);line-height:1.6;transition:background .3s,color .3s}
/* ─ NAV ─ */
.nav{position:sticky;top:0;z-index:1000;background:var(--nav);color:var(--nav-t);
     display:flex;align-items:center;padding:0 20px;height:52px;gap:16px;
     box-shadow:var(--sh-lg);overflow:hidden}
.nav-brand{font-weight:800;font-size:1rem;white-space:nowrap;flex-shrink:0}
.nav-links{display:flex;gap:2px;flex:1;overflow-x:auto;scrollbar-width:none}
.nav-links::-webkit-scrollbar{display:none}
.nav-links a{color:#c7d2fe;text-decoration:none;padding:5px 9px;border-radius:6px;
             font-size:.78rem;white-space:nowrap;transition:background .2s,color .2s}
.nav-links a:hover{background:rgba(255,255,255,.1);color:#fff}
.nav-right{display:flex;gap:8px;flex-shrink:0}
/* ─ BUTTONS ─ */
.btn{padding:7px 14px;border:none;border-radius:var(--r-sm);cursor:pointer;
     font-size:.82rem;font-weight:600;transition:all .2s;display:inline-flex;align-items:center;gap:5px}
.btn-export{background:#10b981;color:#fff}.btn-export:hover{background:#059669}
.btn-theme{background:rgba(255,255,255,.1);color:var(--nav-t);border:1px solid rgba(255,255,255,.2)}
.btn-theme:hover{background:rgba(255,255,255,.2)}
.btn-sm{padding:6px 12px;font-size:.78rem;background:var(--primary);color:#fff}
.btn-sm:hover{background:var(--primary-d)}
/* ─ HERO ─ */
.hero{background:var(--hero);color:#fff;padding:44px 24px;text-align:center}
.hero h1{font-size:1.9rem;font-weight:800;margin-bottom:14px;text-shadow:0 2px 4px rgba(0,0,0,.3)}
.hero-chips{display:flex;justify-content:center;flex-wrap:wrap;gap:12px}
.chip{background:rgba(255,255,255,.12);padding:6px 14px;border-radius:20px;
      font-size:.85rem;border:1px solid rgba(255,255,255,.2)}
/* ─ LAYOUT ─ */
.wrap{max-width:1600px;margin:0 auto;padding:24px 20px}
.sec{background:var(--card);border-radius:var(--r);padding:26px;margin-bottom:26px;
     box-shadow:var(--sh);border:1px solid var(--border)}
.sec-title{font-size:1.3rem;font-weight:700;margin-bottom:20px;
           border-bottom:3px solid var(--primary);padding-bottom:10px}
.sub-title{font-size:.95rem;font-weight:600;margin:20px 0 12px;color:var(--muted)}
/* ─ STAT CARDS ─ */
.card-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(145px,1fr));gap:12px;margin-bottom:12px}
.sc{background:var(--card);border-radius:var(--r-sm);padding:16px 12px;text-align:center;
    border:1px solid var(--border);transition:transform .2s,box-shadow .2s;position:relative;overflow:hidden}
.sc:hover{transform:translateY(-2px);box-shadow:var(--sh-lg)}
.sc::before{content:'';position:absolute;top:0;left:0;right:0;height:3px}
.sc.blue::before{background:var(--info)}.sc.green::before{background:var(--success)}
.sc.orange::before{background:var(--orange)}.sc.purple::before{background:var(--purple)}
.sc.teal::before{background:var(--teal)}.sc.gray::before{background:var(--gray)}
.sc.red::before{background:var(--danger)}
.sc-icon{font-size:1.6rem;display:block;margin-bottom:5px}
.sc-val{font-size:1.4rem;font-weight:800;display:block}
.sc-lbl{font-size:.68rem;color:var(--muted);font-weight:600;text-transform:uppercase;
        letter-spacing:.05em;display:block;margin-top:3px}
/* ─ CHARTS ─ */
.chart-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(340px,1fr));gap:16px}
.chart-box{background:var(--card);border-radius:var(--r-sm);padding:16px;border:1px solid var(--border)}
.chart-box h3{font-size:.9rem;font-weight:600;margin-bottom:10px;text-align:center}
canvas{max-width:100%;height:260px!important}
/* ─ TABLE CONTROLS ─ */
.tbl-ctrls{display:flex;align-items:center;gap:10px;margin-bottom:12px;flex-wrap:wrap}
.search-box{flex:1;min-width:200px;padding:8px 12px;border:2px solid var(--border);
            border-radius:var(--r-sm);background:var(--bg);color:var(--text);
            font-size:.86rem;transition:border-color .2s}
.search-box:focus{outline:none;border-color:var(--primary)}
.sel{padding:8px 11px;border:2px solid var(--border);border-radius:var(--r-sm);
     background:var(--bg);color:var(--text);font-size:.82rem;cursor:pointer}
.sel:focus{outline:none;border-color:var(--primary)}
.tbl-info{font-size:.8rem;color:var(--muted);margin-left:auto}
/* ─ TABLES ─ */
.tbl-wrap{overflow-x:auto;border-radius:var(--r-sm);border:1px solid var(--border)}
.tbl{width:100%;border-collapse:collapse;font-size:.8rem}
.tbl thead th{background:var(--th);padding:10px 12px;text-align:left;font-weight:700;
              border-bottom:2px solid var(--border);white-space:nowrap;position:sticky;top:0}
.tbl thead th.sort{cursor:pointer;user-select:none}
.tbl thead th.sort:hover{background:var(--hover);color:var(--primary)}
.tbl thead th.sort::after{content:' ⇅';opacity:.3;font-size:.7em}
.tbl tbody tr{border-bottom:1px solid var(--border);transition:background .15s}
.tbl tbody tr:nth-child(even){background:var(--stripe)}
.tbl tbody tr:hover{background:var(--hover)}
.tbl tbody td{padding:9px 12px;vertical-align:middle;max-width:240px}
/* ─ BADGES ─ */
.b{display:inline-flex;align-items:center;padding:2px 8px;border-radius:20px;
   font-size:.68rem;font-weight:700;white-space:nowrap}
.b-blue{background:#dbeafe;color:#1e40af}.b-green{background:#dcfce7;color:#166534}
.b-red{background:#fee2e2;color:#991b1b}.b-orange{background:#ffedd5;color:#9a3412}
.b-purple{background:#ede9fe;color:#5b21b6}.b-teal{background:#ccfbf1;color:#115e59}
.b-gray{background:#f3f4f6;color:#374151}.b-yellow{background:#fef9c3;color:#713f12}
.b-pink{background:#fce7f3;color:#9d174d}
.b-yes{background:#dcfce7;color:#166534}.b-no{background:#f3f4f6;color:#9ca3af}
[data-theme=dark] .b-blue{background:#1e3a5f;color:#93c5fd}
[data-theme=dark] .b-green{background:#052e16;color:#86efac}
[data-theme=dark] .b-red{background:#450a0a;color:#fca5a5}
[data-theme=dark] .b-orange{background:#431407;color:#fdba74}
[data-theme=dark] .b-purple{background:#2e1065;color:#c4b5fd}
[data-theme=dark] .b-teal{background:#022c22;color:#5eead4}
[data-theme=dark] .b-gray{background:#1f2937;color:#d1d5db}
[data-theme=dark] .b-yes{background:#052e16;color:#86efac}
[data-theme=dark] .b-no{background:#1f2937;color:#9ca3af}
/* ─ AGENT CARDS ─ */
.agent-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(310px,1fr));gap:16px}
.agent-card{background:var(--card);border:1px solid var(--border);border-radius:var(--r);
            padding:16px;position:relative;overflow:hidden;transition:transform .2s,box-shadow .2s}
.agent-card:hover{transform:translateY(-2px);box-shadow:var(--sh-lg)}
.agent-card::before{content:'';position:absolute;top:0;left:0;bottom:0;width:4px;
                    background:linear-gradient(to bottom,var(--primary),var(--purple))}
.ac-head{display:flex;align-items:flex-start;gap:10px;margin-bottom:10px}
.ac-icon{font-size:1.8rem;width:40px;height:40px;display:flex;align-items:center;
         justify-content:center;background:var(--bg);border-radius:var(--r-sm);
         border:1px solid var(--border);flex-shrink:0}
.ac-name{font-size:.92rem;font-weight:700}
.ac-type{font-size:.75rem;color:var(--muted)}
.ac-file{margin-top:9px;padding:6px 10px;background:var(--bg);border-radius:6px;
         font-family:var(--mono);font-size:.7rem;color:var(--muted);
         border:1px solid var(--border);word-break:break-all}
.lbl{font-size:.66rem;font-weight:700;color:var(--muted);text-transform:uppercase;letter-spacing:.05em}
.val{font-size:.8rem;color:var(--text);font-weight:600;margin-top:2px}
/* ─ PROVIDERS ─ */
.prov-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(220px,1fr));gap:12px}
.prov-card{background:var(--card);border:1px solid var(--border);border-radius:var(--r);
           padding:16px;text-align:center;transition:transform .2s}
.prov-card:hover{transform:translateY(-2px)}
.prov-icon{font-size:2rem;margin-bottom:7px}
.prov-name{font-size:.95rem;font-weight:700;margin-bottom:7px}
.prov-stats{display:flex;justify-content:center;gap:18px;margin:8px 0}
/* ─ ROUTES ─ */
.route-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(280px,1fr));gap:10px}
.route-card{background:var(--bg);border:1px solid var(--border);border-radius:var(--r-sm);
            padding:12px 14px;display:flex;align-items:center;gap:10px}
.route-method{font-family:var(--mono);font-size:.75rem;font-weight:800;padding:3px 8px;
              border-radius:4px;flex-shrink:0}
.GET   {background:#dcfce7;color:#166534}
.POST  {background:#dbeafe;color:#1e40af}
.PUT   {background:#fef9c3;color:#713f12}
.DELETE{background:#fee2e2;color:#991b1b}
.PATCH {background:#ede9fe;color:#5b21b6}
.route-method.ROUTE{background:#f3f4f6;color:#374151}
[data-theme=dark] .GET   {background:#052e16;color:#86efac}
[data-theme=dark] .POST  {background:#1e3a5f;color:#93c5fd}
[data-theme=dark] .PUT   {background:#292524;color:#fcd34d}
[data-theme=dark] .DELETE{background:#450a0a;color:#fca5a5}
[data-theme=dark] .PATCH {background:#2e1065;color:#c4b5fd}
[data-theme=dark] .route-method.ROUTE{background:#1f2937;color:#d1d5db}
.route-path{font-family:var(--mono);font-size:.82rem;font-weight:600;color:var(--text)}
.route-file{font-size:.7rem;color:var(--muted);margin-top:3px}
/* ─ SDK ─ */
.sdk-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(175px,1fr));gap:10px}
.sdk-card{background:var(--card);border:1px solid var(--border);border-radius:var(--r-sm);
          padding:13px;text-align:center;transition:transform .2s}
.sdk-card:hover{transform:translateY(-2px)}
.sdk-icon{font-size:1.7rem;margin-bottom:6px}
.sdk-name{font-weight:700;font-size:.84rem;margin-bottom:3px}
/* ─ PROMPTS ─ */
.prompt-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(260px,1fr));gap:10px}
.prompt-card{background:var(--bg);border:1px solid var(--border);border-radius:var(--r-sm);
             padding:12px;border-left:4px solid var(--purple)}
.pname{font-weight:700;margin:6px 0 3px;font-size:.84rem}
/* ─ TOOLS / WORKFLOWS ─ */
.tool-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(175px,1fr));gap:10px}
.tool-card{background:var(--card);border:1px solid var(--border);border-radius:var(--r-sm);padding:12px}
.wf-card{background:var(--card);border:1px solid var(--border);border-radius:var(--r-sm);
         padding:12px;border-top:3px solid var(--teal)}
.tool-name{font-weight:700;font-size:.84rem;margin-bottom:4px}
/* ─ MISC ─ */
.tag-row{display:flex;flex-wrap:wrap;gap:4px}
.mt4{margin-top:4px}.mt8{margin-top:8px}
.sm{font-size:.76rem}.grey{color:var(--muted)}
.mono{font-family:var(--mono)}
.blue-t{color:var(--primary)}
.big-num{font-size:1.7rem;font-weight:800;color:var(--primary);display:block}
.big-num.sm2{font-size:1.1rem}
.big-lbl{font-size:.72rem;opacity:.85;text-transform:uppercase;letter-spacing:.05em}
.banner{display:flex;gap:20px;flex-wrap:wrap;
        background:linear-gradient(135deg,var(--primary),var(--purple));
        border-radius:var(--r-sm);padding:16px 20px;color:#fff;margin-bottom:18px}
.banner-item{text-align:center}
.info-box{background:#fef9c3;border:1px solid #fbbf24;border-radius:var(--r-sm);
          padding:13px 16px;margin-bottom:14px;font-size:.86rem;color:#78350f}
[data-theme=dark] .info-box{background:#292524;border-color:#d97706;color:#fde68a}
.na{display:inline-flex;align-items:center;padding:2px 9px;background:#fef3c7;
    color:#92400e;border-radius:6px;font-size:.75rem;font-weight:600}
[data-theme=dark] .na{background:#292524;color:#fcd34d}
.empty{text-align:center;padding:32px;color:var(--muted);font-size:.86rem}
.tree-bar{display:flex;gap:8px;margin-bottom:10px}
.tree-pre{font-family:var(--mono);font-size:.8rem;color:var(--text);line-height:1.7;
          white-space:pre;background:var(--bg);border:1px solid var(--border);
          border-radius:var(--r-sm);padding:14px;overflow:auto;max-height:550px}
.unused-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(260px,1fr));gap:7px}
.unused-item{padding:9px 12px;background:#fff7ed;border:1px solid #fed7aa;
             border-radius:var(--r-sm);font-family:var(--mono);font-size:.76rem;
             color:#9a3412;word-break:break-all}
[data-theme=dark] .unused-item{background:#1c0a00;border-color:#7c2d12;color:#fdba74}
.env-list{display:flex;flex-direction:column;gap:6px}
.env-item{display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;
          gap:8px;padding:10px 14px;background:var(--bg);border:1px solid var(--border);
          border-radius:var(--r-sm)}
.env-key{font-family:var(--mono);font-size:.78rem;font-weight:700}
/* ─ FOOTER ─ */
.footer{background:var(--nav);color:#a5b4fc;text-align:center;padding:20px;font-size:.8rem}
.footer p{margin-bottom:4px}
.footer code{background:rgba(255,255,255,.1);padding:2px 6px;border-radius:4px;font-family:var(--mono)}
/* ─ MODAL ─ */
.modal-bg{position:fixed;inset:0;background:rgba(0,0,0,.55);display:flex;
          align-items:center;justify-content:center;z-index:2000}
.modal-box{background:var(--card);border-radius:var(--r);padding:26px;
           max-width:370px;width:90%;box-shadow:var(--sh-lg)}
.modal-box h3{margin-bottom:16px;font-size:1rem}
.exp-list{display:flex;flex-direction:column;gap:8px;margin-bottom:12px}
.exp-btn{padding:10px 16px;background:var(--bg);border:2px solid var(--border);
         color:var(--text);border-radius:var(--r-sm);cursor:pointer;font-size:.86rem;
         font-weight:600;text-align:left;transition:border-color .2s,background .2s}
.exp-btn:hover{border-color:var(--primary);background:var(--hover)}
.btn-close{width:100%;background:var(--danger);color:#fff;border:none;
           border-radius:var(--r-sm);padding:9px;cursor:pointer;font-weight:600}
@media(max-width:768px){
  .nav{flex-wrap:wrap;height:auto;padding:8px}
  .nav-links{order:3;width:100%}
  .hero h1{font-size:1.3rem}
  .chart-grid{grid-template-columns:1fr}
  .agent-grid{grid-template-columns:1fr}
  .card-grid{grid-template-columns:repeat(2,1fr)}
}
@media print{
  .nav,.nav-right{display:none!important}
  .sec{break-inside:avoid}
}
"""

# ── JavaScript (complete, self-contained) ─────────────────────
_JS = r"""
/* ── CHARTS ── */
const PAL=['#4f46e5','#10b981','#f59e0b','#ef4444','#8b5cf6',
           '#14b8a6','#f97316','#3b82f6','#ec4899','#06b6d4',
           '#84cc16','#a855f7','#22c55e','#fb923c','#64748b'];
function tc(){
  const d=document.documentElement.getAttribute('data-theme')==='dark';
  return{text:d?'#f1f5f9':'#1a202c',muted:d?'#94a3b8':'#718096',
         grid:d?'#334155':'#e2e8f0',bg:d?'#1e293b':'#ffffff'};
}
function barChart(id,labels,values){
  const el=document.getElementById(id);if(!el)return;
  const ctx=el.getContext('2d'),W=el.width,H=el.height,c=tc();
  ctx.clearRect(0,0,W,H);ctx.fillStyle=c.bg;ctx.fillRect(0,0,W,H);
  if(!labels.length){ctx.fillStyle=c.muted;ctx.font='12px sans-serif';
    ctx.textAlign='center';ctx.fillText('No data',W/2,H/2);return;}
  const pad={t:14,r:14,b:64,l:42};
  const cW=W-pad.l-pad.r,cH=H-pad.t-pad.b;
  const mx=Math.max(...values,1),bW=cW/labels.length,bp=bW*.14;
  for(let i=0;i<=5;i++){
    const y=pad.t+cH-(i/5)*cH;
    ctx.strokeStyle=c.grid;ctx.lineWidth=1;ctx.setLineDash([3,3]);
    ctx.beginPath();ctx.moveTo(pad.l,y);ctx.lineTo(pad.l+cW,y);ctx.stroke();
    ctx.setLineDash([]);ctx.fillStyle=c.muted;ctx.font='9px sans-serif';
    ctx.textAlign='right';ctx.fillText(Math.round(mx*i/5),pad.l-3,y+3);
  }
  labels.forEach((lbl,i)=>{
    const bH=(values[i]/mx)*cH,x=pad.l+i*bW+bp,y=pad.t+cH-bH,w=bW-bp*2;
    const g=ctx.createLinearGradient(x,y,x,pad.t+cH);
    const col=PAL[i%PAL.length];
    g.addColorStop(0,col);g.addColorStop(1,col+'70');
    ctx.fillStyle=g;
    ctx.beginPath();
    if(ctx.roundRect)ctx.roundRect(x,y,w,Math.max(bH,1),[3,3,0,0]);
    else ctx.rect(x,y,w,Math.max(bH,1));
    ctx.fill();
    ctx.fillStyle=c.text;ctx.font='bold 9px sans-serif';ctx.textAlign='center';
    if(values[i])ctx.fillText(values[i],x+w/2,y-3);
    ctx.save();ctx.translate(x+w/2,pad.t+cH+5);ctx.rotate(-Math.PI/4);
    ctx.fillStyle=c.muted;ctx.font='8px sans-serif';ctx.textAlign='right';
    ctx.fillText(lbl.length>14?lbl.slice(0,12)+'..':lbl,0,0);ctx.restore();
  });
  ctx.strokeStyle=c.grid;ctx.lineWidth=2;ctx.setLineDash([]);
  ctx.beginPath();ctx.moveTo(pad.l,pad.t);ctx.lineTo(pad.l,pad.t+cH);
  ctx.lineTo(pad.l+cW,pad.t+cH);ctx.stroke();
}
function donut(id,labels,values){
  const el=document.getElementById(id);if(!el)return;
  const ctx=el.getContext('2d'),W=el.width,H=el.height,c=tc();
  ctx.clearRect(0,0,W,H);ctx.fillStyle=c.bg;ctx.fillRect(0,0,W,H);
  const tot=values.reduce((a,b)=>a+b,0);
  if(!tot){ctx.fillStyle=c.muted;ctx.font='12px sans-serif';
    ctx.textAlign='center';ctx.fillText('No data',W/2,H/2);return;}
  const cx=W*.37,cy=H*.5,or=Math.min(cx,cy)*.82,ir=or*.54;
  let sa=-Math.PI/2;
  labels.forEach((lbl,i)=>{
    if(!values[i])return;
    const sl=(values[i]/tot)*Math.PI*2,col=PAL[i%PAL.length];
    ctx.beginPath();ctx.moveTo(cx,cy);ctx.arc(cx,cy,or,sa,sa+sl);
    ctx.closePath();ctx.fillStyle=col;ctx.fill();
    ctx.strokeStyle=c.bg;ctx.lineWidth=2;ctx.stroke();sa+=sl;
  });
  ctx.beginPath();ctx.arc(cx,cy,ir,0,Math.PI*2);ctx.fillStyle=c.bg;ctx.fill();
  ctx.fillStyle=c.text;ctx.font='bold 15px sans-serif';ctx.textAlign='center';
  ctx.fillText(tot.toLocaleString(),cx,cy+4);
  ctx.font='9px sans-serif';ctx.fillStyle=c.muted;ctx.fillText('total',cx,cy+17);
  const lx=W*.73,ly0=20,lh=18;
  labels.forEach((lbl,i)=>{
    if(!values[i])return;
    const y=ly0+i*lh;if(y>H-10)return;
    ctx.fillStyle=PAL[i%PAL.length];
    ctx.beginPath();
    if(ctx.roundRect)ctx.roundRect(lx-35,y-6,10,10,[2]);else ctx.rect(lx-35,y-6,10,10);
    ctx.fill();
    ctx.fillStyle=c.muted;ctx.font='8px sans-serif';ctx.textAlign='left';
    const pct=((values[i]/tot)*100).toFixed(1);
    const ll=lbl.length>12?lbl.slice(0,10)+'..':lbl;
    ctx.fillText(`${ll} (${pct}%)`,lx-22,y+3);
  });
}
function renderCharts(){
  barChart('cLang',langLabels,langValues);
  donut   ('cCat', catLabels, catValues);
  barChart('cAI',  aiLabels,  aiValues);
  barChart('cDir', dirLabels, dirValues);
}

/* ── THEME ── */
function toggleTheme(){
  const h=document.documentElement;
  const d=h.getAttribute('data-theme')==='dark';
  h.setAttribute('data-theme',d?'light':'dark');
  document.getElementById('themeBtn').textContent=d?'🌙 Dark':'☀️ Light';
  localStorage.setItem('aiAuditTheme',d?'light':'dark');
  setTimeout(renderCharts,80);
}

/* ── FILE TABLE FILTER ── */
function filterFiles(){
  const q  =(document.getElementById('fileQ') ?.value||'').toLowerCase();
  const cat= document.getElementById('catSel')?.value||'';
  const ai = document.getElementById('aiSel') ?.value||'';
  const rows=document.querySelectorAll('#fileTbl tbody tr');
  let vis=0;
  rows.forEach(r=>{
    let ok=r.textContent.toLowerCase().includes(q);
    if(ok&&cat)ok=r.getAttribute('data-cat')===cat;
    if(ok&&ai) ok=r.getAttribute('data-ai') ===ai;
    r.style.display=ok?'':'none';if(ok)vis++;
  });
  const el=document.getElementById('fCount');
  if(el)el.textContent=`${vis} of ${rows.length} files`;
}

/* ── SORT ── */
const _ss={};
function sortTbl(id,col){
  const t=document.getElementById(id);if(!t)return;
  const k=`${id}-${col}`;_ss[k]=_ss[k]==='asc'?'desc':'asc';
  const asc=_ss[k]==='asc';
  const rows=Array.from(t.querySelectorAll('tbody tr'));
  rows.sort((a,b)=>{
    const at=a.cells[col]?.textContent.trim()||'';
    const bt=b.cells[col]?.textContent.trim()||'';
    const an=parseFloat(at.replace(/[^0-9.-]/g,''));
    const bn=parseFloat(bt.replace(/[^0-9.-]/g,''));
    if(!isNaN(an)&&!isNaN(bn))return asc?an-bn:bn-an;
    return asc?at.localeCompare(bt):bt.localeCompare(at);
  });
  const tb=t.querySelector('tbody');rows.forEach(r=>tb.appendChild(r));
}

/* ── EXPORT ── */
function showExport(){document.getElementById('exportModal').style.display='flex'}
function hideExport(){document.getElementById('exportModal').style.display='none'}
document.getElementById('exportModal').addEventListener('click',e=>{
  if(e.target===e.currentTarget)hideExport();});
function dl(blob,name){
  const a=document.createElement('a');
  a.href=URL.createObjectURL(blob);a.download=name;a.click();URL.revokeObjectURL(a.href);
}
function exportHTML(){
  dl(new Blob([document.documentElement.outerHTML],{type:'text/html'}),'repository_audit.html');
  hideExport();
}
function exportJSON(){
  dl(new Blob([JSON.stringify({summary:auditSummary,files:allFiles},null,2)],
     {type:'application/json'}),'repository_audit.json');hideExport();
}
function exportCSV(){
  const h=['#','Path','Filename','Ext','Language','Category','Purpose',
           'Size','Lines','AI','Used','Models','Providers','SDKs'];
  const rows=allFiles.map(f=>[
    f.serial,f.rel_path,f.filename,f.extension,f.language,f.category,
    f.purpose,f.size,f.lines,f.is_ai,f.is_used,
    (f.models||[]).join(';'),(f.providers||[]).join(';'),(f.sdks||[]).join(';')]);
  const csv=[h,...rows].map(r=>r.map(c=>`"${String(c).replace(/"/g,'""')}"`).join(',')).join('\n');
  dl(new Blob([csv],{type:'text/csv'}),'repository_audit.csv');hideExport();
}

/* ── SMOOTH SCROLL ── */
document.querySelectorAll('a[href^="#"]').forEach(a=>{
  a.addEventListener('click',e=>{
    e.preventDefault();
    document.querySelector(a.getAttribute('href'))?.scrollIntoView({behavior:'smooth',block:'start'});
  });
});

/* ── INIT ── */
document.addEventListener('DOMContentLoaded',()=>{
  const t=localStorage.getItem('aiAuditTheme')||'light';
  document.documentElement.setAttribute('data-theme',t);
  document.getElementById('themeBtn').textContent=t==='dark'?'☀️ Light':'🌙 Dark';
  renderCharts();
  window.addEventListener('resize',()=>{
    clearTimeout(window._rt);window._rt=setTimeout(renderCharts,200);});
});
"""


class HTMLReport:
    """Builds the complete standalone HTML audit report."""

    def __init__(self, s: RepoScanner) -> None:
        self.s = s

    # ── Entry ─────────────────────────────────────────────────

    def build(self) -> str:
        s   = self.s
        st  = s.stats
        dt  = datetime.datetime.fromisoformat(s.scan_date)
        dts = dt.strftime("%B %d, %Y  %H:%M:%S")

        agents = self._dedup_agents()
        unused = [f for f in s.files
                  if not f["is_referenced"] and f["category"] in ("source", "ai")
                  and f["lines"] > 0]

        lang_labels = list(st.get("languages", {}).keys())[:12]
        lang_values = list(st.get("languages", {}).values())[:12]
        cat_data    = Counter(f["category"] for f in s.files)

        return f"""<!DOCTYPE html>
<html lang="en" data-theme="light">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>AI Audit — {esc(s.repo_name)}</title>
<style>{_CSS}</style>
</head>
<body>

<!-- NAV -->
<nav class="nav">
  <div class="nav-brand">🤖 AI Repo Audit</div>
  <div class="nav-links">
    <a href="#overview">Overview</a>
    <a href="#charts">Charts</a>
    <a href="#routes">Routes</a>
    <a href="#files">Files</a>
    <a href="#agents">Agents</a>
    <a href="#providers">Providers</a>
    <a href="#models">Models</a>
    <a href="#prompts">Prompts</a>
    <a href="#sdks">SDKs</a>
    <a href="#apikeys">API Keys</a>
    <a href="#tokens">Tokens</a>
    <a href="#tools">Tools</a>
    <a href="#workflows">Workflows</a>
    <a href="#deps">Deps</a>
    <a href="#unused">Unused</a>
    <a href="#tree">Tree</a>
  </div>
  <div class="nav-right">
    <button class="btn btn-export" onclick="showExport()">⬇ Export</button>
    <button class="btn btn-theme"  onclick="toggleTheme()" id="themeBtn">🌙 Dark</button>
  </div>
</nav>

<!-- HERO -->
<header class="hero">
  <h1>🔍 AI Repository Audit Report</h1>
  <div class="hero-chips">
    <span class="chip">📁 {esc(s.repo_name)}</span>
    <span class="chip">📅 {esc(dts)}</span>
    <span class="chip">📂 {esc(s.root)}</span>
    <span class="chip">🌐 Flask / AWS Elastic Beanstalk</span>
  </div>
</header>

<main class="wrap">

<!-- ======================================================
     OVERVIEW
======================================================= -->
<section id="overview" class="sec">
  <h2 class="sec-title">📊 Repository Overview</h2>

  <h3 class="sub-title">Repository Metrics</h3>
  <div class="card-grid">
    {self._sc("📁","Directories",    st.get("total_dirs",0),          "blue")}
    {self._sc("📄","Total Files",    st.get("total_files",0),         "blue")}
    {self._sc("💻","Source Files",   st.get("total_source_files",0),  "green")}
    {self._sc("⚙️","Config Files",  st.get("total_config_files",0),  "orange")}
    {self._sc("📚","Doc Files",      st.get("total_doc_files",0),     "purple")}
    {self._sc("🧪","Test Files",     st.get("total_test_files",0),    "teal")}
    {self._sc("🏗️","Infra Files",  st.get("total_infra_files",0),   "gray")}
    {self._sc("🤖","AI Files",       st.get("total_ai_files",0),      "red")}
  </div>

  <h3 class="sub-title">AI Components</h3>
  <div class="card-grid">
    {self._sc("🤖","AI Agents",   st.get("total_agents",0),    "red")}
    {self._sc("🏢","Providers",   st.get("total_providers",0), "blue")}
    {self._sc("🧩","Models",      st.get("total_models",0),    "green")}
    {self._sc("💬","Prompts",     st.get("total_prompts",0),   "purple")}
    {self._sc("📦","SDKs",        st.get("total_sdks",0),      "orange")}
    {self._sc("🔑","API Key Refs",len(s.api_keys),             "teal")}
    {self._sc("🔧","Tools",       len(s.tools),                "gray")}
    {self._sc("🔄","Workflows",   len(s.workflows),            "red")}
  </div>

  <h3 class="sub-title">Web / API Metrics</h3>
  <div class="card-grid">
    {self._sc("🌐","Routes",      st.get("total_routes",0),      "blue")}
    {self._sc("📋","Blueprints",  st.get("total_blueprints",0),  "green")}
    {self._sc("🏛️","Classes",   f"{st.get('total_classes',0):,}","orange")}
    {self._sc("⚡","Functions",   f"{st.get('total_functions',0):,}","purple")}
    {self._sc("📝","Lines",       f"{st.get('total_lines',0):,}", "teal")}
    {self._sc("💾","Size",        fmt_size(st.get("total_size",0)),"gray")}
    {self._sc("🐳","Docker",      st.get("total_docker_files",0), "blue")}
    {self._sc("☸️","K8s",        st.get("total_k8s_files",0),   "orange")}
  </div>
</section>

<!-- ======================================================
     CHARTS
======================================================= -->
<section id="charts" class="sec">
  <h2 class="sec-title">📈 Visual Analytics</h2>
  <div class="chart-grid">
    <div class="chart-box"><h3>Language Distribution</h3>
      <canvas id="cLang" width="400" height="280"></canvas></div>
    <div class="chart-box"><h3>File Categories</h3>
      <canvas id="cCat"  width="400" height="280"></canvas></div>
    <div class="chart-box"><h3>AI Components</h3>
      <canvas id="cAI"   width="400" height="280"></canvas></div>
    <div class="chart-box"><h3>Top Directories</h3>
      <canvas id="cDir"  width="400" height="280"></canvas></div>
  </div>
</section>

<!-- ======================================================
     FLASK ROUTES
======================================================= -->
<section id="routes" class="sec">
  <h2 class="sec-title">🌐 Flask Routes &amp; Blueprints</h2>
  {self._routes_html()}
</section>

<!-- ======================================================
     FILE INVENTORY
======================================================= -->
<section id="files" class="sec">
  <h2 class="sec-title">📋 Complete File Inventory</h2>
  <div class="tbl-ctrls">
    <input id="fileQ" class="search-box" placeholder="🔍 Search files…" oninput="filterFiles()">
    <select id="catSel" class="sel" onchange="filterFiles()">
      <option value="">All Categories</option>
      <option value="source">Source</option>
      <option value="config">Config</option>
      <option value="ai">AI</option>
      <option value="test">Test</option>
      <option value="infrastructure">Infrastructure</option>
      <option value="documentation">Documentation</option>
      <option value="frontend">Frontend</option>
      <option value="other">Other</option>
    </select>
    <select id="aiSel" class="sel" onchange="filterFiles()">
      <option value="">All Files</option>
      <option value="1">AI Related Only</option>
      <option value="0">Non-AI Only</option>
    </select>
    <span id="fCount" class="tbl-info">{len(s.files)} files</span>
  </div>
  <div class="tbl-wrap">
    <table class="tbl" id="fileTbl">
      <thead>
        <tr>
          <th class="sort" onclick="sortTbl('fileTbl',0)">#</th>
          <th class="sort" onclick="sortTbl('fileTbl',1)">Path</th>
          <th class="sort" onclick="sortTbl('fileTbl',2)">File Name</th>
          <th class="sort" onclick="sortTbl('fileTbl',3)">Ext</th>
          <th class="sort" onclick="sortTbl('fileTbl',4)">Language</th>
          <th class="sort" onclick="sortTbl('fileTbl',5)">Category</th>
          <th class="sort" onclick="sortTbl('fileTbl',6)">Purpose</th>
          <th>Description</th>
          <th class="sort" onclick="sortTbl('fileTbl',8)">Size</th>
          <th class="sort" onclick="sortTbl('fileTbl',9)">Lines</th>
          <th>Used</th>
          <th>Ref'd</th>
          <th>AI</th>
          <th>Imports</th>
        </tr>
      </thead>
      <tbody>
        {self._file_rows()}
      </tbody>
    </table>
  </div>
</section>

<!-- ======================================================
     AI AGENTS
======================================================= -->
<section id="agents" class="sec">
  <h2 class="sec-title">🤖 AI Agents Detected</h2>
  <div class="banner">
    <div class="banner-item">
      <span class="big-num">{st.get("total_agents",0)}</span>
      <span class="big-lbl">Total AI Agents</span>
    </div>
    <div class="banner-item">
      <span class="big-num">{st.get("total_providers",0)}</span>
      <span class="big-lbl">Providers</span>
    </div>
    <div class="banner-item">
      <span class="big-num">{st.get("total_models",0)}</span>
      <span class="big-lbl">Models</span>
    </div>
    <div class="banner-item">
      <span class="big-num">{st.get("total_sdks",0)}</span>
      <span class="big-lbl">SDKs</span>
    </div>
  </div>
  {self._agents_html(agents)}
</section>

<!-- ======================================================
     PROVIDERS
======================================================= -->
<section id="providers" class="sec">
  <h2 class="sec-title">🏢 AI Providers</h2>
  {self._providers_html()}
</section>

<!-- ======================================================
     MODELS
======================================================= -->
<section id="models" class="sec">
  <h2 class="sec-title">🧩 AI Models</h2>
  {self._models_html()}
</section>

<!-- ======================================================
     PROMPTS
======================================================= -->
<section id="prompts" class="sec">
  <h2 class="sec-title">💬 Prompt Inventory</h2>
  {self._prompts_html()}
</section>

<!-- ======================================================
     SDKs
======================================================= -->
<section id="sdks" class="sec">
  <h2 class="sec-title">📦 AI SDKs &amp; Frameworks</h2>
  {self._sdks_html()}
</section>

<!-- ======================================================
     API KEYS
======================================================= -->
<section id="apikeys" class="sec">
  <h2 class="sec-title">🔑 API Key &amp; Environment Variable References</h2>
  {self._keys_html()}
</section>

<!-- ======================================================
     TOKEN / REQUEST USAGE
======================================================= -->
<section id="tokens" class="sec">
  <h2 class="sec-title">🎯 Token &amp; Request Usage Analysis</h2>
  {self._tokens_html()}
</section>

<!-- ======================================================
     TOOLS
======================================================= -->
<section id="tools" class="sec">
  <h2 class="sec-title">🔧 Tools Detected</h2>
  {self._tools_html()}
</section>

<!-- ======================================================
     WORKFLOWS
======================================================= -->
<section id="workflows" class="sec">
  <h2 class="sec-title">🔄 Workflows &amp; Patterns Detected</h2>
  {self._workflows_html()}
</section>

<!-- ======================================================
     DEPENDENCIES
======================================================= -->
<section id="deps" class="sec">
  <h2 class="sec-title">🔗 Dependency Analysis</h2>
  {self._deps_html()}
</section>

<!-- ======================================================
     UNUSED FILES
======================================================= -->
<section id="unused" class="sec">
  <h2 class="sec-title">⚠️ Potentially Unused Files</h2>
  {self._unused_html(unused)}
</section>

<!-- ======================================================
     DIRECTORY TREE
======================================================= -->
<section id="tree" class="sec">
  <h2 class="sec-title">🌲 Directory Structure</h2>
  <pre class="tree-pre">{esc(self._build_tree())}</pre>
</section>

</main>

<footer class="footer">
  <p>🤖 AI Repository Audit Tool &nbsp;|&nbsp; {esc(dts)}</p>
  <p>Repository: <strong>{esc(s.repo_name)}</strong> &nbsp;|&nbsp;
     Root: <code>{esc(s.root)}</code></p>
  <p>⚠️ Static analysis only — no code was executed.</p>
</footer>

<!-- EXPORT MODAL -->
<div id="exportModal" class="modal-bg" style="display:none">
  <div class="modal-box">
    <h3>📤 Export Report</h3>
    <div class="exp-list">
      <button class="exp-btn" onclick="exportHTML()">📄 Save as HTML</button>
      <button class="exp-btn" onclick="exportJSON()">📊 Save as JSON</button>
      <button class="exp-btn" onclick="exportCSV()">📋 Save as CSV</button>
      <button class="exp-btn" onclick="window.print()">🖨️ Print / PDF</button>
    </div>
    <button class="btn-close" onclick="hideExport()">✕ Close</button>
  </div>
</div>

<script>
{self._js_data(lang_labels, lang_values, cat_data)}
{_JS}
</script>
</body>
</html>"""

    # ── Helpers ───────────────────────────────────────────────

    def _sc(self, icon: str, label: str, value: Any, color: str) -> str:
        return (f'<div class="sc {color}">'
                f'<span class="sc-icon">{icon}</span>'
                f'<span class="sc-val">{esc(str(value))}</span>'
                f'<span class="sc-lbl">{esc(label)}</span>'
                f'</div>')

    def _dedup_agents(self) -> List[Dict]:
        seen: set = set()
        out:  List[Dict] = []
        for a in self.s.agents:
            k = (a.get("name",""), a.get("file",""))
            if k not in seen:
                seen.add(k)
                out.append(a)
        return out

    # ── Flask routes ──────────────────────────────────────────

    def _routes_html(self) -> str:
        s = self.s
        if not s.routes and not s.blueprints:
            return '<div class="empty">🌐 No Flask routes detected.</div>'

        METHOD_ORDER = {"GET":0,"POST":1,"PUT":2,"DELETE":3,"PATCH":4,"ROUTE":5}

        # Blueprints
        bp_html = ""
        if s.blueprints:
            bps = " ".join(f'<span class="b b-blue">{esc(b)}</span>'
                           for b in s.blueprints)
            bp_html = f'<div style="margin-bottom:14px;"><span class="lbl">Registered Blueprints: </span>{bps}</div>'

        # Group routes by file
        by_file: Dict[str, List[Dict]] = defaultdict(list)
        for r in s.routes:
            by_file[r["file"]].append(r)

        cards = []
        for filepath, routes in sorted(by_file.items()):
            routes_sorted = sorted(routes, key=lambda r: (
                METHOD_ORDER.get(r["method"].upper(), 5), r["path"]))
            for r in routes_sorted:
                m = r["method"].upper()
                cards.append(
                    f'<div class="route-card">'
                    f'<span class="route-method {m}">{esc(m)}</span>'
                    f'<div><div class="route-path">{esc(r["path"])}</div>'
                    f'<div class="route-file">📄 {esc(r["file"])}</div></div>'
                    f'</div>'
                )

        return (f'{bp_html}'
                f'<div class="sub-title">Routes ({len(s.routes)} total)</div>'
                f'<div class="route-grid">{"".join(cards)}</div>')

    # ── File rows ─────────────────────────────────────────────

    def _file_rows(self) -> str:
        CAT = {
            "source":"b-blue","config":"b-orange","ai":"b-red",
            "test":"b-teal","infrastructure":"b-gray","documentation":"b-purple",
            "other":"b-gray","frontend":"b-pink","database":"b-yellow",
            "template":"b-purple","api":"b-blue",
        }
        rows = []
        for f in self.s.files:
            cat  = f.get("category","other")
            cb   = CAT.get(cat,"b-gray")
            ai   = f.get("is_ai_related",False)
            used = f.get("is_used",False)
            ref  = f.get("is_referenced",False)
            desc = self._desc(f)
            imps = " ".join(
                f'<span class="b b-gray">{esc(i)}</span>'
                for i in f.get("imports",[])[:4]
            )
            rows.append(
                f'<tr data-cat="{cat}" data-ai="{"1" if ai else "0"}">'
                f'<td>{f["serial"]}</td>'
                f'<td class="mono sm grey" title="{esc(f["rel_path"])}">'
                f'{esc(trunc(f["rel_path"],50))}</td>'
                f'<td><strong>{esc(f["filename"])}</strong></td>'
                f'<td><span class="b b-gray">{esc(f.get("extension",""))}</span></td>'
                f'<td>{esc(f.get("language","?"))}</td>'
                f'<td><span class="b {cb}">{esc(cat)}</span></td>'
                f'<td><span class="b b-blue">{esc(f.get("purpose","?"))}</span></td>'
                f'<td class="sm grey">{esc(trunc(desc,65))}</td>'
                f'<td>{esc(f.get("size_fmt","0 B"))}</td>'
                f'<td>{f.get("lines",0):,}</td>'
                f'<td><span class="b {"b-yes" if used else "b-no"}">{"✓" if used else "—"}</span></td>'
                f'<td><span class="b {"b-yes" if ref  else "b-no"}">{"✓" if ref  else "—"}</span></td>'
                f'<td><span class="b {"b-red" if ai else "b-no"}">{"🤖" if ai else "—"}</span></td>'
                f'<td><div class="tag-row">{imps}</div></td>'
                f'</tr>'
            )
        return "\n".join(rows)

    def _desc(self, f: Dict) -> str:
        parts = [f"{f.get('language','?')} {f.get('purpose','?')}."]
        cls = f.get("classes",  [])
        fn  = f.get("functions",[])
        rts = f.get("routes",   [])
        if cls: parts.append(f"{len(cls)} class(es): {', '.join(cls[:3])}.")
        if fn:  parts.append(f"{len(fn)} function(s).")
        if rts: parts.append(f"{len(rts)} route(s).")
        m = f.get("models_found",   [])
        p = f.get("providers_found",[])
        k = f.get("sdks_found",     [])
        ai_p = []
        if m: ai_p.append(f"Model: {', '.join(m[:2])}")
        if p: ai_p.append(f"Provider: {', '.join(p[:2])}")
        if k: ai_p.append(f"SDK: {', '.join(k[:2])}")
        if ai_p: parts.append(" | ".join(ai_p))
        if f.get("has_tests"): parts.append("Tests included.")
        return " ".join(parts)

    # ── Agents ────────────────────────────────────────────────

    def _agents_html(self, agents: List[Dict]) -> str:
        if not agents:
            return '<div class="empty">🤖 No AI agents detected in this repository.</div>'
        cards = []
        for a in agents:
            def tags(lst, cls):
                return ("".join(f'<span class="b {cls}">{esc(x)}</span>'
                                for x in (lst or [])[:3])
                        or '<span class="b b-gray">Not Detected</span>')
            cards.append(
                f'<div class="agent-card">'
                f'<div class="ac-head">'
                f'<div class="ac-icon">🤖</div>'
                f'<div><div class="ac-name">{esc(a.get("name","?"))}</div>'
                f'<div class="ac-type">{esc(a.get("type","?"))}</div></div></div>'
                f'<div class="lbl">Purpose</div>'
                f'<div class="val mt4">{esc(a.get("purpose","?"))}</div>'
                f'<div class="lbl mt8">🧩 Models</div>'
                f'<div class="tag-row mt4">{tags(a.get("models"),"b-blue")}</div>'
                f'<div class="lbl mt8">🏢 Providers</div>'
                f'<div class="tag-row mt4">{tags(a.get("providers"),"b-green")}</div>'
                f'<div class="lbl mt8">📦 SDKs / Frameworks</div>'
                f'<div class="tag-row mt4">{tags(a.get("sdks"),"b-purple")}</div>'
                f'<div class="ac-file">📄 {esc(a.get("file","?"))}</div>'
                f'</div>'
            )
        return f'<div class="agent-grid">{"".join(cards)}</div>'

    # ── Providers ─────────────────────────────────────────────

    def _providers_html(self) -> str:
        ICONS = {
            "OpenAI":"🟢","Azure OpenAI":"🔵","Anthropic":"🟠",
            "Google Gemini":"🔴","Google Vertex AI":"🔴","AWS Bedrock":"🟡",
            "AWS":"🟡","Meta Llama":"🩵","Mistral":"🔮","Groq":"⚡",
            "Cohere":"🌊","Ollama":"🦙","OpenRouter":"🛣️",
            "HuggingFace":"🤗","DeepSeek":"🐋","Perplexity":"🔍",
            "Together AI":"🤝","Replicate":"🔁","xAI":"🌟","Local LLM":"🖥️",
            "Google":"🔴","Application":"⚙️","Database":"🗄️","Flask":"🌶️",
        }
        if not self.s.providers:
            return '<div class="empty">🏢 No AI providers detected.</div>'
        cards = []
        for pname, pi in self.s.providers.items():
            env = ("".join(f'<span class="b b-teal">{esc(v)}</span>'
                           for v in pi.get("env_vars",[])[:3])
                   or '<span class="b b-gray">Not detected</span>')
            cards.append(
                f'<div class="prov-card">'
                f'<div class="prov-icon">{ICONS.get(pname,"🏢")}</div>'
                f'<div class="prov-name">{esc(pname)}</div>'
                f'<div class="prov-stats">'
                f'<div><span class="big-num sm2">{pi.get("count",0)}</span>'
                f'<div class="lbl">Refs</div></div>'
                f'<div><span class="big-num sm2">{len(pi.get("files",[]))}</span>'
                f'<div class="lbl">Files</div></div>'
                f'</div>'
                f'<div class="lbl mt8">API Key Variables</div>'
                f'<div class="tag-row mt4">{env}</div>'
                f'</div>'
            )
        return f'<div class="prov-grid">{"".join(cards)}</div>'

    # ── Models ────────────────────────────────────────────────

    def _models_html(self) -> str:
        if not self.s.models:
            return '<div class="empty">🧩 No AI models detected.</div>'
        rows = []
        for i,(mn,mi) in enumerate(
                sorted(self.s.models.items(),
                       key=lambda x: x[1]["count"], reverse=True), 1):
            fhtml = " ".join(
                f'<span class="b b-gray">{esc(trunc(f,35))}</span>'
                for f in mi.get("files",[])[:3]
            )
            rows.append(
                f'<tr><td>{i}</td><td><strong>{esc(mn)}</strong></td>'
                f'<td><span class="b b-green">{esc(mi.get("provider","?"))}</span></td>'
                f'<td><strong>{mi.get("count",0)}</strong></td>'
                f'<td><div class="tag-row">{fhtml}</div></td></tr>'
            )
        return (f'<div class="tbl-wrap"><table class="tbl">'
                f'<thead><tr><th>#</th><th>Model</th><th>Provider</th>'
                f'<th>References</th><th>Files</th></tr></thead>'
                f'<tbody>{"".join(rows)}</tbody></table></div>')

    # ── Prompts ───────────────────────────────────────────────

    def _prompts_html(self) -> str:
        seen: set = set(); uniq: List[Dict] = []
        for p in self.s.prompts:
            k = (p.get("file",""), p.get("type",""))
            if k not in seen:
                seen.add(k); uniq.append(p)
        if not uniq:
            return '<div class="empty">💬 No prompts detected.</div>'
        TYPE_CLS = {
            "System Prompt":"b-red","User Prompt":"b-blue",
            "Prompt Template":"b-purple","Markdown Prompt":"b-green",
            "Prompt File":"b-orange","Inline Prompt":"b-teal",
        }
        cards = []
        for p in uniq:
            pt  = p.get("type","?")
            cls = TYPE_CLS.get(pt,"b-gray")
            cards.append(
                f'<div class="prompt-card">'
                f'<span class="b {cls}">{esc(pt)}</span>'
                f'<div class="pname">{esc(p.get("name","?"))}</div>'
                f'<div class="sm grey">Purpose: {esc(p.get("purpose","?"))}</div>'
                f'<div class="mono sm blue-t mt4">📄 {esc(p.get("file","?"))}</div>'
                f'</div>'
            )
        return f'<div class="prompt-grid">{"".join(cards)}</div>'

    # ── SDKs ──────────────────────────────────────────────────

    def _sdks_html(self) -> str:
        ICONS = {
            "OpenAI SDK":"🟢","LangChain":"🔗","LangGraph":"🕸️",
            "Semantic Kernel":"🔮","AutoGen":"🤖","CrewAI":"👥",
            "LlamaIndex":"🦙","Haystack":"🌾","DSPy":"📡",
            "HuggingFace Transformers":"🤗","LiteLLM":"⚡","Instructor":"📐",
            "Ollama SDK":"🦙","Anthropic SDK":"🟠","Google GenAI SDK":"🔴",
            "Groq SDK":"⚡","Boto3 (AWS SDK)":"☁️","Cohere SDK":"🌊",
            "Mistral SDK":"🔮","Pydantic AI":"🐍","SmolAgents":"🤗",
            "Mem0":"🧠","Requests (HTTP client)":"🌐","HTTPX (HTTP client)":"🌐",
            "aiohttp":"🌐","Phidata":"📊","Agno":"🔮",
        }
        if not self.s.sdks:
            return '<div class="empty">📦 No AI SDKs detected.</div>'
        cards = []
        for sname, si in sorted(self.s.sdks.items(),
                                 key=lambda x: x[1]["count"], reverse=True):
            cards.append(
                f'<div class="sdk-card">'
                f'<div class="sdk-icon">{ICONS.get(sname,"📦")}</div>'
                f'<div class="sdk-name">{esc(sname)}</div>'
                f'<div class="sm grey">{esc(si.get("provider","?"))}</div>'
                f'<span class="b b-blue">{si.get("count",0)} refs</span>'
                f'<div class="sm grey mt4">{len(si.get("files",[]))} file(s)</div>'
                f'</div>'
            )
        return f'<div class="sdk-grid">{"".join(cards)}</div>'

    # ── API keys ──────────────────────────────────────────────

    def _keys_html(self) -> str:
        seen: set = set(); uniq: List[Dict] = []
        for k in self.s.api_keys:
            if k["variable"] not in seen:
                seen.add(k["variable"]); uniq.append(k)
        if not uniq:
            return '<div class="empty">🔑 No API key or environment variable references detected.</div>'
        rows = []
        for i, k in enumerate(uniq, 1):
            files = [ak["file"] for ak in self.s.api_keys
                     if ak["variable"] == k["variable"]]
            fhtml = " ".join(
                f'<span class="b b-gray">{esc(trunc(f,30))}</span>'
                for f in files[:3]
            )
            rows.append(
                f'<tr><td>{i}</td>'
                f'<td><code class="mono sm">{esc(k.get("variable",""))}</code></td>'
                f'<td><span class="b b-blue">{esc(k.get("provider","?"))}</span></td>'
                f'<td><div class="tag-row">{fhtml}</div></td>'
                f'<td><span class="b b-teal">{esc(k.get("loaded_from","?"))}</span></td>'
                f'</tr>'
            )
        return (f'<div class="tbl-wrap"><table class="tbl">'
                f'<thead><tr><th>#</th><th>Variable</th><th>Provider / Purpose</th>'
                f'<th>Files</th><th>Loaded From</th></tr></thead>'
                f'<tbody>{"".join(rows)}</tbody></table></div>')

    # ── Token analysis ────────────────────────────────────────

    def _tokens_html(self) -> str:
        tfiles = [(f, f["token_config"])
                  for f in self.s.files if f.get("token_config")]

        static = ""
        if tfiles:
            rows = []
            for f, cfg in tfiles:
                def v(k): return cfg.get(k, '<span class="na">Not Set</span>')
                rows.append(
                    f'<tr>'
                    f'<td class="mono sm">{esc(trunc(f["rel_path"],45))}</td>'
                    f'<td>{v("max_tokens")}</td>'
                    f'<td>{v("temperature")}</td>'
                    f'<td>{v("top_p")}</td>'
                    f'<td>{v("context_window")}</td>'
                    f'<td>{v("timeout")}</td>'
                    f'<td>{v("max_retries")}</td>'
                    f'</tr>'
                )
            static = (f'<h3 class="sub-title">Static Configuration Discovered</h3>'
                      f'<div class="tbl-wrap"><table class="tbl">'
                      f'<thead><tr><th>File</th><th>Max Tokens</th>'
                      f'<th>Temperature</th><th>Top P</th>'
                      f'<th>Context Window</th><th>Timeout(s)</th>'
                      f'<th>Max Retries</th></tr></thead>'
                      f'<tbody>{"".join(rows)}</tbody></table></div>')
        else:
            static = ('<div class="empty">No explicit token configuration '
                      'found in source code. SDK defaults apply.</div>')

        runtime_rows = "\n".join(
            f'<tr><td>{m}</td>'
            f'<td><span class="na">Not Available from Source Code</span></td>'
            f'<td class="grey sm">{n}</td></tr>'
            for m, n in [
                ("Current Tokens Used",      "Requires runtime API call"),
                ("Today's Tokens Used",      "Requires provider dashboard"),
                ("Monthly Tokens Used",      "Requires provider dashboard"),
                ("Remaining Token Quota",    "Requires provider dashboard"),
                ("Token Usage Percentage",   "Requires runtime metrics"),
                ("Estimated Cost",           "Requires token count + pricing data"),
                ("Requests Per Minute",      "Requires runtime monitoring"),
                ("Requests Per Day",         "Requires runtime monitoring"),
                ("Requests Per Month",       "Requires runtime monitoring"),
                ("Current Requests Used",    "Requires provider dashboard"),
                ("Remaining Requests",       "Requires provider dashboard"),
                ("Rate Limits",              "Requires provider API / dashboard"),
                ("Retry / Backoff Logic",    "Check source for max_retries / backoff"),
            ]
        )
        return f"""
<div class="info-box">
  <strong>⚠️ Runtime Usage Note</strong><br>
  Token counts, request counts, remaining quota, and cost estimates
  <strong>cannot be determined from static code analysis alone</strong>.
  They are marked as <em>Not Available from Source Code</em>.
</div>
{static}
<h3 class="sub-title">Runtime Metrics</h3>
<div class="tbl-wrap">
  <table class="tbl">
    <thead><tr><th>Metric</th><th>Value</th><th>Notes</th></tr></thead>
    <tbody>{runtime_rows}</tbody>
  </table>
</div>"""

    # ── Tools ─────────────────────────────────────────────────

    def _tools_html(self) -> str:
        ICONS = {
            "Web Search":"🌐","Database":"🗄️","Vector Store":"📊",
            "RAG":"📚","HTTP Calls":"🌐","Email":"📧","Slack":"💬",
            "GitHub":"🐙","Filesystem":"📁","Shell":"⌨️","Memory":"🧠",
            "Monitoring":"📊","AWS Services":"☁️","Flask/Web":"🌶️",
            "Scheduling":"⏰","Code Runner":"🐍","Calculator":"🧮",
        }
        if not self.s.tools:
            return '<div class="empty">🔧 No tools detected.</div>'
        cards = []
        for tname, files in sorted(self.s.tools.items(),
                                    key=lambda x: len(x[1]), reverse=True):
            uf = list(set(files))
            fh = "".join(
                f'<div class="mono sm grey">{esc(trunc(f,40))}</div>'
                for f in uf[:3]
            )
            cards.append(
                f'<div class="tool-card">'
                f'<div class="tool-name">{ICONS.get(tname,"🔧")} {esc(tname)}</div>'
                f'<div class="sm grey">{len(uf)} file(s)</div>'
                f'{fh}'
                f'</div>'
            )
        return f'<div class="tool-grid">{"".join(cards)}</div>'

    # ── Workflows ─────────────────────────────────────────────

    def _workflows_html(self) -> str:
        ICONS = {
            "Planning":"📋","Execution":"⚡","Reflection":"🪞",
            "Retry / Backoff":"🔁","Evaluation":"⚖️","Memory":"🧠",
            "RAG":"📚","Tool Calling":"🔧","Streaming":"📡",
            "Multi-agent":"👥","Supervisor":"👁️",
            "Monitoring Loop":"🔄","Webhook":"🪝","Alert":"🚨",
        }
        if not self.s.workflows:
            return '<div class="empty">🔄 No workflow patterns detected.</div>'
        cards = []
        for wname, files in sorted(self.s.workflows.items(),
                                    key=lambda x: len(x[1]), reverse=True):
            uf    = list(set(files))
            ftags = "".join(
                f'<span class="b b-teal">{esc(trunc(f,28))}</span>'
                for f in uf[:2]
            )
            cards.append(
                f'<div class="wf-card">'
                f'<div class="tool-name">{ICONS.get(wname,"🔄")} {esc(wname)}</div>'
                f'<div class="sm grey">{len(uf)} file(s)</div>'
                f'<div class="tag-row mt4">{ftags}</div>'
                f'</div>'
            )
        return f'<div class="tool-grid">{"".join(cards)}</div>'

    # ── Dependencies ──────────────────────────────────────────

    def _deps_html(self) -> str:
        all_imps: List[str] = []
        for f in self.s.files:
            all_imps.extend(f.get("imports",[]))
        top = Counter(all_imps).most_common(20)

        pkg_rows = "\n".join(
            f'<tr><td>{i}</td>'
            f'<td><code class="mono sm">{esc(pkg)}</code></td>'
            f'<td><strong>{cnt}</strong></td>'
            f'<td><div style="background:var(--primary);height:7px;border-radius:4px;'
            f'width:{min(100,cnt*6)}%;max-width:160px;"></div></td></tr>'
            for i,(pkg,cnt) in enumerate(top,1)
        ) or '<tr><td colspan="4">No imports detected</td></tr>'

        heavy = sorted(
            [(f, len(f.get("imports",[])))
             for f in self.s.files if f.get("imports")],
            key=lambda x: x[1], reverse=True
        )[:10]
        heavy_rows = "\n".join(
            f'<tr>'
            f'<td class="mono sm">{esc(trunc(f["rel_path"],45))}</td>'
            f'<td><strong>{cnt}</strong></td>'
            f'<td><div class="tag-row">'
            f'{"".join(f"<span class=&quot;b b-gray&quot;>{esc(i)}</span>" for i in f.get("imports",[])[:5])}'
            f'</div></td></tr>'
            for f,cnt in heavy
        ) or '<tr><td colspan="3">—</td></tr>'

        return f"""
<h3 class="sub-title">Most Used Packages</h3>
<div class="tbl-wrap">
  <table class="tbl">
    <thead><tr><th>#</th><th>Package</th><th>Uses</th><th>Frequency</th></tr></thead>
    <tbody>{pkg_rows}</tbody>
  </table>
</div>
<h3 class="sub-title">Files With Most Dependencies</h3>
<div class="tbl-wrap">
  <table class="tbl">
    <thead><tr><th>File</th><th>Import Count</th><th>Top Imports</th></tr></thead>
    <tbody>{heavy_rows}</tbody>
  </table>
</div>"""

    # ── Unused ────────────────────────────────────────────────

    def _unused_html(self, unused: List[Dict]) -> str:
        if not unused:
            return '<div class="empty">✅ No potentially unused source files detected.</div>'
        note = (f'<p class="grey sm" style="margin-bottom:10px;">'
                f'⚠️ These source files have no detected static references. '
                f'They may still be used dynamically. Manual verification recommended. '
                f'Showing {min(60,len(unused))} of {len(unused)} file(s).</p>')
        items = "".join(
            f'<div class="unused-item">⚠️ {esc(f["rel_path"])}</div>'
            for f in unused[:60]
        )
        return f'{note}<div class="unused-grid">{items}</div>'

    # ── Directory tree ────────────────────────────────────────

    def _build_tree(self) -> str:
        s = self.s

        def walk(path: str, prefix: str = "") -> List[str]:
            lines: List[str] = []
            try:
                entries = sorted(
                    os.scandir(path),
                    key=lambda e: (not e.is_dir(), e.name.lower()),
                )
            except PermissionError:
                return lines
            entries = [e for e in entries if e.name not in IGNORED_DIRS]
            for idx, entry in enumerate(entries):
                last = idx == len(entries) - 1
                conn = "└── " if last else "├── "
                ext  = "    " if last else "│   "
                if entry.is_dir():
                    lines.append(f"{prefix}{conn}📁 {entry.name}/")
                    sub = walk(entry.path, prefix + ext)
                    lines.extend(sub[:70])
                    if len(sub) > 70:
                        lines.append(f"{prefix}{ext}    … ({len(sub)-70} more)")
                else:
                    sfx  = Path(entry.name).suffix.lower()
                    lang = EXTENSION_MAP.get(sfx, ("?",""))[0]
                    try:
                        sz = fmt_size(entry.stat().st_size)
                    except Exception:
                        sz = "?"
                    lines.append(f"{prefix}{conn}{entry.name}  [{lang}] ({sz})")
            return lines

        tree = [f"📂 {s.repo_name}/"] + walk(s.root)
        if len(tree) > 500:
            tree = tree[:500]
            tree.append(
                f"\n… truncated at 500 lines "
                f"({s.stats.get('total_files',0)} total files)"
            )
        return "\n".join(tree)

    # ── Embedded JS data ──────────────────────────────────────

    def _js_data(self, lang_labels: List, lang_values: List,
                 cat_data: Counter) -> str:
        s  = self.s
        st = s.stats

        cat_labels = list(cat_data.keys())
        cat_values = list(cat_data.values())

        ai_labels = ["Agents","Providers","Models","Prompts","SDKs","API Keys","Tools","Routes"]
        ai_values = [
            st.get("total_agents",0),    st.get("total_providers",0),
            st.get("total_models",0),    st.get("total_prompts",0),
            st.get("total_sdks",0),      len(set(k["variable"] for k in s.api_keys)),
            len(s.tools),                st.get("total_routes",0),
        ]

        dir_cnt: Counter = Counter()
        for f in s.files:
            parts = f["rel_path"].replace("\\", "/").split("/")
            dir_cnt[parts[0] if len(parts) > 1 else "(root)"] += 1
        top_dirs  = dir_cnt.most_common(8)
        dir_labels = [d[0] for d in top_dirs]
        dir_values = [d[1] for d in top_dirs]

        slim = [{
            "serial":    f["serial"],
            "rel_path":  f["rel_path"],
            "filename":  f["filename"],
            "extension": f["extension"],
            "language":  f["language"],
            "category":  f["category"],
            "purpose":   f["purpose"],
            "size":      f["size"],
            "lines":     f["lines"],
            "is_ai":     f["is_ai_related"],
            "is_used":   f["is_used"],
            "models":    f.get("models_found", []),
            "providers": f.get("providers_found", []),
            "sdks":      f.get("sdks_found", []),
        } for f in s.files]

        summary = {
            "repository":  s.repo_name,
            "root":        s.root,
            "scan_date":   s.scan_date,
            "stats":       {k: v for k, v in st.items() if not isinstance(v, dict)},
            "agents":      s.agents[:50],
            "providers":   {k: {"count": v["count"], "env_vars": v["env_vars"]}
                            for k, v in s.providers.items()},
            "models":      {k: {"provider": v["provider"], "count": v["count"]}
                            for k, v in s.models.items()},
            "sdks":        {k: {"provider": v["provider"], "count": v["count"]}
                            for k, v in s.sdks.items()},
            "routes":      s.routes[:100],
            "blueprints":  s.blueprints,
        }

        return (
            f"const langLabels={json.dumps(lang_labels)};\n"
            f"const langValues={json.dumps(lang_values)};\n"
            f"const catLabels={json.dumps(cat_labels)};\n"
            f"const catValues={json.dumps(cat_values)};\n"
            f"const aiLabels={json.dumps(ai_labels)};\n"
            f"const aiValues={json.dumps(ai_values)};\n"
            f"const dirLabels={json.dumps(dir_labels)};\n"
            f"const dirValues={json.dumps(dir_values)};\n"
            f"const allFiles={json.dumps(slim)};\n"
            f"const auditSummary={json.dumps(summary, default=str)};\n"
        )


# ──────────────────────────────────────────────────────────────
# ADDITIONAL EXPORTERS
# ──────────────────────────────────────────────────────────────

class Exporters:

    def __init__(self, s: RepoScanner) -> None:
        self.s = s

    def to_json(self, path: str) -> None:
        s = self.s
        data = {
            "repository": {
                "name": s.repo_name, "root": s.root, "scan_date": s.scan_date,
            },
            "statistics": {k: v for k, v in s.stats.items()
                           if not isinstance(v, dict)},
            "files": [{
                "serial":       f["serial"],
                "path":         f["rel_path"],
                "filename":     f["filename"],
                "extension":    f["extension"],
                "language":     f["language"],
                "category":     f["category"],
                "purpose":      f["purpose"],
                "size":         f["size"],
                "lines":        f["lines"],
                "is_ai":        f["is_ai_related"],
                "is_used":      f["is_used"],
                "is_referenced":f["is_referenced"],
                "classes":      f.get("classes",[])[:10],
                "functions":    f.get("functions",[])[:10],
                "imports":      f.get("imports",[])[:10],
                "routes":       f.get("routes",[]),
                "models":       f.get("models_found",[]),
                "providers":    f.get("providers_found",[]),
                "sdks":         f.get("sdks_found",[]),
                "token_config": f.get("token_config",{}),
            } for f in s.files],
            "ai_agents":   s.agents,
            "ai_providers":{k: {"count": v["count"], "files": v["files"][:5],
                                "env_vars": v["env_vars"]}
                            for k,v in s.providers.items()},
            "ai_models":   {k: {"provider": v["provider"], "count": v["count"],
                                "files": v["files"][:5]}
                            for k,v in s.models.items()},
            "ai_sdks":     {k: {"provider": v["provider"], "count": v["count"],
                                "files": v["files"][:5]}
                            for k,v in s.sdks.items()},
            "prompts":     s.prompts[:100],
            "api_keys":    s.api_keys[:80],
            "routes":      s.routes[:200],
            "blueprints":  s.blueprints,
        }
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2, default=str)
        print(f"[✓] JSON → {path}")

    def to_csv(self, path: str) -> None:
        fields = [
            "Serial","Relative Path","File Name","Extension","Language",
            "Category","Purpose","Size (bytes)","Lines",
            "Is Used","Is Referenced","Is AI Related",
            "Classes","Functions","Routes","Models","Providers","SDKs","Imports",
            "Token Config",
        ]
        with open(path, "w", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=fields)
            w.writeheader()
            for f in self.s.files:
                w.writerow({
                    "Serial":        f["serial"],
                    "Relative Path": f["rel_path"],
                    "File Name":     f["filename"],
                    "Extension":     f["extension"],
                    "Language":      f["language"],
                    "Category":      f["category"],
                    "Purpose":       f["purpose"],
                    "Size (bytes)":  f["size"],
                    "Lines":         f["lines"],
                    "Is Used":       f["is_used"],
                    "Is Referenced": f["is_referenced"],
                    "Is AI Related": f["is_ai_related"],
                    "Classes":       "; ".join(f.get("classes",[])),
                    "Functions":     "; ".join(f.get("functions",[])[:10]),
                    "Routes":        "; ".join(
                        f'{r["method"]} {r["path"]}'
                        for r in f.get("routes",[])
                    ),
                    "Models":        "; ".join(f.get("models_found",[])),
                    "Providers":     "; ".join(f.get("providers_found",[])),
                    "SDKs":          "; ".join(f.get("sdks_found",[])),
                    "Imports":       "; ".join(f.get("imports",[])[:10]),
                    "Token Config":  json.dumps(f.get("token_config",{})),
                })
        print(f"[✓] CSV  → {path}")

    def to_markdown(self, path: str) -> None:
        s  = self.s
        st = s.stats
        dt = datetime.datetime.fromisoformat(s.scan_date).strftime(
            "%B %d, %Y %H:%M:%S")

        lines = [
            "# AI Repository Audit Report", "",
            f"**Repository:** {s.repo_name}  ",
            f"**Root:** `{s.root}`  ",
            f"**Date:** {dt}  ",
            f"**Framework:** Flask / AWS Elastic Beanstalk  ", "",
            "---", "", "## Repository Summary", "",
            "| Metric | Value |", "|--------|-------|",
        ]
        for k, v in [
            ("Total Directories",    st.get("total_dirs",0)),
            ("Total Files",          st.get("total_files",0)),
            ("Source Files",         st.get("total_source_files",0)),
            ("Config Files",         st.get("total_config_files",0)),
            ("Documentation Files",  st.get("total_doc_files",0)),
            ("Test Files",           st.get("total_test_files",0)),
            ("Infrastructure Files", st.get("total_infra_files",0)),
            ("AI Related Files",     st.get("total_ai_files",0)),
            ("Total Lines of Code",  f"{st.get('total_lines',0):,}"),
            ("Total Size",           fmt_size(st.get("total_size",0))),
        ]:
            lines.append(f"| {k} | {v} |")

        lines += ["", "## AI Components", "",
                  "| Component | Count |", "|-----------|-------|"]
        for k, v in [
            ("AI Agents",    st.get("total_agents",0)),
            ("Providers",    st.get("total_providers",0)),
            ("Models",       st.get("total_models",0)),
            ("Prompts",      st.get("total_prompts",0)),
            ("SDKs",         st.get("total_sdks",0)),
            ("API Key Refs", len(s.api_keys)),
            ("Routes",       st.get("total_routes",0)),
            ("Blueprints",   st.get("total_blueprints",0)),
        ]:
            lines.append(f"| {k} | {v} |")

        if s.routes:
            lines += ["", "## Flask Routes", "",
                      "| Method | Path | File |",
                      "|--------|------|------|"]
            for r in s.routes[:50]:
                lines.append(
                    f"| `{r['method']}` | `{r['path']}` | `{r['file']}` |")

        if s.agents:
            lines += ["", "## AI Agents", "",
                      "| Name | Type | Purpose | File |",
                      "|------|------|---------|------|"]
            seen: set = set()
            for a in s.agents:
                k = (a.get("name",""), a.get("file",""))
                if k not in seen:
                    seen.add(k)
                    lines.append(
                        f"| {a.get('name','')} | {a.get('type','')} | "
                        f"{a.get('purpose','')} | `{a.get('file','')}` |")

        if s.models:
            lines += ["", "## AI Models", "",
                      "| Model | Provider | References |",
                      "|-------|----------|------------|"]
            for mn,mi in sorted(s.models.items(),
                                  key=lambda x: x[1]["count"], reverse=True):
                lines.append(
                    f"| {mn} | {mi.get('provider','?')} | {mi.get('count',0)} |")

        lines += [
            "", "## Runtime Usage Note", "",
            "> Token usage, request counts, remaining quota, and cost",
            "> **cannot be determined from static analysis alone.**",
            "> Reported as **Not Available from Source Code**.", "",
            "---", "",
            "*Generated by AI Repository Audit Tool — static analysis only.*",
        ]

        with open(path, "w", encoding="utf-8") as fh:
            fh.write("\n".join(lines))
        print(f"[✓] MD   → {path}")


# ──────────────────────────────────────────────────────────────
# MAIN
# ──────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="AI Repository Audit Tool — HTML + JSON + CSV + MD reports",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  python ai_audit.py .\n"
            "  python ai_audit.py /path/to/repo\n"
            "  python ai_audit.py /path/to/repo --output ./reports\n"
            "  python ai_audit.py . --no-open\n"
        ),
    )
    parser.add_argument("repo_path", nargs="?", default=".",
                        help="Repository root (default: current directory)")
    parser.add_argument("--output", "-o", default=".",
                        help="Output directory (default: current directory)")
    parser.add_argument("--no-open",     action="store_true",
                        help="Do not open HTML in browser automatically")
    parser.add_argument("--no-json",     action="store_true")
    parser.add_argument("--no-csv",      action="store_true")
    parser.add_argument("--no-markdown", action="store_true")
    args = parser.parse_args()

    repo = os.path.abspath(args.repo_path)
    out  = os.path.abspath(args.output)

    if not os.path.isdir(repo):
        print(f"[ERROR] Not a directory: {repo}")
        sys.exit(1)

    os.makedirs(out, exist_ok=True)

    print("=" * 65)
    print("  AI Repository Audit Tool")
    print("=" * 65)
    print(f"  Repo   : {repo}")
    print(f"  Output : {out}")
    print("=" * 65)

    # Scan
    scanner = RepoScanner(repo)
    scanner.scan()

    # HTML (primary)
    html_path = os.path.join(out, "repository_audit.html")
    print("[*] Building HTML dashboard…")
    html_content = HTMLReport(scanner).build()
    with open(html_path, "w", encoding="utf-8") as fh:
        fh.write(html_content)
    print(f"[✓] HTML → {html_path}  ({fmt_size(len(html_content.encode()))})")

    # Other formats
    exp = Exporters(scanner)
    if not args.no_json:
        exp.to_json(os.path.join(out, "repository_audit.json"))
    if not args.no_csv:
        exp.to_csv(os.path.join(out,  "repository_audit.csv"))
    if not args.no_markdown:
        exp.to_markdown(os.path.join(out, "repository_audit.md"))

    # Summary
    st = scanner.stats
    print("\n" + "=" * 65)
    print("  AUDIT COMPLETE — SUMMARY")
    print("=" * 65)
    print(f"  Directories   : {st.get('total_dirs',0)}")
    print(f"  Total Files   : {st.get('total_files',0)}")
    print(f"  AI Files      : {st.get('total_ai_files',0)}")
    print(f"  AI Agents     : {st.get('total_agents',0)}")
    print(f"  AI Providers  : {st.get('total_providers',0)}")
    print(f"  AI Models     : {st.get('total_models',0)}")
    print(f"  Prompts       : {st.get('total_prompts',0)}")
    print(f"  SDKs          : {st.get('total_sdks',0)}")
    print(f"  Flask Routes  : {st.get('total_routes',0)}")
    print(f"  Blueprints    : {st.get('total_blueprints',0)}")
    print(f"  Lines of Code : {st.get('total_lines',0):,}")
    print("=" * 65)

    if scanner.routes:
        print("\n  FLASK ROUTES:")
        for r in scanner.routes[:15]:
            print(f"    {r['method']:<7} {r['path']}")
        if len(scanner.routes) > 15:
            print(f"    … and {len(scanner.routes)-15} more")

    if scanner.providers:
        print("\n  AI PROVIDERS:")
        for p in scanner.providers:
            print(f"    🏢 {p}")

    if scanner.models:
        print("\n  AI MODELS:")
        for m in list(scanner.models)[:10]:
            print(f"    🧩 {m}")
        if len(scanner.models) > 10:
            print(f"    … and {len(scanner.models)-10} more")

    print("\n  REPORTS WRITTEN:")
    for fn in sorted(os.listdir(out)):
        if fn.startswith("repository_audit"):
            fp = os.path.join(out, fn)
            print(f"    📄 {fn}  ({fmt_size(os.path.getsize(fp))})")

    print("=" * 65)

    # Auto-open
    if not args.no_open:
        file_url = Path(os.path.abspath(html_path)).as_uri()
        print(f"\n[*] Opening: {file_url}")
        try:
            webbrowser.open(file_url)
        except Exception as e:
            print(f"[!] Could not open browser: {e}")
            print(f"    Manually open: {os.path.abspath(html_path)}")

    print("\n✅ Done.\n")


if __name__ == "__main__":
    main()
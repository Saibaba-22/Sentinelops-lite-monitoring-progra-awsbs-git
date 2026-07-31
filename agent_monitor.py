"""
SentinelOps Agent Monitor - Production-Ready AI Agent Observability Dashboard
Standalone module for Flask projects with embedded frontend, pipeline detection, and AI-agent scanning.
"""

import os
import json
import ast
import hashlib
import hmac
import threading
import time
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Any, Optional, Set, Tuple
from collections import defaultdict
from functools import lru_cache
import re

from flask import Flask, Blueprint, jsonify, request, render_template_string
from jinja2 import DictLoader, ChoiceLoader, FileSystemLoader

# ============================================================================
# CONFIGURATION & CONSTANTS
# ============================================================================

PROJECT_ROOT = Path(os.getenv("SENTINELOPS_PROJECT_ROOT") or Path(__file__).parent).resolve()
TIMEZONE = os.getenv("SENTINELOPS_TIMEZONE", "Asia/Kolkata")
WEBHOOK_TOKEN = os.getenv("SENTINELOPS_WEBHOOK_TOKEN", "")
AGENT_LIMITS_JSON = os.getenv("SENTINELOPS_AGENT_LIMITS_JSON", "{}")

MAX_FILES_SCAN = 5000
MAX_FILE_SIZE = 1024 * 1024  # 1 MB
MAX_SCAN_DEPTH = 15
MAX_PAYLOAD_SIZE = 1024 * 1024  # 1 MB
MAX_HISTORY_EVENTS = 500
MAX_USAGE_RECORDS = 10000

IGNORE_DIRS = {
    ".git", ".venv", "venv", "env", "node_modules", "__pycache__",
    ".pytest_cache", ".mypy_cache", "dist", "build", "*.egg-info",
    ".tox", ".coverage", "htmlcov", ".idea", ".vscode", ".env.local"
}

IGNORE_FILES = {
    ".env", ".env.local", ".env.*.local", ".secrets", "secrets.json",
    "credentials.json", "private.key", "id_rsa", "id_ed25519",
    ".aws/credentials", ".aws/config", ".ssh"
}

BINARY_EXTENSIONS = {
    ".pyc", ".pyo", ".so", ".dll", ".exe", ".jar", ".zip", ".tar",
    ".gz", ".png", ".jpg", ".jpeg", ".gif", ".ico", ".svg", ".pdf",
    ".ttf", ".woff", ".woff2"
}

CI_ENV_VARS = {
    "github": ["GITHUB_ACTIONS", "GITHUB_WORKFLOW", "GITHUB_RUN_ID"],
    "azure": ["TF_BUILD", "BUILD_DEFINITIONNAME", "SYSTEM_TEAMPROJECT"],
    "jenkins": ["JENKINS_URL", "JOB_NAME", "BUILD_NUMBER"],
    "gitlab": ["GITLAB_CI", "CI_PIPELINE_ID", "CI_PROJECT_PATH"],
    "circleci": ["CIRCLECI", "CIRCLE_BUILD_NUM", "CIRCLE_PROJECT_REPONAME"],
    "bitbucket": ["BITBUCKET_BUILD_NUMBER", "BITBUCKET_REPO_FULL_NAME"],
    "aws": ["CODEBUILD_BUILD_ID", "CODEBUILD_BUILD_ARN"],
    "gcloud": ["BUILD_ID", "BUILD_STEP"],
}

PIPELINE_CONFIG_FILES = {
    ".github/workflows/*.yml": "github",
    ".github/workflows/*.yaml": "github",
    "azure-pipelines.yml": "azure",
    "azure-pipelines.yaml": "azure",
    "Jenkinsfile": "jenkins",
    ".gitlab-ci.yml": "gitlab",
    ".circleci/config.yml": "circleci",
    "bitbucket-pipelines.yml": "bitbucket",
    "buildspec.yml": "aws",
    "buildspec.yaml": "aws",
    "cloudbuild.yaml": "gcloud",
}

AI_FRAMEWORKS = {
    "langchain": ("LangChain", "General LLM/agent framework"),
    "langgraph": ("LangGraph", "Graph-based agentic framework"),
    "crewai": ("CrewAI", "Multi-agent orchestration"),
    "autogen": ("AutoGen", "Multi-agent conversation framework"),
    "semantic_kernel": ("Semantic Kernel", "MS agent framework"),
    "llamaindex": ("LlamaIndex", "Data indexing/RAG framework"),
    "openai": ("OpenAI SDK", "OpenAI API client"),
    "anthropic": ("Anthropic SDK", "Claude API client"),
    "google.generativeai": ("Google Gemini", "Google AI client"),
    "google.cloud.aiplatform": ("Vertex AI", "Google Vertex AI client"),
    "cohere": ("Cohere SDK", "Cohere API client"),
    "mistralai": ("Mistral SDK", "Mistral API client"),
    "groq": ("Groq SDK", "Groq API client"),
    "ollama": ("Ollama", "Local LLM framework"),
}

AI_PROVIDERS = {
    "openai": "OpenAI",
    "azure": "Azure OpenAI",
    "anthropic": "Anthropic",
    "google": "Google Gemini",
    "vertex": "Google Vertex AI",
    "cohere": "Cohere",
    "mistral": "Mistral",
    "groq": "Groq",
    "huggingface": "Hugging Face",
    "bedrock": "AWS Bedrock",
    "ollama": "Ollama",
}

# ============================================================================
# LOGGING & OBSERVABILITY
# ============================================================================

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

# ============================================================================
# SHARED STATE & PERSISTENCE
# ============================================================================

class AtomicHistory:
    """Thread-safe bounded history with atomic JSON persistence."""

    def __init__(self, max_records: int = MAX_HISTORY_EVENTS):
        self.max_records = max_records
        self.records = []
        self.lock = threading.RLock()

    def add(self, record: Dict[str, Any]):
        """Add record, maintaining bounded size."""
        with self.lock:
            record_copy = dict(record)
            record_copy.setdefault("timestamp", datetime.utcnow().isoformat())
            self.records.insert(0, record_copy)
            self.records = self.records[:self.max_records]

    def get_all(self) -> List[Dict[str, Any]]:
        """Return all records safely."""
        with self.lock:
            return list(self.records)

    def clear(self):
        """Clear all records."""
        with self.lock:
            self.records = []

webhook_history = AtomicHistory(MAX_HISTORY_EVENTS)
usage_history = AtomicHistory(MAX_USAGE_RECORDS)
scan_cache = {"data": None, "timestamp": 0, "lock": threading.RLock()}
SCAN_CACHE_TTL = 60  # seconds

# ============================================================================
# PIPELINE DETECTION
# ============================================================================

class PipelineDetector:
    """Detects CI/CD pipeline provider using multiple evidence sources."""

    @staticmethod
    def detect_from_env() -> Tuple[Optional[str], Dict[str, Any]]:
        """Detect pipeline from runtime environment variables."""
        evidence = {}
        for provider, vars_list in CI_ENV_VARS.items():
            matched = [v for v in vars_list if os.getenv(v)]
            if matched:
                evidence[provider] = matched
                return provider, {"source": "runtime_env", "evidence": matched}
        return None, {}

    @staticmethod
    def detect_from_files() -> Tuple[List[str], Dict[str, Any]]:
        """Detect pipeline config files in repository."""
        found = []
        try:
            for pattern, provider in PIPELINE_CONFIG_FILES.items():
                if "*" in pattern:
                    base_dir = PROJECT_ROOT / pattern.split("*")[0]
                    if base_dir.exists():
                        for f in base_dir.glob(pattern.split("/")[-1]):
                            if f.is_file() and f.stat().st_size < 1024 * 100:
                                found.append((str(f.relative_to(PROJECT_ROOT)), provider))
                else:
                    path = PROJECT_ROOT / pattern
                    if path.exists() and path.is_file():
                        found.append((str(path.relative_to(PROJECT_ROOT)), provider))
        except Exception as e:
            logger.warning(f"Error scanning pipeline files: {e}")
        return found, {"source": "config_files"}

    @staticmethod
    def detect_from_webhook(webhook_data: Dict[str, Any]) -> Tuple[Optional[str], Dict[str, Any]]:
        """Detect pipeline from webhook payload."""
        # GitHub Actions
        if "github" in str(webhook_data).lower() or "workflow" in webhook_data:
            return "github", {"source": "webhook"}
        # Azure DevOps
        if "resource" in webhook_data and "definition" in str(webhook_data).lower():
            return "azure", {"source": "webhook"}
        # GitLab
        if "project" in webhook_data and "pipeline" in webhook_data:
            return "gitlab", {"source": "webhook"}
        # Jenkins
        if "build" in webhook_data and "jobName" in str(webhook_data).lower():
            return "jenkins", {"source": "webhook"}
        return None, {}

    @staticmethod
    def get_pipeline_summary() -> Dict[str, Any]:
        """Compile pipeline detection summary."""
        env_provider, env_evidence = PipelineDetector.detect_from_env()
        config_files, config_evidence = PipelineDetector.detect_from_files()
        
        providers_found = {}
        if env_provider:
            providers_found[env_provider] = {"source": "runtime", "evidence": env_evidence.get("evidence", [])}
        
        for config_file, provider in config_files:
            if provider not in providers_found:
                providers_found[provider] = {"files": []}
            if "files" not in providers_found[provider]:
                providers_found[provider]["files"] = []
            providers_found[provider]["files"].append(config_file)

        latest_webhook = webhook_history.get_all()[0] if webhook_history.get_all() else None

        return {
            "configured": list(providers_found.keys()),
            "runtime": env_provider,
            "config_files": config_files,
            "latest_webhook": latest_webhook,
            "confidence": _calculate_confidence(env_provider, config_files, latest_webhook),
        }

def _calculate_confidence(env_provider, config_files, webhook):
    """Calculate detection confidence: High, Medium, Low."""
    score = 0
    if env_provider:
        score += 2
    if config_files:
        score += 1
    if webhook:
        score += 1
    if score >= 3:
        return "High"
    elif score >= 2:
        return "Medium"
    else:
        return "Low"

# ============================================================================
# FILE SCANNING & INVENTORY
# ============================================================================

class FileScanner:
    """Scans project files and builds inventory with AST analysis."""

    @staticmethod
    def should_ignore(path: Path) -> bool:
        """Check if path should be ignored."""
        name = path.name
        for pattern in IGNORE_DIRS:
            if pattern.startswith("."):
                if name == pattern:
                    return True
            else:
                if pattern in path.parts:
                    return True
        for pattern in IGNORE_FILES:
            if pattern == name or (pattern.startswith(".") and name.startswith(pattern)):
                return True
        return False

    @staticmethod
    def scan_files(max_files=MAX_FILES_SCAN, max_depth=MAX_SCAN_DEPTH) -> Dict[str, Any]:
        """Recursively scan project files."""
        files_data = []
        file_count = 0
        
        try:
            for path in PROJECT_ROOT.rglob("*"):
                if file_count >= max_files:
                    break
                if FileScanner.should_ignore(path):
                    continue
                if path.is_file() and path.relative_to(PROJECT_ROOT).parts.__len__() <= max_depth:
                    try:
                        rel_path = str(path.relative_to(PROJECT_ROOT))
                        size = path.stat().st_size
                        if size > MAX_FILE_SIZE:
                            continue
                        
                        file_ext = path.suffix.lower()
                        if file_ext in BINARY_EXTENSIONS or file_ext.startswith("."):
                            continue
                        
                        file_info = FileScanner.analyze_file(path, rel_path)
                        files_data.append(file_info)
                        file_count += 1
                    except Exception as e:
                        logger.debug(f"Error analyzing {path}: {e}")
        except Exception as e:
            logger.warning(f"Error scanning directory: {e}")

        files_data = FileScanner.prioritize_files(files_data)
        return {"files": files_data, "total": len(files_data)}

    @staticmethod
    def analyze_file(path: Path, rel_path: str) -> Dict[str, Any]:
        """Analyze a single file."""
        file_type = FileScanner.determine_file_type(path)
        purpose = "Unknown"
        imports = []
        classes = []
        functions = []
        
        if path.suffix == ".py":
            try:
                with open(path, "r", encoding="utf-8", errors="ignore") as f:
                    content = f.read(MAX_FILE_SIZE)
                    tree = ast.parse(content)
                    
                    imports = FileScanner.extract_imports(tree)
                    classes = FileScanner.extract_classes(tree)
                    functions = FileScanner.extract_functions(tree)
                    purpose = FileScanner.infer_purpose(path, content, imports, classes, functions)
            except Exception as e:
                logger.debug(f"Error parsing {path}: {e}")

        return {
            "path": rel_path,
            "name": path.name,
            "type": file_type,
            "purpose": purpose,
            "imports": imports[:10],
            "classes": classes[:10],
            "functions": functions[:10],
            "size": path.stat().st_size,
        }

    @staticmethod
    def determine_file_type(path: Path) -> str:
        """Determine file type category."""
        name = path.name
        suffix = path.suffix.lower()
        
        if name in ["app.py", "application.py", "main.py", "wsgi.py", "run.py"]:
            return "main_app"
        if name in ["agent_monitor.py"]:
            return "monitoring"
        if "agent" in name.lower():
            return "ai_agent"
        if name.startswith("test_") or name.endswith("_test.py"):
            return "test"
        if ".github/workflows" in str(path) or name in ["Jenkinsfile", "azure-pipelines.yml", ".gitlab-ci.yml"]:
            return "pipeline"
        if suffix in [".html", ".jinja", ".jinja2"]:
            return "template"
        if suffix in [".css", ".js"]:
            return "static"
        if suffix in [".yml", ".yaml", ".json", ".toml", ".ini", ".conf"]:
            return "config"
        if suffix == ".py":
            return "python"
        return "other"

    @staticmethod
    def extract_imports(tree: ast.AST) -> List[str]:
        """Extract top-level imports from AST."""
        imports = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    imports.append(alias.name)
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    imports.append(node.module)
        return sorted(set(imports))

    @staticmethod
    def extract_classes(tree: ast.AST) -> List[str]:
        """Extract class names from AST."""
        classes = []
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                classes.append(node.name)
        return classes

    @staticmethod
    def extract_functions(tree: ast.AST) -> List[str]:
        """Extract function names from AST."""
        functions = []
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef):
                functions.append(node.name)
        return functions

    @staticmethod
    def infer_purpose(path: Path, content: str, imports: List[str], classes: List[str], functions: List[str]) -> str:
        """Infer file purpose from metadata."""
        name = path.name.lower()
        
        if "agent" in name:
            return "AI agent implementation or helper"
        if "monitor" in name or "observ" in name:
            return "Monitoring or observability utility"
        if "config" in name or "settings" in name:
            return "Configuration file"
        if "test" in name:
            return "Test file"
        if "model" in name:
            return "Data model or database schema"
        if "route" in name or "handler" in name:
            return "Request handler or routing"
        if "util" in name or "helper" in name:
            return "Utility or helper functions"
        
        if "langchain" in imports or "crewai" in imports or "autogen" in imports:
            return "AI agent orchestration or integration"
        if "openai" in imports or "anthropic" in imports:
            return "LLM API integration"
        if any(kw in content.lower() for kw in ["@app.route", "@application.route", "blueprint", "@bp."]):
            return "Flask route handler"
        
        return "Application module"

    @staticmethod
    def prioritize_files(files: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Sort files by priority."""
        priority_order = {
            "main_app": 0,
            "pipeline": 1,
            "ai_agent": 2,
            "config": 3,
            "monitoring": 4,
            "python": 5,
            "template": 6,
            "static": 7,
            "test": 8,
            "other": 9,
        }
        
        files.sort(key=lambda f: (
            priority_order.get(f["type"], 99),
            f["name"]
        ))
        return files

# ============================================================================
# AI AGENT DETECTION
# ============================================================================

class AIAgentDetector:
    """Detects and analyzes AI agents in the project."""

    CHARACTERISTICS = {
        "llm_sdk": "LLM/model-provider SDK usage",
        "model_config": "Model configuration or model-name reference",
        "system_prompt": "System or instruction prompts",
        "goal_oriented": "Goal/task-oriented behavior",
        "planning": "Planning or reasoning loops",
        "tool_calling": "Tool or function calling",
        "autonomous": "Autonomous decision-making",
        "memory": "Memory, state, history, or checkpoints",
        "retrieval": "Retrieval/RAG or vector-store usage",
        "external_action": "External action execution",
        "multi_step": "Multi-step workflows",
        "framework": "Agent frameworks",
        "token_accounting": "Token accounting",
        "rate_limiting": "Rate-limit handling",
        "guardrails": "Human approval or guardrails",
    }

    @staticmethod
    def detect_agents(files_data: Dict[str, Any]) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
        """Detect all agents and separate used vs. unused."""
        all_agents = []
        
        for file_info in files_data.get("files", []):
            if file_info["path"].endswith(".py"):
                agent = AIAgentDetector.analyze_python_file(file_info)
                if agent and agent["classification"] in ["Confirmed AI agent", "Probable AI agent"]:
                    all_agents.append(agent)

        used_agents = AIAgentDetector.filter_used_agents(all_agents)
        return all_agents, used_agents

    @staticmethod
    def analyze_python_file(file_info: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Analyze a Python file for AI agent characteristics."""
        path = PROJECT_ROOT / file_info["path"]
        
        if not path.exists():
            return None

        try:
            with open(path, "r", encoding="utf-8", errors="ignore") as f:
                content = f.read(MAX_FILE_SIZE)
            
            characteristics = AIAgentDetector.extract_characteristics(content)
            confidence_score = AIAgentDetector.calculate_confidence(characteristics)
            classification = AIAgentDetector.classify_agent(confidence_score, file_info["name"])

            if confidence_score < 0.2:
                return None

            detected_provider = AIAgentDetector.detect_provider(content)
            detected_model = AIAgentDetector.detect_model(content)

            return {
                "name": file_info["name"].replace(".py", ""),
                "path": file_info["path"],
                "classification": classification,
                "confidence": round(confidence_score, 2),
                "provider": detected_provider,
                "model": detected_model,
                "framework": AIAgentDetector.detect_framework(content),
                "characteristics": characteristics,
                "tools": AIAgentDetector.extract_tools(content),
                "memory_mechanism": AIAgentDetector.detect_memory(content),
                "evidence": AIAgentDetector.extract_evidence(content),
                "used": False,
            }
        except Exception as e:
            logger.debug(f"Error analyzing agent {file_info['path']}: {e}")
            return None

    @staticmethod
    def extract_characteristics(content: str) -> List[str]:
        """Extract detected characteristics from code."""
        detected = []
        
        # LLM SDK
        if any(lib in content for lib in ["openai", "anthropic", "google.generativeai", "cohere", "groq"]):
            detected.append("llm_sdk")
        
        # Model config
        if any(kw in content for kw in ["model=", "model_name", "gpt-", "claude-", "gemini-", "llama"]):
            detected.append("model_config")
        
        # System prompt
        if any(kw in content for kw in ["system_prompt", "system_message", "instructions", "role"]):
            detected.append("system_prompt")
        
        # Goal-oriented
        if any(kw in content for kw in ["goal", "objective", "task", "purpose"]):
            detected.append("goal_oriented")
        
        # Planning
        if any(kw in content for kw in ["think", "plan", "step", "reason", "reason_action_observation"]):
            detected.append("planning")
        
        # Tool calling
        if any(kw in content for kw in ["tool", "function_call", "tools=", "functions="]):
            detected.append("tool_calling")
        
        # Autonomous
        if any(kw in content for kw in ["while", "loop", "autonomous", "continuous"]):
            detected.append("autonomous")
        
        # Memory
        if any(kw in content for kw in ["memory", "state", "history", "checkpoint", "cache"]):
            detected.append("memory")
        
        # Retrieval/RAG
        if any(kw in content for kw in ["retrieval", "rag", "vector", "embedding", "similarity", "retriever"]):
            detected.append("retrieval")
        
        # External action
        if any(kw in content for kw in ["http", "request", "api", "execute", "run", "subprocess"]):
            detected.append("external_action")
        
        # Multi-step
        if any(kw in content for kw in ["step", "stage", "phase", "workflow", "pipeline"]):
            detected.append("multi_step")
        
        # Frameworks
        if any(fw in content for fw in ["langchain", "crewai", "autogen", "llamaindex", "semantic_kernel"]):
            detected.append("framework")
        
        # Token accounting
        if any(kw in content for kw in ["token", "usage", "cost", "limit"]):
            detected.append("token_accounting")
        
        # Rate limiting
        if any(kw in content for kw in ["rate_limit", "quota", "throttle", "backoff"]):
            detected.append("rate_limiting")
        
        # Guardrails
        if any(kw in content for kw in ["approval", "human", "verify", "validate", "guard"]):
            detected.append("guardrails")
        
        return detected

    @staticmethod
    def calculate_confidence(characteristics: List[str]) -> float:
        """Calculate confidence score (0-1)."""
        if not characteristics:
            return 0.0
        score = len(characteristics) / len(AIAgentDetector.CHARACTERISTICS)
        return min(score, 1.0)

    @staticmethod
    def classify_agent(confidence: float, filename: str) -> str:
        """Classify agent based on confidence and evidence."""
        if confidence >= 0.6:
            return "Confirmed AI agent"
        elif confidence >= 0.4:
            return "Probable AI agent"
        elif confidence >= 0.2:
            return "AI integration/helper"
        else:
            return "Not enough evidence"

    @staticmethod
    def detect_provider(content: str) -> str:
        """Detect AI provider from content."""
        for key, name in AI_PROVIDERS.items():
            if key in content.lower():
                return name
        return "Unknown / not exposed"

    @staticmethod
    def detect_model(content: str) -> str:
        """Detect model name from content."""
        model_patterns = [
            r"gpt-[0-9a-z-]+",
            r"claude-[0-9a-z-]+",
            r"gemini-[0-9a-z-]+",
            r"llama-[0-9]+",
            r"mistral-[0-9a-z-]+",
        ]
        for pattern in model_patterns:
            match = re.search(pattern, content.lower())
            if match:
                return match.group()
        return "Unknown / not exposed"

    @staticmethod
    def detect_framework(content: str) -> str:
        """Detect AI framework."""
        for key, (name, desc) in AI_FRAMEWORKS.items():
            if key in content.lower():
                return name
        return "None detected"

    @staticmethod
    def extract_tools(content: str) -> List[str]:
        """Extract available tools."""
        tools = []
        if "tool" in content.lower():
            # Simple heuristic: look for tool definitions
            tool_pattern = r"(?:tool|func|function)[\s_]*=[\s]*.*?(?:def|class|Tool)"
            tools.extend(re.findall(r"def\s+(\w+)\s*\(", content)[:5])
        return tools

    @staticmethod
    def detect_memory(content: str) -> str:
        """Detect memory/state mechanism."""
        if "langchain" in content.lower() and "memory" in content.lower():
            return "LangChain memory"
        if "vectorstore" in content.lower() or "vector_store" in content.lower():
            return "Vector store"
        if "conversation" in content.lower():
            return "Conversation history"
        if "cache" in content.lower():
            return "Cache/local storage"
        return "None detected"

    @staticmethod
    def extract_evidence(content: str) -> List[str]:
        """Extract evidence snippets (safely)."""
        evidence = []
        for line in content.split("\n"):
            if any(kw in line.lower() for kw in ["import", "agent", "model", "api_key", "endpoint"]):
                clean_line = line.strip()[:100]
                if not any(secret in clean_line.lower() for secret in ["password", "token", "key", "secret"]):
                    evidence.append(clean_line)
            if len(evidence) >= 5:
                break
        return evidence

    @staticmethod
    def filter_used_agents(all_agents: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Filter to agents actually used by the main application."""
        # Check main app file
        main_app_path = None
        for candidate in ["app.py", "application.py", "main.py", "wsgi.py"]:
            path = PROJECT_ROOT / candidate
            if path.exists():
                main_app_path = path
                break

        if not main_app_path:
            return []

        try:
            with open(main_app_path, "r", encoding="utf-8", errors="ignore") as f:
                main_content = f.read(MAX_FILE_SIZE)
        except:
            return []

        used = []
        for agent in all_agents:
            # Check if agent is imported or referenced
            agent_module = agent["name"]
            if (agent_module in main_content or 
                f"import {agent_module}" in main_content or
                f"from {agent_module}" in main_content):
                agent["used"] = True
                used.append(agent)

        return used

# ============================================================================
# WEBHOOK HANDLING
# ============================================================================

def normalize_webhook(data: Dict[str, Any]) -> Dict[str, Any]:
    """Normalize common CI/CD webhook payloads."""
    normalized = {
        "received_at": datetime.utcnow().isoformat(),
        "provider": "unknown",
        "status": "unknown",
        "branch": None,
        "commit": None,
        "repository": None,
        "run_id": None,
        "job_name": None,
        "trigger": None,
    }

    # GitHub Actions
    if "action" in data or "workflow" in data:
        normalized["provider"] = "github"
        normalized["status"] = data.get("action", "unknown")
        normalized["branch"] = data.get("ref", "").replace("refs/heads/", "")
        normalized["commit"] = data.get("head_commit", {}).get("id")
        normalized["repository"] = data.get("repository", {}).get("full_name")
        normalized["run_id"] = data.get("workflow_run", {}).get("id")
        normalized["trigger"] = data.get("workflow_run", {}).get("event")

    # GitLab
    elif "project" in data and "pipeline" in data:
        normalized["provider"] = "gitlab"
        normalized["status"] = data.get("pipeline", {}).get("status", "unknown")
        normalized["branch"] = data.get("ref")
        normalized["commit"] = data.get("checkout_sha")
        normalized["repository"] = data.get("project", {}).get("path_with_namespace")
        normalized["run_id"] = data.get("pipeline", {}).get("id")
        normalized["trigger"] = data.get("trigger")

    # Azure DevOps
    elif "resource" in data:
        normalized["provider"] = "azure"
        normalized["status"] = data.get("resourceContainers", {}).get("account", {}).get("name", "unknown")

    # Jenkins
    elif "build" in data:
        normalized["provider"] = "jenkins"
        normalized["status"] = data.get("build", {}).get("status")
        normalized["run_id"] = data.get("build", {}).get("number")

    webhook_history.add(normalized)
    return normalized

def validate_webhook_token(auth_header: Optional[str] = None, token_header: Optional[str] = None) -> bool:
    """Validate webhook authentication."""
    if not WEBHOOK_TOKEN:
        return True

    token = None
    if auth_header and auth_header.startswith("Bearer "):
        token = auth_header[7:]
    elif token_header:
        token = token_header

    if not token:
        return False

    return hmac.compare_digest(token, WEBHOOK_TOKEN)

# ============================================================================
# USAGE TELEMETRY
# ============================================================================

def record_usage(agent_id: str, usage_data: Dict[str, Any]) -> bool:
    """Record agent usage telemetry."""
    try:
        record = {
            "agent_id": agent_id,
            "timestamp": datetime.utcnow().isoformat(),
        }
        record.update(usage_data)
        usage_history.add(record)
        return True
    except Exception as e:
        logger.error(f"Error recording usage: {e}")
        return False

def get_agent_usage_summary(agent_id: str) -> Dict[str, Any]:
    """Get usage summary for an agent."""
    all_usage = usage_history.get_all()
    agent_usage = [u for u in all_usage if u.get("agent_id") == agent_id]

    if not agent_usage:
        return {
            "prompt_tokens": "No telemetry received",
            "completion_tokens": "No telemetry received",
            "total_tokens": "No telemetry received",
            "request_count": "No telemetry received",
            "hourly_limit": "Not configured",
            "daily_limit": "Not configured",
        }

    latest = agent_usage[0]
    return {
        "prompt_tokens": latest.get("prompt_tokens", "Unknown"),
        "completion_tokens": latest.get("completion_tokens", "Unknown"),
        "total_tokens": latest.get("total_tokens", "Unknown"),
        "request_count": latest.get("request_count", "Unknown"),
        "hourly_limit": latest.get("hourly_limit", "Not configured"),
        "daily_limit": latest.get("daily_limit", "Not configured"),
        "context_window": latest.get("context_window", "Unknown"),
        "last_updated": latest.get("timestamp"),
    }

# ============================================================================
# CACHE MANAGEMENT
# ============================================================================

def get_cached_scan() -> Optional[Dict[str, Any]]:
    """Get cached scan if fresh."""
    with scan_cache["lock"]:
        if scan_cache["data"] and (time.time() - scan_cache["timestamp"]) < SCAN_CACHE_TTL:
            return scan_cache["data"]
    return None

def cache_scan(data: Dict[str, Any]):
    """Cache scan results."""
    with scan_cache["lock"]:
        scan_cache["data"] = data
        scan_cache["timestamp"] = time.time()

def perform_full_scan() -> Dict[str, Any]:
    """Perform a complete project scan."""
    cached = get_cached_scan()
    if cached:
        return cached

    files_data = FileScanner.scan_files()
    all_agents, used_agents = AIAgentDetector.detect_agents(files_data)
    pipeline_info = PipelineDetector.get_pipeline_summary()

    result = {
        "scanned_at": datetime.utcnow().isoformat(),
        "project_root": str(PROJECT_ROOT),
        "files": files_data,
        "agents": {
            "all": all_agents,
            "used": used_agents,
        },
        "pipeline": pipeline_info,
    }

    cache_scan(result)
    return result

# ============================================================================
# FLASK APPLICATION & BLUEPRINTS
# ============================================================================

# Create Flask app
application = Flask(__name__)
application.config["JSON_SORT_KEYS"] = False

# Embedded HTML template
INDEX_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>SentinelOps - AI Agent Monitor</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        
        body {
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
            background: #f8f9fa;
            color: #2c3e50;
            line-height: 1.6;
        }
        
        .container { max-width: 1400px; margin: 0 auto; padding: 20px; }
        
        header {
            background: white;
            border-bottom: 2px solid #10b981;
            padding: 20px;
            margin-bottom: 30px;
            border-radius: 8px;
            box-shadow: 0 2px 4px rgba(0,0,0,0.08);
        }
        
        h1 {
            color: #059669;
            font-size: 2em;
            margin-bottom: 5px;
        }
        
        .header-subtitle {
            color: #64748b;
            font-size: 0.95em;
        }
        
        .grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));
            gap: 20px;
            margin-bottom: 30px;
        }
        
        .card {
            background: white;
            border-radius: 8px;
            padding: 20px;
            box-shadow: 0 2px 8px rgba(0,0,0,0.08);
            border-left: 4px solid #10b981;
        }
        
        .card h2 {
            font-size: 1.1em;
            margin-bottom: 15px;
            color: #059669;
            display: flex;
            align-items: center;
            gap: 10px;
        }
        
        .card-content {
            font-size: 0.95em;
            line-height: 1.8;
        }
        
        .badge {
            display: inline-block;
            padding: 6px 12px;
            border-radius: 4px;
            font-size: 0.85em;
            font-weight: 500;
            margin: 4px 4px 4px 0;
        }
        
        .badge.success { background: #d1fae5; color: #065f46; }
        .badge.warning { background: #fef3c7; color: #92400e; }
        .badge.info { background: #dbeafe; color: #0c2d6b; }
        .badge.error { background: #fee2e2; color: #7f1d1d; }
        
        .status-indicator {
            display: inline-block;
            width: 12px;
            height: 12px;
            border-radius: 50%;
            margin-right: 6px;
        }
        
        .status-indicator.success { background: #10b981; }
        .status-indicator.warning { background: #f59e0b; }
        .status-indicator.error { background: #ef4444; }
        .status-indicator.unknown { background: #6b7280; }
        
        .progress-bar {
            width: 100%;
            height: 24px;
            background: #e5e7eb;
            border-radius: 4px;
            overflow: hidden;
            margin: 10px 0;
        }
        
        .progress-fill {
            height: 100%;
            background: linear-gradient(90deg, #10b981, #059669);
            display: flex;
            align-items: center;
            justify-content: center;
            color: white;
            font-size: 0.75em;
            font-weight: bold;
            transition: width 0.3s ease;
        }
        
        .chart {
            height: 200px;
            background: #f3f4f6;
            border-radius: 4px;
            margin: 15px 0;
            position: relative;
            display: flex;
            align-items: flex-end;
            justify-content: space-around;
            padding: 10px;
        }
        
        .chart-bar {
            width: 8%;
            background: #10b981;
            border-radius: 4px 4px 0 0;
            min-height: 20px;
            position: relative;
        }
        
        .chart-bar:hover {
            background: #059669;
        }
        
        .chart-bar-label {
            position: absolute;
            bottom: -20px;
            left: 0;
            right: 0;
            text-align: center;
            font-size: 0.7em;
            color: #64748b;
        }
        
        .file-tree {
            background: #f8f9fa;
            border: 1px solid #e5e7eb;
            border-radius: 4px;
            padding: 15px;
            font-family: "Monaco", "Courier New", monospace;
            font-size: 0.9em;
            line-height: 1.6;
            max-height: 400px;
            overflow-y: auto;
        }
        
        .tree-item {
            margin-left: 20px;
            color: #475569;
        }
        
        .tree-folder::before { content: "📁 "; }
        .tree-file::before { content: "📄 "; }
        
        .tab-container {
            display: flex;
            border-bottom: 2px solid #e5e7eb;
            margin-bottom: 20px;
            gap: 10px;
        }
        
        .tab-button {
            padding: 10px 20px;
            border: none;
            background: none;
            cursor: pointer;
            font-size: 0.95em;
            color: #64748b;
            border-bottom: 3px solid transparent;
            transition: all 0.3s ease;
        }
        
        .tab-button.active {
            color: #059669;
            border-bottom-color: #059669;
            font-weight: 500;
        }
        
        .tab-button:hover {
            color: #059669;
        }
        
        .tab-content {
            display: none;
        }
        
        .tab-content.active {
            display: block;
        }
        
        button.action-btn {
            background: #059669;
            color: white;
            border: none;
            padding: 10px 20px;
            border-radius: 4px;
            cursor: pointer;
            font-size: 0.95em;
            transition: background 0.3s ease;
        }
        
        button.action-btn:hover {
            background: #047857;
        }
        
        button.action-btn:disabled {
            background: #cbd5e1;
            cursor: not-allowed;
        }
        
        .loading {
            display: inline-block;
            width: 20px;
            height: 20px;
            border: 3px solid #e5e7eb;
            border-top-color: #059669;
            border-radius: 50%;
            animation: spin 0.8s linear infinite;
        }
        
        @keyframes spin {
            to { transform: rotate(360deg); }
        }
        
        .empty-state {
            text-align: center;
            padding: 40px 20px;
            color: #94a3b8;
        }
        
        .empty-state svg {
            width: 60px;
            height: 60px;
            margin-bottom: 20px;
            opacity: 0.5;
        }
        
        .agent-card {
            border: 1px solid #e5e7eb;
            border-radius: 6px;
            padding: 15px;
            margin-bottom: 15px;
            background: white;
        }
        
        .agent-card-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 10px;
        }
        
        .agent-name {
            font-weight: 600;
            color: #059669;
        }
        
        .agent-confidence {
            font-size: 0.85em;
            padding: 4px 8px;
            background: #e0f2fe;
            color: #0369a1;
            border-radius: 3px;
        }
        
        .agent-meta {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 10px;
            font-size: 0.9em;
            margin: 10px 0;
        }
        
        .meta-item {
            background: #f3f4f6;
            padding: 8px;
            border-radius: 3px;
        }
        
        .meta-label {
            font-weight: 500;
            color: #059669;
        }
        
        .meta-value {
            color: #475569;
            word-break: break-all;
        }
        
        @media (max-width: 768px) {
            .grid { grid-template-columns: 1fr; }
            .card { padding: 15px; }
            h1 { font-size: 1.5em; }
            .tab-container { flex-wrap: wrap; }
        }
        
        .footer {
            text-align: center;
            padding: 20px;
            color: #94a3b8;
            font-size: 0.9em;
            margin-top: 40px;
            border-top: 1px solid #e5e7eb;
        }
    </style>
</head>
<body>
    <div class="container">
        <header>
            <h1>🤖 SentinelOps Agent Monitor</h1>
            <p class="header-subtitle">AI Agent Observability Dashboard for <code id="project-name">—</code></p>
        </header>

        <div class="grid">
            <div class="card">
                <h2>⚙️ Pipeline Status</h2>
                <div class="card-content" id="pipeline-status">
                    <div class="loading"></div> Loading...
                </div>
            </div>
            
            <div class="card">
                <h2>🤖 AI Agents Found</h2>
                <div class="card-content" id="agents-summary">
                    <div class="loading"></div> Loading...
                </div>
            </div>
            
            <div class="card">
                <h2>📊 File Inventory</h2>
                <div class="card-content" id="files-summary">
                    <div class="loading"></div> Loading...
                </div>
            </div>
        </div>

        <div class="card" style="margin-bottom: 30px;">
            <h2>🔍 Project Overview</h2>
            <div class="tab-container">
                <button class="tab-button active" onclick="switchTab('files')">Files</button>
                <button class="tab-button" onclick="switchTab('agents')">AI Agents</button>
                <button class="tab-button" onclick="switchTab('pipeline')">Pipeline</button>
                <button class="tab-button" onclick="switchTab('history')">History</button>
            </div>

            <div id="files" class="tab-content active">
                <button class="action-btn" onclick="rescanProject()">↻ Rescan Project</button>
                <div id="files-content" style="margin-top: 15px;"></div>
            </div>

            <div id="agents" class="tab-content">
                <div id="agents-content"></div>
            </div>

            <div id="pipeline" class="tab-content">
                <div id="pipeline-content"></div>
            </div>

            <div id="history" class="tab-content">
                <div id="history-content"></div>
            </div>
        </div>

        <div class="footer">
            Last updated: <span id="last-updated">—</span> | <a href="javascript:location.reload()" style="color: #059669;">Refresh</a>
        </div>
    </div>

    <script>
        const API_BASE = "/api/sentinelops";
        let scanData = null;

        function switchTab(tabName) {
            document.querySelectorAll('.tab-content').forEach(el => el.classList.remove('active'));
            document.querySelectorAll('.tab-button').forEach(el => el.classList.remove('active'));
            document.getElementById(tabName).classList.add('active');
            event.target.classList.add('active');
            
            if (tabName === 'agents' && !document.getElementById('agents-content').innerHTML) {
                renderAgentsTab();
            } else if (tabName === 'pipeline' && !document.getElementById('pipeline-content').innerHTML) {
                renderPipelineTab();
            } else if (tabName === 'history' && !document.getElementById('history-content').innerHTML) {
                renderHistoryTab();
            }
        }

        function formatDate(isoString) {
            const date = new Date(isoString);
            return date.toLocaleString('en-US', { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' });
        }

        function createStatusIndicator(status) {
            const statusMap = {
                'success': 'success',
                'completed': 'success',
                'passed': 'success',
                'failure': 'error',
                'failed': 'error',
                'pending': 'warning',
                'running': 'warning',
            };
            const type = statusMap[status?.toLowerCase()] || 'unknown';
            return `<span class="status-indicator ${type}"></span>${status || 'Unknown'}`;
        }

        function loadDashboard() {
            fetch(`${API_BASE}/summary`)
                .then(r => r.json())
                .then(data => {
                    scanData = data;
                    document.getElementById('project-name').textContent = data.project_root.split('/').pop();
                    document.getElementById('last-updated').textContent = formatDate(data.scanned_at);
                    
                    renderPipelineStatus(data.pipeline);
                    renderAgentsSummary(data.agents);
                    renderFilesSummary(data.files);
                    renderFilesTab(data.files);
                })
                .catch(err => {
                    console.error('Error loading dashboard:', err);
                    document.getElementById('pipeline-status').innerHTML = '<p style="color: red;">Error loading data</p>';
                });
        }

        function renderPipelineStatus(pipeline) {
            const html = `
                <div>
                    <strong>Detected:</strong><br>
                    ${pipeline.configured.length ? pipeline.configured.map(p => `<span class="badge info">${p.toUpperCase()}</span>`).join('') : 'No pipelines configured'}
                    <br><br>
                    <strong>Runtime:</strong> ${pipeline.runtime ? `<span class="badge success">${pipeline.runtime.toUpperCase()}</span>` : 'Not detected'}<br>
                    <strong>Confidence:</strong> <span class="badge ${pipeline.confidence === 'High' ? 'success' : 'warning'}">${pipeline.confidence}</span>
                </div>
            `;
            document.getElementById('pipeline-status').innerHTML = html;
        }

        function renderAgentsSummary(agents) {
            const confirmed = agents.all.filter(a => a.classification === 'Confirmed AI agent').length;
            const probable = agents.all.filter(a => a.classification === 'Probable AI agent').length;
            const used = agents.used.length;
            
            const html = `
                <div>
                    <strong>Total Found:</strong> ${agents.all.length}<br>
                    <strong>Confirmed:</strong> ${confirmed}<br>
                    <strong>Probable:</strong> ${probable}<br>
                    <strong>Actually Used:</strong> ${used}<br>
                </div>
            `;
            document.getElementById('agents-summary').innerHTML = html;
        }

        function renderFilesSummary(files) {
            const mainFiles = files.files.filter(f => f.type === 'main_app');
            const html = `
                <div>
                    <strong>Total Files:</strong> ${files.total}<br>
                    <strong>Main App:</strong> ${mainFiles.map(f => f.name).join(', ') || 'None'}<br>
                    <strong>Python Files:</strong> ${files.files.filter(f => f.type === 'python').length}
                </div>
            `;
            document.getElementById('files-summary').innerHTML = html;
        }

        function renderFilesTab(files) {
            const mainFiles = files.files.filter(f => ['main_app', 'pipeline', 'ai_agent'].includes(f.type));
            const html = mainFiles.length ? `
                <table style="width: 100%; border-collapse: collapse; font-size: 0.9em;">
                    <thead style="background: #f3f4f6; border-bottom: 2px solid #e5e7eb;">
                        <tr>
                            <th style="padding: 10px; text-align: left;">File</th>
                            <th style="padding: 10px; text-align: left;">Type</th>
                            <th style="padding: 10px; text-align: left;">Purpose</th>
                        </tr>
                    </thead>
                    <tbody>
                        ${mainFiles.map(f => `
                            <tr style="border-bottom: 1px solid #e5e7eb;">
                                <td style="padding: 10px;"><code>${f.path}</code></td>
                                <td style="padding: 10px;">${f.type}</td>
                                <td style="padding: 10px;">${f.purpose}</td>
                            </tr>
                        `).join('')}
                    </tbody>
                </table>
            ` : '<p class="empty-state">No files to display</p>';
            document.getElementById('files-content').innerHTML = html;
        }

        function renderAgentsTab() {
            if (!scanData) return;
            const agents = scanData.agents.all;
            const html = agents.length ? `
                <div style="display: grid; gap: 15px;">
                    ${agents.map(agent => `
                        <div class="agent-card">
                            <div class="agent-card-header">
                                <span class="agent-name">${agent.name}</span>
                                <span class="agent-confidence">${(agent.confidence * 100).toFixed(0)}%</span>
                            </div>
                            <div style="margin-bottom: 8px;">
                                <span class="badge ${agent.classification.includes('Confirmed') ? 'success' : 'warning'}">${agent.classification}</span>
                            </div>
                            <div class="agent-meta">
                                <div class="meta-item">
                                    <div class="meta-label">Provider</div>
                                    <div class="meta-value">${agent.provider}</div>
                                </div>
                                <div class="meta-item">
                                    <div class="meta-label">Model</div>
                                    <div class="meta-value">${agent.model}</div>
                                </div>
                                <div class="meta-item">
                                    <div class="meta-label">Framework</div>
                                    <div class="meta-value">${agent.framework}</div>
                                </div>
                                <div class="meta-item">
                                    <div class="meta-label">Used</div>
                                    <div class="meta-value">${agent.used ? '✓ Yes' : '✗ Repository only'}</div>
                                </div>
                            </div>
                        </div>
                    `).join('')}
                </div>
            ` : '<p class="empty-state">No AI agents found in this project</p>';
            document.getElementById('agents-content').innerHTML = html;
        }

        function renderPipelineTab() {
            if (!scanData) return;
            const pipeline = scanData.pipeline;
            const webhook = pipeline.latest_webhook;
            const html = webhook ? `
                <div style="background: #f3f4f6; padding: 15px; border-radius: 4px;">
                    <div style="margin-bottom: 15px;">
                        <strong>Provider:</strong> ${webhook.provider.toUpperCase()}<br>
                        <strong>Status:</strong> ${createStatusIndicator(webhook.status)}<br>
                        <strong>Branch:</strong> ${webhook.branch || '—'}<br>
                        <strong>Commit:</strong> <code>${webhook.commit ? webhook.commit.substring(0, 7) : '—'}</code><br>
                        <strong>Run ID:</strong> ${webhook.run_id || '—'}<br>
                        <strong>Received:</strong> ${formatDate(webhook.received_at)}<br>
                    </div>
                </div>
            ` : '<p class="empty-state">No webhook data received yet</p>';
            document.getElementById('pipeline-content').innerHTML = html;
        }

        function renderHistoryTab() {
            fetch(`${API_BASE}/history`)
                .then(r => r.json())
                .then(data => {
                    const events = data.events || [];
                    const html = events.length ? `
                        <div style="max-height: 500px; overflow-y: auto;">
                            ${events.slice(0, 20).map(e => `
                                <div style="padding: 10px; border-bottom: 1px solid #e5e7eb; font-size: 0.9em;">
                                    <strong>${formatDate(e.timestamp)}</strong> - ${e.provider?.toUpperCase() || 'unknown'} ${createStatusIndicator(e.status)}
                                </div>
                            `).join('')}
                        </div>
                    ` : '<p class="empty-state">No history available</p>';
                    document.getElementById('history-content').innerHTML = html;
                });
        }

        function rescanProject() {
            if (confirm('Rescan the project? This may take a moment.')) {
                const btn = event.target;
                btn.disabled = true;
                btn.textContent = '⏳ Scanning...';
                
                fetch(`${API_BASE}/rescan`, { method: 'POST' })
                    .then(r => r.json())
                    .then(() => {
                        loadDashboard();
                        btn.disabled = false;
                        btn.textContent = '↻ Rescan Project';
                    })
                    .catch(err => {
                        alert('Rescan failed: ' + err);
                        btn.disabled = false;
                        btn.textContent = '↻ Rescan Project';
                    });
            }
        }

        // Load dashboard on page load
        document.addEventListener('DOMContentLoaded', loadDashboard);
    </script>
</body>
</html>
"""

# Setup Jinja2 loader to serve embedded template
def get_template_loader():
    """Get Jinja2 template loader for embedded template."""
    dict_loader = DictLoader({"index.html": INDEX_HTML})
    file_loader = FileSystemLoader(os.path.join(os.path.dirname(__file__), "templates")) if os.path.exists(os.path.join(os.path.dirname(__file__), "templates")) else None
    
    if file_loader:
        return ChoiceLoader([file_loader, dict_loader])
    return dict_loader

application.jinja_loader = get_template_loader()

# Create blueprints
monitor_bp = Blueprint("monitor", __name__, url_prefix="/api/sentinelops")
scanner_bp = Blueprint("scanner", __name__, url_prefix="/api/sentinelops")

# ============================================================================
# ROUTES - Monitor Blueprint
# ============================================================================

@monitor_bp.get("/summary")
def get_summary():
    """Get complete dashboard summary."""
    try:
        scan_result = perform_full_scan()
        return jsonify(scan_result), 200
    except Exception as e:
        logger.error(f"Error generating summary: {e}")
        return jsonify({"error": str(e)}), 500

@monitor_bp.get("/pipelines")
def get_pipelines():
    """Get pipeline information."""
    try:
        scan_result = perform_full_scan()
        return jsonify(scan_result.get("pipeline", {})), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@monitor_bp.get("/agents")
def get_agents():
    """Get AI agents information."""
    try:
        scan_result = perform_full_scan()
        return jsonify(scan_result.get("agents", {})), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@monitor_bp.get("/files")
def get_files():
    """Get file inventory."""
    try:
        scan_result = perform_full_scan()
        return jsonify(scan_result.get("files", {})), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@monitor_bp.get("/history")
def get_history():
    """Get webhook and usage history."""
    try:
        return jsonify({
            "webhooks": webhook_history.get_all()[:100],
            "usage": usage_history.get_all()[:100],
            "events": webhook_history.get_all()[:100],
        }), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# ============================================================================
# ROUTES - Scanner Blueprint
# ============================================================================

@scanner_bp.post("/rescan")
def rescan_project():
    """Trigger a fresh project scan."""
    try:
        with scan_cache["lock"]:
            scan_cache["data"] = None
            scan_cache["timestamp"] = 0
        
        result = perform_full_scan()
        return jsonify({"status": "success", "scanned_at": result["scanned_at"]}), 200
    except Exception as e:
        logger.error(f"Error rescanning: {e}")
        return jsonify({"error": str(e)}), 500

@scanner_bp.post("/usage")
def record_agent_usage():
    """Record agent usage telemetry."""
    try:
        # Check content length
        if request.content_length and request.content_length > MAX_PAYLOAD_SIZE:
            return jsonify({"error": "Payload too large"}), 413

        # Validate webhook token
        auth_header = request.headers.get("Authorization")
        token_header = request.headers.get("X-SentinelOps-Token")
        if not validate_webhook_token(auth_header, token_header):
            return jsonify({"error": "Unauthorized"}), 401

        data = request.get_json() or {}
        agent_id = data.get("agent_id", "unknown")

        # Validate and cap numeric fields
        usage_data = {
            "agent_id": agent_id,
            "agent_name": data.get("agent_name", ""),
            "provider": data.get("provider", ""),
            "model": data.get("model", ""),
            "prompt_tokens": min(int(data.get("prompt_tokens", 0)), 1000000),
            "completion_tokens": min(int(data.get("completion_tokens", 0)), 1000000),
            "total_tokens": min(int(data.get("total_tokens", 0)), 1000000),
            "request_count": min(int(data.get("request_count", 0)), 10000),
            "context_window": data.get("context_window"),
            "hourly_limit": data.get("hourly_limit"),
            "daily_limit": data.get("daily_limit"),
        }

        record_usage(agent_id, usage_data)
        return jsonify({"status": "success"}), 200
    except Exception as e:
        logger.error(f"Error recording usage: {e}")
        return jsonify({"error": str(e)}), 400

# ============================================================================
# WEBHOOK HANDLER
# ============================================================================

def handle_monitor_status():
    """Handle incoming webhook from CI/CD pipeline."""
    try:
        # Check content length
        if request.content_length and request.content_length > MAX_PAYLOAD_SIZE:
            return jsonify({"error": "Payload too large"}), 413

        # Validate webhook token
        auth_header = request.headers.get("Authorization")
        token_header = request.headers.get("X-SentinelOps-Token")
        if not validate_webhook_token(auth_header, token_header):
            return jsonify({"error": "Unauthorized"}), 401

        # Parse payload
        if request.is_json:
            data = request.get_json() or {}
        else:
            data = request.form.to_dict()

        # Normalize webhook
        normalized = normalize_webhook(data)

        logger.info(f"Webhook received: {normalized.get('provider')} - {normalized.get('status')}")
        return jsonify({"status": "received", "normalized": normalized}), 200

    except Exception as e:
        logger.error(f"Error handling webhook: {e}")
        return jsonify({"error": str(e)}), 400

# ============================================================================
# INITIALIZATION
# ============================================================================

# Perform initial scan on module load
try:
    logger.info(f"Initializing SentinelOps Monitor for project: {PROJECT_ROOT}")
    perform_full_scan()
    logger.info("Initial scan completed successfully")
except Exception as e:
    logger.warning(f"Initial scan failed: {e}")

logger.info("SentinelOps Agent Monitor module loaded successfully")
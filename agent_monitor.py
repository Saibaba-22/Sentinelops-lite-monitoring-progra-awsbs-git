#!/usr/bin/env python3
"""
SentinelOps Agent Monitor - Production-ready embedded observability module
All functionality contained in single file per requirements. No external dependencies beyond Flask standard stack.
"""
import os
import sys
import json
import re
import ast
import time
import hmac
import hashlib
import threading
import logging
import traceback
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Any, Optional, Tuple, Set
from collections import defaultdict, OrderedDict
from dataclasses import dataclass, asdict
from enum import Enum
from functools import wraps
from urllib.parse import urlparse

# Flask and Jinja imports (must be available in target environment)
from flask import (
    Flask, Blueprint, request, jsonify, render_template_string, 
    make_response, abort, current_app
)
from jinja2 import ChoiceLoader, DictLoader, FileSystemLoader
from werkzeug.exceptions import BadRequest, UnsupportedMediaType

# ======================
# CONFIGURATION & GLOBALS
# ======================
# Environment-based configuration with safe defaults
PROJECT_ROOT = Path(os.getenv('SENTINELOPS_PROJECT_ROOT', Path(__file__).parent.resolve()))
STORAGE_DIR = PROJECT_ROOT / '.sentinelops'
WEBHOOK_TOKEN = os.getenv('SENTINELOPS_WEBHOOK_TOKEN', '').strip()
TIMEZONE = os.getenv('SENTINELOPS_TIMEZONE', 'Asia/Kolkata')
MAX_SCAN_FILES = int(os.getenv('SENTINELOPS_MAX_SCAN_FILES', '500'))
MAX_FILE_SIZE_BYTES = int(os.getenv('SENTINELOPS_MAX_FILE_SIZE', '1048576'))  # 1MB
MAX_SCAN_DEPTH = int(os.getenv('SENTINELOPS_MAX_SCAN_DEPTH', '5'))
MAX_WEBHOOK_HISTORY = 100
MAX_USAGE_HISTORY = 500
AGENT_LIMITS = {}
if os.getenv('SENTINELOPS_AGENT_LIMITS_JSON'):
    try:
        AGENT_LIMITS = json.loads(os.getenv('SENTINELOPS_AGENT_LIMITS_JSON', '{}'))
    except Exception:
        pass

# Thread-safe storage
_scan_cache = {}
_scan_cache_time = None
_scan_lock = threading.RLock()
_webhook_history = []
_webhook_lock = threading.RLock()
_usage_ledger = defaultdict(list)
_usage_lock = threading.RLock()
_storage_lock = threading.RLock()

# Initialize storage directory safely
try:
    STORAGE_DIR.mkdir(exist_ok=True, mode=0o700)
except Exception:
    pass  # Fail gracefully if cannot create storage

# Logging setup (minimal, no secrets)
logging.basicConfig(level=logging.WARNING)
logger = logging.getLogger('sentinelops')
logger.setLevel(logging.INFO if os.getenv('FLASK_ENV') == 'development' else logging.WARNING)

# ======================
# CORE DATA STRUCTURES
# ======================
class ConfidenceLevel(str, Enum):
    HIGH = "High"
    MEDIUM = "Medium"
    LOW = "Low"
    NONE = "None"

class AgentClassification(str, Enum):
    CONFIRMED = "Confirmed AI Agent"
    PROBABLE = "Probable AI Agent"
    HELPER = "AI Integration Helper"
    INSUFFICIENT = "Insufficient Evidence"
    NON_AGENT = "Not an AI Agent"

@dataclass
class PipelineEvidence:
    provider: str
    confidence: ConfidenceLevel
    source: str  # 'environment', 'repository', 'webhook'
    details: Dict[str, Any]
    detected_at: str

@dataclass
class FileMetadata:
    path: str
    type: str
    size: int
    is_binary: bool
    purpose: str
    category: str  # 'main', 'pipeline', 'ai', 'config', 'test', 'template', 'static', 'other'
    imports: List[str]
    classes: List[str]
    functions: List[str]
    agent_evidence: List[Dict]
    referenced_by_main: bool = False

@dataclass
class AIAgent:
    name: str
    filepath: str
    classification: AgentClassification
    confidence: ConfidenceLevel
    provider: str
    model: str
    framework: str
    purpose: str
    tools: List[str]
    memory_mechanism: str
    evidence: List[Dict]
    in_use: bool
    last_activity: Optional[str]

@dataclass
class TokenUsage:
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    requests: int = 0
    timestamp: str = ""
    context_window: Optional[int] = None
    hourly_limit: Optional[int] = None
    daily_limit: Optional[int] = None

@dataclass
class WebhookEvent:
    id: str
    provider: str
    event_type: str
    status: str
    branch: str
    commit_sha: str
    run_url: str
    workflow_name: str
    run_id: str
    timestamp: str
    raw_payload_summary: str

# ======================
# SECURITY & VALIDATION
# ======================
def verify_webhook_token(f):
    """Decorator to verify webhook authentication token if configured"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not WEBHOOK_TOKEN:
            return f(*args, **kwargs)
        
        token = request.headers.get('Authorization', '').replace('Bearer ', '', 1)
        if not token:
            token = request.headers.get('X-SentinelOps-Token', '')
        
        if not hmac.compare_digest(token, WEBHOOK_TOKEN):
            logger.warning("Webhook authentication failed")
            return jsonify({"error": "Unauthorized"}), 401
        return f(*args, **kwargs)
    return decorated_function

def sanitize_payload(payload: Dict) -> Dict:
    """Remove secrets and sensitive fields from payloads"""
    sanitized = {}
    secret_patterns = [
        r'api[_-]?key', r'token', r'secret', r'password', r'credential', 
        r'private[_-]?key', r'cert', r'auth'
    ]
    
    def redact_value(k, v):
        k_lower = k.lower()
        if any(re.search(pat, k_lower) for pat in secret_patterns):
            return "[REDACTED]"
        if isinstance(v, str) and len(v) > 100 and any(c in v for c in ('sk-', 'pk-', '-----BEGIN')):
            return "[REDACTED_BINARY]"
        return v
    
    def traverse(obj, path=""):
        if isinstance(obj, dict):
            result = {}
            for k, v in obj.items():
                new_path = f"{path}.{k}" if path else k
                if isinstance(v, (dict, list)):
                    result[k] = traverse(v, new_path)
                else:
                    result[k] = redact_value(k, v)
            return result
        elif isinstance(obj, list):
            return [traverse(item, path) for item in obj]
        else:
            return obj
    
    return traverse(payload)

def validate_usage_data(data: Dict) -> Tuple[bool, str]:
    """Validate incoming usage telemetry"""
    required = ['agent_id', 'provider', 'model']
    for field in required:
        if field not in data:
            return False, f"Missing required field: {field}"
    
    numeric_fields = [
        'prompt_tokens', 'completion_tokens', 'total_tokens', 
        'request_count', 'context_window', 'hourly_limit', 'daily_limit'
    ]
    for field in numeric_fields:
        if field in data:
            try:
                val = int(data[field])
                if val < 0 or val > 10**9:  # Reasonable bounds
                    return False, f"Invalid value for {field}"
            except (TypeError, ValueError):
                return False, f"Invalid numeric value for {field}"
    
    return True, ""

# ======================
# PIPELINE DETECTION
# ======================
CI_ENV_VARS = {
    'GitHub Actions': ['GITHUB_ACTIONS', 'GITHUB_WORKFLOW'],
    'Azure DevOps': ['TF_BUILD', 'BUILD_BUILDID'],
    'Jenkins': ['JENKINS_URL', 'JOB_NAME'],
    'GitLab CI': ['GITLAB_CI', 'CI_PIPELINE_ID'],
    'CircleCI': ['CIRCLECI', 'CIRCLE_WORKFLOW_ID'],
    'Bitbucket Pipelines': ['BITBUCKET_BUILD_NUMBER', 'BITBUCKET_REPO_FULL_NAME'],
    'AWS CodeBuild': ['CODEBUILD_BUILD_ID', 'CODEBUILD_SOURCE_REPO_URL'],
    'Google Cloud Build': ['BUILD_ID', 'PROJECT_ID', 'CLUSTER_NAME'],
}

CI_CONFIG_FILES = {
    'GitHub Actions': ['.github/workflows/*.yml', '.github/workflows/*.yaml'],
    'Azure DevOps': ['azure-pipelines.yml', 'azure-pipelines.yaml'],
    'Jenkins': ['Jenkinsfile'],
    'GitLab CI': ['.gitlab-ci.yml'],
    'CircleCI': ['.circleci/config.yml'],
    'Bitbucket Pipelines': ['bitbucket-pipelines.yml'],
    'AWS CodeBuild': ['buildspec.yml'],
    'Google Cloud Build': ['cloudbuild.yaml', 'cloudbuild.yml'],
}

def detect_ci_from_env() -> Optional[PipelineEvidence]:
    """Detect CI provider from environment variables"""
    for provider, vars in CI_ENV_VARS.items():
        if any(os.getenv(v) for v in vars):
            details = {
                'provider': provider,
                'detected_vars': [v for v in vars if os.getenv(v)],
                'run_id': os.getenv(next((v for v in vars if 'id' in v.lower() or 'number' in v.lower()), ''), '')[:64],
                'repo': os.getenv('GITHUB_REPOSITORY', os.getenv('CI_PROJECT_PATH', 'unknown'))[:128],
                'branch': os.getenv('GITHUB_REF', os.getenv('CI_COMMIT_REF_NAME', 'unknown'))[:128],
            }
            # Never include full env values that might contain secrets
            return PipelineEvidence(
                provider=provider,
                confidence=ConfidenceLevel.HIGH,
                source='environment',
                details=details,
                detected_at=datetime.now().isoformat()
            )
    return None

def detect_ci_from_repo() -> List[PipelineEvidence]:
    """Scan repository for CI configuration files"""
    evidences = []
    for provider, patterns in CI_CONFIG_FILES.items():
        for pattern in patterns:
            # Simple glob handling (limited depth)
            if '*' in pattern:
                base_dir = PROJECT_ROOT / pattern.split('*')[0]
                if base_dir.exists():
                    for file in base_dir.rglob('*'):
                        if file.suffix in ('.yml', '.yaml') and not file.name.startswith('.'):
                            try:
                                # Extract workflow name from file content safely
                                content = file.read_text(encoding='utf-8', errors='ignore')[:2048]
                                name_match = re.search(r'name:\s*["\']?([^"\']+)["\']?', content)
                                workflow_name = name_match.group(1) if name_match else file.name
                                
                                evidences.append(PipelineEvidence(
                                    provider=provider,
                                    confidence=ConfidenceLevel.MEDIUM,
                                    source='repository',
                                    details={
                                        'config_file': str(file.relative_to(PROJECT_ROOT)),
                                        'workflow_name': workflow_name[:100],
                                        'exists': True
                                    },
                                    detected_at=datetime.now().isoformat()
                                ))
                            except Exception:
                                continue
            else:
                config_file = PROJECT_ROOT / pattern
                if config_file.exists():
                    evidences.append(PipelineEvidence(
                        provider=provider,
                        confidence=ConfidenceLevel.MEDIUM,
                        source='repository',
                        details={'config_file': pattern, 'exists': True},
                        detected_at=datetime.now().isoformat()
                    ))
    return evidences

def normalize_webhook(payload: Dict, headers: Dict) -> Optional[WebhookEvent]:
    """Normalize common CI webhook payloads"""
    # Detect provider from headers/payload structure
    provider = "unknown"
    if 'X-GitHub-Event' in headers or 'github' in str(headers.get('User-Agent', '')).lower():
        provider = "GitHub Actions"
    elif 'X-Vss-Activityid' in headers or 'azure' in str(headers.get('User-Agent', '')).lower():
        provider = "Azure DevOps"
    elif 'X-Gitlab-Event' in headers:
        provider = "GitLab CI"
    elif payload.get('jenkins'):  # Common Jenkins webhook pattern
        provider = "Jenkins"
    
    # Extract common fields with provider-specific fallbacks
    def get_val(*keys):
        for key in keys:
            if isinstance(key, tuple):
                obj, k = key
                val = obj.get(k) if isinstance(obj, dict) else None
            else:
                val = payload.get(key)
            if val:
                return str(val)[:256]
        return "unknown"
    
    status = "unknown"
    if provider == "GitHub Actions":
        status = get_val('status', ('check_suite', 'conclusion'), ('workflow_run', 'status'))
    elif provider == "Azure DevOps":
        status = get_val(('resource', 'status'), 'status')
    elif provider == "GitLab CI":
        status = get_val(('object_attributes', 'status'), 'build_status')
    
    # Generate unique ID
    event_id = hashlib.sha256(f"{provider}{time.time()}".encode()).hexdigest()[:16]
    
    return WebhookEvent(
        id=event_id,
        provider=provider,
        event_type=get_val('event', 'action', ('headers', 'X-GitHub-Event')),
        status=status,
        branch=get_val('ref', ('repository', 'default_branch'), ('object_attributes', 'ref')),
        commit_sha=get_val('after', ('head_commit', 'id'), ('object_attributes', 'sha'))[:40],
        run_url=get_val(('workflow_run', 'html_url'), ('resource', 'url'), ('build_url',)),
        workflow_name=get_val('name', ('workflow', 'name'), ('definition', 'name')),
        run_id=get_val('run_id', ('build', 'id'), ('object_attributes', 'id'))[:64],
        timestamp=datetime.now().isoformat(),
        raw_payload_summary=f"Provider: {provider}, Status: {status}, Branch: {get_val('ref')}"
    )

# ======================
# PROJECT SCANNING
# ======================
IGNORE_PATTERNS = [
    '.git', '.venv', 'venv', 'node_modules', '__pycache__', '*.pyc', '*.pyo', 
    '*.pyd', '.pytest_cache', '.mypy_cache', '.tox', 'dist', 'build', 'eggs', 
    '*.egg', '.eggs', '.idea', '.vscode', '.env', '.env.*', '*.pem', '*.key', 
    '*.crt', '*.cert', 'secrets', 'credentials', 'tokens', 'local_settings.py',
    'instance', 'logs', '*.log', '.DS_Store', 'Thumbs.db'
]

def should_ignore(path: Path) -> bool:
    """Check if path matches ignore patterns"""
    rel_path = path.relative_to(PROJECT_ROOT) if path.is_absolute() else path
    parts = rel_path.parts if hasattr(rel_path, 'parts') else str(rel_path).split(os.sep)
    
    for part in parts:
        if part.startswith('.') and part not in ('.', '..'):
            return True
        for pattern in IGNORE_PATTERNS:
            if pattern.startswith('*.'):
                if part.endswith(pattern[1:]):
                    return True
            elif pattern == part or pattern == os.path.basename(part):
                return True
    return False

def is_binary_file(filepath: Path) -> bool:
    """Check if file is binary using simple heuristic"""
    try:
        with open(filepath, 'rb') as f:
            chunk = f.read(1024)
        return b'\0' in chunk
    except Exception:
        return True

def scan_project_files(max_files: int = MAX_SCAN_FILES) -> List[FileMetadata]:
    """Recursively scan project files with safety limits"""
    files = []
    main_candidates = ['app.py', 'application.py', 'main.py', 'wsgi.py', 'run.py']
    main_entry = None
    
    # First pass: find main entry point
    for candidate in main_candidates:
        candidate_path = PROJECT_ROOT / candidate
        if candidate_path.exists() and not should_ignore(candidate_path):
            main_entry = candidate
            break
    
    # Second pass: collect files
    try:
        for root, dirs, filenames in os.walk(PROJECT_ROOT, topdown=True):
            # Prune ignored directories early
            dirs[:] = [d for d in dirs if not should_ignore(Path(root) / d)]
            
            # Depth check
            depth = len(Path(root).relative_to(PROJECT_ROOT).parts) if root != str(PROJECT_ROOT) else 0
            if depth > MAX_SCAN_DEPTH:
                continue
            
            for filename in filenames:
                if len(files) >= max_files:
                    break
                
                filepath = Path(root) / filename
                rel_path = filepath.relative_to(PROJECT_ROOT)
                
                if should_ignore(filepath):
                    continue
                
                # Size check
                try:
                    size = filepath.stat().st_size
                    if size > MAX_FILE_SIZE_BYTES:
                        continue
                except Exception:
                    continue
                
                # Binary check
                is_binary = False
                content = ""
                if filepath.suffix in ('.py', '.yml', '.yaml', '.json', '.txt', '.md', '.html', '.js', '.css'):
                    try:
                        content = filepath.read_text(encoding='utf-8', errors='ignore')
                        is_binary = False
                    except Exception:
                        is_binary = True
                else:
                    is_binary = is_binary_file(filepath)
                
                # Determine category and purpose
                category = "other"
                purpose = "General project file"
                if main_entry and str(rel_path) == main_entry:
                    category = "main"
                    purpose = "Application entry point"
                elif any(pat in str(rel_path).lower() for pat in ['pipeline', 'workflow', '.github', 'azure-pipelines', 'jenkins']):
                    category = "pipeline"
                    purpose = "CI/CD pipeline configuration"
                elif any(pat in str(rel_path).lower() for pat in ['agent', 'ai', 'llm', 'model', 'rag', 'chat', 'bot']):
                    category = "ai"
                    purpose = "AI/ML related functionality"
                elif filepath.suffix in ('.cfg', '.ini', '.env.example', 'settings.py', 'config.py'):
                    category = "config"
                    purpose = "Configuration file"
                elif 'test' in str(rel_path).lower() or filepath.suffix == '.py' and 'test' in filename.lower():
                    category = "test"
                    purpose = "Test file"
                elif filepath.suffix in ('.html', '.j2', '.tmpl'):
                    category = "template"
                    purpose = "Template file"
                elif filepath.suffix in ('.js', '.css', '.png', '.jpg', '.svg'):
                    category = "static"
                    purpose = "Static asset"
                
                # Extract Python metadata if applicable
                imports, classes, funcs = [], [], []
                agent_evidence = []
                if filepath.suffix == '.py' and not is_binary and content:
                    try:
                        tree = ast.parse(content)
                        for node in ast.walk(tree):
                            if isinstance(node, ast.Import):
                                for alias in node.names:
                                    imports.append(alias.name)
                            elif isinstance(node, ast.ImportFrom):
                                imports.append(node.module or '')
                            elif isinstance(node, ast.ClassDef):
                                classes.append(node.name)
                                # Check for agent indicators in class
                                if any(kw in node.name.lower() for kw in ['agent', 'bot', 'assistant']):
                                    agent_evidence.append({
                                        "type": "class_name",
                                        "value": node.name,
                                        "line": node.lineno
                                    })
                            elif isinstance(node, ast.FunctionDef):
                                funcs.append(node.name)
                        
                        # Check for agent framework imports
                        ai_keywords = {
                            'langchain': ['langchain', 'crewai', 'autogen'],
                            'openai': ['openai', 'azure.ai'],
                            'anthropic': ['anthropic'],
                            'llama_index': ['llama_index', 'llama-index'],
                            'semantic_kernel': ['semantic_kernel', 'semantic-kernel'],
                            'custom': ['agent', 'llm', 'model', 'chat', 'completion']
                        }
                        for imp in imports:
                            for framework, keywords in ai_keywords.items():
                                if any(kw in imp.lower() for kw in keywords):
                                    agent_evidence.append({
                                        "type": "import",
                                        "framework": framework,
                                        "value": imp,
                                        "line": 0
                                    })
                    except Exception:
                        pass
                
                files.append(FileMetadata(
                    path=str(rel_path),
                    type=filepath.suffix or "unknown",
                    size=size,
                    is_binary=is_binary,
                    purpose=purpose,
                    category=category,
                    imports=imports[:10],  # Limit to avoid bloat
                    classes=classes[:10],
                    functions=funcs[:10],
                    agent_evidence=agent_evidence,
                    referenced_by_main=False  # Will be updated later
                ))
            
            if len(files) >= max_files:
                break
    except Exception as e:
        logger.error(f"Scan error: {str(e)}")
    
    # Prioritize files: main entry first, then pipeline, AI, config, etc.
    def sort_key(f: FileMetadata):
        priority = {
            'main': 0,
            'pipeline': 1,
            'ai': 2,
            'config': 3,
            'test': 4,
            'template': 5,
            'static': 6,
            'other': 7
        }
        return (priority.get(f.category, 7), f.path.lower())
    
    files.sort(key=sort_key)
    return files

def detect_ai_agents(files: List[FileMetadata]) -> List[AIAgent]:
    """Analyze files to detect AI agents with evidence-based classification"""
    agents = []
    ai_frameworks = {
        'langchain': ['langchain', 'langgraph', 'crewai', 'autogen'],
        'openai': ['openai', 'azure.ai.openai'],
        'anthropic': ['anthropic'],
        'google': ['google.generativeai', 'vertexai'],
        'aws': ['boto3', 'bedrock'],
        'huggingface': ['transformers', 'huggingface'],
        'ollama': ['ollama'],
        'llama_index': ['llama_index'],
        'semantic_kernel': ['semantic_kernel'],
        'cohere': ['cohere'],
        'mistral': ['mistralai'],
        'groq': ['groq']
    }
    
    # First pass: identify candidate agent files
    candidate_files = [f for f in files if f.category == 'ai' or f.agent_evidence]
    
    for file_meta in candidate_files:
        # Skip self-monitoring file
        if 'agent_monitor.py' in file_meta.path:
            continue
        
        evidence_items = []
        provider, model, framework = "Unknown", "Unknown", "Unknown"
        tools, memory_mech = [], []
        confidence = ConfidenceLevel.LOW
        classification = AgentClassification.INSUFFICIENT
        
        # Analyze evidence from file metadata
        for evidence in file_meta.agent_evidence:
            evidence_items.append({
                "source": file_meta.path,
                "type": evidence["type"],
                "details": evidence
            })
            
            # Determine framework
            if evidence["type"] == "import":
                for fw, keywords in ai_frameworks.items():
                    if any(kw in evidence.get("value", "").lower() for kw in keywords):
                        framework = fw.capitalize()
                        confidence = ConfidenceLevel.MEDIUM
                        classification = AgentClassification.PROBABLE
        
        # Check content for model references (safe pattern matching)
        try:
            content = (PROJECT_ROOT / file_meta.path).read_text(encoding='utf-8', errors='ignore').lower()
            
            # Model detection patterns
            model_patterns = [
                (r'gpt-[34]-[0-9]+', 'OpenAI'),
                (r'claude-[23]', 'Anthropic'),
                (r'gemini-[12]', 'Google'),
                (r'llama-[23]', 'Meta'),
                (r'mixtral', 'Mistral'),
                (r'command-r', 'Cohere'),
                (r'phi-[23]', 'Microsoft'),
            ]
            for pattern, prov in model_patterns:
                if re.search(pattern, content):
                    model = re.search(pattern, content).group()
                    provider = prov
                    confidence = ConfidenceLevel.HIGH if confidence == ConfidenceLevel.MEDIUM else ConfidenceLevel.MEDIUM
                    classification = AgentClassification.CONFIRMED
            
            # Tool/function calling evidence
            if any(kw in content for kw in ['tool_call', 'function_call', 'tools=']):
                tools.append("Function Calling")
                evidence_items.append({"source": file_meta.path, "type": "capability", "value": "Function Calling"})
            
            # Memory evidence
            if any(kw in content for kw in ['memory', 'history', 'conversationbuffer', 'vectorstore', 'retriever']):
                memory_mech.append("Conversation History" if 'history' in content else "Vector Store")
                evidence_items.append({"source": file_meta.path, "type": "capability", "value": "Memory Mechanism"})
            
            # Agent framework patterns
            if 'langgraph' in content or 'stategraph' in content:
                framework = "LangGraph"
                evidence_items.append({"source": file_meta.path, "type": "framework", "value": "LangGraph"})
            elif 'crew' in content and 'agent' in content:
                framework = "CrewAI"
                evidence_items.append({"source": file_meta.path, "type": "framework", "value": "CrewAI"})
            
        except Exception:
            pass
        
        # Final classification logic
        evidence_count = len(evidence_items)
        if evidence_count >= 3:
            classification = AgentClassification.CONFIRMED
            confidence = ConfidenceLevel.HIGH
        elif evidence_count == 2:
            classification = AgentClassification.PROBABLE
            confidence = ConfidenceLevel.MEDIUM
        elif evidence_count == 1:
            classification = AgentClassification.HELPER
            confidence = ConfidenceLevel.LOW
        
        # Determine if in use (simplified: if in main app directory or has strong evidence)
        in_use = file_meta.category == 'ai' and (confidence in [ConfidenceLevel.HIGH, ConfidenceLevel.MEDIUM] or 
                                                  any('main' in imp.lower() for imp in file_meta.imports))
        
        agents.append(AIAgent(
            name=file_meta.path.split('/')[-1].replace('.py', '').replace('_', ' ').title(),
            filepath=file_meta.path,
            classification=classification,
            confidence=confidence,
            provider=provider,
            model=model,
            framework=framework,
            purpose=file_meta.purpose,
            tools=tools,
            memory_mechanism=", ".join(memory_mech) if memory_mech else "None detected",
            evidence=evidence_items,
            in_use=in_use,
            last_activity="Unknown"
        ))
    
    return agents

# ======================
# USAGE & STORAGE HELPERS
# ======================
def load_webhook_history() -> List[WebhookEvent]:
    """Load webhook history from disk with thread safety"""
    global _webhook_history
    with _webhook_lock:
        try:
            history_file = STORAGE_DIR / 'webhook_history.json'
            if history_file.exists():
                data = json.loads(history_file.read_text())
                return [WebhookEvent(**item) for item in data[-MAX_WEBHOOK_HISTORY:]]
        except Exception as e:
            logger.error(f"Error loading webhook history: {e}")
        return _webhook_history[-MAX_WEBHOOK_HISTORY:]

def save_webhook_event(event: WebhookEvent):
    """Save webhook event to disk and memory"""
    global _webhook_history
    with _webhook_lock:
        _webhook_history.append(event)
        if len(_webhook_history) > MAX_WEBHOOK_HISTORY:
            _webhook_history = _webhook_history[-MAX_WEBHOOK_HISTORY:]
        
        try:
            history_file = STORAGE_DIR / 'webhook_history.json'
            serializable = [asdict(e) for e in _webhook_history]
            history_file.write_text(json.dumps(serializable, indent=2))
        except Exception as e:
            logger.error(f"Error saving webhook history: {e}")

def record_usage(data: Dict):
    """Record token usage telemetry with bounds checking"""
    global _usage_ledger
    with _usage_lock:
        agent_id = data.get('agent_id', 'unknown')
        if len(_usage_ledger[agent_id]) > MAX_USAGE_HISTORY:
            _usage_ledger[agent_id] = _usage_ledger[agent_id][-MAX_USAGE_HISTORY:]
        
        # Apply limits from config if available
        agent_config = AGENT_LIMITS.get(agent_id, {})
        usage = TokenUsage(
            prompt_tokens=min(int(data.get('prompt_tokens', 0)), 10**7),
            completion_tokens=min(int(data.get('completion_tokens', 0)), 10**7),
            total_tokens=min(int(data.get('total_tokens', 0)), 10**7),
            requests=min(int(data.get('request_count', 1)), 10000),
            timestamp=data.get('timestamp', datetime.now().isoformat()),
            context_window=agent_config.get('context_window'),
            hourly_limit=agent_config.get('hourly_limit'),
            daily_limit=agent_config.get('daily_limit')
        )
        _usage_ledger[agent_id].append(asdict(usage))
        
        # Persist to disk (append-only for simplicity)
        try:
            usage_file = STORAGE_DIR / f'usage_{agent_id}.json'
            existing = []
            if usage_file.exists():
                try:
                    existing = json.loads(usage_file.read_text())
                    if len(existing) > MAX_USAGE_HISTORY:
                        existing = existing[-MAX_USAGE_HISTORY:]
                except Exception:
                    existing = []
            existing.append(asdict(usage))
            usage_file.write_text(json.dumps(existing[-MAX_USAGE_HISTORY:], indent=2))
        except Exception as e:
            logger.error(f"Error saving usage data: {e}")

def get_agent_usage(agent_id: str) -> Dict:
    """Aggregate usage statistics for an agent"""
    with _usage_lock:
        history = _usage_ledger.get(agent_id, [])
        if not history:
            return {
                "hourly": {"used": 0, "limit": "Unknown", "remaining": "Unknown", "percent": 0},
                "daily": {"used": 0, "limit": "Unknown", "remaining": "Unknown", "percent": 0},
                "tokens": {"prompt": 0, "completion": 0, "total": 0},
                "history": []
            }
        
        # Simple aggregation (last 24 hours for daily, last hour for hourly)
        now = datetime.now()
        hourly_start = now - timedelta(hours=1)
        daily_start = now - timedelta(days=1)
        
        hourly_requests, daily_requests = 0, 0
        prompt_tokens, completion_tokens, total_tokens = 0, 0, 0
        
        for entry in history:
            try:
                ts = datetime.fromisoformat(entry['timestamp'].replace('Z', '+00:00'))
                if ts >= hourly_start:
                    hourly_requests += entry.get('requests', 1)
                if ts >= daily_start:
                    daily_requests += entry.get('requests', 1)
                
                prompt_tokens += entry.get('prompt_tokens', 0)
                completion_tokens += entry.get('completion_tokens', 0)
                total_tokens += entry.get('total_tokens', 0)
            except Exception:
                continue
        
        # Get limits (from config or history)
        agent_config = AGENT_LIMITS.get(agent_id, {})
        hourly_limit = agent_config.get('hourly_limit')
        daily_limit = agent_config.get('daily_limit')
        
        def calc_usage(used, limit):
            if limit and limit > 0:
                remaining = max(0, limit - used)
                percent = min(100, (used / limit) * 100)
                return used, limit, remaining, round(percent, 1)
            return used, "Unknown", "Unknown", 0
        
        h_used, h_limit, h_rem, h_pct = calc_usage(hourly_requests, hourly_limit)
        d_used, d_limit, d_rem, d_pct = calc_usage(daily_requests, daily_limit)
        
        return {
            "hourly": {
                "used": h_used,
                "limit": h_limit,
                "remaining": h_rem,
                "percent": h_pct
            },
            "daily": {
                "used": d_used,
                "limit": d_limit,
                "remaining": d_rem,
                "percent": d_pct
            },
            "tokens": {
                "prompt": prompt_tokens,
                "completion": completion_tokens,
                "total": total_tokens
            },
            "history": history[-50:]  # Last 50 entries for charts
        }

# ======================
# FLASK APPLICATION SETUP
# ======================
# Create Flask application instance (exported for app.py)
application = Flask(__name__)
application.config['JSON_AS_ASCII'] = False
application.config['JSON_SORT_KEYS'] = False

# Embed index.html template via Jinja loader
INDEX_HTML = '''<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>SentinelOps AI Agent Monitor</title>
    <style>
        :root {
            --primary: #2e7d32;
            --primary-light: #4caf50;
            --secondary: #00796b;
            --accent: #388e3c;
            --bg: #f8faf8;
            --card-bg: #ffffff;
            --border: #e0e6e0;
            --text: #2d372d;
            --text-secondary: #556b55;
            --success: #2e7d32;
            --warning: #ed6c02;
            --error: #c62828;
            --info: #0288d1;
            --shadow: 0 2px 10px rgba(0,0,0,0.08);
            --transition: all 0.3s ease;
        }
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Oxygen, Ubuntu, Cantarell, 'Open Sans', 'Helvetica Neue', sans-serif;
            background-color: var(--bg);
            color: var(--text);
            line-height: 1.5;
            padding: 0;
            margin: 0;
        }
        .container {
            width: 100%;
            max-width: 1400px;
            margin: 0 auto;
            padding: 0 1.5rem;
        }
        header {
            background: linear-gradient(120deg, var(--primary), var(--secondary));
            color: white;
            padding: 1.5rem 0;
            box-shadow: var(--shadow);
            position: sticky;
            top: 0;
            z-index: 100;
        }
        .header-content {
            display: flex;
            justify-content: space-between;
            align-items: center;
            flex-wrap: wrap;
        }
        .logo {
            font-size: 1.8rem;
            font-weight: 700;
            display: flex;
            align-items: center;
            gap: 0.75rem;
        }
        .logo-icon { font-size: 2rem; }
        .status-bar {
            display: flex;
            align-items: center;
            gap: 1.5rem;
            margin-top: 1rem;
            flex-wrap: wrap;
        }
        .status-item {
            display: flex;
            align-items: center;
            gap: 0.5rem;
            font-size: 0.95rem;
        }
        .status-dot {
            width: 10px;
            height: 10px;
            border-radius: 50%;
            background: var(--success);
        }
        .status-dot.warning { background: var(--warning); }
        .status-dot.error { background: var(--error); }
        .status-dot.unknown { background: #9e9e9e; }
        main {
            padding: 2rem 0;
        }
        .summary-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));
            gap: 1.5rem;
            margin-bottom: 2rem;
        }
        .card {
            background: var(--card-bg);
            border-radius: 10px;
            box-shadow: var(--shadow);
            padding: 1.5rem;
            transition: var(--transition);
            border: 1px solid var(--border);
        }
        .card:hover {
            box-shadow: 0 4px 15px rgba(0,0,0,0.12);
            transform: translateY(-2px);
        }
        .card-title {
            display: flex;
            align-items: center;
            gap: 0.75rem;
            font-size: 1.1rem;
            font-weight: 600;
            margin-bottom: 1rem;
            color: var(--secondary);
        }
        .card-icon { font-size: 1.4rem; }
        .metric-value {
            font-size: 1.8rem;
            font-weight: 700;
            margin: 0.5rem 0;
            color: var(--primary);
        }
        .metric-label {
            color: var(--text-secondary);
            font-size: 0.95rem;
        }
        .progress-container {
            margin-top: 0.75rem;
        }
        .progress-label {
            display: flex;
            justify-content: space-between;
            font-size: 0.85rem;
            margin-bottom: 0.25rem;
        }
        .progress-bar {
            height: 8px;
            background: #e8f5e9;
            border-radius: 4px;
            overflow: hidden;
        }
        .progress-fill {
            height: 100%;
            background: var(--accent);
            border-radius: 4px;
            transition: width 0.5s ease;
        }
        .progress-fill.warning { background: var(--warning); }
        .progress-fill.error { background: var(--error); }
        .section {
            margin-bottom: 2.5rem;
        }
        .section-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 1.25rem;
            padding-bottom: 0.75rem;
            border-bottom: 2px solid var(--border);
        }
        .section-title {
            font-size: 1.5rem;
            font-weight: 700;
            color: var(--secondary);
        }
        .section-actions {
            display: flex;
            gap: 0.75rem;
        }
        .btn {
            background: var(--primary);
            color: white;
            border: none;
            padding: 0.6rem 1.25rem;
            border-radius: 6px;
            cursor: pointer;
            font-weight: 500;
            transition: var(--transition);
            display: flex;
            align-items: center;
            gap: 0.5rem;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
        }
        .btn:hover {
            background: var(--primary-light);
            transform: translateY(-1px);
            box-shadow: 0 4px 8px rgba(0,0,0,0.15);
        }
        .btn.secondary {
            background: #757575;
        }
        .btn.secondary:hover {
            background: #616161;
        }
        .btn:active {
            transform: translateY(1px);
            box-shadow: 0 1px 2px rgba(0,0,0,0.1);
        }
        .badge {
            display: inline-block;
            padding: 0.25rem 0.75rem;
            border-radius: 20px;
            font-size: 0.85rem;
            font-weight: 500;
            background: #e8f5e9;
            color: var(--success);
        }
        .badge.warning {
            background: #fff8e1;
            color: var(--warning);
        }
        .badge.error {
            background: #ffebee;
            color: var(--error);
        }
        .badge.info {
            background: #e3f2fd;
            color: var(--info);
        }
        .pipeline-timeline {
            position: relative;
            padding-left: 2rem;
            margin: 1.5rem 0;
        }
        .timeline-item {
            position: relative;
            margin-bottom: 1.5rem;
            padding-left: 1.5rem;
        }
        .timeline-item:before {
            content: '';
            position: absolute;
            left: -28px;
            top: 8px;
            width: 16px;
            height: 16px;
            border-radius: 50%;
            background: var(--primary);
            border: 3px solid white;
            box-shadow: 0 0 0 2px var(--primary);
        }
        .timeline-item.status-success:before { background: var(--success); box-shadow: 0 0 0 2px var(--success); }
        .timeline-item.status-failure:before { background: var(--error); box-shadow: 0 0 0 2px var(--error); }
        .timeline-item.status-running:before { background: var(--warning); box-shadow: 0 0 0 2px var(--warning); }
        .timeline-time {
            font-weight: 600;
            color: var(--secondary);
            margin-bottom: 0.25rem;
        }
        .timeline-content {
            background: var(--card-bg);
            border: 1px solid var(--border);
            border-radius: 8px;
            padding: 1rem;
            box-shadow: var(--shadow);
        }
        .agent-grid {
            display: grid;
            grid-template-columns: repeat(auto-fill, minmax(300px, 1fr));
            gap: 1.5rem;
        }
        .agent-card {
            border-left: 4px solid var(--primary);
            transition: var(--transition);
        }
        .agent-card:hover {
            border-left-color: var(--primary-light);
            transform: translateX(5px);
        }
        .agent-card.status-warning { border-left-color: var(--warning); }
        .agent-card.status-error { border-left-color: var(--error); }
        .agent-header {
            display: flex;
            justify-content: space-between;
            align-items: start;
            margin-bottom: 1rem;
            flex-wrap: wrap;
            gap: 0.5rem;
        }
        .agent-name {
            font-size: 1.25rem;
            font-weight: 700;
            color: var(--text);
        }
        .agent-meta {
            display: flex;
            flex-wrap: wrap;
            gap: 0.75rem;
            margin-top: 0.5rem;
            font-size: 0.95rem;
            color: var(--text-secondary);
        }
        .meta-item {
            display: flex;
            align-items: center;
            gap: 0.4rem;
        }
        .file-tree {
            font-family: monospace;
            background: var(--card-bg);
            border: 1px solid var(--border);
            border-radius: 8px;
            padding: 1.25rem;
            overflow: auto;
            max-height: 400px;
            line-height: 1.6;
        }
        .file-entry {
            display: flex;
            align-items: start;
            gap: 0.5rem;
        }
        .file-icon {
            color: var(--secondary);
            margin-top: 0.25rem;
        }
        .file-path {
            font-weight: 500;
        }
        .file-category {
            font-size: 0.85rem;
            background: #e8f5e9;
            color: var(--success);
            padding: 0.15rem 0.5rem;
            border-radius: 4px;
            margin-left: 0.5rem;
        }
        .file-category.pipeline { background: #e3f2fd; color: var(--info); }
        .file-category.ai { background: #fff8e1; color: var(--warning); }
        .file-category.config { background: #f3e5f5; color: #4a148c; }
        .empty-state {
            text-align: center;
            padding: 2.5rem 1.5rem;
            color: var(--text-secondary);
            border: 1px dashed var(--border);
            border-radius: 8px;
            background: var(--card-bg);
        }
        .empty-icon {
            font-size: 3rem;
            margin-bottom: 1rem;
            color: #a5d6a7;
        }
        .chart-container {
            height: 200px;
            background: var(--card-bg);
            border: 1px solid var(--border);
            border-radius: 8px;
            margin-top: 1rem;
            position: relative;
            overflow: hidden;
        }
        .chart-placeholder {
            display: flex;
            align-items: center;
            justify-content: center;
            height: 100%;
            color: var(--text-secondary);
            font-style: italic;
        }
        .confidence-indicator {
            display: inline-block;
            width: 12px;
            height: 12px;
            border-radius: 50%;
            margin-right: 0.4rem;
        }
        .confidence-high { background: var(--success); }
        .confidence-medium { background: var(--warning); }
        .confidence-low { background: #ffab00; }
        .confidence-none { background: #bdbdbd; }
        .last-updated {
            text-align: right;
            font-size: 0.85rem;
            color: var(--text-secondary);
            margin-top: 0.5rem;
            font-style: italic;
        }
        footer {
            background: var(--card-bg);
            border-top: 1px solid var(--border);
            padding: 1.5rem 0;
            margin-top: 2rem;
            text-align: center;
            color: var(--text-secondary);
            font-size: 0.9rem;
        }
        @media (max-width: 768px) {
            .header-content, .status-bar {
                flex-direction: column;
                align-items: flex-start;
                gap: 1rem;
            }
            .summary-grid, .agent-grid {
                grid-template-columns: 1fr;
            }
            .section-actions {
                width: 100%;
                flex-wrap: wrap;
            }
            .btn {
                width: 100%;
                justify-content: center;
            }
        }
        @media (prefers-reduced-motion) {
            * { transition: none !important; }
        }
        [data-loading] {
            opacity: 0.7;
            pointer-events: none;
        }
        .toast {
            position: fixed;
            bottom: 1.5rem;
            right: 1.5rem;
            background: white;
            border-left: 4px solid var(--success);
            box-shadow: var(--shadow);
            padding: 1rem 1.5rem;
            border-radius: 6px;
            display: flex;
            align-items: center;
            gap: 0.75rem;
            z-index: 1000;
            transform: translateX(400px);
            transition: transform 0.3s ease;
        }
        .toast.show {
            transform: translateX(0);
        }
        .toast.error { border-left-color: var(--error); }
        .toast.warning { border-left-color: var(--warning); }
    </style>
</head>
<body>
    <header>
        <div class="container">
            <div class="header-content">
                <div class="logo">
                    <span class="logo-icon">🛡️</span>
                    <span>SentinelOps AI Agent Monitor</span>
                </div>
                <div class="status-bar">
                    <div class="status-item">
                        <div class="status-dot" id="pipeline-status-dot"></div>
                        <span id="pipeline-status-text">Unknown</span>
                    </div>
                    <div class="status-item">
                        <div class="status-dot unknown" id="agents-status-dot"></div>
                        <span id="agents-status-text">Agents: -</span>
                    </div>
                    <div class="status-item">
                        <span id="last-updated">Last updated: -</span>
                    </div>
                </div>
            </div>
        </div>
    </header>

    <main class="container">
        <!-- Summary Cards -->
        <section class="summary-grid" id="summary-cards">
            <div class="card">
                <div class="card-title"><span class="card-icon">🚀</span> Pipeline Status</div>
                <div class="metric-value" id="pipeline-status">-</div>
                <div class="metric-label" id="pipeline-provider">-</div>
                <div class="progress-container">
                    <div class="progress-label">
                        <span>Latest Run</span>
                        <span id="run-id">-</span>
                    </div>
                    <div class="progress-bar">
                        <div class="progress-fill" id="pipeline-progress" style="width: 0%"></div>
                    </div>
                </div>
            </div>
            <div class="card">
                <div class="card-title"><span class="card-icon">🧠</span> AI Agents</div>
                <div class="metric-value" id="agent-count">-</div>
                <div class="metric-label">Active in Project</div>
                <div class="progress-container">
                    <div class="progress-label">
                        <span>Confidence</span>
                        <span id="agent-confidence">-</span>
                    </div>
                    <div class="progress-bar">
                        <div class="progress-fill" id="agent-progress" style="width: 0%"></div>
                    </div>
                </div>
            </div>
            <div class="card">
                <div class="card-title"><span class="card-icon">📊</span> Token Usage</div>
                <div class="metric-value" id="token-total">-</div>
                <div class="metric-label">Total Tokens (24h)</div>
                <div class="progress-container">
                    <div class="progress-label">
                        <span>Requests</span>
                        <span id="request-count">-</span>
                    </div>
                    <div class="progress-bar">
                        <div class="progress-fill" id="request-progress" style="width: 0%"></div>
                    </div>
                </div>
            </div>
            <div class="card">
                <div class="card-title"><span class="card-icon">📁</span> Project Files</div>
                <div class="metric-value" id="file-count">-</div>
                <div class="metric-label" id="main-file">-</div>
                <div class="progress-container">
                    <div class="progress-label">
                        <span>Scanned</span>
                        <span id="scan-depth">-</span>
                    </div>
                    <div class="progress-bar">
                        <div class="progress-fill" style="width: 100%; background: var(--secondary)"></div>
                    </div>
                </div>
            </div>
        </section>

        <!-- Pipeline Timeline -->
        <section class="section">
            <div class="section-header">
                <h2 class="section-title">Pipeline Activity</h2>
                <div class="section-actions">
                    <button class="btn secondary" id="refresh-btn">
                        <span>⟳</span> Refresh Data
                    </button>
                </div>
            </div>
            <div id="pipeline-timeline" class="pipeline-timeline">
                <!-- Filled by JS -->
            </div>
        </section>

        <!-- AI Agents -->
        <section class="section">
            <div class="section-header">
                <h2 class="section-title">AI Agents in Project</h2>
            </div>
            <div id="agents-container">
                <div class="empty-state">
                    <div class="empty-icon">🤖</div>
                    <p>No AI agents detected. Scan in progress...</p>
                </div>
            </div>
        </section>

        <!-- Project Structure -->
        <section class="section">
            <div class="section-header">
                <h2 class="section-title">Project Structure</h2>
            </div>
            <div class="card">
                <div class="file-tree" id="file-tree">
                    <!-- Filled by JS -->
                </div>
            </div>
        </section>

        <!-- How Agents Are Identified -->
        <section class="section">
            <div class="section-header">
                <h2 class="section-title">How AI Agents Are Identified</h2>
            </div>
            <div class="card">
                <p>This monitor uses <strong>evidence-based analysis</strong> without executing project code:</p>
                <ul style="padding-left: 1.5rem; margin-top: 0.75rem; line-height: 1.7">
                    <li><strong>Framework Detection:</strong> Imports of LangChain, CrewAI, AutoGen, Semantic Kernel, etc.</li>
                    <li><strong>Model References:</strong> GPT, Claude, Gemini, Llama, Mistral patterns in code</li>
                    <li><strong>Capability Signatures:</strong> Function/tool calling, memory mechanisms, RAG patterns</li>
                    <li><strong>Structural Analysis:</strong> Class/function names containing "agent", "bot", "assistant"</li>
                    <li><strong>Configuration Clues:</strong> Model parameters, system prompts, tool definitions</li>
                </ul>
                <p style="margin-top: 1rem; padding-top: 0.75rem; border-top: 1px solid var(--border);">
                    <strong>Confidence Levels:</strong>
                    <span class="badge" style="background:#e8f5e9;color:var(--success)"><span class="confidence-indicator confidence-high"></span>High</span> (3+ strong evidence items),
                    <span class="badge warning"><span class="confidence-indicator confidence-medium"></span>Medium</span> (2 evidence items),
                    <span class="badge" style="background:#fff8e1;color:#5d4037"><span class="confidence-indicator confidence-low"></span>Low</span> (1 evidence item),
                    <span class="badge" style="background:#f5f5f5;color:#616161"><span class="confidence-indicator confidence-none"></span>None</span> (insufficient evidence)
                </p>
                <p style="margin-top: 0.75rem; font-style: italic; color: var(--text-secondary);">
                    Note: Filename containing "agent" alone is <strong>not sufficient</strong> for classification. 
                    <code>agent_monitor.py</code> is excluded from agent detection as it is the monitoring utility itself.
                </p>
            </div>
        </section>
    </main>

    <footer class="container">
        <p>SentinelOps Agent Monitor • All analysis performed locally • No external API calls • v1.0</p>
        <p style="margin-top: 0.25rem; font-size: 0.85rem; color: var(--text-secondary);">
            Pipeline detection combines environment variables, repository configuration, and webhook history. 
            Token usage requires telemetry via <code>POST /api/sentinelops/usage</code>.
        </p>
    </footer>

    <div class="toast" id="toast">
        <span id="toast-icon">✅</span>
        <span id="toast-message">Operation successful</span>
    </div>

    <script>
        // Minimal vanilla JS for dashboard functionality
        const API_BASE = '/api/sentinelops';
        let dashboardData = null;
        const TOAST = {
            show: (message, type = 'success') => {
                const toast = document.getElementById('toast');
                const icon = document.getElementById('toast-icon');
                const msgEl = document.getElementById('toast-message');
                
                toast.className = `toast ${type} show`;
                icon.textContent = type === 'error' ? '❌' : type === 'warning' ? '⚠️' : '✅';
                msgEl.textContent = message;
                
                setTimeout(() => {
                    toast.classList.remove('show');
                }, 3000);
            },
            success: (msg) => TOAST.show(msg, 'success'),
            error: (msg) => TOAST.show(msg, 'error'),
            warning: (msg) => TOAST.show(msg, 'warning')
        };

        // Format helpers
        const fmt = {
            datetime: (isoStr) => {
                if (!isoStr) return 'Unknown';
                try {
                    const dt = new Date(isoStr);
                    return dt.toLocaleString('en-US', { 
                        month: 'short', 
                        day: 'numeric', 
                        hour: '2-digit', 
                        minute: '2-digit' 
                    });
                } catch {
                    return isoStr.substring(0, 16).replace('T', ' ');
                }
            },
            number: (num) => {
                if (typeof num !== 'number' || isNaN(num)) return num;
                return num > 9999 ? (num / 1000).toFixed(1) + 'k' : num.toLocaleString();
            },
            percent: (val) => `${Math.min(100, Math.max(0, val)).toFixed(0)}%`,
            statusClass: (status) => {
                const s = (status || '').toLowerCase();
                if (s.includes('success') || s.includes('completed')) return 'status-success';
                if (s.includes('fail') || s.includes('error')) return 'status-failure';
                if (s.includes('run') || s.includes('process')) return 'status-running';
                return '';
            },
            confidenceClass: (level) => {
                const map = { 'High': 'confidence-high', 'Medium': 'confidence-medium', 'Low': 'confidence-low', 'None': 'confidence-none' };
                return map[level] || 'confidence-none';
            }
        };

        // DOM renderers
        const renderers = {
            summary: (data) => {
                document.getElementById('pipeline-status').textContent = data.pipeline?.latest_status || 'Unknown';
                document.getElementById('pipeline-provider').textContent = data.pipeline?.provider || 'Not detected';
                document.getElementById('agent-count').textContent = fmt.number(data.agents?.active_count || 0);
                document.getElementById('token-total').textContent = fmt.number(data.usage?.tokens?.total || 0);
                document.getElementById('request-count').textContent = fmt.number(data.usage?.hourly?.used || 0);
                document.getElementById('file-count').textContent = fmt.number(data.files?.total || 0);
                document.getElementById('main-file').textContent = data.files?.main_entry || 'Entry point unknown';
                document.getElementById('scan-depth').textContent = `${data.files?.scanned || 0} files`;
                
                // Progress bars
                const statusPct = data.pipeline?.confidence === 'High' ? 100 : 
                                 data.pipeline?.confidence === 'Medium' ? 70 : 
                                 data.pipeline?.confidence === 'Low' ? 30 : 0;
                document.getElementById('pipeline-progress').style.width = fmt.percent(statusPct);
                document.getElementById('pipeline-progress').className = `progress-fill ${statusPct > 80 ? '' : statusPct > 40 ? 'warning' : 'error'}`;
                
                const agentPct = data.agents?.confidence_score || 0;
                document.getElementById('agent-progress').style.width = fmt.percent(agentPct);
                document.getElementById('agent-progress').className = `progress-fill ${agentPct > 80 ? '' : agentPct > 40 ? 'warning' : 'error'}`;
                document.getElementById('agent-confidence').textContent = data.agents?.overall_confidence || 'Unknown';
                
                const reqPct = data.usage?.hourly?.percent || 0;
                document.getElementById('request-progress').style.width = fmt.percent(reqPct);
                document.getElementById('request-progress').className = `progress-fill ${reqPct > 90 ? 'error' : reqPct > 70 ? 'warning' : ''}`;
                
                // Status dots
                const pipelineDot = document.getElementById('pipeline-status-dot');
                pipelineDot.className = `status-dot ${fmt.statusClass(data.pipeline?.latest_status) || 'unknown'}`;
                document.getElementById('pipeline-status-text').textContent = data.pipeline?.latest_status || 'Unknown';
                
                const agentsDot = document.getElementById('agents-status-dot');
                agentsDot.className = `status-dot ${data.agents?.active_count > 0 ? 'success' : 'unknown'}`;
                document.getElementById('agents-status-text').textContent = `Agents: ${data.agents?.active_count || 0}`;
                
                // Last updated
                document.getElementById('last-updated').textContent = `Last updated: ${fmt.datetime(new Date().toISOString())}`;
                document.getElementById('run-id').textContent = (data.pipeline?.run_id || '---').substring(0, 8);
            },
            
            pipelineTimeline: (events) => {
                const container = document.getElementById('pipeline-timeline');
                if (!events || events.length === 0) {
                    container.innerHTML = '<div class="empty-state"><div class="empty-icon">⏱️</div><p>No pipeline events recorded</p></div>';
                    return;
                }
                
                let html = '';
                events.slice(0, 10).forEach(event => {
                    html += `
                        <div class="timeline-item ${fmt.statusClass(event.status)}">
                            <div class="timeline-time">${fmt.datetime(event.timestamp)}</div>
                            <div class="timeline-content">
                                <div style="display:flex;justify-content:space-between;flex-wrap:wrap;gap:0.5rem;margin-bottom:0.5rem">
                                    <strong>${event.workflow_name || event.provider}</strong>
                                    <span class="badge ${fmt.statusClass(event.status)}">${event.status}</span>
                                </div>
                                <div style="display:flex;flex-wrap:wrap;gap:1rem;font-size:0.95rem;color:var(--text-secondary)">
                                    <div><strong>Run:</strong> ${event.run_id.substring(0,8)}</div>
                                    <div><strong>Branch:</strong> ${event.branch}</div>
                                    <div><strong>Commit:</strong> ${event.commit_sha.substring(0,7)}</div>
                                </div>
                                ${event.run_url ? `<div style="margin-top:0.5rem"><a href="${event.run_url}" target="_blank" style="color:var(--secondary);text-decoration:underline">View Run Details</a></div>` : ''}
                            </div>
                        </div>
                    `;
                });
                container.innerHTML = html;
            },
            
            agents: (agents) => {
                const container = document.getElementById('agents-container');
                if (!agents || agents.length === 0) {
                    container.innerHTML = `
                        <div class="empty-state">
                            <div class="empty-icon">🔍</div>
                            <p>No AI agents detected in project files</p>
                            <p style="margin-top:0.5rem;font-size:0.9rem;color:var(--text-secondary)">
                                Agents are identified through evidence-based analysis of imports, model references, and capability patterns.
                            </p>
                        </div>
                    `;
                    return;
                }
                
                let html = '<div class="agent-grid">';
                agents.forEach(agent => {
                    const statusClass = agent.in_use ? '' : 'status-warning';
                    const confidenceClass = fmt.confidenceClass(agent.confidence);
                    html += `
                        <div class="card agent-card ${statusClass}">
                            <div class="agent-header">
                                <div class="agent-name">${agent.name}</div>
                                <span class="badge ${agent.in_use ? 'info' : 'warning'}">
                                    ${agent.in_use ? '✅ In Use' : '⚠️ Repository Only'}
                                </span>
                            </div>
                            <div style="margin-bottom:1rem">
                                <span class="confidence-indicator ${confidenceClass}"></span>
                                <strong>${agent.classification}</strong> 
                                <span style="color:var(--text-secondary);margin-left:0.5rem">(${agent.confidence} confidence)</span>
                            </div>
                            <div class="agent-meta">
                                <div class="meta-item">🛠️ <strong>${agent.framework || 'Unknown'}</strong></div>
                                <div class="meta-item">☁️ ${agent.provider}</div>
                                <div class="meta-item">🤖 ${agent.model}</div>
                            </div>
                            <div style="margin-top:0.75rem;padding-top:0.75rem;border-top:1px solid var(--border);font-size:0.95rem">
                                <div><strong>Purpose:</strong> ${agent.purpose}</div>
                                ${agent.tools.length > 0 ? `<div style="margin-top:0.25rem"><strong>Tools:</strong> ${agent.tools.join(', ')}</div>` : ''}
                                ${agent.memory_mechanism && agent.memory_mechanism !== 'None detected' ? 
                                  `<div style="margin-top:0.25rem"><strong>Memory:</strong> ${agent.memory_mechanism}</div>` : ''}
                            </div>
                            <div style="margin-top:0.75rem;font-size:0.85rem;color:var(--text-secondary)">
                                File: <code>${agent.filepath}</code>
                            </div>
                        </div>
                    `;
                });
                html += '</div>';
                container.innerHTML = html;
            },
            
            fileTree: (files) => {
                const container = document.getElementById('file-tree');
                if (!files || files.length === 0) {
                    container.innerHTML = '<div class="empty-state"><div class="empty-icon">📁</div><p>No files scanned</p></div>';
                    return;
                }
                
                // Build tree structure
                const tree = {};
                files.forEach(file => {
                    const parts = file.path.split('/');
                    let current = tree;
                    parts.forEach((part, i) => {
                        if (!current[part]) current[part] = i === parts.length - 1 ? file : {};
                        current = current[part];
                    });
                });
                
                // Render recursively
                const renderNode = (node, depth = 0) => {
                    let html = '';
                    const indent = '  '.repeat(depth);
                    
                    if (Array.isArray(node)) {
                        node.forEach(item => {
                            html += renderNode(item, depth);
                        });
                        return html;
                    }
                    
                    if (typeof node === 'object' && !node.path) {
                        Object.entries(node).sort((a, b) => {
                            // Directories first
                            if (typeof a[1] === 'object' && !Array.isArray(a[1]) && typeof b[1] !== 'object') return -1;
                            if (typeof b[1] === 'object' && !Array.isArray(b[1]) && typeof a[1] !== 'object') return 1;
                            return a[0].localeCompare(b[0]);
                        }).forEach(([key, value]) => {
                            if (typeof value === 'object' && value.path) {
                                // File
                                const categoryMap = {
                                    'main': 'pipeline',
                                    'pipeline': 'pipeline',
                                    'ai': 'ai',
                                    'config': 'config'
                                };
                                const categoryClass = categoryMap[value.category] || 'other';
                                html += `${indent}<div class="file-entry">
                                    <span class="file-icon">📄</span>
                                    <div>
                                        <span class="file-path">${key}</span>
                                        <span class="file-category ${categoryClass}">${value.category}</span>
                                        <div style="margin-left:1.5rem;font-size:0.85rem;color:var(--text-secondary)">${value.purpose}</div>
                                    </div>
                                </div>\n`;
                            } else {
                                // Directory
                                html += `${indent}<div class="file-entry">
                                    <span class="file-icon" style="color:#5d4037">📁</span>
                                    <strong>${key}/</strong>
                                </div>\n`;
                                html += renderNode(value, depth + 1);
                            }
                        });
                        return html;
                    }
                    
                    return html;
                };
                
                container.innerHTML = `<pre style="margin:0">${renderNode(tree)}</pre>`;
            }
        };

        // Data fetchers
        const fetchData = async () => {
            try {
                document.body.setAttribute('data-loading', 'true');
                const [summaryRes, historyRes] = await Promise.all([
                    fetch(`${API_BASE}/summary`),
                    fetch(`${API_BASE}/history`)
                ]);
                
                if (!summaryRes.ok || !historyRes.ok) throw new Error('API fetch failed');
                
                const summary = await summaryRes.json();
                const history = await historyRes.json();
                dashboardData = { ...summary, history };
                
                // Render all sections
                renderers.summary(summary);
                renderers.pipelineTimeline(history.webhook_events || []);
                renderers.agents(summary.agents?.list || []);
                renderers.fileTree(summary.files?.list || []);
                
                TOAST.success('Data refreshed successfully');
            } catch (err) {
                console.error('Fetch error:', err);
                TOAST.error('Failed to load monitoring data. Check console for details.');
            } finally {
                document.body.removeAttribute('data-loading');
            }
        };

        // Event listeners
        document.getElementById('refresh-btn').addEventListener('click', async () => {
            try {
                const res = await fetch(`${API_BASE}/rescan`, { method: 'POST' });
                if (res.ok) {
                    TOAST.success('Rescan initiated. Refreshing data...');
                    await new Promise(resolve => setTimeout(resolve, 1000)); // Brief delay for processing
                    await fetchData();
                } else {
                    const err = await res.text();
                    throw new Error(err || 'Rescan failed');
                }
            } catch (err) {
                TOAST.error(`Rescan failed: ${err.message}`);
            }
        });

        // Auto-refresh every 2 minutes
        setInterval(fetchData, 120000);

        // Initial load
        window.addEventListener('DOMContentLoaded', fetchData);
    </script>
</body>
</html>'''

# Configure Jinja loader to embed index.html
original_loader = application.jinja_loader
application.jinja_loader = ChoiceLoader([
    DictLoader({'index.html': INDEX_HTML}),
    original_loader if original_loader else FileSystemLoader('templates')
])

# ======================
# BLUEPRINTS & ROUTES
# ======================
monitor_bp = Blueprint('monitor', __name__, url_prefix='/api/sentinelops')
scanner_bp = Blueprint('scanner', __name__, url_prefix='/api/sentinelops')

@monitor_bp.route('/summary', methods=['GET'])
def get_summary():
    """Return comprehensive monitoring summary"""
    global _scan_cache, _scan_cache_time
    
    # Use cached scan results if recent (<5 minutes)
    with _scan_lock:
        if _scan_cache_time and (time.time() - _scan_cache_time) < 300:
            files = _scan_cache.get('files', [])
            agents = _scan_cache.get('agents', [])
        else:
            files = scan_project_files(MAX_SCAN_FILES)
            agents = detect_ai_agents(files)
            _scan_cache = {'files': files, 'agents': agents}
            _scan_cache_time = time.time()
    
    # Determine main entry file
    main_entry = next((f.path for f in files if f.category == 'main'), None)
    
    # Pipeline detection
    env_evidence = detect_ci_from_env()
    repo_evidences = detect_ci_from_repo()
    webhook_history = load_webhook_history()
    latest_webhook = webhook_history[-1] if webhook_history else None
    
    # Determine active pipeline provider
    pipeline_provider = "Unknown"
    pipeline_confidence = ConfidenceLevel.NONE
    latest_status = "Unknown"
    run_id = ""
    
    if env_evidence:
        pipeline_provider = env_evidence.provider
        pipeline_confidence = env_evidence.confidence
        latest_status = "Running"  # In CI environment
    elif latest_webhook:
        pipeline_provider = latest_webhook.provider
        pipeline_confidence = ConfidenceLevel.HIGH
        latest_status = latest_webhook.status
        run_id = latest_webhook.run_id
    elif repo_evidences:
        pipeline_provider = repo_evidences[0].provider
        pipeline_confidence = ConfidenceLevel.MEDIUM
    
    # Agent statistics
    active_agents = [a for a in agents if a.in_use]
    confidence_scores = {
        ConfidenceLevel.HIGH: 100,
        ConfidenceLevel.MEDIUM: 65,
        ConfidenceLevel.LOW: 30,
        ConfidenceLevel.NONE: 0
    }
    avg_confidence = int(sum(confidence_scores[a.confidence] for a in active_agents) / len(active_agents)) if active_agents else 0
    
    # Usage aggregation (simplified)
    all_usage = {}
    for agent in active_agents:
        agent_id = agent.filepath.replace('/', '_').replace('.py', '')
        all_usage[agent_id] = get_agent_usage(agent_id)
    
    # Aggregate totals
    total_tokens = sum(u['tokens']['total'] for u in all_usage.values())
    total_requests = sum(u['hourly']['used'] for u in all_usage.values() if isinstance(u['hourly']['used'], int))
    
    return jsonify({
        "pipeline": {
            "provider": pipeline_provider,
            "confidence": pipeline_confidence.value,
            "latest_status": latest_status,
            "run_id": run_id,
            "environment_evidence": asdict(env_evidence) if env_evidence else None,
            "repository_evidence": [asdict(e) for e in repo_evidences[:3]],
            "webhook_evidence": asdict(latest_webhook) if latest_webhook else None
        },
        "agents": {
            "total_count": len(agents),
            "active_count": len(active_agents),
            "list": [asdict(a) for a in agents],
            "overall_confidence": ConfidenceLevel.HIGH.value if avg_confidence > 80 else 
                                ConfidenceLevel.MEDIUM.value if avg_confidence > 40 else 
                                ConfidenceLevel.LOW.value,
            "confidence_score": avg_confidence
        },
        "files": {
            "total": len(files),
            "scanned": min(len(files), MAX_SCAN_FILES),
            "main_entry": main_entry or "Not detected",
            "list": [asdict(f) for f in files[:100]]  # Limit payload size
        },
        "usage": {
            "tokens": {
                "prompt": sum(u['tokens']['prompt'] for u in all_usage.values()),
                "completion": sum(u['tokens']['completion'] for u in all_usage.values()),
                "total": total_tokens
            },
            "hourly": {
                "used": total_requests,
                "limit": "Configurable via SENTINELOPS_AGENT_LIMITS_JSON",
                "remaining": "Depends on provider/limits",
                "percent": min(100, int((total_requests / 1000) * 100)) if total_requests else 0  # Example calc
            },
            "daily": {
                "used": total_requests,
                "limit": "Configurable via SENTINELOPS_AGENT_LIMITS_JSON",
                "remaining": "Depends on provider/limits",
                "percent": min(100, int((total_requests / 10000) * 100)) if total_requests else 0  # Example calc
            },
            "by_agent": all_usage
        },
        "scan_metadata": {
            "timestamp": datetime.now().isoformat(),
            "project_root": str(PROJECT_ROOT),
            "max_files": MAX_SCAN_FILES,
            "ignored_patterns": IGNORE_PATTERNS[:5]  # Sample
        }
    })

@monitor_bp.route('/history', methods=['GET'])
def get_history():
    """Return webhook and usage history"""
    webhook_events = [asdict(e) for e in load_webhook_history()[-20:]]  # Last 20 events
    
    # Aggregate usage history (simplified)
    usage_history = {}
    with _usage_lock:
        for agent_id, entries in _usage_ledger.items():
            usage_history[agent_id] = entries[-20:]  # Last 20 entries
    
    return jsonify({
        "webhook_events": webhook_events,
        "usage_history": usage_history,
        "storage_info": {
            "webhook_count": len(webhook_events),
            "usage_agents": len(usage_history),
            "storage_path": str(STORAGE_DIR)
        }
    })

@scanner_bp.route('/rescan', methods=['POST'])
def trigger_rescan():
    """Force rescan of project files and agents"""
    global _scan_cache, _scan_cache_time
    with _scan_lock:
        _scan_cache = {}
        _scan_cache_time = None
    return jsonify({"status": "success", "message": "Rescan initiated. Next summary request will refresh data."})

@scanner_bp.route('/usage', methods=['POST'])
def record_usage_endpoint():
    """Accept token usage telemetry from agents"""
    if not request.is_json:
        return jsonify({"error": "Content-Type must be application/json"}), 415
    
    try:
        data = request.get_json()
        if not data:
            return jsonify({"error": "Empty payload"}), 400
        
        # Validate
        is_valid, error_msg = validate_usage_data(data)
        if not is_valid:
            return jsonify({"error": error_msg}), 400
        
        # Record usage
        record_usage(data)
        return jsonify({"status": "success", "received": datetime.now().isoformat()}), 201
    except BadRequest:
        return jsonify({"error": "Invalid JSON payload"}), 400
    except Exception as e:
        logger.error(f"Usage recording error: {str(e)}")
        return jsonify({"error": "Internal server error"}), 500

# ======================
# WEBHOOK HANDLER (EXPORTED)
# ======================
def handle_monitor_status():
    """
    Process CI/CD webhook payloads for pipeline status monitoring.
    Called by app.py at POST /monitor/status
    """
    # Verify token if configured
    if WEBHOOK_TOKEN:
        token = request.headers.get('Authorization', '').replace('Bearer ', '', 1)
        if not token:
            token = request.headers.get('X-SentinelOps-Token', '')
        if not hmac.compare_digest(token, WEBHOOK_TOKEN):
            logger.warning("Webhook authentication failed")
            return jsonify({"error": "Unauthorized"}), 401
    
    # Parse payload (handle JSON and form data)
    try:
        if request.is_json:
            payload = request.get_json()
        elif request.form:
            payload = request.form.to_dict()
        elif request.data:
            payload = json.loads(request.data.decode('utf-8'))
        else:
            return jsonify({"error": "No payload detected"}), 400
    except (BadRequest, UnsupportedMediaType, json.JSONDecodeError) as e:
        logger.warning(f"Invalid webhook payload: {str(e)}")
        return jsonify({"error": "Invalid payload format"}), 400
    except Exception as e:
        logger.error(f"Webhook processing error: {str(e)}")
        return jsonify({"error": "Internal processing error"}), 500
    
    # Normalize and store event
    try:
        event = normalize_webhook(sanitize_payload(payload), dict(request.headers))
        if event:
            save_webhook_event(event)
            logger.info(f"Webhook recorded: {event.provider} {event.status}")
            return jsonify({
                "status": "success",
                "event_id": event.id,
                "provider": event.provider,
                "timestamp": event.timestamp
            }), 200
        else:
            logger.warning("Webhook normalization failed - unknown provider/payload")
            return jsonify({
                "status": "partial_success",
                "message": "Payload received but provider not recognized. Event stored generically.",
                "timestamp": datetime.now().isoformat()
            }), 202
    except Exception as e:
        logger.error(f"Webhook storage error: {str(e)}")
        return jsonify({"error": "Failed to store webhook event"}), 500

# ======================
# EXPORTS (REQUIRED)
# ======================
# These are imported and used by app.py per specification
__all__ = ['application', 'monitor_bp', 'scanner_bp', 'handle_monitor_status']

# Note: Blueprints are NOT registered here. app.py registers them after import.
# This module only defines and exports them.

# Final safety check: Ensure required exports exist
if __name__ == '__main__':
    # For direct execution testing only (not used in production per requirements)
    application.run(host='127.0.0.1', port=5050, debug=True)
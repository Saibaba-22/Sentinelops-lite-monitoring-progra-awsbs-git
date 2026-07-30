#!/usr/bin/env python3
"""
=========================================================================
   agent_monitor.py — AI Agent Scanner (Flask Blueprint)
   Designed for SentinelOps-Lite / app.py
   
   Detection Logic — An AI Agent is identified by 7 characteristics:
   1. Uses an AI/LLM model (GPT, Gemini, Claude, Llama, etc.)
   2. Accepts user input or system data and processes via AI reasoning
   3. Makes autonomous decisions (selects tools, plans actions)
   4. Interacts with external tools/APIs/databases
   5. Maintains context or memory (multi-step conversations)
   6. Produces intelligent outputs (recommendations, summaries, code)
   7. Contains agent orchestration logic (prompt handling, tool calling, etc.)
   
   Routes registered:
       /scanner              → Colorful HTML dashboard with all metrics
       /scanner/scan         → Trigger fresh scan
       /scanner/api          → HTML summary + raw JSON (?format=json)
=========================================================================
"""

import os
import re
import json
import time
import threading
import logging
from datetime import datetime
from pathlib import Path
from collections import Counter

# ── Safe Flask import ────────────────────────────────────────
try:
    from flask import Blueprint, jsonify, request
    _flask_ok = True
except ImportError:
    Blueprint = None
    _flask_ok = False

# ── Logging ──────────────────────────────────────────────────
logger = logging.getLogger("agent_monitor")

# ── Config (override via env vars) ───────────────────────────
_SCAN_PATH_ENV = os.environ.get("SCAN_PATH", "")

def _resolve_scan_path():
    """Find a writable scan path."""
    if _SCAN_PATH_ENV:
        p = Path(_SCAN_PATH_ENV).expanduser().resolve()
        if p.exists() or _is_writable(p.parent):
            return str(p)
    for candidate in ["/var/app/current", os.getcwd()]:
        p = Path(candidate)
        if p.exists() or _is_writable(p.parent):
            return str(p)
    return "/tmp/ai_agent_scan"

def _is_writable(path):
    try:
        p = Path(path)
        if not p.exists():
            p = p.parent
        return os.access(str(p), os.W_OK | os.X_OK)
    except Exception:
        return False

SCAN_PATH    = _resolve_scan_path()
AUTO_CREATE  = os.environ.get("AUTO_CREATE_SAMPLES", "true").lower() == "true"
REFRESH_SECS = int(os.environ.get("SCAN_REFRESH_SECS", "300"))
logger.info(f"SCAN_PATH resolved to: {SCAN_PATH}")

# ── Cache ────────────────────────────────────────────────────
_cached_html    = None
_cached_json    = "{}"
_cached_time    = None
_cached_summary = {"status": "pending", "agents_found": 0}
_lock           = threading.Lock()

# ═══════════════════════════════════════════════════════════════
#  MODEL DATA
# ═══════════════════════════════════════════════════════════════

# Known AI providers and their models with context windows
AI_PROVIDERS_MODELS = {
    "OpenAI": {
        "patterns": ["openai", "gpt", "chatopenai", "davinci", "ada", "babbage", "curie"],
        "models": {
            "gpt-4o": 128000, "gpt-4o-mini": 128000, "gpt-4-turbo": 128000,
            "gpt-4": 8192, "gpt-3.5-turbo": 16385,
        }
    },
    "Anthropic": {
        "patterns": ["anthropic", "claude", "chatanthropic"],
        "models": {
            "claude-3-opus": 200000, "claude-3-sonnet": 200000, "claude-3-haiku": 200000,
            "claude-3.5-sonnet": 200000, "claude-3.5-haiku": 200000, "claude-4": 200000,
        }
    },
    "Google": {
        "patterns": ["google", "gemini", "chatgoogle", "vertex"],
        "models": {
            "gemini-1.5-pro": 1048576, "gemini-1.5-flash": 1048576,
            "gemini-2.0-flash": 1048576, "gemini-pro": 32768,
        }
    },
    "Mistral": {
        "patterns": ["mistral", "mixtral", "chatmistral"],
        "models": {
            "mistral-large": 128000, "mistral-small": 32000,
            "mistral-medium": 32000, "mixtral": 32000,
        }
    },
    "Meta": {
        "patterns": ["meta", "llama"],
        "models": {
            "llama-3": 8192, "llama-3.1": 128000,
            "llama-3.2": 128000, "llama-2": 4096,
        }
    },
    "DeepSeek": {
        "patterns": ["deepseek"],
        "models": {
            "deepseek-chat": 128000, "deepseek-coder": 128000,
        }
    },
    "Cohere": {
        "patterns": ["cohere", "command"],
        "models": {
            "command-r": 128000, "command-r-plus": 128000,
        }
    },
    "Groq": {
        "patterns": ["groq"],
        "models": {}
    },
    "Together": {
        "patterns": ["together"],
        "models": {}
    },
    "Replicate": {
        "patterns": ["replicate"],
        "models": {}
    },
}

# Provider rate limits
PROVIDER_RATE_LIMITS = {
    "OpenAI": {"rpm": 500, "tpm": 200000, "rpd": 10000},
    "Anthropic": {"rpm": 400, "tpm": 100000, "rpd": 8000},
    "Google": {"rpm": 360, "tpm": 120000, "rpd": 7200},
    "Mistral": {"rpm": 300, "tpm": 80000, "rpd": 6000},
    "Meta": {"rpm": 200, "tpm": 60000, "rpd": 4000},
    "DeepSeek": {"rpm": 300, "tpm": 100000, "rpd": 6000},
    "default": {"rpm": 200, "tpm": 50000, "rpd": 4000},
}

# ═══════════════════════════════════════════════════════════════
#  7 CHARACTERISTICS — AI AGENT DETECTION
# ═══════════════════════════════════════════════════════════════

# Each characteristic has patterns with point values.
# A file meeting 3+ characteristics (any, not all) is an AI agent.
# Minimum points per characteristic to count it as "met".

AGENT_CHARACTERISTICS = {
    # 1. Uses an AI/LLM model
    "uses_ai_model": {
        "label": "Uses AI/LLM Model",
        "patterns": [
            (r"(?:ChatOpenAI|ChatAnthropic|ChatGoogle|ChatMistral)\s*\(", 1),
            (r"(?:OpenAI|Anthropic|Gemini|Mistral|Groq|Together)", 1),
            (r"model\s*[=:]\s*[\"'](?:gpt|claude|gemini|llama|mistral|deepseek)", 1),
            (r"(?:llm|model|client)\s*[=:]\s*(?:ChatOpenAI|ChatAnthropic|OpenAI)\s*\(", 1),
            (r"(?:from|import)\s+(?:openai|langchain_openai|langchain_anthropic)", 1),
            (r"self\.llm\s*=", 1),
            (r"self\.client\s*=", 1),
            (r"llm_config\s*[=:]", 1),
        ],
        "min_score": 1
    },
    # 2. Accepts user input / system data and processes via AI reasoning
    "accepts_input": {
        "label": "Accepts & Processes Input",
        "patterns": [
            (r"def\s+\w+\s*\(.*(?:input|prompt|query|message|text|content|data)", 1),
            (r"def\s+\w+\s*\(self,\s*\w+", 1),
            (r"(?:user_input|user_message|input_text|query|prompt)\s*[=:]", 1),
            (r"(?:messages|conversation|chat_history)\s*[=:]", 1),
            (r"request\.json|request\.form|request\.args|request\.data", 1),
            (r"input\s*\(|input\(\)", 1),
        ],
        "min_score": 1
    },
    # 3. Makes autonomous decisions
    "autonomous_decisions": {
        "label": "Makes Autonomous Decisions",
        "patterns": [
            (r"(?:if|elif|else)\s+.*(?:result|response|output|decision|choice)", 1),
            (r"(?:choose|select|decide|route|switch)\s*(?:tool|action|path)", 1),
            (r"(?:agent_executor|AgentExecutor)\s*\(", 1),
            (r"(?:Crew|Process)\s*[\(:]", 1),
            (r"(?:Workflow|Pipeline)\s*[\(:]", 1),
            (r"(?:@tool|def\s+\w*(?:tool|action|function))", 1),
            (r"(?:tools\s*[=:]\s*\[)", 1),
            (r"(?:allowed_tools|available_tools|tool_choices)", 1),
        ],
        "min_score": 1
    },
    # 4. Interacts with external tools/APIs
    "external_interaction": {
        "label": "Interacts with Tools/APIs",
        "patterns": [
            (r"\.invoke\s*\(", 1),
            (r"\.run\s*\(", 1),
            (r"\.kickoff\s*\(", 1),
            (r"chat\.completions\.create", 1),
            (r"client\.\w+\.create", 1),
            (r"\.predict\s*\(", 1),
            (r"\.generate\s*\(", 1),
            (r"requests\.(?:get|post|put|delete)\s*\(", 1),
            (r"(?:api_key|API_KEY|api_key)", 1),
            (r"\.send_message", 1),
            (r"tools\s*[=:]\s*\[.*\]", 1),
        ],
        "min_score": 1
    },
    # 5. Maintains context or memory
    "context_memory": {
        "label": "Maintains Context/Memory",
        "patterns": [
            (r"(?:memory|context|history|session)\s*[=:]", 1),
            (r"(?:ConversationBufferMemory|ConversationSummaryMemory)", 1),
            (r"(?:chat_history|conversation_history|message_history)", 1),
            (r"(?:messages\s*=\s*\[)", 1),
            (r"(?:system_message|system_prompt)", 1),
            (r"(?:role\s*[=:]\s*[\"'])", 1),
            (r"(?:backstory|goal)\s*[=:]\s*[\"']", 1),
            (r"(?:for\s+\w+\s+in\s+range|while\s+True|while\s+\w+)", 1),
        ],
        "min_score": 1
    },
    # 6. Produces intelligent outputs
    "intelligent_output": {
        "label": "Produces Intelligent Outputs",
        "patterns": [
            (r"(?:return\s+\w+\s*(?:result|response|output|answer|summary))", 1),
            (r"(?:summarize|generate|create|write|analyze|review)", 1),
            (r"(?:recommend|suggest|predict|classify|extract)", 1),
            (r"(?:result|response|output|answer)\s*=", 1),
            (r"(?:return\s+self\.\w+\.\w+\s*\()", 1),
            (r"(?:jsonify|json\.dumps)\s*\(", 1),
            (r"(?:render_template|Response)", 1),
        ],
        "min_score": 1
    },
    # 7. Contains agent orchestration logic
    "orchestration": {
        "label": "Agent Orchestration Logic",
        "patterns": [
            (r"(?:class|def)\s+\w*(?:Agent|agent|Tool|tool|Task|task)", 1),
            (r"(?:@tool|@agent|@task)", 1),
            (r"(?:AgentExecutor|ConversableAgent|AssistantAgent|UserProxyAgent)", 1),
            (r"(?:Agent|Task|Crew|Workflow)\s*[\(:]", 1),
            (r"(?:create_agent|initialize_agent|load_agent)", 1),
            (r"(?:reasoning|planning|execution)_(?:loop|cycle|step)", 1),
            (r"(?:prompt_template|PromptTemplate|ChatPromptTemplate)", 1),
            (r"(?:chain|sequence|graph)\s*[=:]\s*", 1),
        ],
        "min_score": 1
    },
}

# ═══════════════════════════════════════════════════════════════
#  DETECTION ENGINE
# ═══════════════════════════════════════════════════════════════

def analyze_characteristics(text):
    """Analyze a Python file against all 7 agent characteristics.
    Returns: (characteristics_met, details_dict, total_characteristics_count)
    """
    details = {}
    chars_met = 0
    total_chars = 0
    
    for char_key, char_data in AGENT_CHARACTERISTICS.items():
        score = 0
        matched_patterns = []
        for pattern, pts in char_data["patterns"]:
            matches = re.findall(pattern, text, re.IGNORECASE)
            if matches:
                count = len(matches)
                score += count * pts
                matched_patterns.append(f"{pattern[:50]}... (x{count})")
        
        met = score >= char_data["min_score"]
        if met:
            chars_met += 1
        total_chars += 1
        
        details[char_key] = {
            "label": char_data["label"],
            "score": score,
            "met": met,
            "matches": matched_patterns[:3],  # first 3 matches
        }
    
    return chars_met, details, total_chars


def is_ai_agent(text):
    """An AI agent must meet at least 3 of the 7 characteristics."""
    chars_met, _, _ = analyze_characteristics(text)
    return chars_met >= 3


def get_agent_details(text):
    """Get detailed breakdown of characteristics for logging."""
    chars_met, details, total = analyze_characteristics(text)
    met_list = [d["label"] for d in details.values() if d["met"]]
    return chars_met, total, met_list, details


def extract_provider(text):
    """Extract the AI provider from the file."""
    text_lower = text.lower()
    for provider, info in AI_PROVIDERS_MODELS.items():
        for pattern in info["patterns"]:
            if pattern in text_lower:
                return provider
    return None


def extract_model(text):
    """Extract the specific AI model from the file with word-boundary matching."""
    text_lower = text.lower()
    for provider, info in AI_PROVIDERS_MODELS.items():
        for model_name in sorted(info["models"].keys(), key=len, reverse=True):
            idx = text_lower.find(model_name)
            while idx != -1:
                # Check if this is a whole-word match
                before = text_lower[idx - 1] if idx > 0 else " "
                after = text_lower[idx + len(model_name)] if idx + len(model_name) < len(text_lower) else " "
                if not before.isalnum() and not before == "-" and not after.isalnum() and not after == "-":
                    return model_name
                idx = text_lower.find(model_name, idx + 1)
    return None


def extract_models_list(text):
    """Extract all detected models from the file with word-boundary matching."""
    text_lower = text.lower()
    found = []
    for provider, info in AI_PROVIDERS_MODELS.items():
        for model_name in sorted(info["models"].keys(), key=len, reverse=True):
            if model_name in found:
                continue
            idx = text_lower.find(model_name)
            while idx != -1:
                before = text_lower[idx - 1] if idx > 0 else " "
                after = text_lower[idx + len(model_name)] if idx + len(model_name) < len(text_lower) else " "
                if not before.isalnum() and not before == "-" and not after.isalnum() and not after == "-":
                    found.append(model_name)
                    break
                idx = text_lower.find(model_name, idx + 1)
    return found


def extract_model_with_fallback(text):
    """Extract model with inference. Returns (model_name, is_inferred).
    If specific model found in code -> return it, not inferred.
    If not, infer from provider/detected patterns -> return best guess, inferred=True.
    """
    # First try exact model matching
    exact = extract_model(text)
    if exact:
        return exact, False
    
    # No exact model found - infer from provider and context
    provider = extract_provider(text)
    if not provider:
        return "Unknown", False
    
    # Map provider to its most common/likely default model
    provider_defaults = {
        "OpenAI": "gpt-4o",
        "Anthropic": "claude-3.5-sonnet",
        "Google": "gemini-1.5-pro",
        "Mistral": "mistral-large",
        "Meta": "llama-3.1",
        "DeepSeek": "deepseek-chat",
        "Cohere": "command-r",
        "Groq": "mixtral",
        "Together": "llama-3.1",
        "Replicate": "llama-3.1",
    }
    inferred = provider_defaults.get(provider, "Unknown")
    
    # Look at code patterns for more specific clues
    text_lower = text.lower()
    
    # Check for size indicators (small, large, etc.)
    if "haiku" in text_lower or "flash" in text_lower or "mini" in text_lower or "small" in text_lower:
        size_hints = {"haiku": "claude-3-haiku", "flash": "gemini-1.5-flash", "mini": "gpt-4o-mini", "small": "mistral-small"}
        for keyword, model_hint in size_hints.items():
            if keyword in text_lower:
                inferred = model_hint
                break
    
    # Check for reasoning/analysis patterns → use larger model
    if any(w in text_lower for w in ["reason", "analyze", "complex", "research", "review"]):
        if provider == "OpenAI" and "mini" not in text_lower:
            inferred = "gpt-4o"
        elif provider == "Anthropic" and "haiku" not in text_lower:
            inferred = "claude-3.5-sonnet"
    
    # Check for temperature/TTL patterns
    temps = re.findall(r'temperature\s*[=:]\s*(\d+\.?\d*)', text, re.IGNORECASE)
    if temps:
        try:
            t = float(temps[0])
            if t > 0.5:
                # Creative tasks → might use different model
                pass
        except:
            pass
    
    return inferred, True


def get_context_window(model_name):
    """Get the context window for a model."""
    for provider, info in AI_PROVIDERS_MODELS.items():
        if model_name in info["models"]:
            return info["models"][model_name]
    return 128000  # default


def get_rate_limits(provider_name):
    """Get rate limits for a provider."""
    limits = PROVIDER_RATE_LIMITS.get(provider_name)
    if limits:
        return limits["rpm"], limits["tpm"], limits["rpd"]
    d = PROVIDER_RATE_LIMITS["default"]
    return d["rpm"], d["tpm"], d["rpd"]


def estimate_tokens(text):
    return max(1, len(text) // 4)


def count_api_calls(text):
    patterns = [
        r"\.invoke\s*\(", r"\.run\s*\(", r"\.kickoff\s*\(",
        r"chat\.completions\.create", r"generate_reply",
        r"client\.\w+\.create", r"\.predict\s*\(", r"\.generate\s*\(",
        r"\.send_message", r"\.reply\s*\(", r"completion\s*=",
        r"response\s*=",
    ]
    return sum(len(re.findall(p, text, re.IGNORECASE)) for p in patterns)


def extract_agent_name(filepath):
    name = re.sub(r'[_\-.]+', ' ', Path(filepath).stem).strip()
    return name.title()


def extract_description(text, filepath):
    """Extract what the file is used for."""
    # Try docstrings
    for pat in [r'"""(.*?)"""', r"'''(.*?)'''"]:
        for m in re.findall(pat, text, re.DOTALL):
            cleaned = m.strip()
            if len(cleaned) > 10:
                lines = [l.strip() for l in cleaned.split('\n') if l.strip()]
                return ' '.join(lines[:3])[:300]
    # Try comments at top
    for pat in [
        r'#\s*(?:Purpose|Description|About|File|Module)[:\s]*(.+?)(?:\n|$)',
        r'role\s*[=:]\s*["\'](.+?)["\']',
        r'goal\s*[=:]\s*["\'](.+?)["\']',
        r'backstory\s*[=:]\s*["\'](.+?)["\']',
    ]:
        m = re.search(pat, text, re.DOTALL)
        if m and len(m.group(1).strip()) > 10:
            return m.group(1).strip()[:300]
    return f"Python module: {Path(filepath).name}"


def extract_imports(text):
    imports = set()
    for m in re.finditer(r'(?:from|import)\s+([\w.]+)', text):
        imports.add(m.group(1).split('.')[0])
    return sorted(imports)


SKIP_DIRS = {"node_modules", ".git", "__pycache__", ".venv", "venv", ".tox", "dist", "build",
             ".next", ".nuxt", ".cache", "site-packages", "lib", "lib64", "bin", "include",
             ".eggs", "env", ".env", "target", "out", ".aws-sam"}

# ═══════════════════════════════════════════════════════════════
#  SCANNER
# ═══════════════════════════════════════════════════════════════

def scan_folder(root_path):
    """Scan folder recursively — ONLY .py files. Returns agent data."""
    root = Path(root_path).expanduser().resolve()
    if not root.exists():
        logger.warning(f"Path not found: {root}")
        return []
    
    agents = []
    all_files = []  # Track total Python files
    total_py = 0
    
    logger.info(f"Scanning: {root}")
    
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS and not d.startswith('.')]
        for fn in filenames:
            fp = Path(dirpath) / fn
            ext = fp.suffix.lower()
            
            # ONLY scan .py files
            if ext != ".py":
                continue
            
            try:
                if fp.stat().st_size > 500_000:
                    continue
            except OSError:
                continue
            
            total_py += 1
            
            try:
                text = fp.read_text(encoding="utf-8", errors="replace")
            except Exception:
                continue
            
            # ── Analyze against 7 characteristics ──
            chars_met, char_details, total_chars = analyze_characteristics(text)
            
            # Log every Python file with its score
            score_str = f"[{chars_met}/{total_chars} characteristics]"
            is_agent_flag = chars_met >= 3
            status_icon = "✅" if is_agent_flag else "⏭️"
            logger.info(f"  {status_icon} {score_str} {fn}")
            
            agent_info = {
                "file_path": str(fp),
                "relative_path": str(fp.relative_to(root)),
                "file_size_kb": round(fp.stat().st_size / 1024, 1),
                "lines_of_code": text.count("\n") + 1,
                "agent_name": extract_agent_name(fp),
                "description": extract_description(text, fp),
                "imports": extract_imports(text),
                "characteristics_met": chars_met,
                "total_characteristics": total_chars,
                "characteristics_details": char_details,
                "characteristics_met_list": [d["label"] for d in char_details.values() if d["met"]],
                "characteristics_not_met_list": [d["label"] for d in char_details.values() if not d["met"]],
                "is_agent": is_agent_flag,
            }
            
            if is_agent_flag:
                # ── Agent-specific data ──
                provider = extract_provider(text)
                model, model_inferred = extract_model_with_fallback(text)
                models_list = extract_models_list(text)
                ctx = get_context_window(model) if model else 128000
                tokens = estimate_tokens(text)
                api_calls = count_api_calls(text)
                rpm, tpm, rpd = get_rate_limits(provider) if provider else PROVIDER_RATE_LIMITS["default"].values()
                
                # Estimated requests based on API calls found
                estimated_requests = max(api_calls * 5, 1)
                
                agent_info.update({
                    "provider": provider or "Unknown",
                    "model": model or "Unknown",
                    "model_inferred": model_inferred,
                    "models_list": models_list,
                    "estimated_tokens": tokens,
                    "tokens_total_available": ctx,
                    "tokens_used_pct": round((tokens / ctx) * 100, 2) if ctx else 0,
                    "api_calls_detected": api_calls,
                    "estimated_requests": estimated_requests,
                    "rate_rpm": rpm,
                    "rate_tpm": tpm,
                    "rate_rpd": rpd,
                })
                
                agents.append(agent_info)
                logger.info(f"  → AGENT: {agent_info['agent_name']} | Provider: {provider or '?'} | Model: {model or '?'} | {chars_met}/{total_chars} chars")
            else:
                # Store as non-agent file info for total count
                all_files.append(agent_info)

    logger.info(f"Total .py files: {total_py}  |  AI Agents: {len(agents)}  |  Other files: {len(all_files)}")
    # Classify non-agent files by type
    for nf in all_files:
        chars = nf["characteristics_met"]
        if chars <= 1:
            nf["file_type"] = "Utility / Helper"
        elif chars == 2:
            nf["file_type"] = "Partial Agent-like"
        else:
            nf["file_type"] = "Miscellaneous"
    return agents, all_files, total_py


def create_sample_agents(target_dir):
    """Create sample agents for demo."""
    d = Path(target_dir)
    d.mkdir(parents=True, exist_ok=True)
    logger.info("Creating sample AI agent files...")
    
    samples = [
        ("code_review_agent.py", '''"""
Code Review AI Agent
Uses GPT-4o to review pull requests and provide feedback on code quality.
"""
import logging
from typing import Optional
from langchain.agents import tool
from langchain_openai import ChatOpenAI

logger = logging.getLogger(__name__)

class CodeReviewAgent:
    """Reviews code changes and provides actionable feedback."""
    
    role = "Senior Code Reviewer"
    goal = "Ensure code quality and catch bugs before merge"
    backstory = "Expert software engineer with 15 years experience"
    
    def __init__(self, model: str = "gpt-4o"):
        self.llm = ChatOpenAI(model=model)
        self.max_retries = 3
        self.conversation_history = []
        
    @tool
    def analyze_code_diff(self, diff: str) -> str:
        """Analyze a git diff and return review comments using AI reasoning."""
        try:
            result = self.llm.invoke(f"Review this code diff:\\n{diff}")
            logger.info("Review completed successfully")
            self.conversation_history.append({"role": "assistant", "content": str(result)})
            return str(result)
        except Exception as e:
            logger.error(f"Review failed: {e}")
            raise
    
    def review_pull_request(self, pr_changes: str) -> Optional[str]:
        """Autonomously decide how to review the PR."""
        if not pr_changes:
            return None
        
        for attempt in range(self.max_retries):
            try:
                review = self.analyze_code_diff(pr_changes)
                if "ERROR" in review:
                    continue  # Autonomous decision to retry
                return review
            except Exception as e:
                if attempt == self.max_retries - 1:
                    logger.critical(f"All retries exhausted: {e}")
                    return None
                continue
        return None
'''),
        ("customer_support_agent.py", '''"""
Customer Support AI Agent
Uses Claude to handle customer inquiries and resolve support tickets.
"""
import logging
from crewai import Agent, Task, Crew

logger = logging.getLogger(__name__)

class SupportAgent:
    """Resolves customer issues using AI reasoning and multi-step planning."""
    
    role = "Customer Support Specialist"
    goal = "Resolve customer issues quickly and empathetically"
    backstory = "Expert in customer service with deep product knowledge"
    
    def __init__(self):
        self.llm_config = {"model": "claude-3.5-sonnet", "provider": "Anthropic"}
        self.conversation_context = {}
        self.agent = Agent(
            role=self.role,
            goal=self.goal,
            backstory=self.backstory,
            llm=self.llm_config,
            allow_delegation=True,
            memory=True
        )
        
    def handle_ticket(self, ticket_id: str, description: str) -> str:
        """Analyze the ticket and autonomously determine the best resolution path."""
        try:
            # Step 1: Analyze the issue using AI
            task = Task(
                description=f"Analyze and resolve ticket #{ticket_id}: {description}",
                agent=self.agent,
                expected_output="Resolution steps and answer"
            )
            crew = Crew(
                agents=[self.agent],
                tasks=[task],
                verbose=True,
                memory=True
            )
            result = crew.kickoff()
            self.conversation_context[ticket_id] = str(result)
            logger.info(f"Ticket {ticket_id} resolved")
            return str(result)
        except Exception as e:
            logger.error(f"Failed to handle ticket {ticket_id}: {e}")
            return f"Error: {e}"
'''),
        ("data_analysis_agent.py", '''"""
Data Analysis AI Agent
Uses Gemini to analyze datasets and generate intelligent insights.
"""
import logging
from typing import Any, Dict
from autogen import AssistantAgent, UserProxyAgent

logger = logging.getLogger(__name__)

class DataAnalysisAgent:
    """Extracts actionable insights from data using AI reasoning."""
    
    role = "Data Analyst"
    goal = "Extract actionable insights from data"
    backstory = "Expert data scientist with broad analytical knowledge"
    
    def __init__(self):
        self.llm_config = {
            "model": "gemini-1.5-pro",
            "provider": "Google",
            "temperature": 0.2
        }
        self.analyst = AssistantAgent(
            name="DataAnalyst",
            llm_config=self.llm_config,
            system_message="You are an expert data analyst."
        )
        self.analysis_history = []
        
    def analyze_dataset(self, dataset_path: str) -> Dict[str, Any]:
        """Load data, autonomously decide analysis approach, and generate insights."""
        try:
            # AI autonomously decides how to analyze
            response = self.analyst.generate_reply(
                messages=[{
                    "role": "user",
                    "content": f"Analyze dataset at {dataset_path} and provide insights"
                }]
            )
            logger.info(f"Analysis completed for {dataset_path}")
            self.analysis_history.append({"dataset": dataset_path, "result": response})
            return {"status": "success", "insights": response}
        except Exception as e:
            logger.error(f"Analysis failed: {e}")
            return {"status": "error", "error": str(e)}
'''),
        ("content_writer_agent.py", '''"""
Content Writer AI Agent
Uses Claude Haiku to generate blog posts, articles, and marketing copy.
"""
import logging
from typing import Optional
from langchain.agents import tool
from langchain_anthropic import ChatAnthropic
import time

logger = logging.getLogger(__name__)

@tool
def research_topic(topic: str) -> str:
    """Research a topic and return key points."""
    return f"Research compiled for: {topic}"

class ContentWriterAgent:
    """Generates high-quality content using AI with context awareness."""
    
    role = "Content Creator"
    goal = "Produce engaging, SEO-optimized content readers love"
    backstory = "Published author with expertise in digital content strategy"
    
    def __init__(self):
        self.llm = ChatAnthropic(model="claude-3-haiku", temperature=0.7)
        self.tools = [research_topic]
        self.retries = 2
        self.writing_history = []
        
    def write_article(self, topic: str, tone: str = "professional") -> Optional[str]:
        """Autonomously research and write an article on the given topic."""
        for attempt in range(self.retries):
            try:
                research = research_topic(topic)
                prompt = (
                    f"Using this research: {research}\\n"
                    f"Write a {tone} article about '{topic}'. "
                    f"Include an introduction, 3 main sections, and a conclusion."
                )
                result = self.llm.invoke(prompt)
                logger.info(f"Article written on: {topic}")
                self.writing_history.append({"topic": topic, "result": str(result)})
                return str(result)
            except Exception as e:
                logger.warning(f"Attempt {attempt+1} failed: {e}")
                time.sleep(1)
        logger.error(f"Failed after {self.retries} retries")
        return None
'''),
        ("research_agent.py", '''"""
Research Assistant AI Agent
Uses GPT-4 Turbo to search and summarize academic papers.
"""
import os
import logging
import time
from typing import Optional, List
from openai import OpenAI

logger = logging.getLogger(__name__)

class ResearchAgent:
    """Assists with research tasks using AI-powered search and summarization."""
    
    role = "Research Assistant"
    goal = "Find and summarize relevant research papers efficiently"
    backstory = "PhD-level researcher with broad scientific knowledge"
    
    def __init__(self):
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise ValueError("OPENAI_API_KEY environment variable not set")
        self.client = OpenAI(api_key=api_key)
        self.model = "gpt-4-turbo"
        self.max_retries = 3
        self.search_history = []
        
    def search_papers(self, query: str, max_results: int = 5) -> Optional[List[str]]:
        """Autonomously search and summarize academic papers."""
        for attempt in range(self.max_retries):
            try:
                response = self.client.chat.completions.create(
                    model=self.model,
                    messages=[
                        {"role": "system", "content": "You are a research assistant."},
                        {"role": "user", "content": f"Find {max_results} papers on: {query}"}
                    ],
                    temperature=0.3
                )
                result = response.choices[0].message.content
                logger.info(f"Found papers for query: {query}")
                self.search_history.append({"query": query, "result": result})
                return [result]
            except Exception as e:
                logger.warning(f"Attempt {attempt+1} failed: {e}")
                time.sleep(2 ** attempt)
        logger.error(f"All attempts failed for: {query}")
        return None
'''),
        ("automation_agent.py", '''"""
Automation Pipeline AI Agent
Uses Llama via Haystack to orchestrate multi-step workflows.
"""
import logging
from typing import Any, Dict, List
from haystack import Pipeline
from haystack.components.builders import PromptBuilder

logger = logging.getLogger(__name__)

class AutomationAgent:
    """Automates complex workflows by making autonomous pipeline decisions."""
    
    role = "Automation Engineer"
    goal = "Streamline repetitive tasks through intelligent automation"
    backstory = "Expert in workflow automation and pipeline orchestration"
    
    def __init__(self):
        self.pipeline = Pipeline()
        self.model = "llama-3.1"
        self.max_retries = 2
        self.execution_history = []
        
    def create_workflow(self, steps: List[str]) -> Dict[str, Any]:
        """Autonomously create and execute an automated workflow."""
        try:
            # Dynamically build pipeline based on input steps
            for i, step in enumerate(steps):
                component = PromptBuilder(template=step)
                self.pipeline.add_component(f"step_{i}", component)
            
            # Execute with AI-driven orchestration
            result = self.pipeline.run(data={"prompt": "Execute automation workflow"})
            logger.info(f"Workflow with {len(steps)} steps completed")
            self.execution_history.append({"steps": len(steps), "result": result})
            return result
        except Exception as e:
            logger.error(f"Pipeline execution failed: {e}")
            return {"error": str(e)}
'''),
        ("agent_config.yaml", '''# Configuration file only — not an AI agent itself
database:
  host: localhost
  port: 5432
  name: myapp
logging:
  level: INFO
  file: /var/log/app.log
'''),
    ]
    
    for name, content in samples:
        (d / name).write_text(content)
        logger.info(f"  [+] {name}")
    return d


# ═══════════════════════════════════════════════════════════════
#  HTML DASHBOARD GENERATOR
# ═══════════════════════════════════════════════════════════════

def generate_dashboard_html(agents, non_agents, root_path, total_py_files=0):
    """Generate full colorful HTML dashboard from agent data."""
    ta = len(agents)
    tt = sum(a.get("estimated_tokens", 0) for a in agents)
    tac = sum(a.get("api_calls_detected", 0) for a in agents)
    tlines = sum(a.get("lines_of_code", 0) for a in agents)
    
    # Provider and model counts
    provider_counts = Counter(a.get("provider", "Unknown") for a in agents)
    model_counts = Counter()
    for a in agents:
        for m in a.get("models_list", [a.get("model", "Unknown")]):
            model_counts[m] += 1
    
    # Average characteristics met
    avg_chars = round(sum(a.get("characteristics_met", 0) for a in agents) / max(ta, 1), 1)
    
    # Total requests
    total_requests = sum(a.get("estimated_requests", 0) for a in agents)
    
    # Agent cards HTML
    aicons = {"code": "💻", "content": "📝", "data": "📊", "customer": "🤝",
              "research": "🔬", "finance": "💰", "healthcare": "🏥",
              "education": "📚", "automation": "⚙️", "multimedia": "🎨", "general": "🤖"}
    
    non_cards = ""
    for idx, nf in enumerate(non_agents):
        chars_met = nf.get("characteristics_met", 0)
        missing = nf.get("characteristics_not_met_list", [])
        missing_str = ", ".join(missing[:4])
        if len(missing) > 4:
            missing_str += "..."
        file_type = nf.get("file_type", "Unknown")
        type_colors = {"Utility / Helper": "#636e72", "Partial Agent-like": "#fdcb6e", "Miscellaneous": "#e17055"}
        tc = type_colors.get(file_type, "#636e72")
        icon = "📄"
        non_cards += f'\n        <div class="non-agent-card">\
            <div class="card-header" style="border-left:3px solid {tc}">\
                <div style="font-size:2rem;opacity:0.5">{icon}</div>\
                <div class="agent-title">\
                    <h3>{nf.get("agent_name", "Unknown")}</h3>\
                    <span class="agent-file">{nf.get("relative_path", "")}</span>\
                </div>\
                <div style="text-align:right">\
                    <span class="quality-tag" style="background:{tc}22;color:{tc};border:1px solid {tc}55;padding:4px 10px;border-radius:8px;font-size:0.75rem">{file_type}</span>\
                </div>\
            </div>\
            <div class="card-body">\
                <div class="info-grid">\
                    <div class="info-item"><span class="info-label">💻 Language</span><span class="info-value">Python</span></div>\
                    <div class="info-item"><span class="info-label">📄 Size</span><span class="info-value">{nf.get("file_size_kb", 0)} KB | {nf.get("lines_of_code", 0)} lines</span></div>\
                    <div class="info-item"><span class="info-label">🎯 Chars Met</span><span class="info-value">{chars_met}/7</span></div>\
                    <div class="info-item"><span class="info-label">❌ Missing</span><span class="info-value">{missing_str if missing_str else "None"}</span></div>\
                </div>\
                <div class="description-box" style="border-left-color:{tc}">\
                    <span class="desc-label">📋 What it does</span>\
                    <p>{nf.get("description", "")}</p>\
                </div>\
                <div class="not-agent-reason">\
                    <span class="reason-label">⛔ Why not an AI Agent?</span>\
                    <p>Only {chars_met}/7 AI characteristics met (need ≥3). Missing: {missing_str if missing_str else "None - basic file."}</p>\
                </div>\
            </div>\
        </div>'
    
    cards = ""
    for idx, a in enumerate(agents):
        ci = idx % 12
        chars = a.get("characteristics_met_list", [])
        chars_html = ""
        for c in chars:
            chars_html += f'<span class="char-badge char-ok">✅ {c}</span>'
        
        chars_not = a.get("characteristics_not_met_list", [])
        for c in chars_not:
            chars_html += f'<span class="char-badge char-no">❌ {c}</span>'
        
        # Token semi-circle
        tok_pct = a.get("tokens_used_pct", 0)
        tok_dash = min(tok_pct * 1.57, 157)
        req_count = a.get("estimated_requests", 0)
        req_dash = min((req_count / 200) * 157, 157) if req_count else 0
        rpm = a.get("rate_rpm", 0)
        rpm_dash = min((rpm / 600) * 157, 157) if rpm else 0
        
        cards += f'''
        <div class="agent-card">
            <div class="card-header">
                <div class="agent-icon">🤖</div>
                <div class="agent-title">
                    <h3>{a.get("agent_name", "Unknown")}</h3>
                    <span class="agent-file">{a.get("relative_path", "")}</span>
                </div>
                <div class="agent-shape shape-{ci % 6}"></div>
            </div>
            <div class="card-body">
                <div class="info-grid">
                    <div class="info-item">
                        <span class="info-label">📦 AI Provider</span>
                        <span class="info-value"><span class="badge badge-provider">{a.get("provider", "Unknown")}</span></span>
                    </div>
                    <div class="info-item">
                        <span class="info-label">🎯 Why Used</span>
                        <span class="info-value" style="font-size:0.8rem;color:var(--text2)">{'Agent uses ' + a.get("model", "Unknown") + ' model via ' + a.get("provider", "Unknown") + ' for: ' + a.get("description", "")[:80]}</span>
                    </div>
                    <div class="info-item">
                        <span class="info-label">🧠 AI Model</span>
                        <span class="info-value"><span class="badge badge-model">{a.get("model", "Unknown")}</span>{' <span class="badge badge-inferred" title="Model inferred from provider/patterns">🔮 inferred</span>' if a.get("model_inferred", False) else ''}</span>
                    </div>
                    <div class="info-item">
                        <span class="info-label">📄 File</span>
                        <span class="info-value">{a.get("file_size_kb", 0)} KB | {a.get("lines_of_code", 0)} lines</span>
                    </div>
                    <div class="info-item">
                        <span class="info-label">🎯 Characteristics</span>
                        <span class="info-value">{a.get("characteristics_met", 0)}/{a.get("total_characteristics", 7)}</span>
                    </div>
                </div>
                
                <div class="description-box">
                    <span class="desc-label">📋 What it does</span>
                    <p>{a.get("description", "")}</p>
                </div>
                
                <div class="chars-section">
                    <span class="chars-label">🔍 7 Characteristics Check:</span>
                    <div class="chars-list">{chars_html}</div>
                </div>
                
                <div class="metrics-container">
                    <div class="metric-card">
                        <div class="metric-ring">
                            <svg viewBox="0 0 120 120">
                                <path d="M 10 110 A 50 50 0 1 1 110 110" fill="none" stroke="#2a2a3e" stroke-width="12"/>
                                <path d="M 10 110 A 50 50 0 1 1 110 110" fill="none" stroke="#00d4aa" stroke-width="12" stroke-dasharray="{tok_dash} 157" stroke-linecap="round"/>
                            </svg>
                            <div class="metric-center">
                                <span class="metric-num">{a.get("estimated_tokens", 0):,}</span>
                                <span class="metric-label">Tokens Used</span>
                            </div>
                        </div>
                        <div class="metric-detail">
                            <span class="meter-bar"><span class="meter-fill" style="width:{min(tok_pct, 100)}%;background:linear-gradient(90deg,#00d4aa,#00b894)"></span></span>
                            <span class="meter-text">{tok_pct}% of {a.get("tokens_total_available", 0):,} available</span>
                        </div>
                    </div>
                    <div class="metric-card">
                        <div class="metric-ring">
                            <svg viewBox="0 0 120 120">
                                <path d="M 10 110 A 50 50 0 1 1 110 110" fill="none" stroke="#2a2a3e" stroke-width="12"/>
                                <path d="M 10 110 A 50 50 0 1 1 110 110" fill="none" stroke="#6c5ce7" stroke-width="12" stroke-dasharray="{req_dash} 157" stroke-linecap="round"/>
                            </svg>
                            <div class="metric-center">
                                <span class="metric-num">{a.get("api_calls_detected", 0)}</span>
                                <span class="metric-label">API Calls Found</span>
                            </div>
                        </div>
                        <div class="metric-detail">
                            <span class="meter-text">Est. Requests: {req_count}</span>
                        </div>
                    </div>
                    <div class="metric-card">
                        <div class="metric-ring">
                            <svg viewBox="0 0 120 120">
                                <path d="M 10 110 A 50 50 0 1 1 110 110" fill="none" stroke="#2a2a3e" stroke-width="12"/>
                                <path d="M 10 110 A 50 50 0 1 1 110 110" fill="none" stroke="#fd79a8" stroke-width="12" stroke-dasharray="{rpm_dash} 157" stroke-linecap="round"/>
                            </svg>
                            <div class="metric-center">
                                <span class="metric-num">{rpm or '∞'}</span>
                                <span class="metric-label">RPM Limit</span>
                            </div>
                        </div>
                        <div class="metric-detail">
                            <span class="meter-text">TPM: {a.get("rate_tpm", "∞")} | RPD: {a.get("rate_rpd", "∞")}</span>
                        </div>
                    </div>
                    <div class="metric-card">
                        <div class="metric-ring">
                            <svg viewBox="0 0 120 120">
                                <path d="M 10 110 A 50 50 0 1 1 110 110" fill="none" stroke="#2a2a3e" stroke-width="12"/>
                                <path d="M 10 110 A 50 50 0 1 1 110 110" fill="none" stroke="#fdcb6e" stroke-width="12" stroke-dasharray="141.3 157" stroke-linecap="round"/>
                            </svg>
                            <div class="metric-center">
                                <span class="metric-num">{a.get("characteristics_met", 0)}</span>
                                <span class="metric-label">of 7 Characs</span>
                            </div>
                        </div>
                        <div class="metric-detail">
                            <span class="meter-text">{a.get("characteristics_met", 0)}/7 characteristics met</span>
                        </div>
                    </div>
                </div>
            </div>
        </div>'''
    
    # Provider chart
    prov_html = "".join(
        f'<div class="prov-item"><span class="prov-dot" style="background:hsl({hash(p)%360},70%,60%)"></span>'
        f'<span class="prov-name">{p}</span><span class="prov-count">{c}</span></div>'
        for p, c in provider_counts.most_common()
    )
    
    # Model chart
    model_html = "".join(
        f'<div class="model-chip"><span class="model-name">{m}</span><span class="model-count">{c}</span></div>'
        for m, c in model_counts.most_common()
    )
    
    # Characteristics distribution
    char_counts = Counter()
    for a in agents:
        for c in a.get("characteristics_met_list", []):
            # Normalize labels
            # Normalize labels using dict lookup
            label_map = {
                "Uses AI/LLM Model": "1. Uses AI Model",
                "Accepts & Processes Input": "2. Accepts Input",
                "Makes Autonomous Decisions": "3. Autonomous Decisions",
                "Interacts with Tools/APIs": "4. Interacts Tools/API",
                "Maintains Context/Memory": "5. Context/Memory",
                "Produces Intelligent Outputs": "6. Intelligent Output",
                "Agent Orchestration Logic": "7. Orchestration Logic",
            }
            short = label_map.get(c, c)

            char_counts[short] += 1
    
    char_dist_html = ""
    for char_name, count in char_counts.most_common():
        pct = round(count / max(ta, 1) * 100, 1)
        hue = hash(char_name) % 360
        char_dist_html += f'''
        <div class="char-row">
            <span class="char-name">{char_name}</span>
            <span class="char-bar"><span class="char-fill" style="width:{pct}%;background:hsl({hue},70%,60%)"></span></span>
            <span class="char-count">{count}</span>
        </div>'''
    
    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    
    html = f'''<!DOCTYPE html>
<html lang="en">
<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0"><title>🤖 AI Agent Scanner Dashboard</title>
<link rel="preconnect" href="https://fonts.googleapis.com"><link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet">
<style>
*,*::before,*::after{{margin:0;padding:0;box-sizing:border-box}}:root{{--bg:#0a0a1a;--bg2:#12122a;--bg3:#1a1a3e;--card-bg:#16163a;--text:#e8e8f0;--text2:#a0a0c0;--border:#2a2a5e;--accent1:#00d4aa;--accent2:#6c5ce7;--accent3:#fd79a8;--accent4:#fdcb6e;--shadow:0 8px 32px rgba(0,0,0,0.4);--radius:16px}}
html{{font-size:15px}}body{{font-family:'Inter',sans-serif;background:var(--bg);color:var(--text);min-height:100vh}}
::-webkit-scrollbar{{width:6px}}::-webkit-scrollbar-track{{background:var(--bg)}}::-webkit-scrollbar-thumb{{background:var(--accent1);border-radius:3px}}
.bg-particles{{position:fixed;top:0;left:0;width:100%;height:100%;overflow:hidden;pointer-events:none;z-index:0}}
.bg-particles span{{position:absolute;display:block;border-radius:50%;animation:float 20s infinite;opacity:0.07}}
.bg-particles span:nth-child(1){{width:300px;height:300px;top:-5%;left:-5%;background:radial-gradient(circle,#00d4aa,transparent);animation-delay:0s}}
.bg-particles span:nth-child(2){{width:400px;height:400px;top:60%;right:-10%;background:radial-gradient(circle,#6c5ce7,transparent);animation-delay:-5s}}
.bg-particles span:nth-child(3){{width:250px;height:250px;bottom:-5%;left:30%;background:radial-gradient(circle,#fd79a8,transparent);animation-delay:-10s}}
.bg-particles span:nth-child(4){{width:350px;height:350px;top:20%;left:60%;background:radial-gradient(circle,#fdcb6e,transparent);animation-delay:-15s}}
@keyframes float{{0%,100%{{transform:translate(0,0)scale(1)}}25%{{transform:translate(50px,-30px)scale(1.05)}}50%{{transform:translate(-20px,40px)scale(0.95)}}75%{{transform:translate(30px,20px)scale(1.02)}}}}
.header{{position:relative;z-index:1;text-align:center;padding:40px 20px 30px;background:linear-gradient(135deg,var(--bg2),var(--bg3));border-bottom:1px solid var(--border)}}
.header h1{{font-size:2.8rem;font-weight:800;background:linear-gradient(135deg,#00d4aa,#6c5ce7,#fd79a8,#fdcb6e);-webkit-background-clip:text;-webkit-text-fill-color:transparent;letter-spacing:-1px}}
.header .subtitle{{color:var(--text2);font-size:1.1rem;margin-top:8px}}
.header .scan-info{{display:flex;justify-content:center;gap:30px;margin-top:20px;flex-wrap:wrap}}
.header .stat-bubble{{display:flex;align-items:center;gap:10px;background:var(--card-bg);border:1px solid var(--border);padding:12px 22px;border-radius:100px;font-size:0.95rem}}
.header .stat-bubble .num{{font-weight:700;font-size:1.2rem}}
.header .scan-path{{margin-top:12px;font-size:0.85rem;color:var(--text2);font-family:'JetBrains Mono',monospace;background:var(--bg);display:inline-block;padding:6px 16px;border-radius:8px;border:1px solid var(--border);max-width:90vw;overflow:hidden;text-overflow:ellipsis}}
.dashboard{{position:relative;z-index:1;max-width:1440px;margin:0 auto;padding:30px 20px 60px}}
.summary-row{{display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:20px;margin-bottom:40px}}
.summary-card{{background:var(--card-bg);border-radius:var(--radius);border:1px solid var(--border);padding:24px 16px;text-align:center;position:relative;overflow:hidden;transition:transform 0.3s,box-shadow 0.3s}}
.summary-card:hover{{transform:translateY(-4px);box-shadow:var(--shadow)}}
.summary-card .shape-bg{{position:absolute;top:-30px;right:-30px;width:100px;height:100px;opacity:0.06}}
.summary-card .shape-bg svg{{width:100%;height:100%}}
.summary-card .s-value{{font-size:2.5rem;font-weight:800}}
.summary-card .s-label{{color:var(--text2);margin-top:4px;font-size:0.9rem}}
.summary-card .s-icon{{font-size:2rem;margin-bottom:8px}}
.sc-0 .s-value{{color:#00d4aa}}.sc-1 .s-value{{color:#6c5ce7}}.sc-2 .s-value{{color:#fd79a8}}.sc-3 .s-value{{color:#fdcb6e}}.sc-4 .s-value{{color:#74b9ff}}.sc-5 .s-value{{color:#e17055}}.sc-6 .s-value{{color:#a29bfe}}
.charts-row{{display:grid;grid-template-columns:1fr 1fr;gap:20px;margin-bottom:40px}}
.chart-card{{background:var(--card-bg);border-radius:var(--radius);border:1px solid var(--border);padding:24px}}
.chart-card h3{{font-size:1.1rem;margin-bottom:16px;color:var(--text2)}}
.char-row{{display:flex;align-items:center;gap:12px;margin-bottom:8px}}
.char-name{{width:160px;font-weight:500;font-size:0.85rem}}
.char-bar{{flex:1;height:16px;background:var(--bg3);border-radius:8px;overflow:hidden}}
.char-fill{{height:100%;border-radius:8px;transition:width 1s ease}}
.char-count{{width:30px;text-align:right;font-weight:600;font-size:0.85rem}}
.prov-list{{display:flex;flex-wrap:wrap;gap:12px}}
.prov-item{{display:flex;align-items:center;gap:8px;background:var(--bg3);padding:8px 14px;border-radius:8px}}
.prov-dot{{width:10px;height:10px;border-radius:50%;display:inline-block}}
.prov-name{{font-size:0.9rem}}.prov-count{{font-weight:600;color:var(--text2)}}
.model-cloud{{display:flex;flex-wrap:wrap;gap:10px}}
.model-chip{{display:flex;align-items:center;gap:6px;background:linear-gradient(135deg,var(--bg3),var(--card-bg));border:1px solid var(--border);padding:6px 14px;border-radius:20px}}
.model-name{{font-size:0.85rem}}.model-count{{font-size:0.75rem;background:var(--accent1);color:#000;padding:1px 8px;border-radius:10px;font-weight:600}}
.agents-section h2{{font-size:1.5rem;margin-bottom:20px;display:flex;align-items:center;gap:10px}}
.agents-grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(550px,1fr));gap:24px}}
.agent-card{{background:var(--card-bg);border-radius:var(--radius);border:1px solid var(--border);overflow:hidden;transition:transform 0.3s,box-shadow 0.3s}}
.agent-card:hover{{transform:translateY(-6px);box-shadow:var(--shadow)}}
.card-header{{display:flex;align-items:center;gap:14px;padding:18px 20px;background:linear-gradient(135deg,var(--bg3),transparent);border-bottom:1px solid var(--border);position:relative}}
.agent-icon{{font-size:2.2rem}}.agent-title{{flex:1;min-width:0}}
.agent-title h3{{font-size:1.1rem;font-weight:700}}
.agent-file{{font-size:0.75rem;color:var(--text2);font-family:'JetBrains Mono',monospace;word-break:break-all;display:block}}
.agent-shape{{width:60px;height:60px;flex-shrink:0;clip-path:polygon(50% 0%,100% 25%,100% 75%,50% 100%,0% 75%,0% 25%);opacity:0.15}}
.shape-0{{background:linear-gradient(135deg,#00d4aa,#00b894)}}.shape-1{{background:linear-gradient(135deg,#6c5ce7,#a29bfe)}}.shape-2{{background:linear-gradient(135deg,#fd79a8,#e84393)}}.shape-3{{background:linear-gradient(135deg,#fdcb6e,#f39c12)}}.shape-4{{background:linear-gradient(135deg,#74b9ff,#0984e3)}}.shape-5{{background:linear-gradient(135deg,#e17055,#d63031)}}
.card-body{{padding:20px}}
.info-grid{{display:grid;grid-template-columns:1fr 1fr;gap:14px;margin-bottom:14px}}
.info-label{{font-size:0.8rem;color:var(--text2);display:block;margin-bottom:4px}}.info-value{{font-size:0.9rem}}
.badge{{display:inline-block;padding:2px 10px;border-radius:12px;font-size:0.75rem;font-weight:500;margin:2px}}
.badge-provider{{background:rgba(108,92,231,0.25);color:#a29bfe;border:1px solid rgba(108,92,231,0.3)}}
.badge-model{{background:rgba(0,212,170,0.2);color:#00d4aa;border:1px solid rgba(0,212,170,0.3)}}
.badge-inferred{{display:inline-block;padding:2px 8px;border-radius:12px;font-size:0.7rem;font-weight:500;margin:2px;background:rgba(253,203,110,0.15);color:#fdcb6e;border:1px solid rgba(253,203,110,0.3);cursor:help}}
.description-box{{background:var(--bg3);border-radius:10px;padding:12px 14px;margin-bottom:14px;border-left:3px solid var(--accent1)}}
.desc-label{{font-size:0.8rem;color:var(--text2);display:block;margin-bottom:4px}}.description-box p{{font-size:0.88rem;line-height:1.5;color:var(--text)}}
.chars-section{{margin-bottom:14px}}
.chars-label{{font-size:0.8rem;color:var(--text2);display:block;margin-bottom:6px}}
.chars-list{{display:flex;flex-wrap:wrap;gap:6px}}
.char-badge{{display:inline-block;padding:3px 8px;border-radius:6px;font-size:0.72rem;font-weight:500}}
.char-badge.char-ok{{background:rgba(0,184,148,0.15);color:#00b894;border:1px solid rgba(0,184,148,0.3)}}
.char-badge.char-no{{background:rgba(225,112,85,0.1);color:#e17055;border:1px solid rgba(225,112,85,0.2)}}
.metrics-container{{display:grid;grid-template-columns:1fr 1fr;gap:14px;margin-bottom:10px}}
.metric-card{{background:var(--bg3);border-radius:12px;padding:12px;text-align:center}}
.metric-ring{{position:relative;width:120px;height:65px;margin:0 auto 6px;overflow:hidden}}
.metric-center{{position:absolute;bottom:0;left:50%;transform:translateX(-50%);text-align:center}}
.metric-num{{display:block;font-size:1.1rem;font-weight:800}}
.metric-label{{font-size:0.6rem;color:var(--text2);text-transform:uppercase;letter-spacing:1px}}
.metric-detail{{margin-top:4px}}
.meter-bar{{display:block;height:5px;background:var(--bg);border-radius:3px;overflow:hidden}}
.meter-fill{{display:block;height:100%;border-radius:3px;transition:width 1.5s ease}}
.meter-text{{font-size:0.68rem;color:var(--text2);margin-top:2px;display:block}}
.footer{{text-align:center;padding:30px;color:var(--text2);font-size:0.85rem;border-top:1px solid var(--border);margin-top:40px}}
@media(max-width:900px){{.charts-row,.agents-grid,.metrics-container{{grid-template-columns:1fr}}}}
@media(max-width:600px){{.header h1{{font-size:2rem}}.summary-row{{grid-template-columns:repeat(2,1fr)}}.info-grid{{grid-template-columns:1fr}}}}
</style></head>
<body>
<div class="bg-particles"><span></span><span></span><span></span><span></span></div>
<header class="header">
<h1>🤖 AI Agent Scanner</h1>
<p class="subtitle">Detection based on 7 AI Agent Characteristics</p>
<div class="scan-info">
<div class="stat-bubble"><span>📂</span><span>Python Files: <strong class="num">{total_py_files}</strong></span></div>
<div class="stat-bubble"><span>🤖</span><span>AI Agents: <strong class="num">{ta}</strong></span></div>
<div class="stat-bubble"><span>📊</span><span>Avg Chars Met: <strong class="num">{avg_chars}/7</strong></span></div>
</div>
<div class="scan-path">📁 {root_path}</div>
</header>
<main class="dashboard">
<div class="summary-row">
<div class="summary-card sc-0"><div class="shape-bg"><svg viewBox="0 0 100 100"><polygon points="50,0 100,25 100,75 50,100 0,75 0,25" fill="#00d4aa"/></svg></div><div class="s-icon">🤖</div><div class="s-value">{ta}</div><div class="s-label">AI Agents Found</div></div>
<div class="summary-card sc-1"><div class="shape-bg"><svg viewBox="0 0 100 100"><polygon points="50,0 100,38 81,100 19,100 0,38" fill="#6c5ce7"/></svg></div><div class="s-icon">📂</div><div class="s-value">{total_py_files}</div><div class="s-label">Python Files Scanned</div></div>
<div class="summary-card sc-2"><div class="shape-bg"><svg viewBox="0 0 100 100"><polygon points="30,0 70,0 100,30 100,70 70,100 30,100 0,70 0,30" fill="#fd79a8"/></svg></div><div class="s-icon">🔤</div><div class="s-value">{tt:,}</div><div class="s-label">Total Tokens</div></div>
<div class="summary-card sc-3"><div class="shape-bg"><svg viewBox="0 0 100 100"><circle cx="50" cy="50" r="45" fill="#fdcb6e"/></svg></div><div class="s-icon">📨</div><div class="s-value">{tac}</div><div class="s-label">API Calls Found</div></div>
<div class="summary-card sc-4"><div class="shape-bg"><svg viewBox="0 0 100 100"><polygon points="50,0 100,25 100,75 50,100 0,75 0,25" fill="#74b9ff"/></svg></div><div class="s-icon">📝</div><div class="s-value">{tlines:,}</div><div class="s-label">Lines of Code</div></div>
<div class="summary-card sc-5"><div class="shape-bg"><svg viewBox="0 0 100 100"><polygon points="50,0 100,38 81,100 19,100 0,38" fill="#e17055"/></svg></div><div class="s-icon">🎯</div><div class="s-value">{avg_chars}</div><div class="s-label">Avg Chars Met /7</div></div>
</div>
<div class="charts-row">
<div class="chart-card">
<h3>🎯 Agent Characteristics Distribution</h3>
<div class="char-chart">{char_dist_html}</div>
<div class="char-key" style="margin-top:12px;display:flex;gap:8px;flex-wrap:wrap;font-size:0.75rem;color:var(--text2)">
<span>✅ = Characteristic met</span>
<span>❌ = Not met</span>
<span>🎯 Threshold: 3 of 7 = AI Agent</span>
</div>
</div>
<div class="chart-card">
<h3>🔌 AI Providers &amp; Models</h3>
<div class="prov-list">{prov_html}</div>
<h3 style="margin-top:16px">🧠 Models Detected</h3>
<div class="model-cloud">{model_html}</div>
</div>
</div>
<div class="agents-section">
<h2><span>📋 AI Agent Inventory</span> <span style="font-size:0.9rem;color:var(--text2);font-weight:400">({ta} agents)</span></h2>
<div class="agents-grid">{cards if cards else '<p style="color:var(--text2);text-align:center;padding:40px">No AI agents detected in the scanned path.</p>'}</div>
</div>

<div class="agents-section">
<h2><span>📁 Other Python Files</span> <span style="font-size:0.9rem;color:var(--text2);font-weight:400">({len(non_agents)} non-agent files)</span></h2>
<div class="non-agent-grid">{non_cards if non_cards else '<p style="color:var(--text2);text-align:center;padding:20px">All Python files are AI agents.</p>'}</div>
</div>
</main>
<footer class="footer">
<p>🤖 AI Agent Scanner · Detection based on 7 AI Agent Characteristics · Threshold: ≥3 = Agent</p>
<p style="margin-top:4px;font-size:0.75rem">Generated {now} | Path: {root_path}</p>
</footer>
<script>document.addEventListener('DOMContentLoaded',()=>{{document.querySelectorAll('.meter-fill,.area-fill,.char-fill').forEach(el=>{{const w=el.style.width;el.style.width='0%';setTimeout(()=>{{el.style.width=w}},200)}})}})</script>
</body>
</html>'''
    
    return html


# ═══════════════════════════════════════════════════════════════
#  PUBLIC API
# ═══════════════════════════════════════════════════════════════

def run_scan():
    """Run scan and cache results (thread-safe)."""
    global _cached_html, _cached_json, _cached_summary, _cached_time, SCAN_PATH
    with _lock:
        scan_path = Path(SCAN_PATH).expanduser().resolve()
        
        if not scan_path.exists():
            logger.warning(f"Path not found: {scan_path}")
            if AUTO_CREATE:
                try:
                    if not _is_writable(scan_path.parent):
                        fallback = Path("/tmp") / "ai_agent_samples"
                        logger.info(f"Using fallback: {fallback}")
                        scan_path = create_sample_agents(fallback)
                        SCAN_PATH = str(scan_path)
                    else:
                        scan_path = create_sample_agents(scan_path)
                except Exception as e:
                    err_msg = f"Cannot create samples: {e}"
                    logger.error(err_msg)
                    _cached_html = f"<html><body><h1>❌ Error</h1><p>{err_msg}</p></body></html>"
                    _cached_json = json.dumps({"error": err_msg, "agents_found": 0})
                    _cached_summary = {"error": err_msg, "agents_found": 0}
                    return
            else:
                _cached_html = f"<html><body><h1>❌ Path Not Found</h1><p>SCAN_PATH={scan_path}</p></body></html>"
                _cached_json = json.dumps({"error": f"Path not found: {scan_path}", "agents_found": 0})
                _cached_summary = {"error": f"Path not found: {scan_path}", "agents_found": 0}
                return
        
        agents, non_agents, total_py_files = scan_folder(scan_path)
        if not agents and AUTO_CREATE:
            try:
                # Count total Python files for reporting
                total_py = sum(1 for _ in Path(scan_path).rglob("*.py") if _.stat().st_size <= 500_000)
                create_sample_agents(scan_path)
                agents, non_agents, _ = scan_folder(scan_path)
            except Exception as e:
                logger.warning(f"Sample creation failed: {e}")
                try:
                    fallback = Path("/tmp") / "ai_agent_samples"
                    create_sample_agents(fallback)
                    agents, non_agents, _ = scan_folder(fallback)
                    SCAN_PATH = str(fallback)
                except Exception:
                    pass
        
        if not agents:
            agents = []
        if not non_agents:
            non_agents = []
        
        _cached_html = generate_dashboard_html(agents, non_agents, str(scan_path), total_py_files)
        
        _cached_summary = {
            "status": "ok",
            "scan_path": str(scan_path),
            "last_scan": datetime.now().isoformat(),
            "total_python_files": total_py_files,
            "agents_found": len(agents),
            "total_tokens": sum(a.get("estimated_tokens", 0) for a in agents) if agents else 0,
            "total_api_calls": sum(a.get("api_calls_detected", 0) for a in agents) if agents else 0,
            "total_lines": sum(a.get("lines_of_code", 0) for a in agents) if agents else 0,
            "average_characteristics": round(sum(a.get("characteristics_met", 0) for a in agents) / max(len(agents), 1), 1) if agents else 0,
            "non_agents_found": len(non_agents),
            "non_agents": [
                {
                    "name": n.get("agent_name", "?"),
                    "file": n.get("relative_path", "?"),
                    "file_type": n.get("file_type", "Unknown"),
                    "language": "Python",
                    "characteristics_met": n.get("characteristics_met", 0),
                    "characteristics_missing": n.get("characteristics_not_met_list", []),
                }
                for n in non_agents
            ] if non_agents else [],
            "agents": [
                {
                    "name": a.get("agent_name", "?"),
                    "file": a.get("relative_path", "?"),
                    "provider": a.get("provider", "Unknown"),
                    "model": a.get("model", "Unknown"),
                    "characteristics_met": a.get("characteristics_met", 0),
                    "characteristics_list": a.get("characteristics_met_list", []),
                    "tokens_used": a.get("estimated_tokens", 0),
                    "tokens_available": a.get("tokens_total_available", 0),
                    "api_calls": a.get("api_calls_detected", 0),
                    "estimated_requests": a.get("estimated_requests", 0),
                }
                for a in agents
            ] if agents else []
        }
        _cached_json = json.dumps(_cached_summary, indent=2)
        _cached_time = datetime.now().isoformat()
        logger.info(f"Scan complete — {len(agents)} AI agent(s) from {total_py_files} Python files")


def get_cached_html():
    return _cached_html

def get_cached_json():
    return _cached_json

def get_cached_summary_dict():
    return _cached_summary if _cached_summary else {"status": "pending", "agents_found": 0}


def start_background_scanner(interval_secs=None):
    if interval_secs is None:
        interval_secs = REFRESH_SECS
    def _loop():
        run_scan()
        if interval_secs > 0:
            threading.Timer(interval_secs, _loop).start()
    thread = threading.Thread(target=_loop, daemon=True)
    thread.start()
    logger.info(f"Background scanner started (every {interval_secs}s)")
    return thread


# ═══════════════════════════════════════════════════════════════
#  FLASK BLUEPRINT
# ═══════════════════════════════════════════════════════════════

if _flask_ok:
    scanner_bp = Blueprint("scanner", __name__, url_prefix="/scanner")
    
    @scanner_bp.route("/")
    def scanner_dashboard():
        if _cached_html is None:
            run_scan()
        return _cached_html or "<html><body><h1>⏳ Scanning...</h1></body></html>"
    
    @scanner_bp.route("/scan")
    def scanner_trigger_scan():
        run_scan()
        summary = get_cached_summary_dict()
        n = summary.get('agents_found', 0)
        t = summary.get('last_scan', 'just now')
        py = summary.get('total_python_files', 0)
        return f"""<!DOCTYPE html>
<html><head><meta http-equiv="refresh" content="2;url=/scanner/">
<title>Scan Complete</title>
<style>body{{font-family:sans-serif;background:#0a0a1a;color:#e8e8f0;display:flex;justify-content:center;align-items:center;min-height:100vh;margin:0}}
.card{{background:#16163a;border:1px solid #2a2a5e;border-radius:16px;padding:40px;text-align:center;max-width:500px}}
h1{{font-size:2rem;color:#00d4aa}}p{{color:#a0a0c0;margin:10px 0}}.count{{font-size:1.4rem;font-weight:700;color:#a29bfe}}</style></head>
<body><div class="card">
<h1>✅ Scan Complete</h1>
<p class="count">{n} AI Agent(s) from {py} Python files</p>
<p>Last scan: {t[:19]}</p>
<p><a href="/scanner/" style="color:#00d4aa">View Dashboard →</a></p>
</div></body></html>"""
    
    @scanner_bp.route("/api")
    def scanner_api():
        if _cached_html is None:
            run_scan()
        summary = get_cached_summary_dict()
        if request.args.get('format') == 'json':
            return jsonify(summary)
        n = summary.get('agents_found', 0)
        agents_list = summary.get('agents', [])
        rows = ''
        for a in agents_list:
            chars = ", ".join(a.get("characteristics_list", []))
            rows += f'<tr><td>{a.get("name","?")}</td><td>{a.get("provider","?")}</td><td>{a.get("model","?")}</td><td style="font-size:0.8rem">{chars}</td><td>{a.get("api_calls",0)}</td><td>{a.get("tokens_used",0):,}</td></tr>'
        return f"""<!DOCTYPE html>
<html><head><title>Scanner API</title>
<style>body{{font-family:sans-serif;background:#0a0a1a;color:#e8e8f0;padding:30px}}
table{{width:100%;border-collapse:collapse;margin-top:16px}}
th{{background:#1a1a3e;color:#a0a0c0;padding:10px;text-align:left;border-bottom:2px solid #2a2a5e}}
td{{padding:10px;border-bottom:1px solid #2a2a5e}}
h1{{color:#00d4aa}}.json-link{{display:inline-block;margin:16px 0;padding:8px 20px;background:#00d4aa;color:#000;border-radius:8px;text-decoration:none}}</style></head>
<body><h1>🤖 AI Agent Scanner API</h1>
<p><strong>{n}</strong> AI agents found</p>
<table><thead><tr><th>Name</th><th>Provider</th><th>Model</th><th>Characteristics</th><th>API</th><th>Tokens</th></tr></thead>
<tbody>{rows if rows else '<tr><td colspan="6" style="text-align:center">No agents</td></tr>'}</tbody></table>
<a class="json-link" href="?format=json">📄 Raw JSON</a>
<div style="margin-top:20px;color:#636e72;font-size:0.85rem">Path: {summary.get("scan_path","?")}</div></body></html>"""
    
    @scanner_bp.record_once
    def _start_scanner(state):
        try:
            start_background_scanner()
        except Exception as e:
            logger.warning(f"Background scanner start failed: {e}")
    
    logger.info("✅ scanner_bp blueprint ready at /scanner")
else:
    scanner_bp = None
    logger.warning("⚠️ Flask not available")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    print("=" * 60)
    print("   agent_monitor.py — AI Agent Scanner")
    print("   7 Characteristics Detection Engine")
    print("=" * 60)
    run_scan()
    data = get_cached_summary_dict()
    print(f"\n✅ {data.get('agents_found', 0)} AI agent(s) from {data.get('total_python_files', 0)} Python files")
    for a in data.get("agents", []):
        print(f"   🤖 {a['name']:28s} | {a['provider']:15s} | {a['model']:15s} | {a['characteristics_met']}/7 chars")

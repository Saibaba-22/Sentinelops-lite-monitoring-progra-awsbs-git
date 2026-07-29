#!/usr/bin/env python3
"""
AI Agent Scanner & Dashboard - REAL DATA VERSION
Scans folders, detects agents, reads ACTUAL usage from log files & env.
NO hardcoded or simulated values.
"""

import os
import re
import json
import ast
import time
import hashlib
import configparser
from datetime import datetime
from pathlib import Path
from http.server import HTTPServer, SimpleHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
import threading
import webbrowser

# ============================================================
# CONFIGURATION
# ============================================================
SCAN_ROOT = os.environ.get("SCAN_ROOT", ".")
SERVER_PORT = 8787

# ============================================================
# AI PROVIDER PATTERNS
# ============================================================
AI_PATTERNS = {
    "providers": {
        "OpenAI": {
            "imports": [
                r"import\s+openai", r"from\s+openai",
                r"OpenAI\s*\(", r"openai\.ChatCompletion",
                r"openai\.api_key", r"OPENAI_API_KEY",
                r"AsyncOpenAI\s*\(",
            ],
            "env_keys": ["OPENAI_API_KEY"],
            "models": [
                "gpt-4o", "gpt-4o-mini", "gpt-4-turbo",
                "gpt-4", "gpt-3.5-turbo", "o1-preview",
                "o1-mini", "dall-e-3", "dall-e-2",
                "whisper-1", "tts-1",
            ],
        },
        "Anthropic": {
            "imports": [
                r"import\s+anthropic", r"from\s+anthropic",
                r"Anthropic\s*\(", r"ANTHROPIC_API_KEY",
                r"AsyncAnthropic\s*\(",
            ],
            "env_keys": ["ANTHROPIC_API_KEY"],
            "models": [
                "claude-3-5-sonnet", "claude-3-5-haiku",
                "claude-3-opus", "claude-3-sonnet", "claude-3-haiku",
                "claude-2.1", "claude-2",
            ],
        },
        "Google AI": {
            "imports": [
                r"import\s+google\.generativeai",
                r"from\s+google\.generativeai",
                r"genai\.GenerativeModel", r"GOOGLE_API_KEY",
                r"import\s+vertexai", r"from\s+vertexai",
            ],
            "env_keys": ["GOOGLE_API_KEY", "GOOGLE_APPLICATION_CREDENTIALS"],
            "models": [
                "gemini-2.0-flash", "gemini-1.5-pro",
                "gemini-1.5-flash", "gemini-pro", "gemini-ultra",
            ],
        },
        "Hugging Face": {
            "imports": [
                r"from\s+transformers", r"import\s+transformers",
                r"pipeline\s*\(", r"AutoModel",
                r"from\s+huggingface_hub", r"HfApi",
            ],
            "env_keys": ["HUGGINGFACE_TOKEN", "HF_TOKEN"],
            "models": [
                "bert", "roberta", "distilbert", "t5",
                "falcon", "mistral", "mixtral", "phi",
                "stable-diffusion", "starcoder",
            ],
        },
        "Cohere": {
            "imports": [
                r"import\s+cohere", r"from\s+cohere",
                r"cohere\.Client", r"COHERE_API_KEY",
            ],
            "env_keys": ["COHERE_API_KEY"],
            "models": [
                "command-r-plus", "command-r", "command",
                "command-light", "embed-english",
            ],
        },
        "Mistral AI": {
            "imports": [
                r"from\s+mistralai", r"import\s+mistralai",
                r"MistralClient", r"MISTRAL_API_KEY",
                r"Mistral\s*\(",
            ],
            "env_keys": ["MISTRAL_API_KEY"],
            "models": [
                "mistral-large", "mistral-medium",
                "mistral-small", "mistral-tiny",
                "open-mistral-7b",
            ],
        },
        "Groq": {
            "imports": [
                r"import\s+groq", r"from\s+groq",
                r"Groq\s*\(", r"GROQ_API_KEY",
            ],
            "env_keys": ["GROQ_API_KEY"],
            "models": ["llama", "mixtral", "gemma", "whisper"],
        },
        "Ollama": {
            "imports": [
                r"import\s+ollama", r"from\s+ollama",
                r"ollama\.chat", r"ollama\.generate",
                r"localhost:11434",
            ],
            "env_keys": [],
            "models": [
                "llama2", "llama3", "mistral",
                "codellama", "phi", "gemma", "qwen",
            ],
        },
        "LangChain": {
            "imports": [
                r"from\s+langchain", r"import\s+langchain",
                r"LLMChain", r"AgentExecutor",
                r"create_react_agent", r"ChatOpenAI",
            ],
            "env_keys": [],
            "models": [],
        },
        "CrewAI": {
            "imports": [
                r"from\s+crewai", r"import\s+crewai",
                r"Agent\s*\(.*role\s*=", r"Crew\s*\(",
            ],
            "env_keys": [],
            "models": [],
        },
        "AutoGen": {
            "imports": [
                r"from\s+autogen", r"import\s+autogen",
                r"AssistantAgent", r"UserProxyAgent",
            ],
            "env_keys": [],
            "models": [],
        },
        "AWS Bedrock": {
            "imports": [
                r"bedrock-runtime", r"invoke_model",
                r"BedrockRuntime",
            ],
            "env_keys": ["AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY"],
            "models": [
                "amazon.titan", "anthropic.claude",
                "ai21.j2", "cohere.command",
            ],
        },
        "Azure OpenAI": {
            "imports": [
                r"AzureOpenAI\s*\(", r"azure_endpoint",
                r"AZURE_OPENAI",
            ],
            "env_keys": ["AZURE_OPENAI_API_KEY", "AZURE_OPENAI_ENDPOINT"],
            "models": ["gpt-4", "gpt-35-turbo"],
        },
    },
    "agent_frameworks": {
        "LangChain Agent": [
            r"AgentExecutor", r"create_react_agent",
            r"initialize_agent", r"AgentType",
        ],
        "CrewAI Agent": [
            r"from\s+crewai\s+import\s+Agent",
            r"Agent\s*\(.*role\s*=",
        ],
        "AutoGen Agent": [
            r"AssistantAgent\s*\(", r"UserProxyAgent\s*\(",
        ],
        "Custom Agent": [
            r"class\s+\w*[Aa]gent\w*\s*[\(:]",
            r"def\s+agent_", r"async\s+def\s+agent_",
        ],
    },
    "agent_areas": {
        "Chatbot / Conversational": [
            r"\bchat\b", r"\bconversation\b", r"\bchatbot\b",
            r"\bassistant\b", r"\bdialogue\b",
        ],
        "Code Generation": [
            r"\bcode[-_]?gen\b", r"\bcoding\b",
            r"\bcode[-_]?review\b", r"\brefactor\b",
        ],
        "Data Analysis": [
            r"\bpandas\b", r"\bdataframe\b",
            r"\bcsv\b", r"\banalyz\b", r"\breport\b",
        ],
        "Web Scraping": [
            r"\bscrape\b", r"\bcrawl\b",
            r"\bbeautifulsoup\b", r"\bselenium\b",
        ],
        "Image Generation": [
            r"\bdall[-_]?e\b", r"\bstable[-_]?diffusion\b",
            r"\bimage[-_]?gen\b",
        ],
        "Text Processing / NLP": [
            r"\bsummariz\b", r"\btranslat\b",
            r"\bsentiment\b", r"\bnlp\b", r"\bembed\b",
        ],
        "Email / Communication": [
            r"\bemail\b", r"\bsmtp\b",
            r"\bsendgrid\b", r"\bslack\b",
        ],
        "Database / Knowledge": [
            r"\bvector[-_]?store\b", r"\bchromadb\b",
            r"\bpinecone\b", r"\bfaiss\b", r"\brag\b",
        ],
        "DevOps / Automation": [
            r"\bdeploy\b", r"\bdocker\b",
            r"\bkubernetes\b", r"\bci[-_]?cd\b",
        ],
        "Research / Search": [
            r"\bsearch\b", r"\bresearch\b",
            r"\bwikipedia\b", r"\bserp\b",
        ],
        "Finance / Trading": [
            r"\btrading\b", r"\bstock\b",
            r"\bcrypto\b", r"\bfinance\b",
        ],
    },
}

# ============================================================
# LOG FILE PATTERNS - Real log file detection
# ============================================================
LOG_PATTERNS = {
    "openai_usage": [
        # OpenAI API response log format
        r'"usage":\s*\{[^}]*"prompt_tokens":\s*(\d+)[^}]*"completion_tokens":\s*(\d+)[^}]*"total_tokens":\s*(\d+)',
        r'"total_tokens":\s*(\d+)',
        r'prompt_tokens["\s:=]+(\d+)',
        r'completion_tokens["\s:=]+(\d+)',
    ],
    "request_success": [
        r'HTTP/\d\.\d"\s+200',
        r'"status":\s*200',
        r'"status":\s*"success"',
        r'status_code=200',
        r'✓|✅|SUCCESS|success',
    ],
    "request_failure": [
        r'HTTP/\d\.\d"\s+[45]\d\d',
        r'"status":\s*[45]\d\d',
        r'Error|ERROR|error|Exception|FAILED|failed',
        r'RateLimitError|APIError|AuthenticationError',
        r'status_code=[45]\d\d',
    ],
    "rate_limit": [
        r'rate.?limit|RateLimit|429',
        r'Too Many Requests',
        r'quota.?exceeded',
    ],
    "response_time": [
        r'response.?time[:\s=]+(\d+\.?\d*)\s*(ms|s)',
        r'elapsed[:\s=]+(\d+\.?\d*)',
        r'duration[:\s=]+(\d+\.?\d*)',
    ],
}

# ============================================================
# LOG FILE READER
# ============================================================
class LogFileReader:
    """Reads and parses REAL log files to extract usage data."""

    LOG_EXTENSIONS = {
        ".log", ".txt", ".json", ".jsonl",
        ".csv", ".out", ".err"
    }
    LOG_NAME_PATTERNS = [
        "*.log", "*.logs", "log_*", "*_log*",
        "usage*", "*usage*", "requests*",
        "*request*", "*api*", "agent*.log",
    ]

    def __init__(self, agent_script_path: str):
        self.agent_path = agent_script_path
        self.agent_dir = os.path.dirname(agent_script_path)
        self.agent_name = os.path.splitext(
            os.path.basename(agent_script_path)
        )[0]

    def find_log_files(self) -> list:
        """Find log files associated with this agent."""
        log_files = []
        search_dirs = [
            self.agent_dir,
            os.path.join(self.agent_dir, "logs"),
            os.path.join(self.agent_dir, "log"),
            os.path.join(self.agent_dir, ".."),
            os.path.join(self.agent_dir, "..", "logs"),
        ]

        for search_dir in search_dirs:
            if not os.path.isdir(search_dir):
                continue
            try:
                for fname in os.listdir(search_dir):
                    fpath = os.path.join(search_dir, fname)
                    if not os.path.isfile(fpath):
                        continue
                    ext = os.path.splitext(fname)[1].lower()
                    if ext not in self.LOG_EXTENSIONS:
                        continue
                    # Check if log file relates to this agent
                    name_lower = fname.lower()
                    agent_lower = self.agent_name.lower()
                    if (
                        agent_lower in name_lower or
                        "log" in name_lower or
                        "usage" in name_lower or
                        "request" in name_lower or
                        "api" in name_lower
                    ):
                        log_files.append(fpath)
            except PermissionError:
                continue

        return list(set(log_files))

    def parse_logs(self) -> dict:
        """Parse all found log files and extract real usage data."""
        log_files = self.find_log_files()

        result = {
            "log_files_found": log_files,
            "total_requests": 0,
            "successful_requests": 0,
            "failed_requests": 0,
            "tokens_used": 0,
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "failure_reasons": {},
            "response_times_ms": [],
            "avg_response_time_ms": None,
            "last_request_time": None,
            "data_source": "none",
        }

        if not log_files:
            result["data_source"] = "no_logs_found"
            return result

        result["data_source"] = "log_files"

        for log_file in log_files:
            self._parse_single_log(log_file, result)

        # Calculate averages
        if result["response_times_ms"]:
            result["avg_response_time_ms"] = round(
                sum(result["response_times_ms"]) / len(result["response_times_ms"]), 2
            )

        # Ensure consistency
        if result["total_requests"] == 0:
            total = result["successful_requests"] + result["failed_requests"]
            result["total_requests"] = total
        elif result["successful_requests"] == 0 and result["failed_requests"] == 0:
            result["failed_requests"] = 0
            result["successful_requests"] = result["total_requests"]

        return result

    def _parse_single_log(self, log_path: str, result: dict):
        """Parse a single log file."""
        try:
            file_size = os.path.getsize(log_path)
            if file_size > 50 * 1024 * 1024:  # Skip files > 50MB
                return
            if file_size == 0:
                return

            with open(log_path, "r", encoding="utf-8", errors="ignore") as f:
                content = f.read()

            # Try JSON/JSONL first
            if log_path.endswith(".jsonl"):
                self._parse_jsonl(content, result)
            elif log_path.endswith(".json"):
                self._parse_json_log(content, result)
            else:
                self._parse_text_log(content, result)

            # Extract last timestamp
            ts_patterns = [
                r'(\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2})',
                r'(\d{4}/\d{2}/\d{2} \d{2}:\d{2}:\d{2})',
            ]
            for pat in ts_patterns:
                matches = re.findall(pat, content)
                if matches:
                    result["last_request_time"] = matches[-1]
                    break

        except Exception:
            pass

    def _parse_jsonl(self, content: str, result: dict):
        """Parse JSONL format logs (one JSON per line)."""
        for line in content.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
                self._extract_from_json_entry(entry, result)
            except json.JSONDecodeError:
                pass

    def _parse_json_log(self, content: str, result: dict):
        """Parse JSON format logs."""
        try:
            data = json.loads(content)
            if isinstance(data, list):
                for entry in data:
                    if isinstance(entry, dict):
                        self._extract_from_json_entry(entry, result)
            elif isinstance(data, dict):
                self._extract_from_json_entry(data, result)
                # Check for nested arrays like {"requests": [...]}
                for key in ["requests", "events", "logs", "entries"]:
                    if key in data and isinstance(data[key], list):
                        for entry in data[key]:
                            self._extract_from_json_entry(entry, result)
        except json.JSONDecodeError:
            # Try parsing as text if JSON fails
            self._parse_text_log(content, result)

    def _extract_from_json_entry(self, entry: dict, result: dict):
        """Extract usage data from a JSON entry."""
        # Token counts
        usage = entry.get("usage", {})
        if isinstance(usage, dict):
            pt = usage.get("prompt_tokens", 0) or 0
            ct = usage.get("completion_tokens", 0) or 0
            tt = usage.get("total_tokens", 0) or 0
            result["prompt_tokens"] += pt
            result["completion_tokens"] += ct
            result["tokens_used"] += tt or (pt + ct)

        # Direct token fields
        for key in ["total_tokens", "tokens"]:
            val = entry.get(key)
            if isinstance(val, (int, float)) and val > 0:
                result["tokens_used"] += int(val)

        # Status
        status = entry.get("status") or entry.get("status_code")
        if status is not None:
            if str(status) in ("200", "success", "ok", "OK", "Success"):
                result["successful_requests"] += 1
                result["total_requests"] += 1
            elif str(status) in ("error", "failed", "fail") or (
                isinstance(status, int) and status >= 400
            ):
                result["failed_requests"] += 1
                result["total_requests"] += 1
                error_msg = (
                    entry.get("error") or
                    entry.get("message") or
                    entry.get("error_message") or
                    f"HTTP {status}"
                )
                if error_msg:
                    result["failure_reasons"][str(error_msg)] = (
                        result["failure_reasons"].get(str(error_msg), 0) + 1
                    )

        # Response time
        for rt_key in ["response_time", "duration", "elapsed", "latency"]:
            val = entry.get(rt_key)
            if isinstance(val, (int, float)) and val > 0:
                # Convert seconds to ms if needed
                rt = val * 1000 if val < 1000 else val
                result["response_times_ms"].append(round(rt, 2))
                break

        # Error messages
        error = entry.get("error") or entry.get("exception") or entry.get("err")
        if error and isinstance(error, str):
            result["failure_reasons"][error] = (
                result["failure_reasons"].get(error, 0) + 1
            )

    def _parse_text_log(self, content: str, result: dict):
        """Parse plain text log files."""
        lines = content.splitlines()

        for line in lines:
            # Token extraction
            token_match = re.search(
                r'"total_tokens":\s*(\d+)', line
            )
            if token_match:
                result["tokens_used"] += int(token_match.group(1))
                continue

            pt_match = re.search(r'prompt_tokens["\s:=]+(\d+)', line)
            ct_match = re.search(r'completion_tokens["\s:=]+(\d+)', line)
            if pt_match:
                result["prompt_tokens"] += int(pt_match.group(1))
            if ct_match:
                result["completion_tokens"] += int(ct_match.group(1))
            if pt_match or ct_match:
                pt = int(pt_match.group(1)) if pt_match else 0
                ct = int(ct_match.group(1)) if ct_match else 0
                result["tokens_used"] += pt + ct

            # Success patterns
            success = False
            for pat in LOG_PATTERNS["request_success"]:
                if re.search(pat, line, re.IGNORECASE):
                    success = True
                    break
            if success:
                result["successful_requests"] += 1
                result["total_requests"] += 1
                continue

            # Failure patterns
            for pat in LOG_PATTERNS["request_failure"]:
                if re.search(pat, line, re.IGNORECASE):
                    result["failed_requests"] += 1
                    result["total_requests"] += 1
                    # Extract reason
                    reason_match = re.search(
                        r'(Error|Exception|FAILED)[:\s]+([^\n]{5,80})',
                        line, re.IGNORECASE
                    )
                    if reason_match:
                        reason = reason_match.group(2).strip()
                        result["failure_reasons"][reason] = (
                            result["failure_reasons"].get(reason, 0) + 1
                        )
                    # Check for rate limit
                    for rl_pat in LOG_PATTERNS["rate_limit"]:
                        if re.search(rl_pat, line, re.IGNORECASE):
                            result["failure_reasons"]["Rate Limit (429)"] = (
                                result["failure_reasons"].get("Rate Limit (429)", 0) + 1
                            )
                    break

            # Response time
            rt_match = re.search(
                r'(?:response.time|elapsed|duration|latency)[:\s=]+(\d+\.?\d*)\s*(ms|s)?',
                line, re.IGNORECASE
            )
            if rt_match:
                val = float(rt_match.group(1))
                unit = rt_match.group(2) or "ms"
                rt_ms = val * 1000 if unit.lower() == "s" else val
                result["response_times_ms"].append(round(rt_ms, 2))


# ============================================================
# ENV & CONFIG READER
# ============================================================
class EnvConfigReader:
    """Reads real environment and config files for API settings."""

    def __init__(self, script_path: str, providers: list):
        self.script_path = script_path
        self.script_dir = os.path.dirname(script_path)
        self.providers = providers

    def read_api_keys_present(self) -> dict:
        """Check which API keys are actually set (not their values)."""
        found_keys = {}
        env_files = self._find_env_files()
        env_vars = self._load_all_env_vars(env_files)

        for provider in self.providers:
            info = AI_PATTERNS["providers"].get(provider, {})
            env_key_names = info.get("env_keys", [])
            for key_name in env_key_names:
                val = env_vars.get(key_name, "")
                if val and val not in ("your_key_here", "YOUR_KEY", "sk-xxx", ""):
                    found_keys[key_name] = True  # Only store presence, NOT value
                else:
                    found_keys[key_name] = False
        return found_keys

    def _find_env_files(self) -> list:
        """Find .env files near the script."""
        candidates = []
        search_dirs = [
            self.script_dir,
            os.path.join(self.script_dir, ".."),
            os.path.join(self.script_dir, "..", ".."),
            SCAN_ROOT,
        ]
        env_filenames = [".env", ".env.local", ".env.production", "config.env"]
        for d in search_dirs:
            for fname in env_filenames:
                p = os.path.join(d, fname)
                if os.path.isfile(p):
                    candidates.append(p)
        return list(set(candidates))

    def _load_all_env_vars(self, env_files: list) -> dict:
        """Load env vars from files + actual environment."""
        env_vars = dict(os.environ)  # Start with real environment
        for env_file in env_files:
            try:
                with open(env_file, "r", errors="ignore") as f:
                    for line in f:
                        line = line.strip()
                        if line and not line.startswith("#") and "=" in line:
                            key, _, val = line.partition("=")
                            env_vars[key.strip()] = val.strip().strip('"').strip("'")
            except Exception:
                pass
        return env_vars

    def read_config_files(self) -> dict:
        """Read config.json, config.yaml, settings.py for agent settings."""
        config = {}
        config_filenames = [
            "config.json", "settings.json", "config.yaml",
            "config.yml", "settings.yaml", "agent_config.json",
        ]
        for d in [self.script_dir, os.path.join(self.script_dir, "..")]:
            for fname in config_filenames:
                fpath = os.path.join(d, fname)
                if os.path.isfile(fpath):
                    try:
                        with open(fpath, "r") as f:
                            data = json.load(f)
                        config.update(data)
                    except Exception:
                        pass
        return config


# ============================================================
# SOURCE CODE ANALYZER
# ============================================================
class SourceCodeAnalyzer:
    """Analyzes Python/JS source files to extract real info."""

    def __init__(self, filepath: str, content: str):
        self.filepath = filepath
        self.content = content
        self.ext = os.path.splitext(filepath)[1].lower()

    def extract_description(self) -> str:
        """Extract real docstring or file comments."""
        # Module-level docstring (Python)
        docstring_match = re.search(
            r'^"""(.*?)"""', self.content, re.DOTALL
        )
        if docstring_match:
            desc = docstring_match.group(1).strip()
            # Take first 3 non-empty lines
            lines = [l.strip() for l in desc.split("\n") if l.strip()]
            return " ".join(lines[:3])[:250]

        docstring_match = re.search(
            r"^'''(.*?)'''", self.content, re.DOTALL
        )
        if docstring_match:
            desc = docstring_match.group(1).strip()
            lines = [l.strip() for l in desc.split("\n") if l.strip()]
            return " ".join(lines[:3])[:250]

        # File-level comments
        lines = self.content.split("\n")[:15]
        comments = []
        for line in lines:
            stripped = line.strip()
            if stripped.startswith(("//", "#")) and not stripped.startswith("#!"):
                comment = re.sub(r'^[/#\s]+', '', stripped).strip()
                if len(comment) > 8:
                    comments.append(comment)
        if comments:
            return " | ".join(comments[:2])[:250]

        # Fallback: filename-based
        name = os.path.splitext(os.path.basename(self.filepath))[0]
        return name.replace("_", " ").replace("-", " ").title()

    def detect_providers(self) -> list:
        """Detect AI providers from imports and usage."""
        found = []
        for provider, info in AI_PATTERNS["providers"].items():
            for pattern in info["imports"]:
                if re.search(pattern, self.content, re.IGNORECASE):
                    found.append(provider)
                    break
        return found

    def detect_models(self) -> list:
        """Detect AI model names from source code."""
        found = []
        for provider, info in AI_PATTERNS["providers"].items():
            for model in info.get("models", []):
                pattern = re.escape(model)
                if re.search(pattern, self.content, re.IGNORECASE):
                    if model not in found:
                        found.append(model)

        # Also search for quoted model strings
        model_quotes = re.findall(
            r'''(?:model\s*=\s*|"model"\s*:\s*)['"]([\w.:\-/]+)['"]''',
            self.content
        )
        for m in model_quotes:
            if len(m) > 3 and m not in found:
                found.append(m)

        return found

    def detect_frameworks(self) -> list:
        """Detect AI frameworks."""
        found = []
        for fw, patterns in AI_PATTERNS["agent_frameworks"].items():
            for pat in patterns:
                if re.search(pat, self.content, re.IGNORECASE):
                    found.append(fw)
                    break
        return found

    def detect_areas(self) -> list:
        """Detect working areas from code content."""
        found = []
        for area, patterns in AI_PATTERNS["agent_areas"].items():
            matches = sum(
                1 for p in patterns
                if re.search(p, self.content, re.IGNORECASE)
            )
            if matches >= 2:
                found.append(area)
        return found

    def extract_inline_usage(self) -> dict:
        """
        Extract usage data written directly in source code,
        e.g., comments or logging statements like:
        # tokens_used = 1500
        # requests_made = 200
        """
        usage = {}
        patterns_inline = {
            "tokens_used": r'#\s*tokens_used\s*[=:]\s*(\d+)',
            "total_requests": r'#\s*(?:total_)?requests\s*[=:]\s*(\d+)',
            "failed_requests": r'#\s*failed\s*[=:]\s*(\d+)',
            "rpm": r'#\s*rpm\s*[=:]\s*(\d+)',
            "tpm": r'#\s*tpm\s*[=:]\s*(\d+)',
        }
        for key, pat in patterns_inline.items():
            m = re.search(pat, self.content, re.IGNORECASE)
            if m:
                usage[key] = int(m.group(1))
        return usage

    def count_api_calls(self) -> int:
        """Count approximate number of API call sites in source."""
        api_call_patterns = [
            r'\.create\s*\(',
            r'\.generate\s*\(',
            r'\.chat\s*\(',
            r'\.complete\s*\(',
            r'\.messages\.create\s*\(',
            r'ollama\.generate\s*\(',
            r'ollama\.chat\s*\(',
            r'client\.chat\.completions\.create\s*\(',
        ]
        count = 0
        for pat in api_call_patterns:
            count += len(re.findall(pat, self.content))
        return count


# ============================================================
# MAIN SCANNER
# ============================================================
class AIAgentScanner:
    """
    Scans directories recursively to detect AI agents.
    Uses ONLY real data from source code, log files, and env vars.
    """

    SUPPORTED_EXTENSIONS = {".py", ".js", ".ts", ".jsx", ".tsx", ".mjs"}
    SKIP_DIRS = {
        "__pycache__", "node_modules", ".git", "venv",
        "env", ".venv", "dist", "build", ".next", ".nuxt",
    }

    def __init__(self, root_path: str):
        self.root_path = os.path.abspath(root_path)
        self.agents = []
        self.folder_tree = {}
        self.scan_stats = {
            "total_files_scanned": 0,
            "total_folders_scanned": 0,
            "total_agents_found": 0,
            "scan_start": None,
            "scan_end": None,
            "scan_duration_ms": 0,
            "root_path": self.root_path,
        }

    def scan(self) -> dict:
        """Run the full scan."""
        self.scan_stats["scan_start"] = datetime.now().isoformat()
        t0 = time.time()

        self.folder_tree = self._build_tree(self.root_path)
        self._scan_dir(self.root_path)

        elapsed = (time.time() - t0) * 1000
        self.scan_stats["scan_end"] = datetime.now().isoformat()
        self.scan_stats["scan_duration_ms"] = round(elapsed, 2)
        self.scan_stats["total_agents_found"] = len(self.agents)

        projects = self._group_into_projects()

        return {
            "scan_root": self.root_path,
            "scan_stats": self.scan_stats,
            "folder_tree": self.folder_tree,
            "agents": self.agents,
            "projects": projects,
            "summary": self._build_summary(projects),
        }

    # ----------------------------------------------------------
    # Folder tree
    # ----------------------------------------------------------
    def _build_tree(self, path: str, depth: int = 0) -> dict:
        node = {
            "name": os.path.basename(path) or path,
            "path": path,
            "type": "folder",
            "depth": depth,
            "children": [],
            "agent_count": 0,
        }
        self.scan_stats["total_folders_scanned"] += 1
        try:
            entries = sorted(os.listdir(path))
        except PermissionError:
            return node

        for entry in entries:
            full = os.path.join(path, entry)
            if os.path.isdir(full):
                if entry.startswith(".") or entry in self.SKIP_DIRS:
                    continue
                node["children"].append(self._build_tree(full, depth + 1))
            elif os.path.isfile(full):
                ext = os.path.splitext(entry)[1].lower()
                if ext in self.SUPPORTED_EXTENSIONS:
                    node["children"].append({
                        "name": entry, "path": full,
                        "type": "file", "depth": depth + 1,
                    })
        return node

    def _mark_agent_in_tree(self, tree: dict, filepath: str):
        """Mark files that are agents in the tree."""
        if tree["type"] == "file" and tree["path"] == filepath:
            tree["is_agent"] = True
        elif tree["type"] == "folder":
            if filepath.startswith(tree["path"]):
                tree["agent_count"] += 1
                for child in tree.get("children", []):
                    self._mark_agent_in_tree(child, filepath)

    # ----------------------------------------------------------
    # Directory scan
    # ----------------------------------------------------------
    def _scan_dir(self, path: str):
        try:
            entries = os.listdir(path)
        except PermissionError:
            return
        for entry in entries:
            full = os.path.join(path, entry)
            if os.path.isdir(full):
                if entry.startswith(".") or entry in self.SKIP_DIRS:
                    continue
                self._scan_dir(full)
            elif os.path.isfile(full):
                ext = os.path.splitext(entry)[1].lower()
                if ext in self.SUPPORTED_EXTENSIONS:
                    self.scan_stats["total_files_scanned"] += 1
                    self._analyze_file(full)

    def _analyze_file(self, filepath: str):
        """Analyze one file - extract REAL data only."""
        try:
            with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
                content = f.read()
        except Exception:
            return

        if len(content.strip()) < 20:
            return

        analyzer = SourceCodeAnalyzer(filepath, content)
        providers = analyzer.detect_providers()
        frameworks = analyzer.detect_frameworks()

        # Only process if AI-related
        if not providers and not frameworks:
            return

        models = analyzer.detect_models()
        areas = analyzer.detect_areas()
        description = analyzer.extract_description()
        api_call_count = analyzer.count_api_calls()
        inline_usage = analyzer.extract_inline_usage()

        # Read real log data
        log_reader = LogFileReader(filepath)
        log_data = log_reader.parse_logs()

        # Read env/config
        env_reader = EnvConfigReader(filepath, providers)
        api_keys_present = env_reader.read_api_keys_present()
        config_data = env_reader.read_config_files()

        # Merge inline usage annotations if log has no data
        if log_data["total_requests"] == 0 and inline_usage:
            log_data.update(inline_usage)
            log_data["data_source"] = "inline_annotations"

        # Build usage stats - NO random values
        usage = self._build_usage(log_data, providers, config_data)

        agent_info = {
            "id": hashlib.md5(filepath.encode()).hexdigest()[:12],
            "script_name": os.path.basename(filepath),
            "script_path": filepath,
            "relative_path": os.path.relpath(filepath, self.root_path),
            "folder": os.path.dirname(
                os.path.relpath(filepath, self.root_path)
            ),
            "providers": providers if providers else [],
            "models": models if models else ["Not specified in code"],
            "frameworks": frameworks if frameworks else ["Direct API"],
            "areas": areas if areas else ["General Purpose"],
            "description": description,
            "file_size_bytes": os.path.getsize(filepath),
            "lines_of_code": content.count("\n") + 1,
            "api_call_sites": api_call_count,
            "last_modified": datetime.fromtimestamp(
                os.path.getmtime(filepath)
            ).isoformat(),
            "api_keys_present": api_keys_present,
            "config": config_data,
            "usage": usage,
        }

        self.agents.append(agent_info)
        self._mark_agent_in_tree(self.folder_tree, filepath)

    def _build_usage(
        self,
        log_data: dict,
        providers: list,
        config_data: dict,
    ) -> dict:
        """
        Build usage dict from REAL log data only.
        Shows null/unknown for anything we couldn't find.
        """
        total = log_data.get("total_requests", 0)
        success = log_data.get("successful_requests", 0)
        failed = log_data.get("failed_requests", 0)
        tokens = log_data.get("tokens_used", 0)

        # Success rate
        if total > 0:
            success_rate = round((success / total) * 100, 1)
        else:
            success_rate = None  # Unknown, not assumed

        # Rate limits: only from config or env
        rpm = config_data.get("rpm") or config_data.get("rate_limit_rpm")
        tpm = config_data.get("tpm") or config_data.get("rate_limit_tpm")
        rpd = config_data.get("rpd") or config_data.get("rate_limit_rpd")
        token_limit = (
            config_data.get("token_limit") or
            config_data.get("max_tokens_total")
        )

        tokens_pct = None
        if tokens and token_limit:
            tokens_pct = round((tokens / token_limit) * 100, 1)

        return {
            "data_source": log_data.get("data_source", "none"),
            "log_files_found": log_data.get("log_files_found", []),
            "total_requests": total if total > 0 else None,
            "successful_requests": success if success > 0 else None,
            "failed_requests": failed,
            "success_rate": success_rate,
            "tokens_used": tokens if tokens > 0 else None,
            "prompt_tokens": log_data.get("prompt_tokens") or None,
            "completion_tokens": log_data.get("completion_tokens") or None,
            "tokens_available": token_limit,
            "tokens_percentage": tokens_pct,
            "rpm": rpm,
            "tpm": tpm,
            "rpd": rpd,
            "rpm_used": None,  # Can't know without live monitoring
            "tpm_used": None,
            "rpd_used": None,
            "failure_reasons": log_data.get("failure_reasons", {}),
            "avg_response_time_ms": log_data.get("avg_response_time_ms"),
            "last_request_time": log_data.get("last_request_time"),
        }

    # ----------------------------------------------------------
    # Project grouping
    # ----------------------------------------------------------
    def _group_into_projects(self) -> list:
        projects = {}
        for agent in self.agents:
            parts = agent["folder"].replace("\\", "/").split("/")
            top = parts[0] if parts and parts[0] not in (".", "") else "Root"
            projects.setdefault(top, []).append(agent)

        result = []
        for name, agents in projects.items():
            total_req = sum(
                a["usage"]["total_requests"] or 0 for a in agents
            )
            total_success = sum(
                a["usage"]["successful_requests"] or 0 for a in agents
            )
            total_failed = sum(
                a["usage"]["failed_requests"] or 0 for a in agents
            )
            total_tokens = sum(
                a["usage"]["tokens_used"] or 0 for a in agents
            )
            result.append({
                "project_name": name,
                "agent_count": len(agents),
                "agents": agents,
                "providers_used": list(
                    {p for a in agents for p in a["providers"]}
                ),
                "models_used": list(
                    {m for a in agents for m in a["models"]}
                ),
                "total_requests": total_req or None,
                "total_tokens": total_tokens or None,
                "total_success": total_success or None,
                "total_failed": total_failed,
            })
        return result

    # ----------------------------------------------------------
    # Summary
    # ----------------------------------------------------------
    def _build_summary(self, projects: list) -> dict:
        providers_cnt: dict = {}
        area_cnt: dict = {}
        model_cnt: dict = {}
        total_req = 0
        total_success = 0
        total_failed = 0
        total_tokens = 0
        all_failure_reasons: dict = {}

        for a in self.agents:
            for p in a["providers"]:
                providers_cnt[p] = providers_cnt.get(p, 0) + 1
            for ar in a["areas"]:
                area_cnt[ar] = area_cnt.get(ar, 0) + 1
            for m in a["models"]:
                model_cnt[m] = model_cnt.get(m, 0) + 1
            u = a["usage"]
            total_req += u.get("total_requests") or 0
            total_success += u.get("successful_requests") or 0
            total_failed += u.get("failed_requests") or 0
            total_tokens += u.get("tokens_used") or 0
            for reason, cnt in u.get("failure_reasons", {}).items():
                all_failure_reasons[reason] = (
                    all_failure_reasons.get(reason, 0) + cnt
                )

        return {
            "total_agents": len(self.agents),
            "total_projects": len(projects),
            "providers_breakdown": providers_cnt,
            "area_breakdown": area_cnt,
            "model_breakdown": model_cnt,
            "overall_usage": {
                "total_requests": total_req or None,
                "total_successful": total_success or None,
                "total_failed": total_failed,
                "overall_success_rate": (
                    round(total_success / total_req * 100, 1)
                    if total_req > 0 else None
                ),
                "total_tokens_used": total_tokens or None,
                "failure_reason_breakdown": all_failure_reasons,
            },
        }


# ============================================================
# HTTP SERVER (Same as before)
# ============================================================
class DashboardHandler(SimpleHTTPRequestHandler):
    scan_results = None

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path in ("/", "/dashboard"):
            self._serve_dashboard()
        elif parsed.path == "/api/scan":
            self._serve_json(DashboardHandler.scan_results)
        elif parsed.path == "/api/rescan":
            params = parse_qs(parsed.query)
            root = params.get("path", [SCAN_ROOT])[0]
            scanner = AIAgentScanner(root)
            DashboardHandler.scan_results = scanner.scan()
            self._serve_json(DashboardHandler.scan_results)
        else:
            super().do_GET()

    def _serve_dashboard(self):
        tmpl = os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            "templates", "dashboard.html"
        )
        try:
            with open(tmpl, "r", encoding="utf-8") as f:
                html = f.read()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(html.encode("utf-8"))
        except FileNotFoundError:
            self.send_response(404)
            self.end_headers()
            self.wfile.write(b"dashboard.html not found in templates/")

    def _serve_json(self, data):
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(
            json.dumps(data, indent=2, default=str).encode("utf-8")
        )

    def log_message(self, fmt, *args):
        pass


# ============================================================
# MAIN
# ============================================================
def main():
    print("\n" + "=" * 60)
    print("🤖  AI AGENT SCANNER - REAL DATA VERSION")
    print("=" * 60)
    print("\n✅ No hardcoded usage values")
    print("✅ No random/simulated statistics")
    print("✅ Real data from: source code, log files, env vars\n")

    scan_root = SCAN_ROOT
    print(f"🔍 Scanning: {os.path.abspath(scan_root)}")
    scanner = AIAgentScanner(scan_root)
    results = scanner.scan()
    DashboardHandler.scan_results = results

    s = results["scan_stats"]
    sum_ = results["summary"]
    print(f"\n📊 Scan Complete!")
    print(f"   📂 Folders: {s['total_folders_scanned']}")
    print(f"   📄 Files:   {s['total_files_scanned']}")
    print(f"   🤖 Agents:  {s['total_agents_found']}")
    print(f"   ⏱️  Time:    {s['scan_duration_ms']}ms")

    for i, agent in enumerate(results["agents"], 1):
        u = agent["usage"]
        data_src = u.get("data_source", "none")
        has_real_data = data_src not in ("none", "no_logs_found")
        print(f"\n  {i}. {agent['script_name']}")
        print(f"     📍 {agent['relative_path']}")
        print(f"     🏢 {', '.join(agent['providers'])}")
        print(f"     🧠 {', '.join(agent['models'][:3])}")
        print(f"     📊 Data: {'✅ Real logs' if has_real_data else '⚠️  No logs found'}")
        if u.get("total_requests"):
            print(f"     📡 Requests: {u['total_requests']} (✅{u['successful_requests']} / ❌{u['failed_requests']})")
        if u.get("tokens_used"):
            print(f"     🪙 Tokens: {u['tokens_used']}")

    print(f"\n🌐 Dashboard: http://localhost:{SERVER_PORT}")
    print("   Press Ctrl+C to stop.\n")

    threading.Timer(1.5, lambda: webbrowser.open(
        f"http://localhost:{SERVER_PORT}"
    )).start()

    server = HTTPServer(("", SERVER_PORT), DashboardHandler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n👋 Stopped.")
        server.server_close()


if __name__ == "__main__":
    main()
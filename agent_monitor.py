#!/usr/bin/env python3
"""
AI Agent Scanner & Dashboard - SINGLE FILE
Scans folders recursively, detects AI agents, serves colorful dashboard.
Works on: Local Python, AWS Beanstalk, Docker, any WSGI server.

Usage:
    python app.py                          # Scan current directory
    SCAN_ROOT=/path/to/project python app.py   # Scan specific path
    gunicorn app:application               # Production WSGI
"""

import os
import re
import json
import time
import hashlib
import threading
from datetime import datetime
from io import BytesIO

# ============================================================
# Try Flask first, fallback to built-in server
# ============================================================
try:
    from flask import Flask, jsonify, request, Response
    USE_FLASK = True
except ImportError:
    USE_FLASK = False

# ============================================================
# CONFIGURATION
# ============================================================
SCAN_ROOT = os.environ.get("SCAN_ROOT", ".")
SERVER_PORT = int(os.environ.get("PORT", 8787))

# ============================================================
# AI DETECTION PATTERNS
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
                "gpt-4o", "gpt-4o-mini", "gpt-4-turbo", "gpt-4",
                "gpt-3.5-turbo", "gpt-3.5", "o1-preview", "o1-mini",
                "o3-mini", "dall-e-3", "dall-e-2", "whisper-1",
                "tts-1", "tts-1-hd", "text-embedding-ada",
                "text-embedding-3-small", "text-embedding-3-large",
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
                "claude-2.1", "claude-2", "claude-instant",
            ],
        },
        "Google AI": {
            "imports": [
                r"import\s+google\.generativeai",
                r"from\s+google\.generativeai",
                r"genai\.GenerativeModel", r"GOOGLE_API_KEY",
                r"import\s+vertexai", r"from\s+vertexai",
                r"GenerativeModel\s*\(",
            ],
            "env_keys": ["GOOGLE_API_KEY", "GOOGLE_APPLICATION_CREDENTIALS"],
            "models": [
                "gemini-2.0-flash", "gemini-1.5-pro",
                "gemini-1.5-flash", "gemini-pro", "gemini-ultra",
                "palm-2", "text-bison",
            ],
        },
        "Hugging Face": {
            "imports": [
                r"from\s+transformers", r"import\s+transformers",
                r"pipeline\s*\(", r"AutoModel",
                r"from\s+huggingface_hub", r"HfApi",
                r"HUGGINGFACE_TOKEN", r"HF_TOKEN",
            ],
            "env_keys": ["HUGGINGFACE_TOKEN", "HF_TOKEN"],
            "models": [
                "bert", "roberta", "distilbert", "t5",
                "falcon", "mistral", "mixtral", "phi",
                "stable-diffusion", "starcoder", "gpt2",
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
                "open-mistral", "codestral",
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
                r"ChatAnthropic", r"ConversationChain",
            ],
            "env_keys": [],
            "models": [],
        },
        "CrewAI": {
            "imports": [
                r"from\s+crewai", r"import\s+crewai",
                r"Agent\s*\(.*role\s*=", r"Crew\s*\(",
                r"Task\s*\(.*description",
            ],
            "env_keys": [],
            "models": [],
        },
        "AutoGen": {
            "imports": [
                r"from\s+autogen", r"import\s+autogen",
                r"AssistantAgent", r"UserProxyAgent",
                r"GroupChat",
            ],
            "env_keys": [],
            "models": [],
        },
        "AWS Bedrock": {
            "imports": [
                r"bedrock-runtime", r"invoke_model",
                r"BedrockRuntime",
            ],
            "env_keys": ["AWS_ACCESS_KEY_ID"],
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
        "Replicate": {
            "imports": [
                r"import\s+replicate", r"from\s+replicate",
                r"replicate\.run", r"REPLICATE_API_TOKEN",
            ],
            "env_keys": ["REPLICATE_API_TOKEN"],
            "models": [],
        },
    },
    "agent_frameworks": {
        "LangChain Agent": [
            r"AgentExecutor", r"create_react_agent",
            r"initialize_agent", r"AgentType",
            r"create_openai_functions_agent",
        ],
        "CrewAI Agent": [
            r"from\s+crewai\s+import\s+Agent",
            r"Agent\s*\(.*role\s*=",
        ],
        "AutoGen Agent": [
            r"AssistantAgent\s*\(",
            r"UserProxyAgent\s*\(",
        ],
        "Custom Agent": [
            r"class\s+\w*[Aa]gent\w*\s*[\(:]",
            r"def\s+agent_",
            r"async\s+def\s+agent_",
        ],
    },
    "agent_areas": {
        "Chatbot / Conversational": [
            r"\bchat\b", r"\bconversation\b",
            r"\bchatbot\b", r"\bassistant\b", r"\bdialogue\b",
        ],
        "Code Generation": [
            r"\bcode[-_]?gen", r"\bcoding\b",
            r"\bcode[-_]?review\b", r"\brefactor\b", r"\bprogrammer\b",
        ],
        "Data Analysis": [
            r"\bpandas\b", r"\bdataframe\b",
            r"\bcsv\b", r"\banalyz", r"\breport\b",
        ],
        "Web Scraping": [
            r"\bscrape\b", r"\bcrawl\b",
            r"\bbeautifulsoup\b", r"\bselenium\b",
        ],
        "Image Generation": [
            r"\bdall[-_]?e\b", r"\bstable[-_]?diffusion\b",
            r"\bimage[-_]?gen", r"\bmidjourney\b",
        ],
        "Text Processing / NLP": [
            r"\bsummariz", r"\btranslat",
            r"\bsentiment\b", r"\bnlp\b", r"\bembed",
        ],
        "Email / Communication": [
            r"\bemail\b", r"\bsmtp\b",
            r"\bsendgrid\b", r"\bslack\b", r"\bnotification\b",
        ],
        "RAG / Knowledge Base": [
            r"\bvector[-_]?store\b", r"\bchromadb\b",
            r"\bpinecone\b", r"\bfaiss\b", r"\brag\b", r"\bretrieval\b",
        ],
        "DevOps / Automation": [
            r"\bdeploy\b", r"\bdocker\b",
            r"\bkubernetes\b", r"\bci[-_]?cd\b", r"\bautomat",
        ],
        "Research / Search": [
            r"\bsearch\b", r"\bresearch\b",
            r"\bwikipedia\b", r"\bserp\b",
        ],
        "Finance / Trading": [
            r"\btrading\b", r"\bstock\b",
            r"\bcrypto\b", r"\bfinance\b", r"\bportfolio\b",
        ],
        "Healthcare": [
            r"\bmedical\b", r"\bhealth\b",
            r"\bdiagnosis\b", r"\bpatient\b", r"\bclinical\b",
        ],
    },
}

LOG_PATTERNS = {
    "request_success": [
        r'HTTP/\d\.\d"\s+200', r'"status":\s*200',
        r'"status":\s*"success"', r'status_code=200',
    ],
    "request_failure": [
        r'HTTP/\d\.\d"\s+[45]\d\d', r'"status":\s*[45]\d\d',
        r'Error|ERROR|Exception|FAILED',
        r'RateLimitError|APIError|AuthenticationError',
    ],
}


# ============================================================
# LOG FILE READER
# ============================================================
class LogFileReader:
    LOG_EXTENSIONS = {".log", ".txt", ".json", ".jsonl", ".csv", ".out"}

    def __init__(self, agent_script_path):
        self.agent_dir = os.path.dirname(agent_script_path)
        self.agent_name = os.path.splitext(os.path.basename(agent_script_path))[0]

    def find_log_files(self):
        log_files = []
        search_dirs = [
            self.agent_dir,
            os.path.join(self.agent_dir, "logs"),
            os.path.join(self.agent_dir, "log"),
            os.path.join(self.agent_dir, ".."),
            os.path.join(self.agent_dir, "..", "logs"),
        ]
        for d in search_dirs:
            if not os.path.isdir(d):
                continue
            try:
                for fname in os.listdir(d):
                    fpath = os.path.join(d, fname)
                    if not os.path.isfile(fpath):
                        continue
                    ext = os.path.splitext(fname)[1].lower()
                    if ext not in self.LOG_EXTENSIONS:
                        continue
                    nl = fname.lower()
                    if any(k in nl for k in [self.agent_name.lower(), "log", "usage", "request", "api"]):
                        log_files.append(fpath)
            except PermissionError:
                pass
        return list(set(log_files))

    def parse_logs(self):
        log_files = self.find_log_files()
        result = {
            "log_files_found": [os.path.basename(f) for f in log_files],
            "total_requests": 0, "successful_requests": 0,
            "failed_requests": 0, "tokens_used": 0,
            "prompt_tokens": 0, "completion_tokens": 0,
            "failure_reasons": {}, "response_times_ms": [],
            "avg_response_time_ms": None, "last_request_time": None,
            "data_source": "no_logs_found" if not log_files else "log_files",
        }
        for lf in log_files:
            self._parse_file(lf, result)

        if result["response_times_ms"]:
            result["avg_response_time_ms"] = round(
                sum(result["response_times_ms"]) / len(result["response_times_ms"]), 2
            )
        t = result["successful_requests"] + result["failed_requests"]
        if t > result["total_requests"]:
            result["total_requests"] = t
        return result

    def _parse_file(self, path, result):
        try:
            sz = os.path.getsize(path)
            if sz > 50 * 1024 * 1024 or sz == 0:
                return
            with open(path, "r", encoding="utf-8", errors="ignore") as f:
                content = f.read()
            if path.endswith(".jsonl"):
                for line in content.splitlines():
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        self._extract_json(json.loads(line), result)
                    except json.JSONDecodeError:
                        pass
            elif path.endswith(".json"):
                try:
                    data = json.loads(content)
                    if isinstance(data, list):
                        for e in data:
                            if isinstance(e, dict):
                                self._extract_json(e, result)
                    elif isinstance(data, dict):
                        self._extract_json(data, result)
                        for k in ["requests", "events", "logs", "entries"]:
                            if k in data and isinstance(data[k], list):
                                for e in data[k]:
                                    if isinstance(e, dict):
                                        self._extract_json(e, result)
                except json.JSONDecodeError:
                    self._parse_text(content, result)
            else:
                self._parse_text(content, result)

            ts = re.findall(r'(\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2})', content)
            if ts:
                result["last_request_time"] = ts[-1]
        except Exception:
            pass

    def _extract_json(self, entry, result):
        usage = entry.get("usage", {})
        if isinstance(usage, dict):
            pt = usage.get("prompt_tokens", 0) or 0
            ct = usage.get("completion_tokens", 0) or 0
            tt = usage.get("total_tokens", 0) or 0
            result["prompt_tokens"] += pt
            result["completion_tokens"] += ct
            result["tokens_used"] += tt or (pt + ct)

        status = entry.get("status") or entry.get("status_code")
        if status is not None:
            s = str(status)
            if s in ("200", "success", "ok", "OK", "Success"):
                result["successful_requests"] += 1
                result["total_requests"] += 1
            elif s in ("error", "failed") or (isinstance(status, int) and status >= 400):
                result["failed_requests"] += 1
                result["total_requests"] += 1
                err = entry.get("error") or entry.get("message") or f"HTTP {status}"
                if err:
                    result["failure_reasons"][str(err)] = result["failure_reasons"].get(str(err), 0) + 1

        for rk in ["response_time", "duration", "elapsed", "latency"]:
            v = entry.get(rk)
            if isinstance(v, (int, float)) and v > 0:
                result["response_times_ms"].append(round(v * 1000 if v < 100 else v, 2))
                break

    def _parse_text(self, content, result):
        for line in content.splitlines():
            m = re.search(r'"total_tokens":\s*(\d+)', line)
            if m:
                result["tokens_used"] += int(m.group(1))
                continue
            pt = re.search(r'prompt_tokens["\s:=]+(\d+)', line)
            ct = re.search(r'completion_tokens["\s:=]+(\d+)', line)
            if pt:
                result["prompt_tokens"] += int(pt.group(1))
            if ct:
                result["completion_tokens"] += int(ct.group(1))
            if pt or ct:
                result["tokens_used"] += (int(pt.group(1)) if pt else 0) + (int(ct.group(1)) if ct else 0)
                continue

            if any(re.search(p, line, re.IGNORECASE) for p in LOG_PATTERNS["request_success"]):
                result["successful_requests"] += 1
                result["total_requests"] += 1
                continue

            if any(re.search(p, line, re.IGNORECASE) for p in LOG_PATTERNS["request_failure"]):
                result["failed_requests"] += 1
                result["total_requests"] += 1
                rm = re.search(r'(Error|Exception|FAILED)[:\s]+([^\n]{5,80})', line, re.IGNORECASE)
                if rm:
                    result["failure_reasons"][rm.group(2).strip()] = result["failure_reasons"].get(rm.group(2).strip(), 0) + 1

            rt = re.search(r'(?:response.time|elapsed|duration|latency)[:\s=]+(\d+\.?\d*)\s*(ms|s)?', line, re.IGNORECASE)
            if rt:
                v = float(rt.group(1))
                ms = v * 1000 if (rt.group(2) or "ms").lower() == "s" else v
                result["response_times_ms"].append(round(ms, 2))


# ============================================================
# ENV CONFIG READER
# ============================================================
class EnvConfigReader:
    def __init__(self, script_path, providers):
        self.script_dir = os.path.dirname(script_path)
        self.providers = providers

    def read_api_keys_present(self):
        env_vars = self._load_env()
        found = {}
        for prov in self.providers:
            info = AI_PATTERNS["providers"].get(prov, {})
            for key in info.get("env_keys", []):
                v = env_vars.get(key, "")
                found[key] = bool(v and v not in ("your_key_here", "YOUR_KEY", "sk-xxx", ""))
        return found

    def read_config(self):
        config = {}
        for d in [self.script_dir, os.path.join(self.script_dir, "..")]:
            for fname in ["config.json", "settings.json", "agent_config.json"]:
                fpath = os.path.join(d, fname)
                if os.path.isfile(fpath):
                    try:
                        with open(fpath) as f:
                            config.update(json.load(f))
                    except Exception:
                        pass
        return config

    def _load_env(self):
        env = dict(os.environ)
        for d in [self.script_dir, os.path.join(self.script_dir, ".."), os.path.join(self.script_dir, "..", "..")]:
            for fname in [".env", ".env.local", "config.env"]:
                p = os.path.join(d, fname)
                if os.path.isfile(p):
                    try:
                        with open(p, "r", errors="ignore") as f:
                            for line in f:
                                line = line.strip()
                                if line and not line.startswith("#") and "=" in line:
                                    k, _, v = line.partition("=")
                                    env[k.strip()] = v.strip().strip('"').strip("'")
                    except Exception:
                        pass
        return env


# ============================================================
# SOURCE CODE ANALYZER
# ============================================================
class SourceCodeAnalyzer:
    def __init__(self, filepath, content):
        self.filepath = filepath
        self.content = content

    def extract_description(self):
        for pat in [r'^"""(.*?)"""', r"^'''(.*?)'''"]:
            m = re.search(pat, self.content, re.DOTALL)
            if m:
                desc = m.group(1).strip()
                lines = [l.strip() for l in desc.split("\n") if l.strip()]
                return " ".join(lines[:3])[:250]
        lines = self.content.split("\n")[:15]
        comments = []
        for line in lines:
            s = line.strip()
            if s.startswith(("//", "#")) and not s.startswith("#!"):
                c = re.sub(r'^[/#\s]+', '', s).strip()
                if len(c) > 8:
                    comments.append(c)
        if comments:
            return " | ".join(comments[:2])[:250]
        name = os.path.splitext(os.path.basename(self.filepath))[0]
        return name.replace("_", " ").replace("-", " ").title()

    def detect_providers(self):
        found = []
        for prov, info in AI_PATTERNS["providers"].items():
            for pat in info["imports"]:
                if re.search(pat, self.content, re.IGNORECASE):
                    found.append(prov)
                    break
        return found

    def detect_models(self):
        found = []
        for prov, info in AI_PATTERNS["providers"].items():
            for model in info.get("models", []):
                if re.search(re.escape(model), self.content, re.IGNORECASE):
                    if model not in found:
                        found.append(model)
        mq = re.findall(r'''(?:model\s*=\s*|"model"\s*:\s*)['"]([\w.:\-/]+)['"]''', self.content)
        for m in mq:
            if len(m) > 3 and m not in found:
                found.append(m)
        return found

    def detect_frameworks(self):
        found = []
        for fw, patterns in AI_PATTERNS["agent_frameworks"].items():
            for pat in patterns:
                if re.search(pat, self.content, re.IGNORECASE):
                    found.append(fw)
                    break
        return found

    def detect_areas(self):
        found = []
        for area, patterns in AI_PATTERNS["agent_areas"].items():
            matches = sum(1 for p in patterns if re.search(p, self.content, re.IGNORECASE))
            if matches >= 2:
                found.append(area)
        return found

    def count_api_calls(self):
        pats = [
            r'\.create\s*\(', r'\.generate\s*\(',
            r'\.chat\s*\(', r'\.complete\s*\(',
            r'\.messages\.create\s*\(', r'\.run\s*\(',
        ]
        return sum(len(re.findall(p, self.content)) for p in pats)


# ============================================================
# MAIN SCANNER
# ============================================================
class AIAgentScanner:
    SUPPORTED_EXT = {".py", ".js", ".ts", ".jsx", ".tsx", ".mjs"}
    SKIP_DIRS = {
        "__pycache__", "node_modules", ".git", "venv", "env",
        ".venv", ".env", "dist", "build", ".next", ".nuxt",
        ".ebextensions", ".elasticbeanstalk", "site-packages",
    }

    def __init__(self, root_path):
        self.root_path = os.path.abspath(root_path)
        self.agents = []
        self.folder_tree = {}
        self.scan_stats = {
            "total_files_scanned": 0, "total_folders_scanned": 0,
            "total_agents_found": 0, "scan_start": None,
            "scan_end": None, "scan_duration_ms": 0,
        }

    def scan(self):
        self.scan_stats["scan_start"] = datetime.now().isoformat()
        t0 = time.time()
        self.folder_tree = self._build_tree(self.root_path)
        self._scan_dir(self.root_path)
        elapsed = (time.time() - t0) * 1000
        self.scan_stats["scan_end"] = datetime.now().isoformat()
        self.scan_stats["scan_duration_ms"] = round(elapsed, 2)
        self.scan_stats["total_agents_found"] = len(self.agents)
        projects = self._group_projects()
        return {
            "scan_root": self.root_path,
            "scan_stats": self.scan_stats,
            "folder_tree": self.folder_tree,
            "agents": self.agents,
            "projects": projects,
            "summary": self._build_summary(projects),
        }

    def _build_tree(self, path, depth=0):
        node = {"name": os.path.basename(path) or path, "path": path, "type": "folder", "depth": depth, "children": [], "agent_count": 0}
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
                if ext in self.SUPPORTED_EXT:
                    node["children"].append({"name": entry, "path": full, "type": "file", "depth": depth + 1})
        return node

    def _mark_tree(self, tree, filepath):
        if tree["type"] == "file" and tree["path"] == filepath:
            tree["is_agent"] = True
        elif tree["type"] == "folder" and filepath.startswith(tree["path"]):
            tree["agent_count"] += 1
            for child in tree.get("children", []):
                self._mark_tree(child, filepath)

    def _scan_dir(self, path):
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
                if ext in self.SUPPORTED_EXT:
                    self.scan_stats["total_files_scanned"] += 1
                    self._analyze_file(full)

    def _analyze_file(self, filepath):
        try:
            with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
                content = f.read()
        except Exception:
            return
        if len(content.strip()) < 20:
            return

        az = SourceCodeAnalyzer(filepath, content)
        providers = az.detect_providers()
        frameworks = az.detect_frameworks()
        if not providers and not frameworks:
            return

        models = az.detect_models()
        areas = az.detect_areas()
        desc = az.extract_description()
        api_calls = az.count_api_calls()

        log_reader = LogFileReader(filepath)
        log_data = log_reader.parse_logs()

        env_reader = EnvConfigReader(filepath, providers)
        api_keys = env_reader.read_api_keys_present()
        config = env_reader.read_config()

        usage = self._build_usage(log_data, config)

        agent = {
            "id": hashlib.md5(filepath.encode()).hexdigest()[:12],
            "script_name": os.path.basename(filepath),
            "script_path": filepath,
            "relative_path": os.path.relpath(filepath, self.root_path),
            "folder": os.path.dirname(os.path.relpath(filepath, self.root_path)) or ".",
            "providers": providers,
            "models": models or ["Not specified"],
            "frameworks": frameworks or ["Direct API"],
            "areas": areas or ["General Purpose"],
            "description": desc,
            "file_size_bytes": os.path.getsize(filepath),
            "lines_of_code": content.count("\n") + 1,
            "api_call_sites": api_calls,
            "last_modified": datetime.fromtimestamp(os.path.getmtime(filepath)).isoformat(),
            "api_keys_configured": api_keys,
            "usage": usage,
        }
        self.agents.append(agent)
        self._mark_tree(self.folder_tree, filepath)

    def _build_usage(self, log_data, config):
        total = log_data.get("total_requests", 0)
        success = log_data.get("successful_requests", 0)
        failed = log_data.get("failed_requests", 0)
        tokens = log_data.get("tokens_used", 0)
        rpm = config.get("rpm") or config.get("rate_limit_rpm")
        tpm = config.get("tpm") or config.get("rate_limit_tpm")
        rpd = config.get("rpd") or config.get("rate_limit_rpd")
        token_limit = config.get("token_limit") or config.get("max_tokens_total")
        return {
            "data_source": log_data.get("data_source", "none"),
            "log_files_found": log_data.get("log_files_found", []),
            "total_requests": total or None,
            "successful_requests": success or None,
            "failed_requests": failed,
            "success_rate": round(success / total * 100, 1) if total > 0 else None,
            "tokens_used": tokens or None,
            "prompt_tokens": log_data.get("prompt_tokens") or None,
            "completion_tokens": log_data.get("completion_tokens") or None,
            "tokens_available": token_limit,
            "tokens_percentage": round(tokens / token_limit * 100, 1) if tokens and token_limit else None,
            "rpm": rpm, "tpm": tpm, "rpd": rpd,
            "failure_reasons": log_data.get("failure_reasons", {}),
            "avg_response_time_ms": log_data.get("avg_response_time_ms"),
            "last_request_time": log_data.get("last_request_time"),
        }

    def _group_projects(self):
        projects = {}
        for agent in self.agents:
            parts = agent["folder"].replace("\\", "/").split("/")
            top = parts[0] if parts and parts[0] not in (".", "") else "Root Project"
            projects.setdefault(top, []).append(agent)
        result = []
        for name, agents in projects.items():
            result.append({
                "project_name": name,
                "agent_count": len(agents),
                "agents": [{"id": a["id"], "script_name": a["script_name"], "providers": a["providers"],
                            "models": a["models"], "areas": a["areas"], "description": a["description"][:100]} for a in agents],
                "providers_used": list({p for a in agents for p in a["providers"]}),
                "models_used": list({m for a in agents for m in a["models"]}),
                "total_requests": sum(a["usage"]["total_requests"] or 0 for a in agents) or None,
                "total_tokens": sum(a["usage"]["tokens_used"] or 0 for a in agents) or None,
                "total_success": sum(a["usage"]["successful_requests"] or 0 for a in agents) or None,
                "total_failed": sum(a["usage"]["failed_requests"] or 0 for a in agents),
            })
        return result

    def _build_summary(self, projects):
        pc, ac, mc = {}, {}, {}
        tr = ts = tf = tt = 0
        fr = {}
        for a in self.agents:
            for p in a["providers"]: pc[p] = pc.get(p, 0) + 1
            for ar in a["areas"]: ac[ar] = ac.get(ar, 0) + 1
            for m in a["models"]: mc[m] = mc.get(m, 0) + 1
            u = a["usage"]
            tr += u.get("total_requests") or 0
            ts += u.get("successful_requests") or 0
            tf += u.get("failed_requests") or 0
            tt += u.get("tokens_used") or 0
            for r, c in u.get("failure_reasons", {}).items():
                fr[r] = fr.get(r, 0) + c
        return {
            "total_agents": len(self.agents), "total_projects": len(projects),
            "providers_breakdown": pc, "area_breakdown": ac, "model_breakdown": mc,
            "overall_usage": {
                "total_requests": tr or None, "total_successful": ts or None,
                "total_failed": tf, "overall_success_rate": round(ts / tr * 100, 1) if tr > 0 else None,
                "total_tokens_used": tt or None, "failure_reason_breakdown": fr,
            },
        }


# ============================================================
# GLOBAL SCAN CACHE
# ============================================================
_scan_cache = {"data": None, "lock": threading.Lock()}


def get_scan_data(force=False):
    with _scan_cache["lock"]:
        if _scan_cache["data"] is None or force:
            scanner = AIAgentScanner(SCAN_ROOT)
            _scan_cache["data"] = scanner.scan()
        return _scan_cache["data"]


# ============================================================
# DASHBOARD HTML (complete inline - CSS + JS + HTML)
# ============================================================
def get_dashboard_html():
    return '''<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>AI Agent Scanner</title>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800;900&family=JetBrains+Mono:wght@400;600&display=swap" rel="stylesheet">
<link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.5.1/css/all.min.css">
<style>
:root{--bg:#0a0a1a;--bg2:#12122a;--bg3:#1a1a3e;--tx:#e8e8ff;--tx2:#9999cc;--tx3:#6666aa;--cyan:#00f5ff;--mag:#ff00ff;--grn:#00ff88;--yel:#ffee00;--org:#ff8800;--red:#ff3355;--blu:#4488ff;--pur:#aa44ff;--pnk:#ff66aa;--tea:#00ccaa;--brd:rgba(255,255,255,0.08);--rad:16px}
*,*::before,*::after{box-sizing:border-box;margin:0;padding:0}
body{font-family:'Inter',sans-serif;background:var(--bg);color:var(--tx);min-height:100vh;overflow-x:hidden}
::-webkit-scrollbar{width:6px}::-webkit-scrollbar-track{background:var(--bg)}::-webkit-scrollbar-thumb{background:linear-gradient(var(--cyan),var(--pur));border-radius:3px}
.bg{position:fixed;top:0;left:0;width:100%;height:100%;z-index:-1;pointer-events:none}
.orb{position:absolute;border-radius:50%;filter:blur(80px);animation:fl 20s ease-in-out infinite}
.orb:nth-child(1){width:500px;height:500px;top:-100px;left:-100px;background:rgba(0,245,255,0.07)}
.orb:nth-child(2){width:400px;height:400px;top:50%;right:-100px;background:rgba(255,0,255,0.05);animation-delay:-7s}
.orb:nth-child(3){width:600px;height:600px;bottom:-200px;left:30%;background:rgba(0,255,136,0.04);animation-delay:-14s}
@keyframes fl{0%,100%{transform:translate(0,0)}50%{transform:translate(40px,-40px)}}
.hdr{background:rgba(18,18,42,0.95);backdrop-filter:blur(20px);border-bottom:1px solid var(--brd);padding:14px 28px;display:flex;align-items:center;justify-content:space-between;position:sticky;top:0;z-index:100;flex-wrap:wrap;gap:10px}
.hdr-l{display:flex;align-items:center;gap:12px}
.logo{width:44px;height:44px;background:linear-gradient(135deg,var(--cyan),var(--pur));border-radius:12px;display:flex;align-items:center;justify-content:center;font-size:20px;animation:gl 3s infinite}
@keyframes gl{0%,100%{box-shadow:0 0 15px rgba(0,245,255,0.3)}50%{box-shadow:0 0 30px rgba(0,245,255,0.5)}}
.brand h1{font-size:18px;font-weight:800;background:linear-gradient(135deg,var(--cyan),var(--pur));-webkit-background-clip:text;-webkit-text-fill-color:transparent}
.brand p{font-size:10px;color:var(--tx3);margin-top:1px}
.hdr-r{display:flex;align-items:center;gap:8px}
.btn{padding:8px 16px;border:none;border-radius:10px;font-weight:600;font-size:11px;cursor:pointer;display:flex;align-items:center;gap:6px;transition:all 0.3s;font-family:'Inter',sans-serif}
.btn-p{background:linear-gradient(135deg,var(--cyan),var(--pur));color:#000}
.btn-p:hover{transform:translateY(-2px);box-shadow:0 4px 15px rgba(0,245,255,0.3)}
.btn-s{background:rgba(255,255,255,0.07);color:var(--tx);border:1px solid var(--brd)}
.sp{background:rgba(255,255,255,0.05);border:1px solid var(--brd);border-radius:8px;padding:5px 12px;font-size:10px;color:var(--tx3);font-family:'JetBrains Mono',monospace;max-width:250px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.mn{padding:22px 28px;max-width:1800px;margin:0 auto}
.sr{display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:12px;margin-bottom:22px}
.sc{background:var(--bg3);border:1px solid var(--brd);border-radius:var(--rad);padding:16px;position:relative;overflow:hidden;transition:all 0.3s}
.sc:hover{transform:translateY(-3px);border-color:rgba(0,245,255,0.3);box-shadow:0 6px 20px rgba(0,0,0,0.3)}
.si{width:38px;height:38px;border-radius:10px;display:flex;align-items:center;justify-content:center;font-size:17px;margin-bottom:8px}
.sv{font-size:24px;font-weight:800;font-family:'JetBrains Mono',monospace}
.sl{font-size:10px;color:var(--tx3);margin-top:2px;text-transform:uppercase;letter-spacing:1px}
.sb{position:absolute;bottom:0;left:0;height:3px;width:100%}
.tabs{display:flex;gap:3px;margin-bottom:20px;background:rgba(255,255,255,0.03);border-radius:12px;padding:3px;flex-wrap:wrap}
.tab{padding:8px 16px;border-radius:9px;cursor:pointer;font-size:11px;font-weight:600;color:var(--tx3);transition:all 0.3s;display:flex;align-items:center;gap:5px;white-space:nowrap}
.tab:hover{color:var(--tx);background:rgba(255,255,255,0.05)}
.tab.on{background:linear-gradient(135deg,var(--cyan),var(--pur));color:#000}
.tc{display:none;animation:fi 0.3s ease}.tc.on{display:block}
@keyframes fi{from{opacity:0;transform:translateY(8px)}to{opacity:1;transform:translateY(0)}}
.g2{display:grid;grid-template-columns:1fr 1fr;gap:16px}
.g3{display:grid;grid-template-columns:repeat(auto-fill,minmax(320px,1fr));gap:16px}
.cs2{grid-column:span 2}
.cd{background:var(--bg3);border:1px solid var(--brd);border-radius:var(--rad);padding:20px;transition:all 0.3s}
.cd:hover{border-color:rgba(0,245,255,0.15)}
.ch{display:flex;justify-content:space-between;align-items:center;margin-bottom:14px}
.ch h3{font-size:14px;font-weight:700;display:flex;align-items:center;gap:7px}
.hg{display:flex;flex-wrap:wrap;gap:12px;justify-content:center;padding:6px 0}
.hex{clip-path:polygon(50% 0%,100% 25%,100% 75%,50% 100%,0% 75%,0% 25%);display:flex;flex-direction:column;align-items:center;justify-content:center;text-align:center;cursor:default;transition:all 0.3s}
.hex:hover{transform:scale(1.08)}
.pen{clip-path:polygon(50% 0%,100% 38%,82% 100%,18% 100%,0% 38%);display:flex;flex-direction:column;align-items:center;justify-content:center;text-align:center;transition:all 0.3s}
.pen:hover{transform:scale(1.08) rotate(3deg)}
.oct{clip-path:polygon(30% 0%,70% 0%,100% 30%,100% 70%,70% 100%,30% 100%,0% 70%,0% 30%);display:flex;flex-direction:column;align-items:center;justify-content:center;text-align:center;transition:all 0.3s}
.oct:hover{transform:scale(1.08) rotate(-3deg)}
.smw{display:flex;flex-wrap:wrap;justify-content:center;gap:18px;padding:6px 0}
.sem{position:relative;width:130px;height:74px;overflow:hidden}
.sem .sv2{position:absolute;bottom:3px;left:50%;transform:translateX(-50%);font-size:16px;font-weight:800;font-family:'JetBrains Mono',monospace}
.sem .sl2{position:absolute;bottom:-16px;left:50%;transform:translateX(-50%);font-size:9px;color:var(--tx3);white-space:nowrap}
.ac{background:var(--bg3);border:1px solid var(--brd);border-radius:var(--rad);padding:18px;position:relative;overflow:hidden;transition:all 0.3s}
.ac:hover{transform:translateY(-3px);box-shadow:0 6px 20px rgba(0,0,0,0.3);border-color:rgba(0,245,255,0.25)}
.atb{position:absolute;top:0;left:0;right:0;height:4px}
.ah{display:flex;align-items:flex-start;gap:10px;margin-bottom:12px}
.ai2{width:42px;height:42px;border-radius:12px;display:flex;align-items:center;justify-content:center;font-size:19px;flex-shrink:0}
.an{font-size:14px;font-weight:700;margin-bottom:2px;word-break:break-all}
.ap{font-size:9px;color:var(--tx3);font-family:'JetBrains Mono',monospace}
.ir{display:flex;align-items:flex-start;gap:7px;padding:4px 0;font-size:11px;border-bottom:1px solid rgba(255,255,255,0.04)}
.ir:last-child{border-bottom:none}
.ii{width:16px;text-align:center;color:var(--cyan);flex-shrink:0;margin-top:1px}
.il{color:var(--tx3);min-width:65px;flex-shrink:0}
.iv{color:var(--tx);flex:1;word-break:break-word}
.tag{display:inline-block;padding:2px 7px;border-radius:20px;font-size:9px;font-weight:600;margin:1px;border:1px solid}
.tp{background:rgba(0,245,255,0.1);color:var(--cyan);border-color:rgba(0,245,255,0.3)}
.tm{background:rgba(170,68,255,0.1);color:var(--pur);border-color:rgba(170,68,255,0.3)}
.ta{background:rgba(0,255,136,0.1);color:var(--grn);border-color:rgba(0,255,136,0.3)}
.tf{background:rgba(255,136,0,0.1);color:var(--org);border-color:rgba(255,136,0,0.3)}
.db{background:rgba(0,245,255,0.04);border-left:3px solid var(--cyan);border-radius:0 8px 8px 0;padding:7px 10px;margin:8px 0;font-size:10px;color:var(--tx2);line-height:1.5}
.ug{display:grid;grid-template-columns:repeat(3,1fr);gap:5px;margin-top:8px}
.uc{background:rgba(255,255,255,0.03);border-radius:8px;padding:7px;text-align:center}
.uv{font-size:13px;font-weight:700;font-family:'JetBrains Mono',monospace}
.ul{font-size:8px;color:var(--tx3);text-transform:uppercase;margin-top:1px}
.pb{width:100%;height:6px;background:rgba(255,255,255,0.06);border-radius:3px;overflow:hidden;margin:6px 0}
.pf{height:100%;border-radius:3px;transition:width 1.2s ease}
.nd{font-size:9px;color:var(--tx3);font-style:italic}
.bd{display:inline-flex;align-items:center;gap:3px;padding:2px 7px;border-radius:20px;font-size:8px;font-weight:700;text-transform:uppercase;letter-spacing:1px}
.br{background:rgba(0,255,136,0.15);color:var(--grn);border:1px solid rgba(0,255,136,0.3)}
.bn{background:rgba(255,136,0,0.15);color:var(--org);border:1px solid rgba(255,136,0,0.3)}
.dt{width:100%;border-collapse:collapse}
.dt th,.dt td{padding:9px 12px;text-align:left;border-bottom:1px solid var(--brd);font-size:11px}
.dt th{color:var(--tx3);font-weight:600;text-transform:uppercase;font-size:9px}
.dt tr:hover{background:rgba(255,255,255,0.02)}
.sd{width:6px;height:6px;border-radius:50%;display:inline-block;margin-right:4px}
.sg{background:var(--grn)}.sr2{background:var(--red)}.sy{background:var(--yel)}
.fr{font-size:9px;color:var(--tx3);padding:1px 0}
.fd{width:5px;height:5px;border-radius:50%;display:inline-block;margin-right:4px;background:var(--red)}
.tb{background:var(--bg3);border:1px solid var(--brd);border-radius:var(--rad);padding:16px;max-height:500px;overflow-y:auto}
.tn{padding:3px 0;font-family:'JetBrains Mono',monospace;font-size:11px}
.tfo{color:var(--yel);cursor:pointer}.tfo:hover{color:var(--org)}
.tfi{color:var(--tx2)}.tfi.ia{color:var(--grn);font-weight:600}
.tc2{margin-left:16px}
.tbg{display:inline-block;background:var(--cyan);color:#000;font-size:8px;font-weight:700;padding:1px 5px;border-radius:8px;margin-left:5px}
.abg{background:var(--grn)}
.dw{position:relative;display:inline-block}
.dcn{position:absolute;top:50%;left:50%;transform:translate(-50%,-50%);text-align:center}
.dv{font-size:22px;font-weight:800;font-family:'JetBrains Mono',monospace}
.dl{font-size:9px;color:var(--tx3)}
.lg{display:flex;flex-wrap:wrap;gap:8px;margin-top:12px}
.li{display:flex;align-items:center;gap:4px;font-size:10px}
.ld{width:9px;height:9px;border-radius:2px;flex-shrink:0}
.em{text-align:center;padding:30px;color:var(--tx3)}
.em i{font-size:40px;margin-bottom:12px;opacity:0.4;display:block}
.ldr{position:fixed;top:0;left:0;right:0;bottom:0;background:rgba(10,10,26,0.97);display:flex;flex-direction:column;align-items:center;justify-content:center;z-index:9999}
.spn{width:50px;height:50px;border:4px solid rgba(0,245,255,0.2);border-top:4px solid var(--cyan);border-radius:50%;animation:sp 0.9s linear infinite}
@keyframes sp{to{transform:rotate(360deg)}}
.lt{margin-top:14px;font-size:14px;color:var(--cyan);font-weight:600}
@media(max-width:1100px){.g2{grid-template-columns:1fr}.cs2{grid-column:span 1}}
@media(max-width:768px){.hdr{padding:10px 14px}.mn{padding:14px}.sp{display:none}.sr{grid-template-columns:repeat(2,1fr)}}
</style>
</head>
<body>
<div class="bg"><div class="orb"></div><div class="orb"></div><div class="orb"></div></div>
<div class="ldr" id="ldr"><div class="spn"></div><div class="lt">Scanning for AI Agents...</div></div>

<header class="hdr">
<div class="hdr-l"><div class="logo">🤖</div><div class="brand"><h1>AI Agent Scanner</h1><p id="st">Loading...</p></div></div>
<div class="hdr-r"><div class="sp" id="spp">📁 ...</div>
<button class="btn btn-s" onclick="exportJSON()"><i class="fas fa-download"></i> Export</button>
<button class="btn btn-p" onclick="rescan()"><i class="fas fa-sync-alt" id="ri"></i> Rescan</button></div>
</header>

<main class="mn" id="mn" style="display:none">
<div class="sr" id="srow"></div>
<div class="tabs">
<div class="tab on" data-t="ov" onclick="stab('ov')"><i class="fas fa-chart-pie"></i> Overview</div>
<div class="tab" data-t="ag" onclick="stab('ag')"><i class="fas fa-robot"></i> Agents</div>
<div class="tab" data-t="pj" onclick="stab('pj')"><i class="fas fa-cubes"></i> Projects</div>
<div class="tab" data-t="us" onclick="stab('us')"><i class="fas fa-chart-bar"></i> Usage</div>
<div class="tab" data-t="fl" onclick="stab('fl')"><i class="fas fa-exclamation-triangle"></i> Failures</div>
<div class="tab" data-t="tr" onclick="stab('tr')"><i class="fas fa-folder-tree"></i> Tree</div>
</div>
<div class="tc on" id="t-ov"></div><div class="tc" id="t-ag"></div><div class="tc" id="t-pj"></div>
<div class="tc" id="t-us"></div><div class="tc" id="t-fl"></div><div class="tc" id="t-tr"></div>
</main>

<script>
const C=['#00f5ff','#ff00ff','#00ff88','#ffee00','#ff8800','#ff3355','#4488ff','#aa44ff','#ff66aa','#00ccaa','#88ff00','#ff4488','#44aaff','#ffcc00','#cc88ff'];
const G=['linear-gradient(135deg,#00f5ff,#aa44ff)','linear-gradient(135deg,#ff00ff,#ff8800)','linear-gradient(135deg,#00ff88,#00f5ff)','linear-gradient(135deg,#ffee00,#ff8800)','linear-gradient(135deg,#ff3355,#ff00ff)','linear-gradient(135deg,#4488ff,#00f5ff)','linear-gradient(135deg,#aa44ff,#ff66aa)','linear-gradient(135deg,#00ccaa,#00ff88)'];
const IC=['🤖','🧠','⚡','🔮','🎯','🚀','💡','🔬','📊','🎨','📧','💰','🔧','🌐','📝','🦜'];
const PI={'OpenAI':'🟢','Anthropic':'🟠','Google AI':'🔵','Hugging Face':'🤗','Cohere':'🟣','Mistral AI':'🌀','AWS Bedrock':'☁️','Azure OpenAI':'🔷','LangChain':'🦜','CrewAI':'👥','AutoGen':'🔄','Ollama':'🦙','Replicate':'🔁','Groq':'⚡'};
let D=null;

document.addEventListener('DOMContentLoaded',()=>fetchData());

async function fetchData(url='/api/scan'){
try{const r=await fetch(url);if(!r.ok)throw new Error('HTTP '+r.status);D=await r.json();render()}
catch(e){document.getElementById('ldr').innerHTML='<div style="text-align:center;color:#ff3355;padding:30px"><i class="fas fa-exclamation-triangle" style="font-size:40px;display:block;margin-bottom:12px"></i><h2>Load Failed</h2><p style="color:#9999cc;margin-top:8px">'+e.message+'</p><button class="btn btn-p" onclick="fetchData()" style="margin-top:14px"><i class="fas fa-redo"></i> Retry</button></div>'}}

async function rescan(){document.getElementById('ri').style.animation='sp 0.5s linear infinite';document.getElementById('ldr').style.display='flex';document.getElementById('mn').style.display='none';try{const r=await fetch('/api/rescan');if(!r.ok)throw new Error('HTTP '+r.status);D=await r.json();render()}catch(e){alert('Failed: '+e.message)}document.getElementById('ri').style.animation=''}
function exportJSON(){const b=new Blob([JSON.stringify(D,null,2)],{type:'application/json'});const u=URL.createObjectURL(b);const a=document.createElement('a');a.href=u;a.download='ai_agents_'+Date.now()+'.json';a.click();URL.revokeObjectURL(u)}
function stab(t){document.querySelectorAll('.tab').forEach(x=>x.classList.remove('on'));document.querySelectorAll('.tc').forEach(x=>x.classList.remove('on'));document.querySelector('[data-t="'+t+'"]').classList.add('on');document.getElementById('t-'+t).classList.add('on')}
function fmt(n){if(n==null)return'N/A';if(typeof n==='string')return n;if(n>=1e6)return(n/1e6).toFixed(1)+'M';if(n>=1e3)return(n/1e3).toFixed(1)+'K';return n.toString()}

function render(){
document.getElementById('ldr').style.display='none';document.getElementById('mn').style.display='block';
const s=D.scan_stats,sm=D.summary,u=sm.overall_usage;
document.getElementById('spp').textContent='📁 '+D.scan_root;document.getElementById('spp').title=D.scan_root;
document.getElementById('st').textContent='Scanned in '+s.scan_duration_ms+'ms • '+new Date(s.scan_start).toLocaleString();
renderStats();renderOv();renderAg();renderPj();renderUs();renderFl();renderTr()}

function renderStats(){const s=D.scan_stats,sm=D.summary,u=sm.overall_usage;
const st=[{i:'🤖',l:'Agents',v:sm.total_agents,c:'#00f5ff',g:G[0]},{i:'📂',l:'Folders',v:s.total_folders_scanned,c:'#ffee00',g:G[3]},{i:'📄',l:'Files',v:s.total_files_scanned,c:'#aa44ff',g:G[6]},{i:'🏢',l:'Providers',v:Object.keys(sm.providers_breakdown).length,c:'#ff8800',g:G[1]},{i:'📡',l:'Requests',v:fmt(u.total_requests),c:'#4488ff',g:G[5]},{i:'✅',l:'Success',v:u.overall_success_rate!=null?u.overall_success_rate+'%':'N/A',c:'#00ff88',g:G[2]},{i:'🪙',l:'Tokens',v:fmt(u.total_tokens_used),c:'#ff66aa',g:G[6]},{i:'📦',l:'Projects',v:sm.total_projects,c:'#00ccaa',g:G[7]}];
document.getElementById('srow').innerHTML=st.map(s=>'<div class="sc"><div class="si" style="background:'+s.g+'">'+s.i+'</div><div class="sv" style="color:'+s.c+'">'+s.v+'</div><div class="sl">'+s.l+'</div><div class="sb" style="background:'+s.g+'"></div></div>').join('')}

function renderOv(){const sm=D.summary,u=sm.overall_usage;let h='<div class="g2">';
h+='<div class="cd"><div class="ch"><h3><i class="fas fa-building" style="color:var(--cyan)"></i> Providers</h3></div><div class="hg">';
const pe=Object.entries(sm.providers_breakdown);
pe.forEach(([n,c],i)=>{h+='<div class="hex" style="background:'+G[i%G.length]+';width:105px;height:121px"><div style="font-size:16px">'+(PI[n]||'🔹')+'</div><div style="font-size:18px;font-weight:800;font-family:JetBrains Mono">'+c+'</div><div style="font-size:7px;margin-top:2px;opacity:0.9;padding:0 6px">'+n+'</div></div>'});
if(!pe.length)h+='<div class="em"><i class="fas fa-building"></i><p>No providers</p></div>';
h+='</div></div>';

h+='<div class="cd"><div class="ch"><h3><i class="fas fa-bullseye" style="color:var(--mag)"></i> Areas</h3></div><div style="display:flex;flex-wrap:wrap;gap:10px;justify-content:center;padding:6px 0">';
const ae=Object.entries(sm.area_breakdown);
const clips=['polygon(50% 0%,100% 25%,100% 75%,50% 100%,0% 75%,0% 25%)','polygon(50% 0%,100% 38%,82% 100%,18% 100%,0% 38%)','polygon(30% 0%,70% 0%,100% 30%,100% 70%,70% 100%,30% 100%,0% 70%,0% 30%)'];
const szs=['105px','92px','88px'];
ae.forEach(([a,c],i)=>{const sz=szs[i%3];h+='<div style="width:'+sz+';height:'+sz+';clip-path:'+clips[i%3]+';background:'+G[i%G.length]+';display:flex;flex-direction:column;align-items:center;justify-content:center;text-align:center;transition:all 0.3s;cursor:default" onmouseover="this.style.transform=\'scale(1.1)\'" onmouseout="this.style.transform=\'scale(1)\'"><div style="font-size:15px;font-weight:800">'+c+'</div><div style="font-size:6px;padding:0 3px;margin-top:1px">'+a.split('/')[0].trim()+'</div></div>'});
if(!ae.length)h+='<div class="em"><p>No areas</p></div>';
h+='</div></div>';

h+='<div class="cd cs2"><div class="ch"><h3><i class="fas fa-gauge-high" style="color:var(--grn)"></i> Gauges</h3></div><div class="smw">';
const gs=[{l:'Success Rate',v:u.overall_success_rate,mx:100,c:'#00ff88',s:'%'},{l:'Agents',v:sm.total_agents,mx:Math.max(20,sm.total_agents),c:'#aa44ff',s:''},{l:'Providers',v:Object.keys(sm.providers_breakdown).length,mx:15,c:'#00f5ff',s:''},{l:'Projects',v:sm.total_projects,mx:Math.max(10,sm.total_projects),c:'#ff8800',s:''}];
gs.forEach(g=>{const p=g.v!=null?Math.min(g.v/g.mx*100,100):0;const cc=Math.PI*54;const off=cc-p/100*cc;
h+='<div class="sem"><svg width="130" height="74" viewBox="0 0 130 74"><path d="M 11 65 A 54 54 0 0 1 119 65" fill="none" stroke="rgba(255,255,255,0.06)" stroke-width="9" stroke-linecap="round"/><path d="M 11 65 A 54 54 0 0 1 119 65" fill="none" stroke="'+g.c+'" stroke-width="9" stroke-linecap="round" stroke-dasharray="'+cc+'" stroke-dashoffset="'+off+'" style="transition:stroke-dashoffset 1.5s ease"/></svg><div class="sv2" style="color:'+g.c+'">'+(g.v!=null?g.v+g.s:'N/A')+'</div><div class="sl2">'+g.l+'</div></div>'});
h+='</div></div>';

const me=Object.entries(sm.model_breakdown);
h+='<div class="cd"><div class="ch"><h3><i class="fas fa-brain" style="color:var(--yel)"></i> Models</h3></div><div style="display:flex;align-items:center;gap:20px;flex-wrap:wrap;justify-content:center"><div class="dw">'+donut(sm.model_breakdown,160)+'<div class="dcn"><div class="dv">'+me.length+'</div><div class="dl">Models</div></div></div><div class="lg">'+me.map(([n,c],i)=>'<div class="li"><div class="ld" style="background:'+C[i%C.length]+'"></div><span>'+n+' ('+c+')</span></div>').join('')+(me.length?'':'<div class="em"><p>No models</p></div>')+'</div></div></div>';

h+='<div class="cd"><div class="ch"><h3><i class="fas fa-exchange-alt" style="color:var(--blu)"></i> Requests</h3></div><div style="display:flex;gap:12px;flex-wrap:wrap;justify-content:center;padding:8px 0">';
h+='<div class="oct" style="width:105px;height:105px;background:linear-gradient(135deg,#00ff88,#00ccaa)"><i class="fas fa-check" style="font-size:15px"></i><div style="font-size:17px;font-weight:800;margin-top:3px">'+fmt(u.total_successful)+'</div><div style="font-size:7px">SUCCESS</div></div>';
h+='<div class="oct" style="width:105px;height:105px;background:linear-gradient(135deg,#ff3355,#ff00ff)"><i class="fas fa-times" style="font-size:15px"></i><div style="font-size:17px;font-weight:800;margin-top:3px">'+fmt(u.total_failed)+'</div><div style="font-size:7px">FAILED</div></div>';
h+='<div class="pen" style="width:105px;height:100px;background:linear-gradient(135deg,#4488ff,#00f5ff)"><i class="fas fa-paper-plane" style="font-size:15px"></i><div style="font-size:17px;font-weight:800;margin-top:3px">'+fmt(u.total_requests)+'</div><div style="font-size:7px">TOTAL</div></div>';
h+='</div></div></div>';
document.getElementById('t-ov').innerHTML=h}

function renderAg(){if(!D.agents.length){document.getElementById('t-ag').innerHTML='<div class="cd"><div class="em"><i class="fas fa-robot"></i><p>No AI agents found.<br>Scan a folder containing Python/JS files with AI imports.</p></div></div>';return}
let h='<div class="g3">';
D.agents.forEach((a,i)=>{const g=G[i%G.length],ic=IC[i%IC.length],u=a.usage,hd=u.data_source==='log_files';
h+='<div class="ac"><div class="atb" style="background:'+g+'"></div><div class="ah"><div class="ai2" style="background:'+g+'">'+ic+'</div><div style="flex:1;min-width:0"><div class="an">'+a.script_name+'</div><div class="ap">📁 '+a.relative_path+'</div><div style="margin-top:3px"><span class="bd '+(hd?'br':'bn')+'">'+(hd?'✅ Log Data':'⚠️ No Logs')+'</span></div></div></div>';
h+='<div><div class="ir"><span class="ii"><i class="fas fa-building"></i></span><span class="il">Provider</span><span class="iv">'+(a.providers.length?a.providers.map(p=>'<span class="tag tp">'+(PI[p]||'🔹')+' '+p+'</span>').join(' '):'<span class="nd">None</span>')+'</span></div>';
h+='<div class="ir"><span class="ii"><i class="fas fa-brain"></i></span><span class="il">Model</span><span class="iv">'+a.models.map(m=>'<span class="tag tm">'+m+'</span>').join(' ')+'</span></div>';
h+='<div class="ir"><span class="ii"><i class="fas fa-bullseye"></i></span><span class="il">Area</span><span class="iv">'+a.areas.map(x=>'<span class="tag ta">'+x+'</span>').join(' ')+'</span></div>';
h+='<div class="ir"><span class="ii"><i class="fas fa-cogs"></i></span><span class="il">Framework</span><span class="iv">'+a.frameworks.map(f=>'<span class="tag tf">'+f+'</span>').join(' ')+'</span></div>';
h+='<div class="ir"><span class="ii"><i class="fas fa-code"></i></span><span class="il">Code</span><span class="iv">'+a.lines_of_code+' lines • '+a.api_call_sites+' API calls</span></div></div>';
h+='<div class="db"><i class="fas fa-info-circle" style="color:var(--cyan)"></i> '+a.description+'</div>';
h+='<div class="ug"><div class="uc"><div class="uv" style="color:#00ff88">'+(u.successful_requests!=null?fmt(u.successful_requests):'—')+'</div><div class="ul">✅ Success</div></div>';
h+='<div class="uc"><div class="uv" style="color:#ff3355">'+(u.failed_requests!=null?u.failed_requests:'—')+'</div><div class="ul">❌ Failed</div></div>';
h+='<div class="uc"><div class="uv" style="color:#00f5ff">'+(u.total_requests!=null?fmt(u.total_requests):'—')+'</div><div class="ul">📡 Total</div></div>';
h+='<div class="uc"><div class="uv" style="color:#ffee00">'+(u.tokens_used!=null?fmt(u.tokens_used):'—')+'</div><div class="ul">🪙 Tokens</div></div>';
h+='<div class="uc"><div class="uv" style="color:#aa44ff">'+(u.rpm!=null?u.rpm:'—')+'</div><div class="ul">⚡ RPM</div></div>';
h+='<div class="uc"><div class="uv" style="color:#ff66aa">'+(u.avg_response_time_ms!=null?u.avg_response_time_ms+'ms':'—')+'</div><div class="ul">⏱ RT</div></div></div>';
if(u.tokens_percentage!=null){h+='<div class="pb"><div class="pf" style="width:'+u.tokens_percentage+'%;background:'+g+'"></div></div><div style="font-size:8px;color:var(--tx3);text-align:right">🪙 '+fmt(u.tokens_used)+' / '+fmt(u.tokens_available)+' ('+u.tokens_percentage+'%)</div>'}
if(u.success_rate!=null){h+='<div style="font-size:9px;color:var(--tx3);margin-top:4px">Rate: <b style="color:'+(u.success_rate>=90?'#00ff88':u.success_rate>=70?'#ffee00':'#ff3355')+'">'+u.success_rate+'%</b></div>'}
const frs=Object.entries(u.failure_reasons||{});
if(frs.length){h+='<div style="margin-top:6px;padding-top:6px;border-top:1px solid var(--brd)"><div style="font-size:9px;color:var(--red);font-weight:600;margin-bottom:3px">⚠️ Failures:</div>';frs.forEach(([r,c])=>{h+='<div class="fr"><span class="fd"></span>'+r+' <b style="color:var(--red)">('+c+'x)</b></div>'});h+='</div>'}
if(u.log_files_found&&u.log_files_found.length){h+='<div style="margin-top:5px;font-size:8px;color:var(--tx3)">📋 '+u.log_files_found.join(', ')+'</div>'}
h+='</div>'});
h+='</div>';document.getElementById('t-ag').innerHTML=h}

function renderPj(){if(!D.projects.length){document.getElementById('t-pj').innerHTML='<div class="cd"><div class="em"><i class="fas fa-cubes"></i><p>No projects</p></div></div>';return}
let h='';D.projects.forEach((p,pi)=>{const g=G[pi%G.length];
h+='<div class="cd" style="margin-bottom:16px"><div class="ch"><h3><span style="font-size:20px">📦</span> '+p.project_name+'</h3><span style="font-size:11px;color:var(--tx3)">'+p.agent_count+' agent'+(p.agent_count!==1?'s':'')+'</span></div>';
h+='<div style="display:flex;gap:10px;flex-wrap:wrap;margin-bottom:12px">';
h+='<div class="hex" style="background:linear-gradient(135deg,#00f5ff,#4488ff);width:85px;height:98px"><div style="font-size:17px;font-weight:800">'+p.agent_count+'</div><div style="font-size:6px">AGENTS</div></div>';
h+='<div class="pen" style="background:linear-gradient(135deg,#00ff88,#00ccaa);width:80px;height:76px"><div style="font-size:14px;font-weight:800">'+fmt(p.total_success)+'</div><div style="font-size:6px">SUCCESS</div></div>';
h+='<div class="oct" style="background:linear-gradient(135deg,#ff3355,#ff00ff);width:78px;height:78px"><div style="font-size:14px;font-weight:800">'+(p.total_failed||0)+'</div><div style="font-size:6px">FAILED</div></div>';
h+='<div class="pen" style="background:linear-gradient(135deg,#ffee00,#ff8800);width:80px;height:76px"><div style="font-size:13px;font-weight:800">'+fmt(p.total_tokens)+'</div><div style="font-size:6px">TOKENS</div></div></div>';
h+='<div style="margin-bottom:10px;display:flex;flex-wrap:wrap;gap:4px">'+p.providers_used.map(x=>'<span class="tag tp">'+(PI[x]||'🔹')+' '+x+'</span>').join('')+p.models_used.slice(0,5).map(m=>'<span class="tag tm">'+m+'</span>').join('')+'</div>';
h+='<div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(200px,1fr));gap:6px">';
p.agents.forEach((a,ai)=>{h+='<div style="background:rgba(255,255,255,0.03);border-radius:8px;padding:8px;border:1px solid var(--brd)"><div style="font-weight:600;font-size:11px">'+IC[ai%IC.length]+' '+a.script_name+'</div><div style="font-size:9px;color:var(--tx3);margin-top:2px">'+a.areas.join(', ')+'</div><div style="font-size:9px;color:var(--cyan);margin-top:1px">'+a.providers.join(', ')+'</div></div>'});
h+='</div></div>'});
document.getElementById('t-pj').innerHTML=h}

function renderUs(){let h='<div class="g2">';
const wt=D.agents.filter(a=>a.usage.tokens_used);
h+='<div class="cd cs2"><div class="ch"><h3><i class="fas fa-chart-bar" style="color:#4488ff"></i> Token Usage</h3></div>';
if(wt.length){wt.forEach((a,i)=>{const p=a.usage.tokens_percentage||0,c=C[i%C.length];
h+='<div style="margin-bottom:10px"><div style="display:flex;justify-content:space-between;margin-bottom:3px"><span style="font-size:11px;font-weight:600">'+IC[i%IC.length]+' '+a.script_name+'</span><span style="font-size:10px;color:var(--tx3);font-family:JetBrains Mono">'+fmt(a.usage.tokens_used)+' / '+(a.usage.tokens_available!=null?fmt(a.usage.tokens_available):'?')+'</span></div><div class="pb" style="height:9px"><div class="pf" style="width:'+p+'%;background:'+c+';height:9px"></div></div><div style="font-size:9px;color:var(--tx3);margin-top:2px">RPM: '+(a.usage.rpm||'—')+' | TPM: '+fmt(a.usage.tpm)+' | RPD: '+fmt(a.usage.rpd)+' | RT: '+(a.usage.avg_response_time_ms!=null?a.usage.avg_response_time_ms+'ms':'—')+'</div></div>'})}
else{h+='<div class="em"><i class="fas fa-chart-bar"></i><p>No token data in logs.<br>Add log files with token usage to see metrics.</p></div>'}
h+='</div>';
h+='<div class="cd cs2"><div class="ch"><h3><i class="fas fa-tachometer-alt" style="color:#ff8800"></i> Rate Limits</h3></div><table class="dt"><thead><tr><th>Agent</th><th>Provider</th><th>Data</th><th>RPM</th><th>TPM</th><th>RPD</th><th>Tokens</th><th>Avg RT</th></tr></thead><tbody>';
D.agents.forEach((a,i)=>{const u=a.usage,hd=u.data_source==='log_files';
h+='<tr><td>'+IC[i%IC.length]+' '+a.script_name+'</td><td>'+a.providers.map(p=>(PI[p]||'🔹')).join('')+' '+(a.providers[0]||'?')+'</td><td><span class="bd '+(hd?'br':'bn')+'" style="font-size:8px">'+(hd?'✅':'⚠️')+'</span></td>';
h+='<td>'+(u.rpm!=null?u.rpm:'<span class="nd">—</span>')+'</td><td>'+(u.tpm!=null?fmt(u.tpm):'<span class="nd">—</span>')+'</td><td>'+(u.rpd!=null?fmt(u.rpd):'<span class="nd">—</span>')+'</td>';
h+='<td>'+(u.tokens_used!=null?fmt(u.tokens_used):'<span class="nd">—</span>')+'</td><td>'+(u.avg_response_time_ms!=null?u.avg_response_time_ms+'ms':'<span class="nd">—</span>')+'</td></tr>'});
h+='</tbody></table></div></div>';
document.getElementById('t-us').innerHTML=h}

function renderFl(){const u=D.summary.overall_usage;let h='';
h+='<div class="cd" style="margin-bottom:16px"><div class="ch"><h3><i class="fas fa-exclamation-triangle" style="color:var(--red)"></i> Summary</h3></div><div style="display:flex;gap:14px;flex-wrap:wrap;justify-content:center;padding:12px 0">';
h+='<div class="hex" style="background:linear-gradient(135deg,#00ff88,#00ccaa);width:125px;height:144px"><i class="fas fa-check-circle" style="font-size:18px"></i><div style="font-size:20px;font-weight:800;font-family:JetBrains Mono;margin-top:3px">'+fmt(u.total_successful)+'</div><div style="font-size:7px;margin-top:2px;opacity:0.9">Successful</div></div>';
h+='<div class="hex" style="background:linear-gradient(135deg,#ff3355,#ff00ff);width:125px;height:144px"><i class="fas fa-times-circle" style="font-size:18px"></i><div style="font-size:20px;font-weight:800;font-family:JetBrains Mono;margin-top:3px">'+fmt(u.total_failed)+'</div><div style="font-size:7px;margin-top:2px;opacity:0.9">Failed</div></div>';
h+='<div class="hex" style="background:linear-gradient(135deg,#4488ff,#00f5ff);width:125px;height:144px"><i class="fas fa-percentage" style="font-size:18px"></i><div style="font-size:20px;font-weight:800;font-family:JetBrains Mono;margin-top:3px">'+(u.overall_success_rate!=null?u.overall_success_rate+'%':'N/A')+'</div><div style="font-size:7px;margin-top:2px;opacity:0.9">Success Rate</div></div>';
h+='</div></div>';

const frs=u.failure_reason_breakdown||{};const fe=Object.entries(frs);
if(fe.length){h+='<div class="cd" style="margin-bottom:16px"><div class="ch"><h3><i class="fas fa-bug" style="color:var(--org)"></i> Failure Reasons</h3></div><div style="display:flex;flex-wrap:wrap;gap:10px;justify-content:center;padding:8px 0">';
fe.forEach(([r,c],i)=>{const sz=['100px','90px','85px'];const s=sz[i%3];
h+='<div style="width:'+s+';height:'+s+';clip-path:'+clips[i%3]+';background:'+G[i%G.length]+';display:flex;flex-direction:column;align-items:center;justify-content:center;text-align:center;padding:5px"><div style="font-size:15px;font-weight:800">'+c+'</div><div style="font-size:6px;margin-top:1px;padding:0 3px">'+r.substring(0,25)+'</div></div>'});
h+='</div></div>'}else{h+='<div class="cd" style="margin-bottom:16px"><div class="em"><i class="fas fa-bug"></i><p>No failures found in logs.</p></div></div>'}

h+='<div class="cd"><div class="ch"><h3><i class="fas fa-list" style="color:var(--pur)"></i> Per-Agent</h3></div><table class="dt"><thead><tr><th>Agent</th><th>Total</th><th>Success</th><th>Failed</th><th>Rate</th><th>Reasons</th></tr></thead><tbody>';
D.agents.forEach((a,i)=>{const u2=a.usage;const rc=u2.success_rate!=null?(u2.success_rate>=95?'var(--grn)':u2.success_rate>=70?'var(--yel)':'var(--red)'):'var(--tx3)';
h+='<tr><td>'+IC[i%IC.length]+' '+a.script_name+'</td><td>'+(u2.total_requests!=null?fmt(u2.total_requests):'<span class="nd">—</span>')+'</td>';
h+='<td><span class="sd sg"></span>'+(u2.successful_requests!=null?fmt(u2.successful_requests):'—')+'</td>';
h+='<td><span class="sd '+((u2.failed_requests||0)>0?'sr2':'sg')+'"></span>'+(u2.failed_requests||0)+'</td>';
h+='<td style="color:'+rc+';font-weight:700">'+(u2.success_rate!=null?u2.success_rate+'%':'N/A')+'</td>';
h+='<td style="max-width:250px">';
const uf=Object.entries(u2.failure_reasons||{});
h+=uf.length?uf.map(([r,c])=>'<div class="fr"><span class="fd"></span>'+r+' <b style="color:var(--red)">('+c+'x)</b></div>').join(''):'<span style="color:var(--grn);font-size:10px">✅ None</span>';
h+='</td></tr>'});
h+='</tbody></table></div>';
document.getElementById('t-fl').innerHTML=h}

const clips=['polygon(50% 0%,100% 25%,100% 75%,50% 100%,0% 75%,0% 25%)','polygon(50% 0%,100% 38%,82% 100%,18% 100%,0% 38%)','polygon(30% 0%,70% 0%,100% 30%,100% 70%,70% 100%,30% 100%,0% 70%,0% 30%)'];

function renderTr(){const aps=new Set(D.agents.map(a=>a.script_path));
function nd(n){if(n.type==='folder'){const b=n.agent_count>0?'<span class="tbg">'+n.agent_count+' 🤖</span>':'';
const ch=(n.children||[]).map(c=>nd(c)).join('');
return'<div class="tn"><span class="tfo" onclick="tgl(this)">📂 '+n.name+b+'</span><div class="tc2">'+ch+'</div></div>'}
const ia=aps.has(n.path);return'<div class="tn"><span class="tfi'+(ia?' ia':'')+'">'+( ia?'🤖':'📄')+' '+n.name+(ia?'<span class="tbg abg">Agent</span>':'')+'</span></div>'}
document.getElementById('t-tr').innerHTML='<div class="tb"><div style="margin-bottom:10px;font-size:12px;font-weight:600;color:var(--cyan)"><i class="fas fa-folder-tree"></i> '+D.scan_root+'</div>'+nd(D.folder_tree)+'</div>'}

function tgl(el){const ch=el.nextElementSibling;if(ch)ch.style.display=ch.style.display==='none'?'block':'none'}

function donut(data,sz){const e=Object.entries(data);const t=e.reduce((s,[,v])=>s+v,0);
if(!t)return'<svg width="'+sz+'" height="'+sz+'"><circle cx="'+(sz/2)+'" cy="'+(sz/2)+'" r="'+(sz*.35)+'" fill="none" stroke="rgba(255,255,255,0.06)" stroke-width="'+(sz*.12)+'"/></svg>';
const cx=sz/2,cy=sz/2,r=sz*.35,cc=2*Math.PI*r;let off=0,p='';
e.forEach(([,v],i)=>{const d=(v/t)*cc;p+='<circle cx="'+cx+'" cy="'+cy+'" r="'+r+'" fill="none" stroke="'+C[i%C.length]+'" stroke-width="'+(sz*.12)+'" stroke-dasharray="'+d+' '+(cc-d)+'" stroke-dashoffset="'+(-off)+'" transform="rotate(-90 '+cx+' '+cy+')" style="transition:all 0.5s"/>';off+=d});
return'<svg width="'+sz+'" height="'+sz+'" viewBox="0 0 '+sz+' '+sz+'">'+p+'</svg>'}
</script>
</body>
</html>'''


# ============================================================
# FLASK APPLICATION (if Flask available)
# ============================================================
if USE_FLASK:
    application = Flask(__name__)
    app = application

    @application.route("/", methods=["GET"])
    @application.route("/dashboard", methods=["GET"])
    def dashboard():
        return Response(get_dashboard_html(), mimetype="text/html")

    @application.route("/api/scan", methods=["GET"])
    def api_scan():
        try:
            return jsonify(get_scan_data())
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    @application.route("/api/rescan", methods=["GET", "POST"])
    def api_rescan():
        try:
            return jsonify(get_scan_data(force=True))
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    @application.route("/api/agent/<agent_id>", methods=["GET"])
    def api_agent(agent_id):
        data = get_scan_data()
        for a in data.get("agents", []):
            if a["id"] == agent_id:
                return jsonify(a)
        return jsonify({"error": "Not found"}), 404

    @application.route("/health", methods=["GET"])
    @application.route("/health-check", methods=["GET"])
    def health():
        return jsonify({"status": "healthy", "service": "AI Agent Scanner"}), 200

    @application.errorhandler(404)
    def e404(e):
        return jsonify({"error": "Not found"}), 404

    @application.errorhandler(405)
    def e405(e):
        return jsonify({"error": "Method not allowed"}), 405

    @application.errorhandler(500)
    def e500(e):
        return jsonify({"error": "Server error"}), 500


# ============================================================
# FALLBACK: Built-in HTTP server (no Flask)
# ============================================================
else:
    from http.server import HTTPServer, BaseHTTPRequestHandler
    from urllib.parse import urlparse

    class FallbackHandler(BaseHTTPRequestHandler):
        def do_GET(self):
            path = urlparse(self.path).path
            if path in ("/", "/dashboard"):
                self._html(get_dashboard_html())
            elif path == "/api/scan":
                self._json(get_scan_data())
            elif path in ("/api/rescan",):
                self._json(get_scan_data(force=True))
            elif path in ("/health", "/health-check"):
                self._json({"status": "healthy"})
            else:
                self.send_error(404)

        def do_POST(self):
            self.do_GET()

        def _html(self, content):
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(content.encode("utf-8"))

        def _json(self, data):
            body = json.dumps(data, indent=2, default=str).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *a):
            pass

    application = None  # No WSGI app for fallback


# ============================================================
# MAIN ENTRY POINT
# ============================================================
def main():
    print("\n" + "=" * 58)
    print("🤖  AI AGENT SCANNER - SINGLE FILE EDITION")
    print("=" * 58)
    print(f"  ✅ 100% real data - no hardcoded/simulated values")
    print(f"  ✅ Reads: source code, log files, .env, config.json")
    print(f"  ✅ {'Flask mode (production-ready)' if USE_FLASK else 'Fallback HTTPServer mode'}")
    print(f"  📁 Scan root: {os.path.abspath(SCAN_ROOT)}")
    print()

    # Pre-scan
    data = get_scan_data()
    s = data["scan_stats"]
    sm = data["summary"]
    print(f"📊 Scan Complete!")
    print(f"   📂 Folders: {s['total_folders_scanned']}")
    print(f"   📄 Files:   {s['total_files_scanned']}")
    print(f"   🤖 Agents:  {s['total_agents_found']}")
    print(f"   ⏱️  Time:    {s['scan_duration_ms']}ms")

    for i, agent in enumerate(data["agents"], 1):
        u = agent["usage"]
        src = u.get("data_source", "none")
        print(f"\n  {i}. {agent['script_name']}")
        print(f"     📍 {agent['relative_path']}")
        print(f"     🏢 {', '.join(agent['providers'])}")
        print(f"     🧠 {', '.join(agent['models'][:3])}")
        print(f"     🎯 {', '.join(agent['areas'])}")
        print(f"     📊 {'✅ Real logs' if src == 'log_files' else '⚠️  No logs found'}")

    print(f"\n{'─' * 58}")

    import webbrowser

    if USE_FLASK:
        print(f"🌐 http://localhost:{SERVER_PORT}")
        threading.Timer(1.5, lambda: webbrowser.open(f"http://localhost:{SERVER_PORT}")).start()
        application.run(host="0.0.0.0", port=SERVER_PORT, debug=False)
    else:
        print(f"🌐 http://localhost:{SERVER_PORT}")
        print("   (Install flask for production: pip install flask gunicorn)")
        threading.Timer(1.5, lambda: webbrowser.open(f"http://localhost:{SERVER_PORT}")).start()
        server = HTTPServer(("", SERVER_PORT), FallbackHandler)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            print("\n👋 Stopped.")
            server.server_close()


if __name__ == "__main__":
    main()
#!/usr/bin/env python3
"""
AI Agent Scanner & Dashboard for SentinelOps-Lite.

This file is imported by app.py or run standalone.
It registers a Flask Blueprint at /scanner with full
HTML+CSS+JS dashboard inline.

Usage:
  # If app.py imports this:
  from agent_monitor import scanner_bp
  application.register_blueprint(scanner_bp)

  # Or standalone:
  python agent_monitor.py
"""

import os
import re
import json
import time
import hashlib
import threading
from datetime import datetime
from flask import Blueprint, Flask, jsonify, request, Response

# ════════════════════════════════════════════════════════════
# BLUEPRINT SETUP
# Register this in your app.py with:
#   from agent_monitor import scanner_bp
#   application.register_blueprint(scanner_bp)
# ════════════════════════════════════════════════════════════
scanner_bp = Blueprint("scanner", __name__)

SCAN_ROOT = os.environ.get(
    "SCAN_ROOT",
    os.path.dirname(os.path.abspath(__file__))
)
_cache = {"data": None, "lock": threading.Lock()}

# ════════════════════════════════════════════════════════════
# AI DETECTION PATTERNS
# ════════════════════════════════════════════════════════════
AI_PROVIDERS = {
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
            "gpt-3.5-turbo", "o1-preview", "o1-mini", "o3-mini",
            "dall-e-3", "dall-e-2", "whisper-1", "tts-1",
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
            "claude-3-opus", "claude-3-sonnet",
            "claude-3-haiku", "claude-2.1", "claude-2",
        ],
    },
    "Google AI / Gemini": {
        "imports": [
            r"import\s+google\.generativeai",
            r"from\s+google\.generativeai",
            r"genai\.GenerativeModel", r"GOOGLE_API_KEY",
            r"import\s+vertexai", r"from\s+vertexai",
            r"AI_PROVIDER.*gemini", r"AI_MODEL.*gemini",
            r"gemini-\d", r"GenerativeModel\s*\(",
        ],
        "env_keys": [
            "GOOGLE_API_KEY",
            "GOOGLE_APPLICATION_CREDENTIALS",
        ],
        "models": [
            "gemini-2.5-flash", "gemini-2.0-flash",
            "gemini-1.5-pro", "gemini-1.5-flash",
            "gemini-pro", "gemini-ultra",
        ],
    },
    "Hugging Face": {
        "imports": [
            r"from\s+transformers", r"import\s+transformers",
            r"pipeline\s*\(", r"AutoModel",
            r"from\s+huggingface_hub",
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
            r"COHERE_API_KEY",
        ],
        "env_keys": ["COHERE_API_KEY"],
        "models": ["command-r-plus", "command-r", "command"],
    },
    "Mistral AI": {
        "imports": [
            r"from\s+mistralai", r"import\s+mistralai",
            r"MISTRAL_API_KEY", r"Mistral\s*\(",
        ],
        "env_keys": ["MISTRAL_API_KEY"],
        "models": [
            "mistral-large", "mistral-medium",
            "mistral-small", "codestral",
        ],
    },
    "Groq": {
        "imports": [
            r"import\s+groq", r"from\s+groq",
            r"Groq\s*\(", r"GROQ_API_KEY",
        ],
        "env_keys": ["GROQ_API_KEY"],
        "models": ["llama3", "mixtral", "gemma"],
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
            "codellama", "phi", "gemma",
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
            r"Crew\s*\(", r"Agent\s*\(.*role\s*=",
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
        "models": ["amazon.titan", "anthropic.claude"],
    },
    "Azure OpenAI": {
        "imports": [
            r"AzureOpenAI\s*\(", r"azure_endpoint",
            r"AZURE_OPENAI",
        ],
        "env_keys": ["AZURE_OPENAI_API_KEY"],
        "models": ["gpt-4", "gpt-35-turbo"],
    },
    "Replicate": {
        "imports": [
            r"import\s+replicate", r"from\s+replicate",
            r"REPLICATE_API_TOKEN",
        ],
        "env_keys": ["REPLICATE_API_TOKEN"],
        "models": [],
    },
}

AI_FRAMEWORKS = {
    "LangChain Agent": [
        r"AgentExecutor", r"create_react_agent",
        r"initialize_agent",
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
    ],
    "Prometheus Monitor": [
        r"from\s+prometheus_client",
        r"import\s+prometheus_client",
        r"Counter\s*\(", r"Gauge\s*\(",
    ],
    "PSUtil Monitor": [
        r"import\s+psutil",
        r"psutil\.Process",
        r"psutil\.cpu_percent",
    ],
}

AI_AREAS = {
    "Chatbot / Conversational": [
        r"\bchat\b", r"\bconversation\b",
        r"\bchatbot\b", r"\bassistant\b",
    ],
    "Monitoring / Observability": [
        r"\bmonitor\b", r"\bmetric\b", r"\bprometheus\b",
        r"\bpsutil\b", r"\bcpu\b", r"\bmemory\b", r"\bhealth\b",
    ],
    "Code Generation": [
        r"\bcode[-_]?gen", r"\bcoding\b", r"\brefactor\b",
    ],
    "Data Analysis": [
        r"\bpandas\b", r"\bdataframe\b", r"\bcsv\b", r"\banalyz",
    ],
    "DevOps / Automation": [
        r"\bdeploy\b", r"\bdocker\b", r"\bkubernetes\b",
        r"\bci[-_]?cd\b", r"\bautomat",
    ],
    "API / Backend Service": [
        r"\bflask\b", r"\bfastapi\b", r"\bdjango\b",
        r"\bendpoint\b", r"\bjsonify\b", r"\broute\b",
    ],
    "Image Generation": [
        r"\bdall[-_]?e\b", r"\bstable[-_]?diffusion\b",
        r"\bimage[-_]?gen",
    ],
    "NLP / Text Processing": [
        r"\bsummariz", r"\btranslat",
        r"\bsentiment\b", r"\bnlp\b",
    ],
    "RAG / Knowledge Base": [
        r"\bvector[-_]?store\b", r"\bchromadb\b",
        r"\bpinecone\b", r"\brag\b",
    ],
    "Research / Search": [
        r"\bsearch\b", r"\bresearch\b", r"\bwikipedia\b",
    ],
    "Finance / Trading": [
        r"\btrading\b", r"\bstock\b", r"\bcrypto\b",
    ],
    "Web Scraping": [
        r"\bscrape\b", r"\bcrawl\b",
        r"\bbeautifulsoup\b", r"\bselenium\b",
    ],
    "Email / Communication": [
        r"\bemail\b", r"\bsmtp\b",
        r"\bsendgrid\b", r"\bslack\b",
    ],
}


# ════════════════════════════════════════════════════════════
# LOG FILE READER — real data only
# ════════════════════════════════════════════════════════════
class LogReader:
    EXTS = {".log", ".txt", ".json", ".jsonl", ".out"}

    def __init__(self, script_path):
        self.dir = os.path.dirname(script_path)
        self.name = os.path.splitext(
            os.path.basename(script_path)
        )[0]

    def parse(self):
        logs = self._find()
        r = {
            "log_files": [os.path.basename(f) for f in logs],
            "total": 0, "ok": 0, "fail": 0,
            "tokens": 0, "ptok": 0, "ctok": 0,
            "failures": {}, "rtimes": [],
            "avg_rt": None, "last_t": None,
            "source": "no_logs" if not logs else "log_files",
        }
        for f in logs:
            self._read(f, r)
        if r["rtimes"]:
            r["avg_rt"] = round(
                sum(r["rtimes"]) / len(r["rtimes"]), 2
            )
        if (r["ok"] + r["fail"]) > r["total"]:
            r["total"] = r["ok"] + r["fail"]
        return r

    def _find(self):
        found = []
        dirs = [
            self.dir,
            os.path.join(self.dir, "logs"),
            os.path.join(self.dir, ".."),
            os.path.join(self.dir, "..", "logs"),
        ]
        for d in dirs:
            if not os.path.isdir(d):
                continue
            try:
                for fn in os.listdir(d):
                    fp = os.path.join(d, fn)
                    if not os.path.isfile(fp):
                        continue
                    if (
                        os.path.splitext(fn)[1].lower()
                        not in self.EXTS
                    ):
                        continue
                    nl = fn.lower()
                    if any(
                        k in nl
                        for k in [
                            self.name.lower(), "log",
                            "usage", "request", "api",
                        ]
                    ):
                        found.append(fp)
            except PermissionError:
                pass
        return list(set(found))

    def _read(self, path, r):
        try:
            sz = os.path.getsize(path)
            if sz == 0 or sz > 50 * 1024 * 1024:
                return
            with open(
                path, "r", encoding="utf-8", errors="ignore"
            ) as f:
                raw = f.read()
        except Exception:
            return

        if path.endswith(".jsonl"):
            for line in raw.splitlines():
                line = line.strip()
                if line:
                    try:
                        self._entry(json.loads(line), r)
                    except Exception:
                        pass
        elif path.endswith(".json"):
            try:
                d = json.loads(raw)
                items = d if isinstance(d, list) else [d]
                for item in items:
                    if isinstance(item, dict):
                        self._entry(item, r)
                        for k in ("requests", "events", "logs"):
                            if (
                                k in item
                                and isinstance(item[k], list)
                            ):
                                for sub in item[k]:
                                    if isinstance(sub, dict):
                                        self._entry(sub, r)
            except Exception:
                self._text(raw, r)
        else:
            self._text(raw, r)

        ts = re.findall(
            r'(\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2})', raw
        )
        if ts:
            r["last_t"] = ts[-1]

    def _entry(self, e, r):
        u = e.get("usage", {})
        if isinstance(u, dict):
            pt = u.get("prompt_tokens", 0) or 0
            ct = u.get("completion_tokens", 0) or 0
            tt = u.get("total_tokens", 0) or 0
            r["ptok"] += pt
            r["ctok"] += ct
            r["tokens"] += tt or (pt + ct)
        st = e.get("status") or e.get("status_code")
        if st is not None:
            s = str(st)
            if s in ("200", "success", "ok", "OK"):
                r["ok"] += 1
                r["total"] += 1
            elif s in ("error", "failed") or (
                isinstance(st, int) and st >= 400
            ):
                r["fail"] += 1
                r["total"] += 1
                err = (
                    e.get("error")
                    or e.get("message")
                    or f"HTTP {st}"
                )
                if err:
                    r["failures"][str(err)] = (
                        r["failures"].get(str(err), 0) + 1
                    )
        for k in (
            "response_time", "duration", "elapsed", "latency"
        ):
            v = e.get(k)
            if isinstance(v, (int, float)) and v > 0:
                r["rtimes"].append(
                    round(v * 1000 if v < 100 else v, 2)
                )
                break

    def _text(self, raw, r):
        OK_P = [
            r'HTTP/\d\.\d"\s+200',
            r'"status":\s*200',
            r'"status":\s*"success"',
        ]
        ER_P = [
            r'HTTP/\d\.\d"\s+[45]\d\d',
            r'"status":\s*[45]\d\d',
            r'Error|ERROR|Exception|FAILED',
            r'RateLimitError|APIError',
        ]
        for line in raw.splitlines():
            m = re.search(r'"total_tokens":\s*(\d+)', line)
            if m:
                r["tokens"] += int(m.group(1))
                continue
            pt = re.search(
                r'prompt_tokens["\s:=]+(\d+)', line
            )
            ct = re.search(
                r'completion_tokens["\s:=]+(\d+)', line
            )
            if pt:
                r["ptok"] += int(pt.group(1))
            if ct:
                r["ctok"] += int(ct.group(1))
            if pt or ct:
                r["tokens"] += (
                    (int(pt.group(1)) if pt else 0)
                    + (int(ct.group(1)) if ct else 0)
                )
                continue
            if any(re.search(p, line, re.I) for p in OK_P):
                r["ok"] += 1
                r["total"] += 1
                continue
            if any(re.search(p, line, re.I) for p in ER_P):
                r["fail"] += 1
                r["total"] += 1
                m2 = re.search(
                    r'(Error|Exception)[:\s]+([^\n]{5,80})',
                    line, re.I,
                )
                if m2:
                    k = m2.group(2).strip()
                    r["failures"][k] = (
                        r["failures"].get(k, 0) + 1
                    )


# ════════════════════════════════════════════════════════════
# ENV & CONFIG READER
# ════════════════════════════════════════════════════════════
class EnvReader:
    def __init__(self, script_path, providers):
        self.dir = os.path.dirname(script_path)
        self.providers = providers

    def api_keys(self):
        env = self._load()
        found = {}
        for p in self.providers:
            info = AI_PROVIDERS.get(p, {})
            for k in info.get("env_keys", []):
                v = env.get(k, "")
                found[k] = bool(
                    v
                    and v
                    not in ("YOUR_KEY", "sk-xxx", "your_key_here", "")
                )
        return found

    def config(self):
        cfg = {}
        for d in [self.dir, os.path.join(self.dir, "..")]:
            for fn in (
                "config.json",
                "settings.json",
                "agent_config.json",
            ):
                fp = os.path.join(d, fn)
                if os.path.isfile(fp):
                    try:
                        with open(fp) as f:
                            cfg.update(json.load(f))
                    except Exception:
                        pass
        return cfg

    def _load(self):
        env = dict(os.environ)
        dirs = [
            self.dir,
            os.path.join(self.dir, ".."),
            os.path.join(self.dir, "..", ".."),
        ]
        for d in dirs:
            for fn in (".env", ".env.local", "config.env"):
                fp = os.path.join(d, fn)
                if os.path.isfile(fp):
                    try:
                        with open(fp, errors="ignore") as f:
                            for line in f:
                                line = line.strip()
                                if (
                                    line
                                    and not line.startswith("#")
                                    and "=" in line
                                ):
                                    k, _, v = line.partition("=")
                                    env[k.strip()] = (
                                        v.strip()
                                        .strip('"')
                                        .strip("'")
                                    )
                    except Exception:
                        pass
        return env


# ════════════════════════════════════════════════════════════
# SOURCE CODE ANALYZER
# ════════════════════════════════════════════════════════════
class Analyzer:
    def __init__(self, path, content):
        self.path = path
        self.content = content

    def description(self):
        for pat in (r'^"""(.*?)"""', r"^'''(.*?)'''"):
            m = re.search(pat, self.content, re.DOTALL)
            if m:
                txt = m.group(1).strip()
                lines = [
                    l.strip() for l in txt.split("\n")
                    if l.strip()
                ]
                return " ".join(lines[:3])[:250]
        for line in self.content.split("\n")[:15]:
            s = line.strip()
            if (
                s.startswith(("//", "#"))
                and not s.startswith("#!")
            ):
                c = re.sub(r'^[/#\s]+', '', s).strip()
                if len(c) > 8:
                    return c[:250]
        n = os.path.splitext(
            os.path.basename(self.path)
        )[0]
        return n.replace("_", " ").replace("-", " ").title()

    def providers(self):
        found = []
        for name, info in AI_PROVIDERS.items():
            for pat in info["imports"]:
                if re.search(pat, self.content, re.I):
                    found.append(name)
                    break
        return found

    def models(self):
        found = []
        for info in AI_PROVIDERS.values():
            for m in info.get("models", []):
                if (
                    re.search(re.escape(m), self.content, re.I)
                    and m not in found
                ):
                    found.append(m)
        for m in re.findall(
            r'''(?:model\s*=\s*|"model"\s*:\s*|'''
            r'''AI_MODEL.*?[=:]\s*)['"]([\w.:\-/]+)['"]''',
            self.content,
        ):
            if len(m) > 3 and m not in found:
                found.append(m)
        for m in re.findall(
            r'"(gemini[\w.\-]+|gpt[\w.\-]+|'
            r'claude[\w.\-]+|llama[\w.\-]+)"',
            self.content,
        ):
            if m not in found:
                found.append(m)
        return found

    def frameworks(self):
        found = []
        for fw, pats in AI_FRAMEWORKS.items():
            if any(
                re.search(p, self.content, re.I) for p in pats
            ):
                found.append(fw)
        return found

    def areas(self):
        found = []
        for area, pats in AI_AREAS.items():
            if (
                sum(
                    1 for p in pats
                    if re.search(p, self.content, re.I)
                )
                >= 2
            ):
                found.append(area)
        return found

    def api_calls(self):
        pats = [
            r'\.create\s*\(',
            r'\.generate\s*\(',
            r'\.chat\s*\(',
            r'\.complete\s*\(',
            r'\.messages\.create\s*\(',
            r'jsonify\s*\(',
        ]
        return sum(
            len(re.findall(p, self.content)) for p in pats
        )


# ════════════════════════════════════════════════════════════
# FOLDER SCANNER
# ════════════════════════════════════════════════════════════
class FolderScanner:
    EXTS = {".py", ".js", ".ts", ".jsx", ".tsx", ".mjs"}
    SKIP = {
        "__pycache__", "node_modules", ".git", "venv",
        "env", ".venv", "dist", "build", ".next",
        ".ebextensions", ".elasticbeanstalk",
        "site-packages", ".platform", "htmlcov",
        ".pytest_cache",
    }

    def __init__(self, root):
        self.root = os.path.abspath(root)
        self.agents = []
        self.nfiles = 0
        self.nfolders = 0

    def scan(self):
        t0 = time.time()
        start = datetime.now().isoformat()
        tree = self._tree(self.root)
        self._walk(self.root)
        ms = round((time.time() - t0) * 1000, 2)
        end = datetime.now().isoformat()

        for a in self.agents:
            self._mark(tree, a["script_path"])

        projects = self._group()
        return {
            "scan_root": self.root,
            "scan_stats": {
                "total_files_scanned": self.nfiles,
                "total_folders_scanned": self.nfolders,
                "total_agents_found": len(self.agents),
                "scan_start": start,
                "scan_end": end,
                "scan_duration_ms": ms,
            },
            "folder_tree": tree,
            "agents": self.agents,
            "projects": projects,
            "summary": self._summary(projects),
        }

    def _tree(self, path, depth=0):
        node = {
            "name": os.path.basename(path) or path,
            "path": path, "type": "folder",
            "depth": depth, "children": [],
            "agent_count": 0,
        }
        self.nfolders += 1
        try:
            entries = sorted(os.listdir(path))
        except PermissionError:
            return node
        for e in entries:
            fp = os.path.join(path, e)
            if os.path.isdir(fp):
                if not e.startswith(".") and e not in self.SKIP:
                    node["children"].append(
                        self._tree(fp, depth + 1)
                    )
            elif os.path.isfile(fp):
                if (
                    os.path.splitext(e)[1].lower()
                    in self.EXTS
                ):
                    node["children"].append({
                        "name": e, "path": fp,
                        "type": "file", "depth": depth + 1,
                    })
        return node

    def _mark(self, node, fpath):
        if node["type"] == "file":
            if node["path"] == fpath:
                node["is_agent"] = True
        elif (
            node["type"] == "folder"
            and fpath.startswith(node["path"])
        ):
            node["agent_count"] += 1
            for c in node.get("children", []):
                self._mark(c, fpath)

    def _walk(self, path):
        try:
            entries = os.listdir(path)
        except PermissionError:
            return
        for e in entries:
            fp = os.path.join(path, e)
            if os.path.isdir(fp):
                if not e.startswith(".") and e not in self.SKIP:
                    self._walk(fp)
            elif os.path.isfile(fp):
                if (
                    os.path.splitext(e)[1].lower()
                    in self.EXTS
                ):
                    self.nfiles += 1
                    self._check(fp)

    def _check(self, fp):
        try:
            with open(
                fp, "r", encoding="utf-8", errors="ignore"
            ) as f:
                content = f.read()
        except Exception:
            return
        if len(content.strip()) < 20:
            return

        az = Analyzer(fp, content)
        provs = az.providers()
        fws = az.frameworks()
        if not provs and not fws:
            return

        models = az.models()
        areas = az.areas()
        desc = az.description()
        calls = az.api_calls()

        lr = LogReader(fp)
        ld = lr.parse()
        er = EnvReader(fp, provs)
        keys = er.api_keys()
        cfg = er.config()

        total = ld.get("total", 0)
        ok = ld.get("ok", 0)
        fail = ld.get("fail", 0)
        tokens = ld.get("tokens", 0)
        tlim = (
            cfg.get("token_limit")
            or cfg.get("max_tokens_total")
        )

        self.agents.append({
            "id": hashlib.md5(fp.encode()).hexdigest()[:12],
            "script_name": os.path.basename(fp),
            "script_path": fp,
            "relative_path": os.path.relpath(fp, self.root),
            "folder": (
                os.path.dirname(
                    os.path.relpath(fp, self.root)
                )
                or "."
            ),
            "providers": provs,
            "models": models or ["Not specified"],
            "frameworks": fws or ["Direct API"],
            "areas": areas or ["General Purpose"],
            "description": desc,
            "file_size_bytes": os.path.getsize(fp),
            "lines_of_code": content.count("\n") + 1,
            "api_call_sites": calls,
            "last_modified": datetime.fromtimestamp(
                os.path.getmtime(fp)
            ).isoformat(),
            "api_keys": keys,
            "usage": {
                "data_source": ld.get("source", "none"),
                "log_files_found": ld.get("log_files", []),
                "total_requests": total or None,
                "successful": ok or None,
                "failed": fail,
                "success_rate": (
                    round(ok / total * 100, 1)
                    if total > 0
                    else None
                ),
                "tokens_used": tokens or None,
                "prompt_tokens": ld.get("ptok") or None,
                "completion_tokens": ld.get("ctok") or None,
                "tokens_available": tlim,
                "tokens_pct": (
                    round(tokens / tlim * 100, 1)
                    if tokens and tlim
                    else None
                ),
                "rpm": cfg.get("rpm"),
                "tpm": cfg.get("tpm"),
                "rpd": cfg.get("rpd"),
                "failure_reasons": ld.get("failures", {}),
                "avg_rt_ms": ld.get("avg_rt"),
                "last_request_time": ld.get("last_t"),
            },
        })

    def _group(self):
        pmap = {}
        for a in self.agents:
            parts = a["folder"].replace("\\", "/").split("/")
            top = (
                parts[0]
                if parts and parts[0] not in (".", "")
                else "Root"
            )
            pmap.setdefault(top, []).append(a)
        result = []
        for name, agents in pmap.items():
            result.append({
                "project_name": name,
                "agent_count": len(agents),
                "agents": [
                    {
                        "id": a["id"],
                        "script_name": a["script_name"],
                        "providers": a["providers"],
                        "models": a["models"],
                        "areas": a["areas"],
                        "description": a["description"][:100],
                    }
                    for a in agents
                ],
                "providers_used": list(
                    {p for a in agents for p in a["providers"]}
                ),
                "models_used": list(
                    {m for a in agents for m in a["models"]}
                ),
                "total_requests": (
                    sum(
                        a["usage"]["total_requests"] or 0
                        for a in agents
                    )
                    or None
                ),
                "total_tokens": (
                    sum(
                        a["usage"]["tokens_used"] or 0
                        for a in agents
                    )
                    or None
                ),
                "total_ok": (
                    sum(
                        a["usage"]["successful"] or 0
                        for a in agents
                    )
                    or None
                ),
                "total_fail": sum(
                    a["usage"]["failed"] or 0
                    for a in agents
                ),
            })
        return result

    def _summary(self, projects):
        pc, ac, mc = {}, {}, {}
        tr = ts = tf = tt = 0
        fr = {}
        for a in self.agents:
            for p in a["providers"]:
                pc[p] = pc.get(p, 0) + 1
            for ar in a["areas"]:
                ac[ar] = ac.get(ar, 0) + 1
            for m in a["models"]:
                mc[m] = mc.get(m, 0) + 1
            u = a["usage"]
            tr += u["total_requests"] or 0
            ts += u["successful"] or 0
            tf += u["failed"] or 0
            tt += u["tokens_used"] or 0
            for reason, cnt in u.get(
                "failure_reasons", {}
            ).items():
                fr[reason] = fr.get(reason, 0) + cnt
        return {
            "total_agents": len(self.agents),
            "total_projects": len(projects),
            "providers_breakdown": pc,
            "area_breakdown": ac,
            "model_breakdown": mc,
            "overall_usage": {
                "total_requests": tr or None,
                "total_successful": ts or None,
                "total_failed": tf,
                "success_rate": (
                    round(ts / tr * 100, 1)
                    if tr > 0
                    else None
                ),
                "total_tokens": tt or None,
                "failure_reasons": fr,
            },
        }


# ════════════════════════════════════════════════════════════
# CACHE HELPER
# ════════════════════════════════════════════════════════════
def get_data(force=False):
    with _cache["lock"]:
        if _cache["data"] is None or force:
            s = FolderScanner(SCAN_ROOT)
            _cache["data"] = s.scan()
        return _cache["data"]


# ════════════════════════════════════════════════════════════
# BLUEPRINT ROUTES
# ════════════════════════════════════════════════════════════
@scanner_bp.route("/scanner", methods=["GET"])
def scanner_page():
    return Response(
        SCANNER_HTML, mimetype="text/html", status=200
    )


@scanner_bp.route("/scanner/api/scan", methods=["GET"])
def scanner_api():
    try:
        return jsonify(get_data())
    except Exception as ex:
        return jsonify({
            "error": str(ex),
            "agents": [],
            "projects": [],
            "summary": {
                "total_agents": 0,
                "total_projects": 0,
                "providers_breakdown": {},
                "area_breakdown": {},
                "model_breakdown": {},
                "overall_usage": {
                    "total_requests": None,
                    "total_successful": None,
                    "total_failed": 0,
                    "success_rate": None,
                    "total_tokens": None,
                    "failure_reasons": {},
                },
            },
            "scan_stats": {
                "total_files_scanned": 0,
                "total_folders_scanned": 0,
                "total_agents_found": 0,
                "scan_start": None,
                "scan_end": None,
                "scan_duration_ms": 0,
            },
            "folder_tree": {
                "name": "error",
                "type": "folder",
                "children": [],
                "agent_count": 0,
                "path": SCAN_ROOT,
                "depth": 0,
            },
            "scan_root": SCAN_ROOT,
        }), 200


@scanner_bp.route(
    "/scanner/api/rescan", methods=["GET", "POST"]
)
def scanner_rescan():
    try:
        return jsonify(get_data(force=True))
    except Exception as ex:
        return jsonify({"error": str(ex)}), 500


# ════════════════════════════════════════════════════════════
# DASHBOARD HTML + CSS + JS (complete inline)
# ════════════════════════════════════════════════════════════
SCANNER_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>AI Agent Scanner — SentinelOps</title>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800;900&family=JetBrains+Mono:wght@400;600&display=swap" rel="stylesheet">
<link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.5.1/css/all.min.css">
<style>
:root{--bg:#0a0a1a;--bg3:#1a1a3e;--t1:#e8e8ff;--t2:#9999cc;--t3:#6666aa;--cy:#00f5ff;--mg:#ff00ff;--gn:#00ff88;--yl:#ffee00;--og:#ff8800;--rd:#ff3355;--bl:#4488ff;--pu:#aa44ff;--pk:#ff66aa;--tl:#00ccaa;--br:rgba(255,255,255,0.08);--ra:16px}
*,*::before,*::after{box-sizing:border-box;margin:0;padding:0}
body{font-family:'Inter',sans-serif;background:var(--bg);color:var(--t1);min-height:100vh;overflow-x:hidden}
::-webkit-scrollbar{width:6px}::-webkit-scrollbar-track{background:var(--bg)}::-webkit-scrollbar-thumb{background:linear-gradient(var(--cy),var(--pu));border-radius:3px}
.bg{position:fixed;inset:0;z-index:-1;pointer-events:none}.orb{position:absolute;border-radius:50%;filter:blur(80px);animation:fl 20s ease-in-out infinite}
.orb:nth-child(1){width:500px;height:500px;top:-100px;left:-100px;background:rgba(0,245,255,.07)}.orb:nth-child(2){width:400px;height:400px;top:50%;right:-100px;background:rgba(255,0,255,.05);animation-delay:-7s}.orb:nth-child(3){width:600px;height:600px;bottom:-200px;left:30%;background:rgba(0,255,136,.04);animation-delay:-14s}
@keyframes fl{0%,100%{transform:translate(0,0)}50%{transform:translate(40px,-40px)}}
.hd{background:rgba(18,18,42,.96);backdrop-filter:blur(20px);border-bottom:1px solid var(--br);padding:14px 28px;display:flex;align-items:center;justify-content:space-between;position:sticky;top:0;z-index:100;flex-wrap:wrap;gap:10px}
.logo{width:44px;height:44px;border-radius:12px;font-size:20px;background:linear-gradient(135deg,var(--cy),var(--pu));display:flex;align-items:center;justify-content:center;animation:gw 3s infinite}
@keyframes gw{0%,100%{box-shadow:0 0 15px rgba(0,245,255,.3)}50%{box-shadow:0 0 30px rgba(0,245,255,.5)}}
.brd{display:flex;align-items:center;gap:12px}.brd h1{font-size:18px;font-weight:800;background:linear-gradient(135deg,var(--cy),var(--pu));-webkit-background-clip:text;-webkit-text-fill-color:transparent}.brd p{font-size:10px;color:var(--t3)}
.hr{display:flex;align-items:center;gap:8px}.sp{background:rgba(255,255,255,.05);border:1px solid var(--br);border-radius:8px;padding:5px 12px;font-size:10px;color:var(--t3);font-family:'JetBrains Mono';max-width:240px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.btn{padding:8px 16px;border:none;border-radius:10px;font-size:11px;font-weight:600;cursor:pointer;display:flex;align-items:center;gap:6px;font-family:'Inter';transition:all .3s}
.bp{background:linear-gradient(135deg,var(--cy),var(--pu));color:#000}.bp:hover{transform:translateY(-2px);box-shadow:0 4px 15px rgba(0,245,255,.35)}
.bs{background:rgba(255,255,255,.07);color:var(--t1);border:1px solid var(--br)}
.bk{background:rgba(255,136,0,.15);color:var(--og);border:1px solid rgba(255,136,0,.3);text-decoration:none;padding:8px 16px;border-radius:10px;font-size:11px;font-weight:600;display:flex;align-items:center;gap:6px}
.mn{padding:22px 28px;max-width:1800px;margin:0 auto}
.sr{display:grid;grid-template-columns:repeat(auto-fit,minmax(155px,1fr));gap:11px;margin-bottom:20px}
.sc{background:var(--bg3);border:1px solid var(--br);border-radius:var(--ra);padding:15px;position:relative;overflow:hidden;transition:all .3s}.sc:hover{transform:translateY(-3px);border-color:rgba(0,245,255,.3);box-shadow:0 6px 20px rgba(0,0,0,.3)}
.si{width:36px;height:36px;border-radius:9px;font-size:16px;display:flex;align-items:center;justify-content:center;margin-bottom:7px}
.sv{font-size:22px;font-weight:800;font-family:'JetBrains Mono'}.sl{font-size:9px;color:var(--t3);margin-top:2px;text-transform:uppercase;letter-spacing:1px}
.sb{position:absolute;bottom:0;left:0;height:3px;width:100%}
.tabs{display:flex;gap:3px;margin-bottom:18px;background:rgba(255,255,255,.03);border-radius:12px;padding:3px;flex-wrap:wrap}
.tab{padding:8px 14px;border-radius:9px;cursor:pointer;font-size:11px;font-weight:600;color:var(--t3);display:flex;align-items:center;gap:5px;white-space:nowrap;transition:all .3s}
.tab:hover{color:var(--t1);background:rgba(255,255,255,.05)}.tab.on{background:linear-gradient(135deg,var(--cy),var(--pu));color:#000}
.tp{display:none;animation:fi .3s ease}.tp.on{display:block}@keyframes fi{from{opacity:0;transform:translateY(8px)}to{opacity:1;transform:translateY(0)}}
.g2{display:grid;grid-template-columns:1fr 1fr;gap:14px}.g3{display:grid;grid-template-columns:repeat(auto-fill,minmax(310px,1fr));gap:14px}.s2{grid-column:span 2}
.cd{background:var(--bg3);border:1px solid var(--br);border-radius:var(--ra);padding:18px;transition:border-color .3s}.cd:hover{border-color:rgba(0,245,255,.15)}
.ch{display:flex;justify-content:space-between;align-items:center;margin-bottom:12px}.ch h3{font-size:13px;font-weight:700;display:flex;align-items:center;gap:7px}
.hex{clip-path:polygon(50% 0%,100% 25%,100% 75%,50% 100%,0% 75%,0% 25%);display:flex;flex-direction:column;align-items:center;justify-content:center;text-align:center;cursor:default;transition:transform .3s}.hex:hover{transform:scale(1.1)}
.pen{clip-path:polygon(50% 0%,100% 38%,82% 100%,18% 100%,0% 38%);display:flex;flex-direction:column;align-items:center;justify-content:center;text-align:center;transition:transform .3s}.pen:hover{transform:scale(1.1) rotate(4deg)}
.oct{clip-path:polygon(30% 0%,70% 0%,100% 30%,100% 70%,70% 100%,30% 100%,0% 70%,0% 30%);display:flex;flex-direction:column;align-items:center;justify-content:center;text-align:center;transition:transform .3s}.oct:hover{transform:scale(1.1) rotate(-4deg)}
.sg{display:flex;flex-wrap:wrap;gap:10px;justify-content:center;padding:6px 0}
.gw{display:flex;flex-wrap:wrap;justify-content:center;gap:16px;padding:8px 0}
.gau{position:relative;width:124px;height:72px;overflow:hidden}.gv{position:absolute;bottom:2px;left:50%;transform:translateX(-50%);font-size:15px;font-weight:800;font-family:'JetBrains Mono'}.gl{position:absolute;bottom:-15px;left:50%;transform:translateX(-50%);font-size:8px;color:var(--t3);white-space:nowrap}
.dw{position:relative;display:inline-block}.dc{position:absolute;top:50%;left:50%;transform:translate(-50%,-50%);text-align:center}.dv{font-size:20px;font-weight:800;font-family:'JetBrains Mono'}.dl{font-size:8px;color:var(--t3)}
.lg{display:flex;flex-wrap:wrap;gap:7px;margin-top:10px}.li{display:flex;align-items:center;gap:4px;font-size:9px}.ld{width:8px;height:8px;border-radius:2px;flex-shrink:0}
.ac{background:var(--bg3);border:1px solid var(--br);border-radius:var(--ra);padding:16px;position:relative;overflow:hidden;transition:all .3s}.ac:hover{transform:translateY(-3px);box-shadow:0 6px 20px rgba(0,0,0,.3);border-color:rgba(0,245,255,.25)}
.ab{position:absolute;top:0;left:0;right:0;height:4px}.ah{display:flex;align-items:flex-start;gap:10px;margin-bottom:10px}
.ai{width:40px;height:40px;border-radius:11px;font-size:18px;display:flex;align-items:center;justify-content:center;flex-shrink:0}
.an{font-size:13px;font-weight:700;word-break:break-all;margin-bottom:2px}.ap{font-size:9px;color:var(--t3);font-family:'JetBrains Mono'}
.ir{display:flex;align-items:flex-start;gap:6px;padding:3px 0;font-size:11px;border-bottom:1px solid rgba(255,255,255,.03)}.ir:last-child{border-bottom:none}
.ii{width:15px;text-align:center;color:var(--cy);flex-shrink:0;font-size:10px;margin-top:1px}.il{color:var(--t3);min-width:62px;flex-shrink:0}.iv{color:var(--t1);flex:1;word-break:break-word}
.tg{display:inline-block;padding:1px 6px;border-radius:20px;font-size:8px;font-weight:600;margin:1px;border:1px solid}
.t-p{background:rgba(0,245,255,.1);color:var(--cy);border-color:rgba(0,245,255,.3)}.t-m{background:rgba(170,68,255,.1);color:var(--pu);border-color:rgba(170,68,255,.3)}
.t-a{background:rgba(0,255,136,.1);color:var(--gn);border-color:rgba(0,255,136,.3)}.t-f{background:rgba(255,136,0,.1);color:var(--og);border-color:rgba(255,136,0,.3)}
.db{background:rgba(0,245,255,.04);border-left:3px solid var(--cy);border-radius:0 7px 7px 0;padding:6px 10px;margin:7px 0;font-size:9px;color:var(--t2);line-height:1.5}
.ug{display:grid;grid-template-columns:repeat(3,1fr);gap:4px;margin-top:7px}.uc{background:rgba(255,255,255,.03);border-radius:7px;padding:6px;text-align:center}
.uv{font-size:12px;font-weight:700;font-family:'JetBrains Mono'}.ul{font-size:7px;color:var(--t3);text-transform:uppercase;margin-top:1px}
.pb{width:100%;height:5px;background:rgba(255,255,255,.06);border-radius:3px;overflow:hidden;margin:5px 0}.pf{height:100%;border-radius:3px;transition:width 1.2s ease}
.bd{display:inline-flex;align-items:center;gap:3px;padding:2px 6px;border-radius:20px;font-size:7px;font-weight:700;text-transform:uppercase;letter-spacing:1px}
.br2{background:rgba(0,255,136,.15);color:var(--gn);border:1px solid rgba(0,255,136,.3)}.bn{background:rgba(255,136,0,.15);color:var(--og);border:1px solid rgba(255,136,0,.3)}
.nd{font-size:8px;color:var(--t3);font-style:italic}
.fe{font-size:8px;color:var(--t3);padding:1px 0}.fd{width:4px;height:4px;border-radius:50%;background:var(--rd);display:inline-block;margin-right:3px}
.dt{width:100%;border-collapse:collapse}.dt th,.dt td{padding:8px 10px;text-align:left;border-bottom:1px solid var(--br);font-size:10px}
.dt th{color:var(--t3);font-weight:600;text-transform:uppercase;font-size:8px}.dt tr:hover{background:rgba(255,255,255,.02)}
.dot{width:5px;height:5px;border-radius:50%;display:inline-block;margin-right:3px}.dg{background:var(--gn)}.dr{background:var(--rd)}
.trb{background:var(--bg3);border:1px solid var(--br);border-radius:var(--ra);padding:14px;max-height:480px;overflow-y:auto}
.tn{padding:2px 0;font-family:'JetBrains Mono';font-size:11px}.tfo{color:var(--yl);cursor:pointer}.tfo:hover{color:var(--og)}
.tfi{color:var(--t2)}.tfi.ia{color:var(--gn);font-weight:600}.tc2{margin-left:16px}
.tbg{background:var(--cy);color:#000;font-size:7px;font-weight:700;padding:1px 5px;border-radius:8px;margin-left:4px;display:inline-block}.tag-a{background:var(--gn)}
.em{text-align:center;padding:30px;color:var(--t3)}.em i{font-size:36px;display:block;margin-bottom:10px;opacity:.4}
.ldr{position:fixed;inset:0;background:rgba(10,10,26,.97);display:flex;flex-direction:column;align-items:center;justify-content:center;z-index:9999}
.spn{width:48px;height:48px;border:4px solid rgba(0,245,255,.2);border-top:4px solid var(--cy);border-radius:50%;animation:spin .9s linear infinite}@keyframes spin{to{transform:rotate(360deg)}}
.lt{margin-top:12px;font-size:13px;color:var(--cy);font-weight:600}
@media(max-width:1100px){.g2{grid-template-columns:1fr}.s2{grid-column:span 1}}@media(max-width:768px){.mn{padding:12px}.sp{display:none}.sr{grid-template-columns:repeat(2,1fr)}}
</style></head><body>
<div class="bg"><div class="orb"></div><div class="orb"></div><div class="orb"></div></div>
<div class="ldr" id="ldr"><div class="spn"></div><div class="lt">Scanning for AI Agents...</div></div>
<header class="hd"><div class="brd"><div class="logo">🤖</div><div><h1>AI Agent Scanner</h1><p id="st">SentinelOps • Loading...</p></div></div>
<div class="hr"><div class="sp" id="spp">📁 ...</div><a href="/" class="bk"><i class="fas fa-arrow-left"></i> Back to App</a>
<button class="btn bs" onclick="exp()"><i class="fas fa-download"></i> Export</button>
<button class="btn bp" onclick="rescan()"><i class="fas fa-sync-alt" id="ri"></i> Rescan</button></div></header>
<main class="mn" id="mn" style="display:none"><div class="sr" id="srow"></div>
<div class="tabs"><div class="tab on" data-p="ov" onclick="stb(this,'ov')"><i class="fas fa-chart-pie"></i> Overview</div>
<div class="tab" data-p="ag" onclick="stb(this,'ag')"><i class="fas fa-robot"></i> Agents</div>
<div class="tab" data-p="pj" onclick="stb(this,'pj')"><i class="fas fa-cubes"></i> Projects</div>
<div class="tab" data-p="us" onclick="stb(this,'us')"><i class="fas fa-chart-bar"></i> Usage</div>
<div class="tab" data-p="fl" onclick="stb(this,'fl')"><i class="fas fa-exclamation-triangle"></i> Failures</div>
<div class="tab" data-p="tr" onclick="stb(this,'tr')"><i class="fas fa-folder-tree"></i> Tree</div></div>
<div class="tp on" id="p-ov"></div><div class="tp" id="p-ag"></div><div class="tp" id="p-pj"></div>
<div class="tp" id="p-us"></div><div class="tp" id="p-fl"></div><div class="tp" id="p-tr"></div></main>
<script>
const CL=['#00f5ff','#ff00ff','#00ff88','#ffee00','#ff8800','#ff3355','#4488ff','#aa44ff','#ff66aa','#00ccaa','#88ff00','#ff4488'];
const GR=['linear-gradient(135deg,#00f5ff,#aa44ff)','linear-gradient(135deg,#ff00ff,#ff8800)','linear-gradient(135deg,#00ff88,#00f5ff)','linear-gradient(135deg,#ffee00,#ff8800)','linear-gradient(135deg,#ff3355,#ff00ff)','linear-gradient(135deg,#4488ff,#00f5ff)','linear-gradient(135deg,#aa44ff,#ff66aa)','linear-gradient(135deg,#00ccaa,#00ff88)'];
const IC=['🤖','🧠','⚡','🔮','🎯','🚀','💡','🔬','📊','🎨','📧','💰','🔧','🌐','📝','🦜'];
const PI={'OpenAI':'🟢','Anthropic':'🟠','Google AI / Gemini':'🔵','Hugging Face':'🤗','Cohere':'🟣','Mistral AI':'🌀','Groq':'⚡','Ollama':'🦙','LangChain':'🦜','CrewAI':'👥','AutoGen':'🔄','AWS Bedrock':'☁️','Azure OpenAI':'🔷','Replicate':'🔁'};
const SC=['polygon(50% 0%,100% 25%,100% 75%,50% 100%,0% 75%,0% 25%)','polygon(50% 0%,100% 38%,82% 100%,18% 100%,0% 38%)','polygon(30% 0%,70% 0%,100% 30%,100% 70%,70% 100%,30% 100%,0% 70%,0% 30%)'];
let D=null;const API='/scanner/api';
document.addEventListener('DOMContentLoaded',()=>load(API+'/scan'));
async function load(url){try{const r=await fetch(url);if(!r.ok)throw new Error('HTTP '+r.status);D=await r.json();render();}catch(e){document.getElementById('ldr').innerHTML='<div style="text-align:center;color:#ff3355;padding:30px"><i class="fas fa-exclamation-triangle" style="font-size:40px;display:block;margin-bottom:12px"></i><h2>Scan Failed</h2><p style="color:#9999cc;margin-top:8px;font-size:12px">'+e.message+'</p><button class="btn bp" onclick="load(API+\\'/scan\\')" style="margin-top:14px"><i class="fas fa-redo"></i> Retry</button></div>';}}
async function rescan(){document.getElementById('ri').style.animation='spin .5s linear infinite';document.getElementById('ldr').style.display='flex';document.getElementById('mn').style.display='none';try{await load(API+'/rescan');}catch(e){alert(e.message);}document.getElementById('ri').style.animation='';}
function exp(){const b=new Blob([JSON.stringify(D,null,2)],{type:'application/json'});const u=URL.createObjectURL(b);const a=document.createElement('a');a.href=u;a.download='agents_'+Date.now()+'.json';a.click();URL.revokeObjectURL(u);}
function stb(el,p){document.querySelectorAll('.tab').forEach(t=>t.classList.remove('on'));document.querySelectorAll('.tp').forEach(t=>t.classList.remove('on'));el.classList.add('on');document.getElementById('p-'+p).classList.add('on');}
function fm(n){if(n==null)return'N/A';if(typeof n==='string')return n;if(n>=1e6)return(n/1e6).toFixed(1)+'M';if(n>=1e3)return(n/1e3).toFixed(1)+'K';return String(n);}
function render(){document.getElementById('ldr').style.display='none';document.getElementById('mn').style.display='block';const ss=D.scan_stats;document.getElementById('spp').textContent='📁 '+D.scan_root;document.getElementById('st').textContent='SentinelOps • '+ss.scan_duration_ms+'ms • '+new Date(ss.scan_start).toLocaleString();bS();bO();bA();bP();bU();bF();bT();}
function bS(){const ss=D.scan_stats,sm=D.summary,ou=sm.overall_usage;const c=[{i:'🤖',l:'Agents',v:sm.total_agents,c:'#00f5ff',g:GR[0]},{i:'📂',l:'Folders',v:ss.total_folders_scanned,c:'#ffee00',g:GR[3]},{i:'📄',l:'Files',v:ss.total_files_scanned,c:'#aa44ff',g:GR[6]},{i:'🏢',l:'Providers',v:Object.keys(sm.providers_breakdown).length,c:'#ff8800',g:GR[1]},{i:'📡',l:'Requests',v:fm(ou.total_requests),c:'#4488ff',g:GR[5]},{i:'✅',l:'Success',v:ou.success_rate!=null?ou.success_rate+'%':'N/A',c:'#00ff88',g:GR[2]},{i:'🪙',l:'Tokens',v:fm(ou.total_tokens),c:'#ff66aa',g:GR[6]},{i:'📦',l:'Projects',v:sm.total_projects,c:'#00ccaa',g:GR[7]}];document.getElementById('srow').innerHTML=c.map(s=>'<div class="sc"><div class="si" style="background:'+s.g+'">'+s.i+'</div><div class="sv" style="color:'+s.c+'">'+s.v+'</div><div class="sl">'+s.l+'</div><div class="sb" style="background:'+s.g+'"></div></div>').join('');}
function bO(){const sm=D.summary,ou=sm.overall_usage;let h='<div class="g2">';h+='<div class="cd"><div class="ch"><h3><i class="fas fa-building" style="color:var(--cy)"></i> Providers</h3></div><div class="sg">';Object.entries(sm.providers_breakdown).forEach(([n,c],i)=>{h+='<div class="hex" style="background:'+GR[i%GR.length]+';width:100px;height:115px"><div style="font-size:16px">'+(PI[n]||'🔹')+'</div><div style="font-size:17px;font-weight:800;font-family:JetBrains Mono">'+c+'</div><div style="font-size:7px;padding:0 5px;margin-top:2px">'+n+'</div></div>';});if(!Object.keys(sm.providers_breakdown).length)h+='<div class="em"><i class="fas fa-building"></i><p>No providers</p></div>';h+='</div></div>';
h+='<div class="cd"><div class="ch"><h3><i class="fas fa-bullseye" style="color:var(--mg)"></i> Areas</h3></div><div class="sg">';const SZ=['100px','90px','85px'];Object.entries(sm.area_breakdown).forEach(([a,c],i)=>{const sz=SZ[i%3];h+='<div style="width:'+sz+';height:'+sz+';clip-path:'+SC[i%3]+';background:'+GR[i%GR.length]+';display:flex;flex-direction:column;align-items:center;justify-content:center;text-align:center;transition:transform .3s;cursor:default" onmouseover="this.style.transform=\'scale(1.1)\'" onmouseout="this.style.transform=\'scale(1)\'"><div style="font-size:14px;font-weight:800">'+c+'</div><div style="font-size:6px;padding:0 3px">'+a.split('/')[0].trim()+'</div></div>';});if(!Object.keys(sm.area_breakdown).length)h+='<div class="em"><p>No areas</p></div>';h+='</div></div>';
h+='<div class="cd s2"><div class="ch"><h3><i class="fas fa-gauge-high" style="color:var(--gn)"></i> Gauges</h3></div><div class="gw">';[{l:'Success Rate',v:ou.success_rate,x:100,c:'#00ff88',s:'%'},{l:'Agents',v:sm.total_agents,x:Math.max(20,sm.total_agents),c:'#aa44ff',s:''},{l:'Providers',v:Object.keys(sm.providers_breakdown).length,x:15,c:'#00f5ff',s:''}].forEach(g=>{const p=g.v!=null?Math.min(g.v/g.x*100,100):0;const C=Math.PI*52;const off=C-p/100*C;h+='<div class="gau"><svg width="124" height="72" viewBox="0 0 124 72"><path d="M 10 64 A 52 52 0 0 1 114 64" fill="none" stroke="rgba(255,255,255,0.06)" stroke-width="8" stroke-linecap="round"/><path d="M 10 64 A 52 52 0 0 1 114 64" fill="none" stroke="'+g.c+'" stroke-width="8" stroke-linecap="round" stroke-dasharray="'+C+'" stroke-dashoffset="'+off+'" style="transition:stroke-dashoffset 1.5s ease"/></svg><div class="gv" style="color:'+g.c+'">'+(g.v!=null?g.v+g.s:'N/A')+'</div><div class="gl">'+g.l+'</div></div>';});h+='</div></div>';
const me=Object.entries(sm.model_breakdown);h+='<div class="cd"><div class="ch"><h3><i class="fas fa-brain" style="color:var(--yl)"></i> Models</h3></div><div style="display:flex;align-items:center;gap:18px;flex-wrap:wrap;justify-content:center"><div class="dw">'+dn(sm.model_breakdown,150)+'<div class="dc"><div class="dv">'+me.length+'</div><div class="dl">Models</div></div></div><div class="lg">'+me.map(([n,c],i)=>'<div class="li"><div class="ld" style="background:'+CL[i%CL.length]+'"></div><span>'+n+' ('+c+')</span></div>').join('')+'</div></div></div>';
h+='<div class="cd"><div class="ch"><h3><i class="fas fa-exchange-alt" style="color:var(--bl)"></i> Requests</h3></div><div class="sg"><div class="oct" style="width:105px;height:105px;background:linear-gradient(135deg,#00ff88,#00ccaa)"><i class="fas fa-check" style="font-size:14px"></i><div style="font-size:16px;font-weight:800;margin-top:3px">'+fm(ou.total_successful)+'</div><div style="font-size:6px">SUCCESS</div></div><div class="oct" style="width:105px;height:105px;background:linear-gradient(135deg,#ff3355,#ff00ff)"><i class="fas fa-times" style="font-size:14px"></i><div style="font-size:16px;font-weight:800;margin-top:3px">'+fm(ou.total_failed)+'</div><div style="font-size:6px">FAILED</div></div><div class="pen" style="width:105px;height:100px;background:linear-gradient(135deg,#4488ff,#00f5ff)"><i class="fas fa-paper-plane" style="font-size:14px"></i><div style="font-size:16px;font-weight:800;margin-top:3px">'+fm(ou.total_requests)+'</div><div style="font-size:6px">TOTAL</div></div></div></div></div>';document.getElementById('p-ov').innerHTML=h;}
function bA(){const el=document.getElementById('p-ag');if(!D.agents.length){el.innerHTML='<div class="cd"><div class="em"><i class="fas fa-robot"></i><p>No AI agents detected.</p></div></div>';return;}let h='<div class="g3">';D.agents.forEach((a,i)=>{const g=GR[i%GR.length],ic=IC[i%IC.length],u=a.usage,hd=u.data_source==='log_files';h+='<div class="ac"><div class="ab" style="background:'+g+'"></div><div class="ah"><div class="ai" style="background:'+g+'">'+ic+'</div><div style="flex:1;min-width:0"><div class="an">'+a.script_name+'</div><div class="ap">📁 '+a.relative_path+'</div><div style="margin-top:3px"><span class="bd '+(hd?'br2':'bn')+'">'+(hd?'✅ Logs':'⚠️ No Logs')+'</span></div></div></div><div>'+ir('fa-building','Provider',a.providers.length?a.providers.map(p=>'<span class="tg t-p">'+(PI[p]||'🔹')+' '+p+'</span>').join(' '):'<span class="nd">None</span>')+ir('fa-brain','Model',a.models.map(m=>'<span class="tg t-m">'+m+'</span>').join(' '))+ir('fa-bullseye','Area',a.areas.map(x=>'<span class="tg t-a">'+x+'</span>').join(' '))+ir('fa-cogs','Framework',a.frameworks.map(f=>'<span class="tg t-f">'+f+'</span>').join(' '))+ir('fa-code','Code',a.lines_of_code+' lines • '+a.api_call_sites+' calls')+'</div><div class="db"><i class="fas fa-info-circle" style="color:var(--cy)"></i> '+a.description+'</div><div class="ug">'+uc(u.successful!=null?fm(u.successful):'—','#00ff88','✅ OK')+uc(u.failed||'—','#ff3355','❌ Fail')+uc(u.total_requests!=null?fm(u.total_requests):'—','#00f5ff','📡 Total')+uc(u.tokens_used!=null?fm(u.tokens_used):'—','#ffee00','🪙 Tok')+uc(u.rpm!=null?u.rpm:'—','#aa44ff','⚡ RPM')+uc(u.avg_rt_ms!=null?u.avg_rt_ms+'ms':'—','#ff66aa','⏱ RT')+'</div>'+(u.tokens_pct!=null?'<div class="pb"><div class="pf" style="width:'+u.tokens_pct+'%;background:'+g+'"></div></div><div style="font-size:7px;color:var(--t3);text-align:right">'+fm(u.tokens_used)+'/'+fm(u.tokens_available)+' ('+u.tokens_pct+'%)</div>':'')+(Object.keys(u.failure_reasons||{}).length?'<div style="margin-top:5px;padding-top:5px;border-top:1px solid var(--br)"><div style="font-size:8px;color:var(--rd);font-weight:600">⚠️ Failures:</div>'+Object.entries(u.failure_reasons).map(([r,c])=>'<div class="fe"><span class="fd"></span>'+r+' ('+c+'x)</div>').join('')+'</div>':'')+'</div>';});h+='</div>';el.innerHTML=h;}
function ir(icon,label,val){return'<div class="ir"><span class="ii"><i class="fas '+icon+'"></i></span><span class="il">'+label+'</span><span class="iv">'+val+'</span></div>';}
function uc(v,c,l){return'<div class="uc"><div class="uv" style="color:'+c+'">'+v+'</div><div class="ul">'+l+'</div></div>';}
function bP(){const el=document.getElementById('p-pj');if(!D.projects.length){el.innerHTML='<div class="cd"><div class="em"><i class="fas fa-cubes"></i><p>No projects</p></div></div>';return;}let h='';D.projects.forEach((p,pi)=>{h+='<div class="cd" style="margin-bottom:14px"><div class="ch"><h3>📦 '+p.project_name+'</h3><span style="font-size:10px;color:var(--t3)">'+p.agent_count+' agents</span></div><div class="sg"><div class="hex" style="background:'+GR[0]+';width:85px;height:98px"><div style="font-size:16px;font-weight:800">'+p.agent_count+'</div><div style="font-size:6px">AGENTS</div></div><div class="pen" style="background:'+GR[2]+';width:78px;height:74px"><div style="font-size:14px;font-weight:800">'+fm(p.total_ok)+'</div><div style="font-size:6px">OK</div></div><div class="oct" style="background:'+GR[4]+';width:74px;height:74px"><div style="font-size:14px;font-weight:800">'+(p.total_fail||0)+'</div><div style="font-size:6px">FAIL</div></div></div><div style="display:flex;flex-wrap:wrap;gap:3px;margin:8px 0">'+p.providers_used.map(x=>'<span class="tg t-p">'+(PI[x]||'🔹')+' '+x+'</span>').join('')+'</div><div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(190px,1fr));gap:5px">'+p.agents.map((a,ai)=>'<div style="background:rgba(255,255,255,.03);border-radius:7px;padding:7px;border:1px solid var(--br)"><div style="font-weight:600;font-size:10px">'+IC[ai%IC.length]+' '+a.script_name+'</div><div style="font-size:8px;color:var(--t3);margin-top:2px">'+a.areas.join(', ')+'</div></div>').join('')+'</div></div>';});el.innerHTML=h;}
function bU(){let h='<div class="g2"><div class="cd s2"><div class="ch"><h3><i class="fas fa-chart-bar" style="color:#4488ff"></i> Tokens</h3></div>';const wt=D.agents.filter(a=>a.usage.tokens_used);if(wt.length){wt.forEach((a,i)=>{const p=a.usage.tokens_pct||0,c=CL[i%CL.length];h+='<div style="margin-bottom:10px"><div style="display:flex;justify-content:space-between;margin-bottom:2px"><span style="font-size:10px;font-weight:600">'+IC[i%IC.length]+' '+a.script_name+'</span><span style="font-size:9px;color:var(--t3)">'+fm(a.usage.tokens_used)+'/'+(a.usage.tokens_available!=null?fm(a.usage.tokens_available):'?')+'</span></div><div class="pb" style="height:9px"><div class="pf" style="width:'+p+'%;background:'+c+';height:9px"></div></div></div>';});}else{h+='<div class="em"><i class="fas fa-chart-bar"></i><p>No token data</p></div>';}h+='</div><div class="cd s2"><div class="ch"><h3><i class="fas fa-tachometer-alt" style="color:#ff8800"></i> Rates</h3></div><table class="dt"><thead><tr><th>Agent</th><th>Provider</th><th>RPM</th><th>TPM</th><th>Tokens</th><th>RT</th></tr></thead><tbody>';D.agents.forEach((a,i)=>{const u=a.usage;h+='<tr><td>'+IC[i%IC.length]+' '+a.script_name+'</td><td>'+(a.providers[0]||'?')+'</td><td>'+(u.rpm!=null?u.rpm:'—')+'</td><td>'+fm(u.tpm)+'</td><td>'+fm(u.tokens_used)+'</td><td>'+(u.avg_rt_ms!=null?u.avg_rt_ms+'ms':'—')+'</td></tr>';});h+='</tbody></table></div></div>';document.getElementById('p-us').innerHTML=h;}
function bF(){const ou=D.summary.overall_usage;let h='<div class="cd" style="margin-bottom:14px"><div class="ch"><h3><i class="fas fa-exclamation-triangle" style="color:var(--rd)"></i> Summary</h3></div><div class="sg"><div class="hex" style="background:linear-gradient(135deg,#00ff88,#00ccaa);width:120px;height:138px"><i class="fas fa-check-circle" style="font-size:16px"></i><div style="font-size:18px;font-weight:800;margin-top:3px">'+fm(ou.total_successful)+'</div><div style="font-size:6px;margin-top:2px">Success</div></div><div class="hex" style="background:linear-gradient(135deg,#ff3355,#ff00ff);width:120px;height:138px"><i class="fas fa-times-circle" style="font-size:16px"></i><div style="font-size:18px;font-weight:800;margin-top:3px">'+fm(ou.total_failed)+'</div><div style="font-size:6px;margin-top:2px">Failed</div></div><div class="hex" style="background:linear-gradient(135deg,#4488ff,#00f5ff);width:120px;height:138px"><i class="fas fa-percentage" style="font-size:16px"></i><div style="font-size:18px;font-weight:800;margin-top:3px">'+(ou.success_rate!=null?ou.success_rate+'%':'N/A')+'</div><div style="font-size:6px;margin-top:2px">Rate</div></div></div></div>';
const fe=Object.entries(ou.failure_reasons||{});if(fe.length){h+='<div class="cd" style="margin-bottom:14px"><div class="ch"><h3><i class="fas fa-bug" style="color:var(--og)"></i> Reasons</h3></div><div class="sg">';fe.forEach(([r,c],i)=>{const sz=['95px','85px','80px'];const s=sz[i%3];h+='<div style="width:'+s+';height:'+s+';clip-path:'+SC[i%3]+';background:'+GR[i%GR.length]+';display:flex;flex-direction:column;align-items:center;justify-content:center;text-align:center;padding:4px"><div style="font-size:14px;font-weight:800">'+c+'</div><div style="font-size:6px;margin-top:1px;padding:0 2px">'+r.substring(0,22)+'</div></div>';});h+='</div></div>';}
h+='<div class="cd"><div class="ch"><h3><i class="fas fa-list" style="color:var(--pu)"></i> Per-Agent</h3></div><table class="dt"><thead><tr><th>Agent</th><th>Total</th><th>OK</th><th>Fail</th><th>Rate</th><th>Reasons</th></tr></thead><tbody>';D.agents.forEach((a,i)=>{const u=a.usage;const rc=u.success_rate!=null?(u.success_rate>=95?'#00ff88':u.success_rate>=70?'#ffee00':'#ff3355'):'var(--t3)';h+='<tr><td>'+IC[i%IC.length]+' '+a.script_name+'</td><td>'+fm(u.total_requests)+'</td><td><span class="dot dg"></span>'+fm(u.successful)+'</td><td><span class="dot '+((u.failed||0)>0?'dr':'dg')+'"></span>'+(u.failed||0)+'</td><td style="color:'+rc+';font-weight:700">'+(u.success_rate!=null?u.success_rate+'%':'N/A')+'</td><td style="max-width:200px">'+(Object.entries(u.failure_reasons||{}).length?Object.entries(u.failure_reasons).map(([r,c])=>'<div class="fe"><span class="fd"></span>'+r+' ('+c+'x)</div>').join(''):'<span style="color:var(--gn);font-size:9px">✅</span>')+'</td></tr>';});h+='</tbody></table></div>';document.getElementById('p-fl').innerHTML=h;}
function bT(){const ap=new Set(D.agents.map(a=>a.script_path));function nd(n){if(n.type==='folder'){const b=n.agent_count>0?'<span class="tbg">'+n.agent_count+' 🤖</span>':'';const ch=(n.children||[]).map(c=>nd(c)).join('');return'<div class="tn"><span class="tfo" onclick="tg(this)">📂 '+n.name+b+'</span><div class="tc2">'+ch+'</div></div>';}const ia=ap.has(n.path);return'<div class="tn"><span class="tfi'+(ia?' ia':'')+'">'+( ia?'🤖':'📄')+' '+n.name+(ia?'<span class="tbg tag-a">Agent</span>':'')+'</span></div>';}document.getElementById('p-tr').innerHTML='<div class="trb"><div style="margin-bottom:8px;font-size:11px;font-weight:600;color:var(--cy)"><i class="fas fa-folder-tree"></i> '+D.scan_root+'</div>'+nd(D.folder_tree)+'</div>';}
function tg(el){const ch=el.nextElementSibling;if(ch)ch.style.display=ch.style.display==='none'?'block':'none';}
function dn(data,sz){const e=Object.entries(data);const t=e.reduce((s,[,v])=>s+v,0);if(!t)return'<svg width="'+sz+'" height="'+sz+'"><circle cx="'+sz/2+'" cy="'+sz/2+'" r="'+sz*.35+'" fill="none" stroke="rgba(255,255,255,0.06)" stroke-width="'+sz*.12+'"/></svg>';const cx=sz/2,cy=sz/2,r=sz*.35,C=2*Math.PI*r;let off=0,p='';e.forEach(([,v],i)=>{const d=(v/t)*C;p+='<circle cx="'+cx+'" cy="'+cy+'" r="'+r+'" fill="none" stroke="'+CL[i%CL.length]+'" stroke-width="'+sz*.12+'" stroke-dasharray="'+d+' '+(C-d)+'" stroke-dashoffset="'+(-off)+'" transform="rotate(-90 '+cx+' '+cy+')" style="transition:all .5s"/>';off+=d;});return'<svg width="'+sz+'" height="'+sz+'" viewBox="0 0 '+sz+' '+sz+'">'+p+'</svg>';}
</script></body></html>"""


# ════════════════════════════════════════════════════════════
# STANDALONE MODE
# ════════════════════════════════════════════════════════════
if __name__ == "__main__":
    app = Flask(__name__)
    app.register_blueprint(scanner_bp)

    print("=" * 50)
    print("🤖 AI Agent Scanner — Standalone Mode")
    print("=" * 50)
    print(f"📁 Scanning: {os.path.abspath(SCAN_ROOT)}")

    data = get_data()
    ss = data["scan_stats"]
    print(f"📊 {ss['total_agents_found']} agents in "
          f"{ss['total_files_scanned']} files "
          f"({ss['scan_duration_ms']}ms)")
    for i, a in enumerate(data["agents"], 1):
        print(f"  {i}. {a['script_name']} → "
              f"{', '.join(a['providers'])} | "
              f"{', '.join(a['areas'])}")
    print(f"\n🌐 http://localhost:8787/scanner")

    app.run(host="0.0.0.0", port=8787, debug=False)
#!/usr/bin/env python3
"""
AI Agent Scanner & Dashboard for SentinelOps-Lite.
Registers Flask Blueprint at /scanner.

In app.py add:
    from agent_monitor import scanner_bp
    application.register_blueprint(scanner_bp)
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
# BLUEPRINT
# ════════════════════════════════════════════════════════════
scanner_bp = Blueprint("scanner", __name__)
SCAN_ROOT = os.environ.get(
    "SCAN_ROOT",
    os.path.dirname(os.path.abspath(__file__))
)
_cache = {"data": None, "lock": threading.Lock()}

# Files to skip during scan (skip THIS file)
THIS_FILE = os.path.basename(__file__)

# ════════════════════════════════════════════════════════════
# AI DETECTION PATTERNS
# ════════════════════════════════════════════════════════════
AI_PROVIDERS = {
    "OpenAI": {
        "imports": [
            r"import\s+openai", r"from\s+openai\s+import",
            r"OpenAI\s*\(", r"openai\.api_key",
            r"AsyncOpenAI\s*\(",
        ],
        "env_keys": ["OPENAI_API_KEY"],
        "models": [
            "gpt-4o", "gpt-4o-mini", "gpt-4-turbo", "gpt-4",
            "gpt-3.5-turbo", "dall-e-3", "whisper-1",
        ],
    },
    "Anthropic": {
        "imports": [
            r"import\s+anthropic", r"from\s+anthropic\s+import",
            r"Anthropic\s*\(", r"AsyncAnthropic\s*\(",
        ],
        "env_keys": ["ANTHROPIC_API_KEY"],
        "models": [
            "claude-3-5-sonnet", "claude-3-opus",
            "claude-3-sonnet", "claude-3-haiku",
        ],
    },
    "Google Gemini": {
        "imports": [
            r"import\s+google\.generativeai",
            r"from\s+google\.generativeai",
            r"genai\.GenerativeModel",
            r"import\s+vertexai",
            r"GenerativeModel\s*\(",
        ],
        "env_keys": ["GOOGLE_API_KEY"],
        "models": [
            "gemini-2.5-flash", "gemini-2.0-flash",
            "gemini-1.5-pro", "gemini-1.5-flash",
            "gemini-pro",
        ],
    },
    "Hugging Face": {
        "imports": [
            r"from\s+transformers\s+import",
            r"import\s+transformers",
            r"from\s+huggingface_hub",
        ],
        "env_keys": ["HF_TOKEN"],
        "models": ["bert", "t5", "mistral", "falcon"],
    },
    "Groq": {
        "imports": [
            r"import\s+groq", r"from\s+groq",
            r"Groq\s*\(",
        ],
        "env_keys": ["GROQ_API_KEY"],
        "models": ["llama3", "mixtral"],
    },
    "Ollama": {
        "imports": [
            r"import\s+ollama", r"from\s+ollama",
            r"ollama\.chat", r"ollama\.generate",
        ],
        "env_keys": [],
        "models": ["llama2", "llama3", "codellama"],
    },
    "LangChain": {
        "imports": [
            r"from\s+langchain\s+import",
            r"from\s+langchain\.\w+\s+import",
            r"AgentExecutor",
        ],
        "env_keys": [], "models": [],
    },
    "CrewAI": {
        "imports": [
            r"from\s+crewai\s+import",
            r"Crew\s*\(",
        ],
        "env_keys": [], "models": [],
    },
    "AutoGen": {
        "imports": [
            r"from\s+autogen\s+import",
            r"AssistantAgent\s*\(",
        ],
        "env_keys": [], "models": [],
    },
}

AI_FRAMEWORKS = {
    "LangChain Agent": [
        r"AgentExecutor\s*\(",
        r"create_react_agent\s*\(",
    ],
    "CrewAI Agent": [
        r"from\s+crewai\s+import\s+Agent",
    ],
    "AutoGen Agent": [
        r"AssistantAgent\s*\(",
    ],
    "Custom Agent": [
        r"class\s+\w*[Aa]gent\w*\s*[\(:]",
    ],
    "Prometheus Monitor": [
        r"from\s+prometheus_client",
        r"Counter\s*\(", r"Gauge\s*\(",
    ],
}

AI_AREAS = {
    "Chatbot": [
        r"\bchat\s*\(", r"\bconversation\b",
        r"\bchatbot\b",
    ],
    "Monitoring": [
        r"\bmonitor\b", r"\bmetric\b",
        r"\bprometheus\b", r"\bpsutil\b",
        r"\bcpu_percent\b",
    ],
    "Code Generation": [
        r"\bcode[-_]?gen", r"\bcode[-_]?review\b",
    ],
    "DevOps": [
        r"\bdeploy\b", r"\bdocker\b",
        r"\bci[-_]?cd\b", r"\bpre[-_]?deploy\b",
        r"\bpost[-_]?deploy\b",
    ],
    "API Service": [
        r"\bflask\b", r"\bjsonify\b",
        r"@\w+\.(get|post|route)\b",
    ],
    "Data Analysis": [
        r"\bpandas\b", r"\bdataframe\b", r"\bcsv\b",
    ],
    "NLP": [
        r"\bsummariz", r"\btranslat",
        r"\bsentiment\b",
    ],
    "RAG": [
        r"\bchromadb\b", r"\bpinecone\b",
        r"\bvector.?store\b",
    ],
}


# ════════════════════════════════════════════════════════════
# HELPER: Detect model names in code via getenv defaults
# ════════════════════════════════════════════════════════════
def _find_env_models(content):
    """Find model names from os.getenv('AI_MODEL', 'xxx')."""
    found = []
    for m in re.findall(
        r'getenv\s*\(\s*["\']AI_MODEL["\']\s*,\s*["\']'
        r'([\w.\-]+)["\']\s*\)',
        content,
    ):
        if m not in found:
            found.append(m)
    return found


def _find_env_providers(content):
    """Find provider from os.getenv('AI_PROVIDER', 'xxx')."""
    found = []
    for m in re.findall(
        r'getenv\s*\(\s*["\']AI_PROVIDER["\']\s*,\s*["\']'
        r'(\w+)["\']\s*\)',
        content,
    ):
        if m not in found:
            found.append(m)
    return found


# ════════════════════════════════════════════════════════════
# LOG READER — real data only
# ════════════════════════════════════════════════════════════
class LogReader:
    EXTS = {".log", ".txt", ".json", ".jsonl"}

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
            "tokens": 0,
            "failures": {},
            "avg_rt": None, "last_t": None,
            "source": "no_logs" if not logs else "log_files",
        }
        for f in logs:
            self._read(f, r)
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
                            self.name.lower(),
                            "log", "usage", "request",
                        ]
                    ):
                        found.append(fp)
            except PermissionError:
                pass
        return list(set(found))

    def _read(self, path, r):
        try:
            sz = os.path.getsize(path)
            if sz == 0 or sz > 20 * 1024 * 1024:
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
                        self._jentry(json.loads(line), r)
                    except Exception:
                        pass
        elif path.endswith(".json"):
            try:
                d = json.loads(raw)
                items = d if isinstance(d, list) else [d]
                for i in items:
                    if isinstance(i, dict):
                        self._jentry(i, r)
            except Exception:
                self._tlines(raw, r)
        else:
            self._tlines(raw, r)

        ts = re.findall(
            r'(\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2})', raw
        )
        if ts:
            r["last_t"] = ts[-1]

    def _jentry(self, e, r):
        u = e.get("usage", {})
        if isinstance(u, dict):
            r["tokens"] += (
                u.get("total_tokens", 0) or 0
            )
        st = e.get("status") or e.get("status_code")
        if st is not None:
            s = str(st)
            if s in ("200", "success", "ok"):
                r["ok"] += 1; r["total"] += 1
            elif s in ("error", "failed") or (
                isinstance(st, int) and st >= 400
            ):
                r["fail"] += 1; r["total"] += 1
                err = (
                    e.get("error")
                    or e.get("message")
                    or f"HTTP {st}"
                )
                if err:
                    k = str(err)[:80]
                    r["failures"][k] = (
                        r["failures"].get(k, 0) + 1
                    )

    def _tlines(self, raw, r):
        OK = [r'"status":\s*200', r'status_code=200']
        ER = [
            r'"status":\s*[45]\d\d',
            r'Error|ERROR|Exception|FAILED',
        ]
        for line in raw.splitlines():
            m = re.search(r'"total_tokens":\s*(\d+)', line)
            if m:
                r["tokens"] += int(m.group(1))
                continue
            if any(re.search(p, line, re.I) for p in OK):
                r["ok"] += 1; r["total"] += 1
                continue
            if any(re.search(p, line, re.I) for p in ER):
                r["fail"] += 1; r["total"] += 1
                m2 = re.search(
                    r'(Error|Exception|FAILED)[:\s]+(.{5,80})',
                    line, re.I,
                )
                if m2:
                    k = m2.group(2).strip()[:80]
                    r["failures"][k] = (
                        r["failures"].get(k, 0) + 1
                    )


# ════════════════════════════════════════════════════════════
# SOURCE ANALYZER
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
                    l.strip()
                    for l in txt.split("\n")
                    if l.strip()
                ]
                return " ".join(lines[:3])[:200]
        for line in self.content.split("\n")[:10]:
            s = line.strip()
            if s.startswith("#") and not s.startswith("#!"):
                c = s.lstrip("# ").strip()
                if len(c) > 8:
                    return c[:200]
        n = os.path.splitext(
            os.path.basename(self.path)
        )[0]
        return n.replace("_", " ").title()

    def providers(self):
        found = []
        for name, info in AI_PROVIDERS.items():
            for pat in info["imports"]:
                if re.search(pat, self.content):
                    found.append(name)
                    break
        # Also check env-based providers
        for p in _find_env_providers(self.content):
            label = p.capitalize()
            if "gemini" in p.lower():
                label = "Google Gemini"
            if label not in found:
                found.append(label)
        return found

    def models(self):
        found = []
        for info in AI_PROVIDERS.values():
            for m in info.get("models", []):
                if re.search(
                    r'["\']' + re.escape(m) + r'["\']',
                    self.content,
                ):
                    if m not in found:
                        found.append(m)
        for m in _find_env_models(self.content):
            if m not in found:
                found.append(m)
        return found

    def frameworks(self):
        found = []
        for fw, pats in AI_FRAMEWORKS.items():
            if any(
                re.search(p, self.content) for p in pats
            ):
                found.append(fw)
        return found

    def areas(self):
        found = []
        for area, pats in AI_AREAS.items():
            if (
                sum(
                    1
                    for p in pats
                    if re.search(p, self.content, re.I)
                )
                >= 2
            ):
                found.append(area)
        return found

    def api_calls(self):
        pats = [
            r'\.create\s*\(', r'\.generate\s*\(',
            r'\.chat\s*\(', r'generate_content\s*\(',
        ]
        return sum(
            len(re.findall(p, self.content)) for p in pats
        )


# ════════════════════════════════════════════════════════════
# FOLDER SCANNER
# ════════════════════════════════════════════════════════════
class Scanner:
    EXTS = {".py", ".js", ".ts"}
    SKIP = {
        "__pycache__", "node_modules", ".git", "venv",
        "env", ".venv", "dist", "build",
        ".ebextensions", ".elasticbeanstalk",
        "site-packages", ".platform",
    }
    # Skip these filenames
    SKIP_FILES = {THIS_FILE, "agent_monitor.py"}

    def __init__(self, root):
        self.root = os.path.abspath(root)
        self.agents = []
        self.nf = 0
        self.nd = 0

    def scan(self):
        t0 = time.time()
        start = datetime.now().isoformat()
        tree = self._tree(self.root)
        self._walk(self.root)
        ms = round((time.time() - t0) * 1000, 2)

        for a in self.agents:
            self._mark(tree, a["script_path"])

        projects = self._group()
        return {
            "scan_root": self.root,
            "scan_stats": {
                "total_files_scanned": self.nf,
                "total_folders_scanned": self.nd,
                "total_agents_found": len(self.agents),
                "scan_start": start,
                "scan_end": datetime.now().isoformat(),
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
        self.nd += 1
        try:
            for e in sorted(os.listdir(path)):
                fp = os.path.join(path, e)
                if os.path.isdir(fp):
                    if not e.startswith(".") and e not in self.SKIP:
                        node["children"].append(
                            self._tree(fp, depth + 1)
                        )
                elif os.path.isfile(fp):
                    ext = os.path.splitext(e)[1].lower()
                    if ext in self.EXTS:
                        node["children"].append({
                            "name": e, "path": fp,
                            "type": "file",
                            "depth": depth + 1,
                        })
        except PermissionError:
            pass
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
            for e in os.listdir(path):
                fp = os.path.join(path, e)
                if os.path.isdir(fp):
                    if not e.startswith(".") and e not in self.SKIP:
                        self._walk(fp)
                elif os.path.isfile(fp):
                    ext = os.path.splitext(e)[1].lower()
                    if ext in self.EXTS:
                        self.nf += 1
                        # Skip this scanner file
                        if e in self.SKIP_FILES:
                            continue
                        self._check(fp)
        except PermissionError:
            pass

    def _check(self, fp):
        try:
            with open(
                fp, "r", encoding="utf-8", errors="ignore"
            ) as f:
                content = f.read()
        except Exception:
            return
        if len(content.strip()) < 30:
            return

        az = Analyzer(fp, content)
        provs = az.providers()
        fws = az.frameworks()
        if not provs and not fws:
            return

        models = az.models()
        areas = az.areas()
        desc = az.description()

        lr = LogReader(fp)
        ld = lr.parse()

        total = ld.get("total", 0)
        ok = ld.get("ok", 0)
        fail = ld.get("fail", 0)
        tokens = ld.get("tokens", 0)

        self.agents.append({
            "id": hashlib.md5(fp.encode()).hexdigest()[:10],
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
            "areas": areas or ["General"],
            "description": desc,
            "lines_of_code": content.count("\n") + 1,
            "api_call_sites": az.api_calls(),
            "last_modified": datetime.fromtimestamp(
                os.path.getmtime(fp)
            ).strftime("%Y-%m-%d %H:%M"),
            "usage": {
                "data_source": ld["source"],
                "log_files": ld["log_files"],
                "total_requests": total or None,
                "successful": ok or None,
                "failed": fail,
                "success_rate": (
                    round(ok / total * 100, 1)
                    if total > 0
                    else None
                ),
                "tokens_used": tokens or None,
                "failure_reasons": ld["failures"],
                "avg_rt_ms": ld["avg_rt"],
                "last_request": ld["last_t"],
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
        return [
            {
                "name": nm,
                "count": len(ag),
                "agents": [
                    {
                        "name": a["script_name"],
                        "providers": a["providers"],
                        "models": a["models"][:5],
                        "areas": a["areas"],
                    }
                    for a in ag
                ],
                "providers": list(
                    {p for a in ag for p in a["providers"]}
                ),
                "total_req": (
                    sum(
                        a["usage"]["total_requests"] or 0
                        for a in ag
                    )
                    or None
                ),
                "total_fail": sum(
                    a["usage"]["failed"] or 0 for a in ag
                ),
            }
            for nm, ag in pmap.items()
        ]

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
            for reason, cnt in u["failure_reasons"].items():
                fr[reason] = fr.get(reason, 0) + cnt
        return {
            "total_agents": len(self.agents),
            "total_projects": len(projects),
            "providers": pc,
            "areas": ac,
            "models": mc,
            "usage": {
                "total_requests": tr or None,
                "total_ok": ts or None,
                "total_fail": tf,
                "success_rate": (
                    round(ts / tr * 100, 1)
                    if tr > 0
                    else None
                ),
                "total_tokens": tt or None,
                "failures": fr,
            },
        }


def get_data(force=False):
    with _cache["lock"]:
        if _cache["data"] is None or force:
            _cache["data"] = Scanner(SCAN_ROOT).scan()
        return _cache["data"]


# ════════════════════════════════════════════════════════════
# ROUTES
# ════════════════════════════════════════════════════════════
@scanner_bp.get("/scanner")
def page():
    return Response(HTML, mimetype="text/html")


@scanner_bp.get("/scanner/api/scan")
def api_scan():
    try:
        return jsonify(get_data())
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@scanner_bp.route(
    "/scanner/api/rescan", methods=["GET", "POST"]
)
def api_rescan():
    try:
        return jsonify(get_data(force=True))
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ════════════════════════════════════════════════════════════
# COMPLETE HTML + CSS + JS DASHBOARD
# ════════════════════════════════════════════════════════════
HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>AI Agent Scanner — SentinelOps</title>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700;800;900&family=JetBrains+Mono:wght@400;600&display=swap" rel="stylesheet">
<link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.5.1/css/all.min.css">
<style>
:root{--bg:#0b0b1e;--c:#161638;--t:#e4e4ff;--t2:#8888bb;--t3:#5555aa;--cy:#00e5ff;--mg:#ff00ff;--gn:#00ff88;--yl:#ffe600;--og:#ff8800;--rd:#ff2244;--bl:#3388ff;--pu:#9944ff;--br:rgba(255,255,255,.07);--r:14px}
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:'Inter',sans-serif;background:var(--bg);color:var(--t);min-height:100vh}
::-webkit-scrollbar{width:5px}::-webkit-scrollbar-thumb{background:linear-gradient(var(--cy),var(--pu));border-radius:3px}
.bg{position:fixed;inset:0;z-index:-1;pointer-events:none}.orb{position:absolute;border-radius:50%;filter:blur(80px);animation:f 20s ease-in-out infinite}
.orb:nth-child(1){width:420px;height:420px;top:-80px;left:-80px;background:rgba(0,229,255,.06)}
.orb:nth-child(2){width:360px;height:360px;top:45%;right:-80px;background:rgba(255,0,255,.04);animation-delay:-7s}
@keyframes f{0%,100%{transform:translate(0,0)}50%{transform:translate(35px,-35px)}}
header{background:rgba(22,22,56,.95);backdrop-filter:blur(16px);border-bottom:1px solid var(--br);padding:12px 24px;display:flex;align-items:center;justify-content:space-between;position:sticky;top:0;z-index:100;flex-wrap:wrap;gap:8px}
.logo{width:40px;height:40px;border-radius:10px;font-size:18px;background:linear-gradient(135deg,var(--cy),var(--pu));display:flex;align-items:center;justify-content:center}
.brd{display:flex;align-items:center;gap:10px}.brd h1{font-size:16px;font-weight:800;background:linear-gradient(135deg,var(--cy),var(--pu));-webkit-background-clip:text;-webkit-text-fill-color:transparent}.brd small{font-size:9px;color:var(--t3);display:block}
.hr{display:flex;gap:6px;align-items:center;flex-wrap:wrap}
.btn{padding:7px 14px;border:none;border-radius:8px;font-size:10px;font-weight:600;cursor:pointer;display:inline-flex;align-items:center;gap:5px;font-family:Inter;transition:all .2s}
.bp{background:linear-gradient(135deg,var(--cy),var(--pu));color:#000}.bp:hover{transform:translateY(-1px);box-shadow:0 3px 12px rgba(0,229,255,.3)}
.bs{background:rgba(255,255,255,.06);color:var(--t);border:1px solid var(--br)}
.bk{color:var(--og);border:1px solid rgba(255,136,0,.3);background:rgba(255,136,0,.1);text-decoration:none}
.mn{padding:20px 24px;max-width:1700px;margin:0 auto}
.row{display:grid;grid-template-columns:repeat(auto-fit,minmax(140px,1fr));gap:10px;margin-bottom:18px}
.st{background:var(--c);border:1px solid var(--br);border-radius:var(--r);padding:14px;position:relative;overflow:hidden;transition:all .2s}
.st:hover{transform:translateY(-2px);border-color:rgba(0,229,255,.25)}
.st-i{width:32px;height:32px;border-radius:8px;display:flex;align-items:center;justify-content:center;font-size:14px;margin-bottom:6px}
.st-v{font-size:20px;font-weight:800;font-family:'JetBrains Mono'}.st-l{font-size:8px;color:var(--t3);text-transform:uppercase;letter-spacing:1px;margin-top:2px}
.st-b{position:absolute;bottom:0;left:0;height:3px;width:100%}
.tabs{display:flex;gap:2px;margin-bottom:16px;background:rgba(255,255,255,.02);border-radius:10px;padding:3px;flex-wrap:wrap}
.tab{padding:7px 13px;border-radius:8px;cursor:pointer;font-size:10px;font-weight:600;color:var(--t3);display:flex;align-items:center;gap:4px;transition:all .2s}
.tab:hover{color:var(--t);background:rgba(255,255,255,.04)}
.tab.on{background:linear-gradient(135deg,var(--cy),var(--pu));color:#000}
.pane{display:none;animation:fi .25s ease}.pane.on{display:block}
@keyframes fi{from{opacity:0;transform:translateY(6px)}to{opacity:1;transform:translateY(0)}}
.g2{display:grid;grid-template-columns:1fr 1fr;gap:12px}.g3{display:grid;grid-template-columns:repeat(auto-fill,minmax(300px,1fr));gap:12px}.s2{grid-column:span 2}
.cd{background:var(--c);border:1px solid var(--br);border-radius:var(--r);padding:16px;transition:border-color .2s}.cd:hover{border-color:rgba(0,229,255,.12)}
.cd h3{font-size:12px;font-weight:700;margin-bottom:10px;display:flex;align-items:center;gap:6px}
.sg{display:flex;flex-wrap:wrap;gap:8px;justify-content:center;padding:4px 0}
.hex{clip-path:polygon(50% 0%,100% 25%,100% 75%,50% 100%,0% 75%,0% 25%);display:flex;flex-direction:column;align-items:center;justify-content:center;text-align:center;transition:transform .2s;cursor:default}.hex:hover{transform:scale(1.08)}
.pen{clip-path:polygon(50% 0%,100% 38%,82% 100%,18% 100%,0% 38%);display:flex;flex-direction:column;align-items:center;justify-content:center;text-align:center;transition:transform .2s}.pen:hover{transform:scale(1.08) rotate(3deg)}
.oct{clip-path:polygon(30% 0%,70% 0%,100% 30%,100% 70%,70% 100%,30% 100%,0% 70%,0% 30%);display:flex;flex-direction:column;align-items:center;justify-content:center;text-align:center;transition:transform .2s}.oct:hover{transform:scale(1.08) rotate(-3deg)}
.ac{background:var(--c);border:1px solid var(--br);border-radius:var(--r);padding:14px;position:relative;overflow:hidden;transition:all .2s}.ac:hover{transform:translateY(-2px);box-shadow:0 4px 16px rgba(0,0,0,.3);border-color:rgba(0,229,255,.2)}
.ab{position:absolute;top:0;left:0;right:0;height:3px}
.ah{display:flex;gap:8px;margin-bottom:8px}.ai{width:36px;height:36px;border-radius:10px;font-size:16px;display:flex;align-items:center;justify-content:center;flex-shrink:0}
.an{font-size:12px;font-weight:700;word-break:break-all}.ap{font-size:8px;color:var(--t3);font-family:'JetBrains Mono'}
.ir{display:flex;gap:5px;padding:3px 0;font-size:10px;border-bottom:1px solid rgba(255,255,255,.03)}.ir:last-child{border-bottom:none}
.ii{width:13px;color:var(--cy);font-size:9px;flex-shrink:0;margin-top:1px;text-align:center}.il{color:var(--t3);min-width:55px}.iv{color:var(--t);flex:1;word-break:break-word}
.tg{display:inline-block;padding:1px 5px;border-radius:12px;font-size:7px;font-weight:600;margin:1px;border:1px solid}
.tp{background:rgba(0,229,255,.08);color:var(--cy);border-color:rgba(0,229,255,.25)}
.tm{background:rgba(153,68,255,.08);color:var(--pu);border-color:rgba(153,68,255,.25)}
.ta{background:rgba(0,255,136,.08);color:var(--gn);border-color:rgba(0,255,136,.25)}
.tf{background:rgba(255,136,0,.08);color:var(--og);border-color:rgba(255,136,0,.25)}
.db{background:rgba(0,229,255,.03);border-left:2px solid var(--cy);border-radius:0 6px 6px 0;padding:5px 8px;margin:6px 0;font-size:8px;color:var(--t2);line-height:1.4}
.ug{display:grid;grid-template-columns:repeat(3,1fr);gap:3px;margin-top:6px}
.uc{background:rgba(255,255,255,.02);border-radius:6px;padding:5px;text-align:center}
.uv{font-size:11px;font-weight:700;font-family:'JetBrains Mono'}.ul{font-size:6px;color:var(--t3);text-transform:uppercase;margin-top:1px}
.pb{width:100%;height:4px;background:rgba(255,255,255,.05);border-radius:2px;overflow:hidden;margin:4px 0}.pf{height:100%;border-radius:2px;transition:width 1s ease}
.bd{display:inline-flex;padding:2px 5px;border-radius:10px;font-size:6px;font-weight:700;text-transform:uppercase;letter-spacing:.5px}
.b-r{background:rgba(0,255,136,.12);color:var(--gn);border:1px solid rgba(0,255,136,.25)}
.b-n{background:rgba(255,136,0,.12);color:var(--og);border:1px solid rgba(255,136,0,.25)}
.fe{font-size:7px;color:var(--t3);padding:1px 0}.fd{width:3px;height:3px;border-radius:50%;background:var(--rd);display:inline-block;margin-right:2px}
.dt{width:100%;border-collapse:collapse}.dt th,.dt td{padding:7px 8px;text-align:left;border-bottom:1px solid var(--br);font-size:9px}
.dt th{color:var(--t3);font-weight:600;text-transform:uppercase;font-size:7px}.dt tr:hover{background:rgba(255,255,255,.015)}
.d{width:4px;height:4px;border-radius:50%;display:inline-block;margin-right:2px}.dg{background:var(--gn)}.dr{background:var(--rd)}
.tr{background:var(--c);border:1px solid var(--br);border-radius:var(--r);padding:12px;max-height:420px;overflow-y:auto}
.tn{padding:2px 0;font-family:'JetBrains Mono';font-size:10px}
.tfo{color:var(--yl);cursor:pointer}.tfo:hover{color:var(--og)}
.tfi{color:var(--t2)}.tfi.ia{color:var(--gn);font-weight:600}
.tc{margin-left:14px}
.tbg{background:var(--cy);color:#000;font-size:6px;font-weight:700;padding:1px 4px;border-radius:6px;margin-left:3px;display:inline-block}
.tag{background:var(--gn)}
.dw{position:relative;display:inline-block}.dcn{position:absolute;top:50%;left:50%;transform:translate(-50%,-50%);text-align:center}
.dv{font-size:18px;font-weight:800;font-family:'JetBrains Mono'}.dl{font-size:7px;color:var(--t3)}
.lg{display:flex;flex-wrap:wrap;gap:5px;margin-top:8px}.li{display:flex;align-items:center;gap:3px;font-size:8px}.ld{width:7px;height:7px;border-radius:2px}
.gw{display:flex;flex-wrap:wrap;justify-content:center;gap:14px;padding:6px 0}
.gau{position:relative;width:110px;height:64px;overflow:hidden}.gv{position:absolute;bottom:2px;left:50%;transform:translateX(-50%);font-size:13px;font-weight:800;font-family:'JetBrains Mono'}.gl{position:absolute;bottom:-12px;left:50%;transform:translateX(-50%);font-size:7px;color:var(--t3);white-space:nowrap}
.em{text-align:center;padding:24px;color:var(--t3)}.em i{font-size:30px;display:block;margin-bottom:8px;opacity:.3}
.ldr{position:fixed;inset:0;background:rgba(11,11,30,.97);display:flex;flex-direction:column;align-items:center;justify-content:center;z-index:9999}
.spn{width:42px;height:42px;border:3px solid rgba(0,229,255,.15);border-top:3px solid var(--cy);border-radius:50%;animation:sp .8s linear infinite}@keyframes sp{to{transform:rotate(360deg)}}
.lt{margin-top:10px;font-size:12px;color:var(--cy);font-weight:600}
@media(max-width:900px){.g2{grid-template-columns:1fr}.s2{grid-column:span 1}.row{grid-template-columns:repeat(2,1fr)}}
</style></head><body>
<div class="bg"><div class="orb"></div><div class="orb"></div></div>
<div class="ldr" id="ldr"><div class="spn"></div><div class="lt">Scanning for AI Agents…</div></div>
<header><div class="brd"><div class="logo">🤖</div><div><h1>AI Agent Scanner</h1><small id="st2">SentinelOps</small></div></div>
<div class="hr"><a href="/" class="btn bk"><i class="fas fa-arrow-left"></i> App</a>
<button class="btn bs" onclick="exp()"><i class="fas fa-download"></i> Export</button>
<button class="btn bp" onclick="rescan()"><i class="fas fa-sync-alt" id="ri"></i> Rescan</button></div></header>
<main class="mn" id="mn" style="display:none"><div class="row" id="srow"></div>
<div class="tabs"><div class="tab on" onclick="sw(this,0)"><i class="fas fa-chart-pie"></i> Overview</div>
<div class="tab" onclick="sw(this,1)"><i class="fas fa-robot"></i> Agents</div>
<div class="tab" onclick="sw(this,2)"><i class="fas fa-cubes"></i> Projects</div>
<div class="tab" onclick="sw(this,3)"><i class="fas fa-chart-bar"></i> Usage</div>
<div class="tab" onclick="sw(this,4)"><i class="fas fa-exclamation-triangle"></i> Failures</div>
<div class="tab" onclick="sw(this,5)"><i class="fas fa-folder-tree"></i> Tree</div></div>
<div class="pane on" id="p0"></div><div class="pane" id="p1"></div><div class="pane" id="p2"></div>
<div class="pane" id="p3"></div><div class="pane" id="p4"></div><div class="pane" id="p5"></div></main>
<script>
const C=['#00e5ff','#ff00ff','#00ff88','#ffe600','#ff8800','#ff2244','#3388ff','#9944ff','#ff66aa','#00ccaa'];
const G=['linear-gradient(135deg,#00e5ff,#9944ff)','linear-gradient(135deg,#ff00ff,#ff8800)','linear-gradient(135deg,#00ff88,#00e5ff)','linear-gradient(135deg,#ffe600,#ff8800)','linear-gradient(135deg,#ff2244,#ff00ff)','linear-gradient(135deg,#3388ff,#00e5ff)','linear-gradient(135deg,#9944ff,#ff66aa)','linear-gradient(135deg,#00ccaa,#00ff88)'];
const I=['🤖','🧠','⚡','🔮','🎯','🚀','💡','🔬','📊','🎨','📧','💰','🔧','🌐','📝'];
const P={'OpenAI':'🟢','Anthropic':'🟠','Google Gemini':'🔵','Hugging Face':'🤗','Groq':'⚡','Ollama':'🦙','LangChain':'🦜','CrewAI':'👥','AutoGen':'🔄','gemini':'🔵'};
const SC=['polygon(50% 0%,100% 25%,100% 75%,50% 100%,0% 75%,0% 25%)','polygon(50% 0%,100% 38%,82% 100%,18% 100%,0% 38%)','polygon(30% 0%,70% 0%,100% 30%,100% 70%,70% 100%,30% 100%,0% 70%,0% 30%)'];
let D;
document.addEventListener('DOMContentLoaded',()=>ld('/scanner/api/scan'));
async function ld(u){try{const r=await fetch(u);if(!r.ok)throw new Error('HTTP '+r.status);D=await r.json();if(D.error&&!D.agents)throw new Error(D.error);rn();}catch(e){document.getElementById('ldr').innerHTML='<div style="text-align:center;color:#ff2244;padding:24px"><i class="fas fa-exclamation-triangle" style="font-size:36px;display:block;margin-bottom:10px"></i><h2 style="font-size:16px">Scan Failed</h2><p style="color:#8888bb;font-size:11px;margin-top:6px">'+e.message+'</p><button class="btn bp" onclick="ld(\'/scanner/api/scan\')" style="margin-top:12px"><i class="fas fa-redo"></i> Retry</button></div>';}}
async function rescan(){document.getElementById('ri').style.animation='sp .4s linear infinite';document.getElementById('ldr').style.display='flex';document.getElementById('mn').style.display='none';await ld('/scanner/api/rescan');document.getElementById('ri').style.animation='';}
function exp(){const b=new Blob([JSON.stringify(D,null,2)],{type:'application/json'});const u=URL.createObjectURL(b);const a=document.createElement('a');a.href=u;a.download='agents_'+Date.now()+'.json';a.click();URL.revokeObjectURL(u);}
function sw(el,n){document.querySelectorAll('.tab').forEach(t=>t.classList.remove('on'));document.querySelectorAll('.pane').forEach(p=>p.classList.remove('on'));el.classList.add('on');document.getElementById('p'+n).classList.add('on');}
function fm(n){if(n==null)return'—';if(typeof n==='string')return n;if(n>=1e6)return(n/1e6).toFixed(1)+'M';if(n>=1e3)return(n/1e3).toFixed(1)+'K';return String(n);}
function dn(data,sz){const e=Object.entries(data);const t=e.reduce((s,[,v])=>s+v,0);if(!t)return'<svg width="'+sz+'" height="'+sz+'"><circle cx="'+sz/2+'" cy="'+sz/2+'" r="'+sz*.35+'" fill="none" stroke="rgba(255,255,255,.05)" stroke-width="'+sz*.12+'"/></svg>';const cx=sz/2,cy=sz/2,r=sz*.35,cc=2*Math.PI*r;let o=0,p='';e.forEach(([,v],i)=>{const d=(v/t)*cc;p+='<circle cx="'+cx+'" cy="'+cy+'" r="'+r+'" fill="none" stroke="'+C[i%C.length]+'" stroke-width="'+sz*.12+'" stroke-dasharray="'+d+' '+(cc-d)+'" stroke-dashoffset="'+(-o)+'" transform="rotate(-90 '+cx+' '+cy+')" style="transition:all .5s"/>';o+=d;});return'<svg width="'+sz+'" height="'+sz+'" viewBox="0 0 '+sz+' '+sz+'">'+p+'</svg>';}
function ir(icon,l,v){return'<div class="ir"><span class="ii"><i class="fas fa-'+icon+'"></i></span><span class="il">'+l+'</span><span class="iv">'+v+'</span></div>';}
function uc(v,c,l){return'<div class="uc"><div class="uv" style="color:'+c+'">'+v+'</div><div class="ul">'+l+'</div></div>';}
function rn(){
document.getElementById('ldr').style.display='none';document.getElementById('mn').style.display='block';
const ss=D.scan_stats,sm=D.summary,ou=sm.usage;
document.getElementById('st2').textContent='SentinelOps • '+ss.scan_duration_ms+'ms • '+ss.total_agents_found+' agents • '+new Date(ss.scan_start).toLocaleString();
// Stats
const cards=[{i:'🤖',l:'Agents',v:sm.total_agents,c:'#00e5ff',g:G[0]},{i:'📂',l:'Folders',v:ss.total_folders_scanned,c:'#ffe600',g:G[3]},{i:'📄',l:'Files',v:ss.total_files_scanned,c:'#9944ff',g:G[6]},{i:'🏢',l:'Providers',v:Object.keys(sm.providers).length,c:'#ff8800',g:G[1]},{i:'📡',l:'Requests',v:fm(ou.total_requests),c:'#3388ff',g:G[5]},{i:'✅',l:'Success',v:ou.success_rate!=null?ou.success_rate+'%':'—',c:'#00ff88',g:G[2]},{i:'🪙',l:'Tokens',v:fm(ou.total_tokens),c:'#ff66aa',g:G[6]},{i:'📦',l:'Projects',v:sm.total_projects,c:'#00ccaa',g:G[7]}];
document.getElementById('srow').innerHTML=cards.map(c=>'<div class="st"><div class="st-i" style="background:'+c.g+'">'+c.i+'</div><div class="st-v" style="color:'+c.c+'">'+c.v+'</div><div class="st-l">'+c.l+'</div><div class="st-b" style="background:'+c.g+'"></div></div>').join('');
// P0: Overview
let h='<div class="g2">';
h+='<div class="cd"><h3><i class="fas fa-building" style="color:var(--cy)"></i> Providers</h3><div class="sg">';
Object.entries(sm.providers).forEach(([n,c],i)=>{h+='<div class="hex" style="background:'+G[i%G.length]+';width:90px;height:104px"><div style="font-size:14px">'+(P[n]||'🔹')+'</div><div style="font-size:16px;font-weight:800;font-family:JetBrains Mono">'+c+'</div><div style="font-size:6px;padding:0 4px;margin-top:1px">'+n+'</div></div>';});
h+='</div></div>';
h+='<div class="cd"><h3><i class="fas fa-bullseye" style="color:var(--mg)"></i> Areas</h3><div class="sg">';
const SZ=['90px','80px','76px'];Object.entries(sm.areas).forEach(([a,c],i)=>{const sz=SZ[i%3];h+='<div style="width:'+sz+';height:'+sz+';clip-path:'+SC[i%3]+';background:'+G[i%G.length]+';display:flex;flex-direction:column;align-items:center;justify-content:center;text-align:center;transition:transform .2s" onmouseover="this.style.transform=\'scale(1.1)\'" onmouseout="this.style.transform=\'scale(1)\'"><div style="font-size:13px;font-weight:800">'+c+'</div><div style="font-size:5px;padding:0 2px">'+a+'</div></div>';});
h+='</div></div>';
h+='<div class="cd s2"><h3><i class="fas fa-gauge-high" style="color:var(--gn)"></i> Gauges</h3><div class="gw">';
[{l:'Success',v:ou.success_rate,x:100,c:'#00ff88',s:'%'},{l:'Agents',v:sm.total_agents,x:Math.max(15,sm.total_agents),c:'#9944ff',s:''},{l:'Providers',v:Object.keys(sm.providers).length,x:12,c:'#00e5ff',s:''}].forEach(g=>{const p=g.v!=null?Math.min(g.v/g.x*100,100):0;const cc=Math.PI*46;const off=cc-p/100*cc;h+='<div class="gau"><svg width="110" height="64" viewBox="0 0 110 64"><path d="M 9 56 A 46 46 0 0 1 101 56" fill="none" stroke="rgba(255,255,255,.05)" stroke-width="7" stroke-linecap="round"/><path d="M 9 56 A 46 46 0 0 1 101 56" fill="none" stroke="'+g.c+'" stroke-width="7" stroke-linecap="round" stroke-dasharray="'+cc+'" stroke-dashoffset="'+off+'" style="transition:stroke-dashoffset 1.2s ease"/></svg><div class="gv" style="color:'+g.c+'">'+(g.v!=null?g.v+g.s:'—')+'</div><div class="gl">'+g.l+'</div></div>';});
h+='</div></div>';
const me=Object.entries(sm.models);
h+='<div class="cd"><h3><i class="fas fa-brain" style="color:var(--yl)"></i> Models</h3><div style="display:flex;align-items:center;gap:14px;flex-wrap:wrap;justify-content:center"><div class="dw">'+dn(sm.models,130)+'<div class="dcn"><div class="dv">'+me.length+'</div><div class="dl">Models</div></div></div><div class="lg">'+me.slice(0,12).map(([n,c],i)=>'<div class="li"><div class="ld" style="background:'+C[i%C.length]+'"></div>'+n+' ('+c+')</div>').join('')+'</div></div></div>';
h+='<div class="cd"><h3><i class="fas fa-exchange-alt" style="color:var(--bl)"></i> Requests</h3><div class="sg">';
h+='<div class="oct" style="width:90px;height:90px;background:linear-gradient(135deg,#00ff88,#00ccaa)"><i class="fas fa-check" style="font-size:12px"></i><div style="font-size:14px;font-weight:800;margin-top:2px">'+fm(ou.total_ok)+'</div><div style="font-size:5px">OK</div></div>';
h+='<div class="oct" style="width:90px;height:90px;background:linear-gradient(135deg,#ff2244,#ff00ff)"><i class="fas fa-times" style="font-size:12px"></i><div style="font-size:14px;font-weight:800;margin-top:2px">'+fm(ou.total_fail)+'</div><div style="font-size:5px">FAIL</div></div>';
h+='<div class="pen" style="width:90px;height:86px;background:linear-gradient(135deg,#3388ff,#00e5ff)"><i class="fas fa-paper-plane" style="font-size:12px"></i><div style="font-size:14px;font-weight:800;margin-top:2px">'+fm(ou.total_requests)+'</div><div style="font-size:5px">TOTAL</div></div>';
h+='</div></div></div>';
document.getElementById('p0').innerHTML=h;
// P1: Agents
if(!D.agents.length){document.getElementById('p1').innerHTML='<div class="cd"><div class="em"><i class="fas fa-robot"></i><p>No agents detected</p></div></div>';} else {
let a='<div class="g3">';D.agents.forEach((ag,i)=>{const g=G[i%G.length],ic=I[i%I.length],u=ag.usage,hd=u.data_source==='log_files';
a+='<div class="ac"><div class="ab" style="background:'+g+'"></div><div class="ah"><div class="ai" style="background:'+g+'">'+ic+'</div><div style="flex:1;min-width:0"><div class="an">'+ag.script_name+'</div><div class="ap">📁 '+ag.relative_path+'</div><div style="margin-top:2px"><span class="bd '+(hd?'b-r':'b-n')+'">'+(hd?'✅ Logs':'⚠️ No Logs')+'</span></div></div></div>';
a+=ir('building','Provider',ag.providers.map(p=>'<span class="tg tp">'+(P[p]||'🔹')+' '+p+'</span>').join(' ')||'—');
a+=ir('brain','Model',ag.models.map(m=>'<span class="tg tm">'+m+'</span>').join(' '));
a+=ir('bullseye','Area',ag.areas.map(x=>'<span class="tg ta">'+x+'</span>').join(' '));
a+=ir('cogs','Framework',ag.frameworks.map(f=>'<span class="tg tf">'+f+'</span>').join(' '));
a+=ir('code','Code',ag.lines_of_code+' lines • '+ag.api_call_sites+' API calls');
a+='<div class="db"><i class="fas fa-info-circle" style="color:var(--cy)"></i> '+ag.description+'</div>';
a+='<div class="ug">'+uc(u.successful!=null?fm(u.successful):'—','#00ff88','✅ OK')+uc(u.failed||'—','#ff2244','❌ Fail')+uc(u.total_requests!=null?fm(u.total_requests):'—','#00e5ff','📡 Total')+uc(u.tokens_used!=null?fm(u.tokens_used):'—','#ffe600','🪙 Tok')+uc(u.success_rate!=null?u.success_rate+'%':'—','#9944ff','📊 Rate')+uc(u.avg_rt_ms!=null?u.avg_rt_ms+'ms':'—','#ff66aa','⏱ RT')+'</div>';
const frs=Object.entries(u.failure_reasons||{});if(frs.length){a+='<div style="margin-top:4px;padding-top:4px;border-top:1px solid var(--br)"><div style="font-size:7px;color:var(--rd);font-weight:600">⚠️ Failures:</div>';frs.forEach(([r,c])=>a+='<div class="fe"><span class="fd"></span>'+r+' ('+c+'x)</div>');a+='</div>';}
a+='</div>';});a+='</div>';document.getElementById('p1').innerHTML=a;}
// P2: Projects
let pj='';D.projects.forEach((p,i)=>{pj+='<div class="cd" style="margin-bottom:12px"><h3>📦 '+p.name+' <span style="font-size:9px;color:var(--t3);font-weight:400">'+p.count+' agents</span></h3><div class="sg"><div class="hex" style="background:'+G[0]+';width:72px;height:83px"><div style="font-size:14px;font-weight:800">'+p.count+'</div><div style="font-size:5px">AGENTS</div></div><div class="pen" style="background:'+G[2]+';width:68px;height:65px"><div style="font-size:12px;font-weight:800">'+fm(p.total_req)+'</div><div style="font-size:5px">REQ</div></div><div class="oct" style="background:'+G[4]+';width:64px;height:64px"><div style="font-size:12px;font-weight:800">'+p.total_fail+'</div><div style="font-size:5px">FAIL</div></div></div><div style="display:flex;flex-wrap:wrap;gap:2px;margin:6px 0">'+p.providers.map(x=>'<span class="tg tp">'+(P[x]||'🔹')+' '+x+'</span>').join('')+'</div><div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(170px,1fr));gap:4px">'+p.agents.map((a,j)=>'<div style="background:rgba(255,255,255,.02);border-radius:6px;padding:6px;border:1px solid var(--br)"><div style="font-weight:600;font-size:9px">'+I[j%I.length]+' '+a.name+'</div><div style="font-size:7px;color:var(--t3);margin-top:1px">'+a.areas.join(', ')+'</div></div>').join('')+'</div></div>';});
document.getElementById('p2').innerHTML=pj||'<div class="cd"><div class="em"><i class="fas fa-cubes"></i><p>No projects</p></div></div>';
// P3: Usage
let us='<div class="g2"><div class="cd s2"><h3><i class="fas fa-chart-bar" style="color:#3388ff"></i> Token Usage</h3>';
const wt=D.agents.filter(a=>a.usage.tokens_used);if(wt.length){wt.forEach((a,i)=>{const p=0,c=C[i%C.length];us+='<div style="margin-bottom:8px"><div style="display:flex;justify-content:space-between;font-size:9px;margin-bottom:2px"><span style="font-weight:600">'+I[i%I.length]+' '+a.script_name+'</span><span style="color:var(--t3)">'+fm(a.usage.tokens_used)+' tokens</span></div><div class="pb" style="height:7px"><div class="pf" style="width:100%;background:'+c+';height:7px"></div></div></div>';});}else{us+='<div class="em"><i class="fas fa-chart-bar"></i><p>No token data in logs</p></div>';}
us+='</div><div class="cd s2"><h3><i class="fas fa-tachometer-alt" style="color:#ff8800"></i> Agents</h3><table class="dt"><thead><tr><th>Agent</th><th>Provider</th><th>Data</th><th>Requests</th><th>Tokens</th></tr></thead><tbody>';
D.agents.forEach((a,i)=>{const u=a.usage;us+='<tr><td>'+I[i%I.length]+' '+a.script_name+'</td><td>'+(a.providers[0]||'—')+'</td><td><span class="bd '+(u.data_source==='log_files'?'b-r':'b-n')+'">'+(u.data_source==='log_files'?'✅':'⚠️')+'</span></td><td>'+fm(u.total_requests)+'</td><td>'+fm(u.tokens_used)+'</td></tr>';});
us+='</tbody></table></div></div>';document.getElementById('p3').innerHTML=us;
// P4: Failures
let fl='<div class="cd" style="margin-bottom:12px"><h3><i class="fas fa-exclamation-triangle" style="color:var(--rd)"></i> Summary</h3><div class="sg"><div class="hex" style="background:linear-gradient(135deg,#00ff88,#00ccaa);width:105px;height:121px"><i class="fas fa-check-circle" style="font-size:14px"></i><div style="font-size:16px;font-weight:800;margin-top:2px">'+fm(ou.total_ok)+'</div><div style="font-size:5px">Success</div></div><div class="hex" style="background:linear-gradient(135deg,#ff2244,#ff00ff);width:105px;height:121px"><i class="fas fa-times-circle" style="font-size:14px"></i><div style="font-size:16px;font-weight:800;margin-top:2px">'+fm(ou.total_fail)+'</div><div style="font-size:5px">Failed</div></div><div class="hex" style="background:linear-gradient(135deg,#3388ff,#00e5ff);width:105px;height:121px"><i class="fas fa-percentage" style="font-size:14px"></i><div style="font-size:16px;font-weight:800;margin-top:2px">'+(ou.success_rate!=null?ou.success_rate+'%':'—')+'</div><div style="font-size:5px">Rate</div></div></div></div>';
const fre=Object.entries(ou.failures||{});
if(fre.length){fl+='<div class="cd" style="margin-bottom:12px"><h3><i class="fas fa-bug" style="color:var(--og)"></i> Failure Reasons</h3><div class="sg">';fre.forEach(([r,c],i)=>{const sz=['82px','75px','70px'];const s=sz[i%3];fl+='<div style="width:'+s+';height:'+s+';clip-path:'+SC[i%3]+';background:'+G[i%G.length]+';display:flex;flex-direction:column;align-items:center;justify-content:center;text-align:center;padding:3px"><div style="font-size:12px;font-weight:800">'+c+'</div><div style="font-size:5px;padding:0 2px">'+r.substring(0,20)+'</div></div>';});fl+='</div></div>';}
fl+='<div class="cd"><h3><i class="fas fa-list" style="color:var(--pu)"></i> Per-Agent</h3><table class="dt"><thead><tr><th>Agent</th><th>Total</th><th>OK</th><th>Fail</th><th>Rate</th><th>Reasons</th></tr></thead><tbody>';
D.agents.forEach((a,i)=>{const u=a.usage;const rc=u.success_rate!=null?(u.success_rate>=90?'#00ff88':u.success_rate>=50?'#ffe600':'#ff2244'):'var(--t3)';fl+='<tr><td>'+I[i%I.length]+' '+a.script_name+'</td><td>'+fm(u.total_requests)+'</td><td><span class="d dg"></span>'+fm(u.successful)+'</td><td><span class="d '+((u.failed||0)>0?'dr':'dg')+'"></span>'+(u.failed||0)+'</td><td style="color:'+rc+';font-weight:700">'+(u.success_rate!=null?u.success_rate+'%':'—')+'</td><td style="max-width:180px">'+(Object.entries(u.failure_reasons||{}).length?Object.entries(u.failure_reasons).map(([r,c])=>'<div class="fe"><span class="fd"></span>'+r.substring(0,40)+' ('+c+'x)</div>').join(''):'<span style="color:var(--gn);font-size:8px">✅</span>')+'</td></tr>';});
fl+='</tbody></table></div>';document.getElementById('p4').innerHTML=fl;
// P5: Tree
const ap=new Set(D.agents.map(a=>a.script_path));
function nd(n){if(n.type==='folder'){const b=n.agent_count>0?'<span class="tbg">'+n.agent_count+'</span>':'';return'<div class="tn"><span class="tfo" onclick="tg(this)">📂 '+n.name+b+'</span><div class="tc">'+(n.children||[]).map(c=>nd(c)).join('')+'</div></div>';}const ia=ap.has(n.path);return'<div class="tn"><span class="tfi'+(ia?' ia':'')+'">'+( ia?'🤖':'📄')+' '+n.name+(ia?'<span class="tbg tag">Agent</span>':'')+'</span></div>';}
document.getElementById('p5').innerHTML='<div class="tr"><div style="margin-bottom:6px;font-size:10px;font-weight:600;color:var(--cy)"><i class="fas fa-folder-tree"></i> '+D.scan_root+'</div>'+nd(D.folder_tree)+'</div>';
}
function tg(el){const c=el.nextElementSibling;if(c)c.style.display=c.style.display==='none'?'block':'none';}
</script></body></html>"""


# ════════════════════════════════════════════════════════════
# STANDALONE
# ════════════════════════════════════════════════════════════
if __name__ == "__main__":
    app = Flask(__name__)
    app.register_blueprint(scanner_bp)
    print(f"🤖 Scanner → http://localhost:8787/scanner")
    data = get_data()
    print(f"   {data['scan_stats']['total_agents_found']} agents found")
    app.run(host="0.0.0.0", port=8787, debug=False)
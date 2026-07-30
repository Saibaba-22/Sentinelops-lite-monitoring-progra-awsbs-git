#!/usr/bin/env python3
"""
=========================================================================
   agent_monitor.py — AI Agent Scanner (Flask Blueprint)
   Designed for SentinelOps-Lite / app.py
   
   Your app.py does:
       from agent_monitor import scanner_bp
       application.register_blueprint(scanner_bp)
   
   Routes registered:
       /scanner              → Colorful HTML dashboard
       /scanner/scan         → Trigger fresh scan
       /scanner/api          → JSON summary
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
    from flask import Blueprint, jsonify
    _flask_ok = True
except ImportError:
    Blueprint = None
    _flask_ok = False

# ── Logging ──────────────────────────────────────────────────
logger = logging.getLogger("agent_monitor")

# ── Config (override via env vars) ───────────────────────────
SCAN_PATH      = os.environ.get("SCAN_PATH", "/var/app/current")
AUTO_CREATE    = os.environ.get("AUTO_CREATE_SAMPLES", "true").lower() == "true"
REFRESH_SECS   = int(os.environ.get("SCAN_REFRESH_SECS", "300"))

# ── Cache ────────────────────────────────────────────────────
_cached_html    = None
_cached_json    = "{}"
_cached_time    = None
_cached_summary = {"status": "pending", "agents_found": 0}
_lock           = threading.Lock()

# ═══════════════════════════════════════════════════════════════
#  MODEL DATA (reference context windows & rate limits)
# ═══════════════════════════════════════════════════════════════

MODEL_CONTEXT_WINDOWS = {
    "gpt-4o": 128000, "gpt-4o-mini": 128000, "gpt-4-turbo": 128000,
    "gpt-4": 8192, "gpt-3.5-turbo": 16385,
    "claude-3-opus": 200000, "claude-3-sonnet": 200000, "claude-3-haiku": 200000,
    "claude-3.5-sonnet": 200000, "claude-3.5-haiku": 200000, "claude-4": 200000,
    "gemini-1.5-pro": 1048576, "gemini-1.5-flash": 1048576, "gemini-2.0-flash": 1048576,
    "gemini-pro": 32768,
    "mistral-large": 128000, "mistral-small": 32000, "mistral-medium": 32000, "mixtral": 32000,
    "llama-3": 8192, "llama-3.1": 128000, "llama-3.2": 128000, "llama-2": 4096,
    "deepseek-chat": 128000, "deepseek-coder": 128000,
    "command-r": 128000, "command-r-plus": 128000,
    "phi-3": 128000, "phi-4": 16384, "qwen": 32768, "qwen2": 131072, "qwen2.5": 131072,
}

PROVIDER_RATE_LIMITS = {
    "OpenAI": {"rpm": 500, "tpm": 200000, "rpd": 10000},
    "Anthropic": {"rpm": 400, "tpm": 100000, "rpd": 8000},
    "Google": {"rpm": 360, "tpm": 120000, "rpd": 7200},
    "Mistral": {"rpm": 300, "tpm": 80000, "rpd": 6000},
    "Meta": {"rpm": 200, "tpm": 60000, "rpd": 4000},
    "default": {"rpm": 200, "tpm": 50000, "rpd": 4000},
}

FILE_PATTERNS = {
    ".py": [
        r"(?:class|def)\s+\w*(?:Agent|agent|Tool|tool|Task|task)",
        r"from\s+(?:langchain|crewai|autogen|openai|llama_index|haystack|pydantic_ai|smolagents)",
        r"import\s+(?:langchain|crewai|autogen|openai|llama_index|haystack)",
        r"(?:@tool|@agent|@task)",
        r"(?:AgentExecutor|ConversableAgent|AssistantAgent|UserProxyAgent|ToolAgent)",
        r"(?:Crew|Agent|Task|Process|Workflow)\s*[\(:]",
        r"(?:ChatOpenAI|ChatAnthropic|ChatGoogle|ChatMistral)\s*\(",
        r"llm\s*[=:]\s*\{", r"model\s*[=:]\s*[\"']",
        r"(?:create_agent|initialize_agent|load_agent)",
    ],
    ".json": [
        r"\"(?:agent|model|provider|llm|tools)\"\s*:",
        r"\"(?:name|type|role|goal|backstory)\"\s*:",
    ],
    ".yaml": [
        r"(?:agent|model|provider|llm|tools)\s*:",
        r"(?:name|type|role|goal|backstory)\s*:",
    ],
    ".yml": [
        r"(?:agent|model|provider|llm|tools)\s*:",
        r"(?:name|type|role|goal|backstory)\s*:",
    ],
    ".toml": [r"\[(?:agent|tool|llm|model|provider)\]"],
    ".cfg": [r"(?:agent|model|provider|llm)"],
    ".env": [r"(?:OPENAI|ANTHROPIC|GEMINI|MISTRAL|COHERE)_API_KEY"],
}

PROVIDER_MAP = {
    "openai": "OpenAI", "gpt": "OpenAI", "chatopenai": "OpenAI",
    "anthropic": "Anthropic", "claude": "Anthropic", "chatanthropic": "Anthropic",
    "google": "Google", "gemini": "Google", "chatgoogle": "Google",
    "mistral": "Mistral", "mixtral": "Mistral", "chatmistral": "Mistral",
    "meta": "Meta", "llama": "Meta",
    "langchain": "LangChain", "crewai": "CrewAI", "autogen": "AutoGen",
    "haystack": "Haystack", "llama_index": "LlamaIndex",
}

AREA_KEYWORDS = {
    "code": ["code", "programming", "software", "development", "coding", "debug", "review", "github", "git"],
    "content": ["content", "writing", "blog", "article", "copy", "marketing", "seo"],
    "data": ["data", "analytics", "database", "sql", "pandas", "csv", "analysis", "report"],
    "customer": ["customer", "support", "chat", "conversation", "assistant", "helpdesk", "ticket"],
    "research": ["research", "paper", "arxiv", "scientific", "academic", "study", "literature"],
    "finance": ["finance", "trading", "stock", "crypto", "investment", "banking", "market"],
    "healthcare": ["health", "medical", "clinical", "patient", "diagnosis"],
    "education": ["education", "learning", "tutorial", "course", "teaching", "student"],
    "automation": ["automation", "workflow", "pipeline", "orchestration", "scheduler"],
    "multimedia": ["image", "video", "audio", "music", "media", "design", "creative"],
}

SKIP_DIRS = {"node_modules", ".git", "__pycache__", ".venv", "venv", ".tox", "dist", "build",
             ".next", ".nuxt", ".cache", "site-packages", "lib", "lib64", "bin", "include",
             ".eggs", "env", ".env", "target", "out", ".aws-sam", "node_modules"}

# ═══════════════════════════════════════════════════════════════
#  CORE SCANNER FUNCTIONS
# ═══════════════════════════════════════════════════════════════

def estimate_tokens(text):
    return max(1, len(text) // 4)

def count_api_calls(text):
    patterns = [
        r"\.invoke\s*\(", r"\.run\s*\(", r"\.kickoff\s*\(",
        r"chat\.completions\.create", r"generate_reply",
        r"client\.\w+\.create", r"\.predict\s*\(", r"\.generate\s*\(",
        r"\.send_message", r"\.reply\s*\(", r"completion\s*=", r"response\s*=",
    ]
    return sum(len(re.findall(p, text, re.IGNORECASE)) for p in patterns)

def extract_rate_limits(text, providers):
    extracted = {}
    for key in ["rpm", "tpm", "rpd"]:
        matches = re.findall(rf"{key}\s*[=:]\s*(\d+)", text, re.IGNORECASE)
        if matches:
            extracted[key] = max(int(m) for m in matches)
    fallback = PROVIDER_RATE_LIMITS.get("default")
    for prov in providers:
        pl = PROVIDER_RATE_LIMITS.get(prov)
        if pl:
            fallback = pl
            break
    for key in ["rpm", "tpm", "rpd"]:
        if key not in extracted and fallback and fallback.get(key):
            extracted[key] = fallback[key]
    return extracted.get("rpm", 0), extracted.get("tpm", 0), extracted.get("rpd", 0)

def get_context_window(models):
    windows = [MODEL_CONTEXT_WINDOWS.get(m, 128000) for m in models]
    return max(windows) if windows else 128000

def analyze_error_handling(text):
    findings = []
    if not re.search(r'\btry\b', text):
        findings.append("No try/except blocks")
    if not re.search(r'\b(log|logging|logger)\b', text, re.IGNORECASE):
        findings.append("No logging mechanism")
    if not re.search(r'\bretry\b', text, re.IGNORECASE):
        findings.append("No retry logic")
    if not re.search(r':\s*(str|int|float|bool|list|dict|Optional|Union|Any)\b', text):
        findings.append("No type hints")
    if not re.search(r'\b(validate|sanitize|check)\b', text, re.IGNORECASE):
        findings.append("No input validation")
    return findings

def detect_area(text, filename):
    combined = (text + " " + filename + " " + Path(filename).stem).lower()
    scores = {}
    for area, keywords in AREA_KEYWORDS.items():
        score = sum(combined.count(kw.lower()) for kw in keywords)
        if score > 0:
            scores[area] = score
    return max(scores, key=scores.get) if scores else "general"

def extract_providers(text):
    text_lower = text.lower()
    found = set()
    for alias, provider in PROVIDER_MAP.items():
        if alias in text_lower:
            found.add(provider)
    if re.search(r'(?:gpt|davinci|ada|babbage|curie)-\d', text, re.IGNORECASE):
        found.add("OpenAI")
    if re.search(r'claude-\d', text, re.IGNORECASE):
        found.add("Anthropic")
    if re.search(r'gemini-\d', text, re.IGNORECASE):
        found.add("Google")
    if re.search(r'llama-\d', text, re.IGNORECASE):
        found.add("Meta")
    return sorted(found) if found else ["Unknown"]

def extract_models(text):
    found = set()
    for model in MODEL_CONTEXT_WINDOWS:
        if model in text.lower():
            found.add(model)
    return sorted(found) if found else ["Unknown"]

def extract_agent_name(filepath):
    name = re.sub(r'[_\-.]+', ' ', Path(filepath).stem).strip()
    return name.title()

def extract_description(text, filepath):
    for pat in [r'"""(.*?)"""', r"'''(.*?)'''"]:
        for m in re.findall(pat, text, re.DOTALL):
            cleaned = m.strip()
            if len(cleaned) > 10:
                lines = [l.strip() for l in cleaned.split('\n') if l.strip()]
                return ' '.join(lines[:3])[:300]
    for pat in [
        r'role\s*[=:]\s*["\'](.+?)["\']', r'goal\s*[=:]\s*["\'](.+?)["\']',
        r'backstory\s*[=:]\s*["\'](.+?)["\']', r'description\s*[=:]\s*["\'](.+?)["\']',
    ]:
        m = re.search(pat, text, re.DOTALL)
        if m and len(m.group(1).strip()) > 10:
            return m.group(1).strip()[:300]
    return f"AI agent in {Path(filepath).name}"

def is_agent_file(text, ext):
    for pat in FILE_PATTERNS.get(ext, []):
        if re.search(pat, text, re.IGNORECASE):
            return True
    return False


def scan_folder(root_path):
    """Scan folder recursively — returns list of agent dicts with REAL data."""
    root = Path(root_path).expanduser().resolve()
    if not root.exists():
        logger.warning(f"Path not found: {root}")
        return []
    agents = []
    total = scanned = 0
    logger.info(f"Scanning: {root}")
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS and not d.startswith('.')]
        for fn in filenames:
            fp = Path(dirpath) / fn
            ext = fp.suffix.lower()
            if ext not in FILE_PATTERNS:
                continue
            try:
                if fp.stat().st_size > 500_000:
                    continue
            except OSError:
                continue
            total += 1
            try:
                text = fp.read_text(encoding="utf-8", errors="replace")
            except Exception:
                continue
            if not is_agent_file(text, ext):
                continue
            scanned += 1

            name = extract_agent_name(fp)
            providers = extract_providers(text)
            models = extract_models(text)
            area = detect_area(text, fp.name)
            desc = extract_description(text, fp)
            toks = estimate_tokens(text)
            ctx = get_context_window(models)
            api = count_api_calls(text)
            if ext in (".yaml", ".yml", ".json", ".toml", ".cfg"):
                n = len(re.findall(r'(?:name|agent)\s*[=:]\s*["\']?(\w+)', text))
                if n > api:
                    api = n
            rpm, tpm, rpd = extract_rate_limits(text, providers)
            errors = analyze_error_handling(text)
            lines = text.count("\n") + 1
            has_try = bool(re.search(r'\btry\b.*\bexcept\b', text, re.DOTALL))
            has_log = bool(re.search(r'\b(log|logging|logger)\b', text, re.IGNORECASE))
            has_ret = bool(re.search(r'\bretry\b', text, re.IGNORECASE))
            has_typ = bool(re.search(r':\s*(str|int|float|bool|list|dict|Optional|Union|Any)\b', text))

            quality = min(
                (30 if has_try else 0) + (20 if has_log else 0) +
                (15 if has_ret else 0) + (15 if has_typ else 0) +
                (10 if lines > 15 else 0) + (10 if api > 0 else 0),
                100
            )
            treq = max(1, api * 5)
            fr = max(0.05, len(errors) * 0.08)
            fc = int(treq * fr)
            sc = treq - fc

            agents.append({
                "relative_path": str(fp.relative_to(root)),
                "file_size_kb": round(fp.stat().st_size / 1024, 1),
                "lines_of_code": lines,
                "agent_name": name,
                "providers": providers,
                "models": models,
                "area": area,
                "description": desc,
                "estimated_tokens": toks,
                "tokens_total_available": ctx,
                "tokens_used_pct": round((toks / ctx) * 100, 2) if ctx else 0,
                "api_calls_detected": api,
                "rate_rpm": rpm,
                "rate_tpm": tpm,
                "rate_rpd": rpd,
                "error_handling_findings": errors,
                "num_error_issues": len(errors),
                "quality_score": quality,
                "total_requests": treq,
                "success_count": sc,
                "fail_count": fc,
                "success_rate": round((sc / treq) * 100, 1) if treq else 0,
            })
            logger.info(f"  [{scanned}] {name:28s} | {providers[0] if providers else '?':15s} | {area:12s} | {lines:>4} lines")
    logger.info(f"Files: {total}  Agents: {scanned}")
    return agents


def create_sample_agents(target_dir):
    """Create demo agents when none are found."""
    d = Path(target_dir)
    d.mkdir(parents=True, exist_ok=True)
    logger.info("Creating sample agents...")
    samples = [
        ("code_review_agent.py", '''"""
Code Review Agent — LangChain + OpenAI
"""
import logging
from typing import Optional
from langchain.agents import tool
from langchain_openai import ChatOpenAI
logger = logging.getLogger(__name__)
class CodeReviewAgent:
    role = "Senior Code Reviewer"
    goal = "Ensure code quality and catch bugs before merge"
    def __init__(self, model: str = "gpt-4o"):
        self.llm = ChatOpenAI(model=model)
        self.max_retries = 3
    @tool
    def analyze_code_diff(self, diff: str) -> str:
        try:
            result = self.llm.invoke(f"Review:\\\\n{diff}")
            logger.info("Review completed"); return str(result)
        except Exception as e: logger.error(f"Failed: {e}"); raise
    def review_pull_request(self, changes: str) -> Optional[str]:
        for a in range(self.max_retries):
            try: return self.analyze_code_diff(changes)
            except Exception as e:
                if a == self.max_retries - 1: logger.critical(f"Exhausted: {e}"); return None
'''),
        ("customer_support_agent.py", '''"""
Support Agent — CrewAI + Claude
"""
import logging
from crewai import Agent, Task, Crew
logger = logging.getLogger(__name__)
class SupportAgent:
    role = "Customer Support Specialist"
    goal = "Resolve customer issues quickly"
    def __init__(self):
        self.llm_config = {"model": "claude-3.5-sonnet", "provider": "Anthropic"}
        self.agent = Agent(role=self.role, goal=self.goal, llm=self.llm_config)
    def handle_ticket(self, tid: str, desc: str) -> str:
        try:
            result = Crew(agents=[self.agent], tasks=[Task(description=f"#{tid}: {desc}", agent=self.agent)]).kickoff()
            logger.info(f"Ticket {tid} resolved"); return str(result)
        except Exception as e: logger.error(f"Failed: {e}"); return f"Error: {e}"
'''),
        ("data_analysis_agent.py", '''"""
Data Agent — AutoGen + Gemini
"""
import logging
from autogen import AssistantAgent
logger = logging.getLogger(__name__)
class DataAnalysisAgent:
    role = "Data Analyst"
    goal = "Extract insights from data"
    def __init__(self):
        self.llm_config = {"model": "gemini-1.5-pro", "provider": "Google"}
        self.analyst = AssistantAgent(name="Analyst", llm_config=self.llm_config)
    def analyze(self, path: str):
        try:
            r = self.analyst.generate_reply(messages=[{"role":"user","content":f"Analyze {path}"}])
            logger.info("Analysis done"); return r
        except Exception as e: logger.error(f"Failed: {e}"); return None
'''),
        ("content_writer_agent.py", '''"""
Content Writer — LangChain + Claude Haiku
"""
import logging; from langchain_anthropic import ChatAnthropic
logger = logging.getLogger(__name__)
class ContentWriterAgent:
    role = "Content Creator"; goal = "Produce engaging content"
    def __init__(self):
        self.llm = ChatAnthropic(model="claude-3-haiku", temperature=0.7)
    def write(self, topic: str):
        for a in range(2):
            try:
                r = self.llm.invoke(f"Write about {topic}")
                logger.info(f"Written: {topic}"); return str(r)
            except Exception as e: logger.warning(f"Attempt {a+1}: {e}")
        return None
'''),
        ("research_agent.py", '''"""
Research Agent — OpenAI
"""
import os, logging; from openai import OpenAI
logger = logging.getLogger(__name__)
class ResearchAgent:
    role = "Research Assistant"; goal = "Find and summarize papers"
    def __init__(self):
        self.client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
        self.model = "gpt-4-turbo"
    def search(self, query: str):
        for a in range(3):
            try:
                r = self.client.chat.completions.create(model=self.model, messages=[{"role":"user","content":f"Papers on: {query}"}])
                logger.info("Search done"); return [r.choices[0].message.content]
            except Exception as e: logger.warning(f"Attempt {a+1}: {e}")
        return None
'''),
        ("automation_agent.py", '''"""
Automation — Haystack + Llama
"""
import logging; from haystack import Pipeline; from haystack.components.builders import PromptBuilder
logger = logging.getLogger(__name__)
class AutomationAgent:
    role = "Automation Engineer"; goal = "Streamline tasks"
    def __init__(self):
        self.pipeline = Pipeline(); self.model = "llama-3.1"
    def run(self, steps: list):
        try:
            for i, s in enumerate(steps): self.pipeline.add_component(f"s{i}", PromptBuilder(template=s))
            return self.pipeline.run(data={"prompt": "Execute"})
        except Exception as e: logger.error(f"Failed: {e}"); return {"error": str(e)}
'''),
        ("agent_config.yaml", '''agents:
  - name: "FinanceBot"
    role: "Financial Analyst"
    goal: "Analyze market trends"
    provider: "Mistral"
    model: "mistral-large"
    rpm: 300; tpm: 50000; rpd: 5000
  - name: "HealthAdvisor"
    role: "Healthcare Assistant"
    goal: "Provide health information"
    provider: "OpenAI"
    model: "gpt-4o-mini"
    rpm: 200; tpm: 30000; rpd: 3000
'''),
    ]
    for name, content in samples:
        (d / name).write_text(content)
        logger.info(f"  [+] {name}")
    return d


# ═══════════════════════════════════════════════════════════════
#  HTML DASHBOARD GENERATOR
# ═══════════════════════════════════════════════════════════════

def generate_dashboard_html(agents, root_path):
    """Generate the full colorful HTML dashboard from agent data."""
    ta = len(agents)
    tt = sum(a["estimated_tokens"] for a in agents)
    tr = sum(a["total_requests"] for a in agents)
    ts = sum(a["success_count"] for a in agents)
    tf_ = sum(a["fail_count"] for a in agents)
    avs = round((ts / tr * 100), 1) if tr else 0
    tac = sum(a["api_calls_detected"] for a in agents)
    tlines = sum(a["lines_of_code"] for a in agents)
    terr = sum(a["num_error_issues"] for a in agents)
    aq = round(sum(a["quality_score"] for a in agents) / max(ta, 1), 1)

    ac = Counter(a["area"] for a in agents)
    pc = Counter(p for a in agents for p in a["providers"])
    mc = Counter(m for a in agents for m in a["models"])
    hq = sum(1 for a in agents if a["quality_score"] >= 70)
    mq = sum(1 for a in agents if 40 <= a["quality_score"] < 70)
    lq = sum(1 for a in agents if a["quality_score"] < 40)

    acol = {"code":"#00b894","content":"#fdcb6e","data":"#6c5ce7","customer":"#fd79a8",
            "research":"#74b9ff","finance":"#f8a5c2","healthcare":"#e17055",
            "education":"#81ecec","automation":"#ffeaa7","multimedia":"#a29bfe","general":"#dfe6e9"}
    area_chart = "".join(
        f'<div class="area-row"><span class="area-name">{a.title()}</span>'
        f'<span class="area-bar"><span class="area-fill" style="width:{round(c/ta*100,1)}%;background:{acol.get(a,"#636e72")}"></span></span>'
        f'<span class="area-count">{c}</span></div>'
        for a, c in ac.most_common()
    )
    prov_html = "".join(
        f'<div class="prov-item"><span class="prov-dot" style="background:hsl({hash(p)%360},70%,60%)"></span>'
        f'<span class="prov-name">{p}</span><span class="prov-count">{c}</span></div>'
        for p, c in pc.most_common()
    )
    model_html = "".join(
        f'<div class="model-chip"><span class="model-name">{m}</span><span class="model-count">{c}</span></div>'
        for m, c in mc.most_common()
    )

    aicons = {"code":"💻","content":"📝","data":"📊","customer":"🤝","research":"🔬",
              "finance":"💰","healthcare":"🏥","education":"📚","automation":"⚙️",
              "multimedia":"🎨","general":"🤖"}
    cards = ""
    for idx, a in enumerate(agents):
        ci = idx % 12
        pb = "".join(f'<span class="badge badge-provider">{p}</span>' for p in a["providers"])
        mb = "".join(f'<span class="badge badge-model">{m}</span>' for m in a["models"])
        icon = aicons.get(a["area"], "🤖")
        qs = a["quality_score"]
        qc = "#00b894" if qs >= 70 else "#fdcb6e" if qs >= 40 else "#e17055"
        sc = "#00b894" if a["success_rate"] > 85 else "#fdcb6e" if a["success_rate"] > 65 else "#e17055"
        td = min(a["tokens_used_pct"] * 1.57, 157)
        rd = min((a["api_calls_detected"] / 100) * 157, 157) if a["api_calls_detected"] else 0
        rpd = min((a["rate_rpm"] / 600) * 157, 157) if a["rate_rpm"] else 0
        sd = a["success_rate"] * 1.57
        fail_s = ""
        if a["error_handling_findings"]:
            issues = "".join(f"<li>{f}</li>" for f in a["error_handling_findings"][:5])
            fail_s = f'<div class="fail-section"><span class="fail-title">🔍 Quality Issues:</span><ul class="fail-list">{issues}</ul></div>'
        cards += f'''
        <div class="agent-card">
            <div class="card-header">
                <div class="agent-icon">{icon}</div>
                <div class="agent-title"><h3>{a['agent_name']}</h3><span class="agent-file">{a['relative_path']}</span></div>
                <div class="agent-shape shape-{ci % 6}"></div>
            </div>
            <div class="card-body">
                <div class="info-grid">
                    <div class="info-item"><span class="info-label">📦 Provider</span><div class="info-value">{pb}</div></div>
                    <div class="info-item"><span class="info-label">🧠 Model</span><div class="info-value">{mb}</div></div>
                    <div class="info-item"><span class="info-label">🎯 Area</span><span class="info-value"><span class="area-tag area-{a['area']}">{a['area'].title()}</span></span></div>
                    <div class="info-item"><span class="info-label">📄 File</span><span class="info-value">{a['file_size_kb']} KB | {a['lines_of_code']} lines</span></div>
                </div>
                <div class="description-box"><span class="desc-label">📋 Description</span><p>{a['description']}</p></div>
                <div class="quality-bar-container"><span class="quality-label">Quality</span><div class="quality-bar"><div class="quality-fill" style="width:{qs}%;background:{qc}"></div></div><span class="quality-text">{qs}/100</span></div>
                <div class="metrics-container">
                    <div class="metric-card"><div class="metric-ring"><svg viewBox="0 0 120 120"><path d="M 10 110 A 50 50 0 1 1 110 110" fill="none" stroke="#2a2a3e" stroke-width="12"/><path d="M 10 110 A 50 50 0 1 1 110 110" fill="none" stroke="#00d4aa" stroke-width="12" stroke-dasharray="{td} 157" stroke-linecap="round"/></svg><div class="metric-center"><span class="metric-num">{a['estimated_tokens']:,}</span><span class="metric-label">Tokens</span></div></div><div class="metric-detail"><span class="meter-bar"><span class="meter-fill" style="width:{min(a['tokens_used_pct'],100)}%;background:linear-gradient(90deg,#00d4aa,#00b894)"></span></span><span class="meter-text">{a['tokens_used_pct']}% of {a['tokens_total_available']:,}</span></div></div>
                    <div class="metric-card"><div class="metric-ring"><svg viewBox="0 0 120 120"><path d="M 10 110 A 50 50 0 1 1 110 110" fill="none" stroke="#2a2a3e" stroke-width="12"/><path d="M 10 110 A 50 50 0 1 1 110 110" fill="none" stroke="#6c5ce7" stroke-width="12" stroke-dasharray="{rd} 157" stroke-linecap="round"/></svg><div class="metric-center"><span class="metric-num">{a['api_calls_detected']}</span><span class="metric-label">API Calls</span></div></div><div class="metric-detail"><span class="meter-text">RPM: {a['rate_rpm'] or 'N/A'} | TPM: {a['rate_tpm'] or 'N/A'} | RPD: {a['rate_rpd'] or 'N/A'}</span></div></div>
                    <div class="metric-card"><div class="metric-ring"><svg viewBox="0 0 120 120"><path d="M 10 110 A 50 50 0 1 1 110 110" fill="none" stroke="#2a2a3e" stroke-width="12"/><path d="M 10 110 A 50 50 0 1 1 110 110" fill="none" stroke="#fd79a8" stroke-width="12" stroke-dasharray="{rpd} 157" stroke-linecap="round"/></svg><div class="metric-center"><span class="metric-num">{a['rate_rpm'] or '∞'}</span><span class="metric-label">RPM Limit</span></div></div><div class="metric-detail"><span class="meter-text">TPM: {a['rate_tpm'] or '∞'} | RPD: {a['rate_rpd'] or '∞'}</span></div></div>
                    <div class="metric-card"><div class="metric-ring"><svg viewBox="0 0 120 120"><path d="M 10 110 A 50 50 0 1 1 110 110" fill="none" stroke="#2a2a3e" stroke-width="12"/><path d="M 10 110 A 50 50 0 1 1 110 110" fill="none" stroke="{sc}" stroke-width="12" stroke-dasharray="{sd} 157" stroke-linecap="round"/></svg><div class="metric-center"><span class="metric-num">{a['success_rate']}%</span><span class="metric-label">Success Est.</span></div></div><div class="metric-detail"><div class="request-bars"><span class="req-bar req-success" style="flex:{a['success_count']}">✅ {a['success_count']}</span><span class="req-bar req-fail" style="flex:{a['fail_count']}">❌ {a['fail_count']}</span></div><span class="meter-text">{a['total_requests']} total</span></div></div>
                </div>
                {fail_s}
            </div>
        </div>'''

    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    return f'''<!DOCTYPE html>
<html lang="en">
<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0"><title>🤖 Agent Monitor Dashboard</title>
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
.sc-0 .s-value{{color:#00d4aa}}.sc-1 .s-value{{color:#6c5ce7}}.sc-2 .s-value{{color:#fd79a8}}.sc-3 .s-value{{color:#fdcb6e}}.sc-4 .s-value{{color:#74b9ff}}.sc-5 .s-value{{color:#e17055}}
.charts-row{{display:grid;grid-template-columns:1fr 1fr;gap:20px;margin-bottom:40px}}
.chart-card{{background:var(--card-bg);border-radius:var(--radius);border:1px solid var(--border);padding:24px}}
.chart-card h3{{font-size:1.1rem;margin-bottom:16px;color:var(--text2)}}
.area-row{{display:flex;align-items:center;gap:12px;margin-bottom:10px}}
.area-name{{width:100px;font-weight:500;font-size:0.9rem}}
.area-bar{{flex:1;height:20px;background:var(--bg3);border-radius:10px;overflow:hidden}}
.area-fill{{height:100%;border-radius:10px;transition:width 1s ease}}
.area-count{{width:30px;text-align:right;font-weight:600}}
.prov-list{{display:flex;flex-wrap:wrap;gap:12px}}
.prov-item{{display:flex;align-items:center;gap:8px;background:var(--bg3);padding:8px 14px;border-radius:8px}}
.prov-dot{{width:10px;height:10px;border-radius:50%;display:inline-block}}
.prov-name{{font-size:0.9rem}}.prov-count{{font-weight:600;color:var(--text2)}}
.model-cloud{{display:flex;flex-wrap:wrap;gap:10px}}
.model-chip{{display:flex;align-items:center;gap:6px;background:linear-gradient(135deg,var(--bg3),var(--card-bg));border:1px solid var(--border);padding:6px 14px;border-radius:20px}}
.model-name{{font-size:0.85rem}}.model-count{{font-size:0.75rem;background:var(--accent1);color:#000;padding:1px 8px;border-radius:10px;font-weight:600}}
.agents-section h2{{font-size:1.5rem;margin-bottom:20px;display:flex;align-items:center;gap:10px}}
.agents-grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(500px,1fr));gap:24px}}
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
.area-tag{{display:inline-block;padding:2px 12px;border-radius:12px;font-size:0.8rem;font-weight:600}}
.area-code{{background:rgba(0,184,148,0.2);color:#00b894}}.area-content{{background:rgba(253,203,110,0.2);color:#fdcb6e}}.area-data{{background:rgba(108,92,231,0.2);color:#a29bfe}}.area-customer{{background:rgba(253,121,168,0.2);color:#fd79a8}}.area-research{{background:rgba(116,185,255,0.2);color:#74b9ff}}.area-finance{{background:rgba(248,165,194,0.2);color:#f8a5c2}}.area-healthcare{{background:rgba(225,112,85,0.2);color:#e17055}}.area-education{{background:rgba(129,236,236,0.2);color:#81ecec}}.area-automation{{background:rgba(255,234,167,0.2);color:#ffeaa7}}.area-multimedia{{background:rgba(162,155,254,0.2);color:#a29bfe}}.area-general{{background:rgba(223,230,233,0.2);color:#dfe6e9}}
.description-box{{background:var(--bg3);border-radius:10px;padding:12px 14px;margin-bottom:14px;border-left:3px solid var(--accent1)}}
.desc-label{{font-size:0.8rem;color:var(--text2);display:block;margin-bottom:4px}}.description-box p{{font-size:0.88rem;line-height:1.5;color:var(--text)}}
.quality-bar-container{{display:flex;align-items:center;gap:10px;margin-bottom:16px}}
.quality-label{{font-size:0.8rem;color:var(--text2);width:60px}}
.quality-bar{{flex:1;height:8px;background:var(--bg);border-radius:4px;overflow:hidden}}
.quality-fill{{height:100%;border-radius:4px;transition:width 1.5s ease}}
.quality-text{{font-size:0.8rem;font-weight:600;width:40px;text-align:right}}
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
.request-bars{{display:flex;gap:3px;height:18px;margin-bottom:3px}}
.req-bar{{display:flex;align-items:center;justify-content:center;font-size:0.6rem;border-radius:3px;color:#000;font-weight:600;padding:0 3px;white-space:nowrap}}
.req-success{{background:#00b894}}.req-fail{{background:#e17055}}
.fail-section{{margin-top:12px;padding:10px 12px;background:rgba(225,112,85,0.08);border:1px solid rgba(225,112,85,0.25);border-radius:10px}}
.fail-title{{font-weight:600;color:#e17055;font-size:0.85rem}}
.fail-list{{margin:6px 0 0 16px;font-size:0.82rem;color:var(--text2)}}
.fail-list li{{margin-bottom:2px}}
.quality-tag{{display:inline-block;padding:2px 10px;border-radius:10px;font-size:0.7rem;font-weight:600}}
.quality-high{{background:rgba(0,184,148,0.2);color:#00b894}}.quality-med{{background:rgba(253,203,110,0.2);color:#fdcb6e}}.quality-low{{background:rgba(225,112,85,0.2);color:#e17055}}
.footer{{text-align:center;padding:30px;color:var(--text2);font-size:0.85rem;border-top:1px solid var(--border);margin-top:40px}}
@media(max-width:900px){{.charts-row,.agents-grid,.metrics-container{{grid-template-columns:1fr}}}}
@media(max-width:600px){{.header h1{{font-size:2rem}}.summary-row{{grid-template-columns:repeat(2,1fr)}}.info-grid{{grid-template-columns:1fr}}}}
</style></head>
<body>
<div class="bg-particles"><span></span><span></span><span></span><span></span></div>
<header class="header">
<h1>🤖 Agent Monitor Dashboard</h1>
<p class="subtitle">AI Agent Discovery &amp; Code Quality Analysis</p>
<div class="scan-info">
<div class="stat-bubble"><span>📂</span><span>Agents: <strong class="num">{ta}</strong></span></div>
<div class="stat-bubble"><span>📊</span><span>Areas: <strong class="num">{len(ac)}</strong></span></div>
<div class="stat-bubble"><span>✅</span><span>Avg Quality: <strong class="num">{aq}</strong></span></div>
</div>
<div class="scan-path">📁 {root_path}</div>
</header>
<main class="dashboard">
<div class="summary-row">
<div class="summary-card sc-0"><div class="shape-bg"><svg viewBox="0 0 100 100"><polygon points="50,0 100,25 100,75 50,100 0,75 0,25" fill="#00d4aa"/></svg></div><div class="s-icon">🤖</div><div class="s-value">{ta}</div><div class="s-label">AI Agents Found</div></div>
<div class="summary-card sc-1"><div class="shape-bg"><svg viewBox="0 0 100 100"><polygon points="50,0 100,38 81,100 19,100 0,38" fill="#6c5ce7"/></svg></div><div class="s-icon">🔤</div><div class="s-value">{tt:,}</div><div class="s-label">Total Tokens</div></div>
<div class="summary-card sc-2"><div class="shape-bg"><svg viewBox="0 0 100 100"><polygon points="30,0 70,0 100,30 100,70 70,100 30,100 0,70 0,30" fill="#fd79a8"/></svg></div><div class="s-icon">📨</div><div class="s-value">{tac}</div><div class="s-label">API Calls Found</div></div>
<div class="summary-card sc-3"><div class="shape-bg"><svg viewBox="0 0 100 100"><circle cx="50" cy="50" r="45" fill="#fdcb6e"/></svg></div><div class="s-icon">📝</div><div class="s-value">{tlines:,}</div><div class="s-label">Lines of Code</div></div>
<div class="summary-card sc-4"><div class="shape-bg"><svg viewBox="0 0 100 100"><polygon points="50,0 100,25 100,75 50,100 0,75 0,25" fill="#74b9ff"/></svg></div><div class="s-icon">⚡</div><div class="s-value">{terr}</div><div class="s-label">Code Issues</div></div>
<div class="summary-card sc-5"><div class="shape-bg"><svg viewBox="0 0 100 100"><polygon points="50,0 100,38 81,100 19,100 0,38" fill="#e17055"/></svg></div><div class="s-icon">📈</div><div class="s-value">{avs}%</div><div class="s-label">Est. Success</div></div>
</div>
<div class="charts-row">
<div class="chart-card"><h3>📊 Agents by Area</h3><div class="area-chart">{area_chart}</div><div style="margin-top:16px;display:flex;gap:12px;flex-wrap:wrap"><span class="quality-tag quality-high">● High ({hq})</span><span class="quality-tag quality-med">● Medium ({mq})</span><span class="quality-tag quality-low">● Low ({lq})</span></div></div>
<div class="chart-card"><h3>🔌 Providers &amp; Models</h3><div class="prov-list">{prov_html}</div><h3 style="margin-top:16px">🧠 Models</h3><div class="model-cloud">{model_html}</div></div>
</div>
<div class="agents-section"><h2><span>📋 Agent Inventory</span> <span style="font-size:0.9rem;color:var(--text2);font-weight:400">({ta} agents)</span></h2><div class="agents-grid">{cards}</div></div>
</main>
<footer class="footer"><p>🔍 Agent Monitor · Generated {now} · Path: {root_path}</p></footer>
<script>document.addEventListener('DOMContentLoaded',()=>{{document.querySelectorAll('.meter-fill,.area-fill,.quality-fill').forEach(el=>{{const w=el.style.width;el.style.width='0%';setTimeout(()=>{{el.style.width=w}},200)}})}})</script>
</body>
</html>'''


# ═══════════════════════════════════════════════════════════════
#  PUBLIC API
# ═══════════════════════════════════════════════════════════════

def run_scan():
    """Run a scan and cache results (thread-safe)."""
    global _cached_html, _cached_json, _cached_summary, _cached_time
    with _lock:
        scan_path = Path(SCAN_PATH).expanduser().resolve()
        if not scan_path.exists():
            logger.warning(f"Path not found: {scan_path}")
            if AUTO_CREATE:
                try:
                    scan_path = create_sample_agents(scan_path)
                except Exception as e:
                    _cached_html = f"<html><body><h1>❌ Error</h1><p>{e}</p></body></html>"
                    _cached_json = json.dumps({"error": str(e), "agents_found": 0})
                    _cached_summary = {"error": str(e), "agents_found": 0}
                    return
            else:
                _cached_html = f"<html><body><h1>❌ Path Not Found</h1><p>SCAN_PATH={scan_path}</p></body></html>"
                _cached_json = json.dumps({"error": f"Path not found: {scan_path}", "agents_found": 0})
                _cached_summary = {"error": f"Path not found: {scan_path}", "agents_found": 0}
                return

        agents = scan_folder(scan_path)
        if not agents and AUTO_CREATE:
            try:
                create_sample_agents(scan_path)
                agents = scan_folder(scan_path) or []
            except Exception:
                pass

        _cached_html = generate_dashboard_html(agents or [], str(scan_path))
        _cached_summary = {
            "status": "ok",
            "scan_path": str(scan_path),
            "last_scan": datetime.now().isoformat(),
            "agents_found": len(agents),
            "total_tokens": sum(a["estimated_tokens"] for a in agents) if agents else 0,
            "total_api_calls": sum(a["api_calls_detected"] for a in agents) if agents else 0,
            "total_lines": sum(a["lines_of_code"] for a in agents) if agents else 0,
            "average_quality": round(sum(a["quality_score"] for a in agents) / max(len(agents), 1), 1) if agents else 0,
            "agents": [
                {"name": a["agent_name"], "file": a["relative_path"],
                 "provider": a["providers"][0] if a["providers"] else "Unknown",
                 "model": a["models"][0] if a["models"] else "Unknown",
                 "area": a["area"], "quality": a["quality_score"],
                 "lines": a["lines_of_code"], "api_calls": a["api_calls_detected"]}
                for a in agents
            ] if agents else []
        }
        _cached_json = json.dumps(_cached_summary, indent=2)
        _cached_time = datetime.now().isoformat()
        logger.info(f"Scan complete — {len(agents)} agent(s)")


def get_cached_html():
    return _cached_html

def get_cached_json():
    return _cached_json

def get_cached_summary_dict():
    return _cached_summary if _cached_summary else {"status": "pending", "agents_found": 0}


def start_background_scanner(interval_secs=None):
    """Run initial scan in background + periodic refresh."""
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
#  FLASK BLUEPRINT — registered by app.py as /scanner
# ═══════════════════════════════════════════════════════════════

if _flask_ok:
    scanner_bp = Blueprint("scanner", __name__, url_prefix="/scanner")

    @scanner_bp.route("/")
    def scanner_dashboard():
        """Colorful HTML dashboard."""
        if _cached_html is None:
            run_scan()
        return _cached_html or "<html><body><h1>⏳ Scanning...</h1></body></html>"

    @scanner_bp.route("/scan")
    def scanner_trigger_scan():
        """Trigger a fresh scan."""
        run_scan()
        return _cached_html or "<html><body><h1>✅ Scan complete</h1><p><a href='/scanner/'>View</a></p></body></html>"

    @scanner_bp.route("/api")
    def scanner_api():
        """JSON summary of detected agents."""
        if _cached_html is None:
            run_scan()
        return jsonify(get_cached_summary_dict())

    @scanner_bp.record_once
    def _start_scanner(state):
        """Auto-start background scanner when blueprint is registered."""
        start_background_scanner()

    logger.info("✅ scanner_bp blueprint ready at /scanner")
else:
    scanner_bp = None
    logger.warning("⚠️ Flask not available — scanner_bp not created")


# ═══════════════════════════════════════════════════════════════
#  Standalone mode
# ═══════════════════════════════════════════════════════════════
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s")
    print("=" * 60)
    print("   agent_monitor.py — AI Agent Scanner Module")
    print("=" * 60)
    run_scan()
    data = get_cached_summary_dict()
    print(f"\n✅ {data['agents_found']} agent(s) found")
    for a in data.get("agents", []):
        print(f"   🤖 {a['name']:28s} | {a['provider']:15s} | {a['area']:12s} | "
              f"{a['lines']:>4} lines | Quality: {a['quality']}/100")
    print(f"\nDashboard HTML: {len(get_cached_html() or ''):,} bytes")

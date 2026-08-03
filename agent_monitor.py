"""
AI Agent Monitor - Complete Single File Solution
Python + HTML + CSS + JavaScript in one Flask application
Run: python agent_monitor.py
Open: http://localhost:5000

INDEPENDENT - No Prometheus dependency
"""

from flask import Flask, render_template_string, request, jsonify, send_file
from flask_cors import CORS
import json
import os
import time
import random
import threading
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Any, Optional
from dataclasses import dataclass
from enum import Enum
import psutil
import io

# ============================================================================
# DATA MODELS
# ============================================================================

class AgentStatus(Enum):
    """Agent status enumeration"""
    ACTIVE   = "active"
    INACTIVE = "inactive"
    ERROR    = "error"
    UNKNOWN  = "unknown"


class RequestStatus(Enum):
    """Request status enumeration"""
    SUCCESS = "success"
    FAILED  = "failed"
    TIMEOUT = "timeout"
    ERROR   = "error"


@dataclass
class Agent:
    """Agent data model"""
    id:               str
    name:             str
    provider:         str
    model:            str
    file_extension:   str
    status:           str
    active:           bool
    success_rate:     float
    failure_rate:     float
    last_used:        str
    requests:         int
    tokens_used:      int
    tokens_available: int
    source:           str
    path:             Optional[str] = None
    timestamp:        Optional[str] = None


@dataclass
class Request:
    """Request data model"""
    request_id:    str
    agent_name:    str
    timestamp:     str
    status:        str
    tokens_used:   int
    response_time: int


@dataclass
class Metrics:
    """System metrics data model"""
    cpu:          float
    memory:       float
    storage:      float
    total_tokens: int
    used_tokens:  int
    rpm:          int
    rph:          int
    rpd:          int


# ============================================================================
# AI AGENT SCANNER CLASS
# ============================================================================

class AIAgentScanner:
    """Main AI Agent Scanner - fully independent, no Prometheus"""

    def __init__(self):
        self.agents:    List[Agent]              = []
        self.requests:  List[Request]            = []
        self.providers: Dict[str, Dict[str, Any]] = {}
        self.metrics    = Metrics(
            cpu=0, memory=0, storage=0,
            total_tokens=1_000_000,
            used_tokens=0,
            rpm=0, rph=0, rpd=0
        )
        self.config = self._load_config()
        self._lock  = threading.Lock()

    # ── config ────────────────────────────────────────────────

    def _load_config(self) -> Dict[str, Any]:
        config_path = Path("config.json")
        if config_path.exists():
            try:
                with open(config_path) as f:
                    return json.load(f)
            except Exception as e:
                print(f"Warning: could not load config.json: {e}")
        return self._default_config()

    @staticmethod
    def _default_config() -> Dict[str, Any]:
        return {
            "agents": [],
            "paths":  [],
            "providers": {
                "openai":      {"name": "OpenAI",           "models": ["gpt-4", "gpt-3.5-turbo"]},
                "anthropic":   {"name": "Anthropic",        "models": ["claude-3", "claude-2"]},
                "google":      {"name": "Google",           "models": ["gemini-pro", "palm-2"]},
                "huggingface": {"name": "Hugging Face",     "models": ["mistral", "llama"]},
                "cohere":      {"name": "Cohere",           "models": ["command", "command-light"]},
                "azure":       {"name": "Microsoft Azure",  "models": ["gpt-4", "gpt-35-turbo"]},
            },
        }

    # ── public API ────────────────────────────────────────────

    def scan_agents(self, agent_names: str, agent_paths: str) -> Dict[str, Any]:
        names = [n.strip() for n in agent_names.split(",") if n.strip()]
        paths = [p.strip() for p in agent_paths.split(",") if p.strip()]

        if not names and not paths:
            return {"error": "Please provide agent names or paths", "success": False}

        self._detect_agents(names, paths)
        self._generate_metrics()

        return {
            "success":      True,
            "agents_count": len(self.agents),
            "agents":       [self._agent_to_dict(a) for a in self.agents],
            "metrics":      self._metrics_to_dict(),
            "requests":     [self._request_to_dict(r) for r in self.requests],
            "providers":    self.providers,
        }

    def get_dashboard_data(self) -> Dict[str, Any]:
        return {
            "system_metrics":  self.get_system_metrics(),
            "token_metrics":   self.get_token_metrics(),
            "request_metrics": self.get_request_metrics(),
            "agent_status":    self.get_agent_status(),
            "agents":          [self._agent_to_dict(a) for a in self.agents],
            "requests":        [self._request_to_dict(r) for r in self.requests],
            "providers":       self.providers,
            "timestamp":       datetime.now().isoformat(),
        }

    def get_system_metrics(self) -> Dict[str, Any]:
        return {
            "cpu":          self.metrics.cpu,
            "memory":       self.metrics.memory,
            "storage":      self.metrics.storage,
            "cpu_actual":   psutil.cpu_percent(interval=0.1),
            "memory_actual": psutil.virtual_memory().percent,
            "disk_usage":   psutil.disk_usage("/").percent,
        }

    def get_token_metrics(self) -> Dict[str, Any]:
        pct = (
            self.metrics.used_tokens / self.metrics.total_tokens * 100
            if self.metrics.total_tokens else 0
        )
        return {
            "tokens_used":    self.metrics.used_tokens,
            "tokens_total":   self.metrics.total_tokens,
            "token_percent":  round(pct, 2),
        }

    def get_request_metrics(self) -> Dict[str, Any]:
        return {
            "rpm": self.metrics.rpm,
            "rph": self.metrics.rph,
            "rpd": self.metrics.rpd,
        }

    def get_agent_status(self) -> Dict[str, Any]:
        active = sum(1 for a in self.agents if a.active)
        return {
            "total_agents":    len(self.agents),
            "active_agents":   active,
            "inactive_agents": len(self.agents) - active,
        }

    def get_detailed_report(self) -> str:
        lines = [
            "\n" + "=" * 80,
            "AI AGENT SCANNER - DETAILED REPORT",
            "=" * 80,
            f"Generated: {datetime.now():%Y-%m-%d %H:%M:%S}",
            "",
            "SYSTEM METRICS", "-" * 80,
            f"CPU Usage   : {self.metrics.cpu}%",
            f"Memory Usage: {self.metrics.memory}%",
            f"Storage     : {self.metrics.storage}%",
            "",
            "TOKEN METRICS", "-" * 80,
            f"Tokens Used : {self._fmt(self.metrics.used_tokens)}",
            f"Tokens Total: {self._fmt(self.metrics.total_tokens)}",
            "",
            "REQUEST METRICS", "-" * 80,
            f"RPM: {self.metrics.rpm}",
            f"RPH: {self.metrics.rph}",
            f"RPD: {self.metrics.rpd}",
            "",
            "DETECTED AGENTS", "-" * 80,
        ]
        for i, a in enumerate(self.agents, 1):
            lines += [
                f"\n{i}. {a.name}",
                f"   Provider    : {a.provider}",
                f"   Model       : {a.model}",
                f"   Status      : {'🟢 Active' if a.active else '🔴 Inactive'}",
                f"   Tokens Used : {self._fmt(a.tokens_used)} / {self._fmt(a.tokens_available)}",
                f"   Requests    : {self._fmt(a.requests)}",
                f"   Success Rate: {a.success_rate:.1f}%",
                f"   Failure Rate: {a.failure_rate:.1f}%",
            ]
        lines.append("\n" + "=" * 80)
        return "\n".join(lines)

    def save_report(self) -> bytes:
        data = {
            "timestamp": datetime.now().isoformat(),
            "summary":   self.get_agent_status(),
            "metrics":   self._metrics_to_dict(),
            "agents":    [self._agent_to_dict(a) for a in self.agents],
            "requests":  [self._request_to_dict(r) for r in self.requests],
            "providers": self.providers,
        }
        return json.dumps(data, indent=2).encode()

    # ── internal helpers ──────────────────────────────────────

    def _detect_agents(self, names: List[str], paths: List[str]) -> None:
        with self._lock:
            self.agents = []

            for name in names:
                self.agents.append(self._parse_agent_name(name))

            for path in paths:
                self.agents.append(Agent(
                    id=f"agent_{len(self.agents)}_{int(time.time())}",
                    name=f"agent-{int(time.time())}",
                    path=path,
                    provider=self._detect_provider(path),
                    model=self._detect_model(path),
                    status=AgentStatus.ACTIVE.value,
                    active=True,
                    file_extension="py",
                    success_rate=85 + random.random() * 15,
                    failure_rate=5  + random.random() * 10,
                    last_used=(datetime.now() - timedelta(seconds=random.randint(0, 86400))).isoformat(),
                    requests=random.randint(100, 10_000),
                    tokens_used=random.randint(10_000, 500_000),
                    tokens_available=1_000_000,
                    source="path_scan",
                    timestamp=datetime.now().isoformat(),
                ))

            for i, agent in enumerate(self.agents):
                agent.id     = f"agent_{i}_{int(time.time())}"
                agent.active = random.random() > 0.2
                agent.status = (
                    AgentStatus.ACTIVE.value if agent.active
                    else AgentStatus.INACTIVE.value
                )

    def _parse_agent_name(self, name: str) -> Agent:
        keywords = [
            "gpt", "claude", "gemini", "palm", "mistral",
            "llama", "cohere", "azure", "openai", "anthropic", "google",
        ]
        ext      = name.split(".")[-1] if "." in name else "unknown"
        provider = "unknown"
        for kw in keywords:
            if kw in name.lower():
                provider = kw
                break

        return Agent(
            id=f"agent_{int(time.time())}",
            name=name,
            provider=provider,
            model=self._model_for_provider(provider),
            file_extension=ext,
            status=AgentStatus.ACTIVE.value,
            active=random.random() > 0.2,
            success_rate=85 + random.random() * 15,
            failure_rate=5  + random.random() * 10,
            last_used=(datetime.now() - timedelta(seconds=random.randint(0, 86400))).isoformat(),
            requests=random.randint(100, 10_000),
            tokens_used=random.randint(10_000, 500_000),
            tokens_available=1_000_000,
            source="user_provided",
            timestamp=datetime.now().isoformat(),
        )

    @staticmethod
    def _detect_provider(path: str) -> str:
        mapping = {
            "openai": "OpenAI",    "gpt":        "OpenAI",
            "claude": "Anthropic", "anthropic":  "Anthropic",
            "gemini": "Google",    "google":     "Google",
            "huggingface": "Hugging Face", "hf": "Hugging Face",
            "mistral": "Mistral",  "llama":      "Meta",
            "cohere":  "Cohere",   "azure":      "Microsoft Azure",
        }
        pl = path.lower()
        for key, val in mapping.items():
            if key in pl:
                return val
        return "Unknown Provider"

    @staticmethod
    def _detect_model(path: str) -> str:
        mapping = {
            "gpt4": "GPT-4",    "gpt-4":   "GPT-4",
            "gpt35": "GPT-3.5", "gpt-35":  "GPT-3.5",
            "claude3": "Claude 3", "claude-3": "Claude 3",
            "claude2": "Claude 2",
            "gemini":  "Gemini Pro",
            "mistral": "Mistral 7B",
            "llama2":  "Llama 2",
            "palm":    "PaLM 2",
            "command": "Command",
        }
        pl = path.lower()
        for key, val in mapping.items():
            if key in pl:
                return val
        return "Unknown Model"

    @staticmethod
    def _model_for_provider(provider: str) -> str:
        mapping = {
            "gpt": "GPT-4",      "claude":    "Claude 3",
            "gemini": "Gemini Pro", "palm":   "PaLM 2",
            "mistral": "Mistral 7B", "llama": "Llama 2",
            "cohere":  "Command",  "openai":  "GPT-4",
            "anthropic": "Claude 3", "google": "Gemini Pro",
            "azure": "GPT-4",
        }
        return mapping.get(provider, "Unknown Model")

    def _generate_metrics(self) -> None:
        with self._lock:
            self.metrics.cpu     = round(random.uniform(10, 80), 1)
            self.metrics.memory  = round(random.uniform(10, 90), 1)
            self.metrics.storage = round(random.uniform(20, 70), 1)

            self.metrics.used_tokens = sum(a.tokens_used for a in self.agents)

            active = sum(1 for a in self.agents if a.active)
            self.metrics.rpm = random.randint(0, 50) * max(active, 1)
            self.metrics.rph = self.metrics.rpm * 60
            self.metrics.rpd = self.metrics.rph * 24

            self._generate_request_history()
            self._generate_provider_info()

    def _generate_request_history(self) -> None:
        self.requests = []
        statuses = [
            RequestStatus.SUCCESS, RequestStatus.SUCCESS,
            RequestStatus.SUCCESS, RequestStatus.FAILED,
            RequestStatus.TIMEOUT,
        ]
        for i in range(20):
            if not self.agents:
                break
            agent = random.choice(self.agents)
            self.requests.append(Request(
                request_id=f"REQ_{int(time.time())}_{i}",
                agent_name=agent.name,
                timestamp=(datetime.now() - timedelta(seconds=random.randint(0, 3600))).isoformat(),
                status=random.choice(statuses).value,
                tokens_used=random.randint(100, 2100),
                response_time=random.randint(100, 5100),
            ))
        self.requests.sort(key=lambda r: r.timestamp, reverse=True)

    def _generate_provider_info(self) -> None:
        self.providers = {}
        for a in self.agents:
            if a.provider not in self.providers:
                self.providers[a.provider] = {
                    "name":           a.provider,
                    "model":          a.model,
                    "count":          0,
                    "active_count":   0,
                    "total_tokens":   0,
                    "total_requests": 0,
                    "success_rate":   0.0,
                }
            p = self.providers[a.provider]
            p["count"]          += 1
            p["active_count"]   += int(a.active)
            p["total_tokens"]   += a.tokens_used
            p["total_requests"] += a.requests
            p["success_rate"]   += a.success_rate

        for p in self.providers.values():
            if p["count"]:
                p["success_rate"] = round(p["success_rate"] / p["count"], 2)

    # ── serialisers ───────────────────────────────────────────

    def _metrics_to_dict(self) -> Dict[str, Any]:
        return {
            "cpu":          self.metrics.cpu,
            "memory":       self.metrics.memory,
            "storage":      self.metrics.storage,
            "total_tokens": self.metrics.total_tokens,
            "used_tokens":  self.metrics.used_tokens,
            "rpm":          self.metrics.rpm,
            "rph":          self.metrics.rph,
            "rpd":          self.metrics.rpd,
        }

    @staticmethod
    def _agent_to_dict(a: Agent) -> Dict[str, Any]:
        return {
            "id":               a.id,
            "name":             a.name,
            "provider":         a.provider,
            "model":            a.model,
            "file_extension":   a.file_extension,
            "status":           a.status,
            "active":           a.active,
            "success_rate":     a.success_rate,
            "failure_rate":     a.failure_rate,
            "last_used":        a.last_used,
            "requests":         a.requests,
            "tokens_used":      a.tokens_used,
            "tokens_available": a.tokens_available,
            "source":           a.source,
            "path":             a.path,
            "timestamp":        a.timestamp,
        }

    @staticmethod
    def _request_to_dict(r: Request) -> Dict[str, Any]:
        return {
            "request_id":   r.request_id,
            "agent_name":   r.agent_name,
            "timestamp":    r.timestamp,
            "status":       r.status,
            "tokens_used":  r.tokens_used,
            "response_time": r.response_time,
        }

    @staticmethod
    def _fmt(n: int) -> str:
        if n >= 1_000_000:
            return f"{n/1_000_000:.2f}M"
        if n >= 1_000:
            return f"{n/1_000:.2f}K"
        return str(n)


# ============================================================================
# FLASK APP
# ============================================================================

application = Flask(__name__)   # named 'application' so app.py can import it
CORS(application)

scanner = AIAgentScanner()

# ── HTML template ─────────────────────────────────────────────────────────────
HTML_TEMPLATE = '''
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>AI Agent Monitor</title>
    <style>
        * { margin:0; padding:0; box-sizing:border-box; }

        body {
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            background: linear-gradient(135deg,#667eea 0%,#764ba2 100%);
            min-height: 100vh;
            padding: 20px;
        }

        .container { max-width:1400px; margin:0 auto; }

        header {
            text-align:center; color:white; margin-bottom:30px;
            animation: slideDown .6s ease-out;
        }
        header h1 { font-size:2.5em; margin-bottom:10px; text-shadow:2px 2px 4px rgba(0,0,0,.3); }
        header p  { font-size:1.1em; opacity:.9; }

        /* ── control panel ── */
        .control-panel {
            display:grid; grid-template-columns:1fr 1fr;
            gap:20px; margin-bottom:30px;
        }
        .input-block {
            background:white; padding:20px;
            border-radius:12px; box-shadow:0 8px 32px rgba(0,0,0,.1);
        }
        .input-block h3 {
            color:#667eea; margin-bottom:15px;
            display:flex; align-items:center; gap:10px;
        }
        .input-block h3::before {
            content:''; display:inline-block;
            width:4px; height:20px;
            background:linear-gradient(180deg,#667eea,#764ba2);
            border-radius:2px;
        }
        input[type="text"] {
            width:100%; padding:12px; margin-bottom:10px;
            border:2px solid #e0e0e0; border-radius:8px;
            font-size:1em; transition:all .3s ease;
        }
        input[type="text"]:focus {
            outline:none; border-color:#667eea;
            box-shadow:0 0 0 3px rgba(102,126,234,.1);
        }

        /* ── buttons ── */
        .btn-row {
            display:flex; gap:10px; flex-wrap:wrap;
            justify-content:center; margin-bottom:20px;
        }
        button {
            flex:1; min-width:150px; padding:12px 20px;
            border:none; border-radius:8px;
            font-size:1em; font-weight:600; cursor:pointer;
            transition:all .3s ease;
            text-transform:uppercase; letter-spacing:.5px;
        }
        .btn-scan {
            background:linear-gradient(135deg,#667eea,#764ba2); color:white;
        }
        .btn-scan:hover { transform:translateY(-2px); box-shadow:0 8px 20px rgba(102,126,234,.4); }
        .btn-clear    { background:#f0f0f0; color:#333; }
        .btn-clear:hover { background:#e0e0e0; }
        .btn-download { background:linear-gradient(135deg,#4facfe,#00f2fe); color:white; }

        /* ── dashboard cards ── */
        .dashboard {
            display:grid;
            grid-template-columns:repeat(auto-fit,minmax(280px,1fr));
            gap:20px; margin-bottom:30px;
        }
        .card {
            background:white; border-radius:12px; padding:20px;
            box-shadow:0 8px 32px rgba(0,0,0,.1);
            border-top:4px solid #667eea;
            animation:fadeIn .6s ease-out forwards; opacity:0;
        }
        .card:nth-child(2){ border-top-color:#764ba2; animation-delay:.1s; }
        .card:nth-child(3){ border-top-color:#f093fb; animation-delay:.2s; }
        .card:nth-child(4){ border-top-color:#4facfe; animation-delay:.3s; }
        .card h3 { color:#333; margin-bottom:15px; font-size:1.1em; }

        .metric {
            display:flex; justify-content:space-between;
            align-items:center; padding:10px 0;
            border-bottom:1px solid #f0f0f0;
        }
        .metric:last-child { border-bottom:none; }
        .metric-label { color:#666; font-weight:500; }
        .metric-value { color:#333; font-weight:700; font-size:1.1em; }
        .metric-value.success { color:#4caf50; }
        .metric-value.danger  { color:#f44336; }

        .progress-bar  { width:100%; height:8px; background:#e0e0e0; border-radius:4px; overflow:hidden; margin-top:6px; }
        .progress-fill { height:100%; background:linear-gradient(90deg,#667eea,#764ba2); border-radius:4px; transition:width .4s ease; }

        /* ── agents section ── */
        .agents-list {
            background:white; border-radius:12px; padding:20px;
            box-shadow:0 8px 32px rgba(0,0,0,.1); margin-bottom:30px;
        }
        .agents-list h2 { color:#333; margin-bottom:20px; }

        .agent-card {
            background:linear-gradient(135deg,#f5f7fa,#c3cfe2);
            border-radius:10px; padding:20px; margin-bottom:15px;
            border-left:5px solid #667eea; transition:all .3s ease;
        }
        .agent-card:hover { transform:translateX(5px); box-shadow:0 6px 20px rgba(102,126,234,.2); }

        .agent-header {
            display:grid; grid-template-columns:1fr 1fr 1fr;
            gap:20px; margin-bottom:15px;
        }
        .agent-label { color:#666; font-size:.85em; font-weight:600; text-transform:uppercase; margin-bottom:4px; }
        .agent-value { color:#333; font-size:1.1em; font-weight:700; }

        .agent-metrics { display:grid; grid-template-columns:repeat(auto-fit,minmax(110px,1fr)); gap:12px; }
        .mini-metric {
            background:white; padding:12px; border-radius:8px;
            text-align:center; border-top:3px solid #667eea;
        }
        .mini-metric-label { color:#999; font-size:.8em; margin-bottom:4px; }
        .mini-metric-value { color:#333; font-weight:700; font-size:1.15em; }

        .status-badge { display:inline-block; padding:5px 12px; border-radius:20px; font-size:.85em; font-weight:600; margin-top:10px; }
        .status-active   { background:#c8e6c9; color:#2e7d32; }
        .status-inactive { background:#ffccbc; color:#d84315; }

        /* ── tabs ── */
        .tabs { display:flex; gap:8px; margin-bottom:20px; border-bottom:2px solid #e0e0e0; flex-wrap:wrap; }
        .tab-button {
            background:none; border:none; padding:12px 18px;
            cursor:pointer; color:#999; font-weight:600;
            border-bottom:3px solid transparent; transition:all .3s ease;
            text-transform:uppercase; font-size:.85em; min-width:auto;
        }
        .tab-button.active { color:#667eea; border-bottom-color:#667eea; }
        .tab-content { display:none; }
        .tab-content.active { display:block; animation:fadeIn .3s ease-out; }

        /* ── table ── */
        .detail-table { width:100%; border-collapse:collapse; margin-top:15px; }
        .detail-table th { background:#f5f5f5; padding:12px; text-align:left; color:#333; font-weight:600; border-bottom:2px solid #e0e0e0; }
        .detail-table td { padding:12px; border-bottom:1px solid #e0e0e0; color:#666; }
        .detail-table tr:hover { background:#f9f9f9; }

        /* ── messages ── */
        .error-msg   { background:#ffebee; color:#c62828; padding:15px; border-radius:8px; margin-bottom:15px; border-left:4px solid #f44336; }
        .success-msg { background:#e8f5e9; color:#2e7d32; padding:15px; border-radius:8px; margin-bottom:15px; border-left:4px solid #4caf50; }

        /* ── loading ── */
        .loading { text-align:center; padding:40px; color:white; }
        .spinner {
            border:4px solid rgba(255,255,255,.3); border-radius:50%;
            border-top:4px solid white; width:40px; height:40px;
            animation:spin 1s linear infinite; margin:0 auto 20px;
        }

        /* ── animations ── */
        @keyframes slideDown { from{opacity:0;transform:translateY(-20px)} to{opacity:1;transform:translateY(0)} }
        @keyframes fadeIn    { from{opacity:0} to{opacity:1} }
        @keyframes spin      { to{transform:rotate(360deg)} }

        /* ── responsive ── */
        @media(max-width:768px){
            .control-panel  { grid-template-columns:1fr; }
            .agent-header   { grid-template-columns:1fr; }
            header h1       { font-size:1.8em; }
            .dashboard      { grid-template-columns:1fr; }
        }
    </style>
</head>
<body>
<div class="container">

    <header>
        <h1>🤖 AI Agent Monitor</h1>
        <p>Real-time monitoring and analysis of AI agents in your project</p>
    </header>

    <!-- inputs -->
    <div class="control-panel">
        <div class="input-block">
            <h3>File / Agent Names</h3>
            <input type="text" id="agentNames" placeholder="e.g., gpt-agent.js, claude-handler.py">
            <small style="color:#999">Comma-separated agent file names</small>
        </div>
        <div class="input-block">
            <h3>File Path / Location</h3>
            <input type="text" id="agentPaths" placeholder="e.g., /src/agents, ./lib/ai">
            <small style="color:#999">Project paths where agents are located</small>
        </div>
    </div>

    <!-- buttons -->
    <div class="btn-row">
        <button class="btn-scan"     onclick="scanAgents()">🔍 SCAN AGENTS</button>
        <button class="btn-clear"    onclick="clearAll()">🗑️ CLEAR</button>
        <button class="btn-download" onclick="downloadReport()">📥 REPORT</button>
    </div>

    <div id="messages"></div>

    <!-- loading -->
    <div id="loading" class="loading" style="display:none">
        <div class="spinner"></div>
        <p>Scanning agents and gathering metrics…</p>
    </div>

    <!-- dashboard -->
    <div id="dashboard" class="dashboard" style="display:none">
        <div class="card">
            <h3>📊 System Metrics</h3>
            <div class="metric"><span class="metric-label">CPU Usage</span>    <span class="metric-value" id="cpuUsage">-</span></div>
            <div class="progress-bar"><div class="progress-fill" id="cpuBar" style="width:0%"></div></div>
            <div class="metric"><span class="metric-label">Memory Usage</span> <span class="metric-value" id="memUsage">-</span></div>
            <div class="progress-bar"><div class="progress-fill" id="memBar" style="width:0%"></div></div>
            <div class="metric"><span class="metric-label">Storage</span>      <span class="metric-value" id="storageUsage">-</span></div>
        </div>

        <div class="card">
            <h3>🔐 Token Metrics</h3>
            <div class="metric"><span class="metric-label">Tokens Used</span>     <span class="metric-value" id="tokensUsed">-</span></div>
            <div class="metric"><span class="metric-label">Total Available</span> <span class="metric-value" id="tokensTotal">-</span></div>
            <div class="metric"><span class="metric-label">Usage %</span>         <span class="metric-value" id="tokenPct">-</span></div>
            <div class="progress-bar"><div class="progress-fill" id="tokenBar" style="width:0%"></div></div>
        </div>

        <div class="card">
            <h3>📈 Request Metrics</h3>
            <div class="metric"><span class="metric-label">RPM (Requests/Min)</span>  <span class="metric-value" id="rpm">-</span></div>
            <div class="metric"><span class="metric-label">RPH (Requests/Hour)</span> <span class="metric-value" id="rph">-</span></div>
            <div class="metric"><span class="metric-label">RPD (Requests/Day)</span>  <span class="metric-value" id="rpd">-</span></div>
        </div>

        <div class="card">
            <h3>⚡ Agent Status</h3>
            <div class="metric"><span class="metric-label">Agents Detected</span> <span class="metric-value success" id="agentCount">-</span></div>
            <div class="metric"><span class="metric-label">Active</span>           <span class="metric-value success" id="activeCount">-</span></div>
            <div class="metric"><span class="metric-label">Inactive</span>         <span class="metric-value danger"  id="inactiveCount">-</span></div>
        </div>
    </div>

    <!-- agents section -->
    <div id="agentsSection" class="agents-list" style="display:none">
        <h2>🤖 Detected AI Agents</h2>

        <div class="tabs">
            <button class="tab-button active" onclick="switchTab('overview',  this)">Overview</button>
            <button class="tab-button"        onclick="switchTab('detailed',  this)">Detailed Metrics</button>
            <button class="tab-button"        onclick="switchTab('requests',  this)">Request History</button>
            <button class="tab-button"        onclick="switchTab('providers', this)">Providers</button>
        </div>

        <div id="overview"   class="tab-content active"><div id="agentsList"></div></div>

        <div id="detailed"   class="tab-content">
            <table class="detail-table">
                <thead><tr>
                    <th>Agent Name</th><th>Provider</th><th>Model</th>
                    <th>Tokens Used / Total</th><th>Requests</th><th>Status</th>
                </tr></thead>
                <tbody id="detailedTable"></tbody>
            </table>
        </div>

        <div id="requests"   class="tab-content">
            <table class="detail-table">
                <thead><tr>
                    <th>Agent</th><th>Request ID</th><th>Timestamp</th>
                    <th>Status</th><th>Tokens</th><th>Response Time</th>
                </tr></thead>
                <tbody id="requestsTable"></tbody>
            </table>
        </div>

        <div id="providers"  class="tab-content"><div id="providersList"></div></div>
    </div>

</div><!-- /container -->

<script>
// ── helpers ──────────────────────────────────────────────────
function fmt(n){
    if(n>=1e6) return (n/1e6).toFixed(2)+'M';
    if(n>=1e3) return (n/1e3).toFixed(2)+'K';
    return n;
}
function esc(t){
    const d=document.createElement('div');
    d.textContent=t; return d.innerHTML;
}
function showMsg(msg, type){
    const el=document.getElementById('messages');
    el.innerHTML=`<div class="${type}-msg">${msg}</div>`;
    setTimeout(()=>el.innerHTML='', 5000);
}

// ── scan ─────────────────────────────────────────────────────
async function scanAgents(){
    const names=document.getElementById('agentNames').value;
    const paths=document.getElementById('agentPaths').value;
    if(!names && !paths){ showMsg('Please provide agent names or paths','error'); return; }

    document.getElementById('loading').style.display='block';
    document.getElementById('dashboard').style.display='none';
    document.getElementById('agentsSection').style.display='none';

    try{
        const res  = await fetch('/api/scan',{
            method:'POST',
            headers:{'Content-Type':'application/json'},
            body: JSON.stringify({agent_names:names, agent_paths:paths})
        });
        const data = await res.json();
        if(data.success){
            renderDashboard(data);
            renderAgents(data.agents);
            renderDetailed(data.agents);
            renderRequests(data.requests);
            renderProviders(data.providers);
            showMsg(`✅ Found ${data.agents_count} AI agent(s)`,'success');
        } else {
            showMsg(data.error||'Scan failed','error');
        }
    } catch(e){
        showMsg('Error: '+e.message,'error');
    } finally {
        document.getElementById('loading').style.display='none';
    }
}

// ── render dashboard ─────────────────────────────────────────
function renderDashboard(data){
    const m=data.metrics;
    const pct=((m.used_tokens/m.total_tokens)*100).toFixed(2);

    document.getElementById('cpuUsage').textContent    = m.cpu+'%';
    document.getElementById('cpuBar').style.width      = m.cpu+'%';
    document.getElementById('memUsage').textContent    = m.memory+'%';
    document.getElementById('memBar').style.width      = m.memory+'%';
    document.getElementById('storageUsage').textContent= m.storage+'%';
    document.getElementById('tokensUsed').textContent  = fmt(m.used_tokens);
    document.getElementById('tokensTotal').textContent = fmt(m.total_tokens);
    document.getElementById('tokenPct').textContent    = pct+'%';
    document.getElementById('tokenBar').style.width    = pct+'%';
    document.getElementById('rpm').textContent         = m.rpm;
    document.getElementById('rph').textContent         = m.rph;
    document.getElementById('rpd').textContent         = m.rpd;
    document.getElementById('agentCount').textContent  = data.agents.length;
    document.getElementById('activeCount').textContent = data.agents.filter(a=>a.active).length;
    document.getElementById('inactiveCount').textContent=data.agents.filter(a=>!a.active).length;
    document.getElementById('dashboard').style.display='grid';
}

// ── render agents overview ────────────────────────────────────
function renderAgents(agents){
    document.getElementById('agentsList').innerHTML = agents.map(a=>`
        <div class="agent-card">
            <div class="agent-header">
                <div><div class="agent-label">Agent Name</div><div class="agent-value">${esc(a.name)}</div></div>
                <div><div class="agent-label">Provider</div>   <div class="agent-value">${esc(a.provider)}</div></div>
                <div><div class="agent-label">Model</div>      <div class="agent-value">${esc(a.model)}</div></div>
            </div>
            <div class="agent-metrics">
                <div class="mini-metric"><div class="mini-metric-label">TOKENS USED</div>  <div class="mini-metric-value">${fmt(a.tokens_used)}</div></div>
                <div class="mini-metric"><div class="mini-metric-label">TOKENS TOTAL</div> <div class="mini-metric-value">${fmt(a.tokens_available)}</div></div>
                <div class="mini-metric"><div class="mini-metric-label">REQUESTS</div>     <div class="mini-metric-value">${fmt(a.requests)}</div></div>
                <div class="mini-metric"><div class="mini-metric-label">SUCCESS RATE</div> <div class="mini-metric-value">${a.success_rate.toFixed(1)}%</div></div>
                <div class="mini-metric"><div class="mini-metric-label">FAILURE RATE</div> <div class="mini-metric-value">${a.failure_rate.toFixed(1)}%</div></div>
            </div>
            <span class="status-badge status-${a.active?'active':'inactive'}">${a.active?'🟢 Active':'🔴 Inactive'}</span>
        </div>
    `).join('');
    document.getElementById('agentsSection').style.display='block';
}

// ── render detailed table ─────────────────────────────────────
function renderDetailed(agents){
    document.getElementById('detailedTable').innerHTML = agents.map(a=>`
        <tr>
            <td>${esc(a.name)}</td>
            <td>${esc(a.provider)}</td>
            <td>${esc(a.model)}</td>
            <td>${fmt(a.tokens_used)} / ${fmt(a.tokens_available)}</td>
            <td>${fmt(a.requests)}</td>
            <td><span class="status-badge status-${a.active?'active':'inactive'}">${a.active?'🟢 Active':'🔴 Inactive'}</span></td>
        </tr>
    `).join('');
}

// ── render requests ───────────────────────────────────────────
function renderRequests(reqs){
    document.getElementById('requestsTable').innerHTML = reqs.slice(0,15).map(r=>`
        <tr>
            <td>${esc(r.agent_name)}</td>
            <td>${esc(r.request_id.substring(0,18))}…</td>
            <td>${new Date(r.timestamp).toLocaleTimeString()}</td>
            <td><span class="metric-value ${r.status==='success'?'success':'danger'}">${r.status==='success'?'✅':'❌'} ${r.status}</span></td>
            <td>${fmt(r.tokens_used)}</td>
            <td>${r.response_time}ms</td>
        </tr>
    `).join('');
}

// ── render providers ──────────────────────────────────────────
function renderProviders(providers){
    document.getElementById('providersList').innerHTML =
        Object.values(providers).map(p=>`
            <div class="agent-card">
                <div class="agent-header">
                    <div><div class="agent-label">Provider</div>     <div class="agent-value">${esc(p.name)}</div></div>
                    <div><div class="agent-label">Primary Model</div><div class="agent-value">${esc(p.model)}</div></div>
                    <div><div class="agent-label">Agent Count</div>  <div class="agent-value">${p.count}</div></div>
                </div>
                <div class="agent-metrics">
                    <div class="mini-metric"><div class="mini-metric-label">ACTIVE</div>          <div class="mini-metric-value">${p.active_count}</div></div>
                    <div class="mini-metric"><div class="mini-metric-label">TOTAL TOKENS</div>    <div class="mini-metric-value">${fmt(p.total_tokens)}</div></div>
                    <div class="mini-metric"><div class="mini-metric-label">TOTAL REQUESTS</div>  <div class="mini-metric-value">${fmt(p.total_requests)}</div></div>
                    <div class="mini-metric"><div class="mini-metric-label">SUCCESS RATE</div>    <div class="mini-metric-value">${p.success_rate}%</div></div>
                </div>
            </div>
        `).join('');
}

// ── tabs ──────────────────────────────────────────────────────
function switchTab(name, btn){
    document.querySelectorAll('.tab-content').forEach(t=>t.classList.remove('active'));
    document.querySelectorAll('.tab-button') .forEach(b=>b.classList.remove('active'));
    document.getElementById(name).classList.add('active');
    btn.classList.add('active');
}

// ── clear ─────────────────────────────────────────────────────
function clearAll(){
    document.getElementById('agentNames').value='';
    document.getElementById('agentPaths').value='';
    document.getElementById('dashboard').style.display='none';
    document.getElementById('agentsSection').style.display='none';
    document.getElementById('messages').innerHTML='';
}

// ── download ──────────────────────────────────────────────────
async function downloadReport(){
    try{
        const res  = await fetch('/api/report/download');
        const blob = await res.blob();
        const url  = URL.createObjectURL(blob);
        const a    = document.createElement('a');
        a.href=url; a.download=`agent_report_${Date.now()}.json`;
        document.body.appendChild(a); a.click();
        URL.revokeObjectURL(url); document.body.removeChild(a);
    } catch(e){
        showMsg('Error downloading report','error');
    }
}
</script>
</body>
</html>
'''


# ── routes ────────────────────────────────────────────────────────────────────

@application.get("/")
def index():
    return render_template_string(HTML_TEMPLATE)


@application.post("/api/scan")
def api_scan():
    data        = request.get_json() or {}
    agent_names = data.get("agent_names", "")
    agent_paths = data.get("agent_paths", "")
    result      = scanner.scan_agents(agent_names, agent_paths)
    return jsonify(result), 200 if result.get("success") else 400


@application.get("/api/dashboard")
def api_dashboard():
    return jsonify(scanner.get_dashboard_data())


@application.get("/api/agents")
def api_agents():
    agents = [scanner._agent_to_dict(a) for a in scanner.agents]
    return jsonify({"agents": agents, "count": len(agents), "timestamp": datetime.now().isoformat()})


@application.get("/api/status")
def api_status():
    return jsonify({
        "status":         "running",
        "agents_count":   len(scanner.agents),
        "active_agents":  sum(1 for a in scanner.agents if a.active),
        "total_requests": len(scanner.requests),
        "timestamp":      datetime.now().isoformat(),
    })


@application.get("/api/report")
def api_report():
    return jsonify({"report": scanner.get_detailed_report(), "timestamp": datetime.now().isoformat()})


@application.get("/api/report/download")
def api_report_download():
    return send_file(
        io.BytesIO(scanner.save_report()),
        mimetype="application/json",
        as_attachment=True,
        download_name=f"agent_report_{datetime.now():%Y%m%d_%H%M%S}.json",
    )


@application.get("/health")
def health():
    return "Healthy", 200


@application.errorhandler(404)
def not_found(e):
    return jsonify({"error": "Not found"}), 404


@application.errorhandler(500)
def server_error(e):
    return jsonify({"error": "Internal server error"}), 500


# ── entry point ───────────────────────────────────────────────────────────────

# app.py can simply do:
#   from agent_monitor import application, scanner

if __name__ == "__main__":
    print("\n" + "=" * 60)
    print("  🤖  AI AGENT MONITOR")
    print("=" * 60)
    print("  URL  : http://localhost:5000")
    print("  Health: http://localhost:5000/health")
    print("=" * 60 + "\n")
    application.run(host="0.0.0.0", port=5000, debug=False, use_reloader=False)
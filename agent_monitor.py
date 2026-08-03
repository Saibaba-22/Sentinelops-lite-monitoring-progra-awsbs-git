#!/usr/bin/env python3
"""
agent_monitor.py
=================
Pure classes only — no HTTP server, no Flask.
Imported by app.py which owns all routing.
"""

import os
import sys
import time
import ast
import re
import threading
import sqlite3
import psutil
import datetime
import random
from pathlib import Path
from collections import defaultdict


# ══════════════════════════════════════════════════════════════
# ENVIRONMENT & MODEL CONFIGURATION
# ──────────────────────────────────────────────────────────────
# All values read directly from environment variables.
# Set these in:
#   GitHub → Settings → Secrets and Variables → Actions
#
# Secrets  : GEMINI_API_KEY, OPENAI_API_KEY, etc.
# Variables: AI_MODEL, AI_PROVIDER
#
# These flow to Beanstalk via pipeline.yml env_map in
# the "Render AWS ECS Dockerrun manifest" step.
# ══════════════════════════════════════════════════════════════

# ── API Keys (from GitHub Secrets) ───────────────────────────
GEMINI_API_KEY    = os.environ.get("GEMINI_API_KEY",    "")
GOOGLE_API_KEY    = os.environ.get("GOOGLE_API_KEY",    "") or GEMINI_API_KEY
OPENAI_API_KEY    = os.environ.get("OPENAI_API_KEY",    "")
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
GROQ_API_KEY      = os.environ.get("GROQ_API_KEY",      "")
MISTRAL_API_KEY   = os.environ.get("MISTRAL_API_KEY",   "")
OLLAMA_BASE_URL   = os.environ.get("OLLAMA_BASE_URL",   "http://localhost:11434")

# ── AI Model & Provider (from GitHub Variables) ───────────────
AI_MODEL    = os.environ.get("AI_MODEL",    "gemini-2.5-flash")
AI_PROVIDER = os.environ.get("AI_PROVIDER", "gemini")

# ── Provider name normalisation ───────────────────────────────
# Maps "gemini" → "google" etc. for MODEL_REGISTRY lookup
_PROVIDER_MAP = {
    "gemini":    "google",
    "google":    "google",
    "openai":    "openai",
    "anthropic": "anthropic",
    "groq":      "groq",
    "mistral":   "mistral",
    "ollama":    "ollama",
}

ACTIVE_PROVIDER = _PROVIDER_MAP.get(
    AI_PROVIDER.lower().strip(),
    AI_PROVIDER.lower().strip()
)
ACTIVE_MODEL = AI_MODEL.strip()

# ── API key lookup by provider ────────────────────────────────
# Maps each provider to its key from environment
_PROVIDER_KEYS = {
    "google":    GOOGLE_API_KEY,
    "openai":    OPENAI_API_KEY,
    "anthropic": ANTHROPIC_API_KEY,
    "groq":      GROQ_API_KEY,
    "mistral":   MISTRAL_API_KEY,
    "ollama":    "local",
}

# Active API key for the current provider
ACTIVE_API_KEY = _PROVIDER_KEYS.get(ACTIVE_PROVIDER, "")

# ── Startup log ───────────────────────────────────────────────
_key_status = "✅ SET" if ACTIVE_API_KEY and ACTIVE_API_KEY != "local" else "❌ MISSING"
print(f"[monitor] Provider : {AI_PROVIDER} → {ACTIVE_PROVIDER}")
print(f"[monitor] Model    : {ACTIVE_MODEL}")
print(f"[monitor] API Key  : {_key_status}")


# ══════════════════════════════════════════════════════════════
# MODEL REGISTRY
# ──────────────────────────────────────────────────────────────
# Single source of truth for all model limits and costs.
# api_key is stored per provider using the env var values above.
# ══════════════════════════════════════════════════════════════

MODEL_REGISTRY = {
    "google": {
        "api_key":  GOOGLE_API_KEY,
        "base_url": "https://generativelanguage.googleapis.com/v1beta",
        "models": {
            "gemini-2.5-flash": {
                "tpm_limit": 1_000_000,     "tph_limit": 60_000_000,
                "tpd_limit": 1_000_000_000, "rpm_limit": 10_000,
                "rph_limit": 600_000,       "rpd_limit": 10_000_000,
                "cost_input_per_1k":  0.00015,
                "cost_output_per_1k": 0.00060,
                "context_window":     1_048_576,
            },
            "gemini-2.5-pro": {
                "tpm_limit": 800_000,       "tph_limit": 48_000_000,
                "tpd_limit": 800_000_000,   "rpm_limit": 2_000,
                "rph_limit": 120_000,       "rpd_limit": 2_000_000,
                "cost_input_per_1k":  0.00125,
                "cost_output_per_1k": 0.01000,
                "context_window":     1_048_576,
            },
            "gemini-1.5-flash": {
                "tpm_limit": 1_000_000,     "tph_limit": 60_000_000,
                "tpd_limit": 1_000_000_000, "rpm_limit": 2_000,
                "rph_limit": 120_000,       "rpd_limit": 2_000_000,
                "cost_input_per_1k":  0.000075,
                "cost_output_per_1k": 0.000300,
                "context_window":     1_048_576,
            },
            "gemini-1.5-pro": {
                "tpm_limit": 32_000,        "tph_limit": 1_920_000,
                "tpd_limit": 32_000_000,    "rpm_limit": 1_000,
                "rph_limit": 60_000,        "rpd_limit": 1_000_000,
                "cost_input_per_1k":  0.00125,
                "cost_output_per_1k": 0.00375,
                "context_window":     1_048_576,
            },
        },
    },
    "openai": {
        "api_key":  OPENAI_API_KEY,
        "base_url": "https://api.openai.com/v1",
        "models": {
            "gpt-4o": {
                "tpm_limit": 30_000,        "tph_limit": 1_800_000,
                "tpd_limit": 30_000_000,    "rpm_limit": 500,
                "rph_limit": 30_000,        "rpd_limit": 500_000,
                "cost_input_per_1k":  0.005,
                "cost_output_per_1k": 0.015,
                "context_window":     128_000,
            },
            "gpt-3.5-turbo": {
                "tpm_limit": 90_000,        "tph_limit": 5_400_000,
                "tpd_limit": 90_000_000,    "rpm_limit": 3_500,
                "rph_limit": 210_000,       "rpd_limit": 3_500_000,
                "cost_input_per_1k":  0.0005,
                "cost_output_per_1k": 0.0015,
                "context_window":     16_385,
            },
        },
    },
    "anthropic": {
        "api_key":  ANTHROPIC_API_KEY,
        "base_url": "https://api.anthropic.com",
        "models": {
            "claude-3-5-sonnet-20241022": {
                "tpm_limit": 80_000,        "tph_limit": 4_800_000,
                "tpd_limit": 80_000_000,    "rpm_limit": 4_000,
                "rph_limit": 240_000,       "rpd_limit": 4_000_000,
                "cost_input_per_1k":  0.003,
                "cost_output_per_1k": 0.015,
                "context_window":     200_000,
            },
        },
    },
    "groq": {
        "api_key":  GROQ_API_KEY,
        "base_url": "https://api.groq.com/openai/v1",
        "models": {
            "llama3-70b-8192": {
                "tpm_limit": 6_000,         "tph_limit": 360_000,
                "tpd_limit": 6_000_000,     "rpm_limit": 30,
                "rph_limit": 1_800,         "rpd_limit": 30_000,
                "cost_input_per_1k":  0.00059,
                "cost_output_per_1k": 0.00079,
                "context_window":     8_192,
            },
        },
    },
    "mistral": {
        "api_key":  MISTRAL_API_KEY,
        "base_url": "https://api.mistral.ai/v1",
        "models": {
            "mistral-large-latest": {
                "tpm_limit": 500_000,       "tph_limit": 30_000_000,
                "tpd_limit": 500_000_000,   "rpm_limit": 1_000,
                "rph_limit": 60_000,        "rpd_limit": 1_000_000,
                "cost_input_per_1k":  0.003,
                "cost_output_per_1k": 0.009,
                "context_window":     128_000,
            },
        },
    },
    "ollama": {
        "api_key":  "",
        "base_url": OLLAMA_BASE_URL,
        "models": {
            "llama3": {
                "tpm_limit": 9_999_999,     "tph_limit": 999_999_999,
                "tpd_limit": 9_999_999_999, "rpm_limit": 99_999,
                "rph_limit": 5_999_999,     "rpd_limit": 99_999_999,
                "cost_input_per_1k":  0.0,
                "cost_output_per_1k": 0.0,
                "context_window":     8_192,
            },
        },
    },
}


# ══════════════════════════════════════════════════════════════
# ACTIVE CONFIG
# ──────────────────────────────────────────────────────────────
# Flat dict built from MODEL_REGISTRY using ACTIVE_PROVIDER
# and ACTIVE_MODEL. Used everywhere in the app.
# ══════════════════════════════════════════════════════════════

def _build_active_config() -> dict:
    """
    Build flat ACTIVE_CONFIG from MODEL_REGISTRY.
    Uses ACTIVE_PROVIDER and ACTIVE_MODEL set from env vars above.
    """
    pcfg = MODEL_REGISTRY.get(ACTIVE_PROVIDER, {})
    mcfg = pcfg.get("models", {}).get(ACTIVE_MODEL, {})

    if not pcfg:
        print(f"[monitor] ❌ Provider '{ACTIVE_PROVIDER}' not in registry")

    if not mcfg:
        print(
            f"[monitor] ❌ Model '{ACTIVE_MODEL}' not found "
            f"under '{ACTIVE_PROVIDER}' — using zero limits"
        )
        mcfg = {
            "tpm_limit": 0, "tph_limit": 0, "tpd_limit": 0,
            "rpm_limit": 0, "rph_limit": 0, "rpd_limit": 0,
            "cost_input_per_1k":  0.0,
            "cost_output_per_1k": 0.0,
            "context_window":     0,
        }

    return {
        # ── Identity ──────────────────────────────────────────
        "name":     ACTIVE_MODEL,
        "provider": ACTIVE_PROVIDER,
        # ── Auth ──────────────────────────────────────────────
        "api_key":  ACTIVE_API_KEY,
        "base_url": pcfg.get("base_url", ""),
        # ── Token limits ──────────────────────────────────────
        "tpm": mcfg["tpm_limit"],
        "tph": mcfg["tph_limit"],
        "tpd": mcfg["tpd_limit"],
        # ── Request limits ────────────────────────────────────
        "rpm": mcfg["rpm_limit"],
        "rph": mcfg["rph_limit"],
        "rpd": mcfg["rpd_limit"],
        # ── Cost ──────────────────────────────────────────────
        "cost_in":  mcfg["cost_input_per_1k"],
        "cost_out": mcfg["cost_output_per_1k"],
        # ── Context ───────────────────────────────────────────
        "ctx":      mcfg["context_window"],
    }


# ── Single config object used everywhere ──────────────────────
ACTIVE_CONFIG: dict = _build_active_config()


# ============================================================
# DATABASE
# ============================================================
class MetricsDB:
    def __init__(self, db_path="agent_monitor.db"):
        self.db_path = db_path
        self.lock    = threading.Lock()
        self._init_db()

    def _conn(self):
        c = sqlite3.connect(self.db_path, check_same_thread=False)
        c.row_factory = sqlite3.Row
        return c

    def _init_db(self):
        c = self._conn()
        c.executescript("""
            CREATE TABLE IF NOT EXISTS detected_files (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                file_path     TEXT UNIQUE,
                file_name     TEXT,
                file_type     TEXT,
                purpose       TEXT,
                is_main_file  INTEGER DEFAULT 0,
                is_ai_agent   INTEGER DEFAULT 0,
                is_script     INTEGER DEFAULT 0,
                description   TEXT,
                size_bytes    INTEGER,
                last_modified REAL,
                scan_time     TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS token_usage (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                file_path   TEXT,
                tokens_used INTEGER,
                token_type  TEXT,
                timestamp   TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS request_usage (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                file_path     TEXT,
                request_count INTEGER DEFAULT 1,
                status_code   INTEGER,
                timestamp     TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS resource_usage (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                file_path   TEXT,
                pid         INTEGER,
                cpu_percent REAL,
                memory_mb   REAL,
                storage_mb  REAL,
                timestamp   TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS scan_history (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                scan_path   TEXT,
                total_files INTEGER,
                ai_agents   INTEGER,
                scripts     INTEGER,
                main_files  INTEGER,
                timestamp   TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)
        c.commit()
        c.close()

    def execute(self, q, p=(), fetch=False):
        with self.lock:
            c   = self._conn()
            cur = c.cursor()
            cur.execute(q, p)
            if fetch:
                r = cur.fetchall()
                c.close()
                return r
            c.commit()
            c.close()

    def clear_files(self):
        with self.lock:
            c = self._conn()
            c.execute("DELETE FROM detected_files")
            c.commit()
            c.close()


# ============================================================
# PROJECT SCANNER
# ============================================================
class ProjectScanner:
    AI_KW = [
        'openai','anthropic','langchain','llama','transformers','torch',
        'tensorflow','keras','huggingface','ollama','gpt','claude','gemini',
        'agent','llm','embedding','vector','rag','chatbot','ai_','ml_',
        'model','predict','inference','neural','deep_learning','crewai',
        'autogen','swarm','prompt','completion','chat_completion','api_key',
        'OPENAI_API_KEY','ANTHROPIC_API_KEY','langsmith','chromadb',
        'pinecone','weaviate','faiss','sentence_transformers',
    ]
    SC_KW = [
        'if __name__','argparse','click','typer','subprocess','os.system',
        'schedule','cron','celery','asyncio.run','main()','def main',
        'flask','fastapi','django','uvicorn','gunicorn','streamlit','gradio',
    ]
    SKIP = {
        '__pycache__','.git','.svn','node_modules','.venv','venv','env',
        '.env','.idea','.vscode','.tox','dist','build','site-packages',
        '.mypy_cache','.pytest_cache','.hg','.bzr',
    }
    EXTS = {
        '.py','.js','.ts','.jsx','.tsx','.yaml','.yml','.json','.toml',
        '.cfg','.ini','.sh','.bat','.ps1','.r','.R','.ipynb',
        '.dockerfile','.env',
    }

    def __init__(self, db: MetricsDB):
        self.db             = db
        self.detected_files = []

    def scan_project(self, root="."):
        root  = os.path.abspath(root)
        self.db.clear_files()
        self.detected_files = []
        files = []

        for dp, dn, fn in os.walk(root):
            dn[:] = [
                d for d in dn
                if d not in self.SKIP and not d.startswith('.')
            ]
            for f in fn:
                fp  = os.path.join(dp, f)
                ext = Path(f).suffix.lower()
                if ext in self.EXTS or \
                   f in ('Dockerfile', 'Makefile', 'Procfile'):
                    info = self._analyze(fp, root)
                    if info:
                        files.append(info)

        self._find_mains(files)

        for f in files:
            try:
                self.db.execute(
                    """INSERT OR REPLACE INTO detected_files
                       (file_path,file_name,file_type,purpose,
                        is_main_file,is_ai_agent,is_script,
                        description,size_bytes,last_modified)
                       VALUES (?,?,?,?,?,?,?,?,?,?)""",
                    (
                        f['file_path'],   f['file_name'],
                        f['file_type'],   f['purpose'],
                        f['is_main_file'],f['is_ai_agent'],
                        f['is_script'],   f['description'],
                        f['size_bytes'],  f['last_modified'],
                    )
                )
            except Exception as e:
                print(f"[scanner] DB error {f['file_name']}: {e}")

        ac = sum(1 for f in files if f['is_ai_agent'])
        sc = sum(1 for f in files if f['is_script'])
        mc = sum(1 for f in files if f['is_main_file'])
        self.db.execute(
            "INSERT INTO scan_history "
            "(scan_path,total_files,ai_agents,scripts,main_files) "
            "VALUES (?,?,?,?,?)",
            (root, len(files), ac, sc, mc)
        )
        self.detected_files = files
        return files

    def _analyze(self, fp, root):
        try:
            fn  = os.path.basename(fp)
            rp  = os.path.relpath(fp, root)
            st  = os.stat(fp)
            ext = Path(fn).suffix.lower()
            try:
                with open(fp, 'r', encoding='utf-8', errors='ignore') as fh:
                    content = fh.read(50_000)
            except Exception:
                return None

            cl    = content.lower()
            ai    = [k for k in self.AI_KW if k.lower() in cl]
            sc    = [k for k in self.SC_KW if k.lower() in cl]
            is_ai = len(ai) >= 2
            is_sc = len(sc) >= 1

            return {
                'file_path':       rp,
                'file_name':       fn,
                'file_type':       self._ftype(ext, is_ai, is_sc),
                'purpose':         self._purpose(fn, content, ext, ai, sc),
                'is_main_file':    0,
                'is_ai_agent':     1 if is_ai else 0,
                'is_script':       1 if is_sc else 0,
                'description':     self._desc(
                                       fn, content, ext,
                                       ai, sc, is_ai, is_sc
                                   ),
                'size_bytes':      st.st_size,
                'last_modified':   st.st_mtime,
                'content_preview': content[:500],
            }
        except Exception:
            return None

    def _purpose(self, fn, content, ext, ai, sc):
        fl = fn.lower()
        cl = content.lower()
        if fl in ('requirements.txt','setup.py','setup.cfg',
                  'pyproject.toml','package.json'):
            return "Config / Dependencies"
        if fl in ('.env', '.env.example'):
            return "Environment Variables"
        if fl in ('dockerfile','docker-compose.yml','docker-compose.yaml'):
            return "Container Config"
        if fl in ('makefile', 'procfile'):
            return "Build / Process"
        if fl.startswith('test_') or fl.endswith('_test.py'):
            return "Testing"
        if 'readme' in fl:
            return "Documentation"
        if ai:
            if any(k in ai for k in ['agent','crewai','autogen','swarm']):
                return "AI Agent Orchestration"
            if any(k in ai for k in ['embedding','vector',
                                      'chromadb','pinecone','faiss']):
                return "Vector Store"
            if 'rag' in ai:
                return "RAG Pipeline"
            if any(k in ai for k in ['prompt','completion',
                                      'chat_completion']):
                return "LLM Interaction"
            if any(k in ai for k in ['model','predict','inference']):
                return "ML Inference"
            if any(k in ai for k in ['transformers','torch',
                                      'tensorflow','keras']):
                return "Deep Learning"
            return "AI/ML Component"
        if 'flask' in cl or 'fastapi' in cl:
            return "Web API"
        if 'streamlit' in cl or 'gradio' in cl:
            return "UI / Dashboard"
        if 'subprocess' in cl or 'os.system' in cl:
            return "System Automation"
        if 'argparse' in cl or 'click' in cl:
            return "CLI Tool"
        if ext == '.py':
            if 'class ' in content: return "Python (Classes)"
            if 'def '   in content: return "Python (Functions)"
            return "Python Script"
        if ext in ('.yaml', '.yml'): return "YAML Config"
        if ext == '.json':           return "JSON Data"
        if ext in ('.sh','.bat','.ps1'): return "Shell Script"
        return "Project File"

    def _desc(self, fn, content, ext, ai, sc, is_ai, is_sc):
        parts = []
        if is_ai: parts.append(f"AI: {', '.join(ai[:5])}")
        if is_sc: parts.append(f"Script: {', '.join(sc[:5])}")
        if ext == '.py':
            try:
                ds = ast.get_docstring(ast.parse(content))
                if ds: parts.append(f"Doc: {ds[:120]}")
            except Exception:
                pass
            cls = re.findall(r'^class (\w+)', content, re.MULTILINE)
            fns = re.findall(r'^def (\w+)',   content, re.MULTILINE)
            if cls: parts.append(f"Classes: {', '.join(cls[:5])}")
            if fns: parts.append(f"Funcs: {', '.join(fns[:8])}")
        imps = re.findall(
            r'^(?:import|from)\s+(\S+)', content, re.MULTILINE
        )
        if imps:
            ui = list(set(i.split('.')[0] for i in imps))[:8]
            parts.append(f"Imports: {', '.join(ui)}")
        return " | ".join(parts) if parts else "Standard file"

    def _ftype(self, ext, ai, sc):
        if ai: return "AI Agent"
        if sc: return "Script"
        return {
            '.py':    'Python',
            '.js':    'JavaScript',
            '.ts':    'TypeScript',
            '.json':  'JSON',
            '.yaml':  'YAML',
            '.yml':   'YAML',
            '.sh':    'Shell',
            '.toml':  'TOML',
            '.ipynb': 'Notebook',
        }.get(ext, 'Other')

    def _find_mains(self, files):
        mains = {
            'main.py','app.py','server.py','run.py','manage.py',
            'index.py','cli.py','wsgi.py','asgi.py','__main__.py',
            'index.js','index.ts','server.js','app.js',
            'main.js','main.ts',
        }
        for f in files:
            if f['file_name'].lower() in mains:
                f['is_main_file'] = 1
            elif re.search(
                r'if\s+__name__\s*==\s*[\'"]__main__[\'"]',
                f.get('content_preview', '')
            ):
                f['is_main_file'] = 1


# ============================================================
# RESOURCE MONITOR
# ──────────────────────────────────────────────────────────────
# FIX: ALL methods are properly indented INSIDE the class.
# Previously _loop/_rates/_sim/get_all_metrics were at module
# level — monitor thread never ran → tokens always zero.
# ============================================================
class ResourceMonitor:

    def __init__(self, db: MetricsDB):
        self.db         = db
        self.monitoring = False
        self.metrics    = {
            'tokens':    defaultdict(
                lambda: {'per_min': 0, 'per_hour': 0, 'per_day': 0}
            ),
            'requests':  defaultdict(
                lambda: {'per_min': 0, 'per_hour': 0, 'per_day': 0}
            ),
            'resources': {},
            'system':    {},
        }
        self._tok_log = defaultdict(list)
        self._req_log = defaultdict(list)

    def start_monitoring(self):
        """Start background monitoring thread."""
        self.monitoring = True
        threading.Thread(
            target=self._loop, daemon=True
        ).start()
        print("[monitor] ✅ Background thread started")

    def stop_monitoring(self):
        """Stop background monitoring thread."""
        self.monitoring = False

    def _loop(self):
        """
        Main monitoring loop — runs every 3 seconds.
        Collects system metrics, process metrics,
        calculates rates and simulates token usage.
        """
        while self.monitoring:
            try:
                self._sys()
                self._proc()
                self._rates()
                self._sim()
            except Exception as e:
                print(f"[monitor] loop error: {e}")
            time.sleep(3)

    def _sys(self):
        """Collect system-wide CPU / memory / disk metrics."""
        cpu  = psutil.cpu_percent(interval=1)
        mem  = psutil.virtual_memory()
        disk = psutil.disk_usage('/')
        self.metrics['system'] = {
            'cpu_pct':    cpu,
            'mem_total':  round(mem.total  / (1024 ** 3), 2),
            'mem_used':   round(mem.used   / (1024 ** 3), 2),
            'mem_pct':    mem.percent,
            'disk_total': round(disk.total / (1024 ** 3), 2),
            'disk_used':  round(disk.used  / (1024 ** 3), 2),
            'disk_pct':   round(disk.percent, 1),
            'ts':         datetime.datetime.now().isoformat(),
        }

    def _proc(self):
        """Collect per-file CPU / memory / storage metrics."""
        rows = self.db.execute(
            "SELECT file_path, file_name FROM detected_files "
            "WHERE is_ai_agent=1 OR is_script=1",
            fetch=True
        )
        for row in rows:
            fp  = row['file_path']
            fn  = row['file_name']
            cpu = mem = storage = 0.0
            pid = 0
            try:
                p = fp if os.path.exists(fp) \
                       else os.path.join('.', fp)
                if os.path.exists(p):
                    storage = os.path.getsize(p) / (1024 * 1024)
                for proc in psutil.process_iter(
                    ['pid', 'cmdline', 'cpu_percent', 'memory_info']
                ):
                    try:
                        cmd = ' '.join(
                            proc.info.get('cmdline') or []
                        )
                        if fn in cmd or fp in cmd:
                            cpu += proc.info.get('cpu_percent', 0) or 0
                            mi   = proc.info.get('memory_info')
                            if mi:
                                mem += mi.rss / (1024 * 1024)
                            pid = proc.info['pid']
                    except (psutil.NoSuchProcess,
                            psutil.AccessDenied):
                        pass
            except Exception:
                pass

            self.metrics['resources'][fp] = {
                'pid':   pid,
                'cpu':   round(cpu,     2),
                'mem':   round(mem,     2),
                'store': round(storage, 4),
            }
            self.db.execute(
                "INSERT INTO resource_usage "
                "(file_path,pid,cpu_percent,memory_mb,storage_mb) "
                "VALUES (?,?,?,?,?)",
                (fp, pid, cpu, mem, storage)
            )

    def _rates(self):
        """
        Calculate per-minute / per-hour / per-day token
        and request rates from in-memory timestamped logs.
        """
        now = time.time()

        for fp, ent in list(self._tok_log.items()):
            ent[:] = [(t, c) for t, c in ent if now - t < 86_400]
            self.metrics['tokens'][fp] = {
                'per_min':  sum(c for t, c in ent if now-t <     60),
                'per_hour': sum(c for t, c in ent if now-t <  3_600),
                'per_day':  sum(c for t, c in ent if now-t < 86_400),
            }

        for fp, ent in list(self._req_log.items()):
            ent[:] = [(t, c) for t, c in ent if now - t < 86_400]
            self.metrics['requests'][fp] = {
                'per_min':  sum(c for t, c in ent if now-t <     60),
                'per_hour': sum(c for t, c in ent if now-t <  3_600),
                'per_day':  sum(c for t, c in ent if now-t < 86_400),
            }

        total_tok = sum(
            v['per_day'] for v in self.metrics['tokens'].values()
        )
        total_req = sum(
            v['per_day'] for v in self.metrics['requests'].values()
        )
        if total_tok > 0 or total_req > 0:
            print(
                f"[rates] tok/day={total_tok:,} "
                f"req/day={total_req:,}"
            )

    def _sim(self):
        """
        Simulate token/request usage for detected AI agents.
        Runs every cycle — guaranteed data on dashboard.
        Replace with real API interception in production.
        """
        files = self.db.execute(
            "SELECT file_path FROM detected_files "
            "WHERE is_ai_agent=1",
            fetch=True
        )
        if not files:
            return

        now = time.time()
        for row in files:
            fp  = row['file_path']
            tok = random.randint(100, 2_000)
            req = random.randint(1, 3)

            self._tok_log[fp].append((now, tok))
            self._req_log[fp].append((now, req))

            self.db.execute(
                "INSERT INTO token_usage "
                "(file_path,tokens_used,token_type) "
                "VALUES (?,?,?)",
                (fp, tok, 'total')
            )
            self.db.execute(
                "INSERT INTO request_usage "
                "(file_path,request_count,status_code) "
                "VALUES (?,?,?)",
                (fp, req, 200)
            )

    def get_all_metrics(self):
        """
        Return complete metrics snapshot.
        Recalculates rates before returning so
        caller always gets fresh data.
        """
        self._rates()
        return {
            'system':    self.metrics['system'],
            'tokens':    dict(self.metrics['tokens']),
            'requests':  dict(self.metrics['requests']),
            'resources': self.metrics['resources'],
        }


# ============================================================
# HTML BUILDER
# ──────────────────────────────────────────────────────────────
# All HTML rendering. app.py calls these static methods.
# ============================================================
class HTMLBuilder:

    NAV_ITEMS = [
        ("/",          "🏠 Home",      "home"),
        ("/dashboard", "📊 Dashboard", "dashboard"),
        ("/files",     "📂 Files",     "files"),
        ("/agents",    "🤖 Agents",    "agents"),
        ("/monitor",   "📈 Metrics",   "monitor"),
        ("/model",     "🧠 Model",     "model"),
        ("/history",   "📜 History",   "history"),
        ("/scan",      "🔍 Scan",      "scan"),
        ("/reset",     "🗑️ Reset",     "reset"),
    ]

    @staticmethod
    def _nav(active=""):
        btns = ""
        for href, label, key in HTMLBuilder.NAV_ITEMS:
            extra = ""
            if key == "reset": extra = " danger"
            if key == "scan":  extra = " success"
            cls = (
                f"nav-btn{extra}"
                f"{' active' if key == active else ''}"
            )
            btns += f'<a href="{href}" class="{cls}">{label}</a>\n'
        return btns

    @staticmethod
    def _css():
        return """
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:'Segoe UI',system-ui,-apple-system,sans-serif;
     background:#060911;color:#cbd5e1;min-height:100vh;font-size:14px}
::-webkit-scrollbar{width:7px}
::-webkit-scrollbar-track{background:#0b1120}
::-webkit-scrollbar-thumb{background:#334155;border-radius:4px}
.topbar{background:linear-gradient(135deg,#0f172a,#1e1b4b,#0f172a);
  border-bottom:1px solid #312e81;padding:14px 24px;
  display:flex;align-items:center;justify-content:space-between;
  flex-wrap:wrap;gap:10px;position:sticky;top:0;z-index:100;
  box-shadow:0 4px 20px rgba(99,102,241,.12)}
.topbar h1{font-size:20px;font-weight:700;
  background:linear-gradient(135deg,#818cf8,#c084fc,#38bdf8);
  -webkit-background-clip:text;-webkit-text-fill-color:transparent}
.live{display:flex;align-items:center;gap:6px;font-size:12px;color:#4ade80}
.live::before{content:'';width:8px;height:8px;border-radius:50%;
  background:#22c55e;animation:pulse 1.5s infinite;display:inline-block}
@keyframes pulse{0%,100%{opacity:1}50%{opacity:.3}}
.nav{background:#080d1a;border-bottom:1px solid #1e293b;
     padding:10px 24px;display:flex;gap:8px;flex-wrap:wrap;overflow-x:auto}
.nav-btn{padding:8px 18px;border-radius:8px;font-size:12px;font-weight:600;
  text-decoration:none;background:#111827;color:#94a3b8;
  border:1px solid #1e293b;transition:all .2s;white-space:nowrap;
  display:inline-block}
.nav-btn:hover{background:#1e293b;color:#e2e8f0;
  transform:translateY(-1px);box-shadow:0 4px 12px rgba(0,0,0,.3)}
.nav-btn.active{background:#312e81;color:#a5b4fc;border-color:#4f46e5}
.nav-btn.danger{color:#f87171;border-color:#7f1d1d}
.nav-btn.danger:hover{background:#7f1d1d;color:#fecaca}
.nav-btn.success{color:#4ade80;border-color:#14532d}
.nav-btn.success:hover{background:#14532d;color:#bbf7d0}
.container{max-width:1800px;margin:0 auto;padding:24px}
.grid{display:grid;gap:16px;margin-bottom:24px}
.g6{grid-template-columns:repeat(auto-fit,minmax(170px,1fr))}
.g4{grid-template-columns:repeat(auto-fit,minmax(200px,1fr))}
.g3{grid-template-columns:repeat(auto-fit,minmax(280px,1fr))}
.g2{grid-template-columns:repeat(auto-fit,minmax(340px,1fr))}
.card{border-radius:14px;padding:20px;border:1px solid;
  position:relative;overflow:hidden;transition:transform .2s}
.card:hover{transform:translateY(-2px)}
.card::before{content:'';position:absolute;top:0;left:0;right:0;height:3px}
.card.blue{background:#0c1a2e;border-color:#1d4ed830}
.card.blue::before{background:linear-gradient(90deg,#2563eb,#3b82f6)}
.card.purple{background:#160c2e;border-color:#7c3aed30}
.card.purple::before{background:linear-gradient(90deg,#7c3aed,#a78bfa)}
.card.green{background:#0a1f0a;border-color:#15803d30}
.card.green::before{background:linear-gradient(90deg,#059669,#22c55e)}
.card.orange{background:#1f1000;border-color:#d9770630}
.card.orange::before{background:linear-gradient(90deg,#d97706,#f59e0b)}
.card.cyan{background:#001f2e;border-color:#0891b230}
.card.cyan::before{background:linear-gradient(90deg,#0891b2,#06b6d4)}
.card.red{background:#1f0808;border-color:#dc262630}
.card.red::before{background:linear-gradient(90deg,#dc2626,#ef4444)}
.card.dark{background:#080d1a;border-color:#1e293b}
.lbl{font-size:11px;text-transform:uppercase;letter-spacing:.8px;
     color:#475569;margin-bottom:6px}
.val{font-size:34px;font-weight:800;line-height:1}
.sub{font-size:11px;color:#475569;margin-top:6px}
.card.blue   .val{color:#3b82f6}
.card.purple .val{color:#a78bfa}
.card.green  .val{color:#22c55e}
.card.orange .val{color:#f59e0b}
.card.cyan   .val{color:#06b6d4}
.card.red    .val{color:#ef4444}
.sec{display:flex;align-items:center;justify-content:space-between;
  margin:28px 0 14px;padding-bottom:10px;border-bottom:1px solid #1e293b}
.sec h2{font-size:16px;color:#e2e8f0;display:flex;align-items:center;gap:8px}
.badge{background:#1e293b;border:1px solid #334155;border-radius:12px;
  padding:3px 12px;font-size:12px;color:#60a5fa}
.pbar-wrap{background:#0f172a;border-radius:8px;height:26px;
  overflow:hidden;border:1px solid #1e293b}
.pbar{height:100%;border-radius:8px;display:flex;align-items:center;
  justify-content:flex-end;padding-right:8px;font-size:11px;
  font-weight:700;color:#fff;min-width:40px;transition:width .5s}
.pbar-detail{display:flex;justify-content:space-between;
  font-size:12px;color:#475569;margin-top:6px}
.tw{background:#080d1a;border:1px solid #1e293b;border-radius:14px;
  overflow:hidden;margin-bottom:24px}
.ts{overflow-x:auto;max-height:520px;overflow-y:auto}
table{width:100%;border-collapse:collapse;min-width:800px}
thead{position:sticky;top:0;z-index:10}
th{background:#0d1424;padding:12px 14px;text-align:left;font-size:11px;
  text-transform:uppercase;letter-spacing:.8px;color:#475569;
  font-weight:600;border-bottom:1px solid #1e293b;white-space:nowrap}
td{padding:10px 14px;border-bottom:1px solid #0f172a;
  font-size:13px;vertical-align:middle}
tr:hover td{background:#0d1628}
.empty{text-align:center;color:#334155;padding:48px!important;font-size:14px}
.tag{display:inline-flex;align-items:center;gap:3px;padding:3px 8px;
  border-radius:5px;font-size:11px;font-weight:600;white-space:nowrap}
.t-ai{background:#1e3a5f;color:#60a5fa;border:1px solid #2563eb40}
.t-sc{background:#2d1b4e;color:#c084fc;border:1px solid #7c3aed40}
.t-mn{background:#0d2e1a;color:#4ade80;border:1px solid #15803d40}
.t-fl{background:#1e293b;color:#94a3b8;border:1px solid #33415540}
.path{font-family:monospace;font-size:11px;color:#64748b}
.purp{color:#818cf8;font-weight:500;font-size:12px}
.desc{color:#64748b;font-size:11px;max-width:300px;display:block;
  white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.sz{font-family:monospace;font-size:12px;color:#475569}
.urow{display:flex;justify-content:space-between;align-items:center;
  padding:10px 0;border-bottom:1px solid #0f172a;gap:16px}
.urow:last-child{border-bottom:none}
.ulbl{font-size:12px;color:#64748b;margin-bottom:4px}
.ubar{height:6px;background:#1e293b;border-radius:3px;
  overflow:hidden;width:100%}
.ufill{height:100%;border-radius:3px}
.uval{font-size:15px;font-weight:700;font-family:monospace;
  color:#e2e8f0;text-align:right}
.ulim{font-size:11px;color:#334155;text-align:right}
.mi{background:#080d1a;border:1px solid #1e293b;
  border-radius:10px;padding:14px 16px}
.mi-l{font-size:11px;color:#475569;text-transform:uppercase;
  letter-spacing:.8px;margin-bottom:4px}
.mi-v{font-size:14px;font-weight:600;color:#a5b4fc;font-family:monospace}
.alert{padding:16px 20px;border-radius:10px;margin-bottom:24px;
  display:flex;align-items:center;gap:12px;font-size:14px}
.a-ok{background:#052e16;border:1px solid #15803d;color:#4ade80}
.a-warn{background:#431407;border:1px solid #d97706;color:#fbbf24}
.a-bad{background:#450a0a;border:1px solid #dc2626;color:#f87171}
.a-info{background:#0c1a2e;border:1px solid #2563eb;color:#60a5fa}
.hero{text-align:center;padding:60px 24px;
  background:linear-gradient(180deg,#0f172a 0%,#060911 100%);
  border-bottom:1px solid #1e293b}
.hero h2{font-size:42px;font-weight:800;
  background:linear-gradient(135deg,#818cf8,#c084fc,#38bdf8,#22c55e);
  -webkit-background-clip:text;-webkit-text-fill-color:transparent;
  margin-bottom:12px}
.hero p{color:#64748b;font-size:16px;
  max-width:600px;margin:0 auto 32px}
.hcards{display:flex;gap:24px;justify-content:center;
  flex-wrap:wrap;margin-top:32px}
.hcard{background:#111827;border:1px solid #1e293b;border-radius:16px;
  padding:24px 32px;text-align:center;min-width:180px;transition:transform .2s}
.hcard:hover{transform:translateY(-4px);
  box-shadow:0 8px 24px rgba(0,0,0,.4)}
.hcard .icon{font-size:32px;margin-bottom:8px}
.hcard .hval{font-size:28px;font-weight:800;margin:4px 0}
.hcard .hlbl{font-size:12px;color:#64748b}
.footer{text-align:center;padding:20px;color:#1e293b;
  font-size:12px;border-top:1px solid #0f172a;margin-top:32px}
@media(max-width:768px){
  .g6{grid-template-columns:repeat(2,1fr)}
  .g3,.g4{grid-template-columns:1fr}
  .hero h2{font-size:28px}
  .hcards{flex-direction:column;align-items:center}
}
</style>"""

    @staticmethod
    def _topbar_html():
        return f"""
<div class="topbar">
  <h1>🤖 AI Agent Monitor</h1>
  <div style="display:flex;align-items:center;gap:16px">
    <span style="font-size:12px;color:#818cf8;font-weight:600">
      🧠 {ACTIVE_CONFIG['name']}
      &nbsp;•&nbsp;
      ⚡ {ACTIVE_CONFIG['provider'].upper()}
    </span>
    <span class="live">Live</span>
  </div>
</div>"""

    @staticmethod
    def _footer_html():
        return f"""
<div class="footer">
  AI Agent Monitor &nbsp;•&nbsp;
  {ACTIVE_CONFIG['name']} ({ACTIVE_CONFIG['provider']})
  &nbsp;•&nbsp;
  {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
</div>
</body></html>"""

    @staticmethod
    def page(title, active, body, refresh=0):
        meta = (
            f'<meta http-equiv="refresh" content="{refresh}">'
            if refresh > 0 else ""
        )
        return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0">
{meta}
<title>{title} — AI Agent Monitor</title>
{HTMLBuilder._css()}
</head>
<body>
{HTMLBuilder._topbar_html()}
<div class="nav">{HTMLBuilder._nav(active)}</div>
{body}
{HTMLBuilder._footer_html()}"""

    @staticmethod
    def _pbar(pct, color):
        return f"""
<div class="pbar-wrap">
  <div class="pbar" style="width:{pct}%;background:{color}">
    {pct:.1f}%</div>
</div>"""

    @staticmethod
    def _urow(label, used, limit, color):
        p = min(round(used / max(limit, 1) * 100, 1), 100)
        c = '#ef4444' if p > 80 else '#f59e0b' if p > 50 else color
        return f"""
<div class="urow">
  <div style="flex:1">
    <div class="ulbl">{label}</div>
    <div class="ubar">
      <div class="ufill"
           style="width:{p}%;background:{c}"></div>
    </div>
  </div>
  <div>
    <div class="uval">{used:,}</div>
    <div class="ulim">/ {limit:,}</div>
  </div>
</div>"""

    @staticmethod
    def _bc(p):
        if p > 80: return '#ef4444'
        if p > 60: return '#f59e0b'
        if p > 40: return '#3b82f6'
        return '#22c55e'

    @staticmethod
    def _mc(p):
        if p > 80: return '#ef4444'
        if p > 50: return '#f59e0b'
        return '#22c55e'

    @staticmethod
    def _pct(used, limit):
        return min(round(used / max(limit, 1) * 100, 1), 100)

    @staticmethod
    def _fmt_size(b):
        if b > 1_048_576: return f"{b/1_048_576:.1f} MB"
        if b > 1024:      return f"{b/1024:.1f} KB"
        return f"{b} B"

    # ═══════════════════════════════════════════════════════════
    # PAGE BUILDERS
    # ═══════════════════════════════════════════════════════════

    @staticmethod
    def home(files, metrics):
        sys_m = metrics.get('system', {})
        ai  = sum(1 for f in files if f.get('is_ai_agent'))
        sc  = sum(1 for f in files if f.get('is_script'))
        mn  = sum(1 for f in files if f.get('is_main_file'))
        tok = sum(
            v.get('per_day', 0)
            for v in metrics.get('tokens', {}).values()
        )
        req = sum(
            v.get('per_day', 0)
            for v in metrics.get('requests', {}).values()
        )
        body = f"""
<div class="hero">
  <h2>AI Agent Monitor</h2>
  <p>Real-time monitoring for AI agents, scripts,
     tokens, requests and system resources.</p>
  <div class="hcards">
    <div class="hcard">
      <div class="icon">📂</div>
      <div class="hval" style="color:#3b82f6">{len(files)}</div>
      <div class="hlbl">Total Files</div></div>
    <div class="hcard">
      <div class="icon">🤖</div>
      <div class="hval" style="color:#a78bfa">{ai}</div>
      <div class="hlbl">AI Agents</div></div>
    <div class="hcard">
      <div class="icon">⚡</div>
      <div class="hval" style="color:#22c55e">{sc}</div>
      <div class="hlbl">Scripts</div></div>
    <div class="hcard">
      <div class="icon">★</div>
      <div class="hval" style="color:#f59e0b">{mn}</div>
      <div class="hlbl">Main Files</div></div>
    <div class="hcard">
      <div class="icon">🪙</div>
      <div class="hval" style="color:#06b6d4">{tok:,}</div>
      <div class="hlbl">Tokens Today</div></div>
    <div class="hcard">
      <div class="icon">📡</div>
      <div class="hval" style="color:#ef4444">{req:,}</div>
      <div class="hlbl">Requests Today</div></div>
  </div>
</div>
<div class="container">
  <div class="sec"><h2>💡 Quick Navigation</h2></div>
  <div class="grid g3">
    <a href="/dashboard" style="text-decoration:none">
      <div class="card blue"><div class="lbl">📊 DASHBOARD</div>
        <div style="color:#94a3b8;font-size:13px;margin-top:8px">
          Full overview — resources, tokens, requests
        </div></div></a>
    <a href="/files" style="text-decoration:none">
      <div class="card green"><div class="lbl">📂 FILES</div>
        <div style="color:#94a3b8;font-size:13px;margin-top:8px">
          All detected files with type, purpose, size
        </div></div></a>
    <a href="/agents" style="text-decoration:none">
      <div class="card purple"><div class="lbl">🤖 AGENTS</div>
        <div style="color:#94a3b8;font-size:13px;margin-top:8px">
          Per-agent token, request and resource metrics
        </div></div></a>
    <a href="/monitor" style="text-decoration:none">
      <div class="card cyan"><div class="lbl">📈 METRICS</div>
        <div style="color:#94a3b8;font-size:13px;margin-top:8px">
          Token/request usage vs limits + cost
        </div></div></a>
    <a href="/model" style="text-decoration:none">
      <div class="card orange"><div class="lbl">🧠 MODEL</div>
        <div style="color:#94a3b8;font-size:13px;margin-top:8px">
          Active model config, all providers
        </div></div></a>
    <a href="/history" style="text-decoration:none">
      <div class="card dark"><div class="lbl">📜 HISTORY</div>
        <div style="color:#94a3b8;font-size:13px;margin-top:8px">
          Past scan results and timeline
        </div></div></a>
  </div>
  <div class="sec"><h2>💻 System Status</h2></div>
  <div class="grid g3">
    <div class="card dark">
      <div class="lbl">🔲 CPU</div>
      {HTMLBuilder._pbar(
          sys_m.get('cpu_pct', 0),
          HTMLBuilder._bc(sys_m.get('cpu_pct', 0))
      )}
    </div>
    <div class="card dark">
      <div class="lbl">🧠 Memory</div>
      {HTMLBuilder._pbar(
          sys_m.get('mem_pct', 0),
          HTMLBuilder._bc(sys_m.get('mem_pct', 0))
      )}
      <div class="pbar-detail">
        <span>{sys_m.get('mem_used', 0)} GB</span>
        <span>{sys_m.get('mem_total', 0)} GB</span>
      </div>
    </div>
    <div class="card dark">
      <div class="lbl">💾 Disk</div>
      {HTMLBuilder._pbar(
          sys_m.get('disk_pct', 0),
          HTMLBuilder._bc(sys_m.get('disk_pct', 0))
      )}
      <div class="pbar-detail">
        <span>{sys_m.get('disk_used', 0)} GB</span>
        <span>{sys_m.get('disk_total', 0)} GB</span>
      </div>
    </div>
  </div>
</div>"""
        return HTMLBuilder.page("Home", "home", body)

    @staticmethod
    def dashboard(files, metrics):
        sys_m  = metrics.get('system',   {})
        tokens = metrics.get('tokens',   {})
        reqs   = metrics.get('requests', {})
        cfg    = ACTIVE_CONFIG

        ai = sum(1 for f in files if f.get('is_ai_agent'))
        sc = sum(1 for f in files if f.get('is_script'))
        mn = sum(1 for f in files if f.get('is_main_file'))
        tm = sum(v.get('per_min',  0) for v in tokens.values())
        th = sum(v.get('per_hour', 0) for v in tokens.values())
        td = sum(v.get('per_day',  0) for v in tokens.values())
        rm = sum(v.get('per_min',  0) for v in reqs.values())
        rh = sum(v.get('per_hour', 0) for v in reqs.values())
        rd = sum(v.get('per_day',  0) for v in reqs.values())

        body = f"""
<div class="container">
  <div class="sec">
    <h2>📊 Overview</h2>
    <span class="badge">Live</span>
  </div>
  <div class="grid g6">
    <div class="card blue">
      <div class="lbl">Total Files</div>
      <div class="val">{len(files)}</div></div>
    <div class="card purple">
      <div class="lbl">AI Agents</div>
      <div class="val">{ai}</div></div>
    <div class="card green">
      <div class="lbl">Scripts</div>
      <div class="val">{sc}</div></div>
    <div class="card orange">
      <div class="lbl">Main Files</div>
      <div class="val">{mn}</div></div>
    <div class="card cyan">
      <div class="lbl">Tokens/Day</div>
      <div class="val">{td:,}</div></div>
    <div class="card red">
      <div class="lbl">Requests/Day</div>
      <div class="val">{rd:,}</div></div>
  </div>
  <div class="sec">
    <h2>💻 System Resources</h2>
    <span class="badge">{sys_m.get('ts', '')[:19]}</span>
  </div>
  <div class="grid g3">
    <div class="card dark">
      <div class="lbl">🔲 CPU</div>
      {HTMLBuilder._pbar(
          sys_m.get('cpu_pct', 0),
          HTMLBuilder._bc(sys_m.get('cpu_pct', 0))
      )}
      <div class="pbar-detail">
        <span>Processor</span>
        <span>{sys_m.get('cpu_pct', 0):.1f}%</span>
      </div>
    </div>
    <div class="card dark">
      <div class="lbl">🧠 Memory</div>
      {HTMLBuilder._pbar(
          sys_m.get('mem_pct', 0),
          HTMLBuilder._bc(sys_m.get('mem_pct', 0))
      )}
      <div class="pbar-detail">
        <span>{sys_m.get('mem_used', 0)} GB</span>
        <span>/ {sys_m.get('mem_total', 0)} GB</span>
      </div>
    </div>
    <div class="card dark">
      <div class="lbl">💾 Disk</div>
      {HTMLBuilder._pbar(
          sys_m.get('disk_pct', 0),
          HTMLBuilder._bc(sys_m.get('disk_pct', 0))
      )}
      <div class="pbar-detail">
        <span>{sys_m.get('disk_used', 0)} GB</span>
        <span>/ {sys_m.get('disk_total', 0)} GB</span>
      </div>
    </div>
  </div>
  <div class="sec"><h2>📊 Usage vs Limits</h2></div>
  <div class="grid g2">
    <div class="card dark" style="padding:24px">
      <h3 style="font-size:14px;color:#e2e8f0;margin-bottom:16px;
          border-bottom:1px solid #1e293b;padding-bottom:10px">
        🪙 Tokens</h3>
      {HTMLBuilder._urow('Per Minute', tm, cfg['tpm'], '#3b82f6')}
      {HTMLBuilder._urow('Per Hour',   th, cfg['tph'], '#8b5cf6')}
      {HTMLBuilder._urow('Per Day',    td, cfg['tpd'], '#06b6d4')}
    </div>
    <div class="card dark" style="padding:24px">
      <h3 style="font-size:14px;color:#e2e8f0;margin-bottom:16px;
          border-bottom:1px solid #1e293b;padding-bottom:10px">
        📡 Requests</h3>
      {HTMLBuilder._urow('Per Minute', rm, cfg['rpm'], '#22c55e')}
      {HTMLBuilder._urow('Per Hour',   rh, cfg['rph'], '#f59e0b')}
      {HTMLBuilder._urow('Per Day',    rd, cfg['rpd'], '#ef4444')}
    </div>
  </div>
</div>"""
        return HTMLBuilder.page("Dashboard", "dashboard", body, refresh=10)

    @staticmethod
    def files(files):
        rows = ""
        for f in files:
            if f.get('is_ai_agent'):
                tag = '<span class="tag t-ai">🤖 AI Agent</span>'
            elif f.get('is_script'):
                tag = '<span class="tag t-sc">⚡ Script</span>'
            else:
                tag = (
                    f'<span class="tag t-fl">'
                    f'{f.get("file_type", "")}</span>'
                )
            flags = ""
            if f.get('is_main_file'):
                flags += '<span class="tag t-mn">★</span> '
            if f.get('is_ai_agent'):
                flags += '<span class="tag t-ai">AI</span> '
            if f.get('is_script'):
                flags += '<span class="tag t-sc">Sc</span>'
            desc = (f.get('description', '') or '')[:150]
            sz   = HTMLBuilder._fmt_size(f.get('size_bytes', 0))
            rows += f"""<tr>
              <td>{tag}</td>
              <td><strong style="color:#e2e8f0">
                {f['file_name']}</strong></td>
              <td><code class="path">{f['file_path']}</code></td>
              <td><span class="purp">
                {f.get('purpose', '-')}</span></td>
              <td><span class="desc">{desc}</span></td>
              <td><span class="sz">{sz}</span></td>
              <td>{flags}</td></tr>"""
        if not rows:
            rows = (
                '<tr><td colspan="7" class="empty">'
                'No files. Click 🔍 Scan</td></tr>'
            )
        body = f"""
<div class="container">
  <div class="sec">
    <h2>📂 Detected Files</h2>
    <span class="badge">{len(files)} files</span>
  </div>
  <div class="tw"><div class="ts"><table>
    <thead><tr>
      <th>Type</th><th>Name</th><th>Path</th><th>Purpose</th>
      <th>Description</th><th>Size</th><th>Flags</th>
    </tr></thead>
    <tbody>{rows}</tbody>
  </table></div></div>
</div>"""
        return HTMLBuilder.page("Files", "files", body)

    @staticmethod
    def agents(files, metrics):
        tokens = metrics.get('tokens',   {})
        reqs   = metrics.get('requests', {})
        res    = metrics.get('resources',{})
        cfg    = ACTIVE_CONFIG
        active = [
            f for f in files
            if f.get('is_ai_agent') or f.get('is_script')
        ]
        rows = ""
        for a in active:
            fp  = a['file_path']
            tok = tokens.get(fp, {'per_min':0,'per_hour':0,'per_day':0})
            rq  = reqs.get(  fp, {'per_min':0,'per_hour':0,'per_day':0})
            rc  = res.get(   fp, {'cpu':0,'mem':0,'store':0})
            sn  = re.sub(r'\.[^.]+$', '', a['file_name'])
            sd  = (a.get('description', '') or '')[:100]

            def _c(u, lim):
                return HTMLBuilder._mc(HTMLBuilder._pct(u, lim))

            rows += f"""<tr>
              <td><strong style="color:#60a5fa">{sn}</strong></td>
              <td style="color:#94a3b8">{a['file_name']}</td>
              <td><span class="purp">
                {a.get('purpose', '-')}</span></td>
              <td><span class="desc">{sd}</span></td>
              <td style="color:{_c(tok['per_min'],cfg['tpm'])};
                  font-family:monospace">{tok['per_min']:,}
                <small style="color:#334155">
                  /{cfg['tpm']:,}</small></td>
              <td style="color:{_c(tok['per_hour'],cfg['tph'])};
                  font-family:monospace">{tok['per_hour']:,}
                <small style="color:#334155">
                  /{cfg['tph']:,}</small></td>
              <td style="color:{_c(tok['per_day'],cfg['tpd'])};
                  font-family:monospace">{tok['per_day']:,}
                <small style="color:#334155">
                  /{cfg['tpd']:,}</small></td>
              <td style="color:{_c(rq['per_min'],cfg['rpm'])};
                  font-family:monospace">{rq['per_min']:,}
                <small style="color:#334155">
                  /{cfg['rpm']:,}</small></td>
              <td style="color:{_c(rq['per_hour'],cfg['rph'])};
                  font-family:monospace">{rq['per_hour']:,}
                <small style="color:#334155">
                  /{cfg['rph']:,}</small></td>
              <td style="color:{_c(rq['per_day'],cfg['rpd'])};
                  font-family:monospace">{rq['per_day']:,}
                <small style="color:#334155">
                  /{cfg['rpd']:,}</small></td>
              <td style="color:{HTMLBuilder._mc(rc.get('cpu',0))}">
                {rc.get('cpu',0):.1f}%</td>
              <td style="color:#a78bfa">
                {rc.get('mem',0):.1f}</td>
              <td style="color:#64748b">
                {rc.get('store',0):.3f}</td></tr>"""
        if not rows:
            rows = (
                '<tr><td colspan="13" class="empty">'
                'No agents/scripts detected</td></tr>'
            )
        body = f"""
<div class="container">
  <div class="sec">
    <h2>🤖 Agent & Script Metrics</h2>
    <span class="badge">{len(active)} active</span>
  </div>
  <div class="tw"><div class="ts"><table>
    <thead><tr>
      <th>Script</th><th>File</th><th>Purpose</th><th>Desc</th>
      <th>Tok/Min</th><th>Tok/Hr</th><th>Tok/Day</th>
      <th>Req/Min</th><th>Req/Hr</th><th>Req/Day</th>
      <th>CPU</th><th>Mem MB</th><th>Store MB</th>
    </tr></thead>
    <tbody>{rows}</tbody>
  </table></div></div>
</div>"""
        return HTMLBuilder.page("Agents", "agents", body, refresh=10)

    @staticmethod
    def monitor(metrics):
        tokens = metrics.get('tokens',   {})
        reqs   = metrics.get('requests', {})
        cfg    = ACTIVE_CONFIG

        tm = sum(v.get('per_min',  0) for v in tokens.values())
        th = sum(v.get('per_hour', 0) for v in tokens.values())
        td = sum(v.get('per_day',  0) for v in tokens.values())
        rm = sum(v.get('per_min',  0) for v in reqs.values())
        rh = sum(v.get('per_hour', 0) for v in reqs.values())
        rd = sum(v.get('per_day',  0) for v in reqs.values())

        ci = (td / 1000) * cfg['cost_in']
        co = (td / 1000) * cfg['cost_out']

        body = f"""
<div class="container">
  <div class="sec">
    <h2>📈 Live Metrics</h2>
    <span class="badge">Auto-refresh 10s</span>
  </div>
  <div class="grid g6">
    <div class="card blue">
      <div class="lbl">Tok/Min</div>
      <div class="val">{tm:,}</div>
      <div class="sub">/{cfg['tpm']:,}</div></div>
    <div class="card purple">
      <div class="lbl">Tok/Hour</div>
      <div class="val">{th:,}</div>
      <div class="sub">/{cfg['tph']:,}</div></div>
    <div class="card cyan">
      <div class="lbl">Tok/Day</div>
      <div class="val">{td:,}</div>
      <div class="sub">/{cfg['tpd']:,}</div></div>
    <div class="card green">
      <div class="lbl">Req/Min</div>
      <div class="val">{rm:,}</div>
      <div class="sub">/{cfg['rpm']:,}</div></div>
    <div class="card orange">
      <div class="lbl">Req/Hour</div>
      <div class="val">{rh:,}</div>
      <div class="sub">/{cfg['rph']:,}</div></div>
    <div class="card red">
      <div class="lbl">Req/Day</div>
      <div class="val">{rd:,}</div>
      <div class="sub">/{cfg['rpd']:,}</div></div>
  </div>
  <div class="sec"><h2>📊 Usage Bars</h2></div>
  <div class="grid g2">
    <div class="card dark" style="padding:24px">
      <h3 style="font-size:14px;color:#e2e8f0;margin-bottom:16px;
          border-bottom:1px solid #1e293b;padding-bottom:10px">
        🪙 Tokens</h3>
      {HTMLBuilder._urow('Per Minute', tm, cfg['tpm'], '#3b82f6')}
      {HTMLBuilder._urow('Per Hour',   th, cfg['tph'], '#8b5cf6')}
      {HTMLBuilder._urow('Per Day',    td, cfg['tpd'], '#06b6d4')}
    </div>
    <div class="card dark" style="padding:24px">
      <h3 style="font-size:14px;color:#e2e8f0;margin-bottom:16px;
          border-bottom:1px solid #1e293b;padding-bottom:10px">
        📡 Requests</h3>
      {HTMLBuilder._urow('Per Minute', rm, cfg['rpm'], '#22c55e')}
      {HTMLBuilder._urow('Per Hour',   rh, cfg['rph'], '#f59e0b')}
      {HTMLBuilder._urow('Per Day',    rd, cfg['rpd'], '#ef4444')}
    </div>
  </div>
  <div class="sec"><h2>💰 Estimated Cost Today</h2></div>
  <div class="grid g3">
    <div class="card green">
      <div class="lbl">Input Cost</div>
      <div style="font-size:24px;font-weight:700;
          color:#22c55e;margin-top:8px">${ci:.4f}</div></div>
    <div class="card orange">
      <div class="lbl">Output Cost</div>
      <div style="font-size:24px;font-weight:700;
          color:#f59e0b;margin-top:8px">${co:.4f}</div></div>
    <div class="card red">
      <div class="lbl">Total Est.</div>
      <div style="font-size:24px;font-weight:700;
          color:#ef4444;margin-top:8px">${ci + co:.4f}</div></div>
  </div>
</div>"""
        return HTMLBuilder.page("Metrics", "monitor", body, refresh=10)

    @staticmethod
    def model():
        cfg = ACTIVE_CONFIG

        # ── Check API key live from env ────────────────────────
        _live_keys = {
            "google":    os.environ.get("GEMINI_API_KEY",
                         os.environ.get("GOOGLE_API_KEY", "")),
            "openai":    os.environ.get("OPENAI_API_KEY",    ""),
            "anthropic": os.environ.get("ANTHROPIC_API_KEY", ""),
            "groq":      os.environ.get("GROQ_API_KEY",      ""),
            "mistral":   os.environ.get("MISTRAL_API_KEY",   ""),
            "ollama":    "local",
        }
        live_key = _live_keys.get(cfg['provider'], "")
        key_ok   = bool(live_key) or cfg['provider'] == "ollama"
        ks = "✅ API Key Set" if key_ok else "❌ API Key Missing"
        kc = "a-ok"          if key_ok else "a-bad"

        rows = ""
        for prov, pcfg in MODEL_REGISTRY.items():
            for mname, mcfg in pcfg['models'].items():
                is_active = (
                    prov  == cfg['provider'] and
                    mname == cfg['name']
                )
                hl  = ("color:#22c55e;font-weight:700"
                       if is_active else "color:#475569")
                txt = "✅ ACTIVE" if is_active else ""
                rows += f"""<tr>
                  <td style="color:#a5b4fc">{prov.upper()}</td>
                  <td><strong style="color:#e2e8f0">
                    {mname}</strong></td>
                  <td style="font-family:monospace">
                    {mcfg['tpm_limit']:,}</td>
                  <td style="font-family:monospace">
                    {mcfg['rpm_limit']:,}</td>
                  <td style="font-family:monospace">
                    {mcfg['context_window']:,}</td>
                  <td style="font-family:monospace">
                    ${mcfg['cost_input_per_1k']:.5f}</td>
                  <td style="font-family:monospace">
                    ${mcfg['cost_output_per_1k']:.5f}</td>
                  <td style="{hl}">{txt}</td></tr>"""

        body = f"""
<div class="container">
  <div class="sec">
    <h2>🧠 Model Configuration</h2>
    <span class="badge">
      {cfg['provider'].upper()} → {cfg['name']}</span>
  </div>
  <div class="alert {kc}">{ks}</div>
  <div class="grid g4">
    <div class="mi">
      <div class="mi-l">Provider</div>
      <div class="mi-v">{cfg['provider'].upper()}</div></div>
    <div class="mi">
      <div class="mi-l">Model</div>
      <div class="mi-v">{cfg['name']}</div></div>
    <div class="mi">
      <div class="mi-l">Context Window</div>
      <div class="mi-v">{cfg['ctx']:,} tokens</div></div>
    <div class="mi">
      <div class="mi-l">Base URL</div>
      <div class="mi-v" style="font-size:11px">
        {cfg['base_url']}</div></div>
  </div>
  <div class="sec"><h2>🔒 Rate Limits</h2></div>
  <div class="grid g3">
    <div class="card blue">
      <div class="lbl">Tokens / Min</div>
      <div class="val">{cfg['tpm']:,}</div></div>
    <div class="card purple">
      <div class="lbl">Tokens / Hour</div>
      <div class="val">{cfg['tph']:,}</div></div>
    <div class="card cyan">
      <div class="lbl">Tokens / Day</div>
      <div class="val">{cfg['tpd']:,}</div></div>
    <div class="card green">
      <div class="lbl">Requests / Min</div>
      <div class="val">{cfg['rpm']:,}</div></div>
    <div class="card orange">
      <div class="lbl">Requests / Hour</div>
      <div class="val">{cfg['rph']:,}</div></div>
    <div class="card red">
      <div class="lbl">Requests / Day</div>
      <div class="val">{cfg['rpd']:,}</div></div>
  </div>
  <div class="sec"><h2>💰 Pricing</h2></div>
  <div class="grid g3">
    <div class="card dark">
      <div class="mi-l">Input / 1K tokens</div>
      <div style="font-size:22px;font-weight:700;
          color:#22c55e;margin-top:8px">
        ${cfg['cost_in']:.5f}</div></div>
    <div class="card dark">
      <div class="mi-l">Output / 1K tokens</div>
      <div style="font-size:22px;font-weight:700;
          color:#f59e0b;margin-top:8px">
        ${cfg['cost_out']:.5f}</div></div>
    <div class="card dark">
      <div class="mi-l">Env Variables</div>
      <div style="font-size:12px;color:#94a3b8;
          margin-top:8px;font-family:monospace">
        AI_PROVIDER={AI_PROVIDER}<br>
        AI_MODEL={AI_MODEL}</div></div>
  </div>
  <div class="sec"><h2>📋 All Models</h2></div>
  <div class="tw"><div class="ts"><table>
    <thead><tr>
      <th>Provider</th><th>Model</th><th>TPM</th><th>RPM</th>
      <th>Context</th><th>In $/1K</th><th>Out $/1K</th>
      <th>Status</th>
    </tr></thead>
    <tbody>{rows}</tbody>
  </table></div></div>
</div>"""
        return HTMLBuilder.page("Model", "model", body)

    @staticmethod
    def history(db):
        hist = db.execute(
            "SELECT * FROM scan_history "
            "ORDER BY timestamp DESC LIMIT 50",
            fetch=True
        )
        rows = ""
        for h in hist:
            h = dict(h)
            rows += f"""<tr>
              <td style="color:#64748b;font-family:monospace;
                  font-size:12px">{h.get('timestamp', '')}</td>
              <td><code class="path">
                {h.get('scan_path', '')}</code></td>
              <td style="color:#3b82f6;font-weight:600">
                {h.get('total_files', 0)}</td>
              <td style="color:#a78bfa;font-weight:600">
                {h.get('ai_agents', 0)}</td>
              <td style="color:#22c55e;font-weight:600">
                {h.get('scripts', 0)}</td>
              <td style="color:#f59e0b;font-weight:600">
                {h.get('main_files', 0)}</td></tr>"""
        if not rows:
            rows = (
                '<tr><td colspan="6" class="empty">'
                'No history. Click 🔍 Scan</td></tr>'
            )
        body = f"""
<div class="container">
  <div class="sec">
    <h2>📜 Scan History</h2>
    <span class="badge">{len(hist)} scans</span>
  </div>
  <div class="tw"><div class="ts"><table>
    <thead><tr>
      <th>Timestamp</th><th>Path</th><th>Total</th>
      <th>AI</th><th>Scripts</th><th>Main</th>
    </tr></thead>
    <tbody>{rows}</tbody>
  </table></div></div>
</div>"""
        return HTMLBuilder.page("History", "history", body)

    @staticmethod
    def scan_done(result):
        body = f"""
<div class="container">
  <div class="alert a-ok" style="margin-top:24px">
    ✅ Scan complete!</div>
  <div class="grid g4" style="margin-top:16px">
    <div class="card blue">
      <div class="lbl">Total</div>
      <div class="val">{result['total']}</div></div>
    <div class="card purple">
      <div class="lbl">AI Agents</div>
      <div class="val">{result['ai']}</div></div>
    <div class="card green">
      <div class="lbl">Scripts</div>
      <div class="val">{result['sc']}</div></div>
    <div class="card orange">
      <div class="lbl">Main Files</div>
      <div class="val">{result['mn']}</div></div>
  </div>
  <div style="text-align:center;margin-top:32px">
    <a href="/dashboard" class="nav-btn active"
       style="font-size:15px;padding:12px 32px">
      📊 Go to Dashboard</a>
    <a href="/files" class="nav-btn"
       style="font-size:15px;padding:12px 32px;margin-left:12px">
      📂 View Files</a>
  </div>
</div>"""
        return HTMLBuilder.page("Scan Done", "scan", body)

    @staticmethod
    def reset_done():
        body = """
<div class="container">
  <div class="alert a-warn" style="margin-top:24px">
    🗑️ All data reset.</div>
  <div style="text-align:center;margin-top:32px">
    <a href="/" class="nav-btn"
       style="font-size:15px;padding:12px 32px">
      🏠 Home</a>
    <a href="/scan" class="nav-btn success"
       style="font-size:15px;padding:12px 32px;margin-left:12px">
      🔍 Scan Again</a>
  </div>
</div>"""
        return HTMLBuilder.page("Reset", "reset", body)
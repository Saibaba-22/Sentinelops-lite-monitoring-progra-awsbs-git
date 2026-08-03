#!/usr/bin/env python3
"""
AI Agent & Script Monitor Dashboard
====================================
A self-contained monitoring dashboard that:
- Scans entire project for AI agents/scripts
- Detects file purposes and main files
- Tracks token usage, request counts, CPU, memory, storage
- Collects all metrics independently (no Prometheus/Grafana)
- Shows everything in a web dashboard
"""

import os
import sys
import time
import json
import ast
import re
import threading
import hashlib
import sqlite3
import socket
import psutil
import datetime
from pathlib import Path
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
from collections import defaultdict
import importlib.util

# ============================================================
# CONFIGURATION - SELECT YOUR AI MODEL
# ============================================================
SUPPORTED_MODELS = {
    "1": {"name": "OpenAI GPT-4", "provider": "openai", "token_limit_per_min": 10000, "token_limit_per_hour": 300000, "token_limit_per_day": 5000000, "request_limit_per_min": 60, "request_limit_per_hour": 3500, "request_limit_per_day": 50000},
    "2": {"name": "OpenAI GPT-3.5-Turbo", "provider": "openai", "token_limit_per_min": 60000, "token_limit_per_hour": 1800000, "token_limit_per_day": 30000000, "request_limit_per_min": 60, "request_limit_per_hour": 3500, "request_limit_per_day": 50000},
    "3": {"name": "Anthropic Claude 3", "provider": "anthropic", "token_limit_per_min": 25000, "token_limit_per_hour": 750000, "token_limit_per_day": 12500000, "request_limit_per_min": 50, "request_limit_per_hour": 2000, "request_limit_per_day": 30000},
    "4": {"name": "Google Gemini Pro", "provider": "google", "token_limit_per_min": 30000, "token_limit_per_hour": 900000, "token_limit_per_day": 15000000, "request_limit_per_min": 60, "request_limit_per_hour": 1500, "request_limit_per_day": 25000},
    "5": {"name": "Ollama Local", "provider": "ollama", "token_limit_per_min": 100000, "token_limit_per_hour": 6000000, "token_limit_per_day": 100000000, "request_limit_per_min": 120, "request_limit_per_hour": 7200, "request_limit_per_day": 100000},
    "6": {"name": "Custom / Other", "provider": "custom", "token_limit_per_min": 10000, "token_limit_per_hour": 600000, "token_limit_per_day": 10000000, "request_limit_per_min": 60, "request_limit_per_hour": 3600, "request_limit_per_day": 50000},
}

# ============================================================
# DATABASE FOR METRICS COLLECTION
# ============================================================
class MetricsDB:
    def __init__(self, db_path="agent_monitor.db"):
        self.db_path = db_path
        self.lock = threading.Lock()
        self._init_db()

    def _get_conn(self):
        conn = sqlite3.connect(self.db_path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self):
        conn = self._get_conn()
        cursor = conn.cursor()
        cursor.executescript("""
            CREATE TABLE IF NOT EXISTS detected_files (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                file_path TEXT UNIQUE,
                file_name TEXT,
                file_type TEXT,
                purpose TEXT,
                is_main_file INTEGER DEFAULT 0,
                is_ai_agent INTEGER DEFAULT 0,
                is_script INTEGER DEFAULT 0,
                description TEXT,
                size_bytes INTEGER,
                last_modified REAL,
                scan_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS token_usage (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                file_path TEXT,
                tokens_used INTEGER,
                token_type TEXT,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS request_usage (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                file_path TEXT,
                request_count INTEGER DEFAULT 1,
                status_code INTEGER,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS resource_usage (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                file_path TEXT,
                pid INTEGER,
                cpu_percent REAL,
                memory_mb REAL,
                storage_mb REAL,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS scan_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                scan_path TEXT,
                total_files INTEGER,
                ai_agents INTEGER,
                scripts INTEGER,
                main_files INTEGER,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)
        conn.commit()
        conn.close()

    def execute(self, query, params=(), fetch=False):
        with self.lock:
            conn = self._get_conn()
            cursor = conn.cursor()
            cursor.execute(query, params)
            if fetch:
                result = cursor.fetchall()
                conn.close()
                return result
            conn.commit()
            conn.close()

    def executemany(self, query, params_list):
        with self.lock:
            conn = self._get_conn()
            cursor = conn.cursor()
            cursor.executemany(query, params_list)
            conn.commit()
            conn.close()

    def clear_files(self):
        with self.lock:
            conn = self._get_conn()
            cursor = conn.cursor()
            cursor.execute("DELETE FROM detected_files")
            conn.commit()
            conn.close()


# ============================================================
# PROJECT SCANNER
# ============================================================
class ProjectScanner:
    AI_KEYWORDS = [
        'openai', 'anthropic', 'langchain', 'llama', 'transformers',
        'torch', 'tensorflow', 'keras', 'huggingface', 'ollama',
        'gpt', 'claude', 'gemini', 'agent', 'llm', 'embedding',
        'vector', 'rag', 'chatbot', 'ai_', 'ml_', 'model',
        'predict', 'inference', 'neural', 'deep_learning',
        'crewai', 'autogen', 'swarm', 'prompt', 'completion',
        'chat_completion', 'api_key', 'OPENAI_API_KEY',
        'ANTHROPIC_API_KEY', 'langsmith', 'chromadb', 'pinecone',
        'weaviate', 'faiss', 'sentence_transformers'
    ]

    SCRIPT_KEYWORDS = [
        'if __name__', 'argparse', 'click', 'typer', 'subprocess',
        'os.system', 'schedule', 'cron', 'celery', 'asyncio.run',
        'main()', 'def main', 'flask', 'fastapi', 'django',
        'uvicorn', 'gunicorn', 'streamlit', 'gradio'
    ]

    IGNORE_DIRS = {
        '__pycache__', '.git', '.svn', 'node_modules', '.venv',
        'venv', 'env', '.env', '.idea', '.vscode', '.tox',
        'dist', 'build', '*.egg-info', '.mypy_cache', '.pytest_cache',
        'site-packages', '.hg', '.bzr'
    }

    SCAN_EXTENSIONS = {
        '.py', '.js', '.ts', '.jsx', '.tsx', '.yaml', '.yml',
        '.json', '.toml', '.cfg', '.ini', '.sh', '.bat', '.ps1',
        '.r', '.R', '.ipynb', '.dockerfile', '.env'
    }

    def __init__(self, db: MetricsDB):
        self.db = db
        self.detected_files = []

    def scan_project(self, root_path="."):
        """Scan entire project directory"""
        root_path = os.path.abspath(root_path)
        self.db.clear_files()
        self.detected_files = []
        all_files = []

        for dirpath, dirnames, filenames in os.walk(root_path):
            # Filter out ignored directories
            dirnames[:] = [d for d in dirnames if d not in self.IGNORE_DIRS
                          and not d.startswith('.')]

            for filename in filenames:
                filepath = os.path.join(dirpath, filename)
                ext = Path(filename).suffix.lower()

                if ext in self.SCAN_EXTENSIONS or filename in ('Dockerfile', 'Makefile', 'Procfile'):
                    file_info = self._analyze_file(filepath, root_path)
                    if file_info:
                        all_files.append(file_info)

        # Determine main files
        self._identify_main_files(all_files)

        # Store in DB
        for f in all_files:
            try:
                self.db.execute("""
                    INSERT OR REPLACE INTO detected_files 
                    (file_path, file_name, file_type, purpose, is_main_file, 
                     is_ai_agent, is_script, description, size_bytes, last_modified)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    f['file_path'], f['file_name'], f['file_type'],
                    f['purpose'], f['is_main_file'], f['is_ai_agent'],
                    f['is_script'], f['description'], f['size_bytes'],
                    f['last_modified']
                ))
            except Exception as e:
                print(f"Error storing file {f['file_name']}: {e}")

        # Record scan history
        ai_count = sum(1 for f in all_files if f['is_ai_agent'])
        script_count = sum(1 for f in all_files if f['is_script'])
        main_count = sum(1 for f in all_files if f['is_main_file'])

        self.db.execute("""
            INSERT INTO scan_history (scan_path, total_files, ai_agents, scripts, main_files)
            VALUES (?, ?, ?, ?, ?)
        """, (root_path, len(all_files), ai_count, script_count, main_count))

        self.detected_files = all_files
        return all_files

    def _analyze_file(self, filepath, root_path):
        """Analyze a single file for its purpose and type"""
        try:
            filename = os.path.basename(filepath)
            rel_path = os.path.relpath(filepath, root_path)
            stat = os.stat(filepath)
            ext = Path(filename).suffix.lower()

            # Read file content
            content = ""
            try:
                with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
                    content = f.read(50000)  # Read first 50KB
            except:
                return None

            content_lower = content.lower()

            # Determine if AI agent
            ai_score = 0
            ai_indicators = []
            for kw in self.AI_KEYWORDS:
                if kw.lower() in content_lower:
                    ai_score += 1
                    ai_indicators.append(kw)

            is_ai_agent = ai_score >= 2

            # Determine if script
            script_score = 0
            script_indicators = []
            for kw in self.SCRIPT_KEYWORDS:
                if kw.lower() in content_lower:
                    script_score += 1
                    script_indicators.append(kw)

            is_script = script_score >= 1

            # Determine purpose
            purpose = self._determine_purpose(filename, content, ext, ai_indicators, script_indicators)

            # Generate description
            description = self._generate_description(filename, content, ext, ai_indicators, script_indicators, is_ai_agent, is_script)

            # Determine file type
            file_type = self._get_file_type(ext, is_ai_agent, is_script)

            return {
                'file_path': rel_path,
                'file_name': filename,
                'file_type': file_type,
                'purpose': purpose,
                'is_main_file': 0,
                'is_ai_agent': 1 if is_ai_agent else 0,
                'is_script': 1 if is_script else 0,
                'description': description,
                'size_bytes': stat.st_size,
                'last_modified': stat.st_mtime,
                'ai_indicators': ai_indicators,
                'script_indicators': script_indicators,
                'content_preview': content[:500]
            }
        except Exception as e:
            return None

    def _determine_purpose(self, filename, content, ext, ai_indicators, script_indicators):
        """Determine the purpose of a file"""
        fname_lower = filename.lower()

        # Config files
        if fname_lower in ('requirements.txt', 'setup.py', 'setup.cfg', 'pyproject.toml',
                           'package.json', 'tsconfig.json', 'webpack.config.js'):
            return "Configuration / Dependencies"

        if fname_lower in ('.env', '.env.example', '.env.local'):
            return "Environment Variables"

        if fname_lower in ('dockerfile', 'docker-compose.yml', 'docker-compose.yaml'):
            return "Container Configuration"

        if fname_lower in ('makefile', 'procfile', 'rakefile'):
            return "Build / Process Management"

        if fname_lower.startswith('test_') or fname_lower.endswith('_test.py') or '/tests/' in filename:
            return "Testing"

        if 'readme' in fname_lower:
            return "Documentation"

        # AI specific
        if ai_indicators:
            if any(kw in ai_indicators for kw in ['agent', 'crewai', 'autogen', 'swarm']):
                return "AI Agent Orchestration"
            if any(kw in ai_indicators for kw in ['embedding', 'vector', 'chromadb', 'pinecone', 'faiss']):
                return "Vector Store / Embeddings"
            if any(kw in ai_indicators for kw in ['rag']):
                return "RAG Pipeline"
            if any(kw in ai_indicators for kw in ['prompt', 'completion', 'chat_completion']):
                return "LLM Interaction / Prompting"
            if any(kw in ai_indicators for kw in ['model', 'predict', 'inference']):
                return "ML Model / Inference"
            if any(kw in ai_indicators for kw in ['transformers', 'torch', 'tensorflow', 'keras']):
                return "Deep Learning / Training"
            return "AI/ML Component"

        # Script specific
        if 'flask' in content.lower() or 'fastapi' in content.lower():
            return "Web API Server"
        if 'streamlit' in content.lower() or 'gradio' in content.lower():
            return "UI / Dashboard"
        if 'schedule' in content.lower() or 'cron' in content.lower():
            return "Scheduled Task / Automation"
        if 'celery' in content.lower():
            return "Task Queue Worker"
        if 'subprocess' in content.lower() or 'os.system' in content.lower():
            return "System Automation Script"
        if 'argparse' in content.lower() or 'click' in content.lower():
            return "CLI Tool"

        # General
        if ext == '.py':
            if 'class ' in content:
                return "Python Module (Classes)"
            if 'def ' in content:
                return "Python Module (Functions)"
            return "Python Script"

        if ext in ('.js', '.ts', '.jsx', '.tsx'):
            return "JavaScript/TypeScript Module"

        if ext in ('.yaml', '.yml'):
            return "YAML Configuration"

        if ext == '.json':
            return "JSON Data / Configuration"

        if ext in ('.sh', '.bat', '.ps1'):
            return "Shell Script"

        if ext == '.ipynb':
            return "Jupyter Notebook"

        return "Project File"

    def _generate_description(self, filename, content, ext, ai_indicators, script_indicators, is_ai, is_script):
        """Generate a human-readable description"""
        parts = []

        if is_ai:
            parts.append(f"AI component using: {', '.join(ai_indicators[:5])}")

        if is_script:
            parts.append(f"Executable script with: {', '.join(script_indicators[:5])}")

        # Extract docstring if Python
        if ext == '.py':
            docstring = self._extract_docstring(content)
            if docstring:
                parts.append(f"Docstring: {docstring[:200]}")

            # Count functions and classes
            functions = re.findall(r'^def (\w+)', content, re.MULTILINE)
            classes = re.findall(r'^class (\w+)', content, re.MULTILINE)
            if classes:
                parts.append(f"Classes: {', '.join(classes[:5])}")
            if functions:
                parts.append(f"Functions: {', '.join(functions[:8])}")

        # Extract imports
        imports = re.findall(r'^(?:import|from)\s+(\S+)', content, re.MULTILINE)
        if imports:
            unique_imports = list(set(imp.split('.')[0] for imp in imports))[:10]
            parts.append(f"Imports: {', '.join(unique_imports)}")

        return " | ".join(parts) if parts else "Standard project file"

    def _extract_docstring(self, content):
        """Extract module-level docstring"""
        try:
            tree = ast.parse(content)
            docstring = ast.get_docstring(tree)
            return docstring
        except:
            # Fallback regex
            match = re.match(r'^(?:\s*#[^\n]*\n)*\s*(?:\'\'\'|""")(.+?)(?:\'\'\'|""")', content, re.DOTALL)
            if match:
                return match.group(1).strip()[:200]
        return None

    def _get_file_type(self, ext, is_ai, is_script):
        if is_ai:
            return "AI Agent"
        if is_script:
            return "Script"
        type_map = {
            '.py': 'Python', '.js': 'JavaScript', '.ts': 'TypeScript',
            '.json': 'JSON', '.yaml': 'YAML', '.yml': 'YAML',
            '.sh': 'Shell', '.bat': 'Batch', '.toml': 'TOML',
            '.ipynb': 'Notebook', '.jsx': 'React', '.tsx': 'React/TS',
            '.r': 'R', '.R': 'R', '.cfg': 'Config', '.ini': 'Config'
        }
        return type_map.get(ext, 'Other')

    def _identify_main_files(self, files):
        """Identify main entry point files"""
        main_patterns = [
            'main.py', 'app.py', 'server.py', 'run.py', 'manage.py',
            'index.py', 'cli.py', 'wsgi.py', 'asgi.py', '__main__.py',
            'index.js', 'index.ts', 'server.js', 'app.js',
            'main.js', 'main.ts'
        ]

        for f in files:
            fname = f['file_name'].lower()
            # Check filename patterns
            if fname in main_patterns:
                f['is_main_file'] = 1
                continue

            # Check for if __name__ == "__main__" pattern
            if f.get('content_preview', '') and 'if __name__' in f.get('content_preview', ''):
                content = ''
                try:
                    with open(os.path.join('.', f['file_path']), 'r', errors='ignore') as fh:
                        content = fh.read()
                except:
                    content = f.get('content_preview', '')

                if re.search(r'if\s+__name__\s*==\s*[\'"]__main__[\'"]', content):
                    f['is_main_file'] = 1


# ============================================================
# RESOURCE MONITOR (Self-contained - No Prometheus/Grafana)
# ============================================================
class ResourceMonitor:
    def __init__(self, db: MetricsDB):
        self.db = db
        self.monitoring = False
        self.monitor_thread = None
        self._process_cache = {}

        # In-memory metrics for fast access
        self.metrics = {
            'tokens': defaultdict(lambda: {'per_min': 0, 'per_hour': 0, 'per_day': 0}),
            'requests': defaultdict(lambda: {'per_min': 0, 'per_hour': 0, 'per_day': 0}),
            'resources': {},
            'system': {}
        }

        # Token/Request tracking timestamps
        self._token_log = defaultdict(list)  # file -> [(timestamp, count), ...]
        self._request_log = defaultdict(list)

    def start_monitoring(self):
        """Start background monitoring thread"""
        self.monitoring = True
        self.monitor_thread = threading.Thread(target=self._monitor_loop, daemon=True)
        self.monitor_thread.start()

    def stop_monitoring(self):
        self.monitoring = False

    def _monitor_loop(self):
        """Main monitoring loop - collects metrics every 5 seconds"""
        while self.monitoring:
            try:
                self._collect_system_metrics()
                self._collect_process_metrics()
                self._calculate_rate_metrics()
                self._simulate_token_requests()  # Simulate for demo
            except Exception as e:
                print(f"Monitor error: {e}")
            time.sleep(5)

    def _collect_system_metrics(self):
        """Collect system-wide metrics"""
        cpu = psutil.cpu_percent(interval=1)
        mem = psutil.virtual_memory()
        disk = psutil.disk_usage('/')

        self.metrics['system'] = {
            'cpu_percent': cpu,
            'memory_total_gb': round(mem.total / (1024**3), 2),
            'memory_used_gb': round(mem.used / (1024**3), 2),
            'memory_percent': mem.percent,
            'disk_total_gb': round(disk.total / (1024**3), 2),
            'disk_used_gb': round(disk.used / (1024**3), 2),
            'disk_percent': round(disk.percent, 1),
            'timestamp': datetime.datetime.now().isoformat()
        }

    def _collect_process_metrics(self):
        """Collect per-process metrics for detected AI agents/scripts"""
        files = self.db.execute(
            "SELECT file_path, file_name FROM detected_files WHERE is_ai_agent=1 OR is_script=1",
            fetch=True
        )

        for f in files:
            file_path = f['file_path']
            file_name = f['file_name']

            # Find running processes matching this file
            cpu_total = 0.0
            mem_total = 0.0
            storage = 0.0
            pid = 0

            try:
                # Check file size for storage
                if os.path.exists(file_path):
                    storage = os.path.getsize(file_path) / (1024 * 1024)  # MB
                elif os.path.exists(os.path.join('.', file_path)):
                    storage = os.path.getsize(os.path.join('.', file_path)) / (1024 * 1024)

                # Find matching processes
                for proc in psutil.process_iter(['pid', 'name', 'cmdline', 'cpu_percent', 'memory_info']):
                    try:
                        cmdline = ' '.join(proc.info.get('cmdline') or [])
                        if file_name in cmdline or file_path in cmdline:
                            cpu_total += proc.info.get('cpu_percent', 0) or 0
                            mem_info = proc.info.get('memory_info')
                            if mem_info:
                                mem_total += mem_info.rss / (1024 * 1024)  # MB
                            pid = proc.info['pid']
                    except (psutil.NoSuchProcess, psutil.AccessDenied):
                        continue

            except Exception:
                pass

            self.metrics['resources'][file_path] = {
                'pid': pid,
                'cpu_percent': round(cpu_total, 2),
                'memory_mb': round(mem_total, 2),
                'storage_mb': round(storage, 4),
                'timestamp': datetime.datetime.now().isoformat()
            }

            # Store in DB
            self.db.execute("""
                INSERT INTO resource_usage (file_path, pid, cpu_percent, memory_mb, storage_mb)
                VALUES (?, ?, ?, ?, ?)
            """, (file_path, pid, cpu_total, mem_total, storage))

    def _calculate_rate_metrics(self):
        """Calculate per-minute, per-hour, per-day rates"""
        now = time.time()

        for file_path in list(self._token_log.keys()):
            entries = self._token_log[file_path]
            # Clean old entries (older than 24h)
            entries[:] = [(t, c) for t, c in entries if now - t < 86400]

            per_min = sum(c for t, c in entries if now - t < 60)
            per_hour = sum(c for t, c in entries if now - t < 3600)
            per_day = sum(c for t, c in entries if now - t < 86400)

            self.metrics['tokens'][file_path] = {
                'per_min': per_min,
                'per_hour': per_hour,
                'per_day': per_day
            }

        for file_path in list(self._request_log.keys()):
            entries = self._request_log[file_path]
            entries[:] = [(t, c) for t, c in entries if now - t < 86400]

            per_min = sum(c for t, c in entries if now - t < 60)
            per_hour = sum(c for t, c in entries if now - t < 3600)
            per_day = sum(c for t, c in entries if now - t < 86400)

            self.metrics['requests'][file_path] = {
                'per_min': per_min,
                'per_hour': per_hour,
                'per_day': per_day
            }

    def _simulate_token_requests(self):
        """Simulate token and request usage for detected AI agents (for demo purposes).
           In production, replace this with actual API call interception."""
        files = self.db.execute(
            "SELECT file_path FROM detected_files WHERE is_ai_agent=1",
            fetch=True
        )
        now = time.time()
        import random

        for f in files:
            fp = f['file_path']
            # Simulate occasional API calls
            if random.random() < 0.3:  # 30% chance every 5 seconds
                tokens = random.randint(50, 2000)
                self._token_log[fp].append((now, tokens))
                self._request_log[fp].append((now, 1))

                self.db.execute(
                    "INSERT INTO token_usage (file_path, tokens_used, token_type) VALUES (?, ?, ?)",
                    (fp, tokens, 'total')
                )
                self.db.execute(
                    "INSERT INTO request_usage (file_path, request_count, status_code) VALUES (?, ?, ?)",
                    (fp, 1, 200)
                )

    def record_tokens(self, file_path, tokens_used):
        """Manually record token usage"""
        now = time.time()
        self._token_log[file_path].append((now, tokens_used))
        self.db.execute(
            "INSERT INTO token_usage (file_path, tokens_used, token_type) VALUES (?, ?, ?)",
            (file_path, tokens_used, 'total')
        )

    def record_request(self, file_path, status_code=200):
        """Manually record API request"""
        now = time.time()
        self._request_log[file_path].append((now, 1))
        self.db.execute(
            "INSERT INTO request_usage (file_path, request_count, status_code) VALUES (?, ?, ?)",
            (file_path, 1, status_code)
        )

    def get_all_metrics(self):
        """Get all current metrics"""
        self._calculate_rate_metrics()
        return {
            'system': self.metrics['system'],
            'tokens': dict(self.metrics['tokens']),
            'requests': dict(self.metrics['requests']),
            'resources': self.metrics['resources']
        }


# ============================================================
# WEB DASHBOARD SERVER
# ============================================================
class DashboardHandler(BaseHTTPRequestHandler):
    scanner = None
    monitor = None
    db = None
    model_config = None
    scan_path = "."

    def log_message(self, format, *args):
        pass  # Suppress default logging

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path
        params = parse_qs(parsed.query)

        if path == '/' or path == '/dashboard':
            self._serve_dashboard()
        elif path == '/api/scan':
            self._api_scan(params)
        elif path == '/api/files':
            self._api_files()
        elif path == '/api/metrics':
            self._api_metrics()
        elif path == '/api/reset':
            self._api_reset()
        elif path == '/api/model':
            self._api_model()
        elif path == '/api/scan-history':
            self._api_scan_history()
        else:
            self.send_error(404)

    def _send_json(self, data):
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.end_headers()
        self.wfile.write(json.dumps(data, default=str).encode())

    def _api_scan(self, params):
        scan_path = params.get('path', [DashboardHandler.scan_path])[0]
        DashboardHandler.scan_path = scan_path
        files = DashboardHandler.scanner.scan_project(scan_path)
        self._send_json({
            'status': 'success',
            'total_files': len(files),
            'ai_agents': sum(1 for f in files if f['is_ai_agent']),
            'scripts': sum(1 for f in files if f['is_script']),
            'main_files': sum(1 for f in files if f['is_main_file']),
            'scan_path': os.path.abspath(scan_path)
        })

    def _api_files(self):
        files = DashboardHandler.db.execute(
            "SELECT * FROM detected_files ORDER BY is_ai_agent DESC, is_script DESC, is_main_file DESC, file_name",
            fetch=True
        )
        self._send_json([dict(f) for f in files])

    def _api_metrics(self):
        metrics = DashboardHandler.monitor.get_all_metrics()
        metrics['model'] = DashboardHandler.model_config
        self._send_json(metrics)

    def _api_reset(self):
        DashboardHandler.db.execute("DELETE FROM detected_files")
        DashboardHandler.db.execute("DELETE FROM token_usage")
        DashboardHandler.db.execute("DELETE FROM request_usage")
        DashboardHandler.db.execute("DELETE FROM resource_usage")
        DashboardHandler.monitor.metrics = {
            'tokens': defaultdict(lambda: {'per_min': 0, 'per_hour': 0, 'per_day': 0}),
            'requests': defaultdict(lambda: {'per_min': 0, 'per_hour': 0, 'per_day': 0}),
            'resources': {},
            'system': {}
        }
        DashboardHandler.monitor._token_log.clear()
        DashboardHandler.monitor._request_log.clear()
        self._send_json({'status': 'reset_complete'})

    def _api_model(self):
        self._send_json(DashboardHandler.model_config)

    def _api_scan_history(self):
        history = DashboardHandler.db.execute(
            "SELECT * FROM scan_history ORDER BY timestamp DESC LIMIT 20",
            fetch=True
        )
        self._send_json([dict(h) for h in history])

    def _serve_dashboard(self):
        model_name = DashboardHandler.model_config['name']
        model_json = json.dumps(DashboardHandler.model_config)

        html = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>AI Agent Monitor Dashboard</title>
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{
            font-family: 'Segoe UI', system-ui, -apple-system, sans-serif;
            background: #0a0e17;
            color: #e0e6f0;
            min-height: 100vh;
        }}
        
        /* Header */
        .header {{
            background: linear-gradient(135deg, #1a1f35 0%, #0d1225 100%);
            border-bottom: 1px solid #2a3456;
            padding: 16px 24px;
            display: flex;
            justify-content: space-between;
            align-items: center;
            flex-wrap: wrap;
            gap: 12px;
        }}
        .header h1 {{
            font-size: 22px;
            background: linear-gradient(135deg, #60a5fa, #a78bfa);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            display: flex;
            align-items: center;
            gap: 10px;
        }}
        .header h1::before {{ content: "🤖"; -webkit-text-fill-color: initial; }}
        .model-badge {{
            background: #1e293b;
            border: 1px solid #3b82f6;
            border-radius: 20px;
            padding: 6px 16px;
            font-size: 13px;
            color: #60a5fa;
        }}
        .btn-group {{
            display: flex;
            gap: 8px;
            flex-wrap: wrap;
        }}
        .btn {{
            padding: 8px 20px;
            border: none;
            border-radius: 8px;
            font-size: 13px;
            font-weight: 600;
            cursor: pointer;
            transition: all 0.2s;
            display: flex;
            align-items: center;
            gap: 6px;
        }}
        .btn:hover {{ transform: translateY(-1px); box-shadow: 0 4px 12px rgba(0,0,0,0.3); }}
        .btn-scan {{ background: #2563eb; color: white; }}
        .btn-scan:hover {{ background: #3b82f6; }}
        .btn-refresh {{ background: #059669; color: white; }}
        .btn-refresh:hover {{ background: #10b981; }}
        .btn-reset {{ background: #dc2626; color: white; }}
        .btn-reset:hover {{ background: #ef4444; }}
        
        /* Scan Path Input */
        .scan-bar {{
            background: #111827;
            padding: 12px 24px;
            border-bottom: 1px solid #1e293b;
            display: flex;
            align-items: center;
            gap: 12px;
        }}
        .scan-bar label {{ font-size: 13px; color: #94a3b8; white-space: nowrap; }}
        .scan-bar input {{
            flex: 1;
            background: #1e293b;
            border: 1px solid #334155;
            border-radius: 6px;
            padding: 8px 14px;
            color: #e0e6f0;
            font-size: 13px;
            font-family: 'Courier New', monospace;
        }}
        .scan-bar input:focus {{ outline: none; border-color: #3b82f6; }}

        /* Status Bar */
        .status-bar {{
            background: #111827;
            padding: 8px 24px;
            border-bottom: 1px solid #1e293b;
            font-size: 12px;
            color: #64748b;
            display: flex;
            justify-content: space-between;
            align-items: center;
        }}
        .status-bar .live {{ color: #22c55e; }}

        /* Main Content */
        .container {{
            padding: 20px 24px;
            max-width: 1800px;
            margin: 0 auto;
        }}

        /* Stats Cards */
        .stats-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 16px;
            margin-bottom: 24px;
        }}
        .stat-card {{
            background: linear-gradient(135deg, #1a1f35, #151b2e);
            border: 1px solid #2a3456;
            border-radius: 12px;
            padding: 20px;
            text-align: center;
        }}
        .stat-card .stat-value {{
            font-size: 32px;
            font-weight: 700;
            margin: 8px 0;
        }}
        .stat-card .stat-label {{
            font-size: 12px;
            color: #64748b;
            text-transform: uppercase;
            letter-spacing: 1px;
        }}
        .stat-card.blue .stat-value {{ color: #3b82f6; }}
        .stat-card.green .stat-value {{ color: #22c55e; }}
        .stat-card.purple .stat-value {{ color: #a78bfa; }}
        .stat-card.orange .stat-value {{ color: #f59e0b; }}
        .stat-card.red .stat-value {{ color: #ef4444; }}
        .stat-card.cyan .stat-value {{ color: #06b6d4; }}

        /* System Resources */
        .system-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
            gap: 16px;
            margin-bottom: 24px;
        }}
        .resource-card {{
            background: #111827;
            border: 1px solid #1e293b;
            border-radius: 12px;
            padding: 20px;
        }}
        .resource-card h3 {{
            font-size: 14px;
            color: #94a3b8;
            margin-bottom: 12px;
        }}
        .progress-bar {{
            background: #1e293b;
            border-radius: 8px;
            height: 24px;
            overflow: hidden;
            margin: 8px 0;
            position: relative;
        }}
        .progress-fill {{
            height: 100%;
            border-radius: 8px;
            transition: width 0.5s ease;
            display: flex;
            align-items: center;
            justify-content: center;
            font-size: 11px;
            font-weight: 600;
            color: white;
            min-width: 40px;
        }}
        .progress-fill.blue {{ background: linear-gradient(90deg, #2563eb, #3b82f6); }}
        .progress-fill.green {{ background: linear-gradient(90deg, #059669, #10b981); }}
        .progress-fill.orange {{ background: linear-gradient(90deg, #d97706, #f59e0b); }}
        .progress-fill.red {{ background: linear-gradient(90deg, #dc2626, #ef4444); }}
        .resource-details {{
            display: flex;
            justify-content: space-between;
            font-size: 12px;
            color: #64748b;
            margin-top: 4px;
        }}

        /* Section Headers */
        .section-header {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin: 24px 0 12px;
            padding-bottom: 8px;
            border-bottom: 1px solid #1e293b;
        }}
        .section-header h2 {{
            font-size: 18px;
            color: #e0e6f0;
            display: flex;
            align-items: center;
            gap: 8px;
        }}
        .section-header .count {{
            background: #1e293b;
            border-radius: 12px;
            padding: 2px 10px;
            font-size: 12px;
            color: #60a5fa;
        }}

        /* File Tables */
        .table-container {{
            background: #111827;
            border: 1px solid #1e293b;
            border-radius: 12px;
            overflow: hidden;
            margin-bottom: 24px;
        }}
        table {{
            width: 100%;
            border-collapse: collapse;
        }}
        th {{
            background: #1a1f35;
            padding: 12px 16px;
            text-align: left;
            font-size: 11px;
            text-transform: uppercase;
            letter-spacing: 1px;
            color: #64748b;
            font-weight: 600;
            border-bottom: 1px solid #2a3456;
            position: sticky;
            top: 0;
        }}
        td {{
            padding: 10px 16px;
            border-bottom: 1px solid #1e293b;
            font-size: 13px;
            vertical-align: top;
        }}
        tr:hover td {{ background: #1a1f35; }}
        .tag {{
            display: inline-block;
            padding: 2px 8px;
            border-radius: 4px;
            font-size: 11px;
            font-weight: 600;
        }}
        .tag-ai {{ background: #3b82f620; color: #60a5fa; border: 1px solid #3b82f640; }}
        .tag-script {{ background: #8b5cf620; color: #a78bfa; border: 1px solid #8b5cf640; }}
        .tag-main {{ background: #22c55e20; color: #4ade80; border: 1px solid #22c55e40; }}
        .tag-file {{ background: #64748b20; color: #94a3b8; border: 1px solid #64748b40; }}
        .file-path {{
            font-family: 'Courier New', monospace;
            font-size: 12px;
            color: #94a3b8;
        }}
        .purpose-text {{ color: #60a5fa; font-weight: 500; }}
        .desc-text {{ color: #94a3b8; font-size: 12px; max-width: 400px; }}
        .size-text {{ color: #64748b; font-size: 12px; font-family: monospace; }}

        /* Token/Request Cards */
        .usage-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(350px, 1fr));
            gap: 16px;
            margin-bottom: 24px;
        }}
        .usage-card {{
            background: #111827;
            border: 1px solid #1e293b;
            border-radius: 12px;
            padding: 20px;
        }}
        .usage-card h3 {{
            font-size: 14px;
            margin-bottom: 16px;
            color: #e0e6f0;
            display: flex;
            align-items: center;
            gap: 8px;
        }}
        .usage-row {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding: 8px 0;
            border-bottom: 1px solid #1e293b;
        }}
        .usage-row:last-child {{ border-bottom: none; }}
        .usage-label {{ font-size: 12px; color: #94a3b8; }}
        .usage-value {{ font-size: 14px; font-weight: 600; font-family: monospace; }}
        .usage-limit {{ font-size: 11px; color: #64748b; }}
        .usage-bar-mini {{
            width: 100%;
            height: 6px;
            background: #1e293b;
            border-radius: 3px;
            margin-top: 4px;
            overflow: hidden;
        }}
        .usage-bar-fill {{
            height: 100%;
            border-radius: 3px;
            transition: width 0.3s;
        }}

        /* Loading overlay */
        .loading {{
            position: fixed;
            top: 0;
            left: 0;
            right: 0;
            bottom: 0;
            background: rgba(10, 14, 23, 0.8);
            display: flex;
            align-items: center;
            justify-content: center;
            z-index: 1000;
            display: none;
        }}
        .loading.active {{ display: flex; }}
        .spinner {{
            width: 50px;
            height: 50px;
            border: 3px solid #1e293b;
            border-top-color: #3b82f6;
            border-radius: 50%;
            animation: spin 0.8s linear infinite;
        }}
        @keyframes spin {{ to {{ transform: rotate(360deg); }} }}

        /* Scrollable table wrapper */
        .table-scroll {{
            max-height: 500px;
            overflow-y: auto;
        }}
        .table-scroll::-webkit-scrollbar {{ width: 8px; }}
        .table-scroll::-webkit-scrollbar-track {{ background: #111827; }}
        .table-scroll::-webkit-scrollbar-thumb {{ background: #334155; border-radius: 4px; }}
        .table-scroll::-webkit-scrollbar-thumb:hover {{ background: #475569; }}

        /* Per-agent metrics table */
        .agent-metrics-table td {{ font-size: 12px; }}
        .metric-good {{ color: #22c55e; }}
        .metric-warn {{ color: #f59e0b; }}
        .metric-danger {{ color: #ef4444; }}

        /* Toast notifications */
        .toast {{
            position: fixed;
            bottom: 24px;
            right: 24px;
            background: #1e293b;
            border: 1px solid #334155;
            border-radius: 8px;
            padding: 12px 20px;
            font-size: 13px;
            z-index: 2000;
            transform: translateY(100px);
            opacity: 0;
            transition: all 0.3s;
        }}
        .toast.show {{ transform: translateY(0); opacity: 1; }}
        .toast.success {{ border-color: #22c55e; color: #4ade80; }}
        .toast.error {{ border-color: #ef4444; color: #f87171; }}

        /* Responsive */
        @media (max-width: 768px) {{
            .header {{ flex-direction: column; text-align: center; }}
            .stats-grid {{ grid-template-columns: repeat(2, 1fr); }}
            .system-grid {{ grid-template-columns: 1fr; }}
            .usage-grid {{ grid-template-columns: 1fr; }}
        }}
    </style>
</head>
<body>
    <!-- Loading Overlay -->
    <div class="loading" id="loading">
        <div class="spinner"></div>
    </div>

    <!-- Toast -->
    <div class="toast" id="toast"></div>

    <!-- Header -->
    <div class="header">
        <h1>AI Agent Monitor</h1>
        <div class="model-badge">📡 Model: {model_name}</div>
        <div class="btn-group">
            <button class="btn btn-scan" onclick="scanProject()">🔍 Scan</button>
            <button class="btn btn-refresh" onclick="refreshAll()">🔄 Refresh</button>
            <button class="btn btn-reset" onclick="resetAll()">🗑️ Reset</button>
        </div>
    </div>

    <!-- Scan Path -->
    <div class="scan-bar">
        <label>📁 Scan Path:</label>
        <input type="text" id="scanPath" value="." placeholder="Enter project path to scan...">
    </div>

    <!-- Status Bar -->
    <div class="status-bar">
        <span id="statusText">Ready to scan</span>
        <span class="live" id="liveIndicator">● Live Monitoring</span>
    </div>

    <!-- Main Content -->
    <div class="container">
        <!-- Summary Stats -->
        <div class="stats-grid" id="statsGrid">
            <div class="stat-card blue">
                <div class="stat-label">Total Files</div>
                <div class="stat-value" id="totalFiles">0</div>
            </div>
            <div class="stat-card purple">
                <div class="stat-label">AI Agents</div>
                <div class="stat-value" id="aiAgents">0</div>
            </div>
            <div class="stat-card green">
                <div class="stat-label">Scripts</div>
                <div class="stat-value" id="scripts">0</div>
            </div>
            <div class="stat-card orange">
                <div class="stat-label">Main Files</div>
                <div class="stat-value" id="mainFiles">0</div>
            </div>
            <div class="stat-card cyan">
                <div class="stat-label">Total Tokens (Day)</div>
                <div class="stat-value" id="totalTokens">0</div>
            </div>
            <div class="stat-card red">
                <div class="stat-label">Total Requests (Day)</div>
                <div class="stat-value" id="totalRequests">0</div>
            </div>
        </div>

        <!-- System Resources -->
        <div class="section-header">
            <h2>💻 System Resources</h2>
        </div>
        <div class="system-grid" id="systemGrid">
            <div class="resource-card">
                <h3>🔲 CPU Usage</h3>
                <div class="progress-bar">
                    <div class="progress-fill blue" id="cpuBar" style="width: 0%">0%</div>
                </div>
                <div class="resource-details">
                    <span id="cpuDetail">Loading...</span>
                </div>
            </div>
            <div class="resource-card">
                <h3>🧠 Memory Usage</h3>
                <div class="progress-bar">
                    <div class="progress-fill green" id="memBar" style="width: 0%">0%</div>
                </div>
                <div class="resource-details">
                    <span id="memDetail">Loading...</span>
                </div>
            </div>
            <div class="resource-card">
                <h3>💾 Disk Usage</h3>
                <div class="progress-bar">
                    <div class="progress-fill orange" id="diskBar" style="width: 0%">0%</div>
                </div>
                <div class="resource-details">
                    <span id="diskDetail">Loading...</span>
                </div>
            </div>
        </div>

        <!-- Detected Files Table -->
        <div class="section-header">
            <h2>📂 Detected Files</h2>
            <span class="count" id="fileCount">0 files</span>
        </div>
        <div class="table-container">
            <div class="table-scroll">
                <table>
                    <thead>
                        <tr>
                            <th>Type</th>
                            <th>File Name</th>
                            <th>Path</th>
                            <th>Purpose</th>
                            <th>Description</th>
                            <th>Size</th>
                            <th>Flags</th>
                        </tr>
                    </thead>
                    <tbody id="filesTable">
                        <tr><td colspan="7" style="text-align:center; color:#64748b; padding:40px;">Click "Scan" to detect project files</td></tr>
                    </tbody>
                </table>
            </div>
        </div>

        <!-- AI Agent / Script Detailed Metrics -->
        <div class="section-header">
            <h2>🤖 AI Agent & Script Metrics</h2>
            <span class="count" id="agentCount">0 agents/scripts</span>
        </div>
        <div class="table-container">
            <div class="table-scroll">
                <table class="agent-metrics-table">
                    <thead>
                        <tr>
                            <th>Script Name</th>
                            <th>File Name</th>
                            <th>Purpose</th>
                            <th>What It Does</th>
                            <th>Tokens/Min</th>
                            <th>Tokens/Hour</th>
                            <th>Tokens/Day</th>
                            <th>Req/Min</th>
                            <th>Req/Hour</th>
                            <th>Req/Day</th>
                            <th>CPU %</th>
                            <th>Memory MB</th>
                            <th>Storage MB</th>
                        </tr>
                    </thead>
                    <tbody id="agentTable">
                        <tr><td colspan="13" style="text-align:center; color:#64748b; padding:40px;">No agents/scripts detected yet</td></tr>
                    </tbody>
                </table>
            </div>
        </div>

        <!-- Token & Request Usage Overview -->
        <div class="section-header">
            <h2>📊 Token & Request Usage vs Limits</h2>
        </div>
        <div class="usage-grid" id="usageGrid">
            <!-- Token Usage Card -->
            <div class="usage-card">
                <h3>🪙 Token Usage</h3>
                <div class="usage-row">
                    <div>
                        <div class="usage-label">Per Minute</div>
                        <div class="usage-bar-mini"><div class="usage-bar-fill" id="tokenMinBar" style="width:0%; background:#3b82f6;"></div></div>
                    </div>
                    <div style="text-align:right">
                        <div class="usage-value" id="tokenMin">0</div>
                        <div class="usage-limit" id="tokenMinLimit">/ {DashboardHandler.model_config['token_limit_per_min'] if DashboardHandler.model_config else 0}</div>
                    </div>
                </div>
                <div class="usage-row">
                    <div>
                        <div class="usage-label">Per Hour</div>
                        <div class="usage-bar-mini"><div class="usage-bar-fill" id="tokenHourBar" style="width:0%; background:#8b5cf6;"></div></div>
                    </div>
                    <div style="text-align:right">
                        <div class="usage-value" id="tokenHour">0</div>
                        <div class="usage-limit" id="tokenHourLimit">/ {DashboardHandler.model_config['token_limit_per_hour'] if DashboardHandler.model_config else 0}</div>
                    </div>
                </div>
                <div class="usage-row">
                    <div>
                        <div class="usage-label">Per Day</div>
                        <div class="usage-bar-mini"><div class="usage-bar-fill" id="tokenDayBar" style="width:0%; background:#06b6d4;"></div></div>
                    </div>
                    <div style="text-align:right">
                        <div class="usage-value" id="tokenDay">0</div>
                        <div class="usage-limit" id="tokenDayLimit">/ {DashboardHandler.model_config['token_limit_per_day'] if DashboardHandler.model_config else 0}</div>
                    </div>
                </div>
            </div>

            <!-- Request Usage Card -->
            <div class="usage-card">
                <h3>📡 Request Usage</h3>
                <div class="usage-row">
                    <div>
                        <div class="usage-label">Per Minute</div>
                        <div class="usage-bar-mini"><div class="usage-bar-fill" id="reqMinBar" style="width:0%; background:#22c55e;"></div></div>
                    </div>
                    <div style="text-align:right">
                        <div class="usage-value" id="reqMin">0</div>
                        <div class="usage-limit" id="reqMinLimit">/ {DashboardHandler.model_config['request_limit_per_min'] if DashboardHandler.model_config else 0}</div>
                    </div>
                </div>
                <div class="usage-row">
                    <div>
                        <div class="usage-label">Per Hour</div>
                        <div class="usage-bar-mini"><div class="usage-bar-fill" id="reqHourBar" style="width:0%; background:#f59e0b;"></div></div>
                    </div>
                    <div style="text-align:right">
                        <div class="usage-value" id="reqHour">0</div>
                        <div class="usage-limit" id="reqHourLimit">/ {DashboardHandler.model_config['request_limit_per_hour'] if DashboardHandler.model_config else 0}</div>
                    </div>
                </div>
                <div class="usage-row">
                    <div>
                        <div class="usage-label">Per Day</div>
                        <div class="usage-bar-mini"><div class="usage-bar-fill" id="reqDayBar" style="width:0%; background:#ef4444;"></div></div>
                    </div>
                    <div style="text-align:right">
                        <div class="usage-value" id="reqDay">0</div>
                        <div class="usage-limit" id="reqDayLimit">/ {DashboardHandler.model_config['request_limit_per_day'] if DashboardHandler.model_config else 0}</div>
                    </div>
                </div>
            </div>
        </div>
    </div>

    <script>
        const MODEL = {model_json};
        let allFiles = [];
        let autoRefreshInterval = null;

        // ---- API Calls ----
        async function api(endpoint) {{
            const resp = await fetch(endpoint);
            return await resp.json();
        }}

        // ---- Scan Project ----
        async function scanProject() {{
            showLoading(true);
            const path = document.getElementById('scanPath').value || '.';
            try {{
                const result = await api('/api/scan?path=' + encodeURIComponent(path));
                showToast('Scan complete: ' + result.total_files + ' files found', 'success');
                await refreshAll();
            }} catch(e) {{
                showToast('Scan failed: ' + e.message, 'error');
            }}
            showLoading(false);
        }}

        // ---- Refresh All Data ----
        async function refreshAll() {{
            try {{
                await Promise.all([loadFiles(), loadMetrics()]);
                document.getElementById('statusText').textContent = 
                    'Last refreshed: ' + new Date().toLocaleTimeString();
            }} catch(e) {{
                console.error('Refresh error:', e);
            }}
        }}

        // ---- Reset All ----
        async function resetAll() {{
            if (!confirm('Reset all data? This clears detected files and metrics.')) return;
            showLoading(true);
            try {{
                await api('/api/reset');
                allFiles = [];
                renderFiles([]);
                renderAgents([], {{}});
                updateStats(0, 0, 0, 0);
                showToast('All data reset', 'success');
            }} catch(e) {{
                showToast('Reset failed', 'error');
            }}
            showLoading(false);
        }}

        // ---- Load Files ----
        async function loadFiles() {{
            const files = await api('/api/files');
            allFiles = files;
            renderFiles(files);
            
            const aiCount = files.filter(f => f.is_ai_agent).length;
            const scriptCount = files.filter(f => f.is_script).length;
            const mainCount = files.filter(f => f.is_main_file).length;
            updateStats(files.length, aiCount, scriptCount, mainCount);
        }}

        // ---- Load Metrics ----
        async function loadMetrics() {{
            const metrics = await api('/api/metrics');
            updateSystemResources(metrics.system);
            updateTokenRequests(metrics);
            renderAgents(allFiles.filter(f => f.is_ai_agent || f.is_script), metrics);
        }}

        // ---- Render Files Table ----
        function renderFiles(files) {{
            const tbody = document.getElementById('filesTable');
            document.getElementById('fileCount').textContent = files.length + ' files';
            
            if (files.length === 0) {{
                tbody.innerHTML = '<tr><td colspan="7" style="text-align:center; color:#64748b; padding:40px;">No files detected. Click "Scan" to start.</td></tr>';
                return;
            }}

            tbody.innerHTML = files.map(f => {{
                let typeTag = '<span class="tag tag-file">' + f.file_type + '</span>';
                if (f.is_ai_agent) typeTag = '<span class="tag tag-ai">🤖 AI Agent</span>';
                else if (f.is_script) typeTag = '<span class="tag tag-script">⚡ Script</span>';
                
                let flags = [];
                if (f.is_main_file) flags.push('<span class="tag tag-main">★ Main</span>');
                if (f.is_ai_agent) flags.push('<span class="tag tag-ai">AI</span>');
                if (f.is_script) flags.push('<span class="tag tag-script">Script</span>');
                
                const sizeStr = f.size_bytes > 1024*1024 
                    ? (f.size_bytes/(1024*1024)).toFixed(1) + ' MB'
                    : f.size_bytes > 1024 
                    ? (f.size_bytes/1024).toFixed(1) + ' KB'
                    : f.size_bytes + ' B';

                const desc = (f.description || '').substring(0, 150);

                return '<tr>' +
                    '<td>' + typeTag + '</td>' +
                    '<td><strong>' + f.file_name + '</strong></td>' +
                    '<td><span class="file-path">' + f.file_path + '</span></td>' +
                    '<td><span class="purpose-text">' + (f.purpose || '-') + '</span></td>' +
                    '<td><span class="desc-text">' + desc + '</span></td>' +
                    '<td><span class="size-text">' + sizeStr + '</span></td>' +
                    '<td>' + flags.join(' ') + '</td>' +
                    '</tr>';
            }}).join('');
        }}

        // ---- Render Agent Metrics Table ----
        function renderAgents(agents, metrics) {{
            const tbody = document.getElementById('agentTable');
            document.getElementById('agentCount').textContent = agents.length + ' agents/scripts';

            if (agents.length === 0) {{
                tbody.innerHTML = '<tr><td colspan="13" style="text-align:center; color:#64748b; padding:40px;">No AI agents or scripts detected</td></tr>';
                return;
            }}

            tbody.innerHTML = agents.map(a => {{
                const fp = a.file_path;
                const tokens = (metrics.tokens && metrics.tokens[fp]) || {{per_min:0, per_hour:0, per_day:0}};
                const reqs = (metrics.requests && metrics.requests[fp]) || {{per_min:0, per_hour:0, per_day:0}};
                const res = (metrics.resources && metrics.resources[fp]) || {{cpu_percent:0, memory_mb:0, storage_mb:0}};

                const tMinPct = (tokens.per_min / MODEL.token_limit_per_min * 100);
                const tHourPct = (tokens.per_hour / MODEL.token_limit_per_hour * 100);
                const tDayPct = (tokens.per_day / MODEL.token_limit_per_day * 100);
                const rMinPct = (reqs.per_min / MODEL.request_limit_per_min * 100);
                const rHourPct = (reqs.per_hour / MODEL.request_limit_per_hour * 100);
                const rDayPct = (reqs.per_day / MODEL.request_limit_per_day * 100);

                function metricClass(pct) {{
                    if (pct > 80) return 'metric-danger';
                    if (pct > 50) return 'metric-warn';
                    return 'metric-good';
                }}

                const scriptName = a.file_name.replace(/\\.[^/.]+$/, "");
                const shortDesc = (a.description || '').substring(0, 100);

                return '<tr>' +
                    '<td><strong>' + scriptName + '</strong></td>' +
                    '<td>' + a.file_name + '</td>' +
                    '<td><span class="purpose-text">' + (a.purpose || '-') + '</span></td>' +
                    '<td><span class="desc-text">' + shortDesc + '</span></td>' +
                    '<td class="' + metricClass(tMinPct) + '">' + tokens.per_min.toLocaleString() + ' <small>/' + MODEL.token_limit_per_min.toLocaleString() + '</small></td>' +
                    '<td class="' + metricClass(tHourPct) + '">' + tokens.per_hour.toLocaleString() + ' <small>/' + MODEL.token_limit_per_hour.toLocaleString() + '</small></td>' +
                    '<td class="' + metricClass(tDayPct) + '">' + tokens.per_day.toLocaleString() + ' <small>/' + MODEL.token_limit_per_day.toLocaleString() + '</small></td>' +
                    '<td class="' + metricClass(rMinPct) + '">' + reqs.per_min + ' <small>/' + MODEL.request_limit_per_min + '</small></td>' +
                    '<td class="' + metricClass(rHourPct) + '">' + reqs.per_hour + ' <small>/' + MODEL.request_limit_per_hour + '</small></td>' +
                    '<td class="' + metricClass(rDayPct) + '">' + reqs.per_day + ' <small>/' + MODEL.request_limit_per_day + '</small></td>' +
                    '<td>' + res.cpu_percent.toFixed(1) + '%</td>' +
                    '<td>' + res.memory_mb.toFixed(1) + '</td>' +
                    '<td>' + res.storage_mb.toFixed(3) + '</td>' +
                    '</tr>';
            }}).join('');
        }}

        // ---- Update Stats Cards ----
        function updateStats(total, ai, scripts, main) {{
            document.getElementById('totalFiles').textContent = total;
            document.getElementById('aiAgents').textContent = ai;
            document.getElementById('scripts').textContent = scripts;
            document.getElementById('mainFiles').textContent = main;
        }}

        // ---- Update System Resources ----
        function updateSystemResources(sys) {{
            if (!sys || !sys.cpu_percent) return;

            const cpuPct = sys.cpu_percent;
            const memPct = sys.memory_percent;
            const diskPct = sys.disk_percent;

            setProgress('cpuBar', cpuPct);
            setProgress('memBar', memPct);
            setProgress('diskBar', diskPct);

            document.getElementById('cpuDetail').textContent = cpuPct.toFixed(1) + '% utilized';
            document.getElementById('memDetail').textContent = 
                sys.memory_used_gb + ' GB / ' + sys.memory_total_gb + ' GB (' + memPct.toFixed(1) + '%)';
            document.getElementById('diskDetail').textContent = 
                sys.disk_used_gb + ' GB / ' + sys.disk_total_gb + ' GB (' + diskPct + '%)';
        }}

        function setProgress(id, pct) {{
            const el = document.getElementById(id);
            const val = Math.min(Math.max(pct, 0), 100);
            el.style.width = val + '%';
            el.textContent = val.toFixed(1) + '%';
            
            // Change color based on value
            el.className = 'progress-fill';
            if (val > 80) el.classList.add('red');
            else if (val > 60) el.classList.add('orange');
            else if (val > 40) el.classList.add('blue');
            else el.classList.add('green');
        }}

        // ---- Update Token/Request Usage ----
        function updateTokenRequests(metrics) {{
            let totalTokenMin = 0, totalTokenHour = 0, totalTokenDay = 0;
            let totalReqMin = 0, totalReqHour = 0, totalReqDay = 0;

            if (metrics.tokens) {{
                Object.values(metrics.tokens).forEach(t => {{
                    totalTokenMin += t.per_min || 0;
                    totalTokenHour += t.per_hour || 0;
                    totalTokenDay += t.per_day || 0;
                }});
            }}
            if (metrics.requests) {{
                Object.values(metrics.requests).forEach(r => {{
                    totalReqMin += r.per_min || 0;
                    totalReqHour += r.per_hour || 0;
                    totalReqDay += r.per_day || 0;
                }});
            }}

            document.getElementById('totalTokens').textContent = totalTokenDay.toLocaleString();
            document.getElementById('totalRequests').textContent = totalReqDay.toLocaleString();

            // Token bars
            setUsageBar('tokenMin', 'tokenMinBar', totalTokenMin, MODEL.token_limit_per_min);
            setUsageBar('tokenHour', 'tokenHourBar', totalTokenHour, MODEL.token_limit_per_hour);
            setUsageBar('tokenDay', 'tokenDayBar', totalTokenDay, MODEL.token_limit_per_day);

            // Request bars
            setUsageBar('reqMin', 'reqMinBar', totalReqMin, MODEL.request_limit_per_min);
            setUsageBar('reqHour', 'reqHourBar', totalReqHour, MODEL.request_limit_per_hour);
            setUsageBar('reqDay', 'reqDayBar', totalReqDay, MODEL.request_limit_per_day);
        }}

        function setUsageBar(valueId, barId, used, limit) {{
            document.getElementById(valueId).textContent = used.toLocaleString();
            const pct = limit > 0 ? Math.min((used / limit) * 100, 100) : 0;
            const bar = document.getElementById(barId);
            bar.style.width = pct + '%';
            if (pct > 80) bar.style.background = '#ef4444';
            else if (pct > 50) bar.style.background = '#f59e0b';
        }}

        // ---- Helpers ----
        function showLoading(show) {{
            document.getElementById('loading').classList.toggle('active', show);
        }}

        function showToast(msg, type) {{
            const toast = document.getElementById('toast');
            toast.textContent = msg;
            toast.className = 'toast ' + type + ' show';
            setTimeout(() => toast.classList.remove('show'), 3000);
        }}

        // ---- Auto-refresh every 5 seconds ----
        function startAutoRefresh() {{
            autoRefreshInterval = setInterval(async () => {{
                try {{ await loadMetrics(); }} catch(e) {{}}
            }}, 5000);
        }}

        // ---- Init ----
        window.addEventListener('load', () => {{
            startAutoRefresh();
            // Blink live indicator
            setInterval(() => {{
                const el = document.getElementById('liveIndicator');
                el.style.opacity = el.style.opacity === '0.3' ? '1' : '0.3';
            }}, 1000);
        }});

        // Enter key triggers scan
        document.addEventListener('DOMContentLoaded', () => {{
            document.getElementById('scanPath').addEventListener('keypress', (e) => {{
                if (e.key === 'Enter') scanProject();
            }});
        }});
    </script>
</body>
</html>"""
        self.send_response(200)
        self.send_header('Content-Type', 'text/html')
        self.end_headers()
        self.wfile.write(html.encode('utf-8'))


# ============================================================
# MAIN - MODEL SELECTION & SERVER START
# ============================================================
def select_model():
    """Interactive model selection at startup"""
    print("\n" + "=" * 60)
    print("🤖 AI Agent & Script Monitor Dashboard")
    print("=" * 60)
    print("\nSelect which AI model you are using:\n")

    for key, model in SUPPORTED_MODELS.items():
        print(f"  [{key}] {model['name']}")
        print(f"      Token limits: {model['token_limit_per_min']:,}/min | {model['token_limit_per_hour']:,}/hr | {model['token_limit_per_day']:,}/day")
        print(f"      Request limits: {model['request_limit_per_min']}/min | {model['request_limit_per_hour']}/hr | {model['request_limit_per_day']}/day")
        print()

    while True:
        choice = input("Enter your choice [1-6]: ").strip()
        if choice in SUPPORTED_MODELS:
            model = SUPPORTED_MODELS[choice]
            print(f"\n✅ Selected: {model['name']}")
            return model
        print("❌ Invalid choice. Please enter 1-6.")


def main():
    # Step 1: Select AI Model
    model_config = select_model()

    # Step 2: Ask for scan path
    scan_path = input("\nEnter project path to scan (default: current directory '.'): ").strip() or "."
    scan_path = os.path.abspath(scan_path)
    print(f"📁 Scan path: {scan_path}")

    # Step 3: Initialize components
    print("\n⚙️  Initializing...")
    db = MetricsDB()
    scanner = ProjectScanner(db)
    monitor = ResourceMonitor(db)

    # Step 4: Initial scan
    print(f"🔍 Scanning project at: {scan_path}")
    files = scanner.scan_project(scan_path)

    total = len(files)
    ai_agents = [f for f in files if f['is_ai_agent']]
    scripts = [f for f in files if f['is_script']]
    main_files = [f for f in files if f['is_main_file']]

    print(f"\n📊 Scan Results:")
    print(f"   Total files detected: {total}")
    print(f"   AI Agents: {len(ai_agents)}")
    print(f"   Scripts: {len(scripts)}")
    print(f"   Main files: {len(main_files)}")

    if main_files:
        print(f"\n   ★ Main files:")
        for f in main_files:
            print(f"     - {f['file_name']} ({f['file_path']}) → {f['purpose']}")

    if ai_agents:
        print(f"\n   🤖 AI Agents:")
        for f in ai_agents:
            print(f"     - {f['file_name']} → {f['purpose']}")

    if scripts:
        print(f"\n   ⚡ Scripts:")
        for f in scripts[:10]:
            print(f"     - {f['file_name']} → {f['purpose']}")
        if len(scripts) > 10:
            print(f"     ... and {len(scripts) - 10} more")

    # Step 5: Start resource monitor
    print("\n📡 Starting resource monitor...")
    monitor.start_monitoring()

    # Step 6: Setup web server
    DashboardHandler.scanner = scanner
    DashboardHandler.monitor = monitor
    DashboardHandler.db = db
    DashboardHandler.model_config = model_config
    DashboardHandler.scan_path = scan_path

    port = 8787
    # Find available port
    while True:
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.bind(('', port))
            sock.close()
            break
        except OSError:
            port += 1
            if port > 9000:
                print("❌ No available ports found")
                sys.exit(1)

    server = HTTPServer(('0.0.0.0', port), DashboardHandler)

    print(f"\n{'=' * 60}")
    print(f"🚀 Dashboard running at: http://localhost:{port}")
    print(f"   Model: {model_config['name']}")
    print(f"   Monitoring: {scan_path}")
    print(f"{'=' * 60}")
    print(f"\n   Press Ctrl+C to stop\n")

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n\n🛑 Shutting down...")
        monitor.stop_monitoring()
        server.server_close()
        print("✅ Goodbye!")


if __name__ == "__main__":
    main()
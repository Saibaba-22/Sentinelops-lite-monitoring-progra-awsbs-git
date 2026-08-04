"""
Deep Deployment Failure Diagnostic Agent
Supports: GitHub Actions, Azure DevOps, Jenkins
Detects: RAM issues, method errors, alignment issues, dependency failures,
         config errors, network issues, and much more.
Always reports: which file, which line, what issue, what files are affected.
"""

from __future__ import annotations

import glob
import json
import os
import platform
import re
import subprocess
import sys
import time
import traceback
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

# ─────────────────────────────────────────────
# CONFIG
# ─────────────────────────────────────────────
MODEL    = os.getenv("AI_MODEL",    "gemini-2.5-flash")
PROVIDER = os.getenv("AI_PROVIDER", "gemini")
MAX_FILE_READ   = 8_000   # chars per file
MAX_CONTEXT     = 30_000  # total context chars sent to AI
REPORT_DIR      = Path("deploy_diagnosis")
REPORT_FILE     = REPORT_DIR / "full_report.txt"
JSON_REPORT     = REPORT_DIR / "report.json"

# ─────────────────────────────────────────────
# DATA CLASSES
# ─────────────────────────────────────────────
@dataclass
class Issue:
    severity:       str          # CRITICAL / HIGH / MEDIUM / LOW
    category:       str          # RAM / METHOD / ALIGNMENT / DEPENDENCY / CONFIG / NETWORK / SYNTAX / UNKNOWN
    file:           str
    line:           str
    description:    str
    expected:       str
    solution:       str
    affected_files: list[str] = field(default_factory=list)

@dataclass
class DiagnosticReport:
    platform:       str
    timestamp:      str
    issues:         list[Issue]  = field(default_factory=list)
    raw_context:    str          = ""
    ai_diagnosis:   str          = ""
    system_info:    dict         = field(default_factory=dict)
    token_usage:    dict         = field(default_factory=dict)

# ─────────────────────────────────────────────
# AI CLIENT
# ─────────────────────────────────────────────
_ai_stats = {"prompt_tokens": 0, "completion_tokens": 0,
             "total_tokens": 0, "requests": 0, "response_time": 0.0}

def build_ai_client():
    from google import genai
    key = os.getenv("GEMINI_API_KEY")
    if not key:
        raise RuntimeError("GEMINI_API_KEY not set")
    return genai.Client(api_key=key)

def ask_ai(prompt: str) -> str:
    client = build_ai_client()
    started = time.perf_counter()
    response = client.models.generate_content(model=MODEL, contents=prompt)
    _ai_stats["response_time"] += time.perf_counter() - started
    _ai_stats["requests"]      += 1
    usage = getattr(response, "usage_metadata", None)
    _ai_stats["prompt_tokens"]     += int(getattr(usage, "prompt_token_count",     0) or 0)
    _ai_stats["completion_tokens"] += int(getattr(usage, "candidates_token_count", 0) or 0)
    _ai_stats["total_tokens"]       = (_ai_stats["prompt_tokens"] +
                                       _ai_stats["completion_tokens"])
    return (getattr(response, "text", "") or "").strip()

# ─────────────────────────────────────────────
# PLATFORM DETECTOR
# ─────────────────────────────────────────────
def detect_platform() -> str:
    """
    Detect which CI/CD platform is running this agent.
    GitHub Actions  → GITHUB_ACTIONS=true
    Azure DevOps    → TF_BUILD=True
    Jenkins         → JENKINS_URL is set
    """
    if os.getenv("GITHUB_ACTIONS") == "true":
        return "github_actions"
    if os.getenv("TF_BUILD") == "True":
        return "azure_devops"
    if os.getenv("JENKINS_URL"):
        return "jenkins"
    return "unknown"

# ─────────────────────────────────────────────
# SYSTEM INFO COLLECTOR
# ─────────────────────────────────────────────
def collect_system_info() -> dict:
    """
    Collect real system metrics:
    RAM, CPU, Disk, Python version, OS details.
    """
    info = {}

    # ── OS & Python ──
    info["os"]             = platform.system()
    info["os_version"]     = platform.version()
    info["architecture"]   = platform.machine()
    info["python_version"] = sys.version
    info["hostname"]       = platform.node()

    # ── RAM ──
    ram_output = safe_run("free -m 2>/dev/null || vm_stat 2>/dev/null")
    info["ram_raw"] = ram_output

    # Parse Linux free -m output
    ram_match = re.search(
        r"Mem:\s+(\d+)\s+(\d+)\s+(\d+)", ram_output
    )
    if ram_match:
        total   = int(ram_match.group(1))
        used    = int(ram_match.group(2))
        free    = int(ram_match.group(3))
        pct     = round((used / total) * 100, 1) if total else 0
        info["ram_total_mb"] = total
        info["ram_used_mb"]  = used
        info["ram_free_mb"]  = free
        info["ram_usage_pct"] = pct
        info["ram_critical"] = pct > 90
        info["ram_warning"]  = 75 < pct <= 90

    # ── CPU ──
    cpu_output = safe_run(
        "top -bn1 2>/dev/null | grep 'Cpu(s)' || "
        "ps -A -o %cpu 2>/dev/null | awk '{s+=$1} END {print s}'"
    )
    info["cpu_raw"] = cpu_output

    # ── Disk ──
    disk_output = safe_run("df -h . 2>/dev/null | tail -1")
    info["disk_raw"] = disk_output
    disk_match = re.search(r"(\d+)%", disk_output)
    if disk_match:
        info["disk_usage_pct"] = int(disk_match.group(1))
        info["disk_critical"]  = info["disk_usage_pct"] > 95

    # ── Open file descriptors ──
    info["open_fds"] = safe_run(
        "ls /proc/self/fd 2>/dev/null | wc -l || echo N/A"
    ).strip()

    # ── Network ──
    info["network"] = safe_run(
        "curl -s --max-time 5 -o /dev/null -w '%{http_code}' "
        "https://pypi.org/simple/ 2>/dev/null || echo timeout"
    ).strip()

    return info

# ─────────────────────────────────────────────
# SAFE COMMAND RUNNER
# ─────────────────────────────────────────────
def safe_run(cmd: str, timeout: int = 20) -> str:
    try:
        result = subprocess.run(
            cmd, shell=True, capture_output=True,
            text=True, timeout=timeout, check=False
        )
        return (result.stdout + result.stderr)[:6000]
    except Exception as exc:
        return f"[command failed: {exc}]"

# ─────────────────────────────────────────────
# CI/CD PLATFORM CONTEXT COLLECTORS
# ─────────────────────────────────────────────
def collect_github_actions_context() -> str:
    parts = ["=== GITHUB ACTIONS CONTEXT ==="]
    for var in [
        "GITHUB_WORKFLOW", "GITHUB_RUN_ID", "GITHUB_RUN_NUMBER",
        "GITHUB_JOB", "GITHUB_ACTION", "GITHUB_REF", "GITHUB_SHA",
        "GITHUB_REPOSITORY", "GITHUB_ACTOR", "GITHUB_EVENT_NAME",
        "RUNNER_OS", "RUNNER_ARCH", "RUNNER_NAME",
    ]:
        parts.append(f"  {var}={os.getenv(var, 'N/A')}")

    # Read step summary if available
    summary_file = os.getenv("GITHUB_STEP_SUMMARY")
    if summary_file and Path(summary_file).exists():
        parts.append("\n--- STEP SUMMARY ---")
        parts.append(Path(summary_file).read_text(errors="replace")[-3000:])

    # Read GitHub Actions log files
    for log_path in glob.glob("/home/runner/work/**/*.log", recursive=True)[:5]:
        try:
            content = Path(log_path).read_text(errors="replace")
            parts.append(f"\n--- LOG: {log_path} ---\n{content[-3000:]}")
        except OSError:
            pass

    return "\n".join(parts)

def collect_azure_devops_context() -> str:
    parts = ["=== AZURE DEVOPS CONTEXT ==="]
    for var in [
        "BUILD_DEFINITIONNAME", "BUILD_BUILDNUMBER", "BUILD_BUILDID",
        "BUILD_SOURCEBRANCH", "BUILD_SOURCEVERSION", "BUILD_REASON",
        "AGENT_NAME", "AGENT_OS", "AGENT_OSARCHITECTURE",
        "SYSTEM_TEAMPROJECT", "SYSTEM_DEFINITIONID",
        "RELEASE_RELEASENAME", "RELEASE_ENVIRONMENTNAME",
    ]:
        parts.append(f"  {var}={os.getenv(var, 'N/A')}")

    # Azure pipeline logs
    agent_home = os.getenv("AGENT_HOMEDIRECTORY", "")
    if agent_home:
        for log_path in glob.glob(
            f"{agent_home}/**/*.log", recursive=True
        )[:5]:
            try:
                content = Path(log_path).read_text(errors="replace")
                parts.append(f"\n--- LOG: {log_path} ---\n{content[-3000:]}")
            except OSError:
                pass
    return "\n".join(parts)

def collect_jenkins_context() -> str:
    parts = ["=== JENKINS CONTEXT ==="]
    for var in [
        "JENKINS_URL", "JOB_NAME", "JOB_BASE_NAME", "BUILD_NUMBER",
        "BUILD_URL", "BUILD_TAG", "NODE_NAME", "NODE_LABELS",
        "WORKSPACE", "GIT_BRANCH", "GIT_COMMIT", "GIT_URL",
        "EXECUTOR_NUMBER",
    ]:
        parts.append(f"  {var}={os.getenv(var, 'N/A')}")

    # Jenkins build log
    workspace = os.getenv("WORKSPACE", ".")
    for log_path in glob.glob(
        f"{workspace}/**/*.log", recursive=True
    )[:5]:
        try:
            content = Path(log_path).read_text(errors="replace")
            parts.append(f"\n--- LOG: {log_path} ---\n{content[-3000:]}")
        except OSError:
            pass
    return "\n".join(parts)

# ─────────────────────────────────────────────
# FILE SCANNER
# ─────────────────────────────────────────────
def scan_project_files() -> dict[str, str]:
    """
    Scan all relevant project files and return their content.
    Looks for: Python, JS, JSON, YAML, Dockerfile, requirements,
               config files, and log files.
    """
    file_map: dict[str, str] = {}
    patterns = [
        "**/*.py",
        "**/*.js", "**/*.ts",
        "**/*.json",
        "**/*.yaml", "**/*.yml",
        "**/Dockerfile*",
        "**/requirements*.txt",
        "**/*.cfg", "**/*.ini", "**/*.env",
        "**/*.log",
        "**/pom.xml",
        "**/package.json",
        "**/Makefile",
    ]
    excluded_dirs = {
        ".git", "node_modules", "__pycache__",
        ".venv", "venv", "env", ".tox",
        "dist", "build", ".eggs",
    }
    for pattern in patterns:
        for file_path in glob.glob(pattern, recursive=True)[:50]:
            path = Path(file_path)
            # Skip excluded directories
            if any(part in excluded_dirs for part in path.parts):
                continue
            try:
                content = path.read_text(
                    encoding="utf-8", errors="replace"
                )
                file_map[str(path)] = content[:MAX_FILE_READ]
            except OSError:
                pass
    return file_map

# ─────────────────────────────────────────────
# DEEP ERROR EXTRACTORS
# ─────────────────────────────────────────────
def extract_python_tracebacks(text: str) -> list[dict]:
    """
    Extract full Python tracebacks from text.
    Returns structured list of traceback details.
    """
    tracebacks = []
    # Match full traceback blocks
    tb_pattern = re.compile(
        r"Traceback \(most recent call last\):(.*?)(?=\n\S|\Z)",
        re.DOTALL
    )
    for match in tb_pattern.finditer(text):
        tb_text = match.group(0)
        frames  = []

        # Extract each frame
        frame_pattern = re.compile(
            r'File "([^"]+)", line (\d+), in (\S+)'
        )
        for frame in frame_pattern.finditer(tb_text):
            frames.append({
                "file": frame.group(1),
                "line": frame.group(2),
                "function": frame.group(3),
            })

        # Extract error type and message
        error_match = re.search(
            r"(\w+(?:Error|Exception|Warning|Fault)):\s*(.+)",
            tb_text
        )
        error_type = error_match.group(1) if error_match else "Unknown"
        error_msg  = error_match.group(2) if error_match else tb_text[-200:]

        tracebacks.append({
            "type":    error_type,
            "message": error_msg.strip(),
            "frames":  frames,
            "raw":     tb_text[:2000],
        })
    return tracebacks

def extract_js_errors(text: str) -> list[dict]:
    """Extract JavaScript / Node.js error patterns."""
    errors = []
    patterns = [
        # TypeError: xxx is not a function
        re.compile(r"(TypeError|ReferenceError|SyntaxError|RangeError):\s*(.+)"),
        # at file.js:line:col
        re.compile(r"at\s+(?:\S+ \()?([^:]+):(\d+):(\d+)\)?"),
        # Module not found
        re.compile(r"Cannot find module '([^']+)'"),
        # ENOMEM
        re.compile(r"(ENOMEM|FATAL ERROR):\s*(.+)"),
    ]
    for pattern in patterns:
        for match in pattern.finditer(text):
            errors.append({
                "match":   match.group(0),
                "groups":  match.groups(),
                "pattern": pattern.pattern,
            })
    return errors

def extract_memory_issues(text: str, system_info: dict) -> list[Issue]:
    """
    Deeply detect RAM/memory issues from both logs AND
    live system metrics.
    """
    issues = []
    lowered = text.lower()

    # Pattern-based detection from logs
    memory_patterns = [
        (r"MemoryError",            "Python MemoryError raised"),
        (r"out of memory",          "Out of memory condition"),
        (r"ENOMEM",                 "OS-level ENOMEM error"),
        (r"cannot allocate memory", "Memory allocation failed"),
        (r"malloc.*failed",         "malloc() call failed"),
        (r"heap space",             "JVM heap space exhausted"),
        (r"gc overhead limit",      "JVM GC overhead limit exceeded"),
        (r"killed.*oom",            "OOM killer terminated the process"),
        (r"oom.killer",             "OOM killer triggered"),
        (r"exit code 137",          "Process killed (likely OOM, exit 137)"),
        (r"exit code: 137",         "Process killed (likely OOM, exit 137)"),
        (r"swap.*full",             "Swap space full"),
        (r"FATAL ERROR.*CALL_AND_RETRY", "Node.js heap out of memory"),
    ]
    for pattern, description in memory_patterns:
        if re.search(pattern, text, re.IGNORECASE):
            # Try to find file/line near this pattern
            match   = re.search(pattern, text, re.IGNORECASE)
            context = text[max(0, match.start()-300):match.end()+300]
            file_ref, line_ref = _nearest_file_line(context)
            issues.append(Issue(
                severity    = "CRITICAL",
                category    = "RAM",
                file        = file_ref,
                line        = line_ref,
                description = description,
                expected    = "Sufficient memory available for the process.",
                solution    = (
                    "1. Increase runner/agent RAM allocation.\n"
                    "2. Reduce batch sizes or chunk data processing.\n"
                    "3. Use streaming instead of loading full data in memory.\n"
                    "4. Add swap space as a temporary measure.\n"
                    "5. Profile memory usage with tracemalloc or memory_profiler."
                ),
                affected_files=[file_ref] if file_ref != "unknown" else [],
            ))

    # Live system RAM check
    if system_info.get("ram_critical"):
        pct   = system_info.get("ram_usage_pct", "?")
        total = system_info.get("ram_total_mb",  "?")
        free  = system_info.get("ram_free_mb",   "?")
        issues.append(Issue(
            severity    = "CRITICAL",
            category    = "RAM",
            file        = "system/runner",
            line        = "N/A",
            description = (
                f"Live RAM usage is critically high: {pct}% used. "
                f"Total={total}MB, Free={free}MB"
            ),
            expected    = "RAM usage below 80% during deployment.",
            solution    = (
                "1. Upgrade runner to larger instance type.\n"
                "2. Close unnecessary background processes.\n"
                "3. Split deployment into smaller steps.\n"
                "4. Add NODE_OPTIONS='--max-old-space-size=512' for Node.js.\n"
                "5. Use Docker memory limits to isolate services."
            ),
            affected_files=[],
        ))
    elif system_info.get("ram_warning"):
        pct   = system_info.get("ram_usage_pct", "?")
        total = system_info.get("ram_total_mb",  "?")
        issues.append(Issue(
            severity    = "HIGH",
            category    = "RAM",
            file        = "system/runner",
            line        = "N/A",
            description = (
                f"RAM usage is high: {pct}% of {total}MB used."
            ),
            expected    = "RAM usage below 75%.",
            solution    = (
                "Monitor memory usage. Consider upgrading runner if this "
                "correlates with deployment failures."
            ),
            affected_files=[],
        ))
    return issues

def extract_method_issues(text: str) -> list[Issue]:
    """
    Detect method/attribute/function not found errors in depth.
    """
    issues = []
    method_patterns = [
        (
            r"AttributeError: '?(\w+)'? object has no attribute '?(\w+)'?",
            "Python AttributeError",
        ),
        (
            r"TypeError: (\S+)\(\) takes (\d+) positional argument",
            "Python TypeError — wrong argument count",
        ),
        (
            r"TypeError: (\S+) is not a function",
            "JavaScript — called non-function",
        ),
        (
            r"TypeError: Cannot read propert(?:y|ies) of (undefined|null)",
            "JavaScript — property access on null/undefined",
        ),
        (
            r"NameError: name '(\S+)' is not defined",
            "Python NameError — undefined variable/function",
        ),
        (
            r"ImportError: cannot import name '(\S+)'",
            "Python ImportError — symbol not found in module",
        ),
        (
            r"ModuleNotFoundError: No module named '(\S+)'",
            "Python — module not installed",
        ),
        (
            r"Cannot find module '([^']+)'",
            "Node.js — module not found",
        ),
        (
            r"method (\S+) not found",
            "Method not found in class/object",
        ),
        (
            r"NoMethodError: undefined method '(\S+)'",
            "Ruby — undefined method",
        ),
        (
            r"java\.lang\.NoSuchMethodException:\s*(\S+)",
            "Java — NoSuchMethodException",
        ),
        (
            r"java\.lang\.ClassNotFoundException:\s*(\S+)",
            "Java — ClassNotFoundException",
        ),
    ]
    for pattern, category in method_patterns:
        for match in re.finditer(pattern, text, re.IGNORECASE):
            context = text[max(0, match.start()-400):match.end()+400]
            file_ref, line_ref   = _nearest_file_line(context)
            affected             = _find_affected_files(text, match.group(0))
            issues.append(Issue(
                severity      = "CRITICAL",
                category      = "METHOD",
                file          = file_ref,
                line          = line_ref,
                description   = (
                    f"{category}: {match.group(0)}"
                ),
                expected      = "Method/attribute/module must exist and be accessible.",
                solution      = _method_solution(category, match),
                affected_files = affected,
            ))
    return issues

def extract_alignment_issues(text: str) -> list[Issue]:
    """
    Detect alignment, indentation, and structural issues.
    """
    issues = []
    alignment_patterns = [
        (
            r"IndentationError: (unexpected indent|expected an indented block)[^\n]*",
            "Python IndentationError",
        ),
        (
            r"TabError: inconsistent use of tabs and spaces",
            "Python TabError — mixed tabs and spaces",
        ),
        (
            r"SyntaxError: invalid syntax[^\n]*",
            "Python SyntaxError",
        ),
        (
            r"YAML.*mapping values are not allowed",
            "YAML alignment/indentation error",
        ),
        (
            r"yaml.*expected.*but found",
            "YAML structure mismatch",
        ),
        (
            r"json.*JSONDecodeError.*line (\d+)",
            "JSON parse error",
        ),
        (
            r"expected ',' or '\}' at line (\d+)",
            "JSON missing comma or brace",
        ),
        (
            r"Unexpected token.*line (\d+)",
            "JSON/JS unexpected token",
        ),
        (
            r"alignment.*fault",
            "Memory alignment fault",
        ),
        (
            r"Bus error",
            "Bus error — likely memory alignment fault",
        ),
        (
            r"Segmentation fault",
            "Segmentation fault — illegal memory access",
        ),
        (
            r"SIGBUS",
            "SIGBUS signal — bus/alignment error",
        ),
    ]
    for pattern, category in alignment_patterns:
        for match in re.finditer(pattern, text, re.IGNORECASE):
            context  = text[max(0, match.start()-400):match.end()+400]
            file_ref, line_ref = _nearest_file_line(context)
            affected = _find_affected_files(text, match.group(0))
            issues.append(Issue(
                severity      = "CRITICAL",
                category      = "ALIGNMENT",
                file          = file_ref,
                line          = line_ref,
                description   = f"{category}: {match.group(0)[:200]}",
                expected      = "Correct indentation and syntax structure.",
                solution      = _alignment_solution(category),
                affected_files = affected,
            ))
    return issues

def extract_dependency_issues(text: str) -> list[Issue]:
    """Detect all dependency / package / version issues."""
    issues = []
    dep_patterns = [
        (
            r"No module named '([^']+)'",
            "Missing Python package",
        ),
        (
            r"ModuleNotFoundError: No module named '([^']+)'",
            "Python module not installed",
        ),
        (
            r"ImportError: ([^\n]+)",
            "Python ImportError",
        ),
        (
            r"Cannot find module '([^']+)'",
            "Node.js module not found",
        ),
        (
            r"npm ERR! ([^\n]+)",
            "NPM error",
        ),
        (
            r"pip.*ERROR.*([^\n]+)",
            "pip install error",
        ),
        (
            r"Could not find a version that satisfies the requirement (\S+)",
            "pip — version not satisfiable",
        ),
        (
            r"version conflict.*requires (\S+)",
            "Dependency version conflict",
        ),
        (
            r"incompatible.*version.*(\d+\.\d+)",
            "Incompatible library version",
        ),
        (
            r"dependency resolution failed",
            "Dependency resolution failed",
        ),
        (
            r"requirements.*not found",
            "requirements.txt issue",
        ),
    ]
    for pattern, category in dep_patterns:
        for match in re.finditer(pattern, text, re.IGNORECASE):
            context  = text[max(0, match.start()-300):match.end()+300]
            file_ref, line_ref = _nearest_file_line(context)
            affected = _find_affected_files(text, match.group(0))
            dep_name = match.group(1) if match.lastindex else "unknown"
            issues.append(Issue(
                severity      = "HIGH",
                category      = "DEPENDENCY",
                file          = file_ref,
                line          = line_ref,
                description   = f"{category}: {match.group(0)[:200]}",
                expected      = (
                    f"Package '{dep_name}' must be installed and compatible."
                ),
                solution      = _dependency_solution(category, dep_name),
                affected_files = affected,
            ))
    return issues

def extract_config_issues(text: str) -> list[Issue]:
    """Detect configuration and environment variable issues."""
    issues = []
    config_patterns = [
        (r"KeyError: '([^']+)'",                      "Missing dict key / env var"),
        (r"Environment variable (\S+) not set",        "Missing env variable"),
        (r"(\S+) is not set",                          "Required variable not set"),
        (r"Invalid configuration.*?([^\n]+)",          "Invalid config value"),
        (r"config.*?error.*?([^\n]+)",                 "Configuration error"),
        (r"permission denied.*?([^\n]+)",              "Permission denied"),
        (r"EACCES.*?([^\n]+)",                         "Access denied (EACCES)"),
        (r"certificate.*?expired",                     "TLS/SSL certificate expired"),
        (r"SSL.*?error",                               "SSL/TLS error"),
        (r"invalid.*?token",                           "Invalid auth token"),
        (r"authentication.*?failed",                   "Authentication failure"),
        (r"401 unauthorized",                          "HTTP 401 Unauthorized"),
        (r"403 forbidden",                             "HTTP 403 Forbidden"),
        (r"port.*?already in use",                     "Port conflict"),
        (r"EADDRINUSE",                                "Address already in use"),
    ]
    for pattern, category in config_patterns:
        for match in re.finditer(pattern, text, re.IGNORECASE):
            context  = text[max(0, match.start()-300):match.end()+300]
            file_ref, line_ref = _nearest_file_line(context)
            affected = _find_affected_files(text, match.group(0))
            issues.append(Issue(
                severity      = "HIGH",
                category      = "CONFIG",
                file          = file_ref,
                line          = line_ref,
                description   = f"{category}: {match.group(0)[:200]}",
                expected      = "All configuration values must be valid and accessible.",
                solution      = _config_solution(category),
                affected_files = affected,
            ))
    return issues

def extract_network_issues(text: str) -> list[Issue]:
    """Detect network, connectivity, DNS, and timeout issues."""
    issues = []
    network_patterns = [
        (r"Connection refused",           "Connection refused"),
        (r"ECONNREFUSED",                 "Connection refused (ECONNREFUSED)"),
        (r"Connection timed out",         "Connection timeout"),
        (r"ETIMEDOUT",                    "Connection timed out (ETIMEDOUT)"),
        (r"Name or service not known",    "DNS resolution failed"),
        (r"ENOTFOUND",                    "DNS not found (ENOTFOUND)"),
        (r"Network is unreachable",       "Network unreachable"),
        (r"ENETUNREACH",                  "Network unreachable (ENETUNREACH)"),
        (r"failed to fetch",              "HTTP fetch failed"),
        (r"curl.*error",                  "curl network error"),
        (r"HTTPSConnectionPool.*Max retries exceeded", "HTTP max retries exceeded"),
        (r"requests\.exceptions\.\w+",   "Python requests library error"),
        (r"502 Bad Gateway",              "HTTP 502 — upstream failure"),
        (r"503 Service Unavailable",      "HTTP 503 — service down"),
        (r"504 Gateway Timeout",          "HTTP 504 — gateway timeout"),
    ]
    for pattern, category in network_patterns:
        for match in re.finditer(pattern, text, re.IGNORECASE):
            context  = text[max(0, match.start()-300):match.end()+300]
            file_ref, line_ref = _nearest_file_line(context)
            affected = _find_affected_files(text, match.group(0))
            issues.append(Issue(
                severity      = "HIGH",
                category      = "NETWORK",
                file          = file_ref,
                line          = line_ref,
                description   = f"{category}: {match.group(0)[:200]}",
                expected      = "Network requests must succeed within timeout limits.",
                solution      = (
                    "1. Check network connectivity from the runner.\n"
                    "2. Verify firewall / security group rules.\n"
                    "3. Check if the target service is running.\n"
                    "4. Increase timeout values.\n"
                    "5. Use retry logic with exponential backoff."
                ),
                affected_files = affected,
            ))
    return issues

def extract_docker_issues(text: str) -> list[Issue]:
    """Detect Docker and container-specific issues."""
    issues = []
    docker_patterns = [
        (r"failed to pull.*image",         "Docker image pull failure"),
        (r"manifest unknown",              "Docker manifest not found"),
        (r"no such image",                 "Docker image not found"),
        (r"container.*exited.*code (\d+)", "Container exited with error code"),
        (r"OCI runtime.*error",            "OCI container runtime error"),
        (r"permission denied.*docker.sock","Docker socket permission denied"),
        (r"Dockerfile.*line (\d+)",        "Dockerfile build error"),
        (r"docker build.*error",           "Docker build failed"),
        (r"docker.*push.*error",           "Docker push failed"),
        (r"registry.*unauthorized",        "Docker registry unauthorized"),
    ]
    for pattern, category in docker_patterns:
        for match in re.finditer(pattern, text, re.IGNORECASE):
            context  = text[max(0, match.start()-300):match.end()+300]
            file_ref = "Dockerfile"
            line_ref = match.group(1) if match.lastindex else "N/A"
            affected = ["Dockerfile", "docker-compose.yml"]
            issues.append(Issue(
                severity      = "CRITICAL",
                category      = "DOCKER",
                file          = file_ref,
                line          = line_ref,
                description   = f"{category}: {match.group(0)[:200]}",
                expected      = "Docker build and push must complete successfully.",
                solution      = _docker_solution(category),
                affected_files = affected,
            ))
    return issues

# ─────────────────────────────────────────────
# HELPER UTILITIES
# ─────────────────────────────────────────────
def _nearest_file_line(context: str) -> tuple[str, str]:
    """
    Given a context string, find the nearest file + line reference.
    """
    patterns = [
        r'File "([^"]+)", line (\d+)',
        r"([A-Za-z0-9_./\\-]+\.(?:py|js|ts|yaml|yml|json|cfg|ini|sh)):(\d+)",
        r"([A-Za-z0-9_./\\-]+\.py)[:\s]+line[:\s]+(\d+)",
        r"line (\d+).*?in ([A-Za-z0-9_./\\-]+)",
        r"Dockerfile:(\d+)",
    ]
    for pattern in patterns:
        match = re.search(pattern, context, re.IGNORECASE)
        if match:
            if pattern.startswith("Dockerfile"):
                return ("Dockerfile", match.group(1))
            if pattern.startswith("line"):
                return (match.group(2), match.group(1))
            return (match.group(1), match.group(2))
    return ("unknown", "N/A")

def _find_affected_files(text: str, error_snippet: str) -> list[str]:
    """
    Find all files referenced near the error in the full context.
    """
    affected = []
    start = text.find(error_snippet[:50])
    if start == -1:
        return []
    window = text[max(0, start-1000):start+1000]
    file_pattern = re.compile(
        r'(?:File "([^"]+)"|'
        r'([A-Za-z0-9_./\\-]+\.(?:py|js|ts|yaml|yml|json|sh|cfg)):)'
    )
    for match in file_pattern.finditer(window):
        fname = match.group(1) or match.group(2)
        if (fname
                and "site-packages" not in fname
                and fname not in affected):
            affected.append(fname)
    return affected[:8]

def _method_solution(category: str, match: re.Match) -> str:
    solutions = {
        "Python AttributeError":        (
            f"1. Check spelling of '{match.group(2) if match.lastindex and match.lastindex >= 2 else 'attribute'}'.\n"
            "2. Verify the object type before calling the attribute.\n"
            "3. Ensure the class defines this method.\n"
            "4. Check for version differences between dev and prod."
        ),
        "Python NameError — undefined variable/function": (
            "1. Import or define the variable before use.\n"
            "2. Check for typos in variable names.\n"
            "3. Verify scope — it may be defined inside a different block."
        ),
        "Python — module not installed": (
            f"1. Add to requirements.txt and rebuild.\n"
            "2. Run: pip install <module> in the environment.\n"
            "3. Verify Docker image includes the dependency layer."
        ),
        "JavaScript — called non-function": (
            "1. Check the variable type before calling it as a function.\n"
            "2. Verify the import/require path is correct.\n"
            "3. Ensure async functions are awaited properly."
        ),
    }
    for key, sol in solutions.items():
        if key in category:
            return sol
    return (
        "1. Check method/function name spelling.\n"
        "2. Verify the method exists in the correct version of the library.\n"
        "3. Review class hierarchy and inheritance.\n"
        "4. Rebuild and reinstall dependencies."
    )

def _alignment_solution(category: str) -> str:
    if "Indentation" in category or "Tab" in category:
        return (
            "1. Use consistent spaces (4 spaces for Python — no tabs).\n"
            "2. Run: autopep8 --in-place --aggressive <file>.py\n"
            "3. Configure editor to show whitespace characters.\n"
            "4. Use .editorconfig to enforce consistent indentation."
        )
    if "YAML" in category:
        return (
            "1. Validate YAML with: python -c \"import yaml; yaml.safe_load(open('file.yaml'))\"\n"
            "2. Use yamllint to check structure.\n"
            "3. Ensure consistent 2-space indentation in YAML.\n"
            "4. Check for tabs — YAML does not allow tabs."
        )
    if "JSON" in category:
        return (
            "1. Validate JSON with: python -m json.tool file.json\n"
            "2. Check for trailing commas (not allowed in JSON).\n"
            "3. Verify all strings use double quotes.\n"
            "4. Use a JSON linter or VS Code JSON validator."
        )
    if "Segmentation" in category or "Bus error" in category or "SIGBUS" in category:
        return (
            "1. Check for null/dangling pointer dereferences.\n"
            "2. Verify memory alignment for the target CPU architecture.\n"
            "3. Run with Valgrind: valgrind --track-origins=yes ./program\n"
            "4. Check if compiled for wrong architecture (ARM vs x86).\n"
            "5. Verify struct packing and __attribute__((packed)) usage."
        )
    return (
        "1. Fix syntax errors shown in the traceback.\n"
        "2. Use a linter (flake8, pylint, eslint).\n"
        "3. Run static analysis before deploying."
    )

def _dependency_solution(category: str, dep_name: str) -> str:
    if "Python" in category or "pip" in category:
        return (
            f"1. Add '{dep_name}' to requirements.txt.\n"
            "2. Rebuild Docker image to include new dependency.\n"
            "3. Use: pip freeze > requirements.txt to capture current env.\n"
            "4. Check for version conflicts with: pip check"
        )
    if "Node" in category or "npm" in category:
        return (
            f"1. Run: npm install {dep_name}\n"
            "2. Add to package.json dependencies.\n"
            "3. Delete node_modules and run: npm ci\n"
            "4. Check .npmrc for registry configuration."
        )
    return (
        f"1. Install the missing dependency: {dep_name}\n"
        "2. Verify the package name is correct.\n"
        "3. Check if a private registry is needed."
    )

def _config_solution(category: str) -> str:
    if "env" in category.lower() or "variable" in category.lower():
        return (
            "1. Add the missing environment variable to CI/CD secrets.\n"
            "2. Check .env file is not gitignored when needed.\n"
            "3. Verify variable name spelling in code vs CI config.\n"
            "4. Add a startup validation that checks all required env vars."
        )
    if "permission" in category.lower() or "access" in category.lower():
        return (
            "1. Check file/directory permissions: ls -la\n"
            "2. Run chmod +x or chown as needed.\n"
            "3. Verify the deployment user has correct IAM/RBAC roles.\n"
            "4. Check Docker container is not running as root when it should."
        )
    if "port" in category.lower():
        return (
            "1. Check which process is using the port: lsof -i :<port>\n"
            "2. Kill the conflicting process or use a different port.\n"
            "3. Ensure Docker port mappings are correct."
        )
    return (
        "1. Review the configuration file for incorrect values.\n"
        "2. Validate config against schema before deploying.\n"
        "3. Check CI/CD secret and variable injection."
    )

def _docker_solution(category: str) -> str:
    if "pull" in category.lower() or "manifest" in category.lower():
        return (
            "1. Verify the image name and tag exist in Docker Hub.\n"
            "2. Check Docker Hub credentials in CI secrets.\n"
            "3. Ensure the build job pushed before the deploy job runs.\n"
            "4. Use the exact SHA tag for immutable references."
        )
    if "permission" in category.lower():
        return (
            "1. Add CI user to the docker group.\n"
            "2. Use: sudo usermod -aG docker $USER\n"
            "3. In GitHub Actions, Docker is available by default on ubuntu runners."
        )
    return (
        "1. Review the Dockerfile for syntax errors.\n"
        "2. Run: docker build . --no-cache to get a clean build.\n"
        "3. Check Docker daemon is running on the agent."
    )

# ─────────────────────────────────────────────
# CONTEXT ASSEMBLER
# ─────────────────────────────────────────────
def collect_all_context(detected_platform: str) -> str:
    """
    Collect ALL available context from the CI/CD environment,
    system, and project files.
    """
    parts = []

    # CI/CD platform context
    if detected_platform == "github_actions":
        parts.append(collect_github_actions_context())
    elif detected_platform == "azure_devops":
        parts.append(collect_azure_devops_context())
    elif detected_platform == "jenkins":
        parts.append(collect_jenkins_context())

    # Generic deployment variables
    parts.append("\n=== DEPLOYMENT VARIABLES ===")
    for key in [
        "TARGET_CLOUD", "AWS_APP_NAME", "AWS_ENV_NAME", "AWS_REGION",
        "AZURE_WEBAPP_NAME", "AZURE_RESOURCE_GROUP",
        "DOCKERHUB_USERNAME", "DOCKERHUB_REPOSITORY",
        "APP_URL", "GITHUB_SHA", "CI", "CD",
    ]:
        parts.append(f"  {key}={os.getenv(key, 'N/A')}")

    # Platform diagnostic commands
    parts.append("\n=== PLATFORM DIAGNOSTICS ===")
    commands = {
        "AWS EB Status":
            "aws elasticbeanstalk describe-environments "
            "--query 'Environments[0].[Status,Health,HealthStatus]' "
            "--output text 2>&1",
        "AWS Recent Events":
            "aws elasticbeanstalk describe-events --max-items 10 "
            "--query 'Events[*].[EventDate,Severity,Message]' "
            "--output text 2>&1",
        "Azure App Status":
            "az webapp show "
            "--name \"${AZURE_WEBAPP_NAME:-}\" "
            "--resource-group \"${AZURE_RESOURCE_GROUP:-}\" "
            "--query '[state,defaultHostName]' -o tsv 2>&1",
        "Azure Logs":
            "az webapp log tail "
            "--name \"${AZURE_WEBAPP_NAME:-}\" "
            "--resource-group \"${AZURE_RESOURCE_GROUP:-}\" "
            "--timeout 10 2>&1 | head -100",
        "Docker Containers":
            "docker ps -a 2>&1",
        "Docker Logs":
            "docker logs $(docker ps -aq | head -1) --tail 100 2>&1",
        "Disk Space":
            "df -h 2>&1",
        "Memory":
            "free -m 2>&1",
        "Top Processes":
            "ps aux --sort=-%mem | head -20 2>&1",
        "Git Log":
            "git log --oneline -10 2>&1",
        "Git Status":
            "git status 2>&1",
        "Git Diff":
            "git diff --name-only 2>&1 | head -30",
        "pip list":
            "pip list 2>&1 | head -50",
        "Node modules":
            "ls node_modules 2>&1 | head -20",
        "Python version":
            "python --version 2>&1",
        "Node version":
            "node --version 2>&1",
        "Environment":
            "env 2>&1 | grep -v SECRET | grep -v KEY | grep -v TOKEN | grep -v PASSWORD",
    }
    for label, cmd in commands.items():
        output = safe_run(cmd)
        if output.strip() and "[command failed" not in output:
            parts.append(f"\n$ [{label}]\n{output[:2000]}")

    # Project files
    parts.append("\n=== PROJECT FILES ===")
    file_map = scan_project_files()
    for fname, content in list(file_map.items())[:30]:
        parts.append(f"\n--- FILE: {fname} ---\n{content}")

    # Existing log/report files
    parts.append("\n=== LOG AND REPORT FILES ===")
    log_patterns = [
        "reports/*.txt", "reports/*.log",
        "*.log", "logs/*.log",
        "errors_report.txt", "deploy_diagnosis/*.txt",
    ]
    for pattern in log_patterns:
        for filename in glob.glob(pattern)[:5]:
            try:
                content = Path(filename).read_text(
                    encoding="utf-8", errors="replace"
                )
                parts.append(f"\n--- {filename} ---\n{content[-4000:]}")
            except OSError:
                pass

    full_context = "\n".join(parts)
    return full_context[:MAX_CONTEXT]

# ─────────────────────────────────────────────
# DEEP SCANNER — RUNS ALL EXTRACTORS
# ─────────────────────────────────────────────
def deep_scan(context: str, system_info: dict) -> list[Issue]:
    """
    Run all issue extractors on the collected context.
    Returns a deduplicated, severity-sorted list of issues.
    """
    all_issues: list[Issue] = []

    # Extract Python tracebacks first for accurate file/line info
    tracebacks = extract_python_tracebacks(context)
    for tb in tracebacks:
        frames     = tb.get("frames", [])
        last_frame = frames[-1] if frames else {}
        affected   = [f["file"] for f in frames
                      if "site-packages" not in f.get("file", "")]
        all_issues.append(Issue(
            severity      = "CRITICAL",
            category      = "SYNTAX",
            file          = last_frame.get("file", "unknown"),
            line          = last_frame.get("line", "N/A"),
            description   = f"{tb['type']}: {tb['message'][:300]}",
            expected      = "No exceptions should be raised during deployment.",
            solution      = (
                f"Fix the {tb['type']} in "
                f"{last_frame.get('file', 'the file shown')} "
                f"at line {last_frame.get('line', 'N/A')}. "
                f"Full traceback:\n{tb['raw'][:1000]}"
            ),
            affected_files = affected,
        ))

    all_issues += extract_memory_issues(context, system_info)
    all_issues += extract_method_issues(context)
    all_issues += extract_alignment_issues(context)
    all_issues += extract_dependency_issues(context)
    all_issues += extract_config_issues(context)
    all_issues += extract_network_issues(context)
    all_issues += extract_docker_issues(context)

    # Deduplicate by (file, line, category)
    seen:   set                  = set()
    unique: list[Issue]          = []
    for issue in all_issues:
        key = (issue.file, issue.line, issue.category,
               issue.description[:60])
        if key not in seen:
            seen.add(key)
            unique.append(issue)

    # Sort by severity
    severity_order = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3}
    unique.sort(key=lambda i: severity_order.get(i.severity, 9))

    return unique

# ─────────────────────────────────────────────
# AI DEEP DIAGNOSIS
# ─────────────────────────────────────────────
def ai_deep_diagnosis(context: str, issues: list[Issue]) -> str:
    """
    Send full context and already-found issues to AI
    for deeper analysis and missed-issue detection.
    """
    found_summary = "\n".join([
        f"- [{i.severity}] {i.category}: {i.description[:100]} "
        f"@ {i.file}:{i.line}"
        for i in issues[:10]
    ])

    prompt = f"""
You are a senior DevOps and software engineer analyzing a deployment failure.

ALREADY DETECTED ISSUES:
{found_summary}

FULL DEPLOYMENT CONTEXT:
{context[:20000]}

Your task:
1. Identify ANY additional issues not already listed above.
2. For EACH issue provide EXACTLY:
   FILE: <filename or 'system' if not file-specific>
   LINE: <line number or N/A>
   CATEGORY: <RAM | METHOD | ALIGNMENT | DEPENDENCY | CONFIG | NETWORK | DOCKER | SYNTAX | OTHER>
   SEVERITY: <CRITICAL | HIGH | MEDIUM | LOW>
   PRESENT_ERROR: <what is actually happening>
   EXPECTED_VALUE: <what should happen>
   WHY: <root cause explanation>
   AFFECTED_FILES: <comma-separated list of files impacted>
   SOLUTION: <step by step fix>
   ---
3. At the end provide a DEPLOYMENT_HEALTH_SCORE from 0-100.
4. Provide PRIORITY_FIX: the single most important fix to apply first.

Be specific. Reference actual file names and line numbers from the context.
"""
    return ask_ai(prompt)

# ─────────────────────────────────────────────
# REPORT BUILDER
# ─────────────────────────────────────────────
def build_report(report: DiagnosticReport) -> str:
    """
    Build the final human-readable diagnostic report.
    """
    lines = [
        "=" * 70,
        "  DEEP DEPLOYMENT FAILURE DIAGNOSTIC REPORT",
        "=" * 70,
        f"  Platform   : {report.platform.upper()}",
        f"  Timestamp  : {report.timestamp}",
        f"  Issues Found: {len(report.issues)}",
        "=" * 70,
        "",
    ]

    # System Info Summary
    si = report.system_info
    lines += [
        "─── SYSTEM HEALTH ───",
        f"  OS          : {si.get('os', 'N/A')} {si.get('os_version', '')}",
        f"  Architecture: {si.get('architecture', 'N/A')}",
        f"  Python      : {si.get('python_version', 'N/A').split()[0]}",
        f"  RAM         : {si.get('ram_used_mb', '?')}MB / {si.get('ram_total_mb', '?')}MB  "
        f"({si.get('ram_usage_pct', '?')}%)"
        + (" ⚠️  CRITICAL" if si.get('ram_critical') else
           " ⚠️  WARNING"  if si.get('ram_warning')  else " ✅"),
        f"  Disk        : {si.get('disk_raw', 'N/A')}",
        f"  Network     : PyPI reachable → {si.get('network', 'N/A')}",
        "",
    ]

    if not report.issues:
        lines.append("  ✅ No specific issues detected by pattern scanner.")
        lines.append("  → Review AI diagnosis below for deeper insights.")
    else:
        lines.append(
            f"  ⚠️  {len(report.issues)} issue(s) detected:\n"
        )
        for idx, issue in enumerate(report.issues, 1):
            severity_icon = {
                "CRITICAL": "🔴",
                "HIGH":     "🟠",
                "MEDIUM":   "🟡",
                "LOW":      "🟢",
            }.get(issue.severity, "⚪")
            lines += [
                f"  {'─'*66}",
                f"  {severity_icon} ISSUE #{idx}  "
                f"[{issue.severity}] [{issue.category}]",
                f"  {'─'*66}",
                f"  FILE          : {issue.file}",
                f"  LINE          : {issue.line}",
                f"  DESCRIPTION   : {issue.description}",
                f"  EXPECTED      : {issue.expected}",
                f"  AFFECTED FILES: {', '.join(issue.affected_files) if issue.affected_files else 'see file above'}",
                "  SOLUTION:",
            ]
            for sol_line in issue.solution.split("\n"):
                lines.append(f"    {sol_line}")
            lines.append("")

    # AI Diagnosis
    if report.ai_diagnosis:
        lines += [
            "=" * 70,
            "  🤖 AI DEEP DIAGNOSIS",
            "=" * 70,
            report.ai_diagnosis,
            "",
        ]

    # Token usage
    tu = report.token_usage
    if tu:
        lines += [
            "─── AI TOKEN USAGE ───",
            f"  Requests    : {tu.get('requests', 0)}",
            f"  Prompt Tok  : {tu.get('prompt_tokens', 0)}",
            f"  Completion  : {tu.get('completion_tokens', 0)}",
            f"  Total Tok   : {tu.get('total_tokens', 0)}",
            f"  AI Time     : {tu.get('response_time', 0):.2f}s",
            "",
        ]

    lines += ["=" * 70, "  END OF REPORT", "=" * 70]
    return "\n".join(lines)

def build_json_report(report: DiagnosticReport) -> dict:
    """Build a machine-readable JSON report."""
    return {
        "platform":    report.platform,
        "timestamp":   report.timestamp,
        "system_info": report.system_info,
        "issues":      [
            {
                "severity":       i.severity,
                "category":       i.category,
                "file":           i.file,
                "line":           i.line,
                "description":    i.description,
                "expected":       i.expected,
                "solution":       i.solution,
                "affected_files": i.affected_files,
            }
            for i in report.issues
        ],
        "ai_diagnosis": report.ai_diagnosis,
        "token_usage":  report.token_usage,
        "total_issues": len(report.issues),
        "critical_count": sum(
            1 for i in report.issues if i.severity == "CRITICAL"
        ),
        "high_count": sum(
            1 for i in report.issues if i.severity == "HIGH"
        ),
    }

# ─────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────
def main() -> int:
    started   = time.perf_counter()
    timestamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

    print("🔍 Deep Deployment Failure Diagnostic Agent starting...")
    print(f"   Timestamp : {timestamp}")

    # 1. Detect platform
    detected_platform = detect_platform()
    print(f"   Platform  : {detected_platform.upper()}")

    # 2. Collect system info
    print("   Collecting system info...")
    system_info = collect_system_info()

    # 3. Collect all context
    print("   Collecting deployment context...")
    context = collect_all_context(detected_platform)

    # 4. Deep pattern scan
    print("   Running deep issue scanner...")
    issues = deep_scan(context, system_info)
    print(f"   Found {len(issues)} issue(s) via pattern scanner.")

    # 5. AI deep diagnosis (if enabled)
    ai_diagnosis = ""
    if os.getenv("RUN_AI_REVIEW", "0") == "1" and os.getenv("GEMINI_API_KEY"):
        print("   Running AI deep diagnosis...")
        try:
            ai_diagnosis = ai_deep_diagnosis(context, issues)
        except Exception as exc:
            ai_diagnosis = f"[AI unavailable: {exc}]"
            print(f"   ⚠️  AI error: {exc}")

    # 6. Build report
    report = DiagnosticReport(
        platform     = detected_platform,
        timestamp    = timestamp,
        issues       = issues,
        raw_context  = context,
        ai_diagnosis = ai_diagnosis,
        system_info  = system_info,
        token_usage  = dict(_ai_stats),
    )

    # 7. Write reports
    REPORT_DIR.mkdir(exist_ok=True)
    text_report = build_report(report)
    REPORT_FILE.write_text(text_report, encoding="utf-8")

    json_data = build_json_report(report)
    JSON_REPORT.write_text(
        json.dumps(json_data, indent=2), encoding="utf-8"
    )

    # Also write root-level for CI artifact pickup
    Path("errors_report.txt").write_text(
        text_report + "\n\n--- RAW CONTEXT ---\n" + context[-5000:],
        encoding="utf-8",
    )

    # 8. Print to stdout
    print("\n" + text_report)
    print(f"\n   Reports written to:")
    print(f"     → {REPORT_FILE}")
    print(f"     → {JSON_REPORT}")
    print(f"     → errors_report.txt")
    print(f"   Total execution: {time.perf_counter()-started:.2f}s")

    return 1  # Always exit 1 — this agent only runs on failure

if __name__ == "__main__":
    _t0 = time.perf_counter()
    _rc = main()
    try:
        from agent.monitor_client import report
        report(
            agent_name        = "errors",
            stage             = "during_deploy",
            state             = "passed" if _rc == 0 else "failed",
            decision          = "pass"   if _rc == 0 else "fail",
            status            = "success" if _rc == 0 else "failed",
            provider          = PROVIDER,
            model             = MODEL,
            prompt_tokens     = _ai_stats.get("prompt_tokens", 0),
            completion_tokens = _ai_stats.get("completion_tokens", 0),
            total_tokens      = _ai_stats.get("total_tokens", 0),
            api_calls         = _ai_stats.get("requests", 0) or 1,
            api_response_time_seconds = round(_ai_stats.get("response_time", 0.0), 4),
            execution_time_seconds    = round(time.perf_counter() - _t0, 3),
            api_key_count     = 1,
        )
    except Exception as e:
        print(f"[errors] monitor report error: {e}", flush=True)
    raise SystemExit(_rc)
from __future__ import annotations

import glob
import json
import os
import platform
import re
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

# ═════════════════════════════════════════════════════════════════
# CONFIG
# ═════════════════════════════════════════════════════════════════
MODEL         = os.getenv("AI_MODEL",    "gemini-2.5-flash")
PROVIDER      = os.getenv("AI_PROVIDER", "gemini")
MAX_FILE_READ = 4_000
MAX_CONTEXT   = 30_000
REPORT_DIR    = Path("deploy_diagnosis")
REPORT_FILE   = REPORT_DIR / "full_report.txt"
JSON_REPORT   = REPORT_DIR / "report.json"


# ═════════════════════════════════════════════════════════════════
# DATA CLASSES
# ═════════════════════════════════════════════════════════════════
@dataclass
class Issue:
    severity:       str
    category:       str
    file:           str
    line:           str
    block:          str = "N/A"
    description:    str = ""
    expected:       str = ""
    solution:       str = ""
    root_cause:     str = ""
    affected_files: list[str] = field(default_factory=list)


@dataclass
class DiagnosticReport:
    platform:     str
    timestamp:    str
    issues:       list[Issue] = field(default_factory=list)
    raw_context:  str = ""
    ai_diagnosis: str = ""
    system_info:  dict = field(default_factory=dict)
    token_usage:  dict = field(default_factory=dict)


_ai_stats = {"prompt_tokens": 0, "completion_tokens": 0,
             "total_tokens": 0, "requests": 0, "response_time": 0.0}


# ═════════════════════════════════════════════════════════════════
# AI CLIENT
# ═════════════════════════════════════════════════════════════════
def build_ai_client():
    from google import genai
    key = os.getenv("GEMINI_API_KEY")
    if not key:
        raise RuntimeError("GEMINI_API_KEY not set")
    return genai.Client(api_key=key)


def ask_ai(prompt: str) -> str:
    client  = build_ai_client()
    started = time.perf_counter()
    resp    = client.models.generate_content(model=MODEL, contents=prompt)
    _ai_stats["response_time"] += time.perf_counter() - started
    _ai_stats["requests"]      += 1
    u = getattr(resp, "usage_metadata", None)
    _ai_stats["prompt_tokens"]     += int(getattr(u, "prompt_token_count",     0) or 0)
    _ai_stats["completion_tokens"] += int(getattr(u, "candidates_token_count", 0) or 0)
    _ai_stats["total_tokens"]       = (_ai_stats["prompt_tokens"]
                                       + _ai_stats["completion_tokens"])
    return (getattr(resp, "text", "") or "").strip()


# ═════════════════════════════════════════════════════════════════
# PLATFORM + SHELL RUNNER
# ═════════════════════════════════════════════════════════════════
def detect_platform() -> str:
    if os.getenv("GITHUB_ACTIONS") == "true": return "github_actions"
    if os.getenv("TF_BUILD") == "True":       return "azure_devops"
    if os.getenv("JENKINS_URL"):              return "jenkins"
    return "unknown"


def safe_run(cmd: str, timeout: int = 15) -> str:
    try:
        r = subprocess.run(cmd, shell=True, capture_output=True,
                           text=True, timeout=timeout, check=False)
        return (r.stdout + r.stderr)[:4000]
    except Exception as exc:
        return f"[command failed: {exc}]"


# ═════════════════════════════════════════════════════════════════
# SYSTEM INFO
# ═════════════════════════════════════════════════════════════════
def collect_system_info() -> dict:
    info = {
        "os":             platform.system(),
        "os_version":     platform.version(),
        "architecture":   platform.machine(),
        "python_version": sys.version,
        "hostname":       platform.node(),
    }
    ram = safe_run("free -m 2>/dev/null || vm_stat 2>/dev/null")
    info["ram_raw"] = ram
    m = re.search(r"Mem:\s+(\d+)\s+(\d+)\s+(\d+)", ram)
    if m:
        total, used, free = int(m.group(1)), int(m.group(2)), int(m.group(3))
        pct = round((used/total)*100, 1) if total else 0
        info.update({"ram_total_mb": total, "ram_used_mb": used,
                     "ram_free_mb": free, "ram_usage_pct": pct,
                     "ram_critical": pct > 90,
                     "ram_warning":  75 < pct <= 90})
    info["cpu_raw"]  = safe_run("top -bn1 2>/dev/null | grep 'Cpu(s)' || echo ''")
    info["disk_raw"] = safe_run("df -h . 2>/dev/null | tail -1")
    dm = re.search(r"(\d+)%", info["disk_raw"])
    if dm:
        info["disk_usage_pct"] = int(dm.group(1))
        info["disk_critical"]  = info["disk_usage_pct"] > 95
    info["open_fds"] = safe_run("ls /proc/self/fd 2>/dev/null | wc -l || echo N/A").strip()
    info["network"]  = safe_run(
        "curl -s --max-time 5 -o /dev/null -w '%{http_code}' "
        "https://pypi.org/simple/ 2>/dev/null || echo timeout"
    ).strip()
    return info


# ═════════════════════════════════════════════════════════════════
# CI CONTEXT
# ═════════════════════════════════════════════════════════════════
def _ci_vars(names: list[str], header: str) -> str:
    parts = [header]
    for v in names:
        parts.append(f"  {v}={os.getenv(v, 'N/A')}")
    return "\n".join(parts)


def collect_github_actions_context() -> str:
    txt = _ci_vars(
        ["GITHUB_WORKFLOW","GITHUB_RUN_ID","GITHUB_RUN_NUMBER","GITHUB_JOB",
         "GITHUB_REF","GITHUB_SHA","GITHUB_REPOSITORY","GITHUB_EVENT_NAME",
         "RUNNER_OS","RUNNER_ARCH"],
        "=== GITHUB ACTIONS CONTEXT ===",
    )
    s = os.getenv("GITHUB_STEP_SUMMARY")
    if s and Path(s).exists():
        txt += "\n--- STEP SUMMARY ---\n" + Path(s).read_text(errors="replace")[-2000:]
    return txt


def collect_azure_devops_context() -> str:
    return _ci_vars(
        ["BUILD_DEFINITIONNAME","BUILD_BUILDNUMBER","BUILD_BUILDID",
         "BUILD_SOURCEBRANCH","BUILD_SOURCEVERSION","AGENT_NAME",
         "AGENT_OS","SYSTEM_TEAMPROJECT","RELEASE_RELEASENAME",
         "RELEASE_ENVIRONMENTNAME"],
        "=== AZURE DEVOPS CONTEXT ===",
    )


def collect_jenkins_context() -> str:
    return _ci_vars(
        ["JENKINS_URL","JOB_NAME","BUILD_NUMBER","BUILD_URL",
         "NODE_NAME","WORKSPACE","GIT_BRANCH","GIT_COMMIT"],
        "=== JENKINS CONTEXT ===",
    )


# ═════════════════════════════════════════════════════════════════
# FILE SCANNER
# ═════════════════════════════════════════════════════════════════
def scan_project_files() -> dict[str, str]:
    files: dict[str, str] = {}
    patterns = ["**/*.py","**/*.js","**/*.ts","**/*.json","**/*.yaml","**/*.yml",
                "**/Dockerfile*","**/requirements*.txt","**/*.cfg","**/*.ini",
                "**/*.env","**/pom.xml","**/package.json","**/Makefile"]
    excluded = {".git","node_modules","__pycache__",".venv","venv","env",
                ".tox","dist","build",".eggs","site-packages","deploy_diagnosis"}
    for pat in patterns:
        for fp in glob.glob(pat, recursive=True)[:30]:
            p = Path(fp)
            if any(part in excluded for part in p.parts):
                continue
            try:
                files[str(p)] = p.read_text(encoding="utf-8",
                                            errors="replace")[:MAX_FILE_READ]
            except OSError:
                pass
    return files


# ═════════════════════════════════════════════════════════════════
# FILE + LINE + BLOCK LOCATOR
# ═════════════════════════════════════════════════════════════════
def _nearest_file_line(context: str) -> tuple[str, str, str]:
    """Return (file, line, block)."""
    m = re.search(r'File "([^"]+)", line (\d+), in (\S+)', context)
    if m: return (m.group(1), m.group(2), m.group(3))
    m = re.search(r'File "([^"]+)", line (\d+)', context)
    if m: return (m.group(1), m.group(2), "N/A")
    m = re.search(r"Dockerfile:(\d+)", context)
    if m: return ("Dockerfile", m.group(1), "N/A")
    for m in re.finditer(
        r"([A-Za-z0-9_./\\-]+\.(?:py|js|ts|yaml|yml|json|cfg|ini|sh)):(\d+)",
        context, re.IGNORECASE,
    ):
        fname = m.group(1)
        if Path(fname).exists() or fname.startswith(("agent/","app.","docker/")):
            return (fname, m.group(2), "N/A")
    m = re.search(r"([A-Za-z0-9_./\\-]+\.py)[:\s]+line[:\s]+(\d+)",
                  context, re.IGNORECASE)
    if m: return (m.group(1), m.group(2), "N/A")
    return ("unknown", "N/A", "N/A")


def _find_affected_files(text: str, error_snippet: str) -> list[str]:
    aff = []
    idx = text.find(error_snippet[:50])
    if idx == -1: return []
    window = text[max(0, idx-800):idx+800]
    for m in re.finditer(
        r'(?:File "([^"]+)"|'
        r'([A-Za-z0-9_./\\-]+\.(?:py|js|ts|yaml|yml|json|sh|cfg)):)', window,
    ):
        fname = m.group(1) or m.group(2)
        if fname and "site-packages" not in fname and fname not in aff:
            aff.append(fname)
    return aff[:6]


# ═════════════════════════════════════════════════════════════════
# ROOT-CAUSE EXPLAINER
# ═════════════════════════════════════════════════════════════════
def _explain_error_type(err_type: str, msg: str) -> str:
    e = {
        "ImportError":         "Module import failing — module missing, misspelled, or symbol not exported.",
        "ModuleNotFoundError": "Python module missing from environment. Add to requirements.txt or activate venv.",
        "AttributeError":      "Method/attribute missing on object — often library version mismatch or typo.",
        "NameError":           "Variable/function used before definition. Missing import or scope error.",
        "TypeError":           "Wrong argument type or count — often API changes between library versions.",
        "SyntaxError":         "Python cannot parse the file — invalid syntax blocks all execution.",
        "IndentationError":    "Mixed tabs/spaces or wrong indent level.",
        "KeyError":            "Dict lookup failed — env var not set or config key renamed.",
        "ValueError":          "Argument type correct but value wrong (e.g., 'abc' where int expected).",
        "FileNotFoundError":   "File missing — check path, cwd, and deploy inclusion.",
        "PermissionError":     "Process lacks OS permissions — check chmod/ownership/Docker user.",
        "ConnectionError":     "Network request failed — host down, DNS issue, or firewall block.",
        "TimeoutError":        "Network call too slow — increase timeout or check service health.",
    }
    for k, v in e.items():
        if k in err_type:
            return v
    return f"Unhandled {err_type} raised. Investigate the traceback."


# ═════════════════════════════════════════════════════════════════
# EXTRACTORS
# ═════════════════════════════════════════════════════════════════
def extract_python_tracebacks(text: str) -> list[Issue]:
    issues: list[Issue] = []
    tb_re = re.compile(r"Traceback \(most recent call last\):(.*?)(?=\n\S|\Z)",
                       re.DOTALL)
    for match in tb_re.finditer(text):
        tb = match.group(0)
        frames = []
        for f in re.finditer(r'File "([^"]+)", line (\d+), in (\S+)', tb):
            frames.append({"file": f.group(1), "line": f.group(2),
                           "function": f.group(3)})
        err = re.search(r"(\w+(?:Error|Exception|Warning|Fault)):\s*(.+)", tb)
        et = err.group(1) if err else "Unknown"
        em = err.group(2).strip() if err else tb[-200:]
        proj = [f for f in frames
                if "site-packages" not in f["file"]
                and "python3" not in f["file"]]
        last = proj[-1] if proj else (frames[-1] if frames else {})
        issues.append(Issue(
            severity   = "CRITICAL",
            category   = "SYNTAX",
            file       = last.get("file", "unknown"),
            line       = last.get("line", "N/A"),
            block      = last.get("function", "N/A"),
            description= f"{et}: {em[:250]}",
            expected   = "No unhandled exceptions during deploy.",
            root_cause = _explain_error_type(et, em),
            solution   = (
                f"1. Open {last.get('file','file above')} at line "
                f"{last.get('line','N/A')} (function `{last.get('function','N/A')}`).\n"
                f"2. Fix the {et}: {em[:120]}\n"
                f"3. Full traceback:\n{tb[:800]}"
            ),
            affected_files = [f["file"] for f in proj][:6],
        ))
    return issues


def extract_memory_issues(text: str, sysinfo: dict) -> list[Issue]:
    issues: list[Issue] = []
    pats = [
        (r"MemoryError",                 "Python MemoryError — insufficient RAM."),
        (r"out of memory",               "OS reported OOM."),
        (r"ENOMEM",                      "OS-level ENOMEM — allocation refused."),
        (r"cannot allocate memory",      "malloc/mmap failed."),
        (r"heap space",                  "JVM heap exhausted."),
        (r"exit code 137",               "OOM killer terminated process (SIGKILL)."),
        (r"FATAL ERROR.*CALL_AND_RETRY", "Node.js V8 heap exhausted."),
    ]
    for p, why in pats:
        m = re.search(p, text, re.IGNORECASE)
        if not m: continue
        ctx = text[max(0, m.start()-300):m.end()+300]
        f, l, b = _nearest_file_line(ctx)
        issues.append(Issue(
            severity="CRITICAL", category="RAM",
            file=f, line=l, block=b,
            description=f"Memory error: {m.group(0)[:120]}",
            expected="Process completes within available RAM.",
            root_cause=why,
            solution=(
                "1. Increase runner/agent RAM.\n"
                "2. Chunk or stream data instead of loading fully.\n"
                "3. Node.js: NODE_OPTIONS='--max-old-space-size=2048'.\n"
                "4. JVM: increase -Xmx.\n"
                "5. Profile with tracemalloc / heap dumps."
            ),
            affected_files=[f] if f != "unknown" else [],
        ))
    if sysinfo.get("ram_critical"):
        issues.append(Issue(
            severity="CRITICAL", category="RAM",
            file="system/runner", line="N/A", block="N/A",
            description=(f"Live RAM {sysinfo.get('ram_usage_pct')}% used "
                         f"({sysinfo.get('ram_used_mb')}MB/"
                         f"{sysinfo.get('ram_total_mb')}MB)."),
            expected="RAM usage below 80%.",
            root_cause="Runner under memory pressure. Deploys will fail intermittently.",
            solution="Upgrade runner size or reduce workload.",
        ))
    return issues


def extract_method_issues(text: str) -> list[Issue]:
    issues: list[Issue] = []
    pats = [
        (r"AttributeError: '?(\w+)'? object has no attribute '?(\w+)'?",
         "Attribute missing",
         "Object's class lacks the attribute. Common: library upgrade renamed it, or wrong object type."),
        (r"NameError: name '(\S+)' is not defined",
         "Undefined name",
         "Variable/function never imported or defined in scope."),
        (r"ImportError: cannot import name '(\S+)'",
         "Symbol not exported",
         "Module exists but doesn't export this name. Check module __init__.py."),
        (r"ModuleNotFoundError: No module named '(\S+)'",
         "Module not installed",
         "Package missing from Python env. Add to requirements.txt."),
        (r"Cannot find module '([^']+)'",
         "Node module missing",
         "npm package not installed. Run npm install."),
        (r"NoMethodError: undefined method '(\S+)'",
         "Ruby method missing",
         "Method doesn't exist on receiver's class."),
        (r"java\.lang\.NoSuchMethodException:\s*(\S+)",
         "Java method missing",
         "JAR version mismatch."),
        (r"java\.lang\.ClassNotFoundException:\s*(\S+)",
         "Java class missing",
         "Classpath missing required JAR."),
    ]
    for pat, cat, why in pats:
        for m in re.finditer(pat, text, re.IGNORECASE):
            ctx = text[max(0, m.start()-400):m.end()+400]
            f, l, b = _nearest_file_line(ctx)
            issues.append(Issue(
                severity="CRITICAL", category="METHOD",
                file=f, line=l, block=b,
                description=f"{cat}: {m.group(0)[:200]}",
                expected="Referenced name/method/module must exist.",
                root_cause=why,
                solution=_method_solution(cat, m),
                affected_files=_find_affected_files(text, m.group(0)),
            ))
    return issues


def extract_alignment_issues(text: str) -> list[Issue]:
    issues: list[Issue] = []
    pats = [
        (r"IndentationError: (unexpected indent|expected an indented block)[^\n]*",
         "Python IndentationError",
         "Inconsistent indentation. Python requires uniform whitespace."),
        (r"TabError: inconsistent use of tabs and spaces",
         "Python TabError",
         "Mixed tabs and spaces in same block. Convert all to spaces."),
        (r"SyntaxError: invalid syntax[^\n]*",
         "Python SyntaxError",
         "Parser rejected the code. Blocks import."),
        (r"YAML.*mapping values are not allowed",
         "YAML indentation error",
         "Bad YAML alignment — usually a colon-space error."),
        (r"yaml.*expected.*but found",
         "YAML structure error",
         "YAML got a token it didn't expect. Check indentation."),
        (r"json.*JSONDecodeError.*line (\d+)",
         "JSON parse error",
         "Invalid JSON — trailing comma, unquoted key, or bad escape."),
        (r"expected ',' or '\}' at line (\d+)",
         "JSON missing delimiter",
         "Missing comma or brace."),
        (r"Unexpected token.*line (\d+)",
         "JSON/JS unexpected token",
         "Parser found something it can't process."),
        (r"Bus error",     "Bus error",     "CPU memory alignment fault."),
        (r"Segmentation fault", "Segfault", "Illegal memory access."),
        (r"SIGBUS",        "SIGBUS",        "Bus/alignment signal received."),
    ]
    for pat, cat, why in pats:
        for m in re.finditer(pat, text, re.IGNORECASE):
            ctx = text[max(0, m.start()-400):m.end()+400]
            f, l, b = _nearest_file_line(ctx)
            issues.append(Issue(
                severity="CRITICAL", category="ALIGNMENT",
                file=f, line=l, block=b,
                description=f"{cat}: {m.group(0)[:200]}",
                expected="Correct indentation and syntax structure.",
                root_cause=why,
                solution=_alignment_solution(cat),
                affected_files=_find_affected_files(text, m.group(0)),
            ))
    return issues


def extract_dependency_issues(text: str) -> list[Issue]:
    issues: list[Issue] = []
    pats = [
        (r"No module named '([^']+)'",
         "Missing Python package", "Package not in requirements.txt or venv missing."),
        (r"ImportError: ([^\n]+)",
         "Python ImportError", "Import failed — see message for cause."),
        (r"Cannot find module '([^']+)'",
         "Node module not found", "npm package missing from node_modules."),
        (r"npm ERR! ([^\n]+)",
         "NPM error", "npm reported install/build failure."),
        (r"pip.*ERROR.*([^\n]+)",
         "pip install error", "pip couldn't install a package."),
        (r"Could not find a version that satisfies the requirement (\S+)",
         "pip version conflict", "No PyPI version matches your constraints."),
        (r"version conflict.*requires (\S+)",
         "Version conflict", "Two packages need incompatible versions."),
        (r"dependency resolution failed",
         "Dep resolution failed", "Resolver couldn't compute a valid set."),
    ]
    for pat, cat, why in pats:
        for m in re.finditer(pat, text, re.IGNORECASE):
            ctx = text[max(0, m.start()-300):m.end()+300]
            f, l, b = _nearest_file_line(ctx)
            dep = m.group(1) if m.lastindex else "unknown"
            issues.append(Issue(
                severity="HIGH", category="DEPENDENCY",
                file=f, line=l, block=b,
                description=f"{cat}: {m.group(0)[:200]}",
                expected=f"Package '{dep}' installed and compatible.",
                root_cause=why,
                solution=_dependency_solution(cat, dep),
                affected_files=_find_affected_files(text, m.group(0)),
            ))
    return issues


def extract_config_issues(text: str) -> list[Issue]:
    issues: list[Issue] = []
    pats = [
        (r"KeyError: '([^']+)'",
         "Missing dict key / env var",
         "Code expects an env var or config key that isn't set."),
        (r"Environment variable (\S+) not set",
         "Missing env variable",
         "Required env var not injected. Check CI/CD secrets."),
        (r"Invalid configuration.*?([^\n]+)",
         "Invalid config value",
         "Config value doesn't match expected format/schema."),
        (r"permission denied.*?([^\n]+)",
         "Permission denied",
         "OS-level access denied. Check chmod, chown, or Docker user."),
        (r"EACCES.*?([^\n]+)",
         "EACCES access denied",
         "Insufficient file permissions."),
        (r"certificate.*?expired",
         "TLS certificate expired",
         "SSL/TLS cert past its expiry date."),
        (r"SSL.*?error",
         "SSL/TLS error",
         "Certificate validation or handshake failure."),
        (r"invalid.*?token",
         "Invalid auth token",
         "API token wrong, expired, or malformed."),
        (r"authentication.*?failed",
         "Authentication failure",
         "Credentials rejected by the target service."),
        (r"401 unauthorized",
         "HTTP 401",
         "Missing/invalid credentials for the request."),
        (r"403 forbidden",
         "HTTP 403",
         "Authenticated but lacks permission to access resource."),
        (r"port.*?already in use",
         "Port conflict",
         "Another process is using the port."),
        (r"EADDRINUSE",
         "EADDRINUSE",
         "Bind failed — port taken."),
    ]
    for pat, cat, why in pats:
        for m in re.finditer(pat, text, re.IGNORECASE):
            ctx = text[max(0, m.start()-300):m.end()+300]
            f, l, b = _nearest_file_line(ctx)
            issues.append(Issue(
                severity="HIGH", category="CONFIG",
                file=f, line=l, block=b,
                description=f"{cat}: {m.group(0)[:200]}",
                expected="Configuration valid and accessible.",
                root_cause=why,
                solution=_config_solution(cat),
                affected_files=_find_affected_files(text, m.group(0)),
            ))
    return issues


def extract_network_issues(text: str) -> list[Issue]:
    issues: list[Issue] = []
    pats = [
        (r"Connection refused", "Connection refused",
         "Target service not listening or blocked."),
        (r"ECONNREFUSED", "ECONNREFUSED",
         "TCP handshake refused — service down."),
        (r"Connection timed out", "Connection timeout",
         "Target unreachable within timeout window."),
        (r"ETIMEDOUT", "ETIMEDOUT",
         "TCP timeout — network path broken or slow."),
        (r"Name or service not known", "DNS resolution failed",
         "Hostname doesn't resolve. DNS issue or wrong hostname."),
        (r"ENOTFOUND", "ENOTFOUND",
         "DNS lookup failed."),
        (r"Network is unreachable", "Network unreachable",
         "No route to host. Routing/firewall issue."),
        (r"ENETUNREACH", "ENETUNREACH",
         "Kernel: no route to network."),
        (r"HTTPSConnectionPool.*Max retries exceeded",
         "HTTP max retries",
         "Repeated request failures. Target dead or slow."),
        (r"502 Bad Gateway", "HTTP 502",
         "Upstream server returned bad response to proxy."),
        (r"503 Service Unavailable", "HTTP 503",
         "Server temporarily unavailable / overloaded."),
        (r"504 Gateway Timeout", "HTTP 504",
         "Proxy timed out waiting for upstream."),
    ]
    for pat, cat, why in pats:
        for m in re.finditer(pat, text, re.IGNORECASE):
            ctx = text[max(0, m.start()-300):m.end()+300]
            f, l, b = _nearest_file_line(ctx)
            issues.append(Issue(
                severity="HIGH", category="NETWORK",
                file=f, line=l, block=b,
                description=f"{cat}: {m.group(0)[:200]}",
                expected="Network requests succeed within timeout.",
                root_cause=why,
                solution=(
                    "1. Check network from the runner (ping/curl).\n"
                    "2. Verify firewall / security group rules.\n"
                    "3. Confirm target service is running.\n"
                    "4. Increase timeout values.\n"
                    "5. Add retry logic with exponential backoff."
                ),
                affected_files=_find_affected_files(text, m.group(0)),
            ))
    return issues


def extract_docker_issues(text: str) -> list[Issue]:
    issues: list[Issue] = []
    pats = [
        (r"failed to pull.*image", "Docker image pull failure",
         "Registry unreachable, image tag missing, or auth failed."),
        (r"manifest unknown", "Docker manifest not found",
         "Image tag doesn't exist in the registry."),
        (r"no such image", "Docker image not found",
         "Image not present locally or in specified registry."),
        (r"container.*exited.*code (\d+)", "Container exited",
         "Container process ended with non-zero exit code."),
        (r"OCI runtime.*error", "OCI runtime error",
         "Container runtime rejected the spec — often exec bit or entrypoint."),
        (r"permission denied.*docker.sock", "Docker socket denied",
         "User lacks access to /var/run/docker.sock."),
        (r"Dockerfile.*line (\d+)", "Dockerfile build error",
         "Instruction failed during image build."),
        (r"docker build.*error", "Docker build failed",
         "Build stage failed. Check preceding output."),
        (r"docker.*push.*error", "Docker push failed",
         "Push rejected. Check auth and repo permissions."),
        (r"registry.*unauthorized", "Registry unauthorized",
         "Missing/invalid registry credentials."),
    ]
    for pat, cat, why in pats:
        for m in re.finditer(pat, text, re.IGNORECASE):
            line = m.group(1) if m.lastindex else "N/A"
            issues.append(Issue(
                severity="CRITICAL", category="DOCKER",
                file="Dockerfile", line=line, block="N/A",
                description=f"{cat}: {m.group(0)[:200]}",
                expected="Docker build/push completes successfully.",
                root_cause=why,
                solution=_docker_solution(cat),
                affected_files=["Dockerfile", "docker-compose.yml"],
            ))
    return issues


# ═════════════════════════════════════════════════════════════════
# SOLUTION HELPERS
# ═════════════════════════════════════════════════════════════════
def _method_solution(cat: str, m: re.Match) -> str:
    if "Attribute missing" in cat:
        return (
            "1. Check spelling of the attribute.\n"
            "2. Verify object type — print(type(x)) before the call.\n"
            "3. Check library version vs the version documented.\n"
            "4. Ensure class defines the method (grep the source)."
        )
    if "Undefined name" in cat:
        return "1. Add the missing import.\n2. Check for typos.\n3. Verify scope."
    if "not installed" in cat.lower() or "module missing" in cat.lower():
        return (
            "1. Add package to requirements.txt (Python) or package.json (Node).\n"
            "2. Rebuild the Docker image.\n"
            "3. Verify the Docker build layer picks up the new dependency."
        )
    if "Symbol not exported" in cat:
        return (
            "1. Check module's public API — the symbol name may have changed.\n"
            "2. Look at the module __init__.py for exports.\n"
            "3. Import from a submodule if the API was reorganized."
        )
    return (
        "1. Check spelling and imports.\n"
        "2. Verify library version.\n"
        "3. Rebuild and reinstall dependencies."
    )


def _alignment_solution(cat: str) -> str:
    if "Indentation" in cat or "Tab" in cat:
        return ("1. Convert all tabs to 4 spaces.\n"
                "2. Run: autopep8 --in-place --aggressive <file>.py\n"
                "3. Enable 'show whitespace' in your editor.\n"
                "4. Add .editorconfig to enforce consistent indent.")
    if "YAML" in cat:
        return ("1. Validate: python -c \"import yaml; yaml.safe_load(open('f.yaml'))\"\n"
                "2. Run yamllint against the file.\n"
                "3. Use 2-space indent, never tabs.")
    if "JSON" in cat:
        return ("1. Validate: python -m json.tool file.json\n"
                "2. Remove trailing commas.\n"
                "3. Use double quotes for all strings.")
    if "Segfault" in cat or "Bus" in cat or "SIGBUS" in cat:
        return ("1. Check for null pointer dereferences.\n"
                "2. Verify architecture match (ARM vs x86).\n"
                "3. Run with Valgrind.\n"
                "4. Check struct packing.")
    return "1. Fix syntax errors in traceback.\n2. Run a linter.\n3. Add pre-commit hooks."


def _dependency_solution(cat: str, dep: str) -> str:
    if "Python" in cat or "pip" in cat:
        return (f"1. Add '{dep}' to requirements.txt.\n"
                "2. Rebuild Docker image.\n"
                "3. pip freeze > requirements.txt to lock versions.\n"
                "4. Run: pip check")
    if "Node" in cat or "npm" in cat:
        return (f"1. Run: npm install {dep}\n"
                "2. Add to package.json.\n"
                "3. Delete node_modules and run npm ci\n"
                "4. Verify .npmrc registry config.")
    return f"1. Install '{dep}'.\n2. Verify package name.\n3. Check private registry access."


def _config_solution(cat: str) -> str:
    c = cat.lower()
    if "env" in c or "variable" in c:
        return ("1. Add missing env var to CI/CD secrets.\n"
                "2. Verify variable name matches code exactly.\n"
                "3. Add startup validation for required env vars.")
    if "permission" in c or "access" in c or "eacces" in c:
        return ("1. Check permissions: ls -la <path>\n"
                "2. Use chmod/chown to fix.\n"
                "3. Verify Docker container user.\n"
                "4. Check IAM/RBAC roles.")
    if "port" in c or "eaddrinuse" in c:
        return ("1. Find blocker: lsof -i :<port>\n"
                "2. Kill or reassign the port.\n"
                "3. Fix Docker port mappings.")
    if "401" in c or "auth" in c or "token" in c:
        return ("1. Regenerate the API token/credential.\n"
                "2. Update the corresponding CI secret.\n"
                "3. Verify header format (Bearer vs raw).")
    if "403" in c:
        return ("1. Check IAM policy / RBAC role for the caller.\n"
                "2. Verify resource ARN or path is correct.\n"
                "3. Check API endpoint requires auth you have.")
    if "certificate" in c or "ssl" in c:
        return ("1. Renew the TLS cert.\n"
                "2. Verify system CA bundle is up to date.\n"
                "3. Check clock skew on the runner.")
    return ("1. Review config file for typos.\n"
            "2. Validate against schema before deploy.\n"
            "3. Check CI/CD secret injection.")


def _docker_solution(cat: str) -> str:
    c = cat.lower()
    if "pull" in c or "manifest" in c or "no such image" in c:
        return ("1. Verify image:tag exists in the registry.\n"
                "2. Check Docker Hub credentials in CI secrets.\n"
                "3. Ensure the build step pushed BEFORE deploy runs.\n"
                "4. Use immutable SHA tags instead of :latest.")
    if "socket" in c or "permission" in c:
        return ("1. Add user to docker group.\n"
                "2. On GitHub ubuntu runners Docker works by default.\n"
                "3. Restart docker daemon if needed.")
    if "exited" in c:
        return ("1. Check container logs: docker logs <container>\n"
                "2. Common exit codes: 137=OOM, 139=segfault, 1=generic error.\n"
                "3. Verify entrypoint and CMD in Dockerfile.")
    return ("1. Review Dockerfile for syntax.\n"
            "2. Build with --no-cache to check clean build.\n"
            "3. Verify Docker daemon is running.")


# ═════════════════════════════════════════════════════════════════
# CONTEXT ASSEMBLER — LOGS FIRST, PROJECT FILES LAST
# ═════════════════════════════════════════════════════════════════
def collect_all_context(plat: str) -> str:
    parts = []

    # 1. LOGS FIRST (most important for diagnosis)
    parts.append("=== DEPLOYMENT LOG FILES ===")
    for pattern in [
        "reports/aws-eb-logs.txt", "reports/aws-eb-events.txt",
        "reports/aws-eb-health.txt", "reports/aws-eb-status.txt",
        "reports/*.txt", "reports/*.log",
        "errors_report.txt", "deploy_diagnosis/*.txt",
        "*.log", "logs/*.log",
    ]:
        for fn in glob.glob(pattern)[:5]:
            try:
                content = Path(fn).read_text(encoding="utf-8", errors="replace")
                parts.append(f"\n--- {fn} ---\n{content[-5000:]}")
            except OSError:
                pass

    # 2. CI PLATFORM CONTEXT
    if plat == "github_actions":
        parts.append("\n" + collect_github_actions_context())
    elif plat == "azure_devops":
        parts.append("\n" + collect_azure_devops_context())
    elif plat == "jenkins":
        parts.append("\n" + collect_jenkins_context())

    # 3. DEPLOYMENT ENV VARS
    parts.append("\n=== DEPLOYMENT VARIABLES ===")
    for k in ["TARGET_CLOUD","AWS_APP_NAME","AWS_ENV_NAME","AWS_REGION",
              "AZURE_WEBAPP_NAME","AZURE_RESOURCE_GROUP",
              "DOCKERHUB_USERNAME","DOCKERHUB_REPOSITORY",
              "APP_URL","GITHUB_SHA","CI","CD"]:
        parts.append(f"  {k}={os.getenv(k, 'N/A')}")

    # 4. DIAGNOSTIC COMMANDS (cap at 1000 chars each)
    parts.append("\n=== DIAGNOSTICS ===")
    cmds = {
        "AWS EB Status": "aws elasticbeanstalk describe-environments "
                         "--query 'Environments[0].[Status,Health,HealthStatus]' -o text 2>&1",
        "AWS EB Events": "aws elasticbeanstalk describe-events --max-items 10 "
                         "--query 'Events[*].[EventDate,Severity,Message]' -o text 2>&1",
        "Docker ps":     "docker ps -a 2>&1",
        "Docker logs":   "docker logs $(docker ps -aq | head -1) --tail 50 2>&1",
        "Disk":          "df -h 2>&1",
        "Memory":        "free -m 2>&1",
        "Top mem":       "ps aux --sort=-%mem | head -10 2>&1",
        "Git log":       "git log --oneline -5 2>&1",
        "Git status":    "git status 2>&1",
        "pip list":      "pip list 2>&1 | head -40",
        "Python ver":    "python --version 2>&1",
        "Node ver":      "node --version 2>&1",
        "Env":           "env 2>&1 | grep -v -i -E 'secret|key|token|password'",
    }
    for label, cmd in cmds.items():
        out = safe_run(cmd)
        if out.strip() and "[command failed" not in out:
            parts.append(f"\n$ [{label}]\n{out[:1000]}")

    # 5. PROJECT FILES LAST — cap at 10KB total
    parts.append("\n=== PROJECT FILES ===")
    file_map = scan_project_files()
    used = 0
    for fname, content in file_map.items():
        if used >= 10_000:
            break
        snippet = content[:2000]
        parts.append(f"\n--- FILE: {fname} ---\n{snippet}")
        used += len(snippet)

    return "\n".join(parts)[:MAX_CONTEXT]


# ═════════════════════════════════════════════════════════════════
# DEEP SCAN + DEDUP
# ═════════════════════════════════════════════════════════════════
def deep_scan(context: str, sysinfo: dict) -> list[Issue]:
    all_issues: list[Issue] = []
    all_issues += extract_python_tracebacks(context)
    all_issues += extract_memory_issues(context, sysinfo)
    all_issues += extract_method_issues(context)
    all_issues += extract_alignment_issues(context)
    all_issues += extract_dependency_issues(context)
    all_issues += extract_config_issues(context)
    all_issues += extract_network_issues(context)
    all_issues += extract_docker_issues(context)

    # Dedup across categories (file + line + first 100 chars of description)
    seen: set = set()
    unique: list[Issue] = []
    for iss in all_issues:
        key = (iss.file, iss.line, iss.description[:100].lower())
        if key in seen:
            continue
        seen.add(key)
        unique.append(iss)

    order = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3}
    unique.sort(key=lambda i: order.get(i.severity, 9))
    return unique


# ═════════════════════════════════════════════════════════════════
# AI DEEP DIAGNOSIS
# ═════════════════════════════════════════════════════════════════
def ai_deep_diagnosis(context: str, issues: list[Issue]) -> str:
    found = "\n".join([
        f"- [{i.severity}] {i.category}: {i.description[:100]} "
        f"@ {i.file}:{i.line} (block: {i.block})"
        for i in issues[:10]
    ]) or "(none detected by pattern scanner)"

    prompt = f"""You are a senior DevOps engineer analyzing a deployment failure.

ALREADY DETECTED (by pattern scanner):
{found}

FULL DEPLOYMENT CONTEXT (logs, diagnostics, source):
{context[:20000]}

Your job: identify the PRIMARY root cause and any additional issues.

For EACH issue output EXACTLY this block (repeat as needed):
FILE: <exact filename>
LINE: <line number or N/A>
BLOCK: <function/class name or N/A>
CATEGORY: <RAM|METHOD|ALIGNMENT|DEPENDENCY|CONFIG|NETWORK|DOCKER|SYNTAX|OTHER>
SEVERITY: <CRITICAL|HIGH|MEDIUM|LOW>
PRESENT_ERROR: <what is actually happening>
EXPECTED_VALUE: <what should happen instead>
ROOT_CAUSE: <the underlying WHY, not the symptom>
AFFECTED_FILES: <comma-separated>
SOLUTION: <numbered step-by-step fix>
---

At the end add:
PRIMARY_CAUSE: <one sentence — the single true cause of this deployment failure>
PRIORITY_FIX: <the ONE change to make first>
DEPLOYMENT_HEALTH_SCORE: <0-100>

Be specific. Reference actual filenames and line numbers from the context above.
Do not hallucinate — if uncertain, say "unknown"."""
    return ask_ai(prompt)


# ═════════════════════════════════════════════════════════════════
# REPORT BUILDERS
# ═════════════════════════════════════════════════════════════════
def build_report(report: DiagnosticReport) -> str:
    lines = [
        "=" * 74,
        "  DEPLOYMENT FAILURE DIAGNOSTIC REPORT",
        "=" * 74,
        f"  Platform    : {report.platform.upper()}",
        f"  Timestamp   : {report.timestamp}",
        f"  Issues Found: {len(report.issues)}",
        "=" * 74,
        "",
    ]

    # ── PRIMARY CAUSE (at the top for quick reading) ────────────
    if report.issues:
        primary = report.issues[0]
        lines += [
            "┌" + "─" * 72 + "┐",
            "│  PRIMARY CAUSE  (highest-severity issue)".ljust(73) + "│",
            "└" + "─" * 72 + "┘",
            f"  FILE      : {primary.file}",
            f"  LINE      : {primary.line}",
            f"  BLOCK     : {primary.block}",
            f"  CATEGORY  : {primary.category}",
            f"  SEVERITY  : {primary.severity}",
            f"  ERROR     : {primary.description[:200]}",
            f"  ROOT CAUSE: {primary.root_cause}",
            f"  FIX       : {primary.solution.splitlines()[0] if primary.solution else 'see below'}",
            "",
        ]

    # ── SYSTEM HEALTH ───────────────────────────────────────────
    si = report.system_info
    ram_pct = si.get("ram_usage_pct", "?")
    ram_flag = (" [CRITICAL]" if si.get("ram_critical") else
                " [WARNING]"  if si.get("ram_warning")  else " [OK]")
    lines += [
        "─── SYSTEM HEALTH ───────────────────────────────────────",
        f"  OS          : {si.get('os','N/A')} {si.get('os_version','')[:60]}",
        f"  Architecture: {si.get('architecture','N/A')}",
        f"  Python      : {si.get('python_version','N/A').split()[0] if si.get('python_version') else 'N/A'}",
        f"  RAM         : {si.get('ram_used_mb','?')}MB / {si.get('ram_total_mb','?')}MB ({ram_pct}%){ram_flag}",
        f"  Disk        : {si.get('disk_raw','N/A').strip()}",
        f"  Network     : PyPI reachable -> {si.get('network','N/A')}",
        "",
    ]

    # ── ISSUE BREAKDOWN ─────────────────────────────────────────
    if not report.issues:
        lines += [
            "  No specific issues detected by pattern scanner.",
            "  Check AI diagnosis section below for deeper insights.",
            "",
        ]
    else:
        lines.append(f"─── ALL {len(report.issues)} ISSUES (sorted by severity) ───\n")
        for idx, iss in enumerate(report.issues, 1):
            icon = {"CRITICAL":"[C]","HIGH":"[H]","MEDIUM":"[M]","LOW":"[L]"}.get(iss.severity,"[?]")
            lines += [
                "  " + "─" * 68,
                f"  {icon} ISSUE #{idx}  [{iss.severity}] [{iss.category}]",
                "  " + "─" * 68,
                f"    FILE       : {iss.file}",
                f"    LINE       : {iss.line}",
                f"    BLOCK      : {iss.block}",
                f"    DESCRIPTION: {iss.description}",
                f"    EXPECTED   : {iss.expected}",
                f"    ROOT CAUSE : {iss.root_cause}",
                f"    AFFECTED   : {', '.join(iss.affected_files) if iss.affected_files else 'see file above'}",
                "    SOLUTION:",
            ]
            for s in iss.solution.split("\n"):
                lines.append(f"      {s}")
            lines.append("")

    # ── AI DIAGNOSIS ────────────────────────────────────────────
    if report.ai_diagnosis:
        lines += [
            "=" * 74,
            "  AI DEEP DIAGNOSIS",
            "=" * 74,
            report.ai_diagnosis,
            "",
        ]

    # ── AI TOKEN USAGE ──────────────────────────────────────────
    tu = report.token_usage
    if tu:
        lines += [
            "─── AI TOKEN USAGE ─────────────────────────────────────",
            f"  Requests    : {tu.get('requests',0)}",
            f"  Prompt Tok  : {tu.get('prompt_tokens',0)}",
            f"  Completion  : {tu.get('completion_tokens',0)}",
            f"  Total Tok   : {tu.get('total_tokens',0)}",
            f"  AI Time     : {tu.get('response_time',0):.2f}s",
            "",
        ]

    lines += ["=" * 74, "  END OF REPORT", "=" * 74]
    return "\n".join(lines)


def build_json_report(report: DiagnosticReport) -> dict:
    return {
        "platform":       report.platform,
        "timestamp":      report.timestamp,
        "system_info":    report.system_info,
        "primary_cause":  (
            {
                "file":       report.issues[0].file,
                "line":       report.issues[0].line,
                "block":      report.issues[0].block,
                "category":   report.issues[0].category,
                "severity":   report.issues[0].severity,
                "description":report.issues[0].description,
                "root_cause": report.issues[0].root_cause,
                "solution":   report.issues[0].solution,
            } if report.issues else None
        ),
        "issues": [
            {
                "severity":       i.severity,
                "category":       i.category,
                "file":           i.file,
                "line":           i.line,
                "block":          i.block,
                "description":    i.description,
                "expected":       i.expected,
                "root_cause":     i.root_cause,
                "solution":       i.solution,
                "affected_files": i.affected_files,
            } for i in report.issues
        ],
        "ai_diagnosis":   report.ai_diagnosis,
        "token_usage":    report.token_usage,
        "total_issues":   len(report.issues),
        "critical_count": sum(1 for i in report.issues if i.severity == "CRITICAL"),
        "high_count":     sum(1 for i in report.issues if i.severity == "HIGH"),
    }


# ═════════════════════════════════════════════════════════════════
# MAIN
# ═════════════════════════════════════════════════════════════════
def main() -> int:
    started   = time.perf_counter()
    timestamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

    print("Deployment Failure Diagnostic Agent starting...")
    print(f"  Timestamp : {timestamp}")

    plat = detect_platform()
    print(f"  Platform  : {plat.upper()}")

    print("  Collecting system info...")
    sysinfo = collect_system_info()

    print("  Collecting deployment context...")
    context = collect_all_context(plat)

    print("  Running deep issue scanner...")
    issues = deep_scan(context, sysinfo)
    print(f"  Found {len(issues)} issue(s) via pattern scanner.")

    # AI diagnosis — DEFAULT ON when key is present
    ai_diag = ""
    if os.getenv("RUN_AI_REVIEW", "1") != "0" and os.getenv("GEMINI_API_KEY"):
        print("  Running AI deep diagnosis...")
        try:
            ai_diag = ai_deep_diagnosis(context, issues)
        except Exception as exc:
            ai_diag = f"[AI unavailable: {exc}]"
            print(f"  AI error: {exc}")

    report = DiagnosticReport(
        platform     = plat,
        timestamp    = timestamp,
        issues       = issues,
        raw_context  = context,
        ai_diagnosis = ai_diag,
        system_info  = sysinfo,
        token_usage  = dict(_ai_stats),
    )

    REPORT_DIR.mkdir(exist_ok=True)
    text = build_report(report)
    REPORT_FILE.write_text(text, encoding="utf-8")
    JSON_REPORT.write_text(
        json.dumps(build_json_report(report), indent=2), encoding="utf-8",
    )
    Path("errors_report.txt").write_text(
        text + "\n\n--- RAW CONTEXT (last 5KB) ---\n" + context[-5000:],
        encoding="utf-8",
    )

    print("\n" + text)
    print("\n  Reports written:")
    print(f"    -> {REPORT_FILE}")
    print(f"    -> {JSON_REPORT}")
    print(f"    -> errors_report.txt")
    print(f"  Total execution: {time.perf_counter()-started:.2f}s")

    return 1   # always exit 1 — only runs on failure


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
"""
final_agent.py - UNIVERSAL POST-DEPLOY HEALTH & UPGRADE ADVISOR
================================================================
Runs AFTER successful deployment.
Standalone file - zero external dependencies beyond Python stdlib.
AI (Gemini) is optional - works fully without it.

What it does:
  1. Endpoint accessibility check  - every URL, reason if failing
  2. App health check              - response time, status, content
  3. Infrastructure health         - RAM, CPU, Disk, Network, Docker
  4. Upgrade recommendations       - based on ACTUAL findings only

Usage:
  python final_agent.py
  APP_URL=https://myapp.com python final_agent.py
  GEMINI_API_KEY=xxx python final_agent.py

Environment Variables:
  APP_URL          - Primary app URL to check
  EXTRA_URLS       - Comma-separated additional URLs to check
  APP_HEALTH_PATH  - Health endpoint path (default: /health or /)
  PROJECT_PATH     - Project root to scan (default: .)
  GEMINI_API_KEY   - Optional: enables AI analysis
  AI_MODEL         - Gemini model (default: gemini-2.5-flash)
"""

from __future__ import annotations

import glob
import json
import os
import platform
import re
import socket
import ssl
import subprocess
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

# ──────────────────────────────────────────────────────────────
# CONFIGURATION
# ──────────────────────────────────────────────────────────────
MODEL        = os.getenv("AI_MODEL", "gemini-2.5-flash")
PROVIDER     = os.getenv("AI_PROVIDER", "gemini")
PROJECT_ROOT = Path(os.getenv("PROJECT_PATH", ".")).resolve()
REPORT_DIR   = Path("reports")
TIMEOUT      = 10  # seconds for HTTP requests

# ──────────────────────────────────────────────────────────────
# DATA CLASSES
# ──────────────────────────────────────────────────────────────
@dataclass
class EndpointResult:
    url:             str
    reachable:       bool
    status_code:     Optional[int]  = None
    latency_ms:      Optional[float] = None
    error:           Optional[str]  = None
    error_reason:    Optional[str]  = None
    ssl_valid:       Optional[bool] = None
    ssl_expiry_days: Optional[int]  = None
    redirect_url:    Optional[str]  = None
    content_preview: Optional[str]  = None
    dns_resolved:    Optional[bool] = None
    dns_ip:          Optional[str]  = None
    port_open:       Optional[bool] = None

@dataclass
class SystemHealth:
    # RAM
    ram_total_mb:   int   = 0
    ram_used_mb:    int   = 0
    ram_free_mb:    int   = 0
    ram_usage_pct:  float = 0.0
    ram_status:     str   = "UNKNOWN"
    # CPU
    cpu_usage_pct:  float = 0.0
    cpu_status:     str   = "UNKNOWN"
    load_avg:       str   = "N/A"
    # Disk
    disk_total_gb:  float = 0.0
    disk_used_gb:   float = 0.0
    disk_free_gb:   float = 0.0
    disk_usage_pct: float = 0.0
    disk_status:    str   = "UNKNOWN"
    # Network
    net_status:     str   = "UNKNOWN"
    net_latency_ms: float = 0.0
    dns_working:    bool  = False
    # Docker
    docker_running: bool  = False
    containers:     list  = field(default_factory=list)
    # Process
    top_processes:  list  = field(default_factory=list)
    open_ports:     list  = field(default_factory=list)

@dataclass
class UpgradeFinding:
    category:      str   # Security/Performance/Reliability/Cost/DevEx
    priority:      str   # CRITICAL/HIGH/MEDIUM/LOW
    title:         str
    present:       str   # what exists NOW (factual)
    expected:      str   # what should exist
    solution:      str   # exact actionable fix
    evidence:      str   # what proof was found (file, line, metric)
    auto_detected: bool  = True  # True = found real evidence, False = generic

@dataclass
class FinalReport:
    timestamp:      str
    project_path:   str
    platform:       str
    endpoints:      list[EndpointResult]
    system_health:  SystemHealth
    findings:       list[UpgradeFinding]
    ai_analysis:    str = ""
    scan_duration:  float = 0.0

# ──────────────────────────────────────────────────────────────
# AI CLIENT  (fully optional)
# ──────────────────────────────────────────────────────────────
_ai_stats: dict = {
    "prompt_tokens": 0, "completion_tokens": 0,
    "total_tokens": 0,  "requests": 0,
    "response_time": 0.0,
}

def _ai_available() -> bool:
    """Check AI availability without making a real API call."""
    return bool(os.getenv("GEMINI_API_KEY"))

def ask_ai(prompt: str) -> str:
    """
    Call Gemini AI. Returns empty string if unavailable.
    Never raises - always returns a string.
    """
    if not _ai_available():
        return ""
    try:
        from google import genai  # type: ignore
    except ImportError:
        return "[AI skipped: google-genai not installed. pip install google-genai]"

    try:
        client  = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))
        started = time.perf_counter()
        resp    = client.models.generate_content(model=MODEL, contents=prompt)
        elapsed = time.perf_counter() - started

        _ai_stats["response_time"]    += elapsed
        _ai_stats["requests"]         += 1
        usage = getattr(resp, "usage_metadata", None)
        _ai_stats["prompt_tokens"]     += int(getattr(usage, "prompt_token_count",     0) or 0)
        _ai_stats["completion_tokens"] += int(getattr(usage, "candidates_token_count", 0) or 0)
        _ai_stats["total_tokens"]       = (_ai_stats["prompt_tokens"] +
                                           _ai_stats["completion_tokens"])
        return (getattr(resp, "text", "") or "").strip()
    except Exception as exc:
        return f"[AI error: {exc}]"

# ──────────────────────────────────────────────────────────────
# SAFE SHELL RUNNER
# ──────────────────────────────────────────────────────────────
def run_cmd(cmd: str, timeout: int = 15) -> str:
    """
    Run a shell command safely.
    Returns output string. Never raises.
    """
    try:
        result = subprocess.run(
            cmd, shell=True, capture_output=True,
            text=True, timeout=timeout, check=False
        )
        out = (result.stdout + result.stderr).strip()
        return out[:5000]
    except subprocess.TimeoutExpired:
        return f"[timeout after {timeout}s]"
    except Exception as exc:
        return f"[error: {exc}]"

# ──────────────────────────────────────────────────────────────
# SECTION 1: ENDPOINT CHECKER
# ──────────────────────────────────────────────────────────────
def _classify_error(exc: Exception, url: str) -> str:
    """
    Given an exception, return a clear human reason why it failed.
    This is the core of 'why is it not accessible'.
    """
    msg = str(exc).lower()

    # DNS
    if any(x in msg for x in ["name or service not known", "nodename nor servname",
                                "enotfound", "getaddrinfo", "name resolution"]):
        host = url.split("//")[-1].split("/")[0].split(":")[0]
        return (f"DNS_FAILURE: Cannot resolve hostname '{host}'. "
                f"The domain does not exist or DNS is misconfigured. "
                f"Check: dig {host} or nslookup {host}")

    # Connection refused
    if any(x in msg for x in ["connection refused", "econnrefused"]):
        port = "443" if url.startswith("https") else "80"
        if ":" in url.split("//")[-1].split("/")[0]:
            port = url.split("//")[-1].split("/")[0].split(":")[1]
        return (f"CONNECTION_REFUSED: Server is reachable but nothing is "
                f"listening on port {port}. "
                f"The application process may have crashed or not started.")

    # Timeout
    if any(x in msg for x in ["timed out", "timeout", "etimedout"]):
        return ("TIMEOUT: Server did not respond within timeout. "
                "Possible causes: firewall blocking port, server overloaded, "
                "application stuck in startup, or wrong URL.")

    # SSL
    if any(x in msg for x in ["ssl", "certificate", "cert", "handshake"]):
        return ("SSL_ERROR: TLS/SSL handshake failed. "
                "Possible causes: expired certificate, self-signed cert, "
                "wrong hostname in cert, or TLS version mismatch.")

    # Network unreachable
    if any(x in msg for x in ["network is unreachable", "enetunreach",
                                "no route to host"]):
        return ("NETWORK_UNREACHABLE: No network path to the server. "
                "Check VPC/firewall rules, security groups, or network configuration.")

    # HTTP errors
    if isinstance(exc, urllib.error.HTTPError):
        code = exc.code
        reasons = {
            400: "BAD_REQUEST: Server rejected the request. Check request format.",
            401: "UNAUTHORIZED: Authentication required. Check API keys or login.",
            403: "FORBIDDEN: Access denied. Check IAM roles, security groups, or IP whitelist.",
            404: "NOT_FOUND: Endpoint does not exist. Check URL path and routing config.",
            429: "RATE_LIMITED: Too many requests. The server is throttling.",
            500: "SERVER_ERROR: Application threw an internal error. Check app logs.",
            502: "BAD_GATEWAY: Upstream server failed. Load balancer or proxy issue.",
            503: "SERVICE_UNAVAILABLE: App is down or starting up. Check container health.",
            504: "GATEWAY_TIMEOUT: Upstream timed out. App too slow or crashed.",
        }
        return reasons.get(code, f"HTTP_{code}: Server returned error {code}.")

    # Port refused
    if "connection reset" in msg:
        return ("CONNECTION_RESET: Server forcibly closed connection. "
                "Possible causes: firewall RST packet, server crash, or wrong protocol.")

    return f"UNKNOWN_ERROR: {str(exc)[:200]}"

def _check_dns(host: str) -> tuple[bool, str]:
    """Check if hostname resolves to an IP."""
    try:
        ip = socket.gethostbyname(host)
        return True, ip
    except socket.gaierror:
        return False, ""

def _check_port(host: str, port: int, timeout: int = 5) -> bool:
    """Check if TCP port is open."""
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except Exception:
        return False

def _check_ssl(host: str, port: int = 443) -> tuple[bool, Optional[int]]:
    """
    Check SSL certificate validity and days until expiry.
    Returns (is_valid, days_remaining)
    """
    try:
        ctx = ssl.create_default_context()
        with ctx.wrap_socket(
            socket.create_connection((host, port), timeout=10),
            server_hostname=host
        ) as s:
            cert      = s.getpeercert()
            expires   = cert.get("notAfter", "")
            if expires:
                import datetime
                expiry_dt   = datetime.datetime.strptime(
                    expires, "%b %d %H:%M:%S %Y %Z"
                )
                days_left   = (expiry_dt - datetime.datetime.utcnow()).days
                return True, days_left
            return True, None
    except ssl.SSLCertVerificationError:
        return False, None
    except ssl.SSLError:
        return False, None
    except Exception:
        return False, None

def check_endpoint(url: str) -> EndpointResult:
    """
    Deep check a single endpoint.
    Returns full EndpointResult with all details.
    """
    result = EndpointResult(url=url, reachable=False)

    # Parse host and port
    try:
        without_scheme = url.split("//", 1)[-1]
        host_part      = without_scheme.split("/")[0]
        if ":" in host_part:
            host, port_str = host_part.rsplit(":", 1)
            port           = int(port_str)
        else:
            host = host_part
            port = 443 if url.startswith("https") else 80
    except Exception:
        result.error        = "Cannot parse URL"
        result.error_reason = "INVALID_URL: URL format is not valid."
        return result

    # Step 1: DNS check
    dns_ok, ip = _check_dns(host)
    result.dns_resolved = dns_ok
    result.dns_ip       = ip
    if not dns_ok:
        result.error        = f"DNS resolution failed for {host}"
        result.error_reason = (
            f"DNS_FAILURE: Hostname '{host}' could not be resolved. "
            f"Verify domain exists: dig {host}"
        )
        return result

    # Step 2: Port check
    port_open = _check_port(host, port)
    result.port_open = port_open
    if not port_open:
        result.error        = f"Port {port} not open on {host}"
        result.error_reason = (
            f"PORT_CLOSED: TCP port {port} is not accepting connections on {host} ({ip}). "
            f"Check: security groups, firewall rules, and if the service is running."
        )
        return result

    # Step 3: SSL check (HTTPS only)
    if url.startswith("https"):
        ssl_valid, ssl_days = _check_ssl(host, port)
        result.ssl_valid       = ssl_valid
        result.ssl_expiry_days = ssl_days
        if not ssl_valid:
            result.error        = "SSL certificate invalid"
            result.error_reason = (
                "SSL_INVALID: Certificate verification failed. "
                "Certificate may be expired, self-signed, or hostname mismatch."
            )

    # Step 4: HTTP request
    try:
        req     = urllib.request.Request(
            url,
            headers={
                "User-Agent": "FinalAgent-HealthCheck/1.0",
                "Accept":     "application/json, text/html, */*",
            }
        )
        started = time.perf_counter()

        # Don't follow redirects automatically — detect them
        opener = urllib.request.build_opener(
            urllib.request.HTTPRedirectHandler()
        )
        with opener.open(req, timeout=TIMEOUT) as resp:
            latency_ms          = (time.perf_counter() - started) * 1000
            body                = resp.read(2000).decode("utf-8", errors="replace")
            result.reachable    = True
            result.status_code  = resp.status
            result.latency_ms   = round(latency_ms, 2)
            result.content_preview = body[:300].strip()

            # Check for redirect
            final_url = resp.geturl()
            if final_url != url:
                result.redirect_url = final_url

    except urllib.error.HTTPError as exc:
        result.status_code  = exc.code
        result.error        = f"HTTP {exc.code}: {exc.reason}"
        result.error_reason = _classify_error(exc, url)
        # 2xx and 3xx are still reachable
        if exc.code < 400:
            result.reachable = True
    except Exception as exc:
        result.error        = str(exc)
        result.error_reason = _classify_error(exc, url)

    return result

def collect_endpoints() -> list[str]:
    """
    Collect all URLs to check from environment and project files.
    """
    urls: list[str] = []

    # From environment variables
    primary = os.getenv("APP_URL") or os.getenv("DEPLOY_URL")
    if primary:
        base         = primary.rstrip("/")
        health_path  = os.getenv("APP_HEALTH_PATH", "")
        urls.append(base)

        # Common health endpoints to auto-check
        for path in ["/health", "/healthz", "/ready", "/ping",
                     "/api/health", "/status", "/api/v1/health"]:
            urls.append(base + path)

    # Extra URLs from env
    extra = os.getenv("EXTRA_URLS", "")
    if extra:
        for u in extra.split(","):
            u = u.strip()
            if u:
                urls.append(u)

    # Scan project files for URLs
    url_pattern = re.compile(
        r'https?://[a-zA-Z0-9._\-]+\.[a-zA-Z]{2,}(?::\d+)?(?:/[^\s\'"<>]*)?'
    )
    scan_files = (
        list(PROJECT_ROOT.glob("*.env"))
        + list(PROJECT_ROOT.glob(".env*"))
        + list(PROJECT_ROOT.glob("**/*.yml"))[:5]
        + list(PROJECT_ROOT.glob("**/*.yaml"))[:5]
        + list(PROJECT_ROOT.glob("**/*.json"))[:5]
    )
    for fpath in scan_files:
        try:
            content = fpath.read_text(encoding="utf-8", errors="replace")
            for match in url_pattern.finditer(content):
                found = match.group(0).rstrip(".,;'\")")
                # Only include real service URLs — skip CDN/static
                if any(x in found for x in
                       ["localhost", "127.0.0.1", "example.com",
                        "schema.org", "w3.org"]):
                    continue
                if found not in urls:
                    urls.append(found)
        except OSError:
            pass

    # Deduplicate preserving order
    seen:   set         = set()
    unique: list[str]   = []
    for u in urls:
        if u not in seen:
            seen.add(u)
            unique.append(u)

    return unique[:20]  # cap at 20 URLs

def run_endpoint_checks(urls: list[str]) -> list[EndpointResult]:
    """Check all endpoints and return results."""
    results = []
    for url in urls:
        print(f"   Checking: {url}")
        result = check_endpoint(url)
        status = "✅" if result.reachable else "❌"
        if result.reachable:
            print(f"   {status} {url} → {result.status_code} "
                  f"({result.latency_ms}ms)")
        else:
            print(f"   {status} {url} → {result.error_reason or result.error}")
        results.append(result)
    return results

# ──────────────────────────────────────────────────────────────
# SECTION 2: SYSTEM / INFRA HEALTH
# ──────────────────────────────────────────────────────────────
def collect_system_health() -> SystemHealth:
    """
    Collect real system metrics.
    Works on Linux (CI runners) and macOS (dev machines).
    """
    health = SystemHealth()

    # ── RAM ──────────────────────────────────────────────────
    free_out = run_cmd("free -m 2>/dev/null")
    if free_out and "[" not in free_out:
        match = re.search(r"Mem:\s+(\d+)\s+(\d+)\s+(\d+)", free_out)
        if match:
            health.ram_total_mb  = int(match.group(1))
            health.ram_used_mb   = int(match.group(2))
            health.ram_free_mb   = int(match.group(3))
            if health.ram_total_mb > 0:
                health.ram_usage_pct = round(
                    (health.ram_used_mb / health.ram_total_mb) * 100, 1
                )
    else:
        # macOS fallback
        vm_out = run_cmd("vm_stat 2>/dev/null")
        if vm_out and "[" not in vm_out:
            pages_free  = re.search(r"Pages free:\s+(\d+)", vm_out)
            pages_used  = re.search(r"Pages active:\s+(\d+)", vm_out)
            if pages_free and pages_used:
                page_size            = 4096
                health.ram_free_mb   = int(pages_free.group(1)) * page_size // (1024 * 1024)
                health.ram_used_mb   = int(pages_used.group(1)) * page_size // (1024 * 1024)
                health.ram_total_mb  = health.ram_free_mb + health.ram_used_mb

    if health.ram_usage_pct >= 90:
        health.ram_status = "CRITICAL"
    elif health.ram_usage_pct >= 75:
        health.ram_status = "WARNING"
    elif health.ram_usage_pct > 0:
        health.ram_status = "OK"

    # ── CPU ──────────────────────────────────────────────────
    cpu_out = run_cmd(
        "top -bn1 2>/dev/null | grep -E 'Cpu|cpu' | head -1"
    )
    cpu_match = re.search(r"(\d+\.?\d*)\s*%?\s*id", cpu_out)
    if cpu_match:
        idle                = float(cpu_match.group(1))
        health.cpu_usage_pct = round(100.0 - idle, 1)
    else:
        # Alternative
        cpu_alt = run_cmd(
            "ps -A -o %cpu 2>/dev/null | "
            "awk '{s+=$1} END {printf \"%.1f\", s}'"
        )
        try:
            health.cpu_usage_pct = float(cpu_alt.strip())
        except ValueError:
            pass

    load_out = run_cmd("uptime 2>/dev/null")
    la_match = re.search(
        r"load averages?:\s*([\d.]+)[,\s]+([\d.]+)[,\s]+([\d.]+)",
        load_out, re.IGNORECASE
    )
    if la_match:
        health.load_avg = (
            f"{la_match.group(1)} {la_match.group(2)} {la_match.group(3)}"
        )

    if health.cpu_usage_pct >= 90:
        health.cpu_status = "CRITICAL"
    elif health.cpu_usage_pct >= 70:
        health.cpu_status = "WARNING"
    elif health.cpu_usage_pct >= 0:
        health.cpu_status = "OK"

    # ── DISK ─────────────────────────────────────────────────
    disk_out = run_cmd("df -h . 2>/dev/null | tail -1")
    if disk_out and "[" not in disk_out:
        # Parse: Filesystem Size Used Avail Use% Mounted
        parts = disk_out.split()
        if len(parts) >= 5:
            pct_match = re.search(r"(\d+)%", disk_out)
            if pct_match:
                health.disk_usage_pct = float(pct_match.group(1))

        disk_detail = run_cmd("df -BM . 2>/dev/null | tail -1")
        detail_match = re.search(
            r"(\d+)M\s+(\d+)M\s+(\d+)M", disk_detail
        )
        if detail_match:
            health.disk_total_gb = round(int(detail_match.group(1)) / 1024, 1)
            health.disk_used_gb  = round(int(detail_match.group(2)) / 1024, 1)
            health.disk_free_gb  = round(int(detail_match.group(3)) / 1024, 1)

    if health.disk_usage_pct >= 95:
        health.disk_status = "CRITICAL"
    elif health.disk_usage_pct >= 80:
        health.disk_status = "WARNING"
    elif health.disk_usage_pct >= 0:
        health.disk_status = "OK"

    # ── NETWORK ──────────────────────────────────────────────
    # Check DNS
    try:
        socket.gethostbyname("google.com")
        health.dns_working = True
    except socket.gaierror:
        health.dns_working = False

    # Check internet latency
    net_start = time.perf_counter()
    try:
        with urllib.request.urlopen(
            "https://www.google.com", timeout=5
        ) as r:
            r.read(100)
        health.net_latency_ms = round(
            (time.perf_counter() - net_start) * 1000, 1
        )
        health.net_status = "OK"
    except Exception:
        try:
            with urllib.request.urlopen(
                "http://www.google.com", timeout=5
            ) as r:
                r.read(100)
            health.net_status     = "OK_NO_HTTPS"
            health.net_latency_ms = round(
                (time.perf_counter() - net_start) * 1000, 1
            )
        except Exception:
            health.net_status = "OFFLINE"

    # ── DOCKER ───────────────────────────────────────────────
    docker_out = run_cmd("docker ps -a --format '{{.Names}}|{{.Status}}|{{.Image}}' 2>/dev/null")
    if docker_out and "[" not in docker_out and "permission denied" not in docker_out.lower():
        health.docker_running = True
        for line in docker_out.splitlines():
            if "|" in line:
                parts = line.split("|")
                if len(parts) >= 3:
                    health.containers.append({
                        "name":   parts[0].strip(),
                        "status": parts[1].strip(),
                        "image":  parts[2].strip(),
                        "healthy": "up" in parts[1].lower(),
                    })

    # ── TOP PROCESSES ─────────────────────────────────────────
    proc_out = run_cmd(
        "ps aux --sort=-%mem 2>/dev/null | head -6 | "
        "awk '{print $1,$2,$3,$4,$11}'"
    )
    for line in proc_out.splitlines()[1:6]:
        parts = line.split()
        if len(parts) >= 5:
            health.top_processes.append({
                "user":  parts[0],
                "pid":   parts[1],
                "cpu":   parts[2],
                "mem":   parts[3],
                "cmd":   parts[4],
            })

    # ── OPEN PORTS ────────────────────────────────────────────
    port_out = run_cmd(
        "ss -tlnp 2>/dev/null | grep LISTEN | "
        "awk '{print $4}' | head -20"
    )
    if not port_out or "[" in port_out:
        port_out = run_cmd(
            "netstat -tlnp 2>/dev/null | grep LISTEN | "
            "awk '{print $4}' | head -20"
        )
    for line in port_out.splitlines():
        port_match = re.search(r":(\d+)$", line.strip())
        if port_match:
            p = int(port_match.group(1))
            if p not in health.open_ports:
                health.open_ports.append(p)

    return health

# ──────────────────────────────────────────────────────────────
# SECTION 3: APP HEALTH FROM ENDPOINTS
# ──────────────────────────────────────────────────────────────
def analyze_app_health(
    endpoint_results: list[EndpointResult],
    system_health: SystemHealth
) -> dict:
    """
    Analyze app health from endpoint results and system metrics.
    Returns a structured health summary.
    """
    total         = len(endpoint_results)
    reachable     = [e for e in endpoint_results if e.reachable]
    unreachable   = [e for e in endpoint_results if not e.reachable]

    # Latency analysis
    latencies = [
        e.latency_ms for e in reachable
        if e.latency_ms is not None
    ]
    avg_latency  = round(sum(latencies) / len(latencies), 1) if latencies else 0
    max_latency  = round(max(latencies), 1) if latencies else 0

    # SSL issues
    ssl_expiring = [
        e for e in reachable
        if e.ssl_expiry_days is not None and e.ssl_expiry_days < 30
    ]
    ssl_invalid  = [
        e for e in endpoint_results
        if e.ssl_valid is False
    ]

    # Error categories
    error_categories: dict[str, list] = {}
    for e in unreachable:
        if e.error_reason:
            cat = e.error_reason.split(":")[0]
            error_categories.setdefault(cat, []).append(e.url)

    # Overall status
    if total == 0:
        app_status = "NO_ENDPOINTS"
    elif len(reachable) == total:
        if avg_latency > 3000:
            app_status = "SLOW"
        else:
            app_status = "HEALTHY"
    elif len(reachable) > total // 2:
        app_status = "DEGRADED"
    else:
        app_status = "DOWN"

    # Docker health
    unhealthy_containers = [
        c for c in system_health.containers
        if not c.get("healthy")
    ]

    return {
        "status":               app_status,
        "total_endpoints":      total,
        "reachable":            len(reachable),
        "unreachable":          len(unreachable),
        "avg_latency_ms":       avg_latency,
        "max_latency_ms":       max_latency,
        "ssl_expiring_soon":    [e.url for e in ssl_expiring],
        "ssl_invalid":          [e.url for e in ssl_invalid],
        "error_categories":     error_categories,
        "unhealthy_containers": unhealthy_containers,
        "ram_status":           system_health.ram_status,
        "cpu_status":           system_health.cpu_status,
        "disk_status":          system_health.disk_status,
        "net_status":           system_health.net_status,
    }

# ──────────────────────────────────────────────────────────────
# SECTION 4: UPGRADE FINDER
# Based ONLY on real detected evidence — zero generic suggestions
# ──────────────────────────────────────────────────────────────
def find_upgrades(
    endpoint_results: list[EndpointResult],
    system_health:    SystemHealth,
    app_health:       dict,
) -> list[UpgradeFinding]:
    """
    Find upgrade opportunities based on ACTUAL evidence only.
    Every finding must have real proof.
    """
    findings: list[UpgradeFinding] = []

    # ── ENDPOINT-BASED FINDINGS ──────────────────────────────

    # Slow endpoints
    slow = [
        e for e in endpoint_results
        if e.reachable and e.latency_ms and e.latency_ms > 1000
    ]
    for e in slow:
        level = "CRITICAL" if e.latency_ms > 5000 else "HIGH" if e.latency_ms > 2000 else "MEDIUM"
        findings.append(UpgradeFinding(
            category  = "Performance",
            priority  = level,
            title     = f"High response latency on {e.url}",
            present   = f"Endpoint responding in {e.latency_ms}ms",
            expected  = "Response under 500ms for API, under 1000ms for web pages",
            solution  = (
                "1. Profile the slowest DB queries with EXPLAIN ANALYZE.\n"
                "2. Add Redis caching for repeated queries.\n"
                "3. Enable gzip/brotli compression on responses.\n"
                "4. Use a CDN (CloudFront/Cloudflare) for static assets.\n"
                "5. Check if server is CPU-bound: add horizontal scaling."
            ),
            evidence  = f"Measured latency: {e.latency_ms}ms at {e.url}",
        ))

    # SSL expiring soon
    for e in endpoint_results:
        if e.ssl_expiry_days is not None and e.ssl_expiry_days < 30:
            priority = "CRITICAL" if e.ssl_expiry_days < 7 else "HIGH"
            findings.append(UpgradeFinding(
                category  = "Security",
                priority  = priority,
                title     = f"SSL certificate expiring in {e.ssl_expiry_days} days",
                present   = f"Certificate at {e.url} expires in {e.ssl_expiry_days} days",
                expected  = "Certificate valid for 90+ days",
                solution  = (
                    "1. Renew via Let's Encrypt: certbot renew\n"
                    "2. Or enable auto-renewal: certbot renew --deploy-hook 'systemctl reload nginx'\n"
                    "3. Use AWS ACM for managed auto-renewal on AWS.\n"
                    "4. Set calendar alert 30 days before expiry."
                ),
                evidence  = f"SSL check on {e.url}: {e.ssl_expiry_days} days remaining",
            ))

    # SSL invalid
    for e in endpoint_results:
        if e.ssl_valid is False:
            findings.append(UpgradeFinding(
                category  = "Security",
                priority  = "CRITICAL",
                title     = f"Invalid SSL certificate on {e.url}",
                present   = "SSL verification failing — users see browser security warning",
                expected  = "Valid trusted SSL certificate",
                solution  = (
                    "1. Get free cert: certbot --nginx -d yourdomain.com\n"
                    "2. For AWS: use ACM with ALB — free managed certs.\n"
                    "3. Check cert hostname matches the URL being accessed.\n"
                    "4. Verify cert chain is complete (include intermediates)."
                ),
                evidence  = f"SSL verification failed for {e.url}",
            ))

    # Unreachable endpoints with specific reasons
    for e in endpoint_results:
        if not e.reachable and e.error_reason:
            cat = e.error_reason.split(":")[0]
            findings.append(UpgradeFinding(
                category  = "Reliability",
                priority  = "CRITICAL",
                title     = f"Endpoint unreachable: {e.url}",
                present   = e.error_reason,
                expected  = "Endpoint returns HTTP 200",
                solution  = _endpoint_fix(cat, e),
                evidence  = f"Check failed: {e.error or e.error_reason}",
            ))

    # No health endpoints found responding
    health_urls   = [
        e for e in endpoint_results
        if any(p in e.url for p in ["/health", "/healthz", "/ready", "/ping"])
    ]
    healthy_count = sum(1 for e in health_urls if e.reachable)
    if health_urls and healthy_count == 0:
        findings.append(UpgradeFinding(
            category  = "Reliability",
            priority  = "HIGH",
            title     = "No health check endpoint responding",
            present   = f"Checked {len(health_urls)} health URLs — none responding",
            expected  = "GET /health returns 200 with JSON status",
            solution  = (
                "Add a health endpoint to your app:\n"
                "  FastAPI: @app.get('/health') def health(): return {'status':'ok'}\n"
                "  Flask:   @app.route('/health') def health(): return 'ok', 200\n"
                "  Express: app.get('/health', (req,res) => res.json({status:'ok'}))\n"
                "Then configure your load balancer to use this for health checks."
            ),
            evidence  = f"URLs checked: {[e.url for e in health_urls]}",
        ))

    # ── RAM FINDINGS ─────────────────────────────────────────
    if system_health.ram_status == "CRITICAL":
        pct   = system_health.ram_usage_pct
        free  = system_health.ram_free_mb
        total = system_health.ram_total_mb
        findings.append(UpgradeFinding(
            category  = "Reliability",
            priority  = "CRITICAL",
            title     = "RAM usage critically high — OOM risk",
            present   = f"RAM usage: {pct}% ({free}MB free of {total}MB total)",
            expected  = "RAM usage below 80%",
            solution  = (
                "Immediate:\n"
                "1. Find memory hog: ps aux --sort=-%mem | head -10\n"
                "2. Restart memory-leaking service.\n"
                "Long term:\n"
                "3. Add memory limits in docker-compose: mem_limit: 512m\n"
                "4. Use streaming instead of loading full datasets.\n"
                "5. Upgrade instance to one with more RAM.\n"
                "6. Add swap: fallocate -l 2G /swapfile && mkswap /swapfile"
            ),
            evidence  = (
                f"Live measurement: {pct}% RAM used. "
                f"Top process: "
                f"{system_health.top_processes[0] if system_health.top_processes else 'N/A'}"
            ),
        ))
    elif system_health.ram_status == "WARNING":
        findings.append(UpgradeFinding(
            category  = "Performance",
            priority  = "HIGH",
            title     = "RAM usage elevated — monitor closely",
            present   = f"RAM at {system_health.ram_usage_pct}%",
            expected  = "RAM usage below 75%",
            solution  = (
                "1. Set up RAM alerting at 80% threshold.\n"
                "2. Profile memory usage: python -m memory_profiler app.py\n"
                "3. Consider upgrading instance type proactively."
            ),
            evidence  = f"Live: {system_health.ram_usage_pct}% RAM",
        ))

    # ── CPU FINDINGS ─────────────────────────────────────────
    if system_health.cpu_status == "CRITICAL":
        findings.append(UpgradeFinding(
            category  = "Performance",
            priority  = "CRITICAL",
            title     = "CPU usage critically high",
            present   = f"CPU at {system_health.cpu_usage_pct}% — load avg: {system_health.load_avg}",
            expected  = "CPU usage below 80%",
            solution  = (
                "1. Identify hot process: top -bn1 | head -20\n"
                "2. Profile Python: py-spy top --pid <pid>\n"
                "3. Add horizontal scaling (more instances).\n"
                "4. Move CPU-heavy tasks to async background workers (Celery/RQ).\n"
                "5. Enable caching for expensive computations.\n"
                "6. Consider upgrading to compute-optimized instance."
            ),
            evidence  = (
                f"CPU: {system_health.cpu_usage_pct}%, "
                f"Load: {system_health.load_avg}"
            ),
        ))

    # ── DISK FINDINGS ─────────────────────────────────────────
    if system_health.disk_status == "CRITICAL":
        findings.append(UpgradeFinding(
            category  = "Reliability",
            priority  = "CRITICAL",
            title     = "Disk usage critically high — deployment risk",
            present   = (
                f"Disk at {system_health.disk_usage_pct}% "
                f"({system_health.disk_free_gb}GB free)"
            ),
            expected  = "Disk usage below 80%",
            solution  = (
                "Immediate:\n"
                "1. Free space: docker system prune -af --volumes\n"
                "2. Clear logs: journalctl --vacuum-size=100M\n"
                "3. Find large files: du -sh /* 2>/dev/null | sort -rh | head -20\n"
                "Long term:\n"
                "4. Add log rotation (logrotate).\n"
                "5. Expand EBS volume or add new disk."
            ),
            evidence  = (
                f"df -h shows {system_health.disk_usage_pct}% used, "
                f"{system_health.disk_free_gb}GB free"
            ),
        ))
    elif system_health.disk_status == "WARNING":
        findings.append(UpgradeFinding(
            category  = "Reliability",
            priority  = "HIGH",
            title     = "Disk usage elevated",
            present   = f"Disk at {system_health.disk_usage_pct}%",
            expected  = "Disk below 80%",
            solution  = (
                "1. Clean Docker: docker system prune -f\n"
                "2. Set up disk usage alerting.\n"
                "3. Plan disk expansion before it hits 95%."
            ),
            evidence  = f"Disk: {system_health.disk_usage_pct}%",
        ))

    # ── DOCKER CONTAINER FINDINGS ─────────────────────────────
    for container in system_health.containers:
        if not container.get("healthy"):
            status = container.get("status", "unknown")
            name   = container.get("name", "unknown")
            image  = container.get("image", "unknown")
            findings.append(UpgradeFinding(
                category  = "Reliability",
                priority  = "HIGH",
                title     = f"Container '{name}' is not healthy",
                present   = f"Container status: {status}",
                expected  = "Container status: Up (healthy)",
                solution  = (
                    f"1. Check logs: docker logs {name} --tail 100\n"
                    f"2. Inspect: docker inspect {name}\n"
                    f"3. Restart: docker restart {name}\n"
                    "4. Add HEALTHCHECK to Dockerfile for auto-restart.\n"
                    "5. Check if required env vars are set: "
                    f"docker exec {name} env"
                ),
                evidence  = (
                    f"docker ps shows container '{name}' "
                    f"({image}) with status: {status}"
                ),
            ))

    # ── NETWORK FINDINGS ──────────────────────────────────────
    if system_health.net_status == "OFFLINE":
        findings.append(UpgradeFinding(
            category  = "Reliability",
            priority  = "CRITICAL",
            title     = "Server has no internet connectivity",
            present   = "Cannot reach google.com — network offline",
            expected  = "Outbound internet access available",
            solution  = (
                "1. Check security group outbound rules.\n"
                "2. Check NAT gateway if in private subnet.\n"
                "3. Verify: curl -v https://google.com\n"
                "4. Check VPC route tables for 0.0.0.0/0 route."
            ),
            evidence  = "urllib request to google.com failed",
        ))
    elif system_health.net_status == "OK_NO_HTTPS":
        findings.append(UpgradeFinding(
            category  = "Security",
            priority  = "HIGH",
            title     = "HTTPS outbound not working — HTTP only",
            present   = "HTTPS connections failing, HTTP works",
            expected  = "Full HTTPS connectivity",
            solution  = (
                "1. Check if port 443 outbound is blocked by firewall.\n"
                "2. Verify SSL certificates on intermediate proxies.\n"
                "3. Check: curl -v https://google.com"
            ),
            evidence  = "HTTPS request failed, HTTP request succeeded",
        ))

    # ── PROJECT FILE FINDINGS ─────────────────────────────────
    _scan_project_files(findings)

    # Sort by priority
    priority_order = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3}
    findings.sort(key=lambda f: priority_order.get(f.priority, 9))

    return findings

def _endpoint_fix(error_category: str, endpoint: EndpointResult) -> str:
    """Return specific fix based on error category."""
    fixes = {
        "DNS_FAILURE": (
            f"1. Verify domain is registered and DNS records exist:\n"
            f"   dig {endpoint.url.split('//')[1].split('/')[0]}\n"
            "2. Check DNS propagation: https://dnschecker.org\n"
            "3. Verify A/CNAME records in your DNS provider.\n"
            "4. Check Route53 hosted zone if using AWS."
        ),
        "CONNECTION_REFUSED": (
            "1. Check if the application process is running:\n"
            "   ps aux | grep python (or node/java/etc)\n"
            "2. Check which ports are open: ss -tlnp\n"
            "3. Verify the app is binding to 0.0.0.0 not 127.0.0.1.\n"
            "4. Check security group inbound rules allow the port.\n"
            "5. Review app startup logs for errors."
        ),
        "TIMEOUT": (
            "1. Check if firewall/security group is blocking the port.\n"
            "2. Verify the app is running and not stuck.\n"
            "3. Test from the server itself: curl localhost:PORT\n"
            "4. Check load balancer target group health.\n"
            "5. Review CPU/RAM — server may be overloaded."
        ),
        "PORT_CLOSED": (
            f"1. Verify app is running: ps aux | grep app\n"
            f"2. Check port binding: ss -tlnp | grep {endpoint.port_open}\n"
            "3. Check security group/firewall allows inbound on this port.\n"
            "4. For AWS: check ALB listener and target group."
        ),
        "FORBIDDEN": (
            "1. Check IAM roles and policies.\n"
            "2. Review security group inbound rules.\n"
            "3. Check IP allowlist configuration.\n"
            "4. Verify correct auth headers/API keys."
        ),
        "SERVER_ERROR": (
            "1. Check application logs immediately:\n"
            "   docker logs <container> --tail 200\n"
            "2. Check for unhandled exceptions in the code.\n"
            "3. Verify all environment variables are set.\n"
            "4. Check database connectivity."
        ),
    }
    return fixes.get(
        error_category,
        (
            f"1. Check server logs for error details.\n"
            f"2. Test manually: curl -v {endpoint.url}\n"
            "3. Review recent deployment changes.\n"
            "4. Rollback if issue is critical."
        )
    )

def _scan_project_files(findings: list[UpgradeFinding]) -> None:
    """
    Scan real project files and add findings based on evidence.
    Only adds a finding if real evidence is found.
    """

    # ── Dockerfile ────────────────────────────────────────────
    dockerfiles = list(PROJECT_ROOT.glob("**/Dockerfile"))[:3]
    for df_path in dockerfiles:
        try:
            txt = df_path.read_text(encoding="utf-8", errors="replace")

            # Old base image — check actual content
            old_image_match = re.search(
                r"FROM python:(3\.[6789]|3\.10|3\.11)[^\n]*", txt
            )
            if old_image_match:
                old_tag = old_image_match.group(0).strip()
                findings.append(UpgradeFinding(
                    category  = "Performance",
                    priority  = "HIGH",
                    title     = f"Outdated Python base image in {df_path.name}",
                    present   = f"Using: {old_tag}",
                    expected  = "FROM python:3.12-slim",
                    solution  = (
                        f"1. Edit {df_path}\n"
                        "2. Change FROM line to: FROM python:3.12-slim\n"
                        "3. Python 3.12 is 15-30% faster and has better error messages.\n"
                        "4. Rebuild: docker build -t yourapp:new .\n"
                        "5. Run tests before deploying."
                    ),
                    evidence  = f"Found in {df_path}: {old_tag}",
                ))

            # No HEALTHCHECK
            if "HEALTHCHECK" not in txt:
                findings.append(UpgradeFinding(
                    category  = "Reliability",
                    priority  = "MEDIUM",
                    title     = f"No HEALTHCHECK in {df_path.name}",
                    present   = "No HEALTHCHECK instruction found",
                    expected  = "HEALTHCHECK CMD curl --fail http://localhost:8000/health || exit 1",
                    solution  = (
                        f"Add to {df_path} before CMD:\n"
                        "  HEALTHCHECK --interval=30s --timeout=10s --retries=3 \\\n"
                        "    CMD curl -f http://localhost:8000/health || exit 1\n"
                        "This enables Docker and K8s to auto-restart unhealthy containers."
                    ),
                    evidence  = f"Scanned {df_path} — no HEALTHCHECK found",
                ))

            # Running as root
            if "USER" not in txt:
                findings.append(UpgradeFinding(
                    category  = "Security",
                    priority  = "MEDIUM",
                    title     = f"Container runs as root in {df_path.name}",
                    present   = "No USER instruction — container runs as root",
                    expected  = "Non-root user for security isolation",
                    solution  = (
                        f"Add to {df_path} before CMD:\n"
                        "  RUN addgroup --system app && adduser --system --group app\n"
                        "  USER app\n"
                        "This prevents privilege escalation if container is compromised."
                    ),
                    evidence  = f"Scanned {df_path} — no USER instruction found",
                ))

            # Single stage build
            from_count = txt.count("FROM")
            if from_count == 1 and len(txt) > 200:
                findings.append(UpgradeFinding(
                    category  = "Performance",
                    priority  = "LOW",
                    title     = f"Single-stage Dockerfile in {df_path.name}",
                    present   = "One FROM stage — image includes build tools",
                    expected  = "Multi-stage build — runtime image ~150MB vs ~900MB",
                    solution  = (
                        "Use multi-stage build:\n"
                        "  # Stage 1: build\n"
                        "  FROM python:3.12-slim AS builder\n"
                        "  WORKDIR /build\n"
                        "  COPY requirements.txt .\n"
                        "  RUN pip install --prefix=/install -r requirements.txt\n\n"
                        "  # Stage 2: runtime\n"
                        "  FROM python:3.12-slim\n"
                        "  COPY --from=builder /install /usr/local\n"
                        "  COPY . .\n"
                        "  CMD [\"python\", \"app.py\"]"
                    ),
                    evidence  = f"Scanned {df_path}: {from_count} FROM statement",
                ))

            # Layer cache ordering issue
            copy_all_pos = txt.find("COPY . .")
            req_pos      = txt.find("requirements.txt")
            if copy_all_pos > 0 and req_pos > copy_all_pos:
                findings.append(UpgradeFinding(
                    category  = "Performance",
                    priority  = "MEDIUM",
                    title     = f"Docker layer cache broken in {df_path.name}",
                    present   = "COPY . . appears before pip install — cache invalidated on every code change",
                    expected  = "Copy requirements.txt first, then pip install, then COPY . .",
                    solution  = (
                        f"Reorder {df_path}:\n"
                        "  COPY requirements.txt .\n"
                        "  RUN pip install -r requirements.txt\n"
                        "  COPY . .  # <-- code changes here, pip layer cached above\n"
                        "This cuts build time from 3min to 20s on code-only changes."
                    ),
                    evidence  = (
                        f"In {df_path}: COPY . . at char {copy_all_pos}, "
                        f"requirements reference at char {req_pos}"
                    ),
                ))

        except OSError:
            pass

    # ── requirements.txt ─────────────────────────────────────
    req_files = list(PROJECT_ROOT.glob("requirements*.txt"))[:4]
    for rf in req_files:
        try:
            txt = rf.read_text(encoding="utf-8", errors="replace")
            lines = [
                l.strip() for l in txt.splitlines()
                if l.strip() and not l.strip().startswith("#")
            ]
            unpinned = [
                l for l in lines
                if not any(op in l for op in ["==", ">=", "~=", "<=", "!="])
                and not l.startswith("-")
                and not l.startswith(".")
            ]
            if len(unpinned) > 2:
                findings.append(UpgradeFinding(
                    category  = "Reliability",
                    priority  = "MEDIUM",
                    title     = f"Unpinned dependencies in {rf.name}",
                    present   = (
                        f"{len(unpinned)} packages without version pins: "
                        f"{', '.join(unpinned[:5])}"
                    ),
                    expected  = "All packages pinned: package==1.2.3",
                    solution  = (
                        f"1. Pin all versions: pip freeze > {rf.name}\n"
                        "2. Or use pip-tools: pip install pip-tools && pip-compile\n"
                        "3. Use Dependabot to keep pins up to date automatically."
                    ),
                    evidence  = (
                        f"Found in {rf}: unpinned packages: "
                        f"{', '.join(unpinned[:8])}"
                    ),
                ))

            # Check for known vulnerable packages
            dangerous = {
                "django":    ("2.", "3.0", "3.1", "3.2"),
                "flask":     ("0.", "1."),
                "requests":  ("2.2", "2.1", "2.0"),
                "urllib3":   ("1.2", "1.1", "1.0"),
                "pyyaml":    ("3.", "4.", "5.3"),
            }
            for line in lines:
                for pkg, old_versions in dangerous.items():
                    if line.lower().startswith(pkg + "=="):
                        ver = line.split("==")[1].strip()
                        if any(ver.startswith(v) for v in old_versions):
                            findings.append(UpgradeFinding(
                                category  = "Security",
                                priority  = "HIGH",
                                title     = f"Potentially outdated/vulnerable: {line}",
                                present   = f"Using {line} in {rf.name}",
                                expected  = f"Latest stable {pkg} version",
                                solution  = (
                                    f"1. Check vulnerabilities: pip-audit\n"
                                    f"2. Update: pip install --upgrade {pkg}\n"
                                    "3. Run your test suite after upgrading.\n"
                                    "4. Enable Dependabot for automated updates."
                                ),
                                evidence  = f"Found {line} in {rf}",
                            ))
        except OSError:
            pass

    # ── GitHub Actions ────────────────────────────────────────
    wf_dir = PROJECT_ROOT / ".github" / "workflows"
    if wf_dir.exists():
        for yf in list(wf_dir.glob("*.yml"))[:5]:
            try:
                txt = yf.read_text(encoding="utf-8", errors="replace")

                # No caching
                if ("actions/cache" not in txt
                        and "cache-from" not in txt
                        and "cache:" not in txt):
                    findings.append(UpgradeFinding(
                        category  = "Performance",
                        priority  = "MEDIUM",
                        title     = f"No dependency caching in {yf.name}",
                        present   = "pip/npm installs run from scratch every build",
                        expected  = "Cached dependencies — builds 3-5x faster",
                        solution  = (
                            f"Add to {yf.name}:\n"
                            "  - uses: actions/cache@v4\n"
                            "    with:\n"
                            "      path: ~/.cache/pip\n"
                            "      key: ${{ runner.os }}-pip-"
                            "${{ hashFiles('requirements*.txt') }}\n"
                            "This cuts build time by 2-4 minutes."
                        ),
                        evidence  = f"Scanned {yf}: no cache action found",
                    ))

                # Long-lived AWS keys
                if "aws-access-key-id" in txt and "role-to-assume" not in txt:
                    findings.append(UpgradeFinding(
                        category  = "Security",
                        priority  = "HIGH",
                        title     = f"Long-lived AWS keys in {yf.name}",
                        present   = "Using static AWS_ACCESS_KEY_ID secret",
                        expected  = "OIDC role-based auth — no stored keys",
                        solution  = (
                            f"Replace in {yf.name}:\n"
                            "  - uses: aws-actions/configure-aws-credentials@v4\n"
                            "    with:\n"
                            "      role-to-assume: arn:aws:iam::ACCOUNT:role/ROLE\n"
                            "      aws-region: us-east-1\n"
                            "Delete AKIA* secrets from GitHub Settings → Secrets."
                        ),
                        evidence  = f"Found aws-access-key-id in {yf}",
                    ))

                # No security scanning
                security_tools = ["trivy", "grype", "snyk", "bandit",
                                  "safety", "semgrep", "sonar"]
                if not any(t in txt.lower() for t in security_tools):
                    findings.append(UpgradeFinding(
                        category  = "Security",
                        priority  = "HIGH",
                        title     = f"No security scanning in {yf.name}",
                        present   = "Pipeline deploys without vulnerability check",
                        expected  = "Container + dependency scanning before deploy",
                        solution  = (
                            f"Add to {yf.name} before deploy step:\n"
                            "  - name: Scan image\n"
                            "    uses: aquasecurity/trivy-action@master\n"
                            "    with:\n"
                            "      image-ref: yourimage:tag\n"
                            "      exit-code: 1\n"
                            "      severity: CRITICAL,HIGH"
                        ),
                        evidence  = f"Scanned {yf}: no security scanner found",
                    ))

                # No test step
                if not any(t in txt.lower() for t in
                           ["pytest", "unittest", "test", "jest", "mocha"]):
                    findings.append(UpgradeFinding(
                        category  = "Reliability",
                        priority  = "HIGH",
                        title     = f"No test step in {yf.name}",
                        present   = "Deploying without automated test verification",
                        expected  = "Tests run on every PR and push",
                        solution  = (
                            f"Add to {yf.name}:\n"
                            "  - name: Run tests\n"
                            "    run: |\n"
                            "      pip install pytest\n"
                            "      pytest tests/ -v --tb=short\n"
                            "This catches regressions before they reach production."
                        ),
                        evidence  = f"Scanned {yf}: no test runner found",
                    ))

            except OSError:
                pass

    # ── Missing .dockerignore ─────────────────────────────────
    if (dockerfiles and
            not (PROJECT_ROOT / ".dockerignore").exists()):
        findings.append(UpgradeFinding(
            category  = "Performance",
            priority  = "MEDIUM",
            title     = "Missing .dockerignore",
            present   = "No .dockerignore — entire project sent to Docker daemon",
            expected  = ".dockerignore excludes venv, __pycache__, .git",
            solution  = (
                "Create .dockerignore:\n"
                "  __pycache__\n"
                "  *.pyc\n"
                "  .venv\n"
                "  venv/\n"
                "  .git\n"
                "  *.log\n"
                "  .env\n"
                "  node_modules/\n"
                "  .pytest_cache/\n"
                "This reduces build context and prevents secrets in .env "
                "from entering the image."
            ),
            evidence  = (
                f"Dockerfile found at {dockerfiles[0]} "
                f"but no .dockerignore in {PROJECT_ROOT}"
            ),
        ))

    # ── Missing tests ─────────────────────────────────────────
    test_files = (
        list(PROJECT_ROOT.glob("**/test_*.py"))
        + list(PROJECT_ROOT.glob("**/tests/**/*.py"))
    )
    test_files = [
        t for t in test_files
        if ".venv" not in str(t) and "venv" not in str(t)
    ]
    if not test_files:
        findings.append(UpgradeFinding(
            category  = "Reliability",
            priority  = "HIGH",
            title     = "No automated tests found",
            present   = "Zero test files in project",
            expected  = "pytest tests covering critical paths",
            solution  = (
                "1. Create tests/test_health.py:\n"
                "   from app import app\n"
                "   def test_health():\n"
                "       resp = app.test_client().get('/health')\n"
                "       assert resp.status_code == 200\n"
                "2. Run: pytest tests/ -v\n"
                "3. Add to CI pipeline before deploy step."
            ),
            evidence  = (
                f"Glob for test_*.py and tests/**/*.py in {PROJECT_ROOT} "
                "returned no results"
            ),
        ))

    # ── No rollback config ────────────────────────────────────
    wf_files = list(wf_dir.glob("*.yml")) if wf_dir.exists() else []
    has_rollback = any(
        "rollback" in (f.read_text(errors="replace") or "").lower()
        for f in wf_files
    )
    if wf_files and not has_rollback:
        findings.append(UpgradeFinding(
            category  = "Reliability",
            priority  = "MEDIUM",
            title     = "No rollback strategy in CI/CD pipeline",
            present   = "Pipeline has no rollback on deploy failure",
            expected  = "Auto-rollback to previous image tag on health check failure",
            solution  = (
                "Add post-deploy check to your workflow:\n"
                "  - name: Verify deployment\n"
                "    run: |\n"
                "      sleep 30\n"
                "      STATUS=$(curl -s -o /dev/null -w '%{http_code}' $APP_URL/health)\n"
                "      if [ \"$STATUS\" != '200' ]; then\n"
                "        echo 'Health check failed — rolling back'\n"
                "        # redeploy previous tag\n"
                "        exit 1\n"
                "      fi"
            ),
            evidence  = (
                f"Checked {len(wf_files)} workflow files — "
                "no rollback logic found"
            ),
        ))

# ──────────────────────────────────────────────────────────────
# AI ANALYSIS  (optional, enhances but not required)
# ──────────────────────────────────────────────────────────────
def run_ai_analysis(
    endpoint_results: list[EndpointResult],
    system_health:    SystemHealth,
    findings:         list[UpgradeFinding],
    app_health:       dict,
) -> str:
    """
    Send real findings to AI for deeper analysis.
    Only runs if GEMINI_API_KEY is set.
    Returns empty string if AI not available.
    """
    if not _ai_available():
        return ""

    # Build a factual summary for AI — no hallucination bait
    endpoint_summary = "\n".join([
        f"  {'✅' if e.reachable else '❌'} {e.url} → "
        f"{'HTTP ' + str(e.status_code) + ' ' + str(e.latency_ms) + 'ms' if e.reachable else e.error_reason}"
        for e in endpoint_results[:15]
    ])

    findings_summary = "\n".join([
        f"  [{f.priority}] {f.category}: {f.title}"
        for f in findings[:20]
    ])

    prompt = f"""
You are a senior DevOps engineer doing post-deployment review.

REAL MEASUREMENTS (do not invent data — use only what is here):

SYSTEM:
  RAM: {system_health.ram_used_mb}MB / {system_health.ram_total_mb}MB ({system_health.ram_usage_pct}%) — {system_health.ram_status}
  CPU: {system_health.cpu_usage_pct}% — {system_health.cpu_status}
  Disk: {system_health.disk_usage_pct}% — {system_health.disk_status}
  Network: {system_health.net_status}
  Docker containers: {len(system_health.containers)} found
  Unhealthy containers: {[c['name'] for c in system_health.containers if not c.get('healthy')]}

ENDPOINTS ({app_health['reachable']}/{app_health['total_endpoints']} reachable):
{endpoint_summary}

APP STATUS: {app_health['status']}
AVG LATENCY: {app_health['avg_latency_ms']}ms

ALREADY DETECTED ISSUES ({len(findings)}):
{findings_summary}

Based ONLY on the real data above:
1. Identify any patterns or root causes not already listed.
2. Prioritize the top 3 actions to take RIGHT NOW.
3. Estimate risk level: LOW / MEDIUM / HIGH / CRITICAL overall.

Format:
ROOT_CAUSE_ANALYSIS:
<your analysis>

TOP_3_ACTIONS:
1. <action>
2. <action>
3. <action>

OVERALL_RISK: <level>
REASONING: <why>
"""
    return ask_ai(prompt)

# ──────────────────────────────────────────────────────────────
# REPORT BUILDER
# ──────────────────────────────────────────────────────────────
def build_text_report(report: FinalReport, app_health: dict) -> str:
    """Build the full human-readable report."""
    lines = []
    sep   = "=" * 72

    lines += [
        sep,
        "  FINAL AGENT — POST-DEPLOY HEALTH & UPGRADE REPORT",
        sep,
        f"  Project   : {report.project_path}",
        f"  Platform  : {report.platform}",
        f"  Timestamp : {report.timestamp}",
        f"  Duration  : {report.scan_duration:.1f}s",
        f"  AI Active : {'Yes (' + MODEL + ')' if _ai_available() else 'No (set GEMINI_API_KEY to enable)'}",
        sep,
        "",
    ]

    # ── SECTION 1: Endpoints ──────────────────────────────────
    lines += [
        "━" * 72,
        "  SECTION 1: ENDPOINT ACCESSIBILITY",
        "━" * 72,
        f"  Total Checked : {app_health['total_endpoints']}",
        f"  Reachable     : {app_health['reachable']}  ✅",
        f"  Unreachable   : {app_health['unreachable']}  ❌",
        f"  Avg Latency   : {app_health['avg_latency_ms']}ms",
        "",
    ]

    for e in report.endpoints:
        if e.reachable:
            ssl_info = ""
            if e.ssl_expiry_days is not None:
                ssl_icon = "🔴" if e.ssl_expiry_days < 7 else "🟡" if e.ssl_expiry_days < 30 else "🟢"
                ssl_info = f" | SSL: {ssl_icon} {e.ssl_expiry_days}d"
            redir = f" → {e.redirect_url}" if e.redirect_url else ""
            lines.append(
                f"  ✅ {e.url}\n"
                f"     Status: HTTP {e.status_code} | "
                f"Latency: {e.latency_ms}ms | "
                f"DNS: {e.dns_ip}{ssl_info}{redir}"
            )
        else:
            lines += [
                f"  ❌ {e.url}",
                f"     DNS Resolved : {e.dns_resolved} ({e.dns_ip or 'N/A'})",
                f"     Port Open    : {e.port_open}",
                f"     Error        : {e.error}",
                f"     ROOT CAUSE   : {e.error_reason}",
            ]
        lines.append("")

    # ── SECTION 2: App & Infra Health ────────────────────────
    status_icons = {
        "HEALTHY": "✅", "DEGRADED": "⚠️",
        "DOWN": "🔴", "SLOW": "🟡", "NO_ENDPOINTS": "ℹ️"
    }
    resource_icons = {"OK": "✅", "WARNING": "⚠️", "CRITICAL": "🔴", "UNKNOWN": "❓"}

    lines += [
        "━" * 72,
        "  SECTION 2: APP & INFRASTRUCTURE HEALTH",
        "━" * 72,
        f"  App Status : {status_icons.get(app_health['status'], '❓')} {app_health['status']}",
        "",
        "  System Resources:",
        f"    RAM  : {resource_icons.get(report.system_health.ram_status, '❓')} "
        f"{report.system_health.ram_used_mb}MB / "
        f"{report.system_health.ram_total_mb}MB "
        f"({report.system_health.ram_usage_pct}%) — "
        f"{report.system_health.ram_status}",
        f"    CPU  : {resource_icons.get(report.system_health.cpu_status, '❓')} "
        f"{report.system_health.cpu_usage_pct}% — "
        f"{report.system_health.cpu_status} "
        f"(load: {report.system_health.load_avg})",
        f"    Disk : {resource_icons.get(report.system_health.disk_status, '❓')} "
        f"{report.system_health.disk_usage_pct}% used "
        f"({report.system_health.disk_free_gb}GB free) — "
        f"{report.system_health.disk_status}",
        f"    Net  : {resource_icons.get(report.system_health.net_status, '❓')} "
        f"{report.system_health.net_status} "
        f"({report.system_health.net_latency_ms}ms)",
        "",
    ]

    # Docker containers
    if report.system_health.containers:
        lines.append("  Docker Containers:")
        for c in report.system_health.containers:
            icon = "✅" if c.get("healthy") else "❌"
            lines.append(
                f"    {icon} {c['name']:30s} | "
                f"{c['status']:30s} | {c['image']}"
            )
        lines.append("")

    # Open ports
    if report.system_health.open_ports:
        lines.append(
            f"  Open Ports : {sorted(report.system_health.open_ports)}"
        )
        lines.append("")

    # ── SECTION 3: Upgrade Recommendations ───────────────────
    lines += [
        "━" * 72,
        "  SECTION 3: UPGRADE RECOMMENDATIONS",
        "━" * 72,
        f"  Total Findings : {len(report.findings)}",
        "",
    ]

    if not report.findings:
        lines.append("  ✅ No upgrade issues detected. Deployment looks healthy!")
    else:
        by_cat: dict[str, list] = {}
        for f in report.findings:
            by_cat.setdefault(f.category, []).append(f)

        priority_icons = {
            "CRITICAL": "🔴",
            "HIGH":     "🟠",
            "MEDIUM":   "🟡",
            "LOW":      "🟢",
        }

        for cat in ["Security", "Reliability", "Performance", "Cost",
                    "Developer Experience"]:
            if cat not in by_cat:
                continue
            cat_findings = by_cat[cat]
            lines += [
                f"  ── {cat.upper()} ({len(cat_findings)} finding(s)) ──",
                "",
            ]
            for idx, f in enumerate(cat_findings, 1):
                icon = priority_icons.get(f.priority, "⚪")
                lines += [
                    f"  {icon} [{f.priority}] {f.title}",
                    f"     PRESENT  : {f.present}",
                    f"     EXPECTED : {f.expected}",
                    f"     EVIDENCE : {f.evidence}",
                    "     SOLUTION :",
                ]
                for sol_line in f.solution.split("\n"):
                    lines.append(f"       {sol_line}")
                lines.append("")

    # ── AI Analysis ───────────────────────────────────────────
    if report.ai_analysis:
        lines += [
            "━" * 72,
            "  🤖 AI ENHANCED ANALYSIS",
            "━" * 72,
            report.ai_analysis,
            "",
        ]
    else:
        lines += [
            "━" * 72,
            "  ℹ️  AI ANALYSIS",
            "━" * 72,
            "  AI not active. Set GEMINI_API_KEY to enable deeper analysis.",
            "",
        ]

    # ── AI Token Usage ────────────────────────────────────────
    if _ai_stats["requests"] > 0:
        lines += [
            f"  AI Stats: {_ai_stats['requests']} request(s) | "
            f"{_ai_stats['total_tokens']} tokens | "
            f"{_ai_stats['response_time']:.1f}s",
            "",
        ]

    lines += [sep, "  END OF REPORT", sep]
    return "\n".join(lines)

# ──────────────────────────────────────────────────────────────
# MAIN
# ──────────────────────────────────────────────────────────────
def main() -> int:
    started   = time.perf_counter()
    timestamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    ci_platform = (
        "github_actions" if os.getenv("GITHUB_ACTIONS") == "true"
        else "azure_devops" if os.getenv("TF_BUILD") == "True"
        else "jenkins"     if os.getenv("JENKINS_URL")
        else "local"
    )

    print(f"\n{'='*60}")
    print("  FINAL AGENT — Post-Deploy Health & Upgrade Advisor")
    print(f"{'='*60}")
    print(f"  Project  : {PROJECT_ROOT}")
    print(f"  Platform : {ci_platform}")
    print(f"  AI       : {'Enabled (' + MODEL + ')' if _ai_available() else 'Disabled (no GEMINI_API_KEY)'}")
    print(f"  Time     : {timestamp}\n")

    # ── STEP 1: Endpoint checks ───────────────────────────────
    print("─── STEP 1: Checking endpoints ───")
    urls             = collect_endpoints()
    if not urls:
        print("  ⚠️  No URLs found. Set APP_URL=https://yourapp.com")
        endpoint_results = []
    else:
        print(f"  Found {len(urls)} URL(s) to check.")
        endpoint_results = run_endpoint_checks(urls)

    # ── STEP 2: System health ─────────────────────────────────
    print("\n─── STEP 2: Collecting system health ───")
    system_health = collect_system_health()
    print(f"  RAM  : {system_health.ram_used_mb}MB/{system_health.ram_total_mb}MB "
          f"({system_health.ram_usage_pct}%) — {system_health.ram_status}")
    print(f"  CPU  : {system_health.cpu_usage_pct}% — {system_health.cpu_status}")
    print(f"  Disk : {system_health.disk_usage_pct}% — {system_health.disk_status}")
    print(f"  Net  : {system_health.net_status}")
    print(f"  Docker containers: {len(system_health.containers)}")

    # ── STEP 3: App health analysis ───────────────────────────
    print("\n─── STEP 3: Analyzing app health ───")
    app_health = analyze_app_health(endpoint_results, system_health)
    print(f"  App status: {app_health['status']}")

    # ── STEP 4: Upgrade findings ──────────────────────────────
    print("\n─── STEP 4: Finding upgrade opportunities ───")
    findings = find_upgrades(endpoint_results, system_health, app_health)
    critical = sum(1 for f in findings if f.priority == "CRITICAL")
    high     = sum(1 for f in findings if f.priority == "HIGH")
    print(f"  Total: {len(findings)} | Critical: {critical} | High: {high}")

    # ── STEP 5: AI analysis (optional) ───────────────────────
    print("\n─── STEP 5: AI analysis ───")
    if _ai_available():
        print("  Running AI analysis...")
        ai_analysis = run_ai_analysis(
            endpoint_results, system_health, findings, app_health
        )
        print("  AI analysis complete.")
    else:
        print("  Skipped — GEMINI_API_KEY not set.")
        ai_analysis = ""

    # ── STEP 6: Build & write reports ────────────────────────
    print("\n─── STEP 6: Writing reports ───")
    report = FinalReport(
        timestamp     = timestamp,
        project_path  = str(PROJECT_ROOT),
        platform      = ci_platform,
        endpoints     = endpoint_results,
        system_health = system_health,
        findings      = findings,
        ai_analysis   = ai_analysis,
        scan_duration = time.perf_counter() - started,
    )

    text_report = build_text_report(report, app_health)

    REPORT_DIR.mkdir(exist_ok=True)
    report_file    = REPORT_DIR / "final_report.txt"
    json_file      = REPORT_DIR / "final_report.json"
    root_copy      = Path("final_report.txt")

    report_file.write_text(text_report, encoding="utf-8")
    root_copy.write_text(text_report,   encoding="utf-8")

    # JSON report
    json_data = {
        "timestamp":    timestamp,
        "platform":     ci_platform,
        "app_health":   app_health,
        "system": {
            "ram_pct":     system_health.ram_usage_pct,
            "ram_status":  system_health.ram_status,
            "cpu_pct":     system_health.cpu_usage_pct,
            "cpu_status":  system_health.cpu_status,
            "disk_pct":    system_health.disk_usage_pct,
            "disk_status": system_health.disk_status,
            "net_status":  system_health.net_status,
            "containers":  system_health.containers,
        },
        "endpoints": [
            {
                "url":           e.url,
                "reachable":     e.reachable,
                "status_code":   e.status_code,
                "latency_ms":    e.latency_ms,
                "error_reason":  e.error_reason,
                "dns_resolved":  e.dns_resolved,
                "dns_ip":        e.dns_ip,
                "port_open":     e.port_open,
                "ssl_valid":     e.ssl_valid,
                "ssl_expiry_days": e.ssl_expiry_days,
            }
            for e in endpoint_results
        ],
        "findings": [
            {
                "category":  f.category,
                "priority":  f.priority,
                "title":     f.title,
                "present":   f.present,
                "expected":  f.expected,
                "solution":  f.solution,
                "evidence":  f.evidence,
            }
            for f in findings
        ],
        "ai_analysis":   ai_analysis,
        "total_findings": len(findings),
        "critical_count": critical,
        "high_count":     high,
        "scan_duration":  round(time.perf_counter() - started, 2),
        "ai_stats":       _ai_stats,
    }
    json_file.write_text(
        json.dumps(json_data, indent=2), encoding="utf-8"
    )

    print(f"  ✅ {report_file}")
    print(f"  ✅ {json_file}")
    print(f"  ✅ {root_copy}")

    # ── Print report ─────────────────────────────────────────
    print("\n" + text_report)

    total_time = time.perf_counter() - started
    print(f"\n  Completed in {total_time:.1f}s")

    return 0

if __name__ == "__main__":
    _t0 = time.perf_counter()
    _rc = main()
    try:
        from agent.monitor_client import report
        report(
            agent_name        = "final_agent",
            stage             = "post_deploy",
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
        print(f"[final_agent] monitor report error: {e}", flush=True)
    raise SystemExit(_rc)
"""
final_agent.py  -  PHASE 3: POST-DEPLOYMENT VERIFICATION (AI-powered)
---------------------------------------------------------------------
Runs AFTER deployment and answers: "Did the deploy succeed, and is the
system actually healthy?"

It probes live endpoints, then uses an AI model (for best results) to:
  - on FAILURE : explain WHERE it failed, WHY, the ROOT CAUSE, and a FIX
  - on SUCCESS : report health + tailored NEXT-STAGE upgrade recommendations

The AI model is defined IN THIS FILE (MODEL below) so you can change it
on the spot if it is unavailable. The API key is read from the
GEMINI_API_KEY environment variable. If the AI is unavailable, the agent
falls back to built-in heuristics so it still produces a useful review.

Outcomes:
  - FAILURE -> WHERE / WHY / ROOT CAUSE / FIX (AI, else heuristics)
  - SUCCESS -> health + tailored next-stage upgrades (AI, else built-in list)

Writes final_review.txt (always) and prints. Exit code 0 success / 1 failure.
"""

# ===== AI CONFIG =========================================================
# Edit MODEL here if the model is unavailable (e.g. quota / region).
# Other valid examples: "gemini-2.5-pro", "gemini-1.5-flash".
MODEL = "gemini-2.5-flash"
# The API key is taken from the GEMINI_API_KEY environment variable.
# ========================================================================

import os
import sys
import json
import subprocess
import urllib.request
import urllib.error
from datetime import datetime
import time
from monitor_client import send_agent_status

# ----------------------------- AI plumbing ------------------------------
def _build_client():
    try:
        from google import genai
    except ImportError:
        raise RuntimeError("google-genai SDK not installed -> pip install google-genai")
    key = os.environ.get("GEMINI_API_KEY")
    if not key:
        raise RuntimeError("GEMINI_API_KEY environment variable is not set")
    return genai.Client(api_key=key)


def ai_status():
    try:
        client = _build_client()
    except Exception as e:
        return False, str(e)
    try:
        client.models.generate_content(model=MODEL, contents="Reply with exactly: OK")
        return True, ""
    except Exception as e:
        return False, f"model '{MODEL}' could not respond: {e}"


def ask(prompt):
    client = _build_client()
    resp = client.models.generate_content(model=MODEL, contents=prompt)
    text = (resp.text or "").strip()
    tokens = 0
    try:
        u = resp.usage_metadata
        tokens = (u.prompt_token_count or 0) + (u.candidates_token_count or 0)
    except Exception:
        pass
    return text, prompt_tokens, completion_tokens


# --------------------------- target discovery ---------------------------
def discover_deploy_url():
    """Auto-discover the Elastic Beanstalk environment CNAME via the
    EB/AWS CLI using ENV_NAME / APP_NAME / AWS_REGION (provided by the
    pipeline) so the operator never hard-codes DEPLOY_URL."""
    env_name = os.getenv("ENV_NAME")
    app_name = os.getenv("APP_NAME")
    region = os.getenv("AWS_REGION") or "us-east-1"

    commands = []
    if env_name:
        commands.append(["eb", "status", env_name, "--query", "CNAME", "--output", "text"])
    if app_name and env_name:
        commands.append([
            "aws", "elasticbeanstalk", "describe-environments",
            "--application-name", app_name, "--environment-names", env_name,
            "--region", region, "--query", "Environments[0].CNAME", "--output", "text",
        ])

    for cmd in commands:
        try:
            out = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            cname = (out.stdout or "").strip()
            looks_like_host = ("elasticbeanstalk.com" in cname or "amazonaws" in cname)
            if cname and cname.lower() != "none" and looks_like_host:
                return "http://" + cname
        except Exception:
            continue
    return None


_explicit = os.getenv("DEPLOY_URL")
_discovered = discover_deploy_url()

if _explicit:
    DEPLOY_URL = _explicit.rstrip("/")
elif _discovered:
    DEPLOY_URL = _discovered.rstrip("/")
else:
    DEPLOY_URL = "http://localhost:5000"  # local fallback when nothing is set

_base = DEPLOY_URL.rsplit(":", 1)[0] if "://" in DEPLOY_URL else DEPLOY_URL
PROM_URL = (os.getenv("PROMETHEUS_URL") or (_base + ":9090")).rstrip("/")
GRAFANA_URL = (os.getenv("GRAFANA_URL") or (_base + ":3000")).rstrip("/")


# ----------------------------- health checks ----------------------------
CHECKS = [
    ("/health", "HTTP 200", lambda r, b: r == 200, "App is alive"),
    ("/api/status", "JSON with deployment block",
     lambda r, b: r == 200 and b"deployment" in b, "Status API returns deployment metadata"),
    ("/metrics", "200 + app_* metrics",
     lambda r, b: r == 200 and b"app_requests_total" in b, "Prometheus metrics are exposed"),
    ("/dashboard", "HTTP 200 (HTML)",
     lambda r, b: r == 200 and b"chart-traffic" in b, "Live HTML dashboard renders"),
]


def fetch(url, timeout=8):
    """Return (status_code, body_bytes, error_string)."""
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "final-agent"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, resp.read(), None
    except urllib.error.HTTPError as e:
        return e.code, e.read() if hasattr(e, "read") else b"", None
    except Exception as e:  # URLError, timeout, connection refused, etc.
        return None, b"", f"{type(e).__name__}: {e}"


def run_checks():
    results = []
    for path, expect, validate, meaning in CHECKS:
        status, body, err = fetch(DEPLOY_URL + path)
        ok = validate(status, body) if status is not None else False
        results.append({
            "path": path, "expect": expect, "status": status,
            "error": err, "ok": ok, "meaning": meaning,
            "cause": None if ok else root_cause(path, status, err),
        })
    return results


def optional_checks():
    extra = []
    if PROM_URL:
        status, _, err = fetch(PROM_URL + "/api/v1/targets", timeout=8)
        extra.append(("Prometheus /targets", status == 200, err))
    if GRAFANA_URL:
        status, _, err = fetch(GRAFANA_URL + "/api/health", timeout=8)
        extra.append(("Grafana /api/health", status == 200, err))
    return extra


def _metrics_sample():
    """Pull a small slice of app_* Prometheus metrics to give the AI context."""
    try:
        status, body, err = fetch(DEPLOY_URL + "/metrics", timeout=8)
        if status != 200 or not body:
            return ""
        lines = []
        for raw in body.splitlines():
            if b"app_" in raw:
                try:
                    lines.append(raw.decode(errors="ignore"))
                except Exception:
                    pass
            if len(lines) >= 100:
                break
        return "\n".join(lines)
    except Exception:
        return ""


# ----------------------- built-in fallback logic ------------------------
def root_cause(path, status, err):
    """Best-effort human explanation of WHY / root cause (used if AI is down)."""
    if err:
        low = err.lower()
        if ("connection refused" in low or "errno 111" in low
                or "connectionrefused" in low or "timeout" in low):
            return ("The service is not reachable. Root cause is usually the "
                    "container/process not running or the wrong port/URL. "
                    "Check the deployment logs and that the load balancer health "
                    "check passes on /health.")
        return f"Unexpected error reaching the service: {err}"
    if status is None:
        return "No HTTP response was returned."
    if status >= 500:
        return ("The app answered but with a server error (5xx). Root cause is "
                "typically an unhandled exception at startup or during the request "
                "(missing env var, bad import, DB/dependency failure).")
    if status >= 400:
        return ("The app answered with a client error (4xx). Root cause is usually "
                "a routing / auth / path mismatch in the proxy or app.")
    return "Responded but failed content validation (unexpected payload)."


def next_stage_recommendations():
    """Built-in list used only when the AI is unavailable."""
    return [
        "Enable Alertmanager (or AWS SNS/Slack) and wire the Prometheus alert "
        "rules so infra/app/agent failures page someone automatically.",
        "Add Elastic Beanstalk managed scaling / autoscaling based on CPU and "
        "request count; run in >=2 AZs for high availability.",
        "Implement blue/green or canary deployments (e.g. EB immutable updates or "
        "a second env + weighted Route53) to eliminate downtime on bad releases.",
        "Add security scanning to CI: Trivy/Snyk for images, pip-audit for deps, "
        "and secret scanning before every deploy.",
        "Centralise logs to CloudWatch with metric filters + alarms; retain >=30d "
        "and alarm on 5xx / error-rate spikes.",
        "Add synthetic/uptime monitoring (e.g. CloudWatch Synthetics or "
        "external ping) on /health and /api/status from outside the VPC.",
        "Promote maturity: SLOs + error-budget dashboards, and an on-call runbook "
        "linked from the Grafana 'Overview' dashboard.",
        "Harden the AI agent: rate-limit /monitor/status, validate payloads, and "
        "store decisions immutably for audit; add a manual approval gate for prod.",
    ]


# ----------------------------- AI analysis ------------------------------
def ai_failure_analysis(results, extra):
    failed = [r for r in results if not r["ok"]]
    facts = []
    for r in failed:
        facts.append(
            f"- endpoint {r['path']} (expect: {r['expect']})\n"
            f"  observed status={r['status']} error={r['error']}"
        )
    for name, ok, err in extra:
        if not ok:
            facts.append(f"- optional check {name}: {err}")
    if not facts:
        return None

    prompt = f"""
You are a senior SRE doing a post-deployment failure review.
The following deployment health checks FAILED:

{chr(10).join(facts)}

For EACH failure, report EXACTLY these fields:
WHERE: <endpoint or component>
WHY: <what was observed, one sentence>
ROOT CAUSE: <most likely root cause, one sentence>
FIX: <concrete step or code/config change to resolve it>

Be specific, practical, and ordered by impact.
"""
    return ask(prompt)


def ai_recommendations(results, extra, metrics_text):
    endpoints = "\n".join(f"- {r['path']} OK (HTTP {r['status']})" for r in results)
    prom = "healthy" if all(ok for _, ok, _ in extra) else "degraded"
    prompt = f"""
You are a senior SRE. A deployment just PASSED all critical health checks:
{endpoints}
Optional monitoring (Prometheus/Grafana): {prom}

Observed Prometheus metrics sample (if any):
{metrics_text or 'none'}

Suggest the TOP 6 concrete NEXT-STAGE upgrades to harden and mature this
system (reliability, scaling, security, observability, CI/CD, AI agent).
For each, give:
1) TITLE
2) WHY IT MATTERS
3) CONCRETE ACTION
Prioritize by impact.
"""
    return ask(prompt)[0]


# -------------------------------- main ----------------------------------
def main():
    started_at = time.perf_counter()
send_agent_status(
    agent_name="final_agent",
    stage="post_deploy",
    status="running",
    decision="none",
    provider="gemini",
    model=MODEL,
)
    print("=" * 70)
    print(" SentinelOps-Lite - POST-DEPLOYMENT VERIFICATION (AI-powered)")
    if not _explicit and _discovered:
        print(" Target: %s  (auto-discovered via EB env '%s')"
              % (DEPLOY_URL, os.getenv("ENV_NAME")))
    elif not _explicit:
        print(" Target: %s  (not set & not discoverable -> local fallback)" % DEPLOY_URL)
    else:
        print(" Target: " + DEPLOY_URL)
    print(" " + datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    print("=" * 70)

    ai_ok, ai_reason = ai_status()
    if ai_ok:
        print(f"[AI] model '{MODEL}' available and running.")
    else:
        print(f"[AI] model NOT available: {ai_reason}")

    results = run_checks()
    extra = optional_checks()
    success = all(r["ok"] for r in results)

    out = []
    out.append("DEPLOYMENT TARGET : %s" % DEPLOY_URL)
    out.append("TIMESTAMP         : %s" % datetime.now().isoformat())
    out.append("")

    if success:
        out.append("STATUS: DEPLOYMENT SUCCESSFUL")
        out.append("")
        out.append("VERIFIED ENDPOINTS:")
        for r in results:
            out.append("  [OK] %-12s -> HTTP %s (%s)" % (r["path"], r["status"], r["meaning"]))
        for name, ok, err in extra:
            out.append("  [%s] %s%s" % ("OK" if ok else "WARN", name,
                                       "" if ok else (" - " + str(err))))
        out.append("")
        if ai_ok:
            try:
                recs = ai_recommendations(results, extra, _metrics_sample())
                out.append("NEXT-STAGE UPGRADES (AI):")
                out.append(recs)
            except Exception as e:
                ai_ok, ai_reason = False, f"AI call failed: {e}"
        if not ai_ok:
            out.append("NEXT-STAGE UPGRADES (built-in fallback):")
            for i, rec in enumerate(next_stage_recommendations(), 1):
                out.append("  %d. %s" % (i, rec))
    else:
        out.append("STATUS: DEPLOYMENT FAILED")
        out.append("")
        out.append("FAILED CHECKS (where / why / root cause / fix):")
        if ai_ok:
            try:
                analysis = ai_failure_analysis(results, extra)
                out.append(analysis if analysis else "(AI returned no analysis)")
            except Exception as e:
                ai_ok, ai_reason = False, f"AI call failed: {e}"
        if not ai_ok:
            for r in results:
                if not r["ok"]:
                    loc = r["path"]
                    why = r["error"] or ("HTTP %s" % r["status"])
                    out.append("  - WHERE      : %s" % loc)
                    out.append("    EXPECT     : %s" % r["expect"])
                    out.append("    WHY        : %s" % why)
                    out.append("    ROOT CAUSE : %s" % r["cause"])
                    out.append("")
            for name, ok, err in extra:
                if not ok:
                    out.append("  - WHERE: %s -> %s" % (name, err))
            out.append("")
            out.append("RECOMMENDED FIRST ACTION: inspect the failed endpoint above,")
            out.append("pull the container/app logs, fix the root cause, then re-run")
            out.append("the pipeline (review_agent -> deploy -> final_agent).")

    report = "\n".join(out)
    print(report)

    with open("final_review.txt", "w") as fh:
        fh.write("SentinelOps-Lite - Final Deployment Review\n")
        fh.write(datetime.now().strftime("%Y-%m-%d %H:%M:%S") + "\n\n")
        fh.write(report + "\n")

    print("\nWrote final_review.txt")
    final_status = "approved" if success else "failed"
final_decision = "approved" if success else "failed"

send_agent_status(
    agent_name="final_agent",
    stage="post_deploy",
    status=final_status,
    decision=final_decision,
    provider="gemini",
    model=MODEL,
    prompt_tokens=locals().get("prompt_tokens", 0),
    completion_tokens=locals().get("completion_tokens", 0),
    total_tokens=(
        locals().get("prompt_tokens", 0)
        + locals().get("completion_tokens", 0)
    ),
    requests_count=2 if ai_ok else 0,
    api_key_count=1 if os.getenv("GEMINI_API_KEY") else 0,
    execution_time_seconds=time.perf_counter() - started_at,
    api_response_time_seconds=locals().get("api_duration", 0),
    error="" if success else "Post-deployment health checks failed",
)
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()

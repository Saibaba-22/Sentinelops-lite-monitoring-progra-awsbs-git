"""
final_agent.py — Post-deployment verification agent for SentinelOps-Lite.

Runs AFTER the deployment finishes and answers one question:
    "Did the deployment succeed, and is the system actually healthy?"

It probes the live environment:
  * GET /health         (expect HTTP 200)
  * GET /api/status     (expect JSON with a deployment section)
  * GET /metrics        (expect 200 + app_* Prometheus metrics)
  * GET /dashboard      (expect 200, HTML)
  * (optional) Prometheus /targets and Grafana /api/health if URLs provided.

Outcomes:
  * FAILURE -> reports WHERE it failed, WHY, and the likely ROOT CAUSE.
  * SUCCESS -> reports health and concrete NEXT-STAGE upgrade recommendations.

The complete review is written to final_review.txt (always) and printed.
Exit code: 0 on success, 1 on failure (so a pipeline can react).

Optional: if GEMINI_API_KEY is set, an LLM root-cause / recommendations
summary is appended (never required).
"""
import os
import sys
import json
import subprocess
import urllib.request
import urllib.error
from datetime import datetime


def discover_deploy_url():
    """Auto-discover the Elastic Beanstalk environment CNAME.

    Uses the EB/AWS CLI with ENV_NAME / APP_NAME / AWS_REGION (already provided
    by the pipeline) so the operator never has to hard-code DEPLOY_URL.
    Returns a full URL (with scheme) or None.
    """
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
            # An EB environment CNAME looks like:
            #     agent.us-east-1.elasticbeanstalk.com
            # It does NOT contain "amazonaws", so we accept both the
            # elasticbeanstalk.com form (EB env CNAME) and any amazonaws.com
            # form (e.g. ELB/ALB endpoints) to avoid a false "not discoverable".
            looks_like_host = (
                "elasticbeanstalk.com" in cname or "amazonaws" in cname
            )
            if cname and cname.lower() != "none" and looks_like_host:
                return "http://" + cname
        except Exception:
            continue
    return None


# --- Resolve target URLs: explicit env overrides win, otherwise auto-discover ---
_explicit = os.getenv("DEPLOY_URL")
_discovered = discover_deploy_url()
if _explicit:
    DEPLOY_URL = _explicit.rstrip("/")
elif _discovered:
    DEPLOY_URL = _discovered.rstrip("/")
else:
    DEPLOY_URL = "http://localhost:5000"   # local fallback when nothing is set

# Prometheus/Grafana are optional; derive from the same host when not given.
_base = DEPLOY_URL.rsplit(":", 1)[0] if "://" in DEPLOY_URL else DEPLOY_URL
PROM_URL = (os.getenv("PROMETHEUS_URL") or (_base + ":9090")).rstrip("/")
GRAFANA_URL = (os.getenv("GRAFANA_URL") or (_base + ":3000")).rstrip("/")

# Critical endpoints that must be healthy for the deploy to count as success.
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


def root_cause(path, status, err):
    """Best-effort human explanation of WHY / root cause."""
    if err:
        if "ConnectionRefused" in err or "timeout" in err.lower():
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


def next_stage_recommendations():
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


def llm_summary(report_text):
    key = os.getenv("GEMINI_API_KEY")
    if not key:
        return None
    try:
        from google import genai
        client = genai.Client(api_key=key)
        resp = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=(
                "You are a senior SRE. Given this post-deployment review, either "
                "explain the root cause in 3 bullets or, if successful, suggest the "
                "top 3 next upgrades in 3 bullets (plain text):\n\n" + report_text
            ),
        )
        return resp.text.strip()
    except Exception as e:
        return f"(LLM summary skipped: {e})"


def main():
    print("=" * 70)
    print(" SentinelOps-Lite — POST-DEPLOYMENT VERIFICATION")
    if not _explicit and _discovered:
        print(" Target: %s  (auto-discovered via EB env '%s')"
              % (DEPLOY_URL, os.getenv("ENV_NAME")))
    elif not _explicit:
        print(" Target: %s  (not set & not discoverable -> local fallback)" % DEPLOY_URL)
    else:
        print(" Target: " + DEPLOY_URL)
    print(" " + datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    print("=" * 70)

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
                                       "" if ok else (" — " + str(err))))
        out.append("")
        out.append("NEXT-STAGE UPGRADES / WHAT CAN BE DONE NEXT:")
        for i, rec in enumerate(next_stage_recommendations(), 1):
            out.append("  %d. %s" % (i, rec))
    else:
        out.append("STATUS: DEPLOYMENT FAILED")
        out.append("")
        out.append("FAILED CHECKS (where / why / root cause):")
        for r in results:
            if not r["ok"]:
                loc = r["path"]
                why = r["error"] or ("HTTP %s" % r["status"])
                out.append("  - WHERE   : %s" % loc)
                out.append("    EXPECT  : %s" % r["expect"])
                out.append("    WHY     : %s" % why)
                out.append("    ROOT CAUSE: %s" % r["cause"])
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

    summary = llm_summary(report)
    if summary:
        print("\n--- LLM SUMMARY ---\n" + summary)
        report += "\n\n--- LLM SUMMARY ---\n" + summary

    with open("final_review.txt", "w") as fh:
        fh.write("SentinelOps-Lite — Final Deployment Review\n")
        fh.write(datetime.now().strftime("%Y-%m-%d %H:%M:%S") + "\n\n")
        fh.write(report + "\n")

    print("\nWrote final_review.txt")
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()

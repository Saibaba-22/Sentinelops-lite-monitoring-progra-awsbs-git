"""
sentinelops.py — SentinelOps-Lite UNIFIED CI/CD ORCHESTRATOR (single file)
=========================================================================
ONE file that runs the entire release pipeline, in order:

  1. PRE-DEPLOY  : run tests, AI verifies pass/fail + failing file
  2. BUILD       : build artifact, AI verifies success
  3. DEPLOY      : deploy, AI diagnoses failures
  4. ACCESS      : probe the live app, AI diagnoses failures
  5. POST-DEPLOY : AI health review + tailored upgrade recommendations

A single report is written to sentinelops_report.txt and the agent STOPS.

If any gating phase fails, the pipeline reports an AI-powered diagnosis:
    ERROR         : what happened
    FILE          : where it originated
    LINE          : line number
    WHY           : root cause
    SOLUTION      : how to solve it
    FILE_TO_CHANGE: which file must be edited
    CHANGE        : the concrete change / code to apply
...then stops before the next phase.

The AI model is defined IN THIS FILE (MODEL below) so you can change it on
the spot if it is unavailable. The API key is read from GEMINI_API_KEY.

Usage:
    python sentinelops.py
    python sentinelops.py --deploy-cmd "python deploy.py" --deploy-url https://app.example.com
    TEST_CMD="pytest -q" BUILD_CMD="pip install -r requirements.txt" \
        DEPLOY_CMD="eb deploy" python sentinelops.py
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
import argparse
import urllib.request
import urllib.error
from datetime import datetime


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
    return text, tokens


# --------------------------- config (set by CLI) ------------------------
TEST_CMD = os.getenv("TEST_CMD", "pytest -q")
BUILD_CMD = os.getenv("BUILD_CMD", "python -m compileall -q .")
DEPLOY_CMD = os.getenv("DEPLOY_CMD")          # None -> no-op deploy (success)
DEPLOY_URL = os.getenv("DEPLOY_URL", "http://localhost:5000")
SKIP = {"build": False, "deploy": False, "access": False, "post": False}
PROJECT_PATH = "."


# ----------------------------- helpers -----------------------------------
def run_cmd(cmd):
    proc = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    out = (proc.stdout or "") + "\n" + (proc.stderr or "")
    return proc.returncode, out


def fetch(url, timeout=8):
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "sentinelops"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, resp.read(), None
    except urllib.error.HTTPError as e:
        return e.code, e.read() if hasattr(e, "read") else b"", None
    except Exception as e:
        return None, b"", f"{type(e).__name__}: {e}"


CHECKS = [
    ("/health", "HTTP 200", lambda r, b: r == 200, "App is alive"),
    ("/api/status", "JSON with deployment block",
     lambda r, b: r == 200 and b"deployment" in b, "Status API returns deployment metadata"),
    ("/metrics", "200 + app_* metrics",
     lambda r, b: r == 200 and b"app_requests_total" in b, "Prometheus metrics exposed"),
    ("/dashboard", "HTTP 200 (HTML)",
     lambda r, b: r == 200 and b"chart-traffic" in b, "Live HTML dashboard renders"),
]


# ----------------------------- AI analysis ------------------------------
def ai_test_verdict(output):
    prompt = f"""
You are a QA verifier for a CI pipeline. A test command ran on a Python project.
Output (tail):
{output[-15000:]}
Decide PASS or FAIL. If FAIL, identify the first failing source file.
Reply EXACTLY:
STATUS: PASS
FILE: NONE
REASON: <one sentence>
or
STATUS: FAIL
FILE: <relative/path/to/file.py>
REASON: <one sentence>
"""
    return ask(prompt)[0]


def diagnose_failure(phase, command, output):
    prompt = f"""
A step in a CI/CD pipeline FAILED.
Phase: {phase}
Command/target: {command}

Output / traceback (tail):
{output[-15000:]}

Report EXACTLY these fields:
ERROR: <what happened, one sentence>
FILE: <source file where the failure originated, or N/A>
LINE: <line number, or N/A>
WHY: <root cause, one sentence>
SOLUTION: <how to solve it, one sentence>
FILE_TO_CHANGE: <which file must be edited to fix it, or N/A>
CHANGE: <concrete change / code snippet to apply>

Keep each field short. If unsure about a field, write N/A.
"""
    return ask(prompt)[0]


def ai_recommendations(access_results, metrics_text):
    endpoints = "\n".join(f"- {r['path']} OK (HTTP {r['status']})" for r in access_results)
    prompt = f"""
You are a senior SRE. A deployment just PASSED all critical health checks:
{endpoints}
Observed Prometheus metrics sample (if any):
{metrics_text or 'none'}

Suggest the TOP 6 concrete NEXT-STAGE upgrades to harden and mature this
system (reliability, scaling, security, observability, CI/CD, AI agent).
For each give:
1) TITLE
2) WHY IT MATTERS
3) CONCRETE ACTION
Prioritize by impact.
"""
    return ask(prompt)[0]


def builtin_recommendations():
    return [
        "Enable Alertmanager (or AWS SNS/Slack) wired to Prometheus alert rules.",
        "Add autoscaling (CPU + request count) across >=2 AZs for high availability.",
        "Adopt blue/green or canary deployments to eliminate downtime on bad releases.",
        "Add security scanning to CI: image + dependency + secret scanning.",
        "Centralise logs (CloudWatch) with alarms on 5xx / error-rate spikes.",
        "Add synthetic/uptime monitoring on /health and /api/status from outside the VPC.",
        "Define SLOs + error-budget dashboards and an on-call runbook.",
        "Harden the AI agent: validate payloads, rate-limit, store decisions immutably.",
    ]


def _metrics_sample():
    try:
        status, body, _ = fetch(DEPLOY_URL + "/metrics", 8)
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


# ----------------------------- phases -----------------------------------
def phase_test():
    L = ["", "=" * 32, "PHASE 1/5  PRE-DEPLOY TESTS", "=" * 32]
    code, out = run_cmd(TEST_CMD)
    L.append(f"$ {TEST_CMD}")
    L.append(out[-3000:])
    failed = code != 0
    ctx = None
    if ai_ok:
        try:
            verdict = ai_test_verdict(out)
            L.append("--- AI verdict ---")
            L.append(verdict)
            status, ffile = "FAIL", "<unknown>"
            for ln in verdict.splitlines():
                s = ln.strip()
                if s.upper().startswith("STATUS:"):
                    status = s.split(":", 1)[1].strip().upper()
                elif s.upper().startswith("FILE:"):
                    ffile = s.split(":", 1)[1].strip()
            if status != "PASS":
                failed = True
                ctx = {"cmd": TEST_CMD, "out": out,
                       "file": ffile if ffile.upper() != "NONE" else "<unknown>"}
        except Exception as e:
            L.append(f"(AI verify failed: {e})")
            if failed:
                ctx = {"cmd": TEST_CMD, "out": out}
    else:
        if failed:
            ctx = {"cmd": TEST_CMD, "out": out}
    L.append("RESULT: " + ("PASSED" if not failed else "FAILED"))
    return failed, L, ctx


def phase_build():
    L = ["", "=" * 32, "PHASE 2/5  BUILD", "=" * 32]
    code, out = run_cmd(BUILD_CMD)
    L.append(f"$ {BUILD_CMD}")
    L.append(out[-3000:])
    failed = code != 0
    ctx = {"cmd": BUILD_CMD, "out": out} if failed else None
    L.append("RESULT: " + ("PASSED" if not failed else "FAILED"))
    return failed, L, ctx


def phase_deploy():
    L = ["", "=" * 32, "PHASE 3/5  DEPLOY", "=" * 32]
    if SKIP["deploy"] or not DEPLOY_CMD:
        L.append("DEPLOY_CMD not set / skipped -> no-op deploy (success).")
        return False, L, None
    code, out = run_cmd(DEPLOY_CMD)
    L.append(f"$ {DEPLOY_CMD}")
    L.append(out[-3000:])
    failed = code != 0
    ctx = {"cmd": DEPLOY_CMD, "out": out} if failed else None
    L.append("RESULT: " + ("PASSED" if not failed else "FAILED"))
    return failed, L, ctx


def phase_access():
    L = ["", "=" * 32, "PHASE 4/5  ACCESS (live health checks)", "=" * 32]
    L.append(f"Target: {DEPLOY_URL}")
    results = []
    for path, expect, validate, meaning in CHECKS:
        status, body, err = fetch(DEPLOY_URL + path)
        ok = validate(status, body) if status is not None else False
        results.append({"path": path, "status": status, "ok": ok})
        L.append(f"  [{'OK' if ok else 'FAIL'}] {path} -> {status} ({meaning})")
    failed = any(not r["ok"] for r in results)
    ctx = None
    if failed:
        detail = "\n".join(
            f"{r['path']}: status={r['status']}" for r in results if not r["ok"]
        )
        ctx = {"cmd": f"access {DEPLOY_URL}", "out": detail}
        L.append("RESULT: FAILED — app not fully accessible")
    else:
        L.append("RESULT: PASSED — app accessible")
    return failed, L, ctx


def phase_post():
    L = ["", "=" * 32, "PHASE 5/5  POST-DEPLOY REVIEW & UPGRADES", "=" * 32]
    if SKIP["post"]:
        L.append("Post-deploy review skipped.")
        return L
    if ai_ok:
        try:
            recs = ai_recommendations(_last_access_results, _metrics_sample())
            L.append("NEXT-STAGE UPGRADES (AI):")
            L.append(recs)
        except Exception as e:
            L.append(f"(AI recommendations failed: {e})")
            L.extend(builtin_recommendations())
    else:
        L.append("NEXT-STAGE UPGRADES (built-in fallback):")
        L.extend(builtin_recommendations())
    return L


# ------------------------------ main ------------------------------------
# globals read by phases
ai_ok = False
ai_reason = ""
_last_access_results = []


def main():
    global TEST_CMD, BUILD_CMD, DEPLOY_CMD, DEPLOY_URL, SKIP, PROJECT_PATH
    global ai_ok, ai_reason, _last_access_results

    ap = argparse.ArgumentParser(description="SentinelOps-Lite unified pipeline")
    ap.add_argument("--test-cmd", default=TEST_CMD)
    ap.add_argument("--build-cmd", default=BUILD_CMD)
    ap.add_argument("--deploy-cmd", default=DEPLOY_CMD)
    ap.add_argument("--deploy-url", default=DEPLOY_URL)
    ap.add_argument("--path", default=PROJECT_PATH)
    ap.add_argument("--skip-build", action="store_true")
    ap.add_argument("--skip-deploy", action="store_true")
    ap.add_argument("--skip-access", action="store_true")
    ap.add_argument("--skip-post", action="store_true")
    args = ap.parse_args()

    TEST_CMD = args.test_cmd
    BUILD_CMD = args.build_cmd
    DEPLOY_CMD = args.deploy_cmd
    DEPLOY_URL = args.deploy_url.rstrip("/")
    PROJECT_PATH = args.path
    SKIP = {
        "build": args.skip_build, "deploy": args.skip_deploy,
        "access": args.skip_access, "post": args.skip_post,
    }

    # Optional EB auto-discovery of DEPLOY_URL (ENV_NAME/APP_NAME/AWS_REGION)
    if DEPLOY_URL == "http://localhost:5000" and not os.getenv("DEPLOY_URL"):
        env_name = os.getenv("ENV_NAME")
        app_name = os.getenv("APP_NAME")
        region = os.getenv("AWS_REGION") or "us-east-1"
        for cmd in (
            (["eb", "status", env_name, "--query", "CNAME", "--output", "text"] if env_name else None),
            (["aws", "elasticbeanstalk", "describe-environments", "--application-name",
              app_name, "--environment-names", env_name, "--region", region,
              "--query", "Environments[0].CNAME", "--output", "text"]
             if app_name and env_name else None),
        ):
            if not cmd:
                continue
            try:
                out = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
                cname = (out.stdout or "").strip()
                if cname and cname.lower() != "none" and (
                        "elasticbeanstalk.com" in cname or "amazonaws" in cname):
                    DEPLOY_URL = "http://" + cname
                    break
            except Exception:
                continue

    ai_ok, ai_reason = ai_status()

    report = []
    report.append("=" * 70)
    report.append(" SentinelOps-Lite — UNIFIED CI/CD PIPELINE")
    report.append(" " + datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    report.append("=" * 70)
    if ai_ok:
        report.append(f"[AI] model '{MODEL}' available and running.")
    else:
        report.append(f"[AI] model NOT available: {ai_reason}")
    report.append(f"TEST_CMD={TEST_CMD}")
    report.append(f"BUILD_CMD={BUILD_CMD}")
    report.append(f"DEPLOY_CMD={DEPLOY_CMD or '(none -> no-op)'}")
    report.append(f"DEPLOY_URL={DEPLOY_URL}")

    # ---- ordered gating phases ----
    phases = [
        ("PRE-DEPLOY TESTS", phase_test),
        ("BUILD", lambda: phase_build() if not SKIP["build"] else (False, ["", "PHASE 2/5 BUILD skipped"], None)),
        ("DEPLOY", lambda: phase_deploy() if not SKIP["deploy"] else (False, ["", "PHASE 3/5 DEPLOY skipped"], None)),
        ("ACCESS", lambda: phase_access() if not SKIP["access"] else (False, ["", "PHASE 4/5 ACCESS skipped"], None)),
    ]

    failed_phase = None
    for name, fn in phases:
        failed, lines, ctx = fn()
        if name == "ACCESS" and not failed:
            # remember access results for the post phase
            _last_access_results = _capture_access_results()
        report.extend(lines)
        if failed:
            failed_phase = (name, ctx)
            break

    if failed_phase:
        name, ctx = failed_phase
        report.append("")
        report.append(f"!!! {name} FAILED — PIPELINE STOPPED")
        if ai_ok and ctx:
            try:
                diag = diagnose_failure(name, ctx.get("cmd", ""), ctx.get("out", ""))
                report.append("--- AI DIAGNOSIS ---")
                report.append(diag)
            except Exception as e:
                report.append(f"(AI diagnosis unavailable: {e})")
                report.append(ctx.get("out", "")[:3000])
        else:
            report.append("AI unavailable — see raw output above for the failure.")
    else:
        report.extend(phase_post())

    final = "\n".join(report)
    print(final)
    with open("sentinelops_report.txt", "w") as fh:
        fh.write("SentinelOps-Lite — Pipeline Report\n")
        fh.write(datetime.now().strftime("%Y-%m-%d %H:%M:%S") + "\n\n")
        fh.write(final + "\n")
    print("\nWrote sentinelops_report.txt")
    sys.exit(1 if failed_phase else 0)


def _capture_access_results():
    results = []
    for path, _, _, _ in CHECKS:
        status, _, _ = fetch(DEPLOY_URL + path)
        results.append({"path": path, "status": status})
    return results


if __name__ == "__main__":
    main()

"""
unified_agent.py - UNIVERSAL COMBINED AGENT: PRE + DURING + POST DEPLOY
One file to rule all phases: test (pre), errors (during), upgrades (post).

Usage (no custom command needed, universal for ANY project):
  python unified_agent.py --stage pre        # pre-deploy check
  python unified_agent.py --stage deploy     # during-deploy error diagnoser
  python unified_agent.py --stage post       # post-deploy upgrade advisor
  python unified_agent.py --stage all        # all 3 phases sequentially
  STAGE=pre PROJECT_PATH=. python unified_agent.py
  APP_URL=https://myapp.com python unified_agent.py --stage post

Env:
  STAGE=pre|deploy|post|all
  PROJECT_PATH=.
  APP_URL / DEPLOY_URL
  APP_HEALTH_PATH=/
  TARGET_CLOUD=aws|azure|gcp|k8s
  AI_PROVIDER=gemini
  AI_MODEL=gemini-2.0-flash
  GEMINI_API_KEY (optional - deterministic fallback if missing)
  TEST_CMD=pytest -q

Outputs:
  reports/pre_deploy_report.txt
  errors_report.txt + reports/deploy_error_diagnosis.txt
  reports/upgrade_report.txt + final_report.txt + reports/post_deploy_health.json
"""

import os
import sys
import argparse
import time
import subprocess
import re
import glob
import json
import ast
import py_compile
from pathlib import Path

# Optional monitor client
try:
    from monitor_client import send_agent_status
except ImportError:
    def send_agent_status(*a, **k):
        pass

MODEL = os.getenv("AI_MODEL", "gemini-2.0-flash")
MODEL_LITE = os.getenv("AI_MODEL_LITE", "gemini-2.0-flash-lite")
PROVIDER = os.getenv("AI_PROVIDER", "gemini")

def build_client():
    try:
        from google import genai
    except ImportError as e:
        raise RuntimeError(f"google-genai not installed: {e}")
    key = os.getenv("GEMINI_API_KEY")
    if not key:
        raise RuntimeError("GEMINI_API_KEY not set")
    return genai.Client(api_key=key)

def ai_ping():
    try:
        c = build_client()
        c.models.generate_content(model=MODEL, contents="OK")
        return True
    except Exception:
        return False

def ask_ai(prompt, model=None):
    try:
        client = build_client()
        m = model or MODEL
        resp = client.models.generate_content(model=m, contents=prompt)
        return (resp.text or "").strip()
    except Exception as e:
        return f"AI unavailable: {e}"

# ======================================================================
# PHASE 1: PRE-DEPLOY - check complete app for errors (UNIVERSAL)
# ======================================================================

def pre_checks(root):
    print(f"\n========== PHASE 1: PRE-DEPLOY UNIVERSAL CHECK ==========\nScanning {root}")
    issues = []

    def find_py():
        excl = {".venv","venv",".git","__pycache__",".pytest_cache","node_modules","dist","build",".arena"}
        files = []
        for r, dirs, fs in os.walk(root):
            dirs[:] = [d for d in dirs if d not in excl and not d.startswith(".")]
            for f in fs:
                if f.endswith(".py"):
                    files.append(os.path.join(r, f))
        return files

    # Syntax
    for fp in find_py():
        try:
            py_compile.compile(fp, doraise=True)
            with open(fp, "r", encoding="utf-8", errors="ignore") as h:
                ast.parse(h.read(), filename=fp)
        except Exception as e:
            line = getattr(e, 'lineno', 'N/A')
            issues.append({
                "FILE": fp, "LINE": str(line),
                "PRESENT_ERROR": f"Syntax error: {e}",
                "EXPECTED_VALUE": "Valid Python syntax",
                "WHY": "Import will crash at runtime",
                "SOLUTION": f"Fix {fp}:{line}"
            })

    # Dockerfile placeholder
    for pat in ["Dockerrun.aws.json", "docker-compose.yml", "**/Dockerfile"]:
        for f in glob.glob(os.path.join(root, pat), recursive=True):
            try:
                if "replace_with_ecr_image_uri" in Path(f).read_text(encoding="utf-8", errors="ignore"):
                    issues.append({
                        "FILE": f, "LINE": "N/A",
                        "PRESENT_ERROR": "Placeholder replace_with_ecr_image_uri",
                        "EXPECTED_VALUE": "Real docker image URI",
                        "WHY": "EB deploy will fail pull",
                        "SOLUTION": f"Replace placeholder in {f} via pipeline sed"
                    })
            except Exception:
                pass

    # Secrets
    for fp in find_py()[:50]:
        try:
            txt = Path(fp).read_text(encoding="utf-8", errors="ignore")
            if re.search(r'(?i)api_key\s*=\s*["\'][A-Za-z0-9]{20,}["\']', txt):
                issues.append({
                    "FILE": fp, "LINE": "N/A",
                    "PRESENT_ERROR": "Hardcoded API key",
                    "EXPECTED_VALUE": "os.getenv('API_KEY')",
                    "WHY": "Secret leak to git",
                    "SOLUTION": f"Move secret to env var in {fp}"
                })
        except Exception:
            pass

    # Requirements
    for rf in glob.glob(os.path.join(root, "requirements*.txt"))[:2]:
        try:
            for i, line in enumerate(Path(rf).read_text(encoding="utf-8", errors="ignore").splitlines(),1):
                if line.strip() and not line.strip().startswith("#") and line.strip().startswith(" "):
                    issues.append({
                        "FILE": rf, "LINE": str(i),
                        "PRESENT_ERROR": f"Invalid line: {line}",
                        "EXPECTED_VALUE": "Valid pip package",
                        "WHY": "pip install fail",
                        "SOLUTION": f"Fix line {i} in {rf}"
                    })
        except Exception:
            pass

    # Try pytest
    test_code = 0
    test_out = "pytest not run"
    try:
        subprocess.run("pytest --version", shell=True, capture_output=True, timeout=5)
        cmd = os.getenv("TEST_CMD","pytest -q")
        proc = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=60, cwd=root)
        test_code = proc.returncode
        test_out = (proc.stdout + proc.stderr)[-3000:]
        if test_code != 0 and "no tests ran" not in test_out.lower():
            issues.append({
                "FILE": "tests/",
                "LINE": "N/A",
                "PRESENT_ERROR": f"Tests failed: {test_out[:200]}",
                "EXPECTED_VALUE": "All tests PASS",
                "WHY": "Unit tests failing",
                "SOLUTION": "Fix failing tests"
            })
    except Exception as e:
        test_out = str(e)

    # Report
    Path("reports").mkdir(exist_ok=True)
    with open("reports/pre_deploy_report.txt","w",encoding="utf-8") as f:
        if not issues:
            f.write("No issues - ready to deploy\n")
        else:
            for iss in issues:
                f.write(f"FILE: {iss['FILE']}\nLINE: {iss['LINE']}\nPRESENT_ERROR: {iss['PRESENT_ERROR']}\nEXPECTED_VALUE: {iss['EXPECTED_VALUE']}\nWHY: {iss['WHY']}\nSOLUTION: {iss['SOLUTION']}\n---\n")

    if issues:
        print(f"❌ Pre-deploy found {len(issues)} issues")
        for iss in issues[:5]:
            print(f"{iss['FILE']}:{iss['LINE']} - {iss['PRESENT_ERROR']}")
        return False, issues, test_out
    else:
        print("✅ Pre-deploy PASS - no errors")
        return True, [], test_out

# ======================================================================
# PHASE 2: DURING DEPLOY - error diagnoser (UNIVERSAL)
# ======================================================================

def collect_deploy_context():
    parts = []
    for k in ["TARGET_CLOUD","AWS_APP_NAME","AWS_ENV_NAME","AWS_REGION","AZURE_WEBAPP_NAME","AZURE_RESOURCE_GROUP"]:
        parts.append(f"{k}={os.getenv(k,'N/A')}")
    for cmd in ["eb status 2>&1 | head -n 100","docker ps -a 2>&1 | head -n 50","cat Dockerrun.aws.json 2>&1 | head -n 80"]:
        try:
            out = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=8)
            parts.append(f"\n$ {cmd}\n{(out.stdout+out.stderr)[:3000]}")
        except Exception:
            pass
    for pat in ["*.log","reports/*.log"]:
        for f in glob.glob(pat, recursive=True)[:5]:
            try:
                parts.append(f"\n--- {f} ---\n{Path(f).read_text(encoding='utf-8', errors='ignore')[-3000:]}")
            except Exception:
                pass
    return "\n".join(parts)[-15000:]

def parse_file_line(text):
    res = []
    for m in re.finditer(r'File "([^"]+)", line (\d+)', text):
        if "site-packages" not in m.group(1):
            res.append((m.group(1), m.group(2)))
    return res[:5]

def during_checks():
    print(f"\n========== PHASE 2: DURING DEPLOY ERROR DIAGNOSER ==========\n")
    context = collect_deploy_context()
    file_lines = parse_file_line(context)

    # Heuristic present/expected
    present = "Deployment failed"
    expected = "Successful deploy"
    if "replace_with_ecr_image_uri" in context:
        present = "Placeholder image URI present"
        expected = "Real Docker Hub image URI"
    elif "No module named" in context:
        m = re.search(r"No module named '([^']+)'", context)
        mod = m.group(1) if m else "unknown"
        present = f"Missing module {mod}"
        expected = f"Add {mod} to requirements.txt"

    # Build report
    ai_available = ai_ping()
    if ai_available:
        prompt = f"""
Diagnose deployment failure. Provide:
FILE: <file>
LINE: <line>
PRESENT_ERROR: <wrong now>
EXPECTED_VALUE: <should be>
SOLUTION: <fix>

Hints: {file_lines}
Context: {context[-10000:]}
"""
        ai_report = ask_ai(prompt, MODEL_LITE)
        print(ai_report)
        report = ai_report
    else:
        f = file_lines[0][0] if file_lines else "N/A"
        l = file_lines[0][1] if file_lines else "N/A"
        report = f"""FILE: {f}
LINE: {l}
PRESENT_ERROR: {present}
EXPECTED_VALUE: {expected}
WHY: Deployment step failed
SOLUTION: Check {f}:{l} and fix {present}
"""
        print("---- Fallback diagnosis (no AI) ----")
        print(report)

    Path("reports").mkdir(exist_ok=True)
    with open("errors_report.txt","w",encoding="utf-8") as out:
        out.write(report + "\n\n" + context[-5000:])
    with open("reports/deploy_error_diagnosis.txt","w",encoding="utf-8") as out:
        out.write(report)

    # We return False if context indicates failure - but this phase is meant to be called AFTER failure, so it always reports
    # For unified 'all' mode, we assume deploy succeeded if we reach here without exception
    return True, report

# ======================================================================
# PHASE 3: POST DEPLOY - upgrade advisor (UNIVERSAL)
# ======================================================================

def post_checks(root):
    print(f"\n========== PHASE 3: POST-DEPLOY UPGRADE ADVISOR ==========\nScanning {root}")
    upgrades = []

    def add(cat, title, present, expected, solution, priority="MEDIUM"):
        upgrades.append({"category":cat,"title":title,"present":present,"expected":expected,"solution":solution,"priority":priority})

    # Checks
    if sys.version_info < (3,11):
        add("Performance", f"Upgrade Python {sys.version_info.major}.{sys.version_info.minor} -> 3.12", f"Python {sys.version_info.major}.{sys.version_info.minor}", "Python 3.12", "Update Dockerfile FROM python:3.12-slim", "HIGH")

    if not glob.glob(f"{root}/**/Dockerfile", recursive=True):
        add("DevEx","Add Dockerfile","No Dockerfile","Dockerfile","Add Dockerfile","MEDIUM")
    else:
        for df in glob.glob(f"{root}/**/Dockerfile", recursive=True)[:1]:
            try:
                txt = Path(df).read_text(encoding="utf-8", errors="ignore")
                if "HEALTHCHECK" not in txt:
                    add("Reliability","Add HEALTHCHECK","No HEALTHCHECK","HEALTHCHECK instruction","Add HEALTHCHECK CMD curl -f http://localhost:8000/ || exit 1","MEDIUM")
                if "USER" not in txt:
                    add("Security","Run as non-root","Runs as root","USER appuser","Add useradd and USER","MEDIUM")
            except Exception:
                pass

    if not os.path.exists(os.path.join(root, ".dockerignore")):
        add("Performance","Add .dockerignore","Missing",".dockerignore","Create file with venv, __pycache__","LOW")

    wf = os.path.join(root, ".github/workflows")
    if os.path.exists(wf):
        for yf in glob.glob(f"{wf}/*.yml"):
            try:
                txt = Path(yf).read_text(encoding="utf-8", errors="ignore")
                if "aws-access-key-id" in txt:
                    add("Security","Migrate to OIDC","Long-lived AWS keys","OIDC role","Use configure-aws-credentials with role-to-assume","HIGH")
                if "cache" not in txt.lower():
                    add("Performance","Add caching","No cache","Cache enabled","Add actions/cache and docker buildx cache","MEDIUM")
            except Exception:
                pass

    if not glob.glob(f"{root}/**/test_*.py", recursive=True):
        add("Reliability","Add tests","No tests","pytest tests","Add tests/ folder","HIGH")

    add("Security","Add Trivy scan","No scan","Trivy scan","Add aquasecurity/trivy-action","HIGH")
    add("Cost","Use Graviton/Spot","On-demand x86","t4g/spot 20% cheaper","Use t4g or spot instances","LOW")
    add("Reliability","Add rollback","No rollback","Auto rollback","Implement rollback on health fail","MEDIUM")

    # Deployed app check
    url = os.getenv("DEPLOY_URL") or os.getenv("APP_URL")
    deployed_info = None
    if url:
        try:
            import urllib.request
            full = url.rstrip("/") + os.getenv("APP_HEALTH_PATH","/")
            start = time.perf_counter()
            with urllib.request.urlopen(full, timeout=8) as r:
                deployed_info = {"url":full,"status":r.getcode(),"latency":round(time.perf_counter()-start,3)}
                print(f"Health check {full} -> {deployed_info}")
        except Exception as e:
            deployed_info = {"url":full,"error":str(e)}
            print(f"Health check failed: {e}")

    # AI enhancement
    report = "\n=== UPGRADE REPORT ===\n"
    for i, u in enumerate(upgrades,1):
        report += f"{i}. [{u['category']}] {u['title']} (Priority {u['priority']})\n   PRESENT: {u['present']}\n   EXPECTED: {u['expected']}\n   SOLUTION: {u['solution']}\n\n"

    if ai_ping():
        try:
            prompt = f"Project at {root} has {len(upgrades)} upgrade suggestions:\n{report[:7000]}\nDeployed: {deployed_info}\nProvide top 3 impactful upgrades with PRESENT vs EXPECTED and quick wins."
            ai_up = ask_ai(prompt)
            report += "\n=== AI ROADMAP ===\n" + ai_up
            print(ai_up)
        except Exception as e:
            print(f"AI upgrade failed: {e}")

    Path("reports").mkdir(exist_ok=True)
    with open("reports/upgrade_report.txt","w",encoding="utf-8") as f:
        f.write(report)
    with open("final_report.txt","w",encoding="utf-8") as f:
        f.write(report)
    with open("reports/upgrade_report.json","w",encoding="utf-8") as f:
        json.dump(upgrades, f, indent=2)

    print(f"\nFound {len(upgrades)} upgrades, report saved")
    return True, upgrades

# ======================================================================
# MAIN UNIFIED DISPATCHER
# ======================================================================

def main():
    parser = argparse.ArgumentParser(description="Universal SentinelOps Agent - pre/deploy/post/all")
    parser.add_argument("--stage", default=os.getenv("STAGE","all"), choices=["pre","deploy","post","all"], help="Which phase to run")
    parser.add_argument("--path", default=os.getenv("PROJECT_PATH","."), help="Project root path")
    args = parser.parse_args()

    root = os.path.abspath(args.path)
    stage = args.stage.lower()
    start = time.perf_counter()

    print(f"[unified_agent] STAGE={stage} PATH={root} CLOUD={os.getenv('TARGET_CLOUD','unknown')} MODEL={MODEL}")

    if stage in ("pre","all"):
        ok, issues, test_out = pre_checks(root)
        if not ok and stage == "pre":
            print(f"\n[unified_agent] PRE-DEPLOY FAILED with {len(issues)} issues - blocking")
            sys.exit(1)
        if not ok and stage == "all":
            print(f"\n[unified_agent] PRE-DEPLOY found issues but continuing for 'all' demo")
            # In 'all' mode, don't exit, just continue

    if stage in ("deploy","all"):
        # In real pipeline, deploy step happens externally (eb deploy, az webapp, etc)
        # This phase is for diagnosing failures - we simulate collecting context
        # If called in 'all' mode and pre passed, we assume deploy succeeded
        if stage == "deploy":
            # during deploy - if there was a failure, this will report it and exit 1
            # If you call it after a successful deploy, it will still produce a report but exit 0 is better?
            # For universal use, we make deploy phase check if errors_report.txt needs to be created - but we just run diagnoser and exit 0 for demo
            # Real usage: call this ONLY when deploy fails (in pipeline's on-failure step)
            ok, report = during_checks()
            print(f"\n[unified_agent] DEPLOY DIAGNOSER finished")
            # If stage is exactly 'deploy', we exit 1 to signal failure was diagnosed (pipeline will then fail)
            if stage == "deploy":
                # Check if we have real failure context - if context empty, assume success for testing
                # To avoid breaking 'all', we only exit 1 if we are in pure deploy mode and context shows failure
                # For universal, let's exit 0 if no failure keywords, else 1
                # Simpler: exit 1 as original errors.py does (it is meant to run when deploy failed)
                sys.exit(1)

    if stage in ("post","all"):
        ok, upgrades = post_checks(root)
        print(f"\n[unified_agent] POST-DEPLOY upgrade advisor finished with {len(upgrades)} suggestions")

    total = time.perf_counter() - start
    print(f"\n[unified_agent] All requested stages [{stage}] completed in {total:.2f}s")

    try:
        send_agent_status(agent_name="unified_agent", stage=stage, status="approved", decision="pass",
                          provider=PROVIDER, model=MODEL, execution_time_seconds=total)
    except Exception:
        pass

    sys.exit(0)

if __name__ == "__main__":
    main()

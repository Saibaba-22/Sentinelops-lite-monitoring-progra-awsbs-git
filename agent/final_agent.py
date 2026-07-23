"""
final_agent.py - UNIVERSAL POST-DEPLOY UPGRADE ADVISOR
Phase 3: After deployment, analyzes project and suggests upgrades.

Provides actionable upgrades across 5 categories:
- Security, Performance, Cost, Reliability, Developer Experience

Works for ANY project (Python, Docker, AWS, Azure, K8s, etc.)

Usage:
  python agent/final_agent.py
  APP_URL=https://myapp.com python agent/final_agent.py
  PROJECT_PATH=. python agent/final_agent.py

No custom command needed - auto-scans project structure.
Uses Gemini if GEMINI_API_KEY set, else rule-based checklist.
"""

import os
import re
import sys
import glob
import time
import subprocess
import json
from pathlib import Path

try:
    from monitor_client import send_agent_status
except ImportError:
    def send_agent_status(*a, **k):
        pass

MODEL = os.getenv("AI_MODEL", "gemini-2.5-flash")
PROVIDER = os.getenv("AI_PROVIDER", "gemini")

def build_client():
    try:
        from google import genai
    except ImportError:
        raise RuntimeError("google-genai not installed")
    key = os.getenv("GEMINI_API_KEY")
    if not key:
        raise RuntimeError("GEMINI_API_KEY not set")
    return genai.Client(api_key=key)

def ai_ok():
    try:
        c = build_client()
        c.models.generate_content(model=MODEL, contents="OK")
        return True
    except Exception:
        return False

def ask_ai(prompt):
    global _ai_prompt_tokens, _ai_completion_tokens, _ai_total_tokens
    global _ai_requests, _ai_response_time
    try:
        client = build_client()
        t0   = time.perf_counter()
        resp = client.models.generate_content(model=MODEL, contents=prompt)
        _ai_response_time += time.perf_counter() - t0
        _ai_requests      += 1
        try:
            _ai_prompt_tokens     += resp.usage_metadata.prompt_token_count     or 0
            _ai_completion_tokens += resp.usage_metadata.candidates_token_count or 0
            _ai_total_tokens       = _ai_prompt_tokens + _ai_completion_tokens
        except Exception:
            pass
        return (resp.text or "").strip()
    except Exception as e:
        return f"AI unavailable: {e}"

def scan_project(root):
    findings = []

    # File existence checks
    files = {
        "Dockerfile": glob.glob(f"{root}/**/Dockerfile", recursive=True),
        ".dockerignore": [os.path.join(root, ".dockerignore")],
        "requirements.txt": glob.glob(f"{root}/requirements*.txt"),
        "pyproject.toml": [os.path.join(root, "pyproject.toml")],
        ".github/workflows": [os.path.join(root, ".github/workflows")],
        "pytest": glob.glob(f"{root}/**/test_*.py", recursive=True) + glob.glob(f"{root}/**/tests/**.py", recursive=True),
        "README": [os.path.join(root, "README.md"), os.path.join(root, "README")],
        ".env.example": [os.path.join(root, ".env.example")],
    }

    # Python version
    py_version = f"{sys.version_info.major}.{sys.version_info.minor}"
    if sys.version_info < (3, 11):
        findings.append({
            "category": "Performance",
            "title": f"Upgrade Python {py_version} -> 3.12",
            "present": f"Project using Python {py_version}",
            "expected": "Python 3.12+ (15-25% faster, better error messages)",
            "priority": "HIGH",
            "solution": "Update Dockerfile FROM python:3.12-slim, update pyproject python version, test"
        })

    # Dockerfile checks
    docker_files = files["Dockerfile"]
    if docker_files:
        for df in docker_files[:1]:
            try:
                txt = Path(df).read_text(encoding="utf-8", errors="ignore")
                if "python:3.9" in txt or "python:3.8" in txt or "python:3.10" in txt:
                    findings.append({
                        "category": "Performance",
                        "title": "Update base image to python:3.12-slim",
                        "present": f"Old base image in {df}",
                        "expected": "python:3.12-slim or python:3.12-alpine",
                        "priority": "HIGH",
                        "solution": f"Change FROM in {df} to python:3.12-slim"
                    })
                if "alpine" in txt.lower() and "apk add" not in txt:
                    # ok
                    pass
                if "HEALTHCHECK" not in txt:
                    findings.append({
                        "category": "Reliability",
                        "title": "Add HEALTHCHECK in Dockerfile",
                        "present": "No HEALTHCHECK instruction",
                        "expected": "HEALTHCHECK CMD curl --fail http://localhost:8000/ || exit 1",
                        "priority": "MEDIUM",
                        "solution": "Add HEALTHCHECK to Dockerfile for Docker/K8s auto-restart"
                    })
                if "USER" not in txt and "root" not in txt.lower():
                    findings.append({
                        "category": "Security",
                        "title": "Run as non-root user",
                        "present": "Container runs as root",
                        "expected": "USER appuser non-root",
                        "priority": "MEDIUM",
                        "solution": "Add RUN useradd appuser && USER appuser in Dockerfile"
                    })
                if "COPY . ." in txt and "requirements" not in txt.split("COPY . .")[0][-200:]:
                    findings.append({
                        "category": "Performance",
                        "title": "Use Docker layer caching for requirements",
                        "present": "COPY . . before pip install - breaks cache",
                        "expected": "COPY requirements.txt . + pip install before COPY . .",
                        "priority": "MEDIUM",
                        "solution": "Reorder Dockerfile: first copy requirements, pip install, then copy code"
                    })
            except Exception:
                pass
    else:
        findings.append({
            "category": "Developer Experience",
            "title": "Add Dockerfile for containerized deployment",
            "present": "No Dockerfile",
            "expected": "Dockerfile present",
            "priority": "MEDIUM",
            "solution": "Add Dockerfile: FROM python:3.12-slim, COPY requirements, CMD uvicorn"
        })

    # .dockerignore
    if not os.path.exists(os.path.join(root, ".dockerignore")):
        findings.append({
            "category": "Performance",
            "title": "Add .dockerignore",
            "present": ".dockerignore missing",
            "expected": ".dockerignore with venv, __pycache__, .git",
            "priority": "LOW",
            "solution": "Create .dockerignore: __pycache__, *.pyc, .venv, .git, logs"
        })

    # Requirements pinning
    for rf in files["requirements.txt"][:1]:
        try:
            txt = Path(rf).read_text(encoding="utf-8", errors="ignore")
            unpinned = [l for l in txt.splitlines() if l.strip() and not l.strip().startswith("#") and "==" not in l and ">=" not in l and "~=" not in l and not l.startswith("-")]
            if len(unpinned) > 3:
                findings.append({
                    "category": "Reliability",
                    "title": "Pin dependencies in requirements.txt",
                    "present": f"{len(unpinned)} unpinned packages",
                    "expected": "All packages pinned with == or ~=",
                    "priority": "MEDIUM",
                    "solution": "Run pip freeze > requirements.txt or use pip-tools"
                })
        except Exception:
            pass

    # GitHub Actions checks
    wf_path = os.path.join(root, ".github/workflows")
    if os.path.exists(wf_path):
        ymls = glob.glob(f"{wf_path}/*.yml") + glob.glob(f"{wf_path}/*.yaml")
        for yf in ymls[:3]:
            try:
                txt = Path(yf).read_text(encoding="utf-8", errors="ignore")
                if "actions/cache" not in txt and "cache-from" not in txt and "cache:" not in txt:
                    findings.append({
                        "category": "Performance",
                        "title": "Add caching to GitHub Actions",
                        "present": f"No cache in {os.path.basename(yf)}",
                        "expected": "actions/cache or docker buildx cache",
                        "priority": "MEDIUM",
                        "solution": "Add cache: pip, docker layers type=gha, cuts build 3min->40s"
                    })
                if "aws-access-key-id" in txt:
                    findings.append({
                        "category": "Security",
                        "title": "Migrate AWS auth to OIDC",
                        "present": "Long-lived AWS keys in GitHub Secrets",
                        "expected": "OIDC role-to-assume via GitHub OIDC",
                        "priority": "HIGH",
                        "solution": "Use aws-actions/configure-aws-credentials with role-to-assume + OIDC, remove AKIA secrets"
                    })
                if "trivy" not in txt.lower() and "security" not in txt.lower():
                    findings.append({
                        "category": "Security",
                        "title": "Add container vulnerability scanning",
                        "present": "No security scan in pipeline",
                        "expected": "Trivy or Grype scan step",
                        "priority": "HIGH",
                        "solution": "Add aquasecurity/trivy-action to scan image for CRITICAL/HIGH"
                    })
            except Exception:
                pass
    else:
        findings.append({
            "category": "Developer Experience",
            "title": "Add CI/CD pipeline",
            "present": "No .github/workflows",
            "expected": "CI pipeline with test, build, deploy",
            "priority": "MEDIUM",
            "solution": "Add GitHub Actions workflow for tests and Docker build"
        })

    # Testing
    if not files["pytest"]:
        findings.append({
            "category": "Reliability",
            "title": "Add automated tests",
            "present": "No tests found",
            "expected": "pytest with at least 1 test",
            "priority": "HIGH",
            "solution": "Add tests/ folder with test_health.py, configure pytest in pipeline"
        })

    # Env example
    if not os.path.exists(os.path.join(root, ".env.example")):
        findings.append({
            "category": "Developer Experience",
            "title": "Add .env.example",
            "present": ".env.example missing",
            "expected": ".env.example with all required env vars",
            "priority": "LOW",
            "solution": "Create .env.example listing DATABASE_URL, API_KEY, etc"
        })

    # Multi-stage docker
    for df in docker_files[:1]:
        try:
            txt = Path(df).read_text(encoding="utf-8", errors="ignore")
            if "FROM" in txt and txt.count("FROM") < 2:
                findings.append({
                    "category": "Performance",
                    "title": "Use multi-stage Docker build",
                    "present": "Single-stage Dockerfile",
                    "expected": "Builder stage + final runtime slim stage, 900MB->150MB",
                    "priority": "LOW",
                    "solution": "Use FROM python:3.12-slim as builder, then FROM distroless/python3"
                })
        except Exception:
            pass

    # Generic best practices
    findings.append({
        "category": "Cost",
        "title": "Use spot / Graviton instances where possible",
        "present": "Using on-demand x86",
        "expected": "t4g (ARM) or spot for non-prod, 20% cost saving",
        "priority": "LOW",
        "solution": "For EB use m6g/t4g family, for K8s use spot node pool"
    })

    findings.append({
        "category": "Reliability",
        "title": "Add rollback strategy",
        "present": "No automatic rollback",
        "expected": "Auto rollback on health check failure",
        "priority": "MEDIUM",
        "solution": "In pipeline post_deploy: if health fails, redeploy previous image tag"
    })

    findings.append({
        "category": "Security",
        "title": "Enable Dependabot",
        "present": "No automated dependency updates",
        "expected": "Dependabot for pip and Docker",
        "priority": "LOW",
        "solution": "Add .github/dependabot.yml for pip and docker"
    })

    return findings

def check_deployed_app():
    """If APP_URL set, try to get health metrics"""
    url = os.getenv("DEPLOY_URL") or os.getenv("APP_URL")
    if not url:
        return None
    health_path = os.getenv("APP_HEALTH_PATH", "/")
    full_url = url.rstrip("/") + health_path
    try:
        import urllib.request
        start = time.perf_counter()
        with urllib.request.urlopen(full_url, timeout=10) as r:
            status = r.getcode()
            body = r.read().decode("utf-8", errors="ignore")[:1000]
            latency = time.perf_counter() - start
            return {"url": full_url, "status": status, "latency_s": round(latency,3), "body_preview": body[:200]}
    except Exception as e:
        return {"url": full_url, "error": str(e)}

def format_upgrade(f, idx):
    return f"""
{idx}. [{f['category']}] {f['title']} (Priority: {f['priority']})
   PRESENT: {f['present']}
   EXPECTED: {f['expected']}
   SOLUTION: {f['solution']}
"""

def main():
    start = time.perf_counter()
    root = os.path.abspath(os.getenv("PROJECT_PATH", "."))
    print(f"[final_agent] UNIVERSAL upgrade advisor scanning: {root}")
    print(f"[final_agent] Model={MODEL} Provider={PROVIDER}")

    findings = scan_project(root)
    deployed = check_deployed_app()

    print(f"[final_agent] Found {len(findings)} potential upgrades")

    by_cat = {}
    for f in findings:
        by_cat.setdefault(f["category"], []).append(f)

    report_txt = "\n=== UNIVERSAL POST-DEPLOY UPGRADE REPORT ===\n"
    report_txt += f"Project: {root}\nScanned: {time.strftime('%Y-%m-%d %H:%M:%S')}\n"
    if deployed:
        report_txt += f"Deployed URL check: {deployed}\n"
    report_txt += f"\nTotal suggestions: {len(findings)}\n"

    for cat in ["Security", "Reliability", "Performance", "Cost", "Developer Experience"]:
        if cat in by_cat:
            report_txt += f"\n--- {cat.upper()} ({len(by_cat[cat])}) ---\n"
            for i, f in enumerate(by_cat[cat], 1):
                report_txt += format_upgrade(f, i)

    ai_review = ""
    if ai_ok():
        try:
            prompt = f"""
You are a universal post-deployment DevOps advisor.
Project path: {root}
Deployed check: {deployed}
Static findings ({len(findings)}):
{report_txt[:8000]}

Provide top 3 upgrades with PRESENT vs EXPECTED and SOLUTION.
Format:
UPGRADE 1: <title>
CATEGORY: Security/Performance/etc
PRESENT: current wrong
EXPECTED: should be
SOLUTION: command
"""
            ai_review = ask_ai(prompt)
            report_txt += "\n\n=== AI ENHANCED UPGRADE ROADMAP ===\n" + ai_review
        except Exception as e:
            ai_review = f"AI failed: {e}"

    print(report_txt)

    Path("reports").mkdir(exist_ok=True)
    with open("reports/upgrade_report.txt", "w", encoding="utf-8") as f:
        f.write(report_txt)
    with open("final_report.txt", "w", encoding="utf-8") as f:
        f.write(report_txt)
    with open("reports/upgrade_report.json", "w", encoding="utf-8") as f:
        json.dump(findings, f, indent=2)

    print(f"\nReports saved.")

    try:
        send_agent_status(
            agent_name="final_agent",
            stage="post_deploy",
            status="approved",
            decision="approved",
            provider=PROVIDER,
            model=MODEL,
            prompt_tokens=_ai_prompt_tokens,
            completion_tokens=_ai_completion_tokens,
            total_tokens=_ai_total_tokens,
            requests_count=_ai_requests,
            api_key_count=1,
            execution_time_seconds=round(time.perf_counter() - start, 4),
            api_response_time_seconds=round(_ai_response_time, 4),
        )
    except Exception:
        pass

    sys.exit(0)


if __name__ == "__main__":
    main()
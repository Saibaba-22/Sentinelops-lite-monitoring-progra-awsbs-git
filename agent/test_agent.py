"""
test_agent.py - UNIVERSAL PRE-DEPLOY CHECKER
Phase 1: Checks complete application for errors before deployment.
Works for ANY Python project (Flask, Django, FastAPI, generic).

What it checks (no args needed):
- Python syntax errors (py_compile all .py)
- Requirements.txt validity
- Dockerfile & Dockerrun.aws.json placeholders
- Missing .dockerignore
- Hardcoded secrets (API_KEY, PASSWORD, etc)
- Env var usage vs .env.example
- Common runtime errors (missing files referenced)
- Runs pytest if available

Output format for each issue:
  FILE: path/to/file
  LINE: line number
  PRESENT_ERROR: what is wrong now
  EXPECTED_VALUE: what should be
  WHY: why it fails
  SOLUTION: how to fix

Usage:
  python agent/test_agent.py
  python agent/test_agent.py --path ./my-app --strict
  PROJECT_PATH=. python agent/test_agent.py

No custom command required - auto-detects everything.
Uses Gemini AI if GEMINI_API_KEY set, else pure deterministic checks.
"""

import os
import re
import sys
import ast
import glob
import time
import subprocess
import py_compile
from pathlib import Path

# Optional monitor
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

def ai_available():
    try:
        c = build_client()
        c.models.generate_content(model=MODEL, contents="OK")
        return True
    except Exception:
        return False

def ask_ai(prompt):
    try:
        client = build_client()
        resp = client.models.generate_content(model=MODEL, contents=prompt)
        return (resp.text or "").strip()
    except Exception as e:
        return f"AI unavailable: {e}"

# --------------------- CHECKERS ---------------------

def find_py_files(root):
    excluded = {".venv","venv",".git","__pycache__",".pytest_cache","node_modules","dist","build",".arena"}
    files = []
    for r, dirs, fs in os.walk(root):
        dirs[:] = [d for d in dirs if d not in excluded and not d.startswith(".")]
        for f in fs:
            if f.endswith(".py"):
                files.append(os.path.join(r, f))
    return files

def check_syntax_errors(root):
    issues = []
    for fp in find_py_files(root):
        try:
            py_compile.compile(fp, doraise=True)
            # also try ast parse for better line info
            with open(fp, "r", encoding="utf-8", errors="ignore") as h:
                src = h.read()
            ast.parse(src, filename=fp)
        except py_compile.PyCompileError as e:
            msg = str(e)
            m = re.search(r"line (\d+)", msg)
            line = m.group(1) if m else "N/A"
            issues.append({
                "FILE": fp,
                "LINE": line,
                "PRESENT_ERROR": msg.splitlines()[-1][:500],
                "EXPECTED_VALUE": "Valid Python syntax, no SyntaxError",
                "WHY": "Python syntax is invalid, deploy will crash on import",
                "SOLUTION": f"Fix syntax in {fp}:{line} - check missing colon, parenthesis, indentation"
            })
        except SyntaxError as e:
            issues.append({
                "FILE": e.filename or fp,
                "LINE": str(e.lineno or "N/A"),
                "PRESENT_ERROR": f"{e.msg}: {e.text.strip() if e.text else ''}",
                "EXPECTED_VALUE": "Valid syntax",
                "WHY": e.msg,
                "SOLUTION": f"Fix line {e.lineno} in {fp}. Expected valid Python."
            })
        except Exception as e:
            # ignore unreadable
            pass
    return issues

def check_requirements(root):
    issues = []
    req_files = glob.glob(os.path.join(root, "requirements*.txt")) + glob.glob(os.path.join(root, "**/requirements*.txt"), recursive=True)
    for rf in req_files[:3]:
        try:
            lines = Path(rf).read_text(encoding="utf-8", errors="ignore").splitlines()
            for idx, line in enumerate(lines, 1):
                line = line.strip()
                if not line or line.startswith("#") or line.startswith("-"):
                    continue
                # invalid if contains spaces without extras
                if " " in line and not any(x in line for x in ["#", ";", "==", ">=", "<=", "~="]):
                    # might be invalid
                    if not re.match(r"^[a-zA-Z0-9_.-]+", line):
                        issues.append({
                            "FILE": rf,
                            "LINE": str(idx),
                            "PRESENT_ERROR": f"Invalid requirement line: {line}",
                            "EXPECTED_VALUE": "Valid pip package e.g. flask==2.3.0",
                            "WHY": "pip install will fail",
                            "SOLUTION": f"Fix line {idx} in {rf} to valid PEP-508 format"
                        })
        except Exception:
            pass
    return issues

def check_docker(root):
    issues = []
    dockerfiles = glob.glob(os.path.join(root, "**/Dockerfile"), recursive=True) + glob.glob(os.path.join(root, "docker/**/Dockerfile"), recursive=True)
    if not dockerfiles:
        issues.append({
            "FILE": "Dockerfile",
            "LINE": "N/A",
            "PRESENT_ERROR": "Dockerfile not found",
            "EXPECTED_VALUE": "Dockerfile at root or docker/Dockerfile",
            "WHY": "Docker build will fail in pipeline",
            "SOLUTION": "Add Dockerfile with python:3.12-slim base, COPY requirements, CMD"
        })
    else:
        for df in dockerfiles[:2]:
            try:
                txt = Path(df).read_text(encoding="utf-8", errors="ignore")
                if "replace_with_ecr_image_uri" in txt or "REPLACE_WITH" in txt:
                    issues.append({
                        "FILE": df,
                        "LINE": "N/A",
                        "PRESENT_ERROR": "Placeholder image URI still present",
                        "EXPECTED_VALUE": 'Valid image like "myrepo/app:latest"',
                        "WHY": "Container will fail to pull placeholder",
                        "SOLUTION": "Replace placeholder with actual DOCKERHUB_USERNAME/REPOSITORY variable in pipeline"
                    })
            except Exception:
                pass

    # Dockerrun check
    for dr in [os.path.join(root, "Dockerrun.aws.json"), os.path.join(root, "docker-compose.yml")]:
        if os.path.exists(dr):
            try:
                txt = Path(dr).read_text(encoding="utf-8", errors="ignore")
                if "replace_with_ecr_image_uri" in txt:
                    issues.append({
                        "FILE": dr,
                        "LINE": "N/A",
                        "PRESENT_ERROR": "Placeholder replace_with_ecr_image_uri not replaced",
                        "EXPECTED_VALUE": "Real Docker Hub image URI",
                        "WHY": "Elastic Beanstalk deploy will fail",
                        "SOLUTION": f"In {dr} replace placeholder via sed in deploy.sh or pipeline"
                    })
            except Exception:
                pass

    if not os.path.exists(os.path.join(root, ".dockerignore")) and dockerfiles:
        issues.append({
            "FILE": ".dockerignore",
            "LINE": "N/A",
            "PRESENT_ERROR": ".dockerignore missing",
            "EXPECTED_VALUE": ".dockerignore with .venv, __pycache__, .git, logs",
            "WHY": "Image bloat and slow builds, may leak secrets",
            "SOLUTION": "Add .dockerignore file"
        })
    return issues

def check_secrets(root):
    issues = []
    secret_patterns = [
        (r"(?i)api_key\s*=\s*['\"][A-Za-z0-9_\-]{20,}['\"]", "Hardcoded API key"),
        (r"(?i)password\s*=\s*['\"][^'\"]{3,}['\"]", "Hardcoded password"),
        (r"AKIA[0-9A-Z]{16}", "Hardcoded AWS Access Key"),
        (r"(?i)secret\s*=\s*['\"][^'\"]{8,}['\"]", "Hardcoded secret"),
    ]
    for fp in find_py_files(root)[:50]:  # limit
        try:
            txt = Path(fp).read_text(encoding="utf-8", errors="ignore")
            for pat, desc in secret_patterns:
                m = re.search(pat, txt)
                if m:
                    line_no = txt[:m.start()].count("\n") + 1
                    issues.append({
                        "FILE": fp,
                        "LINE": str(line_no),
                        "PRESENT_ERROR": f"{desc} found: {m.group(0)[:60]}...",
                        "EXPECTED_VALUE": "Use os.getenv('API_KEY') or secrets manager",
                        "WHY": "Secrets in code leak to git and Docker image",
                        "SOLUTION": f"Move secret to env var in {fp}:{line_no}, use os.getenv"
                    })
                    break
        except Exception:
            pass
    return issues

def check_env(root):
    issues = []
    # find os.getenv usage
    env_used = set()
    for fp in find_py_files(root)[:100]:
        try:
            txt = Path(fp).read_text(encoding="utf-8", errors="ignore")
            for m in re.finditer(r"os\.getenv\(['\"]([A-Z_]+)['\"]|os\.environ\[['\"]([A-Z_]+)['\"]", txt):
                var = m.group(1) or m.group(2)
                if var:
                    env_used.add(var)
        except Exception:
            pass
    # if .env.example exists, compare
    example_path = os.path.join(root, ".env.example")
    if os.path.exists(example_path):
        try:
            example_vars = set()
            for line in Path(example_path).read_text(encoding="utf-8", errors="ignore").splitlines():
                if "=" in line and not line.strip().startswith("#"):
                    example_vars.add(line.split("=")[0].strip())
            missing = env_used - example_vars
            if missing:
                issues.append({
                    "FILE": ".env.example",
                    "LINE": "N/A",
                    "PRESENT_ERROR": f"Env vars used in code not in .env.example: {', '.join(list(missing)[:5])}",
                    "EXPECTED_VALUE": ".env.example should contain all required env vars",
                    "WHY": "New dev or CI will miss required env vars",
                    "SOLUTION": f"Add {', '.join(missing)} to .env.example"
                })
        except Exception:
            pass
    return issues

def try_pytest(root):
    """Try running pytest -q if available, return output"""
    try:
        # quick check if pytest is available
        subprocess.run("pytest --version", shell=True, capture_output=True, timeout=5)
    except Exception:
        return 0, "pytest not installed, skipping"

    cmd = os.getenv("TEST_CMD", "pytest -q")
    try:
        proc = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=60, cwd=root)
        output = (proc.stdout or "") + "\n" + (proc.stderr or "")
        return proc.returncode, output[-5000:]
    except subprocess.TimeoutExpired:
        return 1, "pytest timed out after 60s"
    except Exception as e:
        return 1, f"pytest failed to run: {e}"

# --------------------- MAIN ---------------------

def format_issue(iss):
    return f"""FILE: {iss['FILE']}
LINE: {iss['LINE']}
PRESENT_ERROR: {iss['PRESENT_ERROR']}
EXPECTED_VALUE: {iss['EXPECTED_VALUE']}
WHY: {iss['WHY']}
SOLUTION: {iss['SOLUTION']}
"""

def main():
    start = time.perf_counter()
    root = os.getenv("PROJECT_PATH", ".")
    root = os.path.abspath(root)
    print(f"[test_agent] UNIVERSAL pre-deploy checker scanning: {root}")

    all_issues = []
    all_issues += check_syntax_errors(root)
    all_issues += check_requirements(root)
    all_issues += check_docker(root)
    all_issues += check_secrets(root)
    all_issues += check_env(root)

    print(f"[test_agent] Found {len(all_issues)} static issues")

    # Try pytest
    test_code, test_output = try_pytest(root)
    print(f"[test_agent] Pytest exit code: {test_code}")
    if test_code != 0 and "not installed" not in test_output.lower() and "no tests ran" not in test_output.lower():
        # parse pytest failures
        for line in test_output.splitlines():
            if "FAILED" in line:
                all_issues.append({
                    "FILE": line.split()[0] if line.split() else "tests/",
                    "LINE": "N/A",
                    "PRESENT_ERROR": f"Test failure: {line[:300]}",
                    "EXPECTED_VALUE": "All tests should PASS",
                    "WHY": "Unit tests failing",
                    "SOLUTION": "Fix failing test, check traceback above"
                })

    # Write reports
    Path("reports").mkdir(exist_ok=True)
    with open("reports/pre_deploy_report.txt", "w", encoding="utf-8") as f:
        if not all_issues:
            f.write("No issues found - project looks clean for deployment\n")
        else:
            for iss in all_issues:
                f.write(format_issue(iss) + "\n---\n")

    if not all_issues:
        print("\n✅ No errors found - ready to deploy!")
        # AI optional summary
        if ai_available():
            summary = ask_ai(f"Project at {root} passed all pre-deploy checks: no syntax errors, Dockerfile OK, no hardcoded secrets. Test output: {test_output[:2000]}. Confirm PASS with one sentence.")
            print(f"[AI] {summary}")
        # send monitor
        try:
            send_agent_status(agent_name="test_agent", stage="pre_deploy", status="approved", decision="pass",
                              provider=PROVIDER, model=MODEL, execution_time_seconds=time.perf_counter()-start)
        except Exception:
            pass
        sys.exit(0)
    else:
        print(f"\n❌ Found {len(all_issues)} issues - blocking deploy:\n")
        for iss in all_issues[:10]:  # show first 10
            print(format_issue(iss))
            print("---")

        # AI review if available
        if ai_available():
            prompt = f"""
You are a universal QA checker. Project has {len(all_issues)} pre-deploy issues:

{chr(10).join([format_issue(i) for i in all_issues[:5]])}

Test output tail:
{test_output[:3000]}

Summarize top 3 critical issues with FILE/LINE and fix.
Reply format:
FILE: ...
LINE: ...
PRESENT_ERROR: ...
EXPECTED_VALUE: ...
SOLUTION: ...
"""
            ai_summary = ask_ai(prompt)
            print("\n----- AI Review -----")
            print(ai_summary)
            print("---------------------")
            with open("reports/pre_deploy_ai_review.txt", "w", encoding="utf-8") as f:
                f.write(ai_summary)

        try:
            send_agent_status(agent_name="test_agent", stage="pre_deploy", status="rejected", decision="fail",
                              provider=PROVIDER, model=MODEL, execution_time_seconds=time.perf_counter()-start,
                              error=f"{len(all_issues)} pre-deploy issues")
        except Exception:
            pass
        sys.exit(1)

if __name__ == "__main__":
    main()

"""
errors.py - UNIVERSAL DURING-DEPLOY ERROR DIAGNOSER
Phase 2: Runs during deployment, analyzes failure logs and provides:
  FILE: file name
  LINE: line number
  PRESENT_ERROR: current wrong value / error
  EXPECTED_VALUE: what should be
  WHY: root cause
  SOLUTION: how to fix

Works for ANY project: Python, Docker, AWS EB, Azure App Service, K8s, etc.

No custom command needed - auto-collects logs from:
- Environment (TARGET_CLOUD, AWS_*, AZURE_*)
- *.log, reports/, /tmp/, eb logs, docker ps, Dockerrun.aws.json
- Python tracebacks
- GitHub Actions logs

Usage:
  python agent/errors.py
  TARGET_CLOUD=aws python agent/errors.py

Output: errors_report.txt + reports/deploy_error_diagnosis.txt
"""

import os
import re
import sys
import glob
import time
import subprocess
from pathlib import Path

try:
    from monitor_client import send_agent_status
except ImportError:
    def send_agent_status(*a, **k):
        print(f"[monitor] {k.get('status')}")

MODEL = os.getenv("AI_MODEL", "gemini-2.5-flash")
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

def ai_status():
    try:
        client = build_client()
        client.models.generate_content(model=MODEL, contents="OK")
        return True, ""
    except Exception as e:
        return False, str(e)

def ask_ai(prompt):
    client = build_client()
    resp = client.models.generate_content(model=MODEL, contents=prompt)
    return (resp.text or "").strip()

def collect_context():
    parts = []
    parts.append("=== ENV ===")
    for k in ["TARGET_CLOUD","AWS_APP_NAME","AWS_ENV_NAME","AWS_REGION","AZURE_WEBAPP_NAME","AZURE_RESOURCE_GROUP","GITHUB_SHA","DOCKERHUB_USERNAME","DOCKERHUB_REPOSITORY","APP_NAME","ENV_NAME"]:
        parts.append(f"{k}={os.getenv(k,'N/A')}")

    # Try EB / Azure / Docker status - best effort
    parts.append("\n=== DEPLOY STATUS COMMANDS ===")
    cmds = [
        "eb status 2>&1 | head -n 150",
        "eb health 2>&1 | head -n 150",
        "az webapp log tail --name $AZURE_WEBAPP_NAME --resource-group $AZURE_RESOURCE_GROUP 2>&1 | head -n 150" if os.getenv("AZURE_WEBAPP_NAME") else "echo no azure",
        "docker ps -a 2>&1 | head -n 100",
        "docker logs $(docker ps -aq | head -n1) 2>&1 | tail -n 200" if os.getenv("DOCKERHUB_REPOSITORY") else "echo no docker container",
        "cat Dockerrun.aws.json 2>&1 | head -n 100",
        "cat docker-compose.yml 2>&1 | head -n 100",
        "cat .elasticbeanstalk/config.yml 2>&1 | head -n 100",
    ]
    for cmd in cmds:
        try:
            out = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=12)
            txt = (out.stdout + out.stderr)[:4000]
            if txt.strip():
                parts.append(f"\n$ {cmd}\n{txt}")
        except Exception:
            pass

    parts.append("\n=== LOG FILES ===")
    for pat in ["*.log", "reports/*.log", "reports/*.txt", "/tmp/*.log", "*.txt"]:
        for f in glob.glob(pat, recursive=True)[:8]:
            try:
                p = Path(f)
                size = p.stat().st_size
                if size > 2000000:
                    content = p.read_text(encoding="utf-8", errors="ignore")[-6000:]
                else:
                    content = p.read_text(encoding="utf-8", errors="ignore")[:6000]
                if content.strip():
                    parts.append(f"\n--- {f} ---\n{content[-5000:]}")
            except Exception:
                pass

    # GitHub Actions failure - check if error file exists from previous steps
    parts.append("\n=== RECENT TRACEBACKS ===")
    combined = "\n".join(parts)
    # Also capture current directory ls
    try:
        ls = subprocess.run("ls -la 2>&1 | head -n 100", shell=True, capture_output=True, text=True, timeout=5)
        parts.append(f"\nls -la:\n{ls.stdout[:2000]}")
    except Exception:
        pass

    return "\n".join(parts)[-20000:]

def parse_file_line(error_text):
    """Universal regex to extract FILE/LINE from tracebacks"""
    patterns = [
        r'File "([^"]+)", line (\d+)',  # Python
        r'File ([^\s:]+\.py):(\d+)',       # alternative
        r'([a-zA-Z0-9_\-/\.]+\.py):(\d+):', # pylint/flake
        r'at ([^\s]+\.py):(\d+)',           # some logs
        r'ERROR.*file: ([^\s]+\.py)',       # custom
        r'([A-Za-z0-9_\-/]+\.json):? line (\d+)?', # json
        r'Dockerfile:(\d+)',                 # dockerfile
    ]
    results = []
    for pat in patterns:
        for m in re.finditer(pat, error_text):
            file = m.group(1)
            line = m.group(2) if len(m.groups()) >=2 and m.group(2) else "N/A"
            # filter out stdlib
            if "site-packages" in file or "importlib" in file:
                continue
            if len(file) > 200:
                continue
            results.append((file, line))
    # deduplicate keep order
    seen = set()
    uniq = []
    for f,l in results:
        if (f,l) not in seen:
            seen.add((f,l))
            uniq.append((f,l))
    return uniq[:5]

def heuristic_present_expected(error_text):
    """Heuristic to guess present vs expected"""
    present = "Unknown error"
    expected = "Valid configuration / code"
    # common cases
    if "replace_with_ecr_image_uri" in error_text:
        present = "Placeholder image URI 'replace_with_ecr_image_uri' still present"
        expected = "Real Docker image URI like 'docker.io/username/repo:tag'"
    elif "ModuleNotFoundError" in error_text or "No module named" in error_text:
        m = re.search(r"No module named '([^']+)'", error_text)
        mod = m.group(1) if m else "unknown"
        present = f"Missing module '{mod}' not installed"
        expected = f"Add '{mod}' to requirements.txt and pip install"
    elif "SyntaxError" in error_text:
        present = "Python syntax error"
        expected = "Valid Python syntax"
    elif "Docker" in error_text and ("pull" in error_text.lower() or "image" in error_text.lower()):
        present = "Docker image pull failed - invalid image name or auth failed"
        expected = "Valid Docker Hub image with correct auth"
    elif "401" in error_text or "Unauthorized" in error_text:
        present = "Authentication failed (Docker Hub / AWS / Azure)"
        expected = "Valid credentials / token / OIDC role"
    elif "404" in error_text and "elasticbeanstalk" in error_text.lower():
        present = "EB environment not found"
        expected = "Existing EB application + environment name"
    elif "port" in error_text.lower() and "already" in error_text.lower():
        present = "Port already in use / conflict"
        expected = "Free port or proper EXPOSE in Dockerfile"
    elif "health" in error_text.lower():
        present = "Health check failed"
        expected = "App should return 200 on APP_HEALTH_PATH"
    elif "KeyError" in error_text or "Environment variable" in error_text:
        present = "Missing environment variable"
        expected = "Set required env var in EB/Azure config"
    else:
        # take first error line
        lines = [l.strip() for l in error_text.splitlines() if "error" in l.lower() or "exception" in l.lower() or "fail" in l.lower()]
        if lines:
            present = lines[-1][:500]

    return present, expected

def diagnose_with_ai(context, file_line_list):
    prompt = f"""
You are a universal deployment failure diagnostician for ANY project.

Analyze the deployment failure context and produce EXACTLY this format for the TOP error (one issue):

FILE: <path/to/file.py or Dockerrun.aws.json or Dockerfile or N/A>
LINE: <line number or N/A>
PRESENT_ERROR: <what is currently wrong - the actual wrong value/error message, one sentence>
EXPECTED_VALUE: <what should be instead - correct value, one sentence>
WHY: <why it failed - root cause, one sentence>
SOLUTION: <how to fix - actionable command or code snippet, one sentence>

Rules:
- Focus on Python, Docker, AWS EB, Azure App Service failures
- If file/line not clear, use N/A but still provide PRESENT_ERROR/EXPECTED_VALUE
- PRESENT_ERROR should be the wrong value present now
- EXPECTED_VALUE should be correct value expected
- Keep each field max 2 lines, very concise, actionable

Detected file/line hints from regex:
{file_line_list}

--- FAILURE CONTEXT (last 20k chars) ---
{context}
"""
    return ask_ai(prompt)

def deterministic_diagnosis(context):
    text = context.lower()

    if "cannotpullimagemanifesterror" in text or "failed to pull image" in text:
        return """FILE: Dockerrun.aws.json
LINE: N/A
PRESENT_ERROR: Elastic Beanstalk/ECS cannot pull the app Docker image from Docker Hub: CannotPullImageManifestError unauthorized/authentication required.
EXPECTED_VALUE: Dockerrun.aws.json should reference an existing public Docker Hub image such as docker.io/saibaba22/sentinelops-lite-monitoring-progra-awsbs-git:latest.
WHY: The image name/tag used by EB is wrong, missing, private, or the deployed Dockerrun.aws.json does not match the image pushed by the pipeline.
SOLUTION: Print Dockerrun.aws.json before eb deploy, ensure the app image is docker.io/saibaba22/sentinelops-lite-monitoring-progra-awsbs-git:latest, then deploy with git add Dockerrun.aws.json && eb deploy "$AWS_ENV_NAME" --staged.
"""

    if "replace_with_dockerhub_image_uri" in text or "replace_with_ecr_image_uri" in text:
        return """FILE: Dockerrun.aws.json
LINE: N/A
PRESENT_ERROR: Image placeholder is still present in deployment config.
EXPECTED_VALUE: Placeholder should be replaced with a real Docker image URI.
WHY: The pipeline deployed an unreplaced Dockerrun.aws.json/docker-compose.yml.
SOLUTION: Replace the placeholder before EB deploy and use eb deploy --staged.
"""

    if "no such image" in text or "manifest unknown" in text:
        return """FILE: Dockerrun.aws.json
LINE: N/A
PRESENT_ERROR: Docker image tag does not exist on Docker Hub.
EXPECTED_VALUE: The tag referenced by EB must exist on Docker Hub.
WHY: Pipeline pushed one tag but EB tried to pull another tag.
SOLUTION: Push the same tag used in Dockerrun.aws.json, or use latest consistently.
"""

    if "environment variable" in text and "not set" in text:
        return """FILE: GitHub Actions workflow
LINE: N/A
PRESENT_ERROR: Required environment variable is missing.
EXPECTED_VALUE: Required variable should be passed to the failing step.
WHY: The job or step environment does not include the variable.
SOLUTION: Add the variable under the step env block and print it before running the command.
"""

    return None

def main():
    start = time.perf_counter()
    print(f"[errors.py] UNIVERSAL deploy error diagnoser - cloud={os.getenv('TARGET_CLOUD','unknown')} model={MODEL}")

    ai_ok, ai_reason = ai_status()
    if ai_ok:
        print(f"[AI] model {MODEL} available")
    else:
        print(f"[AI] unavailable: {ai_reason}")

context = collect_context()
print(f"[errors.py] collected {len(context)} chars context")

file_lines = parse_file_line(context)
print(f"[errors.py] parsed file/line hints: {file_lines}")

present, expected = heuristic_present_expected(context)

deterministic = deterministic_diagnosis(context)

if deterministic:
    print("----- errors.py diagnosis deterministic -----")
    print(deterministic)
    print("--------------------------------------------")

    Path("reports").mkdir(exist_ok=True)

    with open("errors_report.txt", "w", encoding="utf-8") as f:
        f.write(deterministic + "\n\n--- RAW CONTEXT ---\n" + context[-8000:])

    with open("reports/deploy_error_diagnosis.txt", "w", encoding="utf-8") as f:
        f.write(deterministic)

    try:
        send_agent_status(
            agent_name="errors_agent",
            stage="deploy",
            status="failed",
            decision="failed",
            provider=PROVIDER,
            model=MODEL,
            execution_time_seconds=time.perf_counter() - start,
            error="deployment failed - deterministic diagnosis",
        )
    except Exception:
        pass

    sys.exit(1)

    print("\n--- Context Preview ---")
    print(context[:2000])
    print("--- End Preview ---\n")

    Path("reports").mkdir(exist_ok=True)

    if not ai_ok:
        # Deterministic fallback - still provide FILE/LINE/PRESENT/EXPECTED
        fallback_file = file_lines[0][0] if file_lines else "N/A"
        fallback_line = file_lines[0][1] if file_lines else "N/A"

        report = f"""FILE: {fallback_file}
LINE: {fallback_line}
PRESENT_ERROR: {present}
EXPECTED_VALUE: {expected}
WHY: Deployment failed - see logs above
SOLUTION: Check {fallback_file}:{fallback_line} and fix {present}

--- RAW CONTEXT ---
{context[-8000:]}

AI was unavailable: {ai_reason}
"""
        print("----- errors.py diagnosis (fallback, no AI) -----")
        print(report)
        print("-------------------------------------------------")
        with open("errors_report.txt", "w", encoding="utf-8") as f:
            f.write(report)
        with open("reports/deploy_error_diagnosis.txt", "w", encoding="utf-8") as f:
            f.write(report)

        try:
            send_agent_status(agent_name="errors_agent", stage="deploy", status="failed", decision="failed",
                              provider=PROVIDER, model=MODEL, execution_time_seconds=time.perf_counter()-start,
                              error=f"{present} in {fallback_file}:{fallback_line}")
        except Exception:
            pass
        sys.exit(1)

    try:
        ai_report = diagnose_with_ai(context, file_lines)
        print("----- errors.py diagnosis (AI) -----")
        print(ai_report)
        print("------------------------------------")

        full_report = ai_report + "\n\n--- RAW CONTEXT ---\n" + context[-8000:]

        with open("errors_report.txt", "w", encoding="utf-8") as f:
            f.write(full_report)
        with open("reports/deploy_error_diagnosis.txt", "w", encoding="utf-8") as f:
            f.write(ai_report)

        try:
            send_agent_status(agent_name="errors_agent", stage="deploy", status="failed", decision="failed",
                              provider=PROVIDER, model=MODEL, execution_time_seconds=time.perf_counter()-start,
                              error="deployment failed - diagnosed")
        except Exception:
            pass
        sys.exit(1)

    except Exception as e:
        import traceback
        traceback.print_exc()
        fallback = f"""FILE: {file_lines[0][0] if file_lines else "N/A"}
LINE: {file_lines[0][1] if file_lines else "N/A"}
PRESENT_ERROR: {present}
EXPECTED_VALUE: {expected}
WHY: {ai_reason if not ai_ok else "AI call failed"}
SOLUTION: Check logs and fix {present}
ERROR: {e}
"""
        with open("errors_report.txt", "w", encoding="utf-8") as f:
            f.write(fallback + "\n" + context[-5000:])
        with open("reports/deploy_error_diagnosis.txt", "w", encoding="utf-8") as f:
            f.write(fallback)
        sys.exit(1)

if deterministic:
    print("----- errors.py diagnosis deterministic -----")
    print(deterministic)
    print("--------------------------------------------")

    Path("reports").mkdir(exist_ok=True)

    with open("errors_report.txt", "w", encoding="utf-8") as f:
        f.write(deterministic + "\n\n--- RAW CONTEXT ---\n" + context[-8000:])

    with open("reports/deploy_error_diagnosis.txt", "w", encoding="utf-8") as f:
        f.write(deterministic)

    sys.exit(1)
if __name__ == "__main__":
    main()

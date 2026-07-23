"""
errors.py - UNIVERSAL DURING-DEPLOY ERROR DIAGNOSER
Phase 2: Runs during deployment, analyzes failure logs.
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

MODEL    = os.getenv("AI_MODEL", "gemini-2.5-flash")
PROVIDER = os.getenv("AI_PROVIDER", "gemini")

# ── Token tracking globals ────────────────────────────────────────
_ai_prompt_tokens     = 0
_ai_completion_tokens = 0
_ai_total_tokens      = 0
_ai_requests          = 0
_ai_response_time     = 0.0


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
    global _ai_prompt_tokens, _ai_completion_tokens, _ai_total_tokens
    global _ai_requests, _ai_response_time
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

def collect_context():
    parts = []
    parts.append("=== ENV ===")
    for k in [
        "TARGET_CLOUD", "AWS_APP_NAME", "AWS_ENV_NAME", "AWS_REGION",
        "AZURE_WEBAPP_NAME", "AZURE_RESOURCE_GROUP", "GITHUB_SHA",
        "DOCKERHUB_USERNAME", "DOCKERHUB_REPOSITORY", "APP_NAME", "ENV_NAME",
    ]:
        parts.append(f"{k}={os.getenv(k, 'N/A')}")

    parts.append("\n=== DEPLOY STATUS COMMANDS ===")
    cmds = [
        "eb status 2>&1 | head -n 150",
        "eb health 2>&1 | head -n 150",
        "docker ps -a 2>&1 | head -n 100",
        "docker logs $(docker ps -aq | head -n1) 2>&1 | tail -n 200",
        "cat Dockerrun.aws.json 2>&1 | head -n 100",
        "cat docker-compose.yml 2>&1 | head -n 100",
        "cat .elasticbeanstalk/config.yml 2>&1 | head -n 100",
    ]
    for cmd in cmds:
        try:
            out = subprocess.run(
                cmd, shell=True, capture_output=True, text=True, timeout=12
            )
            txt = (out.stdout + out.stderr)[:4000]
            if txt.strip():
                parts.append(f"\n$ {cmd}\n{txt}")
        except Exception:
            pass

    parts.append("\n=== LOG FILES ===")
    for pat in ["*.log", "reports/*.log", "reports/*.txt", "/tmp/*.log", "*.txt"]:
        for f in glob.glob(pat, recursive=True)[:8]:
            try:
                p       = Path(f)
                content = p.read_text(encoding="utf-8", errors="ignore")
                if len(content) > 2_000_000:
                    content = content[-6000:]
                else:
                    content = content[:6000]
                if content.strip():
                    parts.append(f"\n--- {f} ---\n{content[-5000:]}")
            except Exception:
                pass

    try:
        ls = subprocess.run(
            "ls -la 2>&1 | head -n 100",
            shell=True, capture_output=True, text=True, timeout=5,
        )
        parts.append(f"\nls -la:\n{ls.stdout[:2000]}")
    except Exception:
        pass

    return "\n".join(parts)[-20000:]


def parse_file_line(error_text):
    patterns = [
        r'File "([^"]+)", line (\d+)',
        r'File ([^\s:]+\.py):(\d+)',
        r'([a-zA-Z0-9_\-/\.]+\.py):(\d+):',
        r'at ([^\s]+\.py):(\d+)',
        r'([A-Za-z0-9_\-/]+\.json):? line (\d+)?',
        r'Dockerfile:(\d+)',
    ]
    results = []
    for pat in patterns:
        for m in re.finditer(pat, error_text):
            file = m.group(1)
            line = m.group(2) if len(m.groups()) >= 2 and m.group(2) else "N/A"
            if "site-packages" in file or "importlib" in file:
                continue
            if len(file) > 200:
                continue
            results.append((file, line))
    seen, uniq = set(), []
    for item in results:
        if item not in seen:
            seen.add(item)
            uniq.append(item)
    return uniq[:5]


def heuristic_present_expected(error_text):
    present  = "Unknown error"
    expected = "Valid configuration / code"
    if "replace_with_ecr_image_uri" in error_text:
        present  = "Placeholder image URI still present"
        expected = "Real Docker image URI"
    elif "ModuleNotFoundError" in error_text or "No module named" in error_text:
        m        = re.search(r"No module named '([^']+)'", error_text)
        mod      = m.group(1) if m else "unknown"
        present  = f"Missing module '{mod}'"
        expected = f"Add '{mod}' to requirements.txt"
    elif "SyntaxError" in error_text:
        present  = "Python syntax error"
        expected = "Valid Python syntax"
    elif "401" in error_text or "Unauthorized" in error_text:
        present  = "Authentication failed"
        expected = "Valid credentials / token"
    elif "health" in error_text.lower():
        present  = "Health check failed"
        expected = "App returns 200 on health path"
    else:
        lines = [
            l.strip() for l in error_text.splitlines()
            if any(w in l.lower() for w in ["error", "exception", "fail"])
        ]
        if lines:
            present = lines[-1][:500]
    return present, expected


def deterministic_diagnosis(context):
    text = context.lower()
    if "cannotpullimagemanifesterror" in text or "failed to pull image" in text:
        return """FILE: Dockerrun.aws.json
LINE: N/A
PRESENT_ERROR: EB cannot pull Docker image - CannotPullImageManifestError
EXPECTED_VALUE: Valid public Docker Hub image URI
WHY: Image name/tag in Dockerrun.aws.json does not exist or is private
SOLUTION: Verify image exists on Docker Hub and Dockerrun.aws.json has correct URI
"""
    if "replace_with_dockerhub_image_uri" in text or "replace_with_ecr_image_uri" in text:
        return """FILE: Dockerrun.aws.json
LINE: N/A
PRESENT_ERROR: Image placeholder not replaced
EXPECTED_VALUE: Real Docker image URI
WHY: Pipeline deployed unreplaced Dockerrun.aws.json
SOLUTION: Replace placeholder with real image URI before eb deploy
"""
    if "no such image" in text or "manifest unknown" in text:
        return """FILE: Dockerrun.aws.json
LINE: N/A
PRESENT_ERROR: Docker image tag does not exist on Docker Hub
EXPECTED_VALUE: Tag referenced by EB must exist on Docker Hub
WHY: Pipeline pushed different tag than what EB pulls
SOLUTION: Use same tag in both docker push and Dockerrun.aws.json
"""
    if "environment variable" in text and "not set" in text:
        return """FILE: GitHub Actions workflow
LINE: N/A
PRESENT_ERROR: Required environment variable missing
EXPECTED_VALUE: Variable passed to failing step
WHY: Job/step environment missing required variable
SOLUTION: Add variable under step env block
"""
    return None


def diagnose_with_ai(context, file_line_list):
    prompt = f"""
You are a universal deployment failure diagnostician.

Produce EXACTLY this format for the TOP error:

FILE: <path or N/A>
LINE: <number or N/A>
PRESENT_ERROR: <what is wrong now, one sentence>
EXPECTED_VALUE: <what should be, one sentence>
WHY: <root cause, one sentence>
SOLUTION: <how to fix, one sentence>

Detected file/line hints: {file_line_list}

--- FAILURE CONTEXT ---
{context}
"""
    return ask_ai(prompt)


def _send(start, status, decision, error=""):
    """Helper to avoid repeating send_agent_status arguments."""
    try:
        send_agent_status(
            agent_name="errors_agent",
            stage="deploy",
            status=status,
            decision=decision,
            provider=PROVIDER,
            model=MODEL,
            prompt_tokens=_ai_prompt_tokens,
            completion_tokens=_ai_completion_tokens,
            total_tokens=_ai_total_tokens,
            requests_count=_ai_requests,
            api_key_count=1,
            execution_time_seconds=round(time.perf_counter() - start, 4),
            api_response_time_seconds=round(_ai_response_time, 4),
            error=error,
        )
    except Exception:
        pass


def main():
    start = time.perf_counter()
    print(
        f"[errors_agent] cloud={os.getenv('TARGET_CLOUD','unknown')} "
        f"model={MODEL}"
    )

    ai_ok, ai_reason = ai_status()
    print(f"[AI] {'available' if ai_ok else 'unavailable: ' + ai_reason}")

    # ── Collect all context ───────────────────────────────────────
    context    = collect_context()
    file_lines = parse_file_line(context)
    present, expected = heuristic_present_expected(context)

    print(f"[errors_agent] context={len(context)} chars  hints={file_lines}")

    Path("reports").mkdir(exist_ok=True)

    # ── 1. Deterministic fast-path ────────────────────────────────
    deterministic = deterministic_diagnosis(context)
    if deterministic:
        print("----- deterministic diagnosis -----")
        print(deterministic)
        print("-----------------------------------")
        with open("errors_report.txt", "w", encoding="utf-8") as f:
            f.write(deterministic + "\n\n--- RAW CONTEXT ---\n" + context[-8000:])
        with open("reports/deploy_error_diagnosis.txt", "w", encoding="utf-8") as f:
            f.write(deterministic)
        _send(start, "failed", "failed", "deterministic diagnosis")
        sys.exit(1)

    # ── 2. No AI - fallback deterministic report ──────────────────
    if not ai_ok:
        fallback_file = file_lines[0][0] if file_lines else "N/A"
        fallback_line = file_lines[0][1] if file_lines else "N/A"
        report = (
            f"FILE: {fallback_file}\n"
            f"LINE: {fallback_line}\n"
            f"PRESENT_ERROR: {present}\n"
            f"EXPECTED_VALUE: {expected}\n"
            f"WHY: Deployment failed - see logs\n"
            f"SOLUTION: Fix {present} in {fallback_file}:{fallback_line}\n"
            f"\nAI unavailable: {ai_reason}\n"
            f"\n--- RAW CONTEXT ---\n{context[-8000:]}"
        )
        print("----- fallback diagnosis (no AI) -----")
        print(report)
        print("--------------------------------------")
        with open("errors_report.txt", "w", encoding="utf-8") as f:
            f.write(report)
        with open("reports/deploy_error_diagnosis.txt", "w", encoding="utf-8") as f:
            f.write(report)
        _send(start, "failed", "failed", f"{present} in {fallback_file}:{fallback_line}")
        sys.exit(1)

    # ── 3. AI diagnosis ───────────────────────────────────────────
    try:
        ai_report = diagnose_with_ai(context, file_lines)
        print("----- AI diagnosis -----")
        print(ai_report)
        print("------------------------")
        with open("errors_report.txt", "w", encoding="utf-8") as f:
            f.write(ai_report + "\n\n--- RAW CONTEXT ---\n" + context[-8000:])
        with open("reports/deploy_error_diagnosis.txt", "w", encoding="utf-8") as f:
            f.write(ai_report)
        _send(start, "failed", "failed", "deployment failed - AI diagnosed")
        sys.exit(1)

    except Exception as e:
        import traceback
        traceback.print_exc()
        fallback_file = file_lines[0][0] if file_lines else "N/A"
        fallback_line = file_lines[0][1] if file_lines else "N/A"
        fallback = (
            f"FILE: {fallback_file}\n"
            f"LINE: {fallback_line}\n"
            f"PRESENT_ERROR: {present}\n"
            f"EXPECTED_VALUE: {expected}\n"
            f"WHY: AI call failed: {e}\n"
            f"SOLUTION: Check logs and fix {present}\n"
        )
        with open("errors_report.txt", "w", encoding="utf-8") as f:
            f.write(fallback + "\n" + context[-5000:])
        with open("reports/deploy_error_diagnosis.txt", "w", encoding="utf-8") as f:
            f.write(fallback)
        _send(start, "failed", "failed", str(e))
        sys.exit(1)


if __name__ == "__main__":
    main()
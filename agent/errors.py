"""
errors.py  -  PHASE 2: DURING DEPLOYMENT / ACCESSING THE APP
------------------------------------------------------------
Runs the command that deploys or accesses your application.
If it succeeds -> prints SUCCESS.
If it fails   -> uses an AI model as a "supporter" to report:
    FILE      : which file failed
    LINE      : the line number
    ISSUE     : what the error is (one sentence)
    WHY       : why it failed (one sentence)
    SOLUTION  : how to solve it

The AI model is defined IN THIS FILE (MODEL below) so you can change it
on the spot if it becomes unavailable. The API key is read from the
GEMINI_API_KEY environment variable.

Usage:
    python errors.py --deploy "python deploy.py"
    python errors.py --deploy "kubectl apply -f k8s/"
    DEPLOY_CMD="docker compose up -d" python errors.py
"""

# ===== AI CONFIG =========================================================
# Edit MODEL here if the model is unavailable (e.g. quota / region).
# Other valid examples: "gemini-2.5-pro", "gemini-1.5-flash".
MODEL = "gemini-3.1-flash-lite"
# The API key is taken from the GEMINI_API_KEY environment variable.
# ========================================================================

import os
import sys
import argparse
import subprocess
import time
from monitor_client import send_agent_status

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
    """Send a prompt to Gemini and return response plus token counts."""
    client = build_client()
    response = client.models.generate_content(
        model=MODEL,
        contents=prompt,
    )
    text = (response.text or "").strip()
    prompt_tokens = 0
    completion_tokens = 0
    try:
        usage = response.usage_metadata
        prompt_tokens = int(usage.prompt_token_count or 0)
        completion_tokens = int(usage.candidates_token_count or 0)
    except Exception:
        pass
    return text, prompt_tokens, completion_tokens


def run_deploy(cmd):
    proc = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    out = (proc.stdout or "") + "\n" + (proc.stderr or "")
    return proc.returncode, out


def diagnose(error_text):
    prompt = f"""
A command failed while deploying / accessing a software application.
Analyse the output/traceback below and report EXACTLY these fields:

FILE: <path/to/file.py or N/A>
LINE: <line number or N/A>
ISSUE: <what the error is, one sentence>
WHY: <why it failed, one sentence>
SOLUTION: <how to solve it - code snippet or step>

Keep each field short. If unsure about a field, write N/A.

--- DEPLOY / ACCESS OUTPUT (tail) ---
{error_text}
"""
    return ask(prompt)


def main():
    started_at = time.perf_counter()

    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--deploy",
        default=os.getenv("DEPLOY_CMD"),
        help="Command that deploys or accesses the app",
    )

    args = parser.parse_args()

    # No command supplied: report a configuration failure, then exit.
    if not args.deploy:
        error_message = "No DEPLOY_CMD or --deploy argument provided"

        print("errors.py: no deploy/access command provided.")
        print('Usage: python agent/errors.py --deploy "python deploy.py"')
        print("       or set the DEPLOY_CMD environment variable.")

        send_agent_status(
            agent_name="errors_agent",
            stage="deploy",
            status="failed",
            decision="failed",
            provider=os.getenv("AI_PROVIDER", "gemini"),
            model=MODEL,
            requests_count=0,
            api_key_count=1 if os.getenv("GEMINI_API_KEY") else 0,
            execution_time_seconds=time.perf_counter() - started_at,
            error=error_message,
        )

        sys.exit(2)

    # Check Gemini availability.
    ai_ok, ai_reason = ai_status()

    if ai_ok:
        print(f"[AI] model '{MODEL}' available and running.")
    else:
        print(f"[AI] model NOT available: {ai_reason}")

    print(f"errors.py: running deploy/access -> {args.deploy}")

    code, output = run_deploy(args.deploy)

    print(output)

    # Deployment/access command succeeded.
    if code == 0:
        print("SUCCESS: application deployed and accessible.")

        send_agent_status(
            agent_name="errors_agent",
            stage="deploy",
            status="approved",
            decision="healthy",
            provider=os.getenv("AI_PROVIDER", "gemini"),
            model=MODEL,
            requests_count=1 if ai_ok else 0,
            api_key_count=1 if os.getenv("GEMINI_API_KEY") else 0,
            execution_time_seconds=time.perf_counter() - started_at,
            error="" if ai_ok else ai_reason,
        )
        sys.exit(0)

    # ---- failure path ----
    # ---- failure path ----
    if ai_ok:
        try:
            api_started_at = time.perf_counter()

            diag, prompt_tokens, completion_tokens = diagnose(
                output[-20_000:]
            )

            api_duration = time.perf_counter() - api_started_at

            print("----- errors.py diagnosis (AI supporter) -----")
            print(diag)
            print("-----------------------------------------------")

            with open("errors_report.txt", "w", encoding="utf-8") as file_handle:
                file_handle.write(diag)

            send_agent_status(
                agent_name="errors_agent",
                stage="deploy",
                status="failed",
                decision="failed",
                provider=os.getenv("AI_PROVIDER", "gemini"),
                model=MODEL,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                total_tokens=prompt_tokens + completion_tokens,
                requests_count=2,
                api_key_count=1 if os.getenv("GEMINI_API_KEY") else 0,
                execution_time_seconds=time.perf_counter() - started_at,
                api_response_time_seconds=api_duration,
                error="Deployment/access command failed",
            )

            sys.exit(1)

        except Exception as exc:
            ai_ok = False
            ai_reason = f"AI call failed: {exc}"
    # ---- degraded (no AI) ----

    print("FAILED during deployment. AI supporter unavailable ->", ai_reason)
    print("Raw output (tail):")
    print(output[-5000:])
    with open("errors_report.txt", "w", encoding="utf-8") as f:
        f.write(f"AI supporter unavailable: {ai_reason}\n\n{output}")

        send_agent_status(
        agent_name="errors_agent",
        stage="deploy",
        status="failed",
        decision="failed",
        provider=os.getenv("AI_PROVIDER", "gemini"),
        model=MODEL,
        requests_count=1 if os.getenv("GEMINI_API_KEY") else 0,
        api_key_count=1 if os.getenv("GEMINI_API_KEY") else 0,
        execution_time_seconds=time.perf_counter() - started_at,
        error=ai_reason,
    )
    sys.exit(1)


if __name__ == "__main__":
    main()

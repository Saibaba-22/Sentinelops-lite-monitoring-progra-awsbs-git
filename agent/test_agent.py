"""
test_agent.py  -  PHASE 1: PRE-DEPLOY test verification
--------------------------------------------------------
Runs your test command BEFORE deployment. Uses an AI model to decide
whether the suite passed; if it failed, prints:

    test_agent.py failed with <file>

and exits 1.

The AI model is defined IN THIS FILE (MODEL below) so you can change it
on the spot if it becomes unavailable. The API key is read from the
GEMINI_API_KEY environment variable.

Usage:
    python test_agent.py                           # default: pytest -q
    python test_agent.py --cmd "pytest -v"
    TEST_CMD="tox" python test_agent.py
"""

# ===== AI CONFIG =========================================================
# Edit MODEL here if the model is unavailable (e.g. quota / region).
# Other valid examples: "gemini-2.5-pro", "gemini-1.5-flash".
MODEL = "gemini-2.5-flash"
# The API key is taken from the GEMINI_API_KEY environment variable.
# ========================================================================

import os
import sys
import argparse
import subprocess
import time
from monitor_client import send_agent_status


def _build_client():
    """Return a Gemini client, or raise a clear reason if it can't be built."""
    try:
        from google import genai
    except ImportError:
        raise RuntimeError("google-genai SDK not installed -> pip install google-genai")
    key = os.environ.get("GEMINI_API_KEY")
    if not key:
        raise RuntimeError("GEMINI_API_KEY environment variable is not set")
    return genai.Client(api_key=key)


def ai_status():
    """Return (available, reason). Pings the model once to confirm it runs."""
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
    """Ask the AI and return (text, token_count)."""
        prompt_tokens = 0
        completion_tokens = 0

    try:
        usage = resp.usage_metadata
        prompt_tokens = usage.prompt_token_count or 0
        completion_tokens = usage.candidates_token_count or 0
    except Exception:
        pass
    return text, prompt_tokens, completion_tokens


def run_tests(cmd):
    proc = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    out = (proc.stdout or "") + "\n" + (proc.stderr or "")
    return proc.returncode, out


def collect_sources(path, limit=200_000):
    sources, total = {}, 0
    for root, _, files in os.walk(path):
        if any(s in root for s in (".venv", "node_modules", ".git", "__pycache__")):
            continue
        for fn in files:
            if fn.endswith(".py"):
                fp = os.path.join(root, fn)
                try:
                    with open(fp, encoding="utf-8") as f:
                        txt = f.read()
                except Exception:
                    continue
                if total + len(txt) > limit:
                    continue
                sources[fp] = txt
                total += len(txt)
    return sources


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cmd", default=os.getenv("TEST_CMD", "pytest -q"))
    ap.add_argument("--path", default=".")
    args = ap.parse_args()

    ai_ok, ai_reason = ai_status()
    if ai_ok:
        print(f"[AI] model '{MODEL}' available and running.")
    else:
        print(f"[AI] model NOT available: {ai_reason}")

    code, output = run_tests(args.cmd)
    tail = output[-20_000:]

    started_at = time.perf_counter()

    if ai_ok:
        try:
            sources = collect_sources(args.path)
            src_block = "\n\n".join(f"=== {p} ===\n{s}" for p, s in sources.items())
            prompt = f"""
You are a QA verifier for a CI pipeline.
A test command was run on a Python project. Below is the captured output
(tail) and the project's source files for context.

Decide PASS or FAIL. If any test failed, identify the first source file
most responsible for the failure.

Reply EXACTLY in this format:
STATUS: PASS
FILE: NONE
REASON: <one sentence>

or, on failure:
STATUS: FAIL
FILE: <relative/path/to/file.py>
REASON: <one sentence>

--- TEST OUTPUT (tail) ---
{tail}

--- PROJECT SOURCES ---
{src_block}
"""
            api_started_at = time.perf_counter()
verdict, prompt_tokens, completion_tokens = ask(prompt)
api_duration = time.perf_counter() - api_started_at
            print("----- test_agent.py -----")
            print(verdict)
            print("-------------------------")

            status, failfile = "FAIL", "<unknown>"
            for line in verdict.splitlines():
                s = line.strip()
                if s.upper().startswith("STATUS:"):
                    status = s.split(":", 1)[1].strip().upper()
                elif s.upper().startswith("FILE:"):
                    failfile = s.split(":", 1)[1].strip()

            if status != "PASS":
                label = failfile if failfile and failfile.upper() != "NONE" else "<unknown>"
                print(f"test_agent.py failed with {label}")
                sys.exit(1)
            print("test_agent.py passed.")
            sys.exit(0)
        except Exception as e:
            # AI worked a moment ago but this call failed; degrade safely.
            ai_ok, ai_reason = False, f"AI call failed: {e}"

    # Degraded (no AI): trust the raw test exit code.
    if code == 0:
        print("test_agent.py passed (verified by raw exit code; AI unavailable).")
        sys.exit(0)
    print("test_agent.py failed with <unknown: AI unavailable>")
    print(ai_reason)

send_agent_status(
    agent_name="test_agent",
    stage="pre_deploy",
    status="failed" if code != 0 else "healthy",
    decision="fail" if code != 0 else "pass",
    provider="gemini",
    model=MODEL,
    requests_count=0,
    api_key_count=1 if os.getenv("GEMINI_API_KEY") else 0,
    execution_time_seconds=time.perf_counter() - started_at,
    error=ai_reason,
)

    send_agent_status(
    agent_name="test_agent",
    stage="pre_deploy",
    status="approved",
    decision="pass",
    provider="gemini",
    model=MODEL,
    prompt_tokens=prompt_tokens,
    completion_tokens=completion_tokens,
    total_tokens=prompt_tokens + completion_tokens,
    requests_count=2,  # Gemini availability ping + verdict request
    api_key_count=1,
    execution_time_seconds=time.perf_counter() - started_at,
    api_response_time_seconds=api_duration,
)
sys.exit(0)
send_agent_status(
    agent_name="test_agent",
    stage="pre_deploy",
    status="rejected",
    decision="fail",
    provider="gemini",
    model=MODEL,
    prompt_tokens=prompt_tokens,
    completion_tokens=completion_tokens,
    total_tokens=prompt_tokens + completion_tokens,
    requests_count=2,
    api_key_count=1,
    execution_time_seconds=time.perf_counter() - started_at,
    api_response_time_seconds=api_duration,
)
sys.exit(1)



if __name__ == "__main__":
    main()

"""
test_agent.py - PHASE 1: PRE-DEPLOY test verification.
Runs tests before deployment, uses Gemini to review the result, and sends
AI-agent metrics to the deployed monitoring endpoint.
Required environment variables:
    GEMINI_API_KEY
    MONITOR_API_URL
    MONITOR_TOKEN
Optional environment variables:
    TEST_CMD
    TARGET_CLOUD
    AI_PROVIDER
    AI_MODEL
"""

import argparse
import os
import subprocess
import sys
import time
from monitor_client import send_agent_status

# ---------------------------------------------------------------------------
# AI configuration
# ---------------------------------------------------------------------------

PROVIDER = os.getenv("AI_PROVIDER", "gemini")
MODEL = os.getenv("AI_MODEL", "gemini-3.5-flash")

AGENT_NAME = "test_agent"
STAGE = "pre_deploy"


# ---------------------------------------------------------------------------
# Gemini helpers
# ---------------------------------------------------------------------------

def build_client():
    """Build and return a Gemini client."""

    try:
        from google import genai
    except ImportError as exc:
        raise RuntimeError(
            "google-genai SDK is not installed. Run: pip install google-genai"
        ) from exc

    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY environment variable is not set")

    return genai.Client(api_key=api_key)


def extract_usage(response):
    """
    Return prompt/input and completion/output token counts safely.
    Token metadata may not exist for every provider response, so zero is valid.
    """
    prompt_tokens = 0
    completion_tokens = 0
    try:
        usage = response.usage_metadata
        prompt_tokens = int(getattr(usage, "prompt_token_count", 0) or 0)
        completion_tokens = int(getattr(usage, "candidates_token_count", 0) or 0)
    except Exception:
        pass
    return prompt_tokens, completion_tokens


def ai_status():
    """
    Make a small Gemini request to ensure the model is accessible.

    Returns:
        available,
        reason,
        prompt_tokens,
        completion_tokens,
        response_duration_seconds,
        request_count
    """

    try:
        client = build_client()
    except Exception as exc:
        return False, str(exc), 0, 0, 0.0, 0

    started_at = time.perf_counter()

    try:
        response = client.models.generate_content(
            model=MODEL,
            contents="Reply with exactly: OK",
        )

        duration = time.perf_counter() - started_at
        prompt_tokens, completion_tokens = extract_usage(response)

        return (
            True,
            "",
            prompt_tokens,
            completion_tokens,
            duration,
            1,
        )

    except Exception as exc:
        duration = time.perf_counter() - started_at

        return (
            False,
            f"Model '{MODEL}' could not respond: {exc}",
            0,
            0,
            duration,
            1,
        )


def ask(prompt):
    """
    Send the test-result prompt to Gemini.

    Returns:
        verdict_text,
        prompt_tokens,
        completion_tokens,
        response_duration_seconds
    """

    client = build_client()

    started_at = time.perf_counter()

    response = client.models.generate_content(
        model=MODEL,
        contents=prompt,
    )

    duration = time.perf_counter() - started_at
    prompt_tokens, completion_tokens = extract_usage(response)

    text = (getattr(response, "text", "") or "").strip()

    return text, prompt_tokens, completion_tokens, duration


# ---------------------------------------------------------------------------
# Test and source helpers
# ---------------------------------------------------------------------------

def run_tests(command):
    """Run the configured test command and return exit code plus output."""

    process = subprocess.run(
        command,
        shell=True,
        capture_output=True,
        text=True,
    )

    output = (process.stdout or "") + "\n" + (process.stderr or "")

    return process.returncode, output


def collect_sources(path, limit=200_000):
    """
    Collect Python sources for Gemini context.

    The size limit prevents accidentally creating a huge prompt.
    """

    sources = {}
    total_size = 0

    excluded_directories = (
        ".venv",
        "venv",
        "node_modules",
        ".git",
        "__pycache__",
        ".pytest_cache",
        "logs",
    )

    for root, _, files in os.walk(path):
        if any(part in root for part in excluded_directories):
            continue

        for filename in files:
            if not filename.endswith(".py"):
                continue

            file_path = os.path.join(root, filename)

            try:
                with open(file_path, encoding="utf-8") as file_handle:
                    content = file_handle.read()
            except Exception:
                continue

            if total_size + len(content) > limit:
                continue

            sources[file_path] = content
            total_size += len(content)

    return sources


def parse_verdict(verdict):
    """
    Parse Gemini output.

    Expected format:
        STATUS: PASS
        FILE: NONE
        REASON: ...
    """

    status = "FAIL"
    failed_file = "<unknown>"

    for line in verdict.splitlines():
        item = line.strip()

        if item.upper().startswith("STATUS:"):
            status = item.split(":", 1)[1].strip().upper()

        elif item.upper().startswith("FILE:"):
            failed_file = item.split(":", 1)[1].strip()

    return status, failed_file


# ---------------------------------------------------------------------------
# Monitoring helper
# ---------------------------------------------------------------------------

def report_and_exit(
    *,
    exit_code,
    status,
    decision,
    overall_started_at,
    prompt_tokens=0,
    completion_tokens=0,
    request_count=0,
    api_response_time_seconds=0.0,
    error=None,
):
    """
    Send a final monitoring event before exiting.

    Monitoring errors are handled inside send_agent_status(), so a temporary
    monitoring outage does not hide the real test result.
    """

    total_tokens = prompt_tokens + completion_tokens

    send_agent_status(
        agent_name=AGENT_NAME,
        stage=STAGE,
        status=status,
        decision=decision,
        provider=PROVIDER,
        model=MODEL,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        total_tokens=total_tokens,
        requests_count=request_count,
        api_key_count=1 if os.getenv("GEMINI_API_KEY") else 0,
        execution_time_seconds=time.perf_counter() - overall_started_at,
        api_response_time_seconds=api_response_time_seconds,
        error=error,
    )

    sys.exit(exit_code)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    overall_started_at = time.perf_counter()

    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--cmd",
        default=os.getenv("TEST_CMD", "pytest -q"),
        help="Test command to execute. Default: pytest -q",
    )
    parser.add_argument(
        "--path",
        default=".",
        help="Project path from which Python source files are collected.",
    )
    args = parser.parse_args()

    # Report that the pre-deploy AI agent has started.
    send_agent_status(
        agent_name=AGENT_NAME,
        stage=STAGE,
        status="running",
        decision="none",
        provider=PROVIDER,
        model=MODEL,
        requests_count=0,
        api_key_count=1 if os.getenv("GEMINI_API_KEY") else 0,
    )

    # First Gemini request: availability check.
    (
        ai_ok,
        ai_reason,
        ping_prompt_tokens,
        ping_completion_tokens,
        ping_duration,
        ping_request_count,
    ) = ai_status()

    if ai_ok:
        print(f"[AI] Provider '{PROVIDER}', model '{MODEL}' is available.")
    else:
        print(f"[AI] Model unavailable: {ai_reason}")

    # Run deterministic test command.
    test_exit_code, test_output = run_tests(args.cmd)
    test_output_tail = test_output[-20_000:]

    # -----------------------------------------------------------------------
    # Gemini unavailable: use real pytest/test command exit code.
    # -----------------------------------------------------------------------
    if not ai_ok:
        if test_exit_code == 0:
            print(
                "test_agent.py passed "
                "(raw test command passed; AI verification unavailable)."
            )

            report_and_exit(
                exit_code=0,
                status="approved",
                decision="pass",
                overall_started_at=overall_started_at,
                prompt_tokens=ping_prompt_tokens,
                completion_tokens=ping_completion_tokens,
                request_count=ping_request_count,
                api_response_time_seconds=ping_duration,
                error=ai_reason,
            )

        print("test_agent.py failed (raw test command failed; AI unavailable).")
        print(ai_reason)

        report_and_exit(
            exit_code=1,
            status="rejected",
            decision="fail",
            overall_started_at=overall_started_at,
            prompt_tokens=ping_prompt_tokens,
            completion_tokens=ping_completion_tokens,
            request_count=ping_request_count,
            api_response_time_seconds=ping_duration,
            error=ai_reason,
        )

    # -----------------------------------------------------------------------
    # Gemini is available: prepare prompt and ask for review.
    # -----------------------------------------------------------------------
    try:
        sources = collect_sources(args.path)

        source_block = "\n\n".join(
            f"=== {file_path} ===\n{content}"
            for file_path, content in sources.items()
        )

        prompt = f"""
You are a QA verifier for a CI/CD pipeline.

A test command ran on a Python project. Review the test output and source
context. Determine whether the result is PASS or FAIL.

Important deterministic rule:
- If the TEST COMMAND EXIT CODE is non-zero, STATUS must be FAIL.
- If the TEST COMMAND EXIT CODE is zero and no failure exists in output,
  STATUS may be PASS.

Reply exactly in this format:

STATUS: PASS
FILE: NONE
REASON: <one sentence>

Or, on failure:

STATUS: FAIL
FILE: <relative/path/to/file.py or NONE>
REASON: <one sentence>

--- TEST COMMAND ---

{args.cmd}

--- TEST COMMAND EXIT CODE ---

{test_exit_code}

--- TEST OUTPUT (tail) ---

{test_output_tail}

--- PROJECT PYTHON SOURCES ---

{source_block}
"""

        (
            verdict,
            verdict_prompt_tokens,
            verdict_completion_tokens,
            verdict_duration,
        ) = ask(prompt)

        print("----- test_agent.py AI verdict -----")
        print(verdict)
        print("------------------------------------")

    except Exception as exc:
        # Gemini was available initially but the verdict request failed.
        error_message = f"AI verdict request failed: {exc}"

        print(error_message)

        if test_exit_code == 0:
            print("Raw test command passed; allowing deployment using fallback.")

            report_and_exit(
                exit_code=0,
                status="approved",
                decision="pass",
                overall_started_at=overall_started_at,
                prompt_tokens=ping_prompt_tokens,
                completion_tokens=ping_completion_tokens,
                request_count=ping_request_count + 1,
                api_response_time_seconds=ping_duration,
                error=error_message,
            )

        print("Raw test command failed; blocking deployment.")

        report_and_exit(
            exit_code=1,
            status="rejected",
            decision="fail",
            overall_started_at=overall_started_at,
            prompt_tokens=ping_prompt_tokens,
            completion_tokens=ping_completion_tokens,
            request_count=ping_request_count + 1,
            api_response_time_seconds=ping_duration,
            error=error_message,
        )

    # Include token usage from both Gemini requests:
    # 1. availability ping
    # 2. AI verdict request
    all_prompt_tokens = ping_prompt_tokens + verdict_prompt_tokens
    all_completion_tokens = ping_completion_tokens + verdict_completion_tokens
    total_request_count = ping_request_count + 1

    ai_status_value, failed_file = parse_verdict(verdict)

    # A test command failure must always block deployment.
    # Gemini can explain the failure, but should not override pytest's result.
    if test_exit_code != 0:
        print(
            "test_agent.py failed because the raw test command returned "
            f"exit code {test_exit_code}."
        )

        report_and_exit(
            exit_code=1,
            status="rejected",
            decision="fail",
            overall_started_at=overall_started_at,
            prompt_tokens=all_prompt_tokens,
            completion_tokens=all_completion_tokens,
            request_count=total_request_count,
            api_response_time_seconds=verdict_duration,
            error=f"Raw test command failed. AI identified: {failed_file}",
        )

    # Tests passed but Gemini reports failure: block for safety.
    if ai_status_value != "PASS":
        label = (
            failed_file
            if failed_file and failed_file.upper() != "NONE"
            else "<unknown>"
        )

        print(f"test_agent.py rejected by AI review: {label}")

        report_and_exit(
            exit_code=1,
            status="rejected",
            decision="fail",
            overall_started_at=overall_started_at,
            prompt_tokens=all_prompt_tokens,
            completion_tokens=all_completion_tokens,
            request_count=total_request_count,
            api_response_time_seconds=verdict_duration,
            error=f"AI rejected the test review. File: {label}",
        )

    # Tests passed and AI approved.
    print("test_agent.py passed: raw tests passed and AI approved.")

    report_and_exit(
        exit_code=0,
        status="approved",
        decision="pass",
        overall_started_at=overall_started_at,
        prompt_tokens=all_prompt_tokens,
        completion_tokens=all_completion_tokens,
        request_count=total_request_count,
        api_response_time_seconds=verdict_duration,
    )


if __name__ == "__main__":
    main()
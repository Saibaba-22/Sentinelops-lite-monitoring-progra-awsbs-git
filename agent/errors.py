"""Deployment failure collector and diagnosis agent.

This script is invoked only after a deployment step fails.  It always writes a
human-readable report and never exposes secret values in collected context.
"""

from __future__ import annotations

import glob
import os
import re
import subprocess
import sys
import time
from pathlib import Path

try:
    from monitor_client import send_agent_status
except ImportError:  # pragma: no cover
    def send_agent_status(**_kwargs):
        return False

MODEL = os.getenv("AI_MODEL", "gemini-2.5-flash")
PROVIDER = os.getenv("AI_PROVIDER", "gemini")
_ai_prompt_tokens = 0
_ai_completion_tokens = 0
_ai_total_tokens = 0
_ai_requests = 0
_ai_response_time = 0.0


def build_client():
    from google import genai

    key = os.getenv("GEMINI_API_KEY")
    if not key:
        raise RuntimeError("GEMINI_API_KEY not set")
    return genai.Client(api_key=key)


def ask_ai(prompt: str) -> str:
    global _ai_prompt_tokens, _ai_completion_tokens, _ai_total_tokens
    global _ai_requests, _ai_response_time
    client = build_client()
    started = time.perf_counter()
    response = client.models.generate_content(model=MODEL, contents=prompt)
    _ai_response_time += time.perf_counter() - started
    _ai_requests += 1
    usage = getattr(response, "usage_metadata", None)
    _ai_prompt_tokens += int(getattr(usage, "prompt_token_count", 0) or 0)
    _ai_completion_tokens += int(getattr(usage, "candidates_token_count", 0) or 0)
    _ai_total_tokens = _ai_prompt_tokens + _ai_completion_tokens
    return (getattr(response, "text", "") or "").strip()


def safe_command(command: str, timeout: int = 12) -> str:
    try:
        result = subprocess.run(command, shell=True, capture_output=True, text=True, timeout=timeout, check=False)
        return (result.stdout + result.stderr)[:4000]
    except Exception as exc:
        return f"command unavailable: {exc}"


def collect_context() -> str:
    parts = ["=== DEPLOYMENT VARIABLES ==="]
    for key in (
        "TARGET_CLOUD", "AWS_APP_NAME", "AWS_ENV_NAME", "AWS_REGION",
        "AZURE_WEBAPP_NAME", "AZURE_RESOURCE_GROUP", "GITHUB_SHA",
        "DOCKERHUB_USERNAME", "DOCKERHUB_REPOSITORY", "APP_URL",
    ):
        parts.append(f"{key}={os.getenv(key, 'N/A')}")
    parts.append("\n=== COMMAND OUTPUT ===")
    commands = [
        "aws elasticbeanstalk describe-environments --application-name \"${AWS_APP_NAME:-}\" --environment-names \"${AWS_ENV_NAME:-}\" --query 'Environments[0].[Status,Health,HealthStatus,CNAME]' --output text 2>&1",
        "az webapp show --name \"${AZURE_WEBAPP_NAME:-}\" --resource-group \"${AZURE_RESOURCE_GROUP:-}\" --query '[state,defaultHostName]' -o tsv 2>&1",
        "docker ps -a 2>&1 | head -100",
        "git status --short 2>&1 | head -100",
    ]
    for command in commands:
        output = safe_command(command)
        if output.strip():
            parts.append(f"\n$ {command}\n{output}")

    parts.append("\n=== REPORT AND LOG FILES ===")
    for pattern in ("reports/*.txt", "reports/*.log", "*.log", "errors_report.txt"):
        for filename in glob.glob(pattern)[:8]:
            try:
                content = Path(filename).read_text(encoding="utf-8", errors="replace")
                parts.append(f"\n--- {filename} ---\n{content[-5000:]}")
            except OSError:
                pass
    return "\n".join(parts)[-20000:]


def parse_file_line(text: str) -> list[tuple[str, str]]:
    patterns = (
        r'File "([^"]+)", line (\d+)',
        r"([A-Za-z0-9_./-]+\.py):(\d+)",
        r"([A-Za-z0-9_./-]+\.json)(?:.*?line\s+)(\d+)",
        r"Dockerfile:(\d+)",
    )
    found = []
    for pattern in patterns:
        for match in re.finditer(pattern, text):
            if pattern.startswith("Dockerfile"):
                item = ("Dockerfile", match.group(1))
            else:
                item = (match.group(1), match.group(2))
            if "site-packages" not in item[0] and item not in found:
                found.append(item)
    return found[:5]


def deterministic_diagnosis(context: str) -> str | None:
    lowered = context.lower()
    if "cannotpullimagemanifesterror" in lowered or "failed to pull image" in lowered:
        return """FILE: deployment configuration
LINE: N/A
PRESENT_ERROR: The platform could not pull the configured container image.
EXPECTED_VALUE: A public Docker Hub image and tag that exists.
WHY: The image name, tag, or registry credentials do not match the image pushed by CI.
SOLUTION: Verify the Docker Hub repository and use the exact SHA tag produced by the build job.
"""
    if "placeholder" in lowered and "image" in lowered:
        return """FILE: docker-compose.yml or deployment template
LINE: N/A
PRESENT_ERROR: An image placeholder reached deployment.
EXPECTED_VALUE: A concrete Docker image URI with the current build tag.
WHY: The deployment preparation step did not render the template.
SOLUTION: Re-run the rendering step and fail before deployment when a template marker remains.
"""
    if "no such image" in lowered or "manifest unknown" in lowered:
        return """FILE: docker-compose.yml or deployment template
LINE: N/A
PRESENT_ERROR: The platform requested an image tag that is not present in Docker Hub.
EXPECTED_VALUE: The same tag must be pushed and referenced by the deployment manifest.
WHY: Build and deployment used different tags.
SOLUTION: Use the immutable GitHub SHA tag in every service image reference.
"""
    if "no module named" in lowered:
        match = re.search(r"no module named ['\"]([^'\"]+)", lowered)
        module = match.group(1) if match else "unknown"
        return f"""FILE: requirements.txt
LINE: N/A
PRESENT_ERROR: Python module '{module}' is missing.
EXPECTED_VALUE: Every imported runtime module is installed in the image.
WHY: The dependency is absent from requirements.txt or the image was not rebuilt.
SOLUTION: Add the package to requirements.txt, rebuild, and push a new immutable image.
"""
    return None


def fallback_report(context: str, hints: list[tuple[str, str]]) -> str:
    file_name, line = hints[0] if hints else ("deployment logs", "N/A")
    return f"""FILE: {file_name}
LINE: {line}
PRESENT_ERROR: Deployment failed; inspect the captured platform output.
EXPECTED_VALUE: All containers start and the public health endpoint returns HTTP 200.
WHY: The deployment command or post-deployment health check failed.
SOLUTION: Review the raw context below and correct the first platform or application error.

--- RAW CONTEXT ---
{context[-8000:]}
"""


def send_status(started: float, error: str) -> None:
    try:
        send_agent_status(
            agent_name="errors_agent",
            stage="deploy",
            status="failed",
            decision="failed",
            provider=PROVIDER,
            model=MODEL,
            prompt_tokens=_ai_prompt_tokens,
            completion_tokens=_ai_completion_tokens,
            total_tokens=_ai_total_tokens,
            requests_count=_ai_requests,
            api_key_count=1 if os.getenv("GEMINI_API_KEY") else 0,
            execution_time_seconds=round(time.perf_counter() - started, 4),
            api_response_time_seconds=round(_ai_response_time, 4),
            error=error,
        )
    except Exception:
        pass


def main() -> int:
    started = time.perf_counter()
    context = collect_context()
    hints = parse_file_line(context)
    report = deterministic_diagnosis(context)

    if report is None and os.getenv("RUN_AI_REVIEW", "0") == "1" and os.getenv("GEMINI_API_KEY"):
        try:
            report = ask_ai(
                "Return exactly FILE, LINE, PRESENT_ERROR, EXPECTED_VALUE, WHY, SOLUTION for the main deployment error.\n\n"
                + context
            )
        except Exception as exc:
            print(f"[AI] unavailable: {exc}")
    if not report:
        report = fallback_report(context, hints)

    reports = Path("reports")
    reports.mkdir(exist_ok=True)
    Path("errors_report.txt").write_text(report + "\n\n--- RAW CONTEXT ---\n" + context[-8000:], encoding="utf-8")
    (reports / "deploy_error_diagnosis.txt").write_text(report + "\n", encoding="utf-8")
    print(report)
    send_status(started, "deployment failure diagnosis")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())

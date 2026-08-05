"""
agent/github_collector.py
Auto-pulls AI agent metrics from GitHub Actions API.
Runs as a background thread inside app.py.
No POST from agents needed — Flask fetches everything.
"""
from __future__ import annotations

import os
import re
import time
import threading
import requests
from typing import Optional

GITHUB_TOKEN    = os.environ.get("GITHUB_TOKEN_METRICS", "").strip()
GITHUB_REPO     = os.environ.get("GITHUB_REPO",          "").strip()
POLL_INTERVAL   = int(os.environ.get("GITHUB_POLL_INTERVAL", "60"))
GITHUB_API_BASE = "https://api.github.com"

# Track which runs we've already processed (avoid double-counting)
_processed_runs: set = set()
_state_cache: dict   = {}
_lock                = threading.Lock()

# Mapping: agent script name -> (agent_name label, stage label)
AGENT_MAP = {
    "test_agent":  ("test_agent",  "pre_deploy"),
    "errors":      ("errors",      "during_deploy"),
    "final_agent": ("final_agent", "post_deploy"),
}

# ── SPECIAL CASE: errors.py always exits 1 by design ─────────
# If we detected this is errors.py running, treat successful run as passed
if agent_key == "errors":
    # errors.py wrote its reports = it succeeded
    if "Reports written to" in log_text or "reports written to" in lower:
        stats["state"]    = "passed"
        stats["decision"] = "pass"
        return stats
    # else fall through to normal detection

def _headers() -> dict:
    return {
        "Accept":        "application/vnd.github+json",
        "Authorization": f"Bearer {GITHUB_TOKEN}",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def _get(path: str, params: dict = None) -> Optional[dict]:
    """Safe GitHub API GET."""
    if not GITHUB_TOKEN or not GITHUB_REPO:
        return None
    try:
        r = requests.get(
            f"{GITHUB_API_BASE}{path}",
            headers=_headers(),
            params=params or {},
            timeout=15,
        )
        if r.status_code == 200:
            return r.json()
        print(f"[gh-collector] {path} -> {r.status_code}")
        return None
    except Exception as e:
        print(f"[gh-collector] error {path}: {e}")
        return None


def _parse_job_log(log_text: str, agent_key: str) -> dict:
    """
    Extract agent metrics from a job's log output.
    """
    stats = {
        "prompt_tokens":     0,
        "completion_tokens": 0,
        "total_tokens":      0,
        "api_calls":         0,
        "execution_time":    0.0,
        "state":             "unknown",
        "decision":          "unknown",
    }

    lower = log_text.lower()

    # ── Extract numeric metrics ──────────────────────────────
    for line in log_text.splitlines():
        m = re.search(r"[Pp]rompt.{0,10}[Tt]okens?[:\s=]+(\d+)", line)
        if m:
            stats["prompt_tokens"] = max(stats["prompt_tokens"], int(m.group(1)))
        m = re.search(r"[Cc]ompletion.{0,10}[Tt]okens?[:\s=]+(\d+)", line)
        if m:
            stats["completion_tokens"] = max(stats["completion_tokens"], int(m.group(1)))
        m = re.search(r"[Tt]otal[_ ]?[Tt]ok(?:en)?s?[:\s=]+(\d+)", line)
        if m:
            stats["total_tokens"] = max(stats["total_tokens"], int(m.group(1)))
        m = re.search(r"(?:api[_ ]?calls?|[Rr]equests?)[:\s=]+(\d+)", line)
        if m:
            stats["api_calls"] = max(stats["api_calls"], int(m.group(1)))
        m = re.search(r"(?:execution[_ ]?time|[Aa]i[_ ]?[Tt]ime|Total execution)[:\s=]+([\d.]+)", line)
        if m:
            stats["execution_time"] = max(stats["execution_time"], float(m.group(1)))

    if stats["total_tokens"] == 0:
        stats["total_tokens"] = stats["prompt_tokens"] + stats["completion_tokens"]

    # ── State detection — per-agent logic ────────────────────

    # SPECIAL CASE: errors.py always exits 1 by design.
    # If reports were written, the agent ran successfully.
    if agent_key == "errors":
        if ("reports written to" in lower
                or "END OF REPORT" in log_text
                or "DEPLOYMENT FAILURE DIAGNOSTIC REPORT" in log_text):
            stats["state"]    = "passed"
            stats["decision"] = "pass"
            return stats

    # test_agent success/failure markers
    if agent_key == "test_agent":
        if "no errors found - ready to deploy" in lower:
            stats["state"]    = "passed"
            stats["decision"] = "pass"
            return stats
        if "blocking deploy" in lower or "❌ found" in lower.replace("❌", "❌"):
            stats["state"]    = "failed"
            stats["decision"] = "fail"
            return stats

    # final_agent success/failure markers
    if agent_key == "final_agent":
        if ("completed in" in lower
                or "no issues found" in lower
                or "post-deploy health" in lower):
            stats["state"]    = "passed"
            stats["decision"] = "pass"
            return stats

    # ── Generic fallback ─────────────────────────────────────
    if "Error: Process completed with exit code 1" in log_text:
        stats["state"]    = "failed"
        stats["decision"] = "fail"
    else:
        stats["state"]    = "passed"
        stats["decision"] = "pass"

    return stats

def _update_metrics(agent_name: str, stage: str, stats: dict,
                    run_id: int, timestamp: float):
    """Push extracted stats into Prometheus gauges/counters."""
    from app import (
        agent_state, agent_last_run_timestamp_seconds,
        agent_prompt_tokens_total, agent_completion_tokens_total,
        agent_token_usage_total, agent_api_calls_total,
        agent_execution_time_seconds, agent_execution_duration_seconds,
        agent_last_decision, agent_tasks_total,
    )

    cloud    = os.environ.get("TARGET_CLOUD", "aws")
    provider = os.environ.get("AI_PROVIDER",  "gemini")
    model    = os.environ.get("AI_MODEL",     "gemini-2.5-flash")

    with _lock:
        # ── State (gauge — clear old, set new) ────────────────
        key = (agent_name, stage, cloud)
        old = _state_cache.get(key)
        new_state = stats.get("state", "unknown")
        if old and old != new_state:
            agent_state.labels(agent_name=agent_name, stage=stage,
                               cloud=cloud, state=old).set(0)
        agent_state.labels(agent_name=agent_name, stage=stage,
                           cloud=cloud, state=new_state).set(1)
        _state_cache[key] = new_state

        # ── Last run timestamp ────────────────────────────────
        agent_last_run_timestamp_seconds.labels(
            agent_name=agent_name, stage=stage, cloud=cloud
        ).set(timestamp)

        # ── Counters — increment by run's contribution ───────
        common = dict(agent_name=agent_name, stage=stage, cloud=cloud,
                      provider=provider, model=model)
        pt = int(stats.get("prompt_tokens", 0))
        ct = int(stats.get("completion_tokens", 0))
        tt = int(stats.get("total_tokens", 0))
        ac = int(stats.get("api_calls", 0))

        if pt > 0: agent_prompt_tokens_total.labels(**common).inc(pt)
        if ct > 0: agent_completion_tokens_total.labels(**common).inc(ct)
        if tt > 0: agent_token_usage_total.labels(**common).inc(tt)

        api_status = "success" if new_state == "passed" else "failed"
        if ac > 0:
            agent_api_calls_total.labels(
                agent_name=agent_name, stage=stage, cloud=cloud,
                provider=provider, model=model, status=api_status
            ).inc(ac)

        # ── Task outcome ──────────────────────────────────────
        task_result = "pass" if new_state == "passed" else "fail"
        agent_tasks_total.labels(
            agent_name=agent_name, stage=stage,
            cloud=cloud, result=task_result
        ).inc(1)

        # ── Execution time ────────────────────────────────────
        ex = float(stats.get("execution_time", 0))
        if ex > 0:
            agent_execution_time_seconds.labels(
                agent_name=agent_name, stage=stage, cloud=cloud
            ).set(ex)
            agent_execution_duration_seconds.labels(
                agent_name=agent_name, stage=stage, cloud=cloud
            ).observe(ex)

        # ── Decision ──────────────────────────────────────────
        dec = stats.get("decision", "unknown")
        agent_last_decision.labels(
            agent_name=agent_name, stage=stage,
            cloud=cloud, decision=dec
        ).set(1)

    print(f"[gh-collector] Updated {agent_name} (run {run_id}): "
          f"tokens={tt} calls={ac} state={new_state}")


def _process_run(run: dict):
    """Fetch jobs+logs for one workflow run, extract metrics per agent."""
    run_id = run["id"]
    if run_id in _processed_runs:
        return
    ts = time.time()  # fallback timestamp
    try:
        # Parse GitHub's ISO timestamp
        from datetime import datetime
        ts = datetime.fromisoformat(
            run["updated_at"].replace("Z", "+00:00")
        ).timestamp()
    except Exception:
        pass

    # Get all jobs for this run
    jobs_data = _get(f"/repos/{GITHUB_REPO}/actions/runs/{run_id}/jobs")
    if not jobs_data:
        return

    for job in jobs_data.get("jobs", []):
        job_id   = job["id"]
        job_name = (job.get("name") or "").lower()

        # Fetch job's log (plain text)
        try:
            log_url = (f"{GITHUB_API_BASE}/repos/{GITHUB_REPO}"
                       f"/actions/jobs/{job_id}/logs")
            r = requests.get(log_url, headers=_headers(),
                             timeout=30, allow_redirects=True)
            if r.status_code != 200:
                continue
            log_text = r.text
        except Exception as e:
            print(f"[gh-collector] log fetch failed: {e}")
            continue

        # Detect which agents ran in this job by scanning log
        for agent_key, (agent_name, stage) in AGENT_MAP.items():
            markers = [
                f"agent/{agent_key}.py",
                f"[{agent_key}]",
                f"agent_name=\"{agent_key}\"",
                f"agent_name='{agent_key}'",
            ]
            if any(m in log_text for m in markers):
                stats = _parse_job_log(log_text, agent_key)
                _update_metrics(agent_name, stage, stats, run_id, ts)

    _processed_runs.add(run_id)
    # Keep set from growing forever
    if len(_processed_runs) > 200:
        _processed_runs.clear()


def _poll_loop():
    """Main background loop — polls GitHub every POLL_INTERVAL seconds."""
    print(f"[gh-collector] Started (repo={GITHUB_REPO}, "
          f"interval={POLL_INTERVAL}s)")
    while True:
        try:
            if GITHUB_TOKEN and GITHUB_REPO:
                # Get recent workflow runs (last 10)
                runs_data = _get(
                    f"/repos/{GITHUB_REPO}/actions/runs",
                    params={"per_page": 10, "status": "completed"},
                )
                if runs_data:
                    for run in runs_data.get("workflow_runs", []):
                        _process_run(run)
        except Exception as e:
            print(f"[gh-collector] loop error: {e}")
        time.sleep(POLL_INTERVAL)


def start():
    """Kick off the background poller thread."""
    if not GITHUB_TOKEN:
        print("[gh-collector] GITHUB_TOKEN_METRICS not set — collector disabled")
        return
    if not GITHUB_REPO:
        print("[gh-collector] GITHUB_REPO not set — collector disabled")
        return
    t = threading.Thread(target=_poll_loop, daemon=True, name="gh-collector")
    t.start()
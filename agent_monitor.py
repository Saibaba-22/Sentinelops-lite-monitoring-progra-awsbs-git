"""Modern local AI-agent monitoring dashboard.

Run from the repository root after Prometheus and the Flask app are running:

    python agent_monitoring.py

Open:

    http://127.0.0.1:7000

The dashboard reads real Prometheus metrics when available and falls back to
logs/agent_stats.json for the latest persisted status. It never invents token
or request values.

Environment variables:
    PROMETHEUS_URL=http://127.0.0.1:9090
    AGENT_STATE_FILE=logs/agent_stats.json
    MONITOR_DASHBOARD_HOST=127.0.0.1
    MONITOR_DASHBOARD_PORT=7000
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

import requests
from flask import Flask, jsonify, render_template_string

BASE_DIR = Path(__file__).resolve().parent
PROMETHEUS_URL = os.getenv("PROMETHEUS_URL", "http://127.0.0.1:9090").rstrip("/")
STATE_FILE = Path(os.getenv("AGENT_STATE_FILE", str(BASE_DIR / "logs" / "agent_stats.json")))
HOST = os.getenv("MONITOR_DASHBOARD_HOST", "127.0.0.1")
PORT = int(os.getenv("MONITOR_DASHBOARD_PORT", "7000"))

app = Flask(__name__)


# ---------------------------------------------------------------------------
# Data collection
# ---------------------------------------------------------------------------


def load_state() -> dict[str, Any]:
    try:
        with STATE_FILE.open(encoding="utf-8") as handle:
            data = json.load(handle)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError, TypeError):
        return {}


def prometheus_query(query: str) -> list[dict[str, Any]]:
    """Run one instant PromQL query and return its vector result.

    An unavailable Prometheus returns an empty list; the UI reports the
    connection state instead of displaying fabricated values.
    """
    try:
        response = requests.get(
            f"{PROMETHEUS_URL}/api/v1/query",
            params={"query": query},
            timeout=5,
        )
        response.raise_for_status()
        body = response.json()
        if body.get("status") != "success":
            return []
        return body.get("data", {}).get("result", []) or []
    except (requests.RequestException, ValueError, TypeError):
        return []


def vector_by_agent(query: str) -> dict[str, float]:
    values: dict[str, float] = {}
    for item in prometheus_query(query):
        labels = item.get("metric", {})
        agent = labels.get("agent_name")
        if not agent:
            continue
        try:
            values[agent] = float(item.get("value", [0, 0])[1])
        except (IndexError, TypeError, ValueError):
            values[agent] = 0.0
    return values


def model_by_agent() -> dict[str, dict[str, str]]:
    values: dict[str, dict[str, str]] = {}
    for item in prometheus_query("agent_model_info"):
        labels = item.get("metric", {})
        agent = labels.get("agent_name")
        if agent:
            values[agent] = {
                "provider": labels.get("provider", "unknown"),
                "model": labels.get("model", "unknown"),
            }
    return values


def state_by_agent() -> dict[str, str]:
    values: dict[str, str] = {}
    for item in prometheus_query("agent_state == 1"):
        labels = item.get("metric", {})
        agent = labels.get("agent_name")
        if agent:
            values[agent] = labels.get("state", "unknown")
    return values


def collect_agents() -> tuple[list[dict[str, Any]], bool]:
    persisted = load_state().get("agents", {})
    if not isinstance(persisted, dict):
        persisted = {}

    token_totals = vector_by_agent("sum by (agent_name) (agent_token_usage_total)")
    prompt_totals = vector_by_agent("sum by (agent_name) (agent_prompt_tokens_total)")
    completion_totals = vector_by_agent("sum by (agent_name) (agent_completion_tokens_total)")
    request_totals = vector_by_agent("sum by (agent_name) (agent_api_calls_total)")
    requests_day = vector_by_agent(
        "sum by (agent_name) (increase(agent_api_calls_total[24h]))"
    )
    tokens_day = vector_by_agent(
        "sum by (agent_name) (increase(agent_token_usage_total[24h]))"
    )
    last_runs = vector_by_agent(
        "max by (agent_name) (agent_last_run_timestamp_seconds)"
    )
    states = state_by_agent()
    models = model_by_agent()

    discovered = set(persisted) | set(token_totals) | set(request_totals) | set(states)
    # Keep the known project agents visible, but mark them as not reported.
    discovered.update({"test_agent", "errors_agent", "final_agent"})

    agents: list[dict[str, Any]] = []
    for name in sorted(discovered):
        saved = persisted.get(name, {}) if isinstance(persisted.get(name, {}), dict) else {}
        model = models.get(name, {})
        last_run = last_runs.get(name, 0)
        if not last_run:
            last_run = saved.get("last_run")

        agents.append(
            {
                "agent_name": name,
                "status": states.get(name, saved.get("status", "not reported")),
                "decision": saved.get("decision", "none"),
                "stage": saved.get("stage", "unknown"),
                "cloud": saved.get("cloud", "unknown"),
                "provider": model.get("provider", saved.get("provider", "unknown")),
                "model": model.get("model", saved.get("model", "unknown")),
                "prompt_tokens": round(prompt_totals.get(name, saved.get("prompt_tokens", 0))),
                "completion_tokens": round(completion_totals.get(name, saved.get("completion_tokens", 0))),
                "total_tokens": round(token_totals.get(name, saved.get("total_tokens", 0))),
                "requests_total": round(request_totals.get(name, saved.get("requests", 0))),
                "requests_24h": round(requests_day.get(name, 0)),
                "tokens_24h": round(tokens_day.get(name, 0)),
                "last_run": last_run or None,
                "has_prometheus_data": name in states or name in token_totals or name in request_totals,
            }
        )

    prometheus_is_reachable = bool(prometheus_query("up"))
    return agents, prometheus_is_reachable


@app.get("/api/agents")
def api_agents():
    agents, prometheus_is_reachable = collect_agents()
    return jsonify(
        generated_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        prometheus_url=PROMETHEUS_URL,
        prometheus_reachable=prometheus_is_reachable,
        agents=agents,
    )


@app.get("/health")
def health():
    return jsonify(ok=True)


# ---------------------------------------------------------------------------
# Modern dashboard UI
# ---------------------------------------------------------------------------


PAGE = r"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>SentinelOps AI Agent Monitor</title>
  <style>
    :root {
      --bg: #070b18; --panel: #11182b; --panel2: #17213a;
      --line: #263452; --text: #edf4ff; --muted: #8ea0c0;
      --blue: #56b4ff; --cyan: #53e0d0; --green: #4ade80;
      --amber: #fbbf24; --red: #fb7185; --shadow: 0 16px 45px #0005;
    }
    * { box-sizing: border-box; }
    body { margin: 0; min-height: 100vh; font: 14px/1.5 Inter, ui-sans-serif, system-ui, sans-serif;
           color: var(--text); background: radial-gradient(circle at 10% 0%, #143159 0, transparent 35%), var(--bg); }
    .wrap { max-width: 1440px; margin: auto; padding: 30px; }
    .top { display: flex; justify-content: space-between; gap: 20px; align-items: end; margin-bottom: 28px; }
    h1 { margin: 0; font-size: clamp(25px, 4vw, 42px); letter-spacing: -.04em; }
    .sub { color: var(--muted); margin-top: 7px; }
    .live { display: flex; gap: 9px; align-items: center; color: var(--muted); }
    .dot { width: 10px; height: 10px; border-radius: 50%; background: var(--green); box-shadow: 0 0 16px var(--green); }
    .dot.off { background: var(--red); box-shadow: 0 0 16px var(--red); }
    .summary { display: grid; grid-template-columns: repeat(4, 1fr); gap: 14px; margin-bottom: 24px; }
    .card { background: linear-gradient(145deg, #151f38, #0e1528); border: 1px solid var(--line);
            border-radius: 18px; padding: 20px; box-shadow: var(--shadow); }
    .label { color: var(--muted); font-size: 12px; text-transform: uppercase; letter-spacing: .1em; }
    .number { font-size: 31px; font-weight: 760; margin-top: 5px; }
    .agents { display: grid; grid-template-columns: repeat(auto-fit, minmax(330px, 1fr)); gap: 16px; }
    .agent { position: relative; overflow: hidden; }
    .agent:before { content: ""; position: absolute; inset: 0 0 auto; height: 3px; background: linear-gradient(90deg, var(--blue), var(--cyan)); }
    .agent-head { display: flex; justify-content: space-between; gap: 12px; align-items: start; }
    .agent-name { font-size: 20px; font-weight: 720; }
    .meta { color: var(--muted); margin-top: 3px; font-size: 12px; }
    .badge { border: 1px solid #ffffff20; border-radius: 999px; padding: 4px 10px; font-size: 11px; text-transform: uppercase; color: var(--cyan); white-space: nowrap; }
    .badge.idle, .badge.not-reported { color: var(--muted); }
    .badge.failed { color: var(--red); }
    .metrics { display: grid; grid-template-columns: repeat(2, 1fr); gap: 10px; margin-top: 20px; }
    .metric { background: #0a1020aa; border: 1px solid #ffffff0d; border-radius: 12px; padding: 12px; }
    .metric b { display: block; font-size: 20px; margin-top: 3px; }
    .metric span { color: var(--muted); font-size: 11px; }
    .empty { padding: 38px; text-align: center; color: var(--muted); }
    .notice { margin: 18px 0; padding: 13px 16px; border-radius: 12px; border: 1px solid #fbbf2435; background: #fbbf2410; color: #fcd879; }
    .footer { color: var(--muted); margin-top: 25px; font-size: 12px; }
    @media (max-width: 800px) { .wrap { padding: 18px; } .top { display: block; } .live { margin-top: 15px; } .summary { grid-template-columns: repeat(2, 1fr); } }
    @media (max-width: 430px) { .summary { grid-template-columns: 1fr 1fr; gap: 8px; } .card { padding: 14px; } }
  </style>
</head>
<body>
<div class="wrap">
  <header class="top">
    <div><h1>SentinelOps <span style="color:var(--blue)">AI Agents</span></h1>
      <div class="sub">Real Prometheus counters · totals · last 24 hours · live status</div></div>
    <div class="live"><i id="dot" class="dot"></i><span id="connection">Connecting to Prometheus...</span></div>
  </header>
  <section class="summary">
    <div class="card"><div class="label">Agents</div><div id="agentsTotal" class="number">—</div></div>
    <div class="card"><div class="label">Total tokens</div><div id="tokensTotal" class="number">—</div></div>
    <div class="card"><div class="label">Total API requests</div><div id="requestsTotal" class="number">—</div></div>
    <div class="card"><div class="label">Requests / 24h</div><div id="requestsDay" class="number">—</div></div>
  </section>
  <div id="notice" class="notice" hidden></div>
  <section id="agents" class="agents"><div class="card empty">Loading agent metrics...</div></section>
  <div class="footer">Refreshes every 10 seconds · Source: Prometheus and persisted agent state</div>
</div>
<script>
const fmt = n => Number(n || 0).toLocaleString();
const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
function agentCard(a) {
  const status = String(a.status || 'not reported').toLowerCase();
  const quality = a.has_prometheus_data ? '' : 'idle';
  return `<article class="card agent">
    <div class="agent-head"><div><div class="agent-name">${esc(a.agent_name)}</div>
      <div class="meta">${esc(a.provider)} · ${esc(a.model)} · ${esc(a.cloud)} · ${esc(a.stage)}</div></div>
      <span class="badge ${quality || status}">${esc(status)}</span></div>
    <div class="metrics">
      <div class="metric"><span>Total tokens</span><b>${fmt(a.total_tokens)}</b></div>
      <div class="metric"><span>Prompt tokens</span><b>${fmt(a.prompt_tokens)}</b></div>
      <div class="metric"><span>Completion tokens</span><b>${fmt(a.completion_tokens)}</b></div>
      <div class="metric"><span>Total API requests</span><b>${fmt(a.requests_total)}</b></div>
      <div class="metric"><span>Requests / 24h</span><b>${fmt(a.requests_24h)}</b></div>
      <div class="metric"><span>Tokens / 24h</span><b>${fmt(a.tokens_24h)}</b></div>
    </div>
    <div class="meta" style="margin-top:16px">Decision: ${esc(a.decision)} · Last run: ${esc(a.last_run || 'not reported')}</div>
  </article>`;
}
async function refresh() {
  try {
    const response = await fetch('/api/agents', {cache: 'no-store'});
    const data = await response.json();
    const list = data.agents || [];
    const connected = !!data.prometheus_reachable;
    document.getElementById('dot').classList.toggle('off', !connected);
    document.getElementById('connection').textContent = connected ? 'Prometheus connected' : 'Prometheus unavailable';
    const real = list.filter(a => a.has_prometheus_data);
    document.getElementById('agentsTotal').textContent = fmt(real.length);
    document.getElementById('tokensTotal').textContent = fmt(list.reduce((n,a) => n + Number(a.total_tokens || 0), 0));
    document.getElementById('requestsTotal').textContent = fmt(list.reduce((n,a) => n + Number(a.requests_total || 0), 0));
    document.getElementById('requestsDay').textContent = fmt(list.reduce((n,a) => n + Number(a.requests_24h || 0), 0));
    const notice = document.getElementById('notice');
    if (!real.length) { notice.hidden = false; notice.textContent = 'Prometheus is connected, but no AI-agent report samples exist yet. Run an agent or verify POST /monitor/status and its token.'; }
    else { notice.hidden = true; }
    document.getElementById('agents').innerHTML = list.map(agentCard).join('');
  } catch (error) {
    document.getElementById('dot').classList.add('off');
    document.getElementById('connection').textContent = 'Dashboard API unavailable';
    document.getElementById('notice').hidden = false;
    document.getElementById('notice').textContent = 'Could not load agent data: ' + error;
  }
}
refresh(); setInterval(refresh, 10000);
</script>
</body></html>"""


@app.get("/")
def dashboard():
    return render_template_string(PAGE)


if __name__ == "__main__":
    print(f"AI-agent dashboard: http://{HOST}:{PORT}")
    print(f"Prometheus source: {PROMETHEUS_URL}")
    app.run(host=HOST, port=PORT, debug=False)

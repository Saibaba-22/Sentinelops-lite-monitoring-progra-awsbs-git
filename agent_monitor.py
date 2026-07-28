#!/usr/bin/env python3
"""
AI Agent Report  —  standalone AI-agent metrics scanner.
========================================================
One self-contained file. Scrape AI-agent stats from Prometheus, from a raw
Prometheus ``/metrics`` endpoint, or from a SentinelOps ``/api/agent-metrics``
JSON endpoint, and report - per agent:

    * how many AI agents exist
    * provider + model
    * status + last run
    * tokens   (prompt / completion / total)
    * requests total / per minute / per hour / per day

It works in ANY project: the only hard dependency is ``requests``. ``rich`` is
optional (used for a coloured terminal table when installed).

DATA SOURCES (pick one; defaults to --prometheus)
-------------------------------------------------
    --prometheus URL   Prometheus HTTP API  -> full data incl. per-hour/day
                                          (uses increase(metric[1h]) / [24h])
    --scrape     URL   A raw /metrics exposition endpoint (e.g. the app itself).
                       Parsed locally; per-hour/day computed from a rolling
                       local history (builds up under --watch).
    --api        URL   A SentinelOps /api/agent-metrics JSON endpoint.

EXAMPLES
--------
    python3 ai_agent_report.py --prometheus http://prometheus:9090/prometheus
    python3 ai_agent_report.py --scrape http://localhost:5000/metrics --watch 30
    python3 ai_agent_report.py --api http://localhost:5000/api/agent-metrics
    python3 ai_agent_report.py --prometheus http://... --html report.html
    python3 ai_agent_report.py --prometheus http://... --json
"""

from __future__ import annotations

import argparse
import csv
import html
import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from typing import Any

try:
    import requests
except ImportError:
    sys.exit("This tool needs the 'requests' package.\n    pip install requests")

try:
    from rich import box
    from rich.console import Console, Group
    from rich.panel import Panel
    from rich.table import Table
    from rich.text import Text

    _HAS_RICH = True
except ImportError:
    _HAS_RICH = False

console = Console() if _HAS_RICH else None

TIMEOUT = 6
DEFAULT_PROM = os.getenv("PROMETHEUS_URL", "http://prometheus:9090/prometheus").rstrip("/")
DEFAULT_HISTORY = os.path.join(os.getcwd(), ".ai_agent_history.json")
DEFAULT_LIMITS = {"rpm": 15, "tpm": 250000, "rpd": 500}


# ===========================================================================
# Helpers
# ===========================================================================
def compact(n: float) -> str:
    n = int(round(n or 0))
    if n >= 1_000_000:
        return f"{n / 1_000_000:.2f}M"
    if n >= 1_000:
        return f"{n / 1_000:.1f}K"
    return f"{n}"


def full(n: float) -> str:
    return f"{int(round(n or 0)):,}"


def _good(s: str) -> bool:
    return (s or "").lower() in {"approved", "healthy", "success", "completed", "passed", "ok"}


def _bad(s: str) -> bool:
    return (s or "").lower() in {"failed", "error", "blocked", "rejected", "denied"}


def status_style(s: str) -> str:
    s = (s or "").lower()
    if s in {"approved", "healthy", "success", "completed", "passed", "ok"}:
        return "bold green"
    if s in {"failed", "error", "blocked", "rejected", "denied"}:
        return "bold red"
    if s in {"running", "in_progress", "pending", "queued"}:
        return "bold cyan"
    if s in {"warning", "degraded"}:
        return "bold yellow"
    return "dim"


def status_color(s: str) -> str:
    style = status_style(s)
    return {
        "bold green": "#4ade80", "bold red": "#fb7185", "bold cyan": "#56b4ff",
        "bold yellow": "#fbbf24", "dim": "#8ea0c0",
    }.get(style, "#8ea0c0")


# ===========================================================================
# Source 1: Prometheus HTTP API
# ===========================================================================
def _prom_query(base: str, query: str) -> list[dict[str, Any]]:
    try:
        r = requests.get(f"{base}/api/v1/query", params={"query": query}, timeout=TIMEOUT)
        r.raise_for_status()
        body = r.json()
        if body.get("status") != "success":
            return []
        return body.get("data", {}).get("result", []) or []
    except (requests.RequestException, ValueError, TypeError):
        return []


def _prom_up(base: str) -> bool:
    return bool(_prom_query(base, "up"))


def _prom_vec(base: str, query: str) -> dict[str, float]:
    out: dict[str, float] = {}
    for item in _prom_query(base, query):
        name = item.get("metric", {}).get("agent_name")
        if not name:
            continue
        try:
            out[name] = float(item.get("value", [0, 0])[1])
        except (IndexError, TypeError, ValueError):
            out[name] = 0.0
    return out


def _prom_labels(base: str, query: str) -> dict[str, dict[str, str]]:
    out: dict[str, dict[str, str]] = {}
    for item in _prom_query(base, query):
        labels = item.get("metric", {})
        name = labels.get("agent_name")
        if name:
            out[name] = labels
    return out


def collect_prometheus(base: str) -> tuple[list[dict[str, Any]], str]:
    connected = _prom_up(base)
    tot_tok = _prom_vec(base, "sum by (agent_name) (agent_token_usage_total)")
    pr_tok = _prom_vec(base, "sum by (agent_name) (agent_prompt_tokens_total)")
    co_tok = _prom_vec(base, "sum by (agent_name) (agent_completion_tokens_total)")
    req_tot = _prom_vec(base, "sum by (agent_name) (agent_api_calls_total)")
    req_min = _prom_vec(base, "sum by (agent_name) (increase(agent_api_calls_total[1m]))")
    req_hour = _prom_vec(base, "sum by (agent_name) (increase(agent_api_calls_total[1h]))")
    req_day = _prom_vec(base, "sum by (agent_name) (increase(agent_api_calls_total[24h]))")
    tok_min = _prom_vec(base, "sum by (agent_name) (increase(agent_token_usage_total[1m]))")
    tok_day = _prom_vec(base, "sum by (agent_name) (increase(agent_token_usage_total[24h]))")
    last_runs = _prom_vec(base, "max by (agent_name) (agent_last_run_timestamp_seconds)")
    models = _prom_labels(base, "agent_model_info")
    states = _prom_labels(base, "agent_state == 1")

    names = set(tot_tok) | set(req_tot) | set(models) | set(states)
    rows: list[dict[str, Any]] = []
    for name in sorted(names):
        mi, si = models.get(name, {}), states.get(name, {})
        lr = last_runs.get(name, 0)
        last_run = (
            datetime.fromtimestamp(float(lr), tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
            if lr else "—"
        )
        rows.append({
            "agent": name,
            "provider": mi.get("provider", "—"),
            "model": mi.get("model", "—"),
            "stage": si.get("stage", mi.get("stage", "—")),
            "cloud": si.get("cloud", mi.get("cloud", "—")),
            "status": si.get("state", "—"),
            "prompt_tokens": int(round(pr_tok.get(name, 0))),
            "completion_tokens": int(round(co_tok.get(name, 0))),
            "total_tokens": int(round(tot_tok.get(name, 0))),
            "requests_total": int(round(req_tot.get(name, 0))),
            "requests_minute": int(round(req_min.get(name, 0))),
            "requests_hour": int(round(req_hour.get(name, 0))),
            "requests_day": int(round(req_day.get(name, 0))),
            "tokens_minute": int(round(tok_min.get(name, 0))),
            "tokens_day": int(round(tok_day.get(name, 0))),
            "last_run": last_run,
        })
    state = "prometheus connected" if connected else "prometheus unreachable"
    return rows, state


# ===========================================================================
# Source 2: raw /metrics exposition scrape (parsed locally)
# ===========================================================================
_LABEL_RE = re.compile(r'(\w+)="((?:[^"\\]|\\.)*)"')


def parse_exposition(text: str) -> dict[str, list[dict[str, Any]]]:
    """Parse Prometheus exposition text -> {metric_name: [{labels, value}]}."""
    parsed: dict[str, list[dict[str, Any]]] = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "{" in line:
            name, rest = line.split("{", 1)
            brace = rest.rfind("}")
            labels_str, value_str = rest[:brace], rest[brace + 1:].strip()
            labels = {k: v for k, v in _LABEL_RE.findall(labels_str)}
        else:
            parts = line.split()
            if len(parts) < 2:
                continue
            name, value_str, labels = parts[0], parts[1], {}
        try:
            value = float(value_str)
        except ValueError:
            continue
        parsed.setdefault(name.strip(), []).append({"labels": labels, "value": value})
    return parsed


def _scrape_sum(parsed: dict, metric: str) -> dict[str, float]:
    out: dict[str, float] = {}
    for entry in parsed.get(metric, []):
        name = entry["labels"].get("agent_name")
        if name:
            out[name] = out.get(name, 0.0) + entry["value"]
    return out


def _scrape_first_label(parsed: dict, metric: str, want_value: float | None = None) -> dict[str, dict[str, str]]:
    out: dict[str, dict[str, str]] = {}
    for entry in parsed.get(metric, []):
        if want_value is not None and entry["value"] != want_value:
            continue
        name = entry["labels"].get("agent_name")
        if name:
            out[name] = entry["labels"]
    return out


def _load_history(path: str) -> dict[str, Any]:
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError, TypeError):
        return {}


def _save_history(path: str, hist: dict[str, Any]) -> None:
    try:
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(hist, fh)
    except OSError:
        pass


def _rate_from_history(hist: dict, key: str, current: float, now: float):
    prev = hist.get(key)
    if not prev or "ts" not in prev:
        return None
    elapsed = now - prev.get("ts", now)
    if elapsed <= 0:
        return None
    delta = max(0.0, current - prev.get("value", current))
    return {
        "per_minute": delta / (elapsed / 60.0),
        "per_hour": delta / (elapsed / 3600.0),
        "per_day": delta / (elapsed / 86400.0),
        "delta": delta,
        "elapsed": elapsed,
    }


def collect_scrape(url: str, history_path: str) -> tuple[list[dict[str, Any]], str]:
    try:
        r = requests.get(url, timeout=TIMEOUT)
        r.raise_for_status()
        text = r.text
    except (requests.RequestException, ValueError) as exc:
        return [], f"scrape failed: {exc}"

    parsed = parse_exposition(text)
    tot_tok = _scrape_sum(parsed, "agent_token_usage_total")
    pr_tok = _scrape_sum(parsed, "agent_prompt_tokens_total")
    co_tok = _scrape_sum(parsed, "agent_completion_tokens_total")
    req_tot = _scrape_sum(parsed, "agent_api_calls_total")
    last_runs = _scrape_sum(parsed, "agent_last_run_timestamp_seconds")
    models = _scrape_first_label(parsed, "agent_model_info")
    states = _scrape_first_label(parsed, "agent_state", want_value=1.0)

    names = set(tot_tok) | set(req_tot) | set(models) | set(states)
    now = time.time()
    hist = _load_history(history_path)
    rows: list[dict[str, Any]] = []
    for name in sorted(names):
        mi, si = models.get(name, {}), states.get(name, {})
        lr = last_runs.get(name, 0)
        last_run = (
            datetime.fromtimestamp(float(lr), tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
            if lr else "—"
        )
        rt = req_tot.get(name, 0)
        tt = tot_tok.get(name, 0)
        req_rate = _rate_from_history(hist, f"{name}|requests", rt, now)
        tok_rate = _rate_from_history(hist, f"{name}|tokens", tt, now)
        rows.append({
            "agent": name,
            "provider": mi.get("provider", "—"),
            "model": mi.get("model", "—"),
            "stage": si.get("stage", mi.get("stage", "—")),
            "cloud": si.get("cloud", mi.get("cloud", "—")),
            "status": si.get("state", "—"),
            "prompt_tokens": int(round(pr_tok.get(name, 0))),
            "completion_tokens": int(round(co_tok.get(name, 0))),
            "total_tokens": int(round(tt)),
            "requests_total": int(round(rt)),
            "requests_minute": int(round(req_rate["per_minute"])) if req_rate else 0,
            "requests_hour": int(round(req_rate["per_hour"])) if req_rate else 0,
            "requests_day": int(round(req_rate["per_day"])) if req_rate else 0,
            "tokens_minute": int(round(tok_rate["per_minute"])) if tok_rate else 0,
            "tokens_day": int(round(tok_rate["per_day"])) if tok_rate else 0,
            "last_run": last_run,
            "_has_rate": bool(req_rate),
        })
        # update history for next run
        hist[f"{name}|requests"] = {"value": rt, "ts": now}
        hist[f"{name}|tokens"] = {"value": tt, "ts": now}
    _save_history(history_path, hist)
    state = f"scraped {url} ({len(names)} agents)"
    return rows, state


# ===========================================================================
# Source 3: SentinelOps /api/agent-metrics JSON
# ===========================================================================
def collect_api(url: str) -> tuple[list[dict[str, Any]], str]:
    try:
        r = requests.get(url, timeout=TIMEOUT)
        r.raise_for_status()
        data = r.json()
    except (requests.RequestException, ValueError) as exc:
        return [], f"api failed: {exc}"
    rows: list[dict[str, Any]] = []
    for a in data.get("agents", []):
        rows.append({
            "agent": a.get("agent_name", "—"),
            "provider": a.get("provider", "—"),
            "model": a.get("model", "—"),
            "stage": a.get("stage", "—"),
            "cloud": a.get("cloud", "—"),
            "status": a.get("status", "—"),
            "prompt_tokens": int(a.get("prompt_tokens", 0) or 0),
            "completion_tokens": int(a.get("completion_tokens", 0) or 0),
            "total_tokens": int(a.get("total_tokens", 0) or 0),
            "requests_total": int(a.get("requests_total", 0) or 0),
            "requests_minute": int(a.get("requests_minute", 0) or 0),
            "requests_hour": int(a.get("requests_hour", 0) or 0),
            "requests_day": int(a.get("requests_day", 0) or 0),
            "tokens_minute": int(a.get("tokens_minute", 0) or 0),
            "tokens_day": int(a.get("tokens_day", 0) or 0),
            "last_run": a.get("last_run") or "—",
        })
    conn = data.get("prometheus_connected")
    state = f"api {url} · prometheus {'connected' if conn else 'unavailable'}"
    return rows, state


# ===========================================================================
# Rendering — terminal (rich) + plain
# ===========================================================================
COLUMNS = [
    ("Agent", "agent", 16), ("Provider", "provider", 11), ("Model", "model", 22),
    ("Tokens", "total_tokens", 9), ("Tok/Day", "tokens_day", 8),
    ("Req/Min", "requests_minute", 8), ("Req/Hour", "requests_hour", 9),
    ("Req/Day", "requests_day", 8), ("Req Total", "requests_total", 9),
    ("Status", "status", 12), ("Last run", "last_run", 21),
]


def _cell(row, key):
    if key in {"total_tokens", "tokens_day", "requests_minute", "requests_hour",
               "requests_day", "requests_total"}:
        return compact(row.get(key, 0))
    return str(row.get(key, "—"))


def render_rich(rows, state, stamp):
    table = Table(box=box.ROUNDED, header_style="bold #56b4ff", border_style="#263452",
                  expand=True, pad_edge=False)
    for title, _, _ in COLUMNS:
        table.add_column(title, style="#cfe0ff" if title != "Agent" else "bold white",
                         no_wrap=title in {"Agent", "Status", "Last run", "Model"})
    for r in rows:
        cells = []
        for title, key, _ in COLUMNS:
            if key == "status":
                cells.append(Text(_cell(r, key), style=status_style(r["status"])))
            else:
                cells.append(_cell(r, key))
        table.add_row(*cells)

    summary = (
        f"[bold]{len(rows)}[/] AI agents   ·   "
        f"[bold]tokens[/] {full(sum(r['total_tokens'] for r in rows))}   ·   "
        f"[bold]requests[/] {full(sum(r['requests_total'] for r in rows))}   ·   "
        f"[bold]req/day[/] {full(sum(r['requests_day'] for r in rows))}"
    )
    header = Panel(
        Group(
            Text.from_markup("[bold cyan]AI Agent Report[/]"),
            Text(f"{stamp}   ·   {state}", style="dim"),
            Text.from_markup(summary),
        ),
        border_style="#263452", box=box.ROUNDED,
    )
    console.print(header)
    console.print(table if rows else Text("(no agents found)", style="dim"))


def render_plain(rows, state, stamp):
    print(f"AI Agent Report   ·   {stamp}")
    print(f"{state}")
    print(f"AI agents: {len(rows)}   tokens: {full(sum(r['total_tokens'] for r in rows))}   "
          f"requests: {full(sum(r['requests_total'] for r in rows))}   "
          f"req/day: {full(sum(r['requests_day'] for r in rows))}")
    print("  ".join(t.ljust(w) for t, _, w in COLUMNS))
    print("  ".join("-" * w for _, _, w in COLUMNS))
    for r in rows:
        print("  ".join(_cell(r, k).ljust(w)[:w] for _, k, w in COLUMNS))


# ===========================================================================
# Rendering — standalone HTML
# ===========================================================================
_CSS = """
:root{--bg:#070b18;--panel:#11182b;--line:#263452;--text:#edf4ff;--muted:#8ea0c0;--blue:#56b4ff;--cyan:#53e0d0;--green:#4ade80;--red:#fb7185}
*{box-sizing:border-box}body{margin:0;min-height:100vh;font:14px/1.5 system-ui,sans-serif;color:var(--text);
background:radial-gradient(circle at 12% 0%,#143159 0,transparent 38%),var(--bg);padding:28px}
.wrap{max-width:1280px;margin:auto}.top{display:flex;justify-content:space-between;align-items:end;gap:18px;margin-bottom:20px;flex-wrap:wrap}
h1{margin:0;font-size:clamp(22px,3.4vw,34px);letter-spacing:-.04em}.sub{color:var(--muted);margin-top:4px}
.cards{display:grid;grid-template-columns:repeat(4,1fr);gap:13px;margin-bottom:20px}
.card{background:linear-gradient(145deg,#151f38,#0e1528);border:1px solid var(--line);border-radius:15px;padding:16px}
.card .l{color:var(--muted);font-size:11px;text-transform:uppercase;letter-spacing:.1em}.card .n{font-size:28px;font-weight:800;margin-top:3px}
.tbl{width:100%;border-collapse:separate;border-spacing:0;background:linear-gradient(145deg,#121b32,#0d1426);border:1px solid var(--line);border-radius:15px;overflow:hidden}
.tbl th,.tbl td{padding:12px 13px;text-align:left;border-bottom:1px solid #1d2942;white-space:nowrap}
.tbl thead th{color:var(--blue);font-size:11px;text-transform:uppercase;letter-spacing:.07em;background:#0c1426}
.tbl tbody tr:last-child td{border-bottom:none}.tbl tbody tr:hover{background:#ffffff08}
.tbl td.r,.tbl th.r{text-align:right}.ag{font-weight:700;color:#fff}.mut{color:var(--muted)}.mod{color:var(--cyan)}
.badge{display:inline-block;border:1px solid #ffffff25;border-radius:999px;padding:3px 10px;font-size:11px;font-weight:600}
.foot{color:var(--muted);margin-top:16px;font-size:12px}
@media(max-width:900px){.cards{grid-template-columns:repeat(2,1fr)}.tbl{font-size:12px}}
"""


def render_html(rows, state, stamp) -> str:
    def h(s):
        return html.escape(str(s))

    body = []
    for r in rows:
        col = status_color(r["status"])
        body.append(f"""<tr>
<td class="ag">{h(r['agent'])}</td>
<td class="mut">{h(r['provider'])}</td>
<td class="mod">{h(r['model'])}</td>
<td class="r">{h(compact(r['total_tokens']))}</td>
<td class="r">{h(compact(r['tokens_day']))}</td>
<td class="r">{h(compact(r['requests_minute']))}</td>
<td class="r">{h(compact(r['requests_hour']))}</td>
<td class="r">{h(compact(r['requests_day']))}</td>
<td class="r">{h(compact(r['requests_total']))}</td>
<td><span class="badge" style="color:{col};border-color:{col}55">{h(r['status'])}</span></td>
<td class="mut">{h(r['last_run'])}</td>
</tr>""")
    rows_html = "\n".join(body) or '<tr><td colspan="11" style="text-align:center;color:var(--muted);padding:28px">No AI agents found.</td></tr>'

    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>AI Agent Report</title><style>{_CSS}</style></head><body><div class="wrap">
<div class="top"><div><h1>AI Agent <span style="color:var(--blue)">Report</span></h1>
<div class="sub">{len(rows)} agents · tokens · requests per minute / hour / day · model · provider</div></div>
<div class="sub">{h(state)}</div></div>
<div class="cards">
<div class="card"><div class="l">AI agents</div><div class="n">{len(rows)}</div></div>
<div class="card"><div class="l">Total tokens</div><div class="n">{h(compact(sum(r['total_tokens'] for r in rows)))}</div></div>
<div class="card"><div class="l">Requests / day</div><div class="n">{h(compact(sum(r['requests_day'] for r in rows)))}</div></div>
<div class="card"><div class="l">Requests total</div><div class="n">{h(compact(sum(r['requests_total'] for r in rows)))}</div></div>
</div>
<table class="tbl"><thead><tr>
<th>Agent</th><th>Provider</th><th>Model</th>
<th class="r">Tokens</th><th class="r">Tok/Day</th>
<th class="r">Req/Min</th><th class="r">Req/Hour</th><th class="r">Req/Day</th><th class="r">Req Total</th>
<th>Status</th><th>Last run</th>
</tr></thead><tbody>
{rows_html}
</tbody></table>
<div class="foot">Generated {h(stamp)} · {h(state)}</div>
</div></body></html>"""


def write_csv(path: str, rows: list[dict[str, Any]]) -> None:
    fields = ["agent", "provider", "model", "stage", "cloud", "status",
              "prompt_tokens", "completion_tokens", "total_tokens",
              "tokens_minute", "tokens_day",
              "requests_total", "requests_minute", "requests_hour", "requests_day", "last_run"]
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=fields)
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, "") for k in fields})


# ===========================================================================
# Main
# ===========================================================================
def main() -> int:
    p = argparse.ArgumentParser(description="Scan and report AI-agent stats from Prometheus or /metrics.")
    src = p.add_mutually_exclusive_group()
    src.add_argument("--prometheus", default=DEFAULT_PROM, help=f"Prometheus base URL (default: {DEFAULT_PROM})")
    src.add_argument("--scrape", metavar="URL", help="Raw /metrics exposition endpoint to parse")
    src.add_argument("--api", metavar="URL", help="SentinelOps /api/agent-metrics JSON endpoint")
    p.add_argument("--watch", type=float, metavar="SEC", help="re-scan every SEC seconds")
    p.add_argument("--history", default=DEFAULT_HISTORY, help=f"local history file for scrape rates (default: {DEFAULT_HISTORY})")
    p.add_argument("--html", metavar="FILE", help="write a standalone HTML report")
    p.add_argument("--json", action="store_true", help="print JSON and exit")
    p.add_argument("--csv", metavar="FILE", help="write CSV and exit")
    p.add_argument("--plain", action="store_true", help="force plain text table")
    args = p.parse_args()

    use_rich = _HAS_RICH and not args.plain

    def run_once():
        if args.scrape:
            rows, state = collect_scrape(args.scrape, args.history)
        elif args.api:
            rows, state = collect_api(args.api)
        else:
            rows, state = collect_prometheus(args.prometheus)
        stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
        return rows, state, stamp

    rows, state, stamp = run_once()

    if args.json:
        print(json.dumps({"generated_at": stamp, "state": state, "agents": rows,
                          "agent_count": len(rows)}, indent=2, default=str))
        return 0
    if args.csv:
        write_csv(args.csv, rows)
        print(f"Wrote {len(rows)} agents to {args.csv}")
        return 0
    if args.html:
        with open(args.html, "w", encoding="utf-8") as fh:
            fh.write(render_html(rows, state, stamp))
        print(f"Wrote HTML report -> {args.html}")
        return 0

    def render(rows, state, stamp):
        if args.watch:
            os.system("cls" if os.name == "nt" else "clear")
        if use_rich:
            render_rich(rows, state, stamp)
        else:
            render_plain(rows, state, stamp)
            if not _HAS_RICH:
                print("\n(tip: pip install rich for a styled table)")

    render(rows, state, stamp)
    if args.watch:
        try:
            while True:
                time.sleep(args.watch)
                rows, state, stamp = run_once()
                render(rows, state, stamp)
        except KeyboardInterrupt:
            print("\nStopped.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

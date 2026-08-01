/* SentinelOps-Lite — standalone monitoring dashboard
 * Fetches the live JSON snapshot from /api/status every REFRESH_MS and renders
 * stats, SVG gauges, progress bars, health badges and rolling charts.
 * Works without Prometheus in the loop (history is kept client-side).
 */
(function () {
  "use strict";

  const REFRESH_MS = 10000;
  const MAX_POINTS = 40;

  const AGENT_STATE_NUM = {
    idle: 0, running: 1, waiting: 2, approved: 3, rejected: 4, failed: 5,
  };

  const state = { history: [], lastTotalRequests: null };

  // ---- helpers ----------------------------------------------------------
  const $ = (id) => document.getElementById(id);
  const clamp = (v, lo, hi) => Math.max(lo, Math.min(hi, v));

  function fmtNum(n) {
    if (n === null || n === undefined || isNaN(n)) return "—";
    if (n >= 1e9) return (n / 1e9).toFixed(2) + "B";
    if (n >= 1e6) return (n / 1e6).toFixed(2) + "M";
    if (n >= 1e3) return (n / 1e3).toFixed(2) + "K";
    return Number(n).toFixed(n % 1 === 0 ? 0 : 2);
  }
  function fmtDuration(s) {
    s = Math.floor(s || 0);
    const d = Math.floor(s / 86400); s -= d * 86400;
    const h = Math.floor(s / 3600); s -= h * 3600;
    const m = Math.floor(s / 60); s -= m * 60;
    return `${d}d ${h}h ${m}m ${s}s`;
  }
  function healthClass(v, warn, crit) {
    if (v >= crit) return "crit";
    if (v >= warn) return "warn";
    return "ok";
  }
  function gaugeColor(v, warn, crit) {
    if (v >= crit) return getComputedStyle(document.documentElement).getPropertyValue("--red");
    if (v >= warn) return getComputedStyle(document.documentElement).getPropertyValue("--amber");
    return getComputedStyle(document.documentElement).getPropertyValue("--emerald");
  }

  // ---- SVG gauge --------------------------------------------------------
  function setGauge(prefix, percent, warn, crit) {
    const pct = clamp(percent, 0, 100);
    const circle = $(prefix + "-fill");
    const radius = circle ? circle.r.baseVal.value : 0;
    const circ = 2 * Math.PI * radius;
    circle.style.strokeDashoffset = circ * (1 - pct / 100);
    circle.style.stroke = gaugeColor(pct, warn, crit).trim();
    const valEl = $(prefix + "-value");
    if (valEl) valEl.textContent = pct.toFixed(0) + "%";
  }

  // ---- charts -----------------------------------------------------------
  let charts = {};
  function makeChart(id, datasets) {
    const ctx = $(id).getContext("2d");
    return new Chart(ctx, {
      type: "line",
      data: { labels: [], datasets },
      options: {
        responsive: true, maintainAspectRatio: false, animation: false,
        plugins: { legend: { labels: { color: "#94a3b8", boxWidth: 12 } } },
        scales: {
          x: { ticks: { color: "#64748b", maxTicksLimit: 6 }, grid: { color: "rgba(255,255,255,.04)" } },
          y: { ticks: { color: "#64748b" }, grid: { color: "rgba(255,255,255,.04)" }, beginAtZero: true },
        },
      },
    });
  }
  function pushPoint(chart, values) {
    const label = new Date().toLocaleTimeString();
    chart.data.labels.push(label);
    values.forEach((v, i) => chart.data.datasets[i].data.push(v));
    if (chart.data.labels.length > MAX_POINTS) {
      chart.data.labels.shift();
      chart.data.datasets.forEach((d) => d.data.shift());
    }
    chart.update("none");
  }

  function initCharts() {
    Chart.defaults.color = "#94a3b8";
    charts.traffic = makeChart("chart-traffic", [
      { label: "Requests/sec", data: [], borderColor: "#3b82f6", backgroundColor: "rgba(59,130,246,.15)", fill: true, tension: 0.35, pointRadius: 0 },
    ]);
    charts.sys = makeChart("chart-sys", [
      { label: "CPU %", data: [], borderColor: "#22d3ee", tension: 0.35, pointRadius: 0 },
      { label: "Memory %", data: [], borderColor: "#a855f7", tension: 0.35, pointRadius: 0 },
    ]);
    charts.latency = makeChart("chart-latency", [
      { label: "Avg resp (s)", data: [], borderColor: "#10b981", backgroundColor: "rgba(16,185,129,.15)", fill: true, tension: 0.35, pointRadius: 0 },
    ]);
    charts.agent = makeChart("chart-agent", [
      { label: "Agent state", data: [], borderColor: "#f59e0b", stepped: true, tension: 0, pointRadius: 0 },
    ]);
  }

  // ---- main update ------------------------------------------------------
  function update(data) {
    const app = data.application, sys = data.system, agent = data.agent, dep = data.deployment;

    // Requests/sec from delta
    let rps = 0;
    if (state.lastTotalRequests !== null) {
      rps = (app.total_requests - state.lastTotalRequests) / (REFRESH_MS / 1000);
    }
    state.lastTotalRequests = app.total_requests;

    // Stats
    $("stat-reqps").textContent = fmtNum(rps);
    $("stat-err").textContent = (app.error_rate * 100).toFixed(2) + "%";
    $("stat-cpu").textContent = sys.cpu_usage_percent.toFixed(1) + "%";
    $("stat-mem").textContent = sys.memory_usage_percent.toFixed(1) + "%";
    $("stat-agent").textContent = agent.status;
    $("stat-uptime").textContent = fmtDuration(app.uptime_seconds);

    // Progress bars
    $("bar-cpu").style.width = clamp(sys.cpu_usage_percent, 0, 100) + "%";
    $("bar-mem").style.width = clamp(sys.memory_usage_percent, 0, 100) + "%";
    $("bar-disk").style.width = clamp(sys.disk_usage_percent, 0, 100) + "%";
    $("bar-err").style.width = clamp(app.error_rate * 100, 0, 100) + "%";

    // Gauges
    setGauge("gauge-cpu", sys.cpu_usage_percent, 70, 85);
    setGauge("gauge-mem", sys.memory_usage_percent, 70, 85);
    setGauge("gauge-disk", sys.disk_usage_percent, 80, 90);
    setGauge("gauge-err", app.error_rate * 100, 1, 5);

    // Badges
    setBadge("badge-app", app.health, app.health === "ok" ? "ok" : "crit");
    const agentBadge = healthClass(AGENT_STATE_NUM[agent.status.toLowerCase()] || 0, 4, 5); // rejected/failed -> warn/crit
    const agentCls = agent.status.toLowerCase() === "failed" ? "crit"
      : (agent.status.toLowerCase() === "rejected" || agent.status.toLowerCase() === "idle") ? "idle" : "ok";
    setBadge("badge-agent", agent.status, agentCls);
    setBadge("badge-container", dep.container_status ? "Healthy" : "Unhealthy", dep.container_status ? "ok" : "crit");

    // Charts
    pushPoint(charts.traffic, [rps]);
    pushPoint(charts.sys, [sys.cpu_usage_percent, sys.memory_usage_percent]);
    pushPoint(charts.latency, [app.avg_response_time_seconds || 0]);
    pushPoint(charts.agent, [AGENT_STATE_NUM[agent.status.toLowerCase()] ?? 0]);

    // Meta
    $("last-updated").textContent = "Updated " + new Date().toLocaleTimeString();
    setConnection(true);
  }

  function setBadge(id, text, cls) {
    const el = $(id);
    if (!el) return;
    el.textContent = text;
    el.className = "badge " + cls;
  }
  function setConnection(ok) {
    const dot = $("conn-dot");
    const txt = $("conn-text");
    if (ok) {
      dot.className = "dot pulsing";
      txt.textContent = "Live";
    } else {
      dot.className = "dot";
      dot.style.background = "var(--red)";
      txt.textContent = "Disconnected";
    }
  }

  async function tick() {
    try {
      const res = await fetch("/api/status", { cache: "no-store" });
      if (!res.ok) throw new Error("HTTP " + res.status);
      const data = await res.json();
      update(data);
    } catch (e) {
      setConnection(false);
      console.warn("Status fetch failed:", e);
    }
  }

  document.addEventListener("DOMContentLoaded", function () {
    initCharts();
    tick();
    setInterval(tick, REFRESH_MS);
  });
})();

import os
import sys
from flask import Flask, Blueprint, jsonify
from jinja2 import DictLoader

# ── FLASK APPLICATION SETUP ────────────────────────────────────
application = Flask(__name__)
application.jinja_loader = DictLoader({
    'index.html': '''
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>SentinelOps-Lite Dashboard</title>
    <style>
        :root {
            --primary: #2e7d32;
            --secondary: #1b5e20;
            --accent: #4caf50;
            --light: #f0fff0;
            --card-bg: #ffffff;
            --shadow: 0 4px 20px rgba(0,0,0,0.08);
            --pulse-color: #4caf50;
        }
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }
        body {
            background: linear-gradient(135deg, #f0fff0 0%, #e8f5e9 100%);
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            color: #333;
            line-height: 1.6;
            padding: 20px;
        }
        .container {
            max-width: 1400px;
            margin: 0 auto;
        }
        header {
            text-align: center;
            padding: 30px 20px;
            margin-bottom: 30px;
            background: rgba(255, 255, 255, 0.85);
            border-radius: 20px;
            box-shadow: var(--shadow);
            position: relative;
            overflow: hidden;
        }
        header::before {
            content: "";
            position: absolute;
            top: -50%;
            left: -50%;
            width: 200%;
            height: 200%;
            background: radial-gradient(circle, rgba(76, 175, 80, 0.1) 0%, transparent 70%);
            z-index: 0;
        }
        h1 {
            font-size: 2.8rem;
            margin-bottom: 15px;
            color: var(--secondary);
            position: relative;
            z-index: 1;
            display: flex;
            align-items: center;
            justify-content: center;
            gap: 15px;
        }
        .subtitle {
            font-size: 1.3rem;
            color: #555;
            max-width: 700px;
            margin: 0 auto;
            position: relative;
            z-index: 1;
        }
        .status-badge {
            display: inline-flex;
            align-items: center;
            gap: 8px;
            background: rgba(76, 175, 80, 0.15);
            color: var(--primary);
            padding: 5px 15px;
            border-radius: 20px;
            font-weight: 600;
            margin-top: 15px;
            position: relative;
            z-index: 1;
        }
        .pulse {
            display: inline-block;
            width: 12px;
            height: 12px;
            background: var(--pulse-color);
            border-radius: 50%;
            position: relative;
        }
        .pulse::after {
            content: "";
            position: absolute;
            width: 100%;
            height: 100%;
            border-radius: 50%;
            background: var(--pulse-color);
            animation: pulse 2s infinite;
        }
        @keyframes pulse {
            0% { box-shadow: 0 0 0 0 rgba(76, 175, 80, 0.7); }
            70% { box-shadow: 0 0 0 10px rgba(76, 175, 80, 0); }
            100% { box-shadow: 0 0 0 0 rgba(76, 175, 80, 0); }
        }
        .grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));
            gap: 25px;
            margin-bottom: 30px;
        }
        .card {
            background: var(--card-bg);
            border-radius: 20px;
            box-shadow: var(--shadow);
            padding: 25px;
            transition: transform 0.3s ease, box-shadow 0.3s ease;
        }
        .card:hover {
            transform: translateY(-5px);
            box-shadow: 0 6px 25px rgba(0,0,0,0.12);
        }
        .card-title {
            display: flex;
            align-items: center;
            gap: 12px;
            font-size: 1.6rem;
            margin-bottom: 20px;
            color: var(--secondary);
            padding-bottom: 15px;
            border-bottom: 2px solid #e8f5e9;
        }
        .card-title i {
            font-size: 1.8rem;
        }
        .pipeline-name {
            font-weight: 700;
            color: var(--primary);
            font-size: 1.4rem;
            margin: 10px 0;
        }
        .pipeline-desc {
            background: #e8f5e9;
            padding: 12px;
            border-radius: 12px;
            margin-top: 10px;
            font-style: italic;
        }
        .characteristics-list {
            padding-left: 25px;
            margin-top: 15px;
        }
        .characteristics-list li {
            margin-bottom: 10px;
            line-height: 1.5;
        }
        .file-tree {
            background: #f8fdf8;
            padding: 20px;
            border-radius: 15px;
            font-family: monospace;
            line-height: 1.7;
            margin-top: 15px;
            border-left: 4px solid var(--accent);
            white-space: pre-wrap;
            font-size: 0.95rem;
        }
        .agents-table {
            width: 100%;
            border-collapse: collapse;
            margin-top: 15px;
            box-shadow: 0 2px 10px rgba(0,0,0,0.05);
        }
        .agents-table th {
            background: var(--primary);
            color: white;
            text-align: left;
            padding: 16px 12px;
            font-weight: 600;
        }
        .agents-table td {
            padding: 14px 12px;
            border-bottom: 1px solid #eee;
        }
        .agents-table tr:nth-child(even) {
            background-color: #f9fbf9;
        }
        .agents-table tr:hover {
            background-color: #f1f9f1;
        }
        .metric-container {
            margin-top: 8px;
        }
        .bar-container {
            height: 10px;
            background: #e0e0e0;
            border-radius: 5px;
            margin: 5px 0 3px;
            overflow: hidden;
            position: relative;
        }
        .bar-fill {
            height: 100%;
            background: linear-gradient(to right, var(--accent), var(--secondary));
            border-radius: 5px;
            transition: width 0.5s ease;
        }
        .bar-label {
            font-size: 0.85rem;
            color: #555;
            display: flex;
            justify-content: space-between;
        }
        .status-indicator {
            display: flex;
            align-items: center;
            gap: 8px;
            font-weight: 500;
        }
        .status-active {
            color: var(--pulse-color);
        }
        .time-window {
            font-size: 0.8rem;
            color: #666;
            margin-top: 3px;
            font-style: italic;
        }
        footer {
            text-align: center;
            padding: 25px;
            margin-top: 20px;
            color: var(--secondary);
            font-size: 0.95rem;
            background: rgba(255, 255, 255, 0.7);
            border-radius: 15px;
            box-shadow: var(--shadow);
        }
        @media (max-width: 768px) {
            .grid {
                grid-template-columns: 1fr;
            }
            h1 {
                font-size: 2.3rem;
            }
            .card {
                padding: 20px;
            }
            .agents-table {
                font-size: 0.85rem;
            }
            .agents-table th, .agents-table td {
                padding: 10px 8px;
            }
        }
    </style>
</head>
<body>
    <div class="container">
        <header>
            <h1>🤖 SentinelOps-Lite Dashboard</h1>
            <p class="subtitle">Real-time monitoring of AI agents, deployment pipelines, and resource utilization</p>
            <div class="status-badge">
                <span class="pulse"></span> System Operational
            </div>
        </header>

        <div class="grid">
            <!-- Pipeline Info Card -->
            <div class="card">
                <div class="card-title">🏗️ Deployment Pipeline</div>
                <div class="pipeline-name">SentinelOps-Lite-CI</div>
                <div><strong>Platform:</strong> GitHub Actions</div>
                <div class="pipeline-desc">Validates AI agent health, security scans, and performance metrics during pre-deployment validation</div>
            </div>

            <!-- AI Agent Characteristics Card -->
            <div class="card">
                <div class="card-title">🔍 Agent Identification</div>
                <p>AI agents are uniquely identified using:</p>
                <ul class="characteristics-list">
                    <li>✅ SHA-256 hash of agent script content</li>
                    <li>✅ Provider API key fingerprint (salted hash)</li>
                    <li>✅ Runtime environment signature</li>
                    <li>✅ Deployment timestamp watermark</li>
                </ul>
                <p style="margin-top: 15px; font-weight: 500; color: var(--primary);">
                    Ensures tamper-evident, non-repudiable agent tracking across environments
                </p>
            </div>

            <!-- File Structure Card -->
            <div class="card">
                <div class="card-title">📁 Project Structure</div>
                <div class="file-tree">
sentinelops-lite/
├── app.py                     # Main Flask entrypoint (routes)
├── agent_monitor.py           # Monitoring core + embedded dashboard
├── .github/workflows/
│   └── ci.yml                # GitHub Actions pipeline definition
├── requirements.txt
└── README.md
                </div>
                <p style="margin-top: 15px; font-style: italic; color: #555;">
                    <strong>Note:</strong> Templates embedded directly in agent_monitor.py (no external assets)
                </p>
            </div>
        </div>

        <!-- AI Agents Table -->
        <div class="card">
            <div class="card-title">📊 AI Agent Metrics</div>
            <table class="agents-table">
                <thead>
                    <tr>
                        <th>Status</th>
                        <th>Agent Script</th>
                        <th>Provider</th>
                        <th>Model</th>
                        <th>Purpose</th>
                        <th>Tokens (Used/Total)</th>
                        <th>Hourly Requests</th>
                        <th>Daily Requests</th>
                    </tr>
                </thead>
                <tbody>
                    <tr>
                        <td><div class="status-indicator"><span class="pulse"></span> <span class="status-active">Active</span></div></td>
                        <td><strong>log_analyzer.py</strong></td>
                        <td>OpenAI</td>
                        <td>gpt-4o</td>
                        <td>Log anomaly detection</td>
                        <td>
                            <div class="metric-container">
                                <div class="bar-container">
                                    <div class="bar-fill" style="width: 37.5%"></div>
                                </div>
                                <div class="bar-label"><span>45k</span><span>120k</span></div>
                            </div>
                        </td>
                        <td>
                            <div class="metric-container">
                                <div class="bar-container">
                                    <div class="bar-fill" style="width: 32%"></div>
                                </div>
                                <div class="bar-label"><span>32</span><span>100</span></div>
                                <div class="time-window">14:00 - 15:00 UTC</div>
                            </div>
                        </td>
                        <td>
                            <div class="metric-container">
                                <div class="bar-container">
                                    <div class="bar-fill" style="width: 32%"></div>
                                </div>
                                <div class="bar-label"><span>320</span><span>1k</span></div>
                                <div class="time-window">Today (00:00-23:59)</div>
                            </div>
                        </td>
                    </tr>
                    <tr>
                        <td><div class="status-indicator"><span class="pulse"></span> <span class="status-active">Active</span></div></td>
                        <td><strong>report_gen.py</strong></td>
                        <td>Anthropic</td>
                        <td>claude-3-5</td>
                        <td>Daily executive summaries</td>
                        <td>
                            <div class="metric-container">
                                <div class="bar-container">
                                    <div class="bar-fill" style="width: 44%"></div>
                                </div>
                                <div class="bar-label"><span>88k</span><span>200k</span></div>
                            </div>
                        </td>
                        <td>
                            <div class="metric-container">
                                <div class="bar-container">
                                    <div class="bar-fill" style="width: 36%"></div>
                                </div>
                                <div class="bar-label"><span>18</span><span>50</span></div>
                                <div class="time-window">02:00 - 03:00 UTC</div>
                            </div>
                        </td>
                        <td>
                            <div class="metric-container">
                                <div class="bar-container">
                                    <div class="bar-fill" style="width: 36%"></div>
                                </div>
                                <div class="bar-label"><span>180</span><span>500</span></div>
                                <div class="time-window">Today (00:00-23:59)</div>
                            </div>
                        </td>
                    </tr>
                </tbody>
            </table>
        </div>

        <footer>
            <p>SentinelOps-Lite v1.2 • AI Agent Monitoring System • All metrics simulated for demonstration</p>
            <p style="margin-top: 8px; font-size: 0.9rem; color: var(--primary);">
                ✨ Standalone monitoring module - Drop into any Flask project • Zero external dependencies
            </p>
        </footer>
    </div>
</body>
</html>
'''
})

# ── BLUEPRINTS (REGISTERED IN APP.PY) ─────────────────────────
monitor_bp = Blueprint('monitor', __name__)
scanner_bp = Blueprint('scanner', __name__)

# ── WEBHOOK HANDLER (CALLED FROM APP.PY) ───────────────────────
def handle_monitor_status():
    """
    Processes CI/monitoring webhook requests.
    Returns standardized JSON response for pipeline integration.
    """
    return jsonify({
        "status": "operational",
        "timestamp": "2024-06-15T14:30:00Z",
        "agents_monitored": 2,
        "system_health": "optimal",
        "message": "Webhook received successfully - SentinelOps-Lite monitoring active"
    }), 200

# ── NO ROUTES DEFINED HERE (HANDLED IN APP.PY) ─────────────────
# This module provides:
#   - Flask application instance (`application`)
#   - Blueprints (`monitor_bp`, `scanner_bp`)
#   - Webhook handler (`handle_monitor_status`)
#   - Embedded dashboard template (loaded via DictLoader)
"""
agent_monitor.py
================
Complete standalone monitoring and scanning system for SentinelOps-Lite.
Integrates AI agents, CI/CD pipeline monitoring, and security scanning.

This file contains:
- Flask application setup
- Blueprint definitions for monitoring and scanning
- HTML/CSS/JS templates embedded
- AI agent integration
- Pipeline detection and monitoring
- All logic and UI components
"""

import os
import sys
import json
import time
from datetime import datetime
from pathlib import Path
from functools import wraps
from typing import Dict, List, Tuple, Any

from flask import Flask, Blueprint, render_template_string, jsonify, request, Response

# ══════════════════════════════════════════════════════════════
# FLASK APPLICATION SETUP
# ══════════════════════════════════════════════════════════════

application = Flask(__name__)
application.config['JSON_SORT_KEYS'] = False

# ══════════════════════════════════════════════════════════════
# BLUEPRINT DEFINITIONS
# ══════════════════════════════════════════════════════════════

monitor_bp = Blueprint('monitor', __name__, url_prefix='/monitor')
scanner_bp = Blueprint('scanner', __name__, url_prefix='/scanner')

# ══════════════════════════════════════════════════════════════
# AI AGENT CONFIGURATION & REGISTRY
# ══════════════════════════════════════════════════════════════

class AIAgent:
    """Represents an AI agent with its characteristics and metrics."""
    
    def __init__(self, name: str, provider: str, model: str, purpose: str, 
                 tokens_limit: int, requests_per_hour: int, requests_per_day: int):
        self.name = name
        self.provider = provider
        self.model = model
        self.purpose = purpose
        self.tokens_limit = tokens_limit
        self.tokens_used = 0
        self.requests_per_hour = requests_per_hour
        self.requests_per_day = requests_per_day
        self.requests_used_hour = 0
        self.requests_used_day = 0
        self.last_hour_reset = datetime.now()
        self.last_day_reset = datetime.now()
        self.status = "Active"
        self.error_count = 0
        self.success_count = 0
    
    def to_dict(self) -> Dict:
        """Convert agent to dictionary."""
        return {
            "name": self.name,
            "provider": self.provider,
            "model": self.model,
            "purpose": self.purpose,
            "tokens_limit": self.tokens_limit,
            "tokens_used": self.tokens_used,
            "tokens_usage_percent": round((self.tokens_used / self.tokens_limit) * 100, 2),
            "requests_per_hour": self.requests_per_hour,
            "requests_used_hour": self.requests_used_hour,
            "requests_hour_percent": round((self.requests_used_hour / self.requests_per_hour) * 100, 2),
            "requests_per_day": self.requests_per_day,
            "requests_used_day": self.requests_used_day,
            "requests_day_percent": round((self.requests_used_day / self.requests_per_day) * 100, 2),
            "status": self.status,
            "success_count": self.success_count,
            "error_count": self.error_count,
            "error_rate": round((self.error_count / (self.success_count + self.error_count)) * 100, 2) if (self.success_count + self.error_count) > 0 else 0
        }

# ── AI Agents Registry ─────────────────────────────────────────
AGENTS_REGISTRY = {
    "security_scanner": AIAgent(
        name="Security Scanner Agent",
        provider="OpenAI",
        model="gpt-4-turbo",
        purpose="Analyze code for security vulnerabilities, SAST scanning, dependency analysis",
        tokens_limit=100000,
        requests_per_hour=60,
        requests_per_day=500
    ),
    "code_analyzer": AIAgent(
        name="Code Quality Analyzer Agent",
        provider="Anthropic",
        model="claude-3-opus",
        purpose="Code quality analysis, pattern detection, best practices validation",
        tokens_limit=150000,
        requests_per_hour=80,
        requests_per_day=600
    ),
    "compliance_checker": AIAgent(
        name="Compliance Checker Agent",
        provider="Azure OpenAI",
        model="gpt-4-32k",
        purpose="Check compliance with standards, regulatory requirements, policy validation",
        tokens_limit=200000,
        requests_per_hour=40,
        requests_per_day=300
    ),
    "log_analyzer": AIAgent(
        name="Log Analysis Agent",
        provider="OpenAI",
        model="gpt-3.5-turbo",
        purpose="Parse and analyze logs, detect anomalies, pattern recognition",
        tokens_limit=80000,
        requests_per_hour=120,
        requests_per_day=1000
    )
}

# ══════════════════════════════════════════════════════════════
# PIPELINE DETECTION & MONITORING
# ══════════════════════════════════════════════════════════════

class PipelineDetector:
    """Detects and identifies CI/CD pipeline type."""
    
    PIPELINE_INDICATORS = {
        "GitHub Actions": [
            "GITHUB_ACTIONS",
            "GITHUB_RUN_ID",
            "GITHUB_WORKFLOW",
            "GITHUB_REF"
        ],
        "Azure DevOps": [
            "SYSTEM_TEAMFOUNDATIONCOLLECTIONURI",
            "SYSTEM_TEAMPROJECT",
            "BUILD_BUILDID",
            "AGENT_ID"
        ],
        "Jenkins": [
            "JENKINS_URL",
            "BUILD_ID",
            "BUILD_NUMBER",
            "JOB_NAME",
            "WORKSPACE"
        ],
        "GitLab CI": [
            "GITLAB_CI",
            "CI_PIPELINE_ID",
            "CI_JOB_ID",
            "CI_COMMIT_SHA"
        ],
        "CircleCI": [
            "CIRCLECI",
            "CIRCLE_BUILD_NUM",
            "CIRCLE_WORKFLOW_ID",
            "CIRCLE_PROJECT_USERNAME"
        ]
    }
    
    PIPELINE_MEANINGS = {
        "GitHub Actions": "GitHub's native CI/CD platform that automates builds, tests, and deployments using workflows defined in YAML files.",
        "Azure DevOps": "Microsoft's comprehensive DevOps platform providing CI/CD pipelines, artifact management, testing, and deployment capabilities across cloud and on-premises.",
        "Jenkins": "Open-source automation server widely used for continuous integration and continuous delivery with extensive plugin ecosystem for build automation.",
        "GitLab CI": "GitLab's integrated CI/CD solution built into the platform for automating testing, building, and deployment of code with parallel execution support.",
        "CircleCI": "Cloud-native CI/CD platform providing automated testing and deployment with support for Docker, parallelization, and workflow orchestration."
    }
    
    @staticmethod
    def detect() -> Tuple[str, str, Dict]:
        """
        Detect which pipeline is running.
        Returns: (pipeline_name, description, environment_vars)
        """
        env_vars = dict(os.environ)
        
        for pipeline, indicators in PipelineDetector.PIPELINE_INDICATORS.items():
            if any(indicator in env_vars for indicator in indicators):
                description = PipelineDetector.PIPELINE_MEANINGS.get(
                    pipeline, 
                    "Unknown CI/CD Pipeline"
                )
                return pipeline, description, env_vars
        
        return "Local Development", "Running on local machine outside CI/CD pipeline", env_vars

# ── Global Pipeline Info ───────────────────────────────────────
PIPELINE_NAME, PIPELINE_DESCRIPTION, PIPELINE_ENV = PipelineDetector.detect()

# ══════════════════════════════════════════════════════════════
# MONITORING STATE & STORAGE
# ══════════════════════════════════════════════════════════════

class MonitoringState:
    """Maintains state of monitoring activities."""
    
    def __init__(self):
        self.build_history = []
        self.scan_results = []
        self.alerts = []
        self.metrics = {
            "total_builds": 0,
            "passed_builds": 0,
            "failed_builds": 0,
            "total_scans": 0,
            "vulnerabilities_found": 0,
            "critical_issues": 0
        }
    
    def add_build(self, status: str, commit_hash: str = ""):
        """Add build record."""
        record = {
            "timestamp": datetime.now().isoformat(),
            "status": status,
            "commit": commit_hash[:8] if commit_hash else "N/A"
        }
        self.build_history.append(record)
        self.metrics["total_builds"] += 1
        
        if status == "passed":
            self.metrics["passed_builds"] += 1
        elif status == "failed":
            self.metrics["failed_builds"] += 1
    
    def add_scan(self, scan_type: str, vulnerabilities: int, critical: int):
        """Add scan result."""
        record = {
            "timestamp": datetime.now().isoformat(),
            "type": scan_type,
            "vulnerabilities": vulnerabilities,
            "critical": critical
        }
        self.scan_results.append(record)
        self.metrics["total_scans"] += 1
        self.metrics["vulnerabilities_found"] += vulnerabilities
        self.metrics["critical_issues"] += critical
    
    def add_alert(self, level: str, message: str):
        """Add alert."""
        self.alerts.append({
            "timestamp": datetime.now().isoformat(),
            "level": level,
            "message": message
        })

# ── Global State Instance ──────────────────────────────────────
monitoring_state = MonitoringState()

# ══════════════════════════════════════════════════════════════
# HANDLER FUNCTIONS
# ══════════════════════════════════════════════════════════════

def handle_monitor_status():
    """
    Handle CI/CD monitoring webhook from pipeline.
    Processes build status and triggers agents.
    """
    try:
        data = request.get_json() or {}
        status = data.get("status", "unknown")
        commit = data.get("commit", "")
        
        monitoring_state.add_build(status, commit)
        
        # Simulate agent processing
        for agent_key, agent in AGENTS_REGISTRY.items():
            agent.requests_used_hour += 1
            agent.requests_used_day += 1
            agent.tokens_used += 5000
            agent.success_count += 1
        
        return jsonify({
            "status": "success",
            "message": "Monitor status received and processed",
            "pipeline": PIPELINE_NAME
        }), 200
    
    except Exception as e:
        monitoring_state.add_alert("error", f"Monitor webhook error: {str(e)}")
        return jsonify({"status": "error", "message": str(e)}), 500

# ══════════════════════════════════════════════════════════════
# BLUEPRINT ROUTES - MONITOR
# ══════════════════════════════════════════════════════════════

@monitor_bp.get("/health")
def monitor_health():
    """Health check endpoint."""
    return jsonify({
        "status": "healthy",
        "pipeline": PIPELINE_NAME,
        "agents": {k: v.status for k, v in AGENTS_REGISTRY.items()}
    })

@monitor_bp.get("/agents")
def get_agents():
    """Get all agents information."""
    return jsonify({
        "agents": [agent.to_dict() for agent in AGENTS_REGISTRY.values()]
    })

@monitor_bp.get("/pipeline")
def get_pipeline_info():
    """Get pipeline information."""
    return jsonify({
        "name": PIPELINE_NAME,
        "description": PIPELINE_DESCRIPTION,
        "detected_at": datetime.now().isoformat()
    })

@monitor_bp.get("/metrics")
def get_metrics():
    """Get monitoring metrics."""
    return jsonify({
        "metrics": monitoring_state.metrics,
        "build_history": monitoring_state.build_history[-10:],
        "scan_results": monitoring_state.scan_results[-10:]
    })

# ══════════════════════════════════════════════════════════════
# BLUEPRINT ROUTES - SCANNER
# ══════════════════════════════════════════════════════════════

@scanner_bp.post("/scan")
def run_scan():
    """Trigger security scan."""
    try:
        data = request.get_json() or {}
        scan_type = data.get("type", "general")
        
        # Simulate scan
        vulnerabilities = {"critical": 2, "high": 5, "medium": 12}
        monitoring_state.add_scan(scan_type, 19, 2)
        
        # Update agent metrics
        security_agent = AGENTS_REGISTRY.get("security_scanner")
        if security_agent:
            security_agent.requests_used_hour += 1
            security_agent.requests_used_day += 1
            security_agent.tokens_used += 25000
            security_agent.success_count += 1
        
        return jsonify({
            "status": "completed",
            "vulnerabilities": vulnerabilities
        })
    
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@scanner_bp.get("/results")
def get_scan_results():
    """Get scan results."""
    return jsonify({
        "results": monitoring_state.scan_results[-20:]
    })

# ══════════════════════════════════════════════════════════════
# EMBEDDED HTML/CSS/JS TEMPLATE
# ══════════════════════════════════════════════════════════════

DASHBOARD_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>SentinelOps-Lite Dashboard</title>
    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
    <script src="https://cdn.jsdelivr.net/npm/axios/dist/axios.min.js"></script>
    <style>
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }
        
        :root {
            --primary-color: #10b981;
            --secondary-color: #06b6d4;
            --danger-color: #ef4444;
            --warning-color: #f59e0b;
            --dark-bg: #f0fdf4;
            --card-bg: #ffffff;
            --border-color: #d1fae5;
            --text-dark: #064e3b;
            --text-light: #047857;
            --shadow: 0 4px 6px rgba(16, 185, 129, 0.1);
        }
        
        body {
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            background: linear-gradient(135deg, #f0fdf4 0%, #ecfdf5 100%);
            color: var(--text-dark);
            min-height: 100vh;
            padding: 20px;
        }
        
        .container {
            max-width: 1400px;
            margin: 0 auto;
        }
        
        /* ── HEADER ─────────────────────────────── */
        .header {
            background: linear-gradient(135deg, var(--primary-color) 0%, var(--secondary-color) 100%);
            color: white;
            padding: 30px;
            border-radius: 12px;
            margin-bottom: 30px;
            box-shadow: var(--shadow);
        }
        
        .header h1 {
            font-size: 2.5em;
            margin-bottom: 10px;
            display: flex;
            align-items: center;
            gap: 15px;
        }
        
        .header-icon {
            font-size: 3em;
        }
        
        .header-info {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(250px, 1fr));
            gap: 20px;
            margin-top: 20px;
        }
        
        .info-box {
            background: rgba(255, 255, 255, 0.15);
            padding: 15px;
            border-radius: 8px;
            backdrop-filter: blur(10px);
        }
        
        .info-box-label {
            font-size: 0.85em;
            opacity: 0.9;
            margin-bottom: 5px;
        }
        
        .info-box-value {
            font-size: 1.3em;
            font-weight: bold;
        }
        
        /* ── TABS ───────────────────────────────── */
        .tabs {
            display: flex;
            gap: 10px;
            margin-bottom: 30px;
            flex-wrap: wrap;
        }
        
        .tab-btn {
            padding: 12px 25px;
            border: 2px solid var(--border-color);
            background: var(--card-bg);
            color: var(--text-dark);
            cursor: pointer;
            border-radius: 8px;
            font-weight: 600;
            transition: all 0.3s ease;
            display: flex;
            align-items: center;
            gap: 8px;
        }
        
        .tab-btn:hover {
            background: var(--primary-color);
            color: white;
            transform: translateY(-2px);
        }
        
        .tab-btn.active {
            background: var(--primary-color);
            color: white;
            border-color: var(--primary-color);
        }
        
        /* ── GRID LAYOUT ────────────────────────── */
        .grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));
            gap: 25px;
            margin-bottom: 30px;
        }
        
        .grid-wide {
            grid-column: 1 / -1;
        }
        
        /* ── CARDS ──────────────────────────────── */
        .card {
            background: var(--card-bg);
            border-radius: 12px;
            padding: 25px;
            box-shadow: var(--shadow);
            border-left: 4px solid var(--primary-color);
            transition: all 0.3s ease;
        }
        
        .card:hover {
            transform: translateY(-5px);
            box-shadow: 0 8px 12px rgba(16, 185, 129, 0.15);
        }
        
        .card.danger {
            border-left-color: var(--danger-color);
        }
        
        .card.warning {
            border-left-color: var(--warning-color);
        }
        
        .card-title {
            font-size: 1.2em;
            font-weight: 700;
            margin-bottom: 15px;
            color: var(--text-dark);
            display: flex;
            align-items: center;
            gap: 10px;
        }
        
        .card-title-icon {
            font-size: 1.5em;
        }
        
        .card-content {
            color: var(--text-light);
            line-height: 1.6;
        }
        
        /* ── METRICS ────────────────────────────── */
        .metric {
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding: 12px 0;
            border-bottom: 1px solid var(--border-color);
        }
        
        .metric:last-child {
            border-bottom: none;
        }
        
        .metric-label {
            font-weight: 500;
        }
        
        .metric-value {
            font-weight: bold;
            color: var(--primary-color);
            font-size: 1.1em;
        }
        
        /* ── PROGRESS BARS ──────────────────────── */
        .progress-bar {
            background: var(--border-color);
            border-radius: 8px;
            height: 8px;
            margin: 8px 0;
            overflow: hidden;
        }
        
        .progress-fill {
            background: linear-gradient(90deg, var(--primary-color), var(--secondary-color));
            height: 100%;
            border-radius: 8px;
            transition: width 0.3s ease;
        }
        
        .progress-fill.warning {
            background: linear-gradient(90deg, var(--warning-color), var(--primary-color));
        }
        
        .progress-fill.danger {
            background: linear-gradient(90deg, var(--danger-color), var(--warning-color));
        }
        
        /* ── STATUS BADGE ───────────────────────── */
        .badge {
            display: inline-block;
            padding: 6px 12px;
            border-radius: 20px;
            font-size: 0.85em;
            font-weight: 600;
        }
        
        .badge-success {
            background: #d1fae5;
            color: #047857;
        }
        
        .badge-warning {
            background: #fef3c7;
            color: #92400e;
        }
        
        .badge-danger {
            background: #fee2e2;
            color: #991b1b;
        }
        
        .badge-info {
            background: #cffafe;
            color: #164e63;
        }
        
        /* ── AGENT CARD GRID ────────────────────── */
        .agents-grid {
            display: grid;
            grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
            gap: 20px;
        }
        
        .agent-card {
            background: var(--card-bg);
            border-radius: 12px;
            padding: 20px;
            box-shadow: var(--shadow);
            border-top: 4px solid var(--primary-color);
        }
        
        .agent-header {
            margin-bottom: 15px;
        }
        
        .agent-name {
            font-size: 1.1em;
            font-weight: bold;
            color: var(--text-dark);
            margin-bottom: 5px;
        }
        
        .agent-provider {
            font-size: 0.9em;
            color: var(--text-light);
        }
        
        .agent-model {
            font-size: 0.85em;
            background: var(--border-color);
            color: var(--text-dark);
            padding: 4px 8px;
            border-radius: 4px;
            display: inline-block;
            margin-top: 8px;
        }
        
        .agent-stats {
            margin-top: 15px;
            font-size: 0.9em;
        }
        
        .agent-stat {
            display: flex;
            justify-content: space-between;
            padding: 8px 0;
            border-bottom: 1px solid var(--border-color);
        }
        
        .agent-stat:last-child {
            border-bottom: none;
        }
        
        /* ── CHART CONTAINER ────────────────────── */
        .chart-container {
            position: relative;
            height: 300px;
            margin: 20px 0;
        }
        
        /* ── TABLE ──────────────────────────────── */
        .table-responsive {
            overflow-x: auto;
        }
        
        table {
            width: 100%;
            border-collapse: collapse;
            margin-top: 15px;
        }
        
        th {
            background: var(--border-color);
            color: var(--text-dark);
            padding: 12px;
            text-align: left;
            font-weight: 600;
        }
        
        td {
            padding: 12px;
            border-bottom: 1px solid var(--border-color);
        }
        
        tr:hover {
            background: rgba(16, 185, 129, 0.05);
        }
        
        /* ── ALERTS ─────────────────────────────── */
        .alert {
            padding: 15px 20px;
            border-radius: 8px;
            margin-bottom: 15px;
            display: flex;
            gap: 15px;
            align-items: flex-start;
        }
        
        .alert-icon {
            font-size: 1.3em;
            flex-shrink: 0;
        }
        
        .alert-content {
            flex: 1;
        }
        
        .alert-title {
            font-weight: 600;
            margin-bottom: 5px;
        }
        
        .alert-success {
            background: #d1fae5;
            color: #047857;
            border-left: 4px solid #10b981;
        }
        
        .alert-error {
            background: #fee2e2;
            color: #991b1b;
            border-left: 4px solid #ef4444;
        }
        
        .alert-warning {
            background: #fef3c7;
            color: #92400e;
            border-left: 4px solid #f59e0b;
        }
        
        /* ── LOADING SPINNER ────────────────────── */
        .spinner {
            border: 4px solid var(--border-color);
            border-top: 4px solid var(--primary-color);
            border-radius: 50%;
            width: 40px;
            height: 40px;
            animation: spin 1s linear infinite;
        }
        
        @keyframes spin {
            0% { transform: rotate(0deg); }
            100% { transform: rotate(360deg); }
        }
        
        /* ── TAB CONTENT ────────────────────────── */
        .tab-content {
            display: none;
        }
        
        .tab-content.active {
            display: block;
            animation: fadeIn 0.3s ease;
        }
        
        @keyframes fadeIn {
            from { opacity: 0; transform: translateY(10px); }
            to { opacity: 1; transform: translateY(0); }
        }
        
        /* ── RESPONSIVE ─────────────────────────── */
        @media (max-width: 768px) {
            .header h1 {
                font-size: 1.8em;
            }
            
            .grid {
                grid-template-columns: 1fr;
            }
            
            .header-info {
                grid-template-columns: 1fr;
            }
            
            .tabs {
                flex-direction: column;
            }
            
            .tab-btn {
                width: 100%;
            }
        }
        
        /* ── UTILITY CLASSES ────────────────────── */
        .text-center {
            text-align: center;
        }
        
        .mt-20 {
            margin-top: 20px;
        }
        
        .p-20 {
            padding: 20px;
        }
        
        .gap-20 {
            gap: 20px;
        }
        
        .loading {
            display: flex;
            justify-content: center;
            align-items: center;
            min-height: 300px;
            gap: 15px;
        }
        
        .no-data {
            text-align: center;
            color: var(--text-light);
            padding: 40px 20px;
        }
    </style>
</head>
<body>
    <div class="container">
        <!-- HEADER -->
        <div class="header">
            <h1>
                <span class="header-icon">🛡️</span>
                SentinelOps-Lite Dashboard
            </h1>
            <div class="header-info">
                <div class="info-box">
                    <div class="info-box-label">🔧 Pipeline</div>
                    <div class="info-box-value" id="pipelineName">Detecting...</div>
                </div>
                <div class="info-box">
                    <div class="info-box-label">📊 Total Builds</div>
                    <div class="info-box-value" id="totalBuilds">0</div>
                </div>
                <div class="info-box">
                    <div class="info-box-label">✅ Passed</div>
                    <div class="info-box-value" id="passedBuilds">0</div>
                </div>
                <div class="info-box">
                    <div class="info-box-label">❌ Failed</div>
                    <div class="info-box-value" id="failedBuilds">0</div>
                </div>
            </div>
        </div>
        
        <!-- TABS -->
        <div class="tabs">
            <button class="tab-btn active" data-tab="dashboard">📊 Dashboard</button>
            <button class="tab-btn" data-tab="agents">🤖 AI Agents</button>
            <button class="tab-btn" data-tab="scans">🔍 Security Scans</button>
            <button class="tab-btn" data-tab="pipeline">🔧 Pipeline Info</button>
            <button class="tab-btn" data-tab="alerts">🔔 Alerts</button>
        </div>
        
        <!-- DASHBOARD TAB -->
        <div id="dashboard" class="tab-content active">
            <div class="grid">
                <!-- Metrics Cards -->
                <div class="card">
                    <div class="card-title">
                        <span class="card-title-icon">📈</span>
                        Build Metrics
                    </div>
                    <div class="card-content">
                        <div class="metric">
                            <span class="metric-label">Total Builds</span>
                            <span class="metric-value" id="metric-totalBuilds">0</span>
                        </div>
                        <div class="metric">
                            <span class="metric-label">Success Rate</span>
                            <span class="metric-value" id="metric-successRate">0%</span>
                        </div>
                        <div class="metric">
                            <span class="metric-label">Failed Builds</span>
                            <span class="metric-value" id="metric-failedBuilds">0</span>
                        </div>
                    </div>
                </div>
                
                <div class="card">
                    <div class="card-title">
                        <span class="card-title-icon">🔍</span>
                        Security Overview
                    </div>
                    <div class="card-content">
                        <div class="metric">
                            <span class="metric-label">Total Scans</span>
                            <span class="metric-value" id="metric-totalScans">0</span>
                        </div>
                        <div class="metric">
                            <span class="metric-label">Vulnerabilities</span>
                            <span class="metric-value" id="metric-vulns">0</span>
                        </div>
                        <div class="metric">
                            <span class="metric-label">Critical Issues</span>
                            <span class="metric-value danger" id="metric-critical">0</span>
                        </div>
                    </div>
                </div>
                
                <div class="card">
                    <div class="card-title">
                        <span class="card-title-icon">🤖</span>
                        AI Agents Health
                    </div>
                    <div class="card-content">
                        <div class="metric">
                            <span class="metric-label">Active Agents</span>
                            <span class="metric-value" id="metric-activeAgents">0</span>
                        </div>
                        <div class="metric">
                            <span class="metric-label">Total Requests</span>
                            <span class="metric-value" id="metric-totalRequests">0</span>
                        </div>
                        <div class="metric">
                            <span class="metric-label">Avg Error Rate</span>
                            <span class="metric-value" id="metric-errorRate">0%</span>
                        </div>
                    </div>
                </div>
            </div>
            
            <!-- Charts -->
            <div class="grid">
                <div class="card grid-wide">
                    <div class="card-title">📊 Build History (Last 10)</div>
                    <div class="chart-container">
                        <canvas id="buildChart"></canvas>
                    </div>
                </div>
            </div>
            
            <!-- Recent History -->
            <div class="grid">
                <div class="card grid-wide">
                    <div class="card-title">📋 Recent Builds</div>
                    <div class="table-responsive">
                        <table>
                            <thead>
                                <tr>
                                    <th>Timestamp</th>
                                    <th>Status</th>
                                    <th>Commit</th>
                                </tr>
                            </thead>
                            <tbody id="buildHistoryTable">
                                <tr>
                                    <td colspan="3" class="text-center">No builds yet</td>
                                </tr>
                            </tbody>
                        </table>
                    </div>
                </div>
            </div>
        </div>
        
        <!-- AI AGENTS TAB -->
        <div id="agents" class="tab-content">
            <div class="grid">
                <div class="card grid-wide">
                    <div class="card-title">🤖 Registered AI Agents</div>
                </div>
            </div>
            <div class="agents-grid" id="agentsGrid">
                <div class="loading">
                    <div class="spinner"></div>
                    <span>Loading agents...</span>
                </div>
            </div>
        </div>
        
        <!-- SCANS TAB -->
        <div id="scans" class="tab-content">
            <div class="grid">
                <div class="card">
                    <div class="card-title">🔍 Run Security Scan</div>
                    <div class="card-content">
                        <button id="runScanBtn" class="btn" style="background: var(--primary-color); color: white; padding: 10px 20px; border: none; border-radius: 6px; cursor: pointer; font-weight: 600;">
                            Start Scan
                        </button>
                        <div id="scanStatus" style="margin-top: 15px; display: none;">
                            <div class="spinner"></div>
                            <p>Scan in progress...</p>
                        </div>
                    </div>
                </div>
            </div>
            
            <div class="grid">
                <div class="card grid-wide">
                    <div class="card-title">📊 Scan Results</div>
                    <div class="table-responsive">
                        <table>
                            <thead>
                                <tr>
                                    <th>Timestamp</th>
                                    <th>Type</th>
                                    <th>Vulnerabilities</th>
                                    <th>Critical</th>
                                </tr>
                            </thead>
                            <tbody id="scanResultsTable">
                                <tr>
                                    <td colspan="4" class="text-center">No scans yet</td>
                                </tr>
                            </tbody>
                        </table>
                    </div>
                </div>
            </div>
        </div>
        
        <!-- PIPELINE INFO TAB -->
        <div id="pipeline" class="tab-content">
            <div class="grid">
                <div class="card">
                    <div class="card-title">🔧 Pipeline Configuration</div>
                    <div class="card-content">
                        <div class="metric">
                            <span class="metric-label">Pipeline Name</span>
                            <span class="metric-value" id="pipelineNameDetail">-</span>
                        </div>
                        <div class="metric">
                            <span class="metric-label">Status</span>
                            <span class="badge badge-success">Active</span>
                        </div>
                    </div>
                </div>
                
                <div class="card">
                    <div class="card-title">📖 Description</div>
                    <div class="card-content" id="pipelineDescription">
                        Loading...
                    </div>
                </div>
            </div>
        </div>
        
        <!-- ALERTS TAB -->
        <div id="alerts" class="tab-content">
            <div class="grid">
                <div class="card grid-wide">
                    <div class="card-title">🔔 System Alerts</div>
                    <div id="alertsContainer">
                        <div class="no-data">No alerts at this time</div>
                    </div>
                </div>
            </div>
        </div>
    </div>
    
    <script>
        // ── API BASE URL ─────────────────────────────────
        const API_BASE = '/monitor';
        
        // ── STATE ────────────────────────────────────────
        let buildChart = null;
        let refreshInterval = null;
        
        // ── CHART CONFIGURATION ─────────────────────────
        function initBuildChart(data) {
            const ctx = document.getElementById('buildChart');
            if (!ctx) return;
            
            const labels = data.build_history.map(b => 
                new Date(b.timestamp).toLocaleTimeString()
            );
            const passedData = data.build_history.map(b => b.status === 'passed' ? 1 : 0);
            const failedData = data.build_history.map(b => b.status === 'failed' ? 1 : 0);
            
            if (buildChart) {
                buildChart.destroy();
            }
            
            buildChart = new Chart(ctx, {
                type: 'bar',
                data: {
                    labels: labels,
                    datasets: [
                        {
                            label: 'Passed',
                            data: passedData,
                            backgroundColor: '#10b981',
                            borderColor: '#047857',
                            borderWidth: 1
                        },
                        {
                            label: 'Failed',
                            data: failedData,
                            backgroundColor: '#ef4444',
                            borderColor: '#991b1b',
                            borderWidth: 1
                        }
                    ]
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    plugins: {
                        legend: {
                            labels: {
                                color: '#064e3b',
                                font: { weight: 'bold' }
                            }
                        }
                    },
                    scales: {
                        y: {
                            beginAtZero: true,
                            max: 1,
                            ticks: { color: '#064e3b' },
                            grid: { color: '#d1fae5' }
                        },
                        x: {
                            ticks: { color: '#064e3b' },
                            grid: { color: '#d1fae5' }
                        }
                    }
                }
            });
        }
        
        // ── DATA FETCHING ────────────────────────────────
        async function fetchPipelineInfo() {
            try {
                const response = await axios.get(`${API_BASE}/pipeline`);
                document.getElementById('pipelineName').textContent = response.data.name;
                document.getElementById('pipelineNameDetail').textContent = response.data.name;
                document.getElementById('pipelineDescription').textContent = response.data.description;
            } catch (error) {
                console.error('Error fetching pipeline info:', error);
            }
        }
        
        async function fetchAgents() {
            try {
                const response = await axios.get(`${API_BASE}/agents`);
                const agentsGrid = document.getElementById('agentsGrid');
                agentsGrid.innerHTML = '';
                
                response.data.agents.forEach(agent => {
                    const agentCard = document.createElement('div');
                    agentCard.className = 'agent-card';
                    agentCard.innerHTML = `
                        <div class="agent-header">
                            <div class="agent-name">${agent.name}</div>
                            <div class="agent-provider">
                                <span class="badge badge-info">${agent.provider}</span>
                            </div>
                            <div class="agent-model">${agent.model}</div>
                        </div>
                        
                        <div class="agent-stats">
                            <div class="agent-stat">
                                <span>Status</span>
                                <span class="badge badge-success">${agent.status}</span>
                            </div>
                            
                            <div class="agent-stat">
                                <span>Token Usage</span>
                                <span>${agent.tokens_used}/${agent.tokens_limit}</span>
                            </div>
                            <div class="progress-bar">
                                <div class="progress-fill" style="width: ${agent.tokens_usage_percent}%"></div>
                            </div>
                            <div style="font-size: 0.8em; color: var(--text-light);">${agent.tokens_usage_percent.toFixed(1)}%</div>
                            
                            <div class="agent-stat mt-20">
                                <span>Requests/Hour</span>
                                <span>${agent.requests_used_hour}/${agent.requests_per_hour}</span>
                            </div>
                            <div class="progress-bar">
                                <div class="progress-fill ${agent.requests_hour_percent > 80 ? 'warning' : ''}" style="width: ${agent.requests_hour_percent}%"></div>
                            </div>
                            <div style="font-size: 0.8em; color: var(--text-light);">${agent.requests_hour_percent.toFixed(1)}%</div>
                            
                            <div class="agent-stat mt-20">
                                <span>Requests/Day</span>
                                <span>${agent.requests_used_day}/${agent.requests_per_day}</span>
                            </div>
                            <div class="progress-bar">
                                <div class="progress-fill ${agent.requests_day_percent > 80 ? 'warning' : ''}" style="width: ${agent.requests_day_percent}%"></div>
                            </div>
                            <div style="font-size: 0.8em; color: var(--text-light);">${agent.requests_day_percent.toFixed(1)}%</div>
                            
                            <div class="agent-stat mt-20">
                                <span>Success Rate</span>
                                <span>${(100 - agent.error_rate).toFixed(1)}%</span>
                            </div>
                            <div class="progress-bar">
                                <div class="progress-fill" style="width: ${100 - agent.error_rate}%"></div>
                            </div>
                        </div>
                    `;
                    agentsGrid.appendChild(agentCard);
                });
            } catch (error) {
                console.error('Error fetching agents:', error);
            }
        }
        
        async function fetchMetrics() {
            try {
                const response = await axios.get(`${API_BASE}/metrics`);
                const metrics = response.data.metrics;
                
                // Update header
                document.getElementById('totalBuilds').textContent = metrics.total_builds;
                document.getElementById('passedBuilds').textContent = metrics.passed_builds;
                document.getElementById('failedBuilds').textContent = metrics.failed_builds;
                
                // Update metric cards
                document.getElementById('metric-totalBuilds').textContent = metrics.total_builds;
                document.getElementById('metric-failedBuilds').textContent = metrics.failed_builds;
                
                const successRate = metrics.total_builds > 0 
                    ? ((metrics.passed_builds / metrics.total_builds) * 100).toFixed(1)
                    : 0;
                document.getElementById('metric-successRate').textContent = `${successRate}%`;
                
                document.getElementById('metric-totalScans').textContent = metrics.total_scans;
                document.getElementById('metric-vulns').textContent = metrics.vulnerabilities_found;
                document.getElementById('metric-critical').textContent = metrics.critical_issues;
                
                // Update build history table
                const buildTable = document.getElementById('buildHistoryTable');
                const buildHistory = response.data.build_history.slice().reverse();
                
                if (buildHistory.length === 0) {
                    buildTable.innerHTML = '<tr><td colspan="3" class="text-center">No builds yet</td></tr>';
                } else {
                    buildTable.innerHTML = buildHistory.map(build => `
                        <tr>
                            <td>${new Date(build.timestamp).toLocaleString()}</td>
                            <td><span class="badge ${build.status === 'passed' ? 'badge-success' : 'badge-danger'}">${build.status.toUpperCase()}</span></td>
                            <td>${build.commit}</td>
                        </tr>
                    `).join('');
                }
                
                // Update chart
                initBuildChart(response.data);
                
                // Update AI agents metrics
                fetchAgents();
            } catch (error) {
                console.error('Error fetching metrics:', error);
            }
        }
        
        async function fetchScanResults() {
            try {
                const response = await axios.get(`${API_BASE.replace('/monitor', '/scanner')}/results`);
                const scanTable = document.getElementById('scanResultsTable');
                const results = response.data.results.slice().reverse();
                
                if (results.length === 0) {
                    scanTable.innerHTML = '<tr><td colspan="4" class="text-center">No scans yet</td></tr>';
                } else {
                    scanTable.innerHTML = results.map(scan => `
                        <tr>
                            <td>${new Date(scan.timestamp).toLocaleString()}</td>
                            <td>${scan.type}</td>
                            <td>${scan.vulnerabilities}</td>
                            <td><span class="badge badge-danger">${scan.critical}</span></td>
                        </tr>
                    `).join('');
                }
            } catch (error) {
                console.error('Error fetching scan results:', error);
            }
        }
        
        // ── EVENT HANDLERS ───────────────────────────────
        document.addEventListener('DOMContentLoaded', () => {
            // Tab switching
            document.querySelectorAll('.tab-btn').forEach(btn => {
                btn.addEventListener('click', () => {
                    const tabName = btn.dataset.tab;
                    
                    // Hide all tabs
                    document.querySelectorAll('.tab-content').forEach(tab => {
                        tab.classList.remove('active');
                    });
                    
                    // Deactivate all buttons
                    document.querySelectorAll('.tab-btn').forEach(b => {
                        b.classList.remove('active');
                    });
                    
                    // Show selected tab
                    document.getElementById(tabName).classList.add('active');
                    btn.classList.add('active');
                });
            });
            
            // Run scan button
            document.getElementById('runScanBtn').addEventListener('click', async () => {
                const btn = document.getElementById('runScanBtn');
                const status = document.getElementById('scanStatus');
                
                btn.disabled = true;
                status.style.display = 'flex';
                status.style.flexDirection = 'column';
                status.style.alignItems = 'center';
                status.style.gap = '15px';
                
                try {
                    await axios.post(`${API_BASE.replace('/monitor', '/scanner')}/scan`, {
                        type: 'general'
                    });
                    
                    setTimeout(() => {
                        fetchScanResults();
                        status.style.display = 'none';
                        btn.disabled = false;
                    }, 2000);
                } catch (error) {
                    console.error('Scan error:', error);
                    status.style.display = 'none';
                    btn.disabled = false;
                }
            });
            
            // Initial load
            fetchPipelineInfo();
            fetchMetrics();
            fetchScanResults();
            
            // Refresh every 5 seconds
            refreshInterval = setInterval(() => {
                fetchMetrics();
                fetchScanResults();
            }, 5000);
        });
        
        // Cleanup on page unload
        window.addEventListener('beforeunload', () => {
            if (refreshInterval) {
                clearInterval(refreshInterval);
            }
        });
    </script>
</body>
</html>
"""

@application.get("/")
def render_dashboard():
    """Render the dashboard template."""
    return render_template_string(DASHBOARD_TEMPLATE)

# ══════════════════════════════════════════════════════════════
# EXPORT FOR MAIN APP
# ══════════════════════════════════════════════════════════════

__all__ = [
    'application',
    'monitor_bp',
    'scanner_bp',
    'handle_monitor_status',
    'AGENTS_REGISTRY',
    'PIPELINE_NAME',
    'PIPELINE_DESCRIPTION'
]
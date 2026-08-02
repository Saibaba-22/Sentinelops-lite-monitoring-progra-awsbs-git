"""
app.py
======
Flask entry point for SentinelOps-Lite with AI Agent Monitor.
Only routes and redirections live here.
All logic lives in agent_monitor.py.
"""

import os
import sys
import time
from pathlib import Path

from flask import render_template, Response, request, jsonify, send_file
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

# ── path setup ────────────────────────────────────────────────
BASE_DIR = Path(__file__).resolve().parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

# ── import application and blueprint from agent_monitor ───────
from agent_monitor import application, monitor_bp, scanner_bp, scanner

# ── import custom Prometheus metrics ──────────────────────────
from monitoring.metrics import (
    start_metrics_updater,
    update_metrics,
    app_requests_total,
    app_request_duration_seconds,
    app_errors_total,
    app_exceptions_total,
    http_status_codes_total,
    APP_STATS,
)

# ── register blueprints ───────────────────────────────────────
application.register_blueprint(monitor_bp)
application.register_blueprint(scanner_bp)

# ── start metrics background updater ──────────────────────────
update_metrics()
start_metrics_updater(interval=5)


# ══════════════════════════════════════════════════════════════
# REQUEST TRACKING — populates app_* metrics for Grafana
# ══════════════════════════════════════════════════════════════


@application.before_request
def _track_request_start():
    """Record when each request started."""
    request._start_time = time.time()


@application.after_request
def _track_request_end(response):
    """Increment Prometheus counters after every request."""
    try:
        duration = time.time() - getattr(request, "_start_time", time.time())
        method = request.method
        endpoint = request.path
        status = str(response.status_code)

        # Increment counters
        app_requests_total.labels(method=method, endpoint=endpoint, status=status).inc()
        app_request_duration_seconds.labels(method=method, endpoint=endpoint).observe(duration)
        http_status_codes_total.labels(code=status).inc()

        if response.status_code >= 500:
            app_errors_total.inc()

        # Update APP_STATS for dashboard JSON snapshots
        APP_STATS["total_requests"] += 1
        APP_STATS["total_request_time"] += duration
        if response.status_code < 400:
            APP_STATS["success_requests"] += 1
        else:
            APP_STATS["failed_requests"] += 1
    except Exception:
        pass

    return response


@application.errorhandler(Exception)
def _track_exception(e):
    """Count uncaught exceptions."""
    try:
        app_exceptions_total.inc()
        APP_STATS["exceptions"] += 1
    except Exception:
        pass
    return Response("Internal Server Error", status=500)


# ══════════════════════════════════════════════════════════════
# ROUTES  —  only links and redirections live here
# ══════════════════════════════════════════════════════════════


@application.get("/")
def home():
    """Main dashboard page."""
    return render_template("index.html")


@application.route("/monitor/status", methods=["GET", "POST"])
def monitor_status():
    """
    CI / monitoring webhook.
    Delegates entirely to agent_monitor.handle_monitor_status().
    """
    from agent_monitor import handle_monitor_status
    return handle_monitor_status()


@application.get("/health")
def health_check():
    """Health check endpoint."""
    return Response("Healthy", status=200, content_type="text/plain")


@application.get("/metrics", endpoint="app_prometheus_metrics")
def prometheus_metrics():
    """Prometheus scrape endpoint."""
    return Response(
        generate_latest(),
        content_type=CONTENT_TYPE_LATEST,
    )


# ══════════════════════════════════════════════════════════════
# AI AGENT MONITOR ROUTES
# ══════════════════════════════════════════════════════════════


@application.route('/dashboard/agents')
def agents_dashboard():
    """AI Agent Monitor dashboard page."""
    return render_template("index.html")


@application.route('/api/scan', methods=['POST'])
def scan_agents():
    """
    Scan for AI agents
    
    POST request body:
    {
        "agent_names": "gpt-agent.js, claude-handler.py",
        "agent_paths": "/src/agents, ./lib/ai"
    }
    """
    try:
        data = request.get_json()
        
        if not data:
            return jsonify({
                'error': 'No JSON data provided',
                'success': False
            }), 400

        agent_names = data.get('agent_names', '')
        agent_paths = data.get('agent_paths', '')

        result = scanner.scan_agents(agent_names, agent_paths)
        
        app_requests_total.labels(method='POST', endpoint='/api/scan', status='200').inc()
        return jsonify(result), 200 if result.get('success') else 400

    except Exception as e:
        application.logger.error(f"Scan error: {str(e)}")
        app_exceptions_total.inc()
        return jsonify({'error': str(e), 'success': False}), 500


@application.route('/api/dashboard', methods=['GET'])
def get_dashboard():
    """Get complete dashboard data"""
    try:
        dashboard_data = scanner.get_dashboard_data()
        return jsonify(dashboard_data), 200
    except Exception as e:
        application.logger.error(f"Dashboard error: {str(e)}")
        app_exceptions_total.inc()
        return jsonify({'error': str(e)}), 500


@application.route('/api/metrics/system', methods=['GET'])
def get_system_metrics():
    """Get system metrics"""
    try:
        metrics = scanner.get_system_metrics()
        return jsonify(metrics), 200
    except Exception as e:
        application.logger.error(f"System metrics error: {str(e)}")
        app_exceptions_total.inc()
        return jsonify({'error': str(e)}), 500


@application.route('/api/metrics/tokens', methods=['GET'])
def get_token_metrics():
    """Get token metrics"""
    try:
        metrics = scanner.get_token_metrics()
        return jsonify(metrics), 200
    except Exception as e:
        application.logger.error(f"Token metrics error: {str(e)}")
        app_exceptions_total.inc()
        return jsonify({'error': str(e)}), 500


@application.route('/api/metrics/requests', methods=['GET'])
def get_request_metrics():
    """Get request metrics"""
    try:
        metrics = scanner.get_request_metrics()
        return jsonify(metrics), 200
    except Exception as e:
        application.logger.error(f"Request metrics error: {str(e)}")
        app_exceptions_total.inc()
        return jsonify({'error': str(e)}), 500


@application.route('/api/agents', methods=['GET'])
def get_agents():
    """Get all scanned agents"""
    try:
        agents = [scanner._agent_to_dict(agent) for agent in scanner.agents]
        return jsonify({
            'agents': agents,
            'count': len(agents),
            'timestamp': time.time()
        }), 200
    except Exception as e:
        application.logger.error(f"Get agents error: {str(e)}")
        app_exceptions_total.inc()
        return jsonify({'error': str(e)}), 500


@application.route('/api/agents/<agent_id>', methods=['GET'])
def get_agent(agent_id):
    """Get specific agent details"""
    try:
        agent = next((a for a in scanner.agents if a.id == agent_id), None)
        if agent:
            return jsonify(scanner._agent_to_dict(agent)), 200
        else:
            return jsonify({'error': 'Agent not found'}), 404
    except Exception as e:
        application.logger.error(f"Get agent error: {str(e)}")
        app_exceptions_total.inc()
        return jsonify({'error': str(e)}), 500


@application.route('/api/requests', methods=['GET'])
def get_requests():
    """Get request history"""
    try:
        limit = request.args.get('limit', 20, type=int)
        requests_list = [scanner._request_to_dict(req) for req in scanner.requests[:limit]]
        return jsonify({
            'requests': requests_list,
            'count': len(requests_list),
            'timestamp': time.time()
        }), 200
    except Exception as e:
        application.logger.error(f"Get requests error: {str(e)}")
        app_exceptions_total.inc()
        return jsonify({'error': str(e)}), 500


@application.route('/api/providers', methods=['GET'])
def get_providers():
    """Get provider information"""
    try:
        providers = scanner.get_providers_summary()
        return jsonify({
            'providers': providers,
            'count': len(providers),
            'timestamp': time.time()
        }), 200
    except Exception as e:
        application.logger.error(f"Get providers error: {str(e)}")
        app_exceptions_total.inc()
        return jsonify({'error': str(e)}), 500


@application.route('/api/report', methods=['GET'])
def get_report():
    """Get text report"""
    try:
        report = scanner.get_detailed_report()
        return jsonify({
            'report': report,
            'timestamp': time.time()
        }), 200
    except Exception as e:
        application.logger.error(f"Get report error: {str(e)}")
        app_exceptions_total.inc()
        return jsonify({'error': str(e)}), 500


@application.route('/api/report/download', methods=['GET'])
def download_report():
    """Download report as JSON file"""
    try:
        report_bytes = scanner.save_report()
        return send_file(
            __import__('io').BytesIO(report_bytes),
            mimetype='application/json',
            as_attachment=True,
            download_name=f'agent_report_{int(time.time())}.json'
        )
    except Exception as e:
        application.logger.error(f"Download report error: {str(e)}")
        app_exceptions_total.inc()
        return jsonify({'error': str(e)}), 500


@application.route('/api/status', methods=['GET'])
def get_status():
    """Get scanner status"""
    try:
        status = {
            'status': 'running',
            'agents_count': len(scanner.agents),
            'active_agents': sum(1 for agent in scanner.agents if agent.active),
            'total_requests': len(scanner.requests),
            'timestamp': time.time()
        }
        return jsonify(status), 200
    except Exception as e:
        application.logger.error(f"Get status error: {str(e)}")
        app_exceptions_total.inc()
        return jsonify({'error': str(e)}), 500


@application.route('/api/refresh', methods=['POST'])
def refresh_metrics():
    """Refresh metrics for current agents"""
    try:
        if scanner.agents:
            scanner.generate_metrics()
            return jsonify({
                'success': True,
                'metrics': {
                    'cpu': scanner.metrics.cpu,
                    'memory': scanner.metrics.memory,
                    'storage': scanner.metrics.storage,
                    'used_tokens': scanner.metrics.used_tokens,
                    'total_tokens': scanner.metrics.total_tokens,
                    'rpm': scanner.metrics.rpm,
                    'rph': scanner.metrics.rph,
                    'rpd': scanner.metrics.rpd
                },
                'timestamp': time.time()
            }), 200
        else:
            return jsonify({'error': 'No agents to refresh'}), 400
    except Exception as e:
        application.logger.error(f"Refresh metrics error: {str(e)}")
        app_exceptions_total.inc()
        return jsonify({'error': str(e)}), 500


@application.route('/api/clear', methods=['POST'])
def clear_data():
    """Clear all scanned data"""
    try:
        scanner.agents = []
        scanner.requests = []
        scanner.providers = {}
        return jsonify({
            'success': True,
            'message': 'Data cleared',
            'timestamp': time.time()
        }), 200
    except Exception as e:
        application.logger.error(f"Clear data error: {str(e)}")
        app_exceptions_total.inc()
        return jsonify({'error': str(e)}), 500


# ══════════════════════════════════════════════════════════════
# ERROR HANDLERS
# ══════════════════════════════════════════════════════════════


@application.errorhandler(404)
def not_found(error):
    """Handle 404 errors"""
    return jsonify({
        'error': 'Not found',
        'status': 404
    }), 404


@application.errorhandler(500)
def internal_error(error):
    """Handle 500 errors"""
    application.logger.error(f"Internal error: {str(error)}")
    return jsonify({
        'error': 'Internal server error',
        'status': 500
    }), 500


# ══════════════════════════════════════════════════════════════
# WSGI entry point
# ══════════════════════════════════════════════════════════════

if __name__ == "__main__":
    port  = int(os.environ.get("PORT", "5000"))
    debug = os.environ.get("FLASK_DEBUG") == "1"
    application.run(host="0.0.0.0", port=port, debug=debug)
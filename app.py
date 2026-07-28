"""Public Flask entry point for SentinelOps-Lite."""

import os

from flask import jsonify, render_template

from agent_monitor import application


@application.get("/")
def home():
    """Render the main application page."""
    return render_template("index.html")


@application.get("/api")
def api():
    """Small version endpoint used by smoke tests."""
    return jsonify(
        message="Hello from SentinelOps-Lite!",
        status="running",
        version=os.getenv("APP_VERSION", "1.0.0"),
        build=os.getenv("BUILD_NUMBER", "unknown"),
    )


if __name__ == "__main__":
    port = int(os.getenv("PORT", "5000"))
    application.run(
        host="0.0.0.0",
        port=port,
        debug=os.getenv("FLASK_DEBUG") == "1",
    )

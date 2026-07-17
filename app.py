import os

import sys

from pathlib import Path

from flask import render_template


# Add project root to Python path

BASE_DIR = Path(__file__).resolve().parent


if str(BASE_DIR) not in sys.path:

    sys.path.insert(0, str(BASE_DIR))


# Import Flask application from agent_monitor.py

from agent_monitor import application


# Serve your index.html at "/"

@application.route("/")

def home():

    return render_template("index.html")


# Optional API

@application.route("/api")

def api():

    return {

        "message": "Hello from SentinelOps-Lite!",

        "status": "running"

    }


# Start Application

if __name__ == "__main__":

    port = int(os.environ.get("PORT", "5000"))

    application.run(

        host="0.0.0.0",

        port=port,

        debug=os.environ.get("FLASK_DEBUG") == "1"

    )

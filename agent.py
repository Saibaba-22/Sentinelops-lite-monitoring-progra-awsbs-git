"""
SentinelOps-Lite AI Agent Gate
------------------------------
Runs after unit tests finish. Reads the test result summary, sends it
to Gemini (Google AI Studio API key), and gets a simple APPROVE /
REJECT decision.
"""
import os
import sys
import json
from datetime import datetime
import requests
import pathlib

from google import genai

RESULTS_FILE = "test_results.txt"

if not os.path.exists(RESULTS_FILE):
    print(f"ERROR: {RESULTS_FILE} not found. Did the test step run first?")
    sys.exit(1)

with open(RESULTS_FILE, "r") as f:
    test_output = f.read()

api_key = os.environ.get("GEMINI_API_KEY")
if not api_key:
    print("ERROR: GEMINI_API_KEY environment variable is not set.")
    sys.exit(1)

client = genai.Client(api_key=api_key)


def save_status(status, tokens=0, requests_count=1):
    payload = {
        "status": status,
        "tokens": tokens,
        "requests": requests_count,
        "api_keys": 1,
        "last_run": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "model": "gemini-2.5-flash",
    }

    monitor_url = os.getenv("MONITOR_API_URL", "http://localhost:5000/monitor/status")

    try:
        requests.post(
            monitor_url,
            json=payload,
            timeout=10,
        )
    except Exception as e:
        print(f"Unable to update monitoring: {e}")


prompt = f"""
You are a release-approval agent for a CI/CD pipeline.
Below is the raw output of the automated test suite.
Rules:
- If ALL tests passed, respond APPROVE.
- If ANY test failed, respond REJECT.
- Respond with a single word only: APPROVE or REJECT.
- On a second line, give a one-sentence reason.

Test output:
{test_output}
"""

response = client.models.generate_content(
    model="gemini-2.5-flash",
    contents=prompt,
)

decision_text = response.text.strip()
decision_word = decision_text.splitlines()[0].strip().upper()

tokens = 0
try:
    usage = response.usage_metadata
    tokens = usage.prompt_token_count + usage.candidates_token_count
except Exception:
    pass

stats = {
    "status": "Approved" if decision_word == "APPROVE" else "Rejected",
    "requests": 1,
    "api_keys": 1,
    "model": "gemini-2.5-flash",
    "last_run": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    "api_key_name": "GEMINI_API_KEY",
    "tokens": tokens,
}

# Persist the decision next to this script (overridable via env).
stats_file = pathlib.Path(
    os.getenv("AGENT_STATS_PATH", str(pathlib.Path(__file__).resolve().parent / "agent_stats.json"))
)
with open(stats_file, "w") as f:
    json.dump(stats, f, indent=4)

print("----- AI Agent Decision -----")
print(decision_text)
print("------------------------------")

with open("agent_decision.txt", "w") as f:
    f.write(decision_word)

if decision_word != "APPROVE":
    print("Agent rejected the release. Stopping pipeline.")
    sys.exit(1)

save_status(stats["status"], stats["tokens"])
print("Agent approved the release. Continuing to deployment.")
sys.exit(0)

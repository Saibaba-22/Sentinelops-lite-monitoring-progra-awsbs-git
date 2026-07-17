"""
review_agent.py — Pre-deployment review gate for SentinelOps-Lite.

Runs a battery of deterministic checks on the project BEFORE deployment:
  1. All required files exist.
  2. Every Python file compiles (syntax).
  3. All YAML / JSON config files parse.
  4. test_app.py passes (pytest).
  5. The Flask app imports and core endpoints (/health, /metrics, /api/status)
     respond correctly.
  6. Dockerrun.aws.json has no leftover placeholder image URI.

For every problem it reports: which FILE, which LINE (when known), what was
EXPECTED and what was ACTUALLY found.

Decision:
  * No errors  -> prints "PROCEED TO DEPLOY" and exits 0.
  * Any error  -> prints the findings and exits 1 (pipeline must stop).

Optional: if GEMINI_API_KEY is set, an LLM summary is appended (never required).
"""
import os
import re
import sys
import json
import glob
import subprocess
import py_compile
from datetime import datetime

try:
    import yaml
except ImportError:
    yaml = None

ROOT = os.path.dirname(os.path.abspath(__file__))
os.chdir(ROOT)

# --------------------------------------------------------------------------
# Inventory of everything that must be present and healthy.
# --------------------------------------------------------------------------
REQUIRED_FILES = [
    "app.py", "agent.py", "agent_monitor.py", "requirements.txt", "test_app.py",
    "docker/Dockerfile", "docker/docker-compose.yml", "docker/nginx/nginx.conf",
    "Dockerrun.aws.json", "docker-compose.yml", "deployment/Procfile", "deployment/deploy.sh",
    ".ebextensions/01-nginx.config", ".ebextensions/02-logging.config",
    "monitoring/__init__.py", "monitoring/metrics.py", "monitoring/collectors.py",
    "monitoring/agent_state.py",
    "monitoring/prometheus/prometheus.yml", "monitoring/prometheus/alert.rules.yml",
    "monitoring/prometheus/recording.rules.yml",
    "monitoring/grafana/provisioning/datasources/datasource.yml",
    "monitoring/grafana/provisioning/dashboards/dashboard.yml",
    "monitoring/grafana/dashboards/system-dashboard.json",
    "monitoring/grafana/dashboards/application-dashboard.json",
    "monitoring/grafana/dashboards/ai-agent-dashboard.json",
    "monitoring/grafana/dashboards/deployment-dashboard.json",
    "monitoring/grafana/provisioning/dashboards/dashboards.json",
    "static/css/dashboard.css", "static/js/dashboard.js",
    "templates/dashboard.html", "templates/index.html",
    "docs/README.md", "docs/DEPLOYMENT.md", "docs/TROUBLESHOOTING.md",
    "review_agent.py", "final_agent.py",
]

YAML_FILES = [
    "monitoring/prometheus/prometheus.yml",
    "monitoring/prometheus/alert.rules.yml",
    "monitoring/prometheus/recording.rules.yml",
    "monitoring/grafana/provisioning/datasources/datasource.yml",
    "monitoring/grafana/provisioning/dashboards/dashboard.yml",
    "docker-compose.yml",
]
JSON_FILES = [
    "Dockerrun.aws.json",
    "monitoring/grafana/dashboards/system-dashboard.json",
    "monitoring/grafana/dashboards/application-dashboard.json",
    "monitoring/grafana/dashboards/ai-agent-dashboard.json",
    "monitoring/grafana/dashboards/deployment-dashboard.json",
    "monitoring/grafana/provisioning/dashboards/dashboards.json",
]
PY_FILES = [f for f in glob.glob("**/*.py", recursive=True)
            if not f.startswith("logs") and not f.startswith(".pytest_cache")]


class Finding:
    def __init__(self, severity, file, line, check, expected, actual):
        self.severity = severity          # "error" | "warning"
        self.file = file
        self.line = line
        self.check = check
        self.expected = expected
        self.actual = actual

    def render(self):
        loc = self.file if self.line in (None, 0) else f"{self.file}:{self.line}"
        return (f"  [{self.severity.upper()}] {loc}\n"
                f"      check    : {self.check}\n"
                f"      expected : {self.expected}\n"
                f"      actual   : {self.actual}")


findings = []


def add(severity, file, line, check, expected, actual):
    findings.append(Finding(severity, file, line, check, expected, actual))


# --------------------------------------------------------------------------
# 1. Required files present
# --------------------------------------------------------------------------
def check_files():
    for f in REQUIRED_FILES:
        if not os.path.exists(f):
            add("error", f, 0, "file exists", "file is present", "file is MISSING")


# --------------------------------------------------------------------------
# 2. Python syntax
# --------------------------------------------------------------------------
def check_python_syntax():
    for f in PY_FILES:
        try:
            py_compile.compile(f, doraise=True)
        except py_compile.PyCompileError as e:
            msg = str(e)
            m = re.search(r"line (\d+)", msg)
            line = int(m.group(1)) if m else 0
            add("error", f, line, "Python compiles", "no syntax errors",
                msg.strip().splitlines()[-1] if msg.strip() else "compile error")


# --------------------------------------------------------------------------
# 3. YAML / JSON parse
# --------------------------------------------------------------------------
def check_yaml():
    if yaml is None:
        add("warning", "pyyaml", 0, "YAML library", "pyyaml installed",
            "pyyaml missing — YAML files not validated")
        return
    for f in YAML_FILES:
        if not os.path.exists(f):
            continue
        try:
            list(yaml.safe_load_all(open(f)))
        except yaml.YAMLError as e:
            line = getattr(getattr(e, "problem_mark", None), "line", 0)
            add("error", f, (line or 0) + 1, "YAML parses",
                "valid YAML document", str(e).splitlines()[0])


def check_json():
    for f in JSON_FILES:
        if not os.path.exists(f):
            continue
        try:
            json.load(open(f))
        except json.JSONDecodeError as e:
            add("error", f, e.lineno, "JSON parses",
                "valid JSON", f"{e.msg} (col {e.colno})")


# --------------------------------------------------------------------------
# 4. Unit tests (pytest) — capture file:line of failures
# --------------------------------------------------------------------------
def check_tests():
    if not os.path.exists("test_app.py"):
        return
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", "test_app.py", "-q",
         "--tb=short", "-p", "no:cacheprovider"],
        capture_output=True, text=True,
    )
    out = proc.stdout + proc.stderr
    if proc.returncode == 0:
        return  # all green

    # Collect detailed traceback locations: File "x", line N
    for m in re.finditer(r'File "([^"]+)", line (\d+)', out):
        add("error", m.group(1), int(m.group(2)), "test passes",
            "code under test behaves as expected",
            "assertion / runtime error at this location")

    # Ensure at least one top-level finding exists even if no traceback matched
    if not any(f.check == "test passes" for f in findings):
        summary = next((l for l in out.splitlines() if "failed" in l or "error" in l.lower()),
                       "pytest exited non-zero")
        add("error", "test_app.py", 0, "test passes", "all tests pass", summary.strip())


# --------------------------------------------------------------------------
# 5. Flask app imports & core endpoints respond
# --------------------------------------------------------------------------
def check_app_endpoints():
    try:
        from app import application
    except Exception as e:
        add("error", "app.py", 0, "app imports", "Flask app imports cleanly",
            f"{type(e).__name__}: {e}")
        return
    try:
        client = application.test_client()
    except Exception as e:
        add("error", "agent_monitor.py", 0, "test client", "app builds a test client",
            f"{type(e).__name__}: {e}")
        return

    checks = [
        ("/health", 200, "text/html"),
        ("/metrics", 200, "text/plain"),
        ("/api/status", 200, "application/json"),
        ("/agent/status", 200, "application/json"),
    ]
    for path, exp_status, exp_ct in checks:
        try:
            r = client.get(path)
            ok = r.status_code == exp_status and r.content_type.startswith(exp_ct)
            if not ok:
                add("error", "agent_monitor.py", 0, f"GET {path}",
                    f"HTTP {exp_status} / {exp_ct}", f"got HTTP {r.status_code} / {r.content_type}")
        except Exception as e:
            add("error", "agent_monitor.py", 0, f"GET {path}",
                f"HTTP {exp_status}", f"{type(e).__name__}: {e}")

    # /metrics must actually expose our custom application metrics
    try:
        r = client.get("/metrics")
        if b"app_requests_total" not in r.data:
            add("error", "monitoring/metrics.py", 0, "/metrics content",
                "exposes app_* metrics", "app_requests_total not found in exposition")
    except Exception:
        pass


# --------------------------------------------------------------------------
# 6. Dockerrun placeholder check
# --------------------------------------------------------------------------
def check_dockerrun():
    f = "Dockerrun.aws.json"
    if not os.path.exists(f):
        return
    try:
        text = open(f).read()
    except Exception:
        return
    if "REPLACE_WITH_ECR_IMAGE_URI" in text:
        line = text.splitlines().index(
            [l for l in text.splitlines() if "REPLACE_WITH_ECR_IMAGE_URI" in l][0]) + 1
        # The placeholder is expected in committed code; deploy.sh substitutes it.
        deploy_fixes = os.path.exists("deployment/deploy.sh") and \
            "REPLACE_WITH_ECR_IMAGE_URI" in open("deployment/deploy.sh").read()
        if deploy_fixes:
            add("warning", f, line, "image URI configured",
                "real ECR image URI injected at deploy time",
                "placeholder kept by design; deployment/deploy.sh substitutes it "
                "during 'eb deploy' (non-blocking)")
        else:
            add("error", f, line, "image URI configured",
                "real ECR image URI (e.g. <acct>.dkr.ecr.<region>.amazonaws.com/...:latest)",
                "still contains placeholder and deploy.sh does not substitute it")


# --------------------------------------------------------------------------
# Optional LLM summary (never required)
# --------------------------------------------------------------------------
def llm_summary(report_text):
    key = os.getenv("GEMINI_API_KEY")
    if not key:
        return None
    try:
        from google import genai
        client = genai.Client(api_key=key)
        resp = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=(
                "You are a senior release engineer. Summarise the following "
                "pre-deployment review in 3 bullet points (plain text):\n\n"
                + report_text
            ),
        )
        return resp.text.strip()
    except Exception as e:
        return f"(LLM summary skipped: {e})"


# --------------------------------------------------------------------------
# Main
# --------------------------------------------------------------------------
def main():
    print("=" * 70)
    print(" SentinelOps-Lite — PRE-DEPLOYMENT REVIEW")
    print(" " + datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    print("=" * 70)

    check_files()
    check_python_syntax()
    check_yaml()
    check_json()
    check_tests()
    check_app_endpoints()
    check_dockerrun()

    errors = [f for f in findings if f.severity == "error"]
    warnings = [f for f in findings if f.severity == "warning"]

    lines = []
    lines.append("Files checked : %d" % len(REQUIRED_FILES))
    lines.append("Python files  : %d" % len(PY_FILES))
    lines.append("Errors        : %d" % len(errors))
    lines.append("Warnings      : %d" % len(warnings))
    lines.append("")

    if errors:
        lines.append("FINDINGS (blocking):")
        for f in errors:
            lines.append(f.render())
        lines.append("")
        lines.append("DECISION: DO NOT DEPLOY — fix the errors above, then re-run.")
    else:
        lines.append("DECISION: PROCEED TO DEPLOY — all checks passed.")
        if warnings:
            lines.append("")
            lines.append("Non-blocking warnings:")
            for f in warnings:
                lines.append(f.render())

    report = "\n".join(lines)
    print(report)

    summary = llm_summary(report)
    if summary:
        print("\n--- LLM SUMMARY ---\n" + summary)

    # Persist the report for the pipeline / auditors.
    try:
        with open("review_report.txt", "w") as fh:
            fh.write(report + "\n")
    except Exception:
        pass

    sys.exit(1 if errors else 0)


if __name__ == "__main__":
    main()

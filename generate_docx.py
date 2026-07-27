from docx import Document
from docx.shared import Inches, Pt, Cm, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.style import WD_STYLE_TYPE
import datetime

doc = Document()

# ─── Page Setup ───
for section in doc.sections:
    section.top_margin = Cm(2.54)
    section.bottom_margin = Cm(2.54)
    section.left_margin = Cm(2.54)
    section.right_margin = Cm(2.54)

# ─── Style Customization ───
style = doc.styles['Normal']
font = style.font
font.name = 'Calibri'
font.size = Pt(11)
font.color.rgb = RGBColor(0x33, 0x33, 0x33)

for level in range(1, 4):
    heading_style = doc.styles[f'Heading {level}']
    heading_style.font.name = 'Calibri'
    heading_style.font.color.rgb = RGBColor(0x0F, 0x17, 0x2A)

# ─── Helper functions ───
def add_table_with_header(doc, headers, rows, col_widths=None):
    table = doc.add_table(rows=1 + len(rows), cols=len(headers))
    table.style = 'Light Grid Accent 1'
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    
    # Header row
    for i, header in enumerate(headers):
        cell = table.rows[0].cells[i]
        cell.text = header
        for paragraph in cell.paragraphs:
            for run in paragraph.runs:
                run.font.bold = True
                run.font.size = Pt(10)
    
    # Data rows
    for r_idx, row in enumerate(rows):
        for c_idx, value in enumerate(row):
            cell = table.rows[r_idx + 1].cells[c_idx]
            cell.text = str(value)
            for paragraph in cell.paragraphs:
                for run in paragraph.runs:
                    run.font.size = Pt(10)
    
    return table

def add_code_block(doc, code_text):
    p = doc.add_paragraph()
    run = p.add_run(code_text)
    run.font.name = 'Consolas'
    run.font.size = Pt(9)
    run.font.color.rgb = RGBColor(0x1E, 0x29, 0x3B)
    p.paragraph_format.left_indent = Cm(1)
    p.paragraph_format.space_before = Pt(4)
    p.paragraph_format.space_after = Pt(4)
    # Add shading
    from docx.oxml.ns import qn
    from lxml import etree
    shading = etree.SubElement(p._element.get_or_add_pPr(), qn('w:shd'))
    shading.set(qn('w:fill'), '1E293B')
    shading.set(qn('w:val'), 'clear')
    run.font.color.rgb = RGBColor(0xE2, 0xE8, 0xF0)
    return p

def add_bullet(doc, text, level=0):
    p = doc.add_paragraph(text, style='List Bullet')
    p.paragraph_format.left_indent = Cm(1.27 + level * 0.63)
    return p

def add_numbered(doc, text):
    p = doc.add_paragraph(text, style='List Number')
    return p

# ══════════════════════════════════════════════════════════════
# TITLE PAGE
# ══════════════════════════════════════════════════════════════
for _ in range(6):
    doc.add_paragraph()

title = doc.add_paragraph()
title.alignment = WD_ALIGN_PARAGRAPH.CENTER
run = title.add_run('SentinelOps-Lite')
run.font.size = Pt(36)
run.font.bold = True
run.font.color.rgb = RGBColor(0x38, 0xBD, 0xF8)

subtitle = doc.add_paragraph()
subtitle.alignment = WD_ALIGN_PARAGRAPH.CENTER
run = subtitle.add_run('Multi-Cloud AI-Powered CI/CD Monitoring Platform')
run.font.size = Pt(18)
run.font.color.rgb = RGBColor(0x94, 0xA3, 0xB8)

doc.add_paragraph()

meta = doc.add_paragraph()
meta.alignment = WD_ALIGN_PARAGRAPH.CENTER
run = meta.add_run(f'Project Documentation — {datetime.date.today().strftime("%B %d, %Y")}')
run.font.size = Pt(12)
run.font.color.rgb = RGBColor(0x94, 0xA3, 0xB8)

doc.add_paragraph()

meta2 = doc.add_paragraph()
meta2.alignment = WD_ALIGN_PARAGRAPH.CENTER
run = meta2.add_run('Cloud Providers: AWS Elastic Beanstalk | Azure App Service')
run.font.size = Pt(12)
run.font.color.rgb = RGBColor(0x22, 0xC5, 0x5E)

doc.add_page_break()

# ══════════════════════════════════════════════════════════════
# TABLE OF CONTENTS
# ══════════════════════════════════════════════════════════════
doc.add_heading('Table of Contents', level=1)
toc_items = [
    '1. Project Overview',
    '2. Project Architecture',
    '3. Project Work Flow',
    '4. Tech Stack',
    '5. Commands',
    '6. Background Process',
    '7. Result',
    '8. Errors and Solutions',
    '9. Outcomes',
    '10. Learning',
]
for item in toc_items:
    p = doc.add_paragraph(item)
    p.paragraph_format.space_after = Pt(2)

doc.add_page_break()

# ══════════════════════════════════════════════════════════════
# 1. PROJECT OVERVIEW
# ══════════════════════════════════════════════════════════════
doc.add_heading('1. Project Overview', level=1)

doc.add_heading('What is SentinelOps-Lite?', level=2)
doc.add_paragraph(
    'SentinelOps-Lite is a multi-cloud, AI-powered CI/CD monitoring platform that '
    'automates deployment validation, error diagnosis, and infrastructure observability '
    'across AWS Elastic Beanstalk and Azure App Service environments. It integrates '
    'Prometheus metrics collection, Grafana dashboard visualization, and Gemini AI agents '
    'to provide intelligent go/no-go deployment decisions and real-time system monitoring.'
)

doc.add_heading('Key Capabilities', level=2)
add_bullet(doc, 'Multi-Cloud Deployment — single GitHub Actions pipeline deploys to AWS or Azure based on selection')
add_bullet(doc, 'AI-Powered Release Gates — Gemini AI agents (pre-deploy, error, final) validate deployments')
add_bullet(doc, 'Auto-Provisioned Monitoring — Grafana dashboards show data immediately after deploy with zero manual setup')
add_bullet(doc, 'Real-Time Observability — Prometheus scrapes Flask app, node-exporter, and agent metrics every 10 seconds')
add_bullet(doc, 'Public Monitor Dashboard — /monitor/status endpoint shows live data in browser (no auth needed)')
add_bullet(doc, 'CI Agent Integration — /monitor/status POST endpoint receives agent state with token-based authentication')

doc.add_heading('Problem Solved', level=2)
doc.add_paragraph(
    'Before SentinelOps-Lite, deployments required manual Grafana datasource configuration '
    'after every deploy. Internal Docker networking URLs (172.17.0.1, localhost, host.docker.internal) '
    'failed in production ECS/Azure environments, leaving dashboards empty until someone manually '
    'added a Prometheus connection. The /monitor/status endpoint returned 403 Forbidden when browsed, '
    'blocking visibility into deployment health.'
)
doc.add_paragraph(
    'SentinelOps-Lite resolves all three issues: (1) Grafana auto-provisioning via $__env{} '
    'env var interpolation and deploy script URL injection, (2) correct external URL usage instead '
    'of broken internal IPs, (3) public GET handler for /monitor/status alongside the authenticated POST handler.'
)

# ══════════════════════════════════════════════════════════════
# 2. PROJECT ARCHITECTURE
# ══════════════════════════════════════════════════════════════
doc.add_heading('2. Project Architecture', level=1)

doc.add_heading('Multi-Container Architecture', level=2)
doc.add_paragraph(
    'The application runs as a multi-container Docker deployment with 5 services '
    'coordinated by an nginx reverse proxy:'
)

add_table_with_header(doc,
    ['Container', 'Image', 'Port', 'Purpose'],
    [
        ['nginx', 'nginx:1.27-alpine', '80 → 80', 'Reverse proxy — routes /, /prometheus/, /grafana/, /monitor/'],
        ['app', 'Custom Flask image', '5000 → 5000', 'Flask application + Prometheus metrics + AI agent endpoints'],
        ['prometheus', 'prom/prometheus:v2.53.0', '9090 → 9090', 'Metrics scraper — collects from app and node-exporter'],
        ['grafana', 'grafana/grafana:11.1.0', '3000 → 3000', 'Dashboard visualization — auto-provisioned datasource + dashboards'],
        ['node-exporter', 'prom/node-exporter:v1.8.0', '9100 → 9100', 'Host system metrics (CPU, memory, disk, network)'],
    ]
)

doc.add_heading('Network Routing', level=2)
doc.add_paragraph('All external traffic enters through nginx on port 80. Nginx routes requests to appropriate containers:')

add_table_with_header(doc,
    ['URL Path', 'Routes To', 'Description'],
    [
        ['/', 'app:5000', 'Flask application home page'],
        ['/monitor/', 'app:5000', 'Monitor dashboard (GET) + CI POST receiver'],
        ['/prometheus/', 'prometheus:9090', 'Prometheus UI (sub-path via --web.external-url)'],
        ['/grafana/', 'grafana:3000', 'Grafana dashboards (sub-path via GF_SERVER_SERVE_FROM_SUB_PATH)'],
        ['/metrics', 'app:5000', 'Prometheus exposition format'],
        ['/health', 'app:5000', 'Lightweight health probe for load balancers'],
        ['/api/status', 'app:5000', 'JSON aggregated status snapshot'],
        ['/agent/status', 'app:5000', 'AI agent state JSON'],
    ]
)

doc.add_heading('Grafana Auto-Provisioning Architecture', level=2)
doc.add_paragraph(
    'Grafana uses a built-in feature called provisioning. When the container starts, it reads YAML '
    'configuration files from /etc/grafana/provisioning/ and automatically creates datasources and '
    'loads dashboards. The key innovation is using $__env{PROMETHEUS_URL} in the datasource YAML, '
    'which reads the PROMETHEUS_URL environment variable from the container at startup.'
)
doc.add_paragraph('The deploy scripts dynamically resolve the correct external URL (EB CNAME for AWS, Azure hostname for Azure) and inject it into the docker-compose files before deployment. This means Grafana always connects to the correct Prometheus URL — no manual configuration ever needed.')

add_code_block(doc, 
    '# datasource.yml — the key fix\n'
    'apiVersion: 1\n'
    'datasources:\n'
    '  - name: Prometheus\n'
    '    type: prometheus\n'
    '    uid: prometheus\n'
    '    access: proxy\n'
    '    url: $__env{PROMETHEUS_URL}    # ← reads env var at startup\n'
    '    isDefault: true\n'
    '    editable: true')

doc.add_heading('AWS Deployment Architecture', level=2)
doc.add_paragraph(
    'AWS Elastic Beanstalk uses the docker-compose.yml file at the repo root. '
    'The deploy-aws.sh script: (1) builds and pushes the Docker image, '
    '(2) resolves the EB environment CNAME, (3) replaces all placeholders in docker-compose.yml, '
    '(4) selects the AWS nginx config, (5) deploys via eb deploy. '
    'EB reads docker-compose.yml and spins up all 5 containers as ECS tasks.'
)

doc.add_heading('Azure Deployment Architecture', level=2)
doc.add_paragraph(
    'Azure App Service uses docker-compose.azure.yml for multi-container deployment. '
    'The deploy-azure.sh script: (1) builds and pushes the Docker image, '
    '(2) resolves the Azure hostname, (3) replaces all placeholders in docker-compose.azure.yml, '
    '(4) selects the Azure nginx config, (5) deploys via az webapp config container set. '
    'Azure terminates TLS at the front end — containers communicate internally on plain HTTP.'
)

doc.add_heading('AI Agent Architecture', level=2)
doc.add_paragraph(
    'Three Gemini AI agents run in the GitHub Actions pipeline at different stages:'
)

add_table_with_header(doc,
    ['Agent', 'Trigger', 'Purpose', 'Input', 'Output'],
    [
        ['Pre-deploy Agent', 'Before deployment', 'Validate readiness — go/no-go decision', 'Test results, monitor data', 'Decision: approved/rejected'],
        ['Error Agent', 'On deploy failure', 'Diagnose failure root cause', 'Error logs, cloud status', 'Analysis + remediation suggestion'],
        ['Final Agent', 'After successful deploy', 'Post-deploy health verification', 'App URL, monitor data', 'Health report + metrics snapshot'],
    ]
)

# ══════════════════════════════════════════════════════════════
# 3. PROJECT WORK FLOW
# ══════════════════════════════════════════════════════════════
doc.add_heading('3. Project Work Flow', level=1)

doc.add_heading('GitHub Actions Pipeline Flow', level=2)
doc.add_paragraph('The pipeline has 3 jobs that run sequentially:')

add_numbered(doc, 'Pre-deploy checks — Runs test_agent.py with Gemini AI to validate readiness')
add_numbered(doc, 'Build, push, deploy — Builds Docker image, pushes to Docker Hub, deploys to selected cloud')
add_numbered(doc, 'Post-deploy verification — Health check + final_agent.py with Gemini AI for post-validation')

doc.add_heading('AWS Deployment Flow (detailed)', level=2)
steps_aws = [
    'Developer triggers workflow_dispatch → selects "aws"',
    'GitHub Actions runner checks out repository',
    'Pipeline validates all required variables and secrets',
    'Configures AWS credentials via aws-actions/configure-aws-credentials',
    'Installs awsebcli and awscli',
    'Calls deploy/deploy-aws.sh:',
    '    a. Builds Docker image from docker/Dockerfile',
    '    b. Logs in to Docker Hub and pushes image',
    '    c. Resolves EB environment CNAME (e.g., agent.eba-wu4pmszn.us-east-1.elasticbeanstalk.com)',
    '    d. Derives PROMETHEUS_URL, GF_SERVER_DOMAIN, GF_SERVER_ROOT_URL from CNAME',
    '    e. Copies nginx-aws.conf as the active nginx config',
    '    f. Replaces all placeholders in docker-compose.yml via sed',
    '    g. Verifies no placeholders remain (fails if any found)',
    '    h. Detects ECS platform via aws elasticbeanstalk list-available-solution-stacks',
    '    i. Runs eb init, eb create (if needed), eb deploy',
    'Pipeline resolves final app URL from EB CNAME',
    'Verifies Grafana is healthy and Prometheus datasource is auto-provisioned',
    'Runs post-deploy final_agent.py for AI health verification',
    'Uploads all artifacts (logs, reports) for review',
]
for step in steps_aws:
    if step.startswith('    '):
        p = doc.add_paragraph(step.strip())
        p.paragraph_format.left_indent = Cm(2)
    else:
        add_numbered(doc, step)

doc.add_heading('Azure Deployment Flow (detailed)', level=2)
steps_azure = [
    'Developer triggers workflow_dispatch → selects "azure"',
    'GitHub Actions runner checks out repository',
    'Pipeline validates all required variables and secrets',
    'Azure login via azure/login with service principal credentials',
    'Calls deploy/deploy-azure.sh:',
    '    a. Builds Docker image from docker/Dockerfile',
    '    b. Logs in to Docker Hub and pushes image',
    '    c. Resolves Azure hostname via az webapp show (e.g., app.azurewebsites.net)',
    '    d. Derives PROMETHEUS_URL, GF_SERVER_DOMAIN, GF_SERVER_ROOT_URL from hostname',
    '    e. Copies nginx-azure.conf as the active nginx config',
    '    f. Replaces all placeholders in docker-compose.azure.yml via sed',
    '    g. Verifies no placeholders remain',
    '    h. Runs az webapp config container set --multicontainer-config-type COMPOSE',
    '    i. Runs az webapp restart',
    'Pipeline resolves final app URL from Azure hostname',
    'Verifies Grafana is healthy and Prometheus datasource is auto-provisioned',
    'Runs post-deploy final_agent.py for AI health verification',
    'Uploads all artifacts for review',
]
for step in steps_azure:
    if step.startswith('    '):
        p = doc.add_paragraph(step.strip())
        p.paragraph_format.left_indent = Cm(2)
    else:
        add_numbered(doc, step)

doc.add_heading('Monitoring Data Flow', level=2)
doc.add_paragraph(
    'Prometheus scrapes metrics from the Flask app (/metrics endpoint) and node-exporter every 10 seconds. '
    'Grafana reads from Prometheus via the auto-provisioned datasource. The /monitor/status GET endpoint '
    'reads from agent_state_store and collectors.build_status() to show real-time data. '
    'CI agents POST to /monitor/status with X-Monitor-Token authentication to update agent state and Prometheus metrics.'
)

# ══════════════════════════════════════════════════════════════
# 4. TECH STACK
# ══════════════════════════════════════════════════════════════
doc.add_heading('4. Tech Stack', level=1)

add_table_with_header(doc,
    ['Category', 'Technology', 'Version / Details', 'Purpose'],
    [
        ['Application', 'Flask', 'Python 3.11', 'Web framework — serves app, metrics, monitoring endpoints'],
        ['Application', 'Werkzeug', 'Latest', 'WSGI utility — error handling'],
        ['AI Engine', 'Google Gemini', '2.5-flash', 'AI agent — go/no-go decisions, error analysis, health checks'],
        ['Metrics', 'Prometheus Client', 'Latest', 'Python Prometheus client — custom metrics exposition'],
        ['Metrics Server', 'Prometheus', 'v2.53.0', 'Metrics collection and storage — scrapes every 10s'],
        ['Visualization', 'Grafana', '11.1.0', 'Dashboard rendering — auto-provisioned datasource & dashboards'],
        ['Host Metrics', 'Node Exporter', 'v1.8.0', 'System metrics — CPU, memory, disk, network'],
        ['Reverse Proxy', 'Nginx', '1.27-alpine', 'Routing — /, /prometheus/, /grafana/, /monitor/'],
        ['Containerization', 'Docker', 'Multi-container', '5-service architecture via docker-compose'],
        ['CI/CD', 'GitHub Actions', 'workflow_dispatch', 'Pipeline — build, push, deploy, verify'],
        ['AWS Compute', 'Elastic Beanstalk', 'running ECS platform', 'Multi-container Docker hosting (ECS task definition)'],
        ['AWS CLI', 'EB CLI + AWS CLI', 'Latest', 'Deployment automation — eb init, eb deploy'],
        ['Azure Compute', 'App Service (Linux)', 'Docker Compose', 'Multi-container hosting via docker-compose'],
        ['Azure CLI', 'Azure CLI', 'Latest', 'Deployment automation — az webapp config container set'],
        ['Registry', 'Docker Hub', 'saibaba22/sentinelops-lite-...', 'Image storage and distribution'],
        ['Agent Auth', 'MONITOR_TOKEN', 'X-Monitor-Token header', 'POST endpoint authentication for CI agents'],
    ]
)

# ══════════════════════════════════════════════════════════════
# 5. COMMANDS
# ══════════════════════════════════════════════════════════════
doc.add_heading('5. Commands', level=1)

doc.add_heading('Local Development', level=2)
add_code_block(doc, '# Run locally with docker-compose\ndocker-compose up --build')
add_code_block(doc, '# Check app health\ncurl http://localhost/health')
add_code_block(doc, '# View Prometheus metrics\ncurl http://localhost/metrics')
add_code_block(doc, '# View monitoring dashboard\nopen http://localhost/monitor/status')

doc.add_heading('AWS Deployment (Manual)', level=2)
add_code_block(doc, 
    '# Set environment variables\n'
    'export APP_NAME=sentinelops-lite\n'
    'export ENV_NAME=sentinelops-lite-prod\n'
    'export AWS_REGION=us-east-1\n'
    'export REPOSITORY=sentinelops-lite-monitoring-progra-awsbs-git\n'
    'export DOCKERHUB_USERNAME=saibaba22\n'
    'export DOCKERHUB_TOKEN=your-token\n'
    'export GITHUB_SHA=abc1234\n'
    'export MONITOR_TOKEN_AWS=your-monitor-secret\n\n'
    '# Run deployment\n'
    'bash deploy/deploy-aws.sh')

doc.add_heading('Azure Deployment (Manual)', level=2)
add_code_block(doc,
    '# Set environment variables\n'
    'export AZURE_WEBAPP_NAME=sentinelops-monitor\n'
    'export AZURE_RESOURCE_GROUP=sentinelops-rg\n'
    'export REPOSITORY=sentinelops-lite-monitoring-progra-awsbs-git\n'
    'export DOCKERHUB_USERNAME=saibaba22\n'
    'export DOCKERHUB_TOKEN=your-token\n'
    'export GITHUB_SHA=abc1234\n'
    'export MONITOR_TOKEN_AZURE=your-monitor-secret\n\n'
    '# Run deployment\n'
    'bash deploy/deploy-azure.sh')

doc.add_heading('CI Agent — POST Monitoring Event', level=2)
add_code_block(doc,
    '# Send agent state to /monitor/status (with auth token)\n'
    'curl -X POST http://agent.eba-wu4pmszn.us-east-1.elasticbeanstalk.com/monitor/status \\\n'
    '  -H "X-Monitor-Token: $MONITOR_TOKEN" \\\n'
    '  -H "Content-Type: application/json" \\\n'
    '  -d \'{"agent_name":"pre-deploy", "stage":"pre_deploy", "status":"approved", "cloud":"aws", "provider":"gemini", "model":"gemini-2.5-flash", "total_tokens":1520, "requests":2, "execution_time_seconds":3.2}\'')

doc.add_heading('Verification Commands', level=2)
add_code_block(doc,
    '# Check Grafana health\n'
    'curl http://agent.eba-.../grafana/api/health\n\n'
    '# List Grafana datasources (should show Prometheus auto-provisioned)\n'
    'curl -u admin:admin123 http://agent.eba-.../grafana/api/datasources\n\n'
    '# Check Prometheus targets\n'
    'curl http://agent.eba-.../prometheus/api/v1/targets\n\n'
    '# Browse monitoring dashboard\n'
    'open http://agent.eba-.../monitor/status')

doc.add_heading('GitHub Actions Pipeline Trigger', level=2)
add_code_block(doc,
    '# Trigger via GitHub CLI\n'
    'gh workflow run "SentinelOps-Lite Multi-Cloud Pipeline" -f cloud=aws\n'
    'gh workflow run "SentinelOps-Lite Multi-Cloud Pipeline" -f cloud=azure')

# ══════════════════════════════════════════════════════════════
# 6. BACKGROUND PROCESS
# ══════════════════════════════════════════════════════════════
doc.add_heading('6. Background Process', level=1)

doc.add_heading('Metrics Background Collector', level=2)
doc.add_paragraph(
    'The Flask app starts a background thread at boot via start_metrics_updater(interval=5). '
    'This thread runs every 5 seconds and updates system-level Prometheus metrics including:'
)
add_bullet(doc, 'app_uptime_seconds — application uptime counter')
add_bullet(doc, 'python_process_resident_memory_bytes — process memory usage')
add_bullet(doc, 'python_process_cpu_percent — CPU percentage')
add_bullet(doc, 'python_thread_count — active thread count')
add_bullet(doc, 'app_active_sessions / app_active_users — session tracking')
add_bullet(doc, 'app_restart_total — restart counter')

doc.add_heading('Prometheus Scrape Cycle', level=2)
doc.add_paragraph(
    'Prometheus runs a continuous scrape cycle with a 10-second interval. '
    'It collects metrics from three targets:'
)
add_table_with_header(doc,
    ['Target', 'URL', 'Metrics Path', 'Interval'],
    [
        ['prometheus (self)', 'localhost:9090', '/prometheus/metrics', '10s'],
        ['flask-app', 'app:5000', '/metrics', '10s'],
        ['node-exporter', 'node-exporter:9100', '/metrics', '10s'],
    ]
)

doc.add_heading('Grafana Dashboard Refresh', level=2)
doc.add_paragraph(
    'Grafana dashboards auto-refresh every 10 seconds (configured in the dashboard JSON). '
    'The dashboard provider scans /var/lib/grafana/dashboards/ every 10 seconds for new or updated JSON files.'
)

doc.add_heading('/monitor/status Auto-Refresh', level=2)
doc.add_paragraph(
    'The /monitor/status GET endpoint HTML page includes a JavaScript auto-refresh that reloads '
    'the page every 10 seconds, ensuring the browser always shows current data without manual refresh.'
)

# ══════════════════════════════════════════════════════════════
# 7. RESULT
# ══════════════════════════════════════════════════════════════
doc.add_heading('7. Result', level=1)

doc.add_heading('What Works After All Fixes', level=2)

add_table_with_header(doc,
    ['Feature', 'Before Fix', 'After Fix', 'Cloud'],
    [
        ['Grafana datasource', 'Empty — manual connection needed every deploy', 'Auto-provisioned — data shows on login', 'Both'],
        ['Prometheus URL', '172.17.0.1:9090 (broken in ECS)', 'External EB/Azure URL (auto-resolved by deploy script)', 'Both'],
        ['/monitor/status', '403 Forbidden when browsed', 'Dark-themed dashboard with real values, auto-refresh', 'Both'],
        ['Prometheus scrape targets', '172.17.0.1:5000 (broken)', 'app:5000 (Docker service names)', 'Both'],
        ['nginx routing', 'Missing /monitor/ route', 'Full routing: /, /monitor/, /prometheus/, /grafana/', 'Both'],
        ['MONITOR_TOKEN in container', 'Not passed — POST auth always failed', 'Injected from GitHub secrets via deploy scripts', 'Both'],
        ['Azure monitoring', 'No Prometheus/Grafana deployed', 'Full 5-container stack with docker-compose.azure.yml', 'Azure'],
        ['Cloud selection', 'Separate pipelines for AWS and Azure', 'Single pipeline with cloud selection dropdown', 'Both'],
    ]
)

doc.add_heading('Access URLs After Deployment', level=2)

add_table_with_header(doc,
    ['Endpoint', 'AWS URL', 'Azure URL'],
    [
        ['App Home', 'http://agent.eba-.../', 'https://app.azurewebsites.net/'],
        ['Monitor Dashboard', 'http://agent.eba-.../monitor/status', 'https://app.azurewebsites.net/monitor/status'],
        ['Prometheus UI', 'http://agent.eba-.../prometheus/', 'https://app.azurewebsites.net/prometheus/'],
        ['Grafana Dashboards', 'http://agent.eba-.../grafana/ (admin/admin123)', 'https://app.azurewebsites.net/grafana/'],
        ['Metrics', 'http://agent.eba-.../metrics', 'https://app.azurewebsites.net/metrics'],
        ['Health', 'http://agent.eba-.../health', 'https://app.azurewebsites.net/health'],
        ['Agent Status JSON', 'http://agent.eba-.../agent/status', 'https://app.azurewebsites.net/agent/status'],
        ['API Status JSON', 'http://agent.eba-.../api/status', 'https://app.azurewebsites.net/api/status'],
    ]
)

# ══════════════════════════════════════════════════════════════
# 8. ERRORS AND SOLUTIONS
# ══════════════════════════════════════════════════════════════
doc.add_heading('8. Errors and Solutions', level=1)

doc.add_heading('Error 1: Grafana Dashboards Empty After Deploy', level=2)
doc.add_paragraph('Symptom: After deploying to AWS EB or Azure, Grafana dashboards show "No data" until manually adding a Prometheus connection.')
doc.add_paragraph('Root Cause: The datasource.yml had a hardcoded URL (http://172.17.0.1:9090/prometheus) that does not work in ECS/Azure networking. Grafana could not connect to Prometheus.')
doc.add_paragraph('Solution: Changed datasource.yml URL to $__env{PROMETHEUS_URL}. The deploy scripts dynamically resolve the correct external URL (EB CNAME or Azure hostname) and inject it as a container environment variable. Grafana reads this env var at startup and auto-connects.')

doc.add_heading('Error 2: Internal Docker IPs Do Not Work (172.17.0.1, localhost, host.docker.internal)', level=2)
doc.add_paragraph('Symptom: All three internal networking approaches failed to connect Grafana to Prometheus.')
add_table_with_header(doc,
    ['URL Tried', 'Why It Failed'],
    [
        ['http://prometheus:9090', 'Hostname resolves but missing /prometheus/ path prefix (Prometheus uses --web.external-url=/prometheus/)'],
        ['http://host.docker.internal:9090', 'Docker Desktop feature — not available in ECS or Azure App Service'],
        ['http://172.17.0.1:9090/prometheus', 'Docker bridge gateway IP — does not route properly in ECS networking'],
        ['http://localhost:9090', 'localhost inside Grafana container = Grafana itself, not Prometheus'],
    ]
)
doc.add_paragraph('Solution: Only the external URL works because nginx reverse-proxies correctly. Use the external EB/Azure URL as PROMETHEUS_URL.')

doc.add_heading('Error 3: Prometheus Scrape Targets Using Broken IPs', level=2)
doc.add_paragraph('Symptom: Prometheus could not scrape metrics from Flask app and node-exporter.')
doc.add_paragraph('Root Cause: prometheus.yml used 172.17.0.1:5000 and 172.17.0.1:9100 as scrape targets — same broken Docker bridge gateway.')
doc.add_paragraph('Solution: Changed to Docker service names: app:5000 and node-exporter:9100. These resolve correctly via Docker links in both ECS and Azure.')

doc.add_heading('Error 4: /monitor/status Returns 403 Forbidden', level=2)
doc.add_paragraph('Symptom: Browsing http://agent.eba-.../monitor/status returns 403 Forbidden.')
doc.add_paragraph('Root Cause: Two issues — (1) the route only accepted POST requests (methods=["POST"]), browsers send GET; (2) the POST handler requires X-Monitor-Token header for authentication, browsers do not send this.')
doc.add_paragraph('Solution: Added a new GET handler (monitor_status_get) that serves a public HTML dashboard with real values, no auth required. The existing POST handler remains unchanged for CI agents with token auth. Also added nginx /monitor/ location block to ensure requests reach Flask.')

doc.add_heading('Error 5: Dockerrun.aws.json and docker-compose.yml Conflict', level=2)
doc.add_paragraph('Symptom: EB uses docker-compose.yml but Dockerrun.aws.json also exists, causing confusion.')
doc.add_paragraph('Root Cause: When both files exist at the repo root, EB prioritizes Dockerrun.aws.json and ignores docker-compose.yml. This means monitoring containers may not deploy correctly.')
doc.add_paragraph('Solution: Remove Dockerrun.aws.json from the repo. Keep docker-compose.yml for AWS EB and docker-compose.azure.yml for Azure. EB expects the exact filename "docker-compose.yml" — do not rename to docker-compose.aws.yml.')

doc.add_heading('Error 6: MONITOR_TOKEN Not Available in Flask Container', level=2)
doc.add_paragraph('Symptom: POST to /monitor/status with correct X-Monitor-Token still returns 401 unauthorized.')
doc.add_paragraph('Root Cause: The Flask app checks os.getenv("MONITOR_TOKEN") but the environment variable was never passed into the container via docker-compose.yml.')
doc.add_paragraph('Solution: Added MONITOR_TOKEN=replace_with_monitor_token to docker-compose.yml app service. Deploy scripts replace it with MONITOR_TOKEN_AWS or MONITOR_TOKEN_AZURE from GitHub secrets.')

# ══════════════════════════════════════════════════════════════
# 9. OUTCOMES
# ══════════════════════════════════════════════════════════════
doc.add_heading('9. Outcomes', level=1)

doc.add_heading('Zero Manual Configuration After Deploy', level=2)
doc.add_paragraph(
    'After every deployment (AWS or Azure), Grafana automatically shows data on dashboards '
    'without any manual datasource setup. The pipeline resolves URLs, injects them into '
    'container env vars, and Grafana reads them at startup via $__env{} interpolation.'
)

doc.add_heading('Single Unified Pipeline for Both Clouds', level=2)
doc.add_paragraph(
    'One GitHub Actions workflow handles both AWS and Azure deployment with a cloud selection '
    'dropdown. The deploy-aws.sh and deploy-azure.sh scripts share the same pattern '
    '(build → push → resolve URL → inject → deploy → verify) but use cloud-specific tools.'
)

doc.add_heading('Public Monitoring Visibility', level=2)
doc.add_paragraph(
    'The /monitor/status endpoint now serves a beautiful dark-themed HTML dashboard that '
    'auto-refreshes every 10 seconds. It shows real application stats and all AI agent states '
    'without requiring authentication. This gives immediate visibility into deployment health.'
)

doc.add_heading('Secure CI Agent Communication', level=2)
doc.add_paragraph(
    'The POST handler for /monitor/status is protected by X-Monitor-Token authentication. '
    'The token flows from GitHub secrets → deploy scripts → container env vars → Flask app, '
    'ensuring only authorized CI agents can update monitoring state.'
)

doc.add_heading('Production-Ready Observability Stack', level=2)
doc.add_paragraph(
    'The complete 5-container stack (nginx + app + prometheus + grafana + node-exporter) '
    'runs on both clouds with correct networking, proper sub-path routing, and automated '
    'configuration. Prometheus scrapes every 10s, Grafana auto-provisioned, dashboards '
    'pre-loaded, /monitor/status public — all working end-to-end.'
)

# ══════════════════════════════════════════════════════════════
# 10. LEARNING
# ══════════════════════════════════════════════════════════════
doc.add_heading('10. Learning', level=1)

doc.add_heading('Docker Networking in Production is Different from Local', level=2)
doc.add_paragraph(
    'Internal Docker networking IPs (172.17.0.1, host.docker.internal, localhost) work on '
    'local development machines but fail in production ECS or Azure App Service environments. '
    'The only reliable way to connect services in production is through: (1) Docker service names '
    'for inter-container communication (app:5000, prometheus:9090), and (2) external URLs '
    'through the reverse proxy for cross-network access (Grafana → Prometheus).'
)

doc.add_heading('Prometheus Sub-Path Changes All API Endpoints', level=2)
doc.add_paragraph(
    'When Prometheus uses --web.external-url=/prometheus/, ALL its endpoints move under that path: '
    '/prometheus/api/v1/query instead of /api/v1/query, /prometheus/targets instead of /targets. '
    'Simply pointing to http://prometheus:9090 (without the /prometheus/ path) will fail. '
    'This is a common mistake when configuring Grafana datasources for sub-path Prometheus deployments.'
)

doc.add_heading('Grafana $__env{} is the Cleanest Auto-Provisioning Method', level=2)
doc.add_paragraph(
    'Grafana supports several ways to dynamically configure datasources: environment variable '
    'interpolation ($__env{}), secret interpolation ($__secret{}), and the Admin HTTP API. '
    'The $__env{} approach is the cleanest because it requires zero API calls, zero manual '
    'configuration, and works with the existing provisioning file system. The deploy script '
    'just sets the right environment variable — Grafana handles everything else.'
)

doc.add_heading('EB Reads docker-compose.yml by Exact Name Only', level=2)
doc.add_paragraph(
    'Elastic Beanstalk expects the file to be named exactly "docker-compose.yml". '
    'Renaming it to "docker-compose.aws.yml" causes EB to not find it and deployment fails. '
    'Also, when both Dockerrun.aws.json and docker-compose.yml exist, EB uses Dockerrun '
    'and ignores docker-compose. The lesson: understand which format your EB platform uses '
    'and ensure only that file exists at the repo root.'
)

doc.add_heading('Dual-Method Endpoints (GET + POST) Solve Auth Conflicts', level=2)
doc.add_paragraph(
    'An endpoint that serves both public browsers and authenticated CI agents needs two handlers: '
    'GET for public access (HTML dashboard, no auth) and POST for machine access (JSON, with auth). '
    'Trying to serve both through a single route leads to 403 errors for browsers or security '
    'bypasses for CI agents. Flask supports multiple method handlers on the same route path.'
)

doc.add_heading('Deploy Script Pattern: Build → Resolve → Inject → Deploy', level=2)
doc.add_paragraph(
    'The most reliable deployment pattern for dynamic monitoring URLs is: (1) Build the Docker image, '
    '(2) Resolve the cloud hostname/CNAME from the cloud API, (3) Inject the resolved URL into '
    'configuration files via sed placeholder replacement, (4) Deploy. This pattern works identically '
    'for both AWS (EB CNAME) and Azure (App Service hostname) and requires zero manual URL configuration.'
)

doc.add_heading('nginx Location Blocks Prevent 403s on Custom Routes', level=2)
doc.add_paragraph(
    'When adding custom routes like /monitor/ to a Flask app behind nginx, you must add '
    'an explicit nginx location block for that path. Without it, nginx may block the request '
    'before it reaches Flask, resulting in 403 Forbidden. Always map all custom Flask routes '
    'in the nginx reverse proxy configuration.'
)

doc.add_heading('Environment Variable Chain: GitHub Secrets → Deploy Script → Container → Application', level=2)
doc.add_paragraph(
    'Secrets and configuration values flow through a 4-step chain: (1) Stored as GitHub secrets, '
    '(2) Passed as env vars to the deploy script in the pipeline, (3) Injected into docker-compose '
    'via sed placeholder replacement, (4) Read by the application via os.getenv(). '
    'Each step must be explicitly wired — missing any step in the chain causes the value to '
    'not reach its destination (e.g., MONITOR_TOKEN not available in Flask container).'
)

# ══════════════════════════════════════════════════════════════
# APPENDIX
# ══════════════════════════════════════════════════════════════
doc.add_page_break()
doc.add_heading('Appendix A: Complete File List', level=1)

add_table_with_header(doc,
    ['#', 'File', 'Cloud', 'Status', 'Purpose'],
    [
        ['1', 'monitoring/grafana/provisioning/datasources/datasource.yml', 'Both', 'CHANGED', 'Grafana datasource — $__env{PROMETHEUS_URL}'],
        ['2', 'monitoring/grafana/provisioning/dashboards/dashboard.yml', 'Both', 'Same', 'Dashboard auto-provision provider'],
        ['3', 'monitoring/grafana/dashboards/sentinelops-overview.json', 'Both', 'Same', 'Pre-built Grafana dashboard'],
        ['4', 'monitoring/prometheus/prometheus.yml', 'Both', 'CHANGED', 'Fixed scrape targets — app:5000, node-exporter:9100'],
        ['5', 'docker-compose.yml', 'AWS', 'CHANGED', 'EB deployment — added PROMETHEUS_URL + MONITOR_TOKEN placeholders'],
        ['6', 'docker-compose.azure.yml', 'Azure', 'NEW', 'Azure App Service deployment — same structure with Azure nginx'],
        ['7', 'docker/nginx/nginx-aws.conf', 'AWS', 'CHANGED', 'Reverse proxy — added /monitor/ location block'],
        ['8', 'docker/nginx/nginx-azure.conf', 'Azure', 'NEW', 'Reverse proxy — HTTPS headers + /monitor/ block'],
        ['9', 'deploy/deploy-aws.sh', 'AWS', 'CHANGED', 'Deploy script — resolves CNAME + injects URLs + MONITOR_TOKEN'],
        ['10', 'deploy/deploy-azure.sh', 'Azure', 'NEW', 'Deploy script — resolves hostname + injects URLs + MONITOR_TOKEN'],
        ['11', '.github/workflows/pipeline.yml', 'Both', 'CHANGED', 'Unified pipeline — calls deploy scripts + Grafana verification'],
        ['12', 'agent_monitor.py', 'Both', 'CHANGED', 'Added GET handler for /monitor/status — public HTML dashboard'],
    ]
)

doc.add_heading('Appendix B: GitHub Variables & Secrets', level=1)

doc.add_heading('Variables (11 — all existing)', level=2)
add_table_with_header(doc,
    ['Variable', 'Example Value', 'Used By'],
    [
        ['DOCKERHUB_USERNAME', 'saibaba22', 'Both — docker login'],
        ['DOCKERHUB_REPOSITORY', 'sentinelops-lite-...-git', 'Both — image name'],
        ['PYTHON_VERSION', '3.11', 'Both — setup-python'],
        ['APP_HEALTH_PATH', '/health', 'Both — health check'],
        ['AWS_APP_NAME', 'sentinelops-lite', 'AWS — eb init'],
        ['AWS_ENV_NAME', 'sentinelops-lite-prod', 'AWS — eb deploy'],
        ['AWS_REGION', 'us-east-1', 'AWS — eb init'],
        ['AZURE_WEBAPP_NAME', 'sentinelops-monitor', 'Azure — az webapp'],
        ['AZURE_RESOURCE_GROUP', 'sentinelops-rg', 'Azure — az webapp'],
        ['AI_PROVIDER', 'gemini', 'Both — AI agents'],
        ['AI_MODEL', 'gemini-2.5-flash', 'Both — AI agents'],
    ]
)

doc.add_heading('Secrets (9 — all existing)', level=2)
add_table_with_header(doc,
    ['Secret', 'Used By'],
    [
        ['DOCKERHUB_TOKEN', 'Both — docker push auth'],
        ['AWS_ACCESS_KEY_ID', 'AWS — configure-aws-credentials'],
        ['AWS_SECRET_ACCESS_KEY', 'AWS — configure-aws-credentials'],
        ['AZURE_CREDENTIALS', 'Azure — azure/login (JSON service principal)'],
        ['GEMINI_API_KEY', 'Both — AI agents'],
        ['MONITOR_API_URL_AWS', 'AWS — AI agent POST URL'],
        ['MONITOR_TOKEN_AWS', 'AWS — /monitor/status POST auth + Flask container MONITOR_TOKEN'],
        ['MONITOR_API_URL_AZURE', 'Azure — AI agent POST URL'],
        ['MONITOR_TOKEN_AZURE', 'Azure — /monitor/status POST auth + Flask container MONITOR_TOKEN'],
    ]
)

# ─── Save ───
doc.save('/home/user/SentinelOps-Lite-Project-Documentation.docx')
print("✅ Document saved successfully!")

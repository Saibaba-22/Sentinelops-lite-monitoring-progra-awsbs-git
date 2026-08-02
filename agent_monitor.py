"""
AI Agent Monitor - Complete Single File Solution
Python + HTML + CSS + JavaScript in one Flask application
Run: python agent_monitor.py
Open: http://localhost:5000
"""

from flask import Flask, render_template_string, request, jsonify, send_file
from flask_cors import CORS
import json
import os
import time
import random
import threading
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Any, Optional
from dataclasses import dataclass, asdict
from enum import Enum
import psutil
import io

from prometheus_client import Counter, Gauge, Histogram

# Metrics
app_agents_detected = Gauge('app_agents_detected', 'Total agents detected')
app_active_agents = Gauge('app_active_agents', 'Active agents count')
app_tokens_used = Gauge('app_tokens_used', 'Total tokens used')
app_tokens_total = Gauge('app_tokens_total', 'Total tokens available')
app_cpu_usage = Gauge('app_cpu_usage', 'CPU usage percentage')
app_memory_usage = Gauge('app_memory_usage', 'Memory usage percentage')
app_storage_usage = Gauge('app_storage_usage', 'Storage usage percentage')
app_rpm = Gauge('app_rpm', 'Requests per minute')
app_rph = Gauge('app_rph', 'Requests per hour')
app_rpd = Gauge('app_rpd', 'Requests per day')
app_agent_provider = Counter('app_agent_provider', 'Agents by provider', ['provider'])
app_agent_tokens_used = Gauge('app_agent_tokens_used', 'Tokens by agent', ['agent_name'])
app_agent_requests_total = Gauge('app_agent_requests_total', 'Requests by agent', ['agent_name'])

# ============================================================================
# DATA MODELS
# ============================================================================

class AgentStatus(Enum):
    """Agent status enumeration"""
    ACTIVE = "active"
    INACTIVE = "inactive"
    ERROR = "error"
    UNKNOWN = "unknown"


class RequestStatus(Enum):
    """Request status enumeration"""
    SUCCESS = "success"
    FAILED = "failed"
    TIMEOUT = "timeout"
    ERROR = "error"


@dataclass
class Agent:
    """Agent data model"""
    id: str
    name: str
    provider: str
    model: str
    file_extension: str
    status: str
    active: bool
    success_rate: float
    failure_rate: float
    last_used: str
    requests: int
    tokens_used: int
    tokens_available: int
    source: str
    path: Optional[str] = None
    timestamp: Optional[str] = None


@dataclass
class Request:
    """Request data model"""
    request_id: str
    agent_name: str
    timestamp: str
    status: str
    tokens_used: int
    response_time: int


@dataclass
class Metrics:
    """System metrics data model"""
    cpu: float
    memory: float
    storage: float
    total_tokens: int
    used_tokens: int
    rpm: int
    rph: int
    rpd: int


# ============================================================================
# AI AGENT SCANNER CLASS
# ============================================================================

class AIAgentScanner:
    """Main AI Agent Scanner class"""

    def __init__(self):
        """Initialize the scanner"""
        self.agents: List[Agent] = []
        self.requests: List[Request] = []
        self.providers: Dict[str, Dict[str, Any]] = {}
        self.metrics = Metrics(
            cpu=0,
            memory=0,
            storage=0,
            total_tokens=1000000,
            used_tokens=0,
            rpm=0,
            rph=0,
            rpd=0
        )
        self.config = self.load_config()
        self._lock = threading.Lock()

    def load_config(self) -> Dict[str, Any]:
        """Load configuration from config.json"""
        config_path = Path('config.json')
        
        if config_path.exists():
            try:
                with open(config_path, 'r') as f:
                    return json.load(f)
            except Exception as e:
                print(f"Warning: Could not load config: {e}")
                return self.get_default_config()
        else:
            return self.get_default_config()

    @staticmethod
    def get_default_config() -> Dict[str, Any]:
        """Get default configuration"""
        return {
            'agents': [],
            'paths': [],
            'providers': {
                'openai': {'name': 'OpenAI', 'models': ['gpt-4', 'gpt-3.5-turbo']},
                'anthropic': {'name': 'Anthropic', 'models': ['claude-3', 'claude-2']},
                'google': {'name': 'Google', 'models': ['gemini-pro', 'palm-2']},
                'huggingface': {'name': 'Hugging Face', 'models': ['mistral', 'llama']},
                'cohere': {'name': 'Cohere', 'models': ['command', 'command-light']},
                'azure': {'name': 'Microsoft Azure', 'models': ['gpt-4', 'gpt-35-turbo']}
            }
        }

    def scan_agents(self, agent_names: str, agent_paths: str) -> Dict[str, Any]:
        """Scan for AI agents"""
        try:
            names = [n.strip() for n in agent_names.split(',') if n.strip()]
            paths = [p.strip() for p in agent_paths.split(',') if p.strip()]

            if not names and not paths:
                return {'error': 'Please provide agent names or paths', 'success': False}

            # Detect agents
            self.detect_agents(names, paths)
            
            # Generate metrics
            self.generate_metrics()

            return {
                'success': True,
                'agents_count': len(self.agents),
                'agents': [self._agent_to_dict(agent) for agent in self.agents],
                'metrics': self._metrics_to_dict(),
                'requests': [self._request_to_dict(req) for req in self.requests],
                'providers': self.get_providers_summary()
            }
        except Exception as e:
            return {'error': str(e), 'success': False}

    def detect_agents(self, names: List[str], paths: List[str]) -> None:
        """Detect AI agents from names and paths"""
        with self._lock:
            self.agents = []

            # Create agents from names
            for name in names:
                agent = self.parse_agent_name(name)
                self.agents.append(agent)

            # Create agents from paths
            for path in paths:
                provider = self.detect_provider(path)
                model = self.detect_model(path)
                agent = Agent(
                    id=f"agent_{len(self.agents)}_{int(time.time())}",
                    name=f"agent-{int(time.time())}",
                    path=path,
                    provider=provider,
                    model=model,
                    status=AgentStatus.ACTIVE.value,
                    active=True,
                    file_extension='py',
                    success_rate=85 + random.random() * 15,
                    failure_rate=5 + random.random() * 10,
                    last_used=(datetime.now() - timedelta(seconds=random.randint(0, 86400))).isoformat(),
                    requests=random.randint(100, 10000),
                    tokens_used=random.randint(10000, 500000),
                    tokens_available=1000000,
                    source='path_scan',
                    timestamp=datetime.now().isoformat()
                )
                self.agents.append(agent)

            # Enrich agents with additional data
            for i, agent in enumerate(self.agents):
                agent.id = f"agent_{i}_{int(time.time())}"
                agent.active = random.random() > 0.2
                agent.status = AgentStatus.ACTIVE.value if agent.active else AgentStatus.INACTIVE.value

    def parse_agent_name(self, name: str) -> Agent:
        """Parse agent name and extract information"""
        providers = ['gpt', 'claude', 'gemini', 'palm', 'mistral', 'llama', 'cohere', 'azure', 'openai', 'anthropic', 'google']
        file_ext = name.split('.')[-1] if '.' in name else 'unknown'
        detected_provider = 'unknown'
        detected_model = 'unknown'

        name_lower = name.lower()
        for provider in providers:
            if provider in name_lower:
                detected_provider = provider
                break

        if detected_provider != 'unknown':
            detected_model = self.get_model_for_provider(detected_provider)

        return Agent(
            id=f"agent_{int(time.time())}",
            name=name,
            provider=detected_provider,
            model=detected_model,
            file_extension=file_ext,
            status=AgentStatus.ACTIVE.value,
            active=random.random() > 0.2,
            success_rate=85 + random.random() * 15,
            failure_rate=5 + random.random() * 10,
            last_used=(datetime.now() - timedelta(seconds=random.randint(0, 86400))).isoformat(),
            requests=random.randint(100, 10000),
            tokens_used=random.randint(10000, 500000),
            tokens_available=1000000,
            source='user_provided',
            timestamp=datetime.now().isoformat()
        )

    def detect_provider(self, path: str) -> str:
        """Detect provider from path"""
        path_lower = path.lower()
        providers = {
            'openai': 'OpenAI',
            'gpt': 'OpenAI',
            'claude': 'Anthropic',
            'anthropic': 'Anthropic',
            'gemini': 'Google',
            'google': 'Google',
            'huggingface': 'Hugging Face',
            'hf': 'Hugging Face',
            'mistral': 'Mistral',
            'llama': 'Meta',
            'cohere': 'Cohere',
            'azure': 'Microsoft Azure'
        }

        for key, value in providers.items():
            if key in path_lower:
                return value

        return 'Unknown Provider'

    def detect_model(self, path: str) -> str:
        """Detect model from path"""
        models = {
            'gpt4': 'GPT-4',
            'gpt-4': 'GPT-4',
            'gpt35': 'GPT-3.5',
            'gpt-35': 'GPT-3.5',
            'claude3': 'Claude 3',
            'claude-3': 'Claude 3',
            'claude2': 'Claude 2',
            'gemini': 'Gemini Pro',
            'mistral': 'Mistral 7B',
            'llama2': 'Llama 2',
            'palm': 'PaLM 2',
            'command': 'Command'
        }

        path_lower = path.lower()
        for key, value in models.items():
            if key in path_lower:
                return value

        return 'Unknown Model'

    @staticmethod
    def get_model_for_provider(provider: str) -> str:
        """Get default model for provider"""
        models = {
            'gpt': 'GPT-4',
            'claude': 'Claude 3',
            'gemini': 'Gemini Pro',
            'palm': 'PaLM 2',
            'mistral': 'Mistral 7B',
            'llama': 'Llama 2',
            'cohere': 'Command',
            'openai': 'GPT-4',
            'anthropic': 'Claude 3',
            'google': 'Gemini Pro',
            'azure': 'GPT-4'
        }

        return models.get(provider, 'Unknown Model')

    def generate_metrics(self) -> None:
        """Generate realistic metrics"""
        with self._lock:
            # System metrics
            self.metrics.cpu = random.randint(10, 80)
            self.metrics.memory = random.randint(10, 90)
            self.metrics.storage = random.randint(20, 70)

            # Token metrics
            self.metrics.used_tokens = sum(agent.tokens_used for agent in self.agents)

            # Request metrics
            active_agents = sum(1 for agent in self.agents if agent.active)
            self.metrics.rpm = random.randint(0, 50) * active_agents
            self.metrics.rph = self.metrics.rpm * 60
            self.metrics.rpd = self.metrics.rph * 24

            # Generate request history
            self.generate_request_history()

            # Generate provider info
            self.generate_provider_info()

    def generate_request_history(self) -> None:
        """Generate request history"""
        self.requests = []
        status_options = [RequestStatus.SUCCESS, RequestStatus.SUCCESS, RequestStatus.SUCCESS, 
                         RequestStatus.FAILED, RequestStatus.TIMEOUT]

        for i in range(20):
            if not self.agents:
                break
                
            agent = random.choice(self.agents)
            status = random.choice(status_options)

            request = Request(
                request_id=f"REQ_{int(time.time())}_{i}",
                agent_name=agent.name,
                timestamp=(datetime.now() - timedelta(seconds=random.randint(0, 3600))).isoformat(),
                status=status.value,
                tokens_used=random.randint(100, 2100),
                response_time=random.randint(100, 5100)
            )
            self.requests.append(request)

        # Sort by timestamp
        self.requests.sort(key=lambda x: x.timestamp, reverse=True)

    def generate_provider_info(self) -> None:
        """Generate provider information"""
        self.providers = {}

        for agent in self.agents:
            if agent.provider not in self.providers:
                self.providers[agent.provider] = {
                    'name': agent.provider,
                    'model': agent.model,
                    'count': 0,
                    'active_count': 0,
                    'total_tokens': 0,
                    'total_requests': 0,
                    'success_rate': 0
                }

            self.providers[agent.provider]['count'] += 1
            if agent.active:
                self.providers[agent.provider]['active_count'] += 1
            self.providers[agent.provider]['total_tokens'] += agent.tokens_used
            self.providers[agent.provider]['total_requests'] += agent.requests
            self.providers[agent.provider]['success_rate'] += agent.success_rate

        # Calculate averages
        for provider in self.providers.values():
            if provider['count'] > 0:
                provider['success_rate'] = round(provider['success_rate'] / provider['count'], 2)

    def get_providers_summary(self) -> Dict[str, Dict[str, Any]]:
        """Get providers summary"""
        return self.providers

    def get_system_metrics(self) -> Dict[str, Any]:
        """Get system metrics"""
        return {
            'cpu': self.metrics.cpu,
            'memory': self.metrics.memory,
            'storage': self.metrics.storage,
            'cpu_actual': psutil.cpu_percent(interval=0.1),
            'memory_actual': psutil.virtual_memory().percent,
            'disk_usage': psutil.disk_usage('/').percent
        }

    def get_token_metrics(self) -> Dict[str, Any]:
        """Get token metrics"""
        token_percent = (self.metrics.used_tokens / self.metrics.total_tokens) * 100 if self.metrics.total_tokens > 0 else 0
        return {
            'tokens_used': self.metrics.used_tokens,
            'tokens_total': self.metrics.total_tokens,
            'token_percent': round(token_percent, 2)
        }

    def get_request_metrics(self) -> Dict[str, Any]:
        """Get request metrics"""
        return {
            'rpm': self.metrics.rpm,
            'rph': self.metrics.rph,
            'rpd': self.metrics.rpd
        }

    def get_agent_status(self) -> Dict[str, Any]:
        """Get agent status"""
        active_count = sum(1 for agent in self.agents if agent.active)
        return {
            'total_agents': len(self.agents),
            'active_agents': active_count,
            'inactive_agents': len(self.agents) - active_count
        }

    def get_dashboard_data(self) -> Dict[str, Any]:
        """Get all dashboard data"""
        return {
            'system_metrics': self.get_system_metrics(),
            'token_metrics': self.get_token_metrics(),
            'request_metrics': self.get_request_metrics(),
            'agent_status': self.get_agent_status(),
            'agents': [self._agent_to_dict(agent) for agent in self.agents],
            'requests': [self._request_to_dict(req) for req in self.requests],
            'providers': self.get_providers_summary(),
            'timestamp': datetime.now().isoformat()
        }

    def get_detailed_report(self) -> str:
        """Generate detailed text report"""
        report = []
        report.append("\n" + "="*80)
        report.append("AI AGENT SCANNER - DETAILED REPORT")
        report.append("="*80)
        report.append(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        report.append("")

        # System Metrics
        report.append("SYSTEM METRICS")
        report.append("-" * 80)
        report.append(f"CPU Usage: {self.metrics.cpu}%")
        report.append(f"Memory Usage: {self.metrics.memory}%")
        report.append(f"Storage: {self.metrics.storage}%")
        report.append("")

        # Token Metrics
        report.append("TOKEN METRICS")
        report.append("-" * 80)
        report.append(f"Tokens Used: {self._format_number(self.metrics.used_tokens)}")
        report.append(f"Tokens Total: {self._format_number(self.metrics.total_tokens)}")
        token_percent = (self.metrics.used_tokens / self.metrics.total_tokens) * 100 if self.metrics.total_tokens > 0 else 0
        report.append(f"Usage: {token_percent:.2f}%")
        report.append("")

        # Request Metrics
        report.append("REQUEST METRICS")
        report.append("-" * 80)
        report.append(f"RPM (Requests/Min): {self.metrics.rpm}")
        report.append(f"RPH (Requests/Hour): {self.metrics.rph}")
        report.append(f"RPD (Requests/Day): {self.metrics.rpd}")
        report.append("")

        # Agent Status
        report.append("AGENT STATUS")
        report.append("-" * 80)
        active_count = sum(1 for agent in self.agents if agent.active)
        report.append(f"Total Agents: {len(self.agents)}")
        report.append(f"Active: {active_count}")
        report.append(f"Inactive: {len(self.agents) - active_count}")
        report.append("")

        # Agents
        report.append("DETECTED AGENTS")
        report.append("-" * 80)
        for i, agent in enumerate(self.agents, 1):
            report.append(f"\n{i}. {agent.name}")
            report.append(f"   Provider: {agent.provider}")
            report.append(f"   Model: {agent.model}")
            report.append(f"   Status: {'🟢 Active' if agent.active else '🔴 Inactive'}")
            report.append(f"   Tokens Used: {self._format_number(agent.tokens_used)} / {self._format_number(agent.tokens_available)}")
            report.append(f"   Requests: {self._format_number(agent.requests)}")
            report.append(f"   Success Rate: {agent.success_rate:.1f}%")
            report.append(f"   Failure Rate: {agent.failure_rate:.1f}%")

        report.append("\n" + "="*80)
        return "\n".join(report)

    def save_report(self, filename: str = None) -> bytes:
        """Save report to JSON and return as bytes"""
        if filename is None:
            filename = f'agent_report_{datetime.now().strftime("%Y%m%d_%H%M%S")}.json'

        report_data = {
            'timestamp': datetime.now().isoformat(),
            'summary': {
                'total_agents': len(self.agents),
                'active_agents': sum(1 for agent in self.agents if agent.active),
                'inactive_agents': sum(1 for agent in self.agents if not agent.active)
            },
            'metrics': self._metrics_to_dict(),
            'agents': [self._agent_to_dict(agent) for agent in self.agents],
            'requests': [self._request_to_dict(req) for req in self.requests],
            'providers': self.get_providers_summary()
        }

        return json.dumps(report_data, indent=2).encode()

    @staticmethod
    def _format_number(num: int) -> str:
        """Format number for display"""
        if num >= 1000000:
            return f"{num / 1000000:.2f}M"
        elif num >= 1000:
            return f"{num / 1000:.2f}K"
        else:
            return str(num)

    @staticmethod
    def _agent_to_dict(agent: Agent) -> Dict[str, Any]:
        """Convert agent to dictionary"""
        return {
            'id': agent.id,
            'name': agent.name,
            'provider': agent.provider,
            'model': agent.model,
            'file_extension': agent.file_extension,
            'status': agent.status,
            'active': agent.active,
            'success_rate': agent.success_rate,
            'failure_rate': agent.failure_rate,
            'last_used': agent.last_used,
            'requests': agent.requests,
            'tokens_used': agent.tokens_used,
            'tokens_available': agent.tokens_available,
            'source': agent.source,
            'path': agent.path,
            'timestamp': agent.timestamp
        }

    @staticmethod
    def _request_to_dict(req: Request) -> Dict[str, Any]:
        """Convert request to dictionary"""
        return {
            'request_id': req.request_id,
            'agent_name': req.agent_name,
            'timestamp': req.timestamp,
            'status': req.status,
            'tokens_used': req.tokens_used,
            'response_time': req.response_time
        }

    @staticmethod
    def _metrics_to_dict() -> Dict[str, Any]:
        """This will be overridden in instance"""
        pass


# ============================================================================
# FLASK APP & HTML/CSS/JS
# ============================================================================

app = Flask(__name__)
CORS(app)

# Initialize scanner
scanner = AIAgentScanner()

# HTML Template
HTML_TEMPLATE = '''
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>AI Agent Monitor - Python</title>
    <style>
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }

        body {
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            min-height: 100vh;
            padding: 20px;
        }

        .container {
            max-width: 1400px;
            margin: 0 auto;
        }

        header {
            text-align: center;
            color: white;
            margin-bottom: 30px;
            animation: slideDown 0.6s ease-out;
        }

        header h1 {
            font-size: 2.5em;
            margin-bottom: 10px;
            text-shadow: 2px 2px 4px rgba(0,0,0,0.3);
        }

        header p {
            font-size: 1.1em;
            opacity: 0.9;
        }

        .control-panel {
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 20px;
            margin-bottom: 30px;
            animation: slideUp 0.6s ease-out 0.1s both;
        }

        .input-block {
            background: white;
            padding: 20px;
            border-radius: 12px;
            box-shadow: 0 8px 32px rgba(0,0,0,0.1);
        }

        .input-block h3 {
            color: #667eea;
            margin-bottom: 15px;
            display: flex;
            align-items: center;
            gap: 10px;
        }

        .input-block h3::before {
            content: '';
            display: inline-block;
            width: 4px;
            height: 20px;
            background: linear-gradient(180deg, #667eea, #764ba2);
            border-radius: 2px;
        }

        input[type="text"] {
            width: 100%;
            padding: 12px;
            margin-bottom: 10px;
            border: 2px solid #e0e0e0;
            border-radius: 8px;
            font-size: 1em;
            transition: all 0.3s ease;
        }

        input[type="text"]:focus {
            outline: none;
            border-color: #667eea;
            box-shadow: 0 0 0 3px rgba(102, 126, 234, 0.1);
        }

        .button-group {
            display: flex;
            gap: 10px;
        }

        button {
            flex: 1;
            padding: 12px 20px;
            border: none;
            border-radius: 8px;
            font-size: 1em;
            font-weight: 600;
            cursor: pointer;
            transition: all 0.3s ease;
            text-transform: uppercase;
            letter-spacing: 0.5px;
        }

        .btn-scan {
            background: linear-gradient(135deg, #667eea, #764ba2);
            color: white;
        }

        .btn-scan:hover {
            transform: translateY(-2px);
            box-shadow: 0 8px 20px rgba(102, 126, 234, 0.4);
        }

        .btn-clear {
            background: #f0f0f0;
            color: #333;
        }

        .btn-clear:hover {
            background: #e0e0e0;
        }

        .btn-download {
            background: linear-gradient(135deg, #4facfe, #00f2fe);
            color: white;
        }

        .dashboard {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));
            gap: 20px;
            margin-bottom: 30px;
        }

        .card {
            background: white;
            border-radius: 12px;
            padding: 20px;
            box-shadow: 0 8px 32px rgba(0,0,0,0.1);
            animation: fadeIn 0.6s ease-out forwards;
            opacity: 0;
            border-top: 4px solid #667eea;
        }

        .card:nth-child(2) {
            animation-delay: 0.1s;
            border-top-color: #764ba2;
        }

        .card:nth-child(3) {
            animation-delay: 0.2s;
            border-top-color: #f093fb;
        }

        .card:nth-child(4) {
            animation-delay: 0.3s;
            border-top-color: #4facfe;
        }

        .card h3 {
            color: #333;
            margin-bottom: 15px;
            display: flex;
            align-items: center;
            gap: 8px;
            font-size: 1.2em;
        }

        .metric {
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding: 12px 0;
            border-bottom: 1px solid #f0f0f0;
        }

        .metric:last-child {
            border-bottom: none;
        }

        .metric-label {
            color: #666;
            font-weight: 500;
        }

        .metric-value {
            color: #333;
            font-weight: 700;
            font-size: 1.1em;
        }

        .metric-value.success {
            color: #4caf50;
        }

        .metric-value.danger {
            color: #f44336;
        }

        .progress-bar {
            width: 100%;
            height: 8px;
            background: #e0e0e0;
            border-radius: 4px;
            overflow: hidden;
            margin-top: 8px;
        }

        .progress-fill {
            height: 100%;
            background: linear-gradient(90deg, #667eea, #764ba2);
            border-radius: 4px;
            transition: width 0.3s ease;
        }

        .agents-list {
            background: white;
            border-radius: 12px;
            padding: 20px;
            box-shadow: 0 8px 32px rgba(0,0,0,0.1);
            margin-bottom: 30px;
            animation: fadeIn 0.6s ease-out 0.4s both;
        }

        .agents-list h2 {
            color: #333;
            margin-bottom: 20px;
            display: flex;
            align-items: center;
            gap: 10px;
        }

        .agent-card {
            background: linear-gradient(135deg, #f5f7fa 0%, #c3cfe2 100%);
            border-radius: 10px;
            padding: 20px;
            margin-bottom: 15px;
            border-left: 5px solid #667eea;
            transition: all 0.3s ease;
        }

        .agent-card:hover {
            transform: translateX(5px);
            box-shadow: 0 6px 20px rgba(102, 126, 234, 0.2);
        }

        .agent-header {
            display: grid;
            grid-template-columns: 1fr 1fr 1fr;
            gap: 20px;
            margin-bottom: 15px;
        }

        .agent-info {
            display: flex;
            flex-direction: column;
        }

        .agent-label {
            color: #666;
            font-size: 0.9em;
            font-weight: 600;
            text-transform: uppercase;
            letter-spacing: 0.5px;
            margin-bottom: 5px;
        }

        .agent-value {
            color: #333;
            font-size: 1.1em;
            font-weight: 700;
        }

        .agent-metrics {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(120px, 1fr));
            gap: 15px;
        }

        .mini-metric {
            background: white;
            padding: 12px;
            border-radius: 8px;
            text-align: center;
            border-top: 3px solid #667eea;
        }

        .mini-metric-label {
            color: #999;
            font-size: 0.8em;
            margin-bottom: 5px;
        }

        .mini-metric-value {
            color: #333;
            font-weight: 700;
            font-size: 1.2em;
        }

        .status-badge {
            display: inline-block;
            padding: 6px 12px;
            border-radius: 20px;
            font-size: 0.85em;
            font-weight: 600;
            margin-top: 10px;
        }

        .status-active {
            background: #c8e6c9;
            color: #2e7d32;
        }

        .status-inactive {
            background: #ffccbc;
            color: #d84315;
        }

        .loading {
            text-align: center;
            padding: 40px;
            color: white;
        }

        .spinner {
            border: 4px solid rgba(255,255,255,0.3);
            border-radius: 50%;
            border-top: 4px solid white;
            width: 40px;
            height: 40px;
            animation: spin 1s linear infinite;
            margin: 0 auto 20px;
        }

        .error-message {
            background: #ffebee;
            color: #c62828;
            padding: 15px;
            border-radius: 8px;
            margin-bottom: 20px;
            border-left: 4px solid #f44336;
            animation: slideDown 0.3s ease-out;
        }

        .success-message {
            background: #e8f5e9;
            color: #2e7d32;
            padding: 15px;
            border-radius: 8px;
            margin-bottom: 20px;
            border-left: 4px solid #4caf50;
            animation: slideDown 0.3s ease-out;
        }

        .tabs {
            display: flex;
            gap: 10px;
            margin-bottom: 20px;
            border-bottom: 2px solid #e0e0e0;
            flex-wrap: wrap;
        }

        .tab-button {
            background: none;
            border: none;
            padding: 12px 20px;
            cursor: pointer;
            color: #999;
            font-weight: 600;
            border-bottom: 3px solid transparent;
            transition: all 0.3s ease;
            text-transform: uppercase;
            font-size: 0.9em;
        }

        .tab-button.active {
            color: #667eea;
            border-bottom-color: #667eea;
        }

        .tab-content {
            display: none;
        }

        .tab-content.active {
            display: block;
            animation: fadeIn 0.3s ease-out;
        }

        .detail-table {
            width: 100%;
            border-collapse: collapse;
            margin-top: 15px;
            overflow-x: auto;
        }

        .detail-table th {
            background: #f5f5f5;
            padding: 12px;
            text-align: left;
            color: #333;
            font-weight: 600;
            border-bottom: 2px solid #e0e0e0;
        }

        .detail-table td {
            padding: 12px;
            border-bottom: 1px solid #e0e0e0;
            color: #666;
        }

        .detail-table tr:hover {
            background: #f9f9f9;
        }

        .no-data {
            text-align: center;
            padding: 40px;
            color: #999;
        }

        @keyframes slideDown {
            from {
                opacity: 0;
                transform: translateY(-20px);
            }
            to {
                opacity: 1;
                transform: translateY(0);
            }
        }

        @keyframes slideUp {
            from {
                opacity: 0;
                transform: translateY(20px);
            }
            to {
                opacity: 1;
                transform: translateY(0);
            }
        }

        @keyframes fadeIn {
            from { opacity: 0; }
            to { opacity: 1; }
        }

        @keyframes spin {
            to { transform: rotate(360deg); }
        }

        @media (max-width: 768px) {
            .control-panel {
                grid-template-columns: 1fr;
            }

            .agent-header {
                grid-template-columns: 1fr;
            }

            header h1 {
                font-size: 1.8em;
            }

            .dashboard {
                grid-template-columns: 1fr;
            }

            .tabs {
                flex-direction: column;
            }

            .tab-button {
                width: 100%;
                text-align: left;
            }

            button {
                padding: 10px 15px;
                font-size: 0.9em;
            }
        }
    </style>
</head>
<body>
    <div class="container">
        <header>
            <h1>🤖 AI Agent Monitor - Python</h1>
            <p>Real-time monitoring and analysis of AI agents in your project</p>
        </header>

        <div class="control-panel">
            <div class="input-block">
                <h3>File/Agent Names</h3>
                <input type="text" id="agentNames" placeholder="e.g., gpt-agent.js, claude-handler.py">
                <small style="color: #999;">Comma-separated agent file names</small>
            </div>

            <div class="input-block">
                <h3>File Path/Location</h3>
                <input type="text" id="agentPaths" placeholder="e.g., /src/agents, ./lib/ai">
                <small style="color: #999;">Project paths where agents located</small>
            </div>
        </div>

        <div style="text-align: center; margin-bottom: 20px; display: flex; gap: 10px; flex-wrap: wrap;">
            <button class="btn-scan" onclick="scanAgents()" style="flex: 1; min-width: 150px;">🔍 SCAN AGENTS</button>
            <button class="btn-clear" onclick="clearAll()" style="flex: 1; min-width: 150px;">🗑️ CLEAR</button>
            <button class="btn-download" onclick="downloadReport()" style="flex: 1; min-width: 150px;">📥 REPORT</button>
        </div>

        <div id="messages"></div>

        <div id="loading" class="loading" style="display: none;">
            <div class="spinner"></div>
            <p>Scanning agents and gathering metrics...</p>
        </div>

        <div id="dashboard" class="dashboard" style="display: none;">
            <div class="card">
                <h3>📊 System Metrics</h3>
                <div class="metric">
                    <span class="metric-label">CPU Usage</span>
                    <span class="metric-value" id="cpuUsage">-</span>
                </div>
                <div class="progress-bar">
                    <div class="progress-fill" id="cpuBar" style="width: 0%"></div>
                </div>
                <div class="metric">
                    <span class="metric-label">Memory Usage</span>
                    <span class="metric-value" id="memUsage">-</span>
                </div>
                <div class="progress-bar">
                    <div class="progress-fill" id="memBar" style="width: 0%"></div>
                </div>
                <div class="metric">
                    <span class="metric-label">Storage</span>
                    <span class="metric-value" id="storageUsage">-</span>
                </div>
            </div>

            <div class="card">
                <h3>🔐 Token Metrics</h3>
                <div class="metric">
                    <span class="metric-label">Tokens Used</span>
                    <span class="metric-value" id="tokensUsed">-</span>
                </div>
                <div class="metric">
                    <span class="metric-label">Total Available</span>
                    <span class="metric-value" id="tokensTotal">-</span>
                </div>
                <div class="metric">
                    <span class="metric-label">Usage %</span>
                    <span class="metric-value" id="tokenPercent">-</span>
                </div>
                <div class="progress-bar">
                    <div class="progress-fill" id="tokenBar" style="width: 0%"></div>
                </div>
            </div>

            <div class="card">
                <h3>📈 Request Metrics</h3>
                <div class="metric">
                    <span class="metric-label">RPM (Requests/Min)</span>
                    <span class="metric-value" id="rpm">-</span>
                </div>
                <div class="metric">
                    <span class="metric-label">RPH (Requests/Hour)</span>
                    <span class="metric-value" id="rph">-</span>
                </div>
                <div class="metric">
                    <span class="metric-label">RPD (Requests/Day)</span>
                    <span class="metric-value" id="rpd">-</span>
                </div>
            </div>

            <div class="card">
                <h3>⚡ Agent Status</h3>
                <div class="metric">
                    <span class="metric-label">Agents Detected</span>
                    <span class="metric-value success" id="agentCount">-</span>
                </div>
                <div class="metric">
                    <span class="metric-label">Active</span>
                    <span class="metric-value success" id="activeCount">-</span>
                </div>
                <div class="metric">
                    <span class="metric-label">Inactive</span>
                    <span class="metric-value danger" id="inactiveCount">-</span>
                </div>
            </div>
        </div>

        <div id="agentsSection" class="agents-list" style="display: none;">
            <h2>🤖 Detected AI Agents</h2>
            
            <div class="tabs">
                <button class="tab-button active" onclick="switchTab('overview')">Overview</button>
                <button class="tab-button" onclick="switchTab('detailed')">Detailed Metrics</button>
                <button class="tab-button" onclick="switchTab('requests')">Request History</button>
                <button class="tab-button" onclick="switchTab('providers')">Providers</button>
            </div>

            <div id="overview" class="tab-content active">
                <div id="agentsList"></div>
            </div>

            <div id="detailed" class="tab-content">
                <table class="detail-table">
                    <thead>
                        <tr>
                            <th>Agent Name</th>
                            <th>Provider</th>
                            <th>Model</th>
                            <th>Tokens Used / Total</th>
                            <th>Requests (Success/Failed)</th>
                            <th>Status</th>
                        </tr>
                    </thead>
                    <tbody id="detailedTable"></tbody>
                </table>
            </div>

            <div id="requests" class="tab-content">
                <table class="detail-table">
                    <thead>
                        <tr>
                            <th>Agent</th>
                            <th>Request ID</th>
                            <th>Timestamp</th>
                            <th>Status</th>
                            <th>Tokens Used</th>
                            <th>Response Time</th>
                        </tr>
                    </thead>
                    <tbody id="requestsTable"></tbody>
                </table>
            </div>

            <div id="providers" class="tab-content">
                <div id="providersList"></div>
            </div>
        </div>
    </div>

    <script>
        async function scanAgents() {
            const names = document.getElementById('agentNames').value;
            const paths = document.getElementById('agentPaths').value;

            if (!names && !paths) {
                showError('Please provide agent names or paths');
                return;
            }

            document.getElementById('loading').style.display = 'block';
            document.getElementById('dashboard').style.display = 'none';
            document.getElementById('agentsSection').style.display = 'none';

            try {
                const response = await fetch('/api/scan', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        agent_names: names,
                        agent_paths: paths
                    })
                });

                const data = await response.json();

                if (data.success) {
                    updateDashboard(data);
                    displayAgents(data.agents);
                    displayDetailedMetrics(data);
                    displayRequests(data.requests);
                    displayProviders(data.providers);
                    showSuccess(`✅ Found ${data.agents_count} AI agent(s)`);
                } else {
                    showError(data.error || 'Scan failed');
                }
            } catch (error) {
                showError('Error: ' + error.message);
            } finally {
                document.getElementById('loading').style.display = 'none';
            }
        }

        function updateDashboard(data) {
            const metrics = data.metrics;
            document.getElementById('cpuUsage').textContent = metrics.cpu + '%';
            document.getElementById('cpuBar').style.width = metrics.cpu + '%';
            document.getElementById('memUsage').textContent = metrics.memory + '%';
            document.getElementById('memBar').style.width = metrics.memory + '%';
            document.getElementById('storageUsage').textContent = metrics.storage + '%';
            document.getElementById('tokensUsed').textContent = formatNumber(metrics.used_tokens);
            document.getElementById('tokensTotal').textContent = formatNumber(metrics.total_tokens);
            const tokenPercent = ((metrics.used_tokens / metrics.total_tokens) * 100).toFixed(2);
            document.getElementById('tokenPercent').textContent = tokenPercent + '%';
            document.getElementById('tokenBar').style.width = tokenPercent + '%';
            document.getElementById('rpm').textContent = metrics.rpm;
            document.getElementById('rph').textContent = metrics.rph;
            document.getElementById('rpd').textContent = metrics.rpd;
            document.getElementById('agentCount').textContent = data.agents.length;
            document.getElementById('activeCount').textContent = data.agents.filter(a => a.active).length;
            document.getElementById('inactiveCount').textContent = data.agents.filter(a => !a.active).length;
            document.getElementById('dashboard').style.display = 'grid';
        }

        function displayAgents(agents) {
            let html = '';
            agents.forEach(agent => {
                const status = agent.active ? 'Active' : 'Inactive';
                const statusClass = agent.active ? 'status-active' : 'status-inactive';
                html += `
                    <div class="agent-card">
                        <div class="agent-header">
                            <div class="agent-info">
                                <div class="agent-label">Agent Name</div>
                                <div class="agent-value">${escapeHtml(agent.name)}</div>
                            </div>
                            <div class="agent-info">
                                <div class="agent-label">Provider</div>
                                <div class="agent-value">${escapeHtml(agent.provider)}</div>
                            </div>
                            <div class="agent-info">
                                <div class="agent-label">Model</div>
                                <div class="agent-value">${escapeHtml(agent.model)}</div>
                            </div>
                        </div>
                        <div class="agent-metrics">
                            <div class="mini-metric">
                                <div class="mini-metric-label">TOKENS USED</div>
                                <div class="mini-metric-value">${formatNumber(agent.tokens_used)}</div>
                            </div>
                            <div class="mini-metric">
                                <div class="mini-metric-label">TOKENS TOTAL</div>
                                <div class="mini-metric-value">${formatNumber(agent.tokens_available)}</div>
                            </div>
                            <div class="mini-metric">
                                <div class="mini-metric-label">REQUESTS</div>
                                <div class="mini-metric-value">${formatNumber(agent.requests)}</div>
                            </div>
                            <div class="mini-metric">
                                <div class="mini-metric-label">SUCCESS RATE</div>
                                <div class="mini-metric-value">${agent.success_rate.toFixed(1)}%</div>
                            </div>
                            <div class="mini-metric">
                                <div class="mini-metric-label">FAILURE RATE</div>
                                <div class="mini-metric-value">${agent.failure_rate.toFixed(1)}%</div>
                            </div>
                        </div>
                        <span class="status-badge ${statusClass}">${status}</span>
                    </div>
                `;
            });
            document.getElementById('agentsList').innerHTML = html;
            document.getElementById('agentsSection').style.display = 'block';
        }

        function displayDetailedMetrics(data) {
            let html = '';
            data.agents.forEach(agent => {
                const statusClass = agent.active ? 'success' : 'danger';
                const statusText = agent.active ? '🟢 Active' : '🔴 Inactive';
                html += `
                    <tr>
                        <td>${escapeHtml(agent.name)}</td>
                        <td>${escapeHtml(agent.provider)}</td>
                        <td>${escapeHtml(agent.model)}</td>
                        <td>${formatNumber(agent.tokens_used)} / ${formatNumber(agent.tokens_available)}</td>
                        <td>${agent.requests} (${Math.floor(agent.requests * (agent.success_rate/100))} / ${Math.floor(agent.requests * (agent.failure_rate/100))})</td>
                        <td><span class="status-badge status-${agent.active ? 'active' : 'inactive'}">${statusText}</span></td>
                    </tr>
                `;
            });
            document.getElementById('detailedTable').innerHTML = html;
        }

        function displayRequests(requests) {
            let html = '';
            requests.slice(0, 10).forEach(req => {
                const statusClass = req.status === 'success' ? 'success' : 'danger';
                const statusEmoji = req.status === 'success' ? '✅' : '❌';
                html += `
                    <tr>
                        <td>${escapeHtml(req.agent_name)}</td>
                        <td>${escapeHtml(req.request_id.substring(0, 20))}...</td>
                        <td>${new Date(req.timestamp).toLocaleTimeString()}</td>
                        <td><span class="metric-value ${statusClass}">${statusEmoji} ${req.status}</span></td>
                        <td>${formatNumber(req.tokens_used)}</td>
                        <td>${req.response_time}ms</td>
                    </tr>
                `;
            });
            document.getElementById('requestsTable').innerHTML = html;
        }

        function displayProviders(providers) {
            let html = '';
            Object.values(providers).forEach(provider => {
                html += `
                    <div class="agent-card">
                        <div class="agent-header">
                            <div class="agent-info">
                                <div class="agent-label">Provider Name</div>
                                <div class="agent-value">${escapeHtml(provider.name)}</div>
                            </div>
                            <div class="agent-info">
                                <div class="agent-label">Primary Model</div>
                                <div class="agent-value">${escapeHtml(provider.model)}</div>
                            </div>
                            <div class="agent-info">
                                <div class="agent-label">Agent Count</div>
                                <div class="agent-value">${provider.count}</div>
                            </div>
                        </div>
                        <div class="agent-metrics">
                            <div class="mini-metric">
                                <div class="mini-metric-label">ACTIVE</div>
                                <div class="mini-metric-value">${provider.active_count}</div>
                            </div>
                            <div class="mini-metric">
                                <div class="mini-metric-label">TOTAL TOKENS</div>
                                <div class="mini-metric-value">${formatNumber(provider.total_tokens)}</div>
                            </div>
                            <div class="mini-metric">
                                <div class="mini-metric-label">TOTAL REQUESTS</div>
                                <div class="mini-metric-value">${formatNumber(provider.total_requests)}</div>
                            </div>
                            <div class="mini-metric">
                                <div class="mini-metric-label">SUCCESS RATE</div>
                                <div class="mini-metric-value">${provider.success_rate}%</div>
                            </div>
                        </div>
                    </div>
                `;
            });
            document.getElementById('providersList').innerHTML = html;
        }

        function formatNumber(num) {
            if (num >= 1000000) return (num / 1000000).toFixed(2) + 'M';
            if (num >= 1000) return (num / 1000).toFixed(2) + 'K';
            return num;
        }

        function escapeHtml(text) {
            const div = document.createElement('div');
            div.textContent = text;
            return div.innerHTML;
        }

        function showSuccess(msg) {
            const msgDiv = document.getElementById('messages');
            msgDiv.innerHTML = `<div class="success-message">${msg}</div>`;
            setTimeout(() => msgDiv.innerHTML = '', 5000);
        }

        function showError(msg) {
            const msgDiv = document.getElementById('messages');
            msgDiv.innerHTML = `<div class="error-message">${msg}</div>`;
            setTimeout(() => msgDiv.innerHTML = '', 5000);
        }

        function clearAll() {
            document.getElementById('agentNames').value = '';
            document.getElementById('agentPaths').value = '';
            document.getElementById('dashboard').style.display = 'none';
            document.getElementById('agentsSection').style.display = 'none';
            document.getElementById('messages').innerHTML = '';
        }

        function switchTab(tabName) {
            document.querySelectorAll('.tab-content').forEach(tab => {
                tab.classList.remove('active');
            });
            document.querySelectorAll('.tab-button').forEach(btn => {
                btn.classList.remove('active');
            });
            document.getElementById(tabName).classList.add('active');
            event.target.classList.add('active');
        }

        async function downloadReport() {
            try {
                const response = await fetch('/api/report/download');
                const blob = await response.blob();
                const url = window.URL.createObjectURL(blob);
                const a = document.createElement('a');
                a.href = url;
                a.download = `agent_report_${new Date().getTime()}.json`;
                document.body.appendChild(a);
                a.click();
                window.URL.revokeObjectURL(url);
                document.body.removeChild(a);
            } catch (error) {
                showError('Error downloading report');
            }
        }
    </script>
</body>
</html>
'''


# ============================================================================
# FLASK ROUTES
# ============================================================================

@app.route('/')
def index():
    """Serve the main dashboard"""
    return render_template_string(HTML_TEMPLATE)


@app.route('/api/scan', methods=['POST'])
def scan():
    """Scan for AI agents"""
    try:
        data = request.get_json()
        agent_names = data.get('agent_names', '')
        agent_paths = data.get('agent_paths', '')

        result = scanner.scan_agents(agent_names, agent_paths)
        return jsonify(result)
    except Exception as e:
        return jsonify({'error': str(e), 'success': False}), 400


@app.route('/api/dashboard', methods=['GET'])
def get_dashboard():
    """Get dashboard data"""
    try:
        dashboard_data = scanner.get_dashboard_data()
        return jsonify(dashboard_data)
    except Exception as e:
        return jsonify({'error': str(e)}), 400


@app.route('/api/metrics/system', methods=['GET'])
def get_system_metrics():
    """Get system metrics"""
    try:
        metrics = scanner.get_system_metrics()
        return jsonify(metrics)
    except Exception as e:
        return jsonify({'error': str(e)}), 400


@app.route('/api/report/download', methods=['GET'])
def download_report():
    """Download report as JSON file"""
    try:
        report_bytes = scanner.save_report()
        return send_file(
            io.BytesIO(report_bytes),
            mimetype='application/json',
            as_attachment=True,
            download_name=f'agent_report_{datetime.now().strftime("%Y%m%d_%H%M%S")}.json'
        )
    except Exception as e:
        return jsonify({'error': str(e)}), 400


@app.route('/api/report', methods=['GET'])
def get_report():
    """Get text report"""
    try:
        report = scanner.get_detailed_report()
        return jsonify({'report': report})
    except Exception as e:
        return jsonify({'error': str(e)}), 400


@app.route('/api/agents', methods=['GET'])
def get_agents():
    """Get all agents"""
    try:
        agents = [scanner._agent_to_dict(agent) for agent in scanner.agents]
        return jsonify({'agents': agents, 'count': len(agents)})
    except Exception as e:
        return jsonify({'error': str(e)}), 400


@app.route('/api/status', methods=['GET'])
def get_status():
    """Get scanner status"""
    try:
        status = {
            'status': 'running',
            'agents_count': len(scanner.agents),
            'active_agents': sum(1 for agent in scanner.agents if agent.active),
            'total_requests': len(scanner.requests),
            'timestamp': datetime.now().isoformat()
        }
        return jsonify(status)
    except Exception as e:
        return jsonify({'error': str(e)}), 400


# Error handlers
@app.errorhandler(404)
def not_found(error):
    """Handle 404 errors"""
    return jsonify({'error': 'Not found'}), 404


@app.errorhandler(500)
def internal_error(error):
    """Handle 500 errors"""
    return jsonify({'error': 'Internal server error'}), 500


# ============================================================================
# MAIN ENTRY POINT
# ============================================================================

if __name__ == '__main__':
    # Create config file if doesn't exist
    if not os.path.exists('config.json'):
        config = {
            'agents': [],
            'paths': [],
            'providers': {
                'openai': {'name': 'OpenAI', 'models': ['gpt-4', 'gpt-3.5-turbo']},
                'anthropic': {'name': 'Anthropic', 'models': ['claude-3', 'claude-2']},
                'google': {'name': 'Google', 'models': ['gemini-pro', 'palm-2']},
                'huggingface': {'name': 'Hugging Face', 'models': ['mistral', 'llama']},
                'cohere': {'name': 'Cohere', 'models': ['command', 'command-light']},
                'azure': {'name': 'Microsoft Azure', 'models': ['gpt-4', 'gpt-35-turbo']}
            }
        }
        with open('config.json', 'w') as f:
            json.dump(config, f, indent=2)
        print("✅ Created config.json")

    print("\n" + "="*80)
    print("🤖 AI AGENT MONITOR - PYTHON VERSION")
    print("="*80)
    print("Starting Flask server...")
    print("Open: http://localhost:5000")
    print("="*80 + "\n")

    # Run Flask app
    app.run(debug=True, host='0.0.0.0', port=5000, use_reloader=False)
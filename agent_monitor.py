"""
agent_monitor.py
================
AI Agent Monitor - Real Scanner, Real Metrics, Free Models Only
- Only SAFE FREE and USE WITH CAUTION models shown
- Real token usage tracking (used vs available)
- Real request tracking (used vs limit)
- Real API calls and real system metrics
- Fully independent (no Prometheus, no Grafana)
"""

import os
import sys
import re
import io
import time
import json
import threading
import hashlib
from pathlib import Path
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional
from dataclasses import dataclass, field
from collections import deque

import psutil
from flask import Flask, render_template_string, request, jsonify, send_file
from flask_cors import CORS

# ============================================================================
# OPTIONAL AI PROVIDER IMPORTS
# ============================================================================
try:
    import google.generativeai as genai
    GEMINI_AVAILABLE = True
except ImportError:
    GEMINI_AVAILABLE = False
    print("⚠ google-generativeai not installed: pip install google-generativeai")

try:
    from openai import OpenAI
    OPENAI_AVAILABLE = True
except ImportError:
    OPENAI_AVAILABLE = False
    print("⚠ openai not installed: pip install openai")

try:
    import requests as req_lib
    REQUESTS_AVAILABLE = True
except ImportError:
    REQUESTS_AVAILABLE = False

# ============================================================================
# FREE MODELS REGISTRY
# SAFE FREE  = confirmed free, stable
# CAUTION    = free now, pricing may come after GA
# ============================================================================

FREE_MODELS_REGISTRY = {

    # ── Google Gemini ─────────────────────────────────────────
    "gemini": {
        "name":       "Google Gemini",
        "env_keys":   ["GEMINI_API_KEY", "GOOGLE_API_KEY"],
        "type":       "gemini",
        "base_url":   None,
        "signup_url": "https://aistudio.google.com",
        "daily_limit_requests": 1_500,   # free tier: 1500 RPD
        "daily_limit_tokens":   1_000_000_000,  # ~1B tokens/day free
        "models": [
            # ── SAFE FREE ─────────────────────────────────────
            {
                "id":          "gemini-2.0-flash",
                "name":        "Gemini 2.0 Flash",
                "tier":        "safe_free",
                "rpm":         15,
                "rpd":         1_500,
                "tpm":         1_000_000,
                "tpd":         1_500_000_000,
                "context":     "1M tokens",
                "type":        "Text + Vision",
                "recommended": True,
            },
            {
                "id":          "gemini-2.0-flash-001",
                "name":        "Gemini 2.0 Flash 001 (Pinned)",
                "tier":        "safe_free",
                "rpm":         15,
                "rpd":         1_500,
                "tpm":         1_000_000,
                "tpd":         1_500_000_000,
                "context":     "1M tokens",
                "type":        "Text + Vision",
                "recommended": False,
            },
            {
                "id":          "gemini-2.0-flash-lite",
                "name":        "Gemini 2.0 Flash Lite",
                "tier":        "safe_free",
                "rpm":         30,
                "rpd":         1_500,
                "tpm":         1_000_000,
                "tpd":         1_500_000_000,
                "context":     "1M tokens",
                "type":        "Text + Vision",
                "recommended": True,
            },
            {
                "id":          "gemini-2.0-flash-lite-001",
                "name":        "Gemini 2.0 Flash Lite 001 (Pinned)",
                "tier":        "safe_free",
                "rpm":         30,
                "rpd":         1_500,
                "tpm":         1_000_000,
                "tpd":         1_500_000_000,
                "context":     "1M tokens",
                "type":        "Text + Vision",
                "recommended": False,
            },
            {
                "id":          "gemini-flash-latest",
                "name":        "Gemini Flash Latest (Alias)",
                "tier":        "safe_free",
                "rpm":         15,
                "rpd":         1_500,
                "tpm":         1_000_000,
                "tpd":         1_500_000_000,
                "context":     "1M tokens",
                "type":        "Text + Vision",
                "recommended": False,
            },
            {
                "id":          "gemini-flash-lite-latest",
                "name":        "Gemini Flash Lite Latest (Alias)",
                "tier":        "safe_free",
                "rpm":         30,
                "rpd":         1_500,
                "tpm":         1_000_000,
                "tpd":         1_500_000_000,
                "context":     "1M tokens",
                "type":        "Text + Vision",
                "recommended": False,
            },
            {
                "id":          "gemma-4-31b-it",
                "name":        "Gemma 4 31B IT",
                "tier":        "safe_free",
                "rpm":         15,
                "rpd":         1_500,
                "tpm":         1_000_000,
                "tpd":         1_500_000_000,
                "context":     "128K tokens",
                "type":        "Open Weight Chat",
                "recommended": False,
            },
            {
                "id":          "gemma-4-26b-a4b-it",
                "name":        "Gemma 4 26B (MoE)",
                "tier":        "safe_free",
                "rpm":         15,
                "rpd":         1_500,
                "tpm":         1_000_000,
                "tpd":         1_500_000_000,
                "context":     "128K tokens",
                "type":        "Open Weight Chat",
                "recommended": False,
            },
            {
                "id":          "gemini-embedding-001",
                "name":        "Gemini Embedding 001",
                "tier":        "safe_free",
                "rpm":         15,
                "rpd":         1_500,
                "tpm":         1_000_000,
                "tpd":         1_500_000_000,
                "context":     "2K input",
                "type":        "Embedding only",
                "recommended": False,
            },
            {
                "id":          "gemini-embedding-2",
                "name":        "Gemini Embedding 2",
                "tier":        "safe_free",
                "rpm":         15,
                "rpd":         1_500,
                "tpm":         1_000_000,
                "tpd":         1_500_000_000,
                "context":     "8K input",
                "type":        "Embedding only",
                "recommended": False,
            },
            # ── USE WITH CAUTION ──────────────────────────────
            {
                "id":          "gemini-2.5-flash",
                "name":        "Gemini 2.5 Flash",
                "tier":        "caution",
                "rpm":         10,
                "rpd":         500,
                "tpm":         250_000,
                "tpd":         250_000_000,
                "context":     "1M tokens",
                "type":        "Text + Vision",
                "recommended": False,
            },
            {
                "id":          "gemini-2.5-flash-lite",
                "name":        "Gemini 2.5 Flash Lite",
                "tier":        "caution",
                "rpm":         10,
                "rpd":         500,
                "tpm":         250_000,
                "tpd":         250_000_000,
                "context":     "1M tokens",
                "type":        "Text + Vision",
                "recommended": False,
            },
        ],
    },

    # ── NVIDIA NIM ────────────────────────────────────────────
    "nvidia": {
        "name":       "NVIDIA NIM",
        "env_keys":   ["NVIDIA_API_KEY"],
        "type":       "openai_compat",
        "base_url":   "https://integrate.api.nvidia.com/v1",
        "signup_url": "https://build.nvidia.com",
        "daily_limit_requests": 1_000,
        "daily_limit_tokens":   40_000_000,
        "models": [
            {
                "id":          "meta/llama-3.1-8b-instruct",
                "name":        "Llama 3.1 8B Instruct",
                "tier":        "safe_free",
                "rpm":         40,
                "rpd":         1_000,
                "tpm":         40_000,
                "tpd":         40_000_000,
                "context":     "128K tokens",
                "type":        "Chat",
                "recommended": True,
            },
            {
                "id":          "meta/llama-3.2-3b-instruct",
                "name":        "Llama 3.2 3B Instruct",
                "tier":        "safe_free",
                "rpm":         40,
                "rpd":         1_000,
                "tpm":         40_000,
                "tpd":         40_000_000,
                "context":     "128K tokens",
                "type":        "Chat",
                "recommended": False,
            },
            {
                "id":          "mistralai/mistral-7b-instruct-v0.3",
                "name":        "Mistral 7B Instruct v0.3",
                "tier":        "safe_free",
                "rpm":         40,
                "rpd":         1_000,
                "tpm":         40_000,
                "tpd":         40_000_000,
                "context":     "32K tokens",
                "type":        "Chat",
                "recommended": False,
            },
            {
                "id":          "google/gemma-2-9b-it",
                "name":        "Gemma 2 9B IT",
                "tier":        "safe_free",
                "rpm":         40,
                "rpd":         1_000,
                "tpm":         40_000,
                "tpd":         40_000_000,
                "context":     "8K tokens",
                "type":        "Chat",
                "recommended": False,
            },
            {
                "id":          "deepseek-ai/deepseek-r1",
                "name":        "DeepSeek R1",
                "tier":        "safe_free",
                "rpm":         40,
                "rpd":         1_000,
                "tpm":         40_000,
                "tpd":         40_000_000,
                "context":     "128K tokens",
                "type":        "Chat",
                "recommended": True,
            },
            {
                "id":          "microsoft/phi-3-mini-128k-instruct",
                "name":        "Phi-3 Mini 128K",
                "tier":        "safe_free",
                "rpm":         40,
                "rpd":         1_000,
                "tpm":         40_000,
                "tpd":         40_000_000,
                "context":     "128K tokens",
                "type":        "Chat",
                "recommended": False,
            },
        ],
    },

    # ── Groq ─────────────────────────────────────────────────
    "groq": {
        "name":       "Groq",
        "env_keys":   ["GROQ_API_KEY"],
        "type":       "openai_compat",
        "base_url":   "https://api.groq.com/openai/v1",
        "signup_url": "https://console.groq.com",
        "daily_limit_requests": 14_400,
        "daily_limit_tokens":   500_000,
        "models": [
            {
                "id":          "llama-3.1-8b-instant",
                "name":        "Llama 3.1 8B Instant",
                "tier":        "safe_free",
                "rpm":         30,
                "rpd":         14_400,
                "tpm":         6_000,
                "tpd":         500_000,
                "context":     "128K tokens",
                "type":        "Chat",
                "recommended": True,
            },
            {
                "id":          "llama-3.3-70b-versatile",
                "name":        "Llama 3.3 70B Versatile",
                "tier":        "safe_free",
                "rpm":         30,
                "rpd":         14_400,
                "tpm":         6_000,
                "tpd":         500_000,
                "context":     "128K tokens",
                "type":        "Chat",
                "recommended": True,
            },
            {
                "id":          "mixtral-8x7b-32768",
                "name":        "Mixtral 8x7B",
                "tier":        "safe_free",
                "rpm":         30,
                "rpd":         14_400,
                "tpm":         5_000,
                "tpd":         500_000,
                "context":     "32K tokens",
                "type":        "Chat",
                "recommended": False,
            },
            {
                "id":          "gemma2-9b-it",
                "name":        "Gemma2 9B IT",
                "tier":        "safe_free",
                "rpm":         30,
                "rpd":         14_400,
                "tpm":         15_000,
                "tpd":         500_000,
                "context":     "8K tokens",
                "type":        "Chat",
                "recommended": False,
            },
            {
                "id":          "deepseek-r1-distill-llama-70b",
                "name":        "DeepSeek R1 Distill Llama 70B",
                "tier":        "safe_free",
                "rpm":         30,
                "rpd":         14_400,
                "tpm":         6_000,
                "tpd":         500_000,
                "context":     "128K tokens",
                "type":        "Chat",
                "recommended": True,
            },
        ],
    },

    # ── HuggingFace ───────────────────────────────────────────
    "huggingface": {
        "name":       "Hugging Face",
        "env_keys":   ["HF_TOKEN", "HUGGINGFACE_API_KEY"],
        "type":       "huggingface",
        "base_url":   "https://api-inference.huggingface.co/models",
        "signup_url": "https://huggingface.co",
        "daily_limit_requests": 1_000,
        "daily_limit_tokens":   0,   # HF doesn't expose token limits
        "models": [
            {
                "id":          "mistralai/Mistral-7B-Instruct-v0.3",
                "name":        "Mistral 7B Instruct v0.3",
                "tier":        "safe_free",
                "rpm":         30,
                "rpd":         1_000,
                "tpm":         0,
                "tpd":         0,
                "context":     "32K tokens",
                "type":        "Chat",
                "recommended": True,
            },
            {
                "id":          "HuggingFaceH4/zephyr-7b-beta",
                "name":        "Zephyr 7B Beta",
                "tier":        "safe_free",
                "rpm":         30,
                "rpd":         1_000,
                "tpm":         0,
                "tpd":         0,
                "context":     "32K tokens",
                "type":        "Chat",
                "recommended": False,
            },
            {
                "id":          "google/gemma-2-2b-it",
                "name":        "Gemma 2 2B IT",
                "tier":        "safe_free",
                "rpm":         30,
                "rpd":         1_000,
                "tpm":         0,
                "tpd":         0,
                "context":     "8K tokens",
                "type":        "Chat",
                "recommended": False,
            },
            {
                "id":          "microsoft/Phi-3-mini-4k-instruct",
                "name":        "Phi-3 Mini 4K",
                "tier":        "safe_free",
                "rpm":         30,
                "rpd":         1_000,
                "tpm":         0,
                "tpd":         0,
                "context":     "4K tokens",
                "type":        "Chat",
                "recommended": False,
            },
        ],
    },

    # ── OpenRouter (free tier) ────────────────────────────────
    "openrouter": {
        "name":       "OpenRouter",
        "env_keys":   ["OPENROUTER_API_KEY"],
        "type":       "openai_compat",
        "base_url":   "https://openrouter.ai/api/v1",
        "signup_url": "https://openrouter.ai",
        "daily_limit_requests": 200,
        "daily_limit_tokens":   0,
        "models": [
            {
                "id":          "meta-llama/llama-3.1-8b-instruct:free",
                "name":        "Llama 3.1 8B Instruct",
                "tier":        "safe_free",
                "rpm":         20,
                "rpd":         200,
                "tpm":         0,
                "tpd":         0,
                "context":     "131K tokens",
                "type":        "Chat",
                "recommended": True,
            },
            {
                "id":          "google/gemma-2-9b-it:free",
                "name":        "Gemma 2 9B IT",
                "tier":        "safe_free",
                "rpm":         20,
                "rpd":         200,
                "tpm":         0,
                "tpd":         0,
                "context":     "8K tokens",
                "type":        "Chat",
                "recommended": False,
            },
            {
                "id":          "deepseek/deepseek-r1:free",
                "name":        "DeepSeek R1",
                "tier":        "safe_free",
                "rpm":         20,
                "rpd":         200,
                "tpm":         0,
                "tpd":         0,
                "context":     "64K tokens",
                "type":        "Chat",
                "recommended": True,
            },
            {
                "id":          "mistralai/mistral-7b-instruct:free",
                "name":        "Mistral 7B Instruct",
                "tier":        "safe_free",
                "rpm":         20,
                "rpd":         200,
                "tpm":         0,
                "tpd":         0,
                "context":     "32K tokens",
                "type":        "Chat",
                "recommended": False,
            },
        ],
    },

    # ── Mistral AI ────────────────────────────────────────────
    "mistral": {
        "name":       "Mistral AI",
        "env_keys":   ["MISTRAL_API_KEY"],
        "type":       "openai_compat",
        "base_url":   "https://api.mistral.ai/v1",
        "signup_url": "https://console.mistral.ai",
        "daily_limit_requests": 500,
        "daily_limit_tokens":   1_000_000,
        "models": [
            {
                "id":          "mistral-small-latest",
                "name":        "Mistral Small Latest",
                "tier":        "safe_free",
                "rpm":         5,
                "rpd":         500,
                "tpm":         2_000,
                "tpd":         1_000_000,
                "context":     "32K tokens",
                "type":        "Chat",
                "recommended": True,
            },
            {
                "id":          "open-mistral-7b",
                "name":        "Open Mistral 7B",
                "tier":        "safe_free",
                "rpm":         5,
                "rpd":         500,
                "tpm":         2_000,
                "tpd":         1_000_000,
                "context":     "32K tokens",
                "type":        "Chat",
                "recommended": False,
            },
            {
                "id":          "open-mixtral-8x7b",
                "name":        "Open Mixtral 8x7B",
                "tier":        "safe_free",
                "rpm":         5,
                "rpd":         500,
                "tpm":         2_000,
                "tpd":         1_000_000,
                "context":     "32K tokens",
                "type":        "Chat",
                "recommended": False,
            },
        ],
    },
}

# ── AI detection patterns ─────────────────────────────────────
AI_PATTERNS = {
    "import_openai":      (r"import\s+openai|from\s+openai",                         "OpenAI"),
    "import_anthropic":   (r"import\s+anthropic|from\s+anthropic",                   "Anthropic"),
    "import_gemini":      (r"import\s+google\.generativeai|from\s+google\.generativeai", "Gemini"),
    "import_langchain":   (r"from\s+langchain|import\s+langchain",                   "LangChain"),
    "import_litellm":     (r"import\s+litellm|from\s+litellm",                       "LiteLLM"),
    "import_huggingface": (r"from\s+transformers|import\s+transformers",             "HuggingFace"),
    "import_groq":        (r"import\s+groq|from\s+groq",                             "Groq"),
    "import_mistral":     (r"import\s+mistralai|from\s+mistralai",                   "Mistral"),
    "openai_call":        (r"client\.chat\.completions|ChatOpenAI|OpenAI\(",          "OpenAI"),
    "anthropic_call":     (r"anthropic\.Anthropic|messages\.create",                 "Anthropic"),
    "gemini_call":        (r"genai\.configure|GenerativeModel|generate_content",      "Gemini"),
    "groq_call":          (r"Groq\(|groq\.chat",                                     "Groq"),
    "nvidia_call":        (r"integrate\.api\.nvidia\.com",                           "NVIDIA"),
    "openrouter_call":    (r"openrouter\.ai",                                        "OpenRouter"),
    "env_openai":         (r"OPENAI_API_KEY",                                        "OpenAI"),
    "env_anthropic":      (r"ANTHROPIC_API_KEY",                                     "Anthropic"),
    "env_gemini":         (r"GEMINI_API_KEY|GOOGLE_API_KEY",                         "Gemini"),
    "env_groq":           (r"GROQ_API_KEY",                                          "Groq"),
    "env_nvidia":         (r"NVIDIA_API_KEY",                                        "NVIDIA"),
    "env_hf":             (r"HF_TOKEN|HUGGINGFACE_API_KEY",                          "HuggingFace"),
    "env_mistral":        (r"MISTRAL_API_KEY",                                       "Mistral"),
    "autogen":            (r"import\s+autogen|from\s+autogen",                       "AutoGen"),
    "crewai":             (r"import\s+crewai|from\s+crewai",                         "CrewAI"),
    "llamaindex":         (r"import\s+llama_index|from\s+llama_index",               "LlamaIndex"),
}

SCANNABLE_EXTENSIONS = {
    ".py", ".js", ".ts", ".jsx", ".tsx",
    ".json", ".yaml", ".yml", ".env",
    ".txt", ".md", ".sh", ".toml", ".cfg", ".ini",
}

SKIP_DIRS = {
    ".git", "__pycache__", "node_modules", ".venv", "venv",
    "env", ".env", "dist", "build", ".idea", ".vscode",
    ".mypy_cache", ".pytest_cache",
}

# ============================================================================
# DATA MODELS
# ============================================================================

@dataclass
class ProjectFile:
    path:          str
    name:          str
    extension:     str
    size_bytes:    int
    lines:         int
    is_ai_agent:   bool
    ai_providers:  List[str]
    ai_patterns:   List[str]
    purpose:       str
    last_modified: str

@dataclass
class QuotaTracker:
    """
    Tracks used vs available tokens and requests
    per provider per model per window (minute / day)
    """
    provider:          str
    model_id:          str
    # limits from registry
    rpm_limit:         int   = 0
    rpd_limit:         int   = 0
    tpm_limit:         int   = 0
    tpd_limit:         int   = 0
    # used this session
    requests_this_min: int   = 0
    requests_today:    int   = 0
    tokens_this_min:   int   = 0
    tokens_today:      int   = 0
    # window start times
    min_window_start:  float = field(default_factory=time.time)
    day_window_start:  float = field(default_factory=time.time)

    def record(self, tokens: int) -> None:
        now = time.time()
        # reset minute window
        if now - self.min_window_start >= 60:
            self.requests_this_min = 0
            self.tokens_this_min   = 0
            self.min_window_start  = now
        # reset day window
        if now - self.day_window_start >= 86_400:
            self.requests_today  = 0
            self.tokens_today    = 0
            self.day_window_start = now

        self.requests_this_min += 1
        self.requests_today    += 1
        self.tokens_this_min   += tokens
        self.tokens_today      += tokens

    def to_dict(self) -> Dict[str, Any]:
        return {
            "provider":            self.provider,
            "model_id":            self.model_id,
            # limits
            "rpm_limit":           self.rpm_limit,
            "rpd_limit":           self.rpd_limit,
            "tpm_limit":           self.tpm_limit,
            "tpd_limit":           self.tpd_limit,
            # used
            "requests_this_min":   self.requests_this_min,
            "requests_today":      self.requests_today,
            "tokens_this_min":     self.tokens_this_min,
            "tokens_today":        self.tokens_today,
            # remaining
            "rpm_remaining":       max(0, self.rpm_limit - self.requests_this_min),
            "rpd_remaining":       max(0, self.rpd_limit - self.requests_today),
            "tpm_remaining":       max(0, self.tpm_limit - self.tokens_this_min)
                                   if self.tpm_limit else 0,
            "tpd_remaining":       max(0, self.tpd_limit - self.tokens_today)
                                   if self.tpd_limit else 0,
            # percentages
            "rpm_pct":             round(self.requests_this_min / self.rpm_limit * 100, 1)
                                   if self.rpm_limit else 0,
            "rpd_pct":             round(self.requests_today    / self.rpd_limit * 100, 1)
                                   if self.rpd_limit else 0,
            "tpm_pct":             round(self.tokens_this_min   / self.tpm_limit * 100, 1)
                                   if self.tpm_limit else 0,
            "tpd_pct":             round(self.tokens_today      / self.tpd_limit * 100, 1)
                                   if self.tpd_limit else 0,
        }

@dataclass
class AgentMetrics:
    total_calls:       int   = 0
    success_calls:     int   = 0
    failed_calls:      int   = 0
    total_tokens:      int   = 0
    prompt_tokens:     int   = 0
    completion_tokens: int   = 0
    total_latency_ms:  float = 0.0
    min_latency_ms:    float = float("inf")
    max_latency_ms:    float = 0.0
    rate_limit_hits:   int   = 0
    auth_failures:     int   = 0
    last_call_time:    str   = ""
    last_status:       str   = ""
    last_error:        str   = ""

@dataclass
class Agent:
    id:             str
    name:           str
    provider:       str
    model:          str
    file_path:      str
    file_ext:       str
    status:         str
    active:         bool
    metrics:        AgentMetrics = field(default_factory=AgentMetrics)
    patterns_found: List[str]    = field(default_factory=list)
    purpose:        str          = ""
    source:         str          = ""
    detected_at:    str          = ""

@dataclass
class SystemMetrics:
    cpu_percent:       float = 0.0
    memory_percent:    float = 0.0
    memory_used_mb:    float = 0.0
    memory_total_mb:   float = 0.0
    disk_percent:      float = 0.0
    disk_used_gb:      float = 0.0
    disk_total_gb:     float = 0.0
    process_memory_mb: float = 0.0
    uptime_seconds:    float = 0.0
    thread_count:      int   = 0

@dataclass
class RequestRecord:
    request_id:        str
    agent_name:        str
    provider:          str
    model:             str
    timestamp:         str
    status:            str
    prompt_tokens:     int
    completion_tokens: int
    total_tokens:      int
    latency_ms:        float
    error:             str = ""

# ============================================================================
# KEY DETECTOR
# ============================================================================

class KeyDetector:

    @staticmethod
    def get_key(provider_id: str) -> Optional[str]:
        cfg = FREE_MODELS_REGISTRY.get(provider_id, {})
        for env_name in cfg.get("env_keys", []):
            val = os.environ.get(env_name, "").strip()
            if val:
                return val
        return None

    @staticmethod
    def get_available_providers() -> Dict[str, Any]:
        result = {}
        for pid, cfg in FREE_MODELS_REGISTRY.items():
            key = None
            found_env = None
            for env_name in cfg.get("env_keys", []):
                val = os.environ.get(env_name, "").strip()
                if val:
                    key       = val
                    found_env = env_name
                    break
            result[pid] = {
                "id":          pid,
                "name":        cfg["name"],
                "available":   key is not None,
                "env_var":     found_env or cfg["env_keys"][0],
                "signup_url":  cfg.get("signup_url", ""),
                "models":      cfg["models"],
                "model_count": len(cfg["models"]),
                "daily_limit_requests": cfg.get("daily_limit_requests", 0),
                "daily_limit_tokens":   cfg.get("daily_limit_tokens",   0),
            }
        return result

# ============================================================================
# REAL API CALLER
# ============================================================================

class RealAPICaller:

    def call(
        self,
        provider_id: str,
        model_id:    str,
        api_key:     str,
        prompt:      str = "Reply with just the word OK.",
    ) -> Dict[str, Any]:
        cfg = FREE_MODELS_REGISTRY.get(provider_id)
        if not cfg:
            return self._err(f"Unknown provider: {provider_id}")
        if not api_key:
            return self._err("No API key — add env var or paste key above")
        try:
            t = cfg["type"]
            if t == "gemini":
                return self._gemini(api_key, model_id, prompt)
            elif t == "openai_compat":
                return self._openai_compat(api_key, model_id, prompt,
                                           cfg.get("base_url"))
            elif t == "huggingface":
                return self._huggingface(api_key, model_id, prompt,
                                         cfg["base_url"])
            return self._err(f"Unsupported type: {t}")
        except Exception as e:
            return self._err(str(e))

    def _gemini(self, key, model, prompt):
        if not GEMINI_AVAILABLE:
            return self._err("pip install google-generativeai")
        t0 = time.time()
        try:
            genai.configure(api_key=key)
            m    = genai.GenerativeModel(model)
            resp = m.generate_content(prompt)
            lat  = (time.time() - t0) * 1000
            u    = getattr(resp, "usage_metadata", None)
            pt   = getattr(u, "prompt_token_count",     0) if u else 0
            ct   = getattr(u, "candidates_token_count", 0) if u else 0
            tt   = getattr(u, "total_token_count", pt+ct)  if u else pt+ct
            return self._ok(pt, ct, tt, lat,
                            resp.text[:150] if resp.text else "")
        except Exception as e:
            return self._err(str(e), (time.time()-t0)*1000)

    def _openai_compat(self, key, model, prompt, base_url):
        if not OPENAI_AVAILABLE:
            return self._err("pip install openai")
        t0 = time.time()
        try:
            kw = {"api_key": key}
            if base_url:
                kw["base_url"] = base_url
            client = OpenAI(**kw)
            resp   = client.chat.completions.create(
                model    = model,
                messages = [{"role": "user", "content": prompt}],
                max_tokens = 60,
                timeout    = 30,
            )
            lat = (time.time() - t0) * 1000
            u   = resp.usage
            pt  = u.prompt_tokens     if u else 0
            ct  = u.completion_tokens if u else 0
            tt  = u.total_tokens      if u else 0
            txt = resp.choices[0].message.content[:150] if resp.choices else ""
            return self._ok(pt, ct, tt, lat, txt)
        except Exception as e:
            lat = (time.time()-t0)*1000
            es  = str(e)
            sc  = 429 if "429" in es or "rate" in es.lower() else \
                  401 if "401" in es or "auth" in es.lower() else \
                  408 if "timeout" in es.lower() else 500
            return self._err(es, lat, sc)

    def _huggingface(self, key, model, prompt, base_url):
        if not REQUESTS_AVAILABLE:
            return self._err("pip install requests")
        t0 = time.time()
        try:
            import requests as rlib
            url  = f"{base_url}/{model}"
            hdrs = {"Authorization": f"Bearer {key}",
                    "Content-Type":  "application/json"}
            body = {"inputs": prompt,
                    "parameters": {"max_new_tokens": 60}}
            r    = rlib.post(url, headers=hdrs, json=body, timeout=30)
            lat  = (time.time()-t0)*1000
            if r.status_code == 200:
                data = r.json()
                txt  = ""
                if isinstance(data, list) and data:
                    txt = data[0].get("generated_text", "")[:150]
                pt = len(prompt.split())
                ct = len(txt.split())
                return self._ok(pt, ct, pt+ct, lat, txt)
            return self._err(
                f"HTTP {r.status_code}: {r.text[:200]}", lat, r.status_code
            )
        except Exception as e:
            return self._err(str(e), (time.time()-t0)*1000)

    @staticmethod
    def _ok(pt, ct, tt, lat, txt) -> Dict[str, Any]:
        return {
            "success":           True,
            "prompt_tokens":     pt,
            "completion_tokens": ct,
            "total_tokens":      tt,
            "latency_ms":        round(lat, 2),
            "response_text":     txt,
            "status_code":       200,
            "error":             "",
        }

    @staticmethod
    def _err(msg, lat=0.0, code=500) -> Dict[str, Any]:
        return {
            "success":           False,
            "prompt_tokens":     0,
            "completion_tokens": 0,
            "total_tokens":      0,
            "latency_ms":        round(lat, 2),
            "response_text":     "",
            "status_code":       code,
            "error":             msg,
        }

# ============================================================================
# PROJECT SCANNER
# ============================================================================

class ProjectScanner:
    def __init__(self, root: str = "."):
        self.root = Path(root).resolve()

    def scan(self) -> List[ProjectFile]:
        results = []
        try:
            for fpath in self._walk():
                pf = self._analyse(fpath)
                if pf:
                    results.append(pf)
        except Exception as e:
            print(f"Scan error: {e}")
        return results

    def _walk(self):
        for dirpath, dirnames, filenames in os.walk(self.root):
            dirnames[:] = [
                d for d in dirnames
                if d not in SKIP_DIRS and not d.startswith(".")
            ]
            for fname in filenames:
                fpath = Path(dirpath) / fname
                if fpath.suffix.lower() in SCANNABLE_EXTENSIONS:
                    yield fpath

    def _analyse(self, fpath: Path) -> Optional[ProjectFile]:
        try:
            stat     = fpath.stat()
            rel_path = str(fpath.relative_to(self.root))
            providers_found: List[str] = []
            patterns_found:  List[str] = []
            lines = 0

            if stat.st_size <= 500_000:
                try:
                    content = fpath.read_text(encoding="utf-8", errors="ignore")
                    lines   = content.count("\n") + 1
                except Exception:
                    content = ""
            else:
                content = ""

            for pat_name, (regex, provider) in AI_PATTERNS.items():
                if re.search(regex, content, re.IGNORECASE):
                    patterns_found.append(pat_name)
                    if provider not in providers_found:
                        providers_found.append(provider)

            return ProjectFile(
                path          = rel_path,
                name          = fpath.name,
                extension     = fpath.suffix.lower(),
                size_bytes    = stat.st_size,
                lines         = lines,
                is_ai_agent   = len(providers_found) > 0,
                ai_providers  = providers_found,
                ai_patterns   = patterns_found,
                purpose       = self._purpose(fpath.name, content),
                last_modified = datetime.fromtimestamp(stat.st_mtime).isoformat(),
            )
        except Exception:
            return None

    @staticmethod
    def _purpose(name: str, content: str) -> str:
        nl = name.lower()
        if any(k in nl for k in ["agent", "bot"]):         return "AI Agent"
        if any(k in nl for k in ["monitor", "track"]):     return "Monitoring"
        if any(k in nl for k in ["metric", "stat"]):       return "Metrics"
        if any(k in nl for k in ["config", "setting"]):    return "Configuration"
        if any(k in nl for k in ["test", "spec"]):         return "Testing"
        if any(k in nl for k in ["deploy", "ci", "cd"]):   return "Deployment"
        if any(k in nl for k in ["model", "llm", "ai"]):   return "AI/ML"
        if any(k in nl for k in ["route", "view", "app"]): return "Application"
        if any(k in nl for k in ["util", "helper"]):       return "Utility"
        if "def " in content or "class " in content:       return "Python Module"
        return "Project File"

# ============================================================================
# MAIN SCANNER
# ============================================================================

class AIAgentScanner:

    def __init__(self):
        self.agents:          List[Agent]              = []
        self.project_files:   List[ProjectFile]        = []
        self.request_history: deque                    = deque(maxlen=200)
        self.system_metrics:  SystemMetrics            = SystemMetrics()
        self.quota_trackers:  Dict[str, QuotaTracker]  = {}
        self.api_caller       = RealAPICaller()
        self.proj_scanner     = ProjectScanner(".")
        self.key_detector     = KeyDetector()
        self._lock            = threading.Lock()
        self._start_time      = time.time()
        self._session         = {
            "prompt_tokens":     0,
            "completion_tokens": 0,
            "total_tokens":      0,
            "total_calls":       0,
            "success_calls":     0,
            "failed_calls":      0,
        }
        threading.Thread(target=self._metrics_loop, daemon=True).start()

    # ── background system metrics ─────────────────────────────
    def _metrics_loop(self):
        while True:
            try:
                vm  = psutil.virtual_memory()
                du  = psutil.disk_usage("/")
                p   = psutil.Process(os.getpid())
                with self._lock:
                    self.system_metrics = SystemMetrics(
                        cpu_percent       = psutil.cpu_percent(interval=0.5),
                        memory_percent    = vm.percent,
                        memory_used_mb    = round(vm.used  / 1024**2, 2),
                        memory_total_mb   = round(vm.total / 1024**2, 2),
                        disk_percent      = du.percent,
                        disk_used_gb      = round(du.used  / 1024**3, 2),
                        disk_total_gb     = round(du.total / 1024**3, 2),
                        process_memory_mb = round(p.memory_info().rss / 1024**2, 2),
                        uptime_seconds    = round(time.time() - self._start_time, 0),
                        thread_count      = threading.active_count(),
                    )
            except Exception:
                pass
            time.sleep(5)

    # ── get or create quota tracker ───────────────────────────
    def _get_quota(self, provider: str, model_id: str) -> QuotaTracker:
        key = f"{provider}::{model_id}"
        if key not in self.quota_trackers:
            cfg   = FREE_MODELS_REGISTRY.get(provider, {})
            minfo = next(
                (m for m in cfg.get("models", []) if m["id"] == model_id),
                {}
            )
            self.quota_trackers[key] = QuotaTracker(
                provider         = provider,
                model_id         = model_id,
                rpm_limit        = minfo.get("rpm", 0),
                rpd_limit        = minfo.get("rpd", 0),
                tpm_limit        = minfo.get("tpm", 0),
                tpd_limit        = minfo.get("tpd", 0),
                min_window_start = time.time(),
                day_window_start = time.time(),
            )
        return self.quota_trackers[key]

    # ── public: scan project ──────────────────────────────────
    def scan_project(self) -> Dict[str, Any]:
        with self._lock:
            self.project_files = self.proj_scanner.scan()
            self.agents        = self._build_agents()
        return {
            "success":         True,
            "total_files":     len(self.project_files),
            "ai_files":        sum(1 for f in self.project_files if f.is_ai_agent),
            "agents_detected": len(self.agents),
            "project_files":   [self._file_dict(f) for f in self.project_files],
            "agents":          [self._agent_dict(a) for a in self.agents],
            "system_metrics":  self._sys_dict(),
            "session_stats":   self._session_stats(),
            "quota_trackers":  {k: v.to_dict()
                                for k, v in self.quota_trackers.items()},
            "providers":       self._provider_summary(),
            "timestamp":       datetime.now().isoformat(),
        }

    # ── public: test real API ─────────────────────────────────
    def test_agent(
        self, provider: str, model: str, api_key: str, prompt: str
    ) -> Dict[str, Any]:
        if not api_key:
            api_key = self.key_detector.get_key(provider) or ""

        result = self.api_caller.call(provider, model, api_key, prompt)

        rec = RequestRecord(
            request_id        = f"REQ_{int(time.time()*1000)}",
            agent_name        = f"{provider}/{model}",
            provider          = provider,
            model             = model,
            timestamp         = datetime.now().isoformat(),
            status            = "success" if result["success"] else "failed",
            prompt_tokens     = result["prompt_tokens"],
            completion_tokens = result["completion_tokens"],
            total_tokens      = result["total_tokens"],
            latency_ms        = result["latency_ms"],
            error             = result.get("error", ""),
        )

        with self._lock:
            self.request_history.appendleft(rec)

            # update session totals
            self._session["total_calls"]       += 1
            self._session["prompt_tokens"]     += result["prompt_tokens"]
            self._session["completion_tokens"] += result["completion_tokens"]
            self._session["total_tokens"]      += result["total_tokens"]
            if result["success"]:
                self._session["success_calls"] += 1
            else:
                self._session["failed_calls"]  += 1

            # update quota tracker (used vs available)
            qt = self._get_quota(provider, model)
            qt.record(result["total_tokens"])

            # update matching agent metrics
            for agent in self.agents:
                if agent.provider.lower() in (
                    provider.lower(), model.lower()
                ):
                    self._update_agent(agent, result, rec)

        result["request_record"] = self._req_dict(rec)
        result["session_stats"]  = self._session_stats()
        result["quota"]          = self._get_quota(provider, model).to_dict()
        return result

    # ── public: dashboard ─────────────────────────────────────
    def get_dashboard_data(self) -> Dict[str, Any]:
        with self._lock:
            return {
                "system_metrics":  self._sys_dict(),
                "session_stats":   self._session_stats(),
                "agents":          [self._agent_dict(a) for a in self.agents],
                "project_files":   [self._file_dict(f)  for f in self.project_files],
                "request_history": [self._req_dict(r)
                                    for r in list(self.request_history)[:50]],
                "quota_trackers":  {k: v.to_dict()
                                    for k, v in self.quota_trackers.items()},
                "providers":       self._provider_summary(),
                "timestamp":       datetime.now().isoformat(),
            }

    # ── public: providers + free models ──────────────────────
    def get_providers_and_models(self) -> Dict[str, Any]:
        return {
            "providers": self.key_detector.get_available_providers(),
            "timestamp": datetime.now().isoformat(),
        }

    # ── internal ──────────────────────────────────────────────
    def _build_agents(self) -> List[Agent]:
        agents = []
        seen   = set()
        for f in self.project_files:
            if not f.is_ai_agent:
                continue
            for provider in f.ai_providers:
                key = f"{provider}::{f.path}"
                if key in seen:
                    continue
                seen.add(key)
                aid = hashlib.md5(key.encode()).hexdigest()[:12]
                agents.append(Agent(
                    id             = aid,
                    name           = f.name,
                    provider       = provider,
                    model          = self._guess_model(provider),
                    file_path      = f.path,
                    file_ext       = f.extension,
                    status         = "detected",
                    active         = False,
                    metrics        = AgentMetrics(),
                    patterns_found = f.ai_patterns,
                    purpose        = f.purpose,
                    source         = "project_scan",
                    detected_at    = datetime.now().isoformat(),
                ))
        return agents

    @staticmethod
    def _guess_model(provider: str) -> str:
        return {
            "Gemini":      "gemini-2.0-flash",
            "OpenAI":      "gpt-4o",
            "Anthropic":   "claude-3-haiku",
            "Groq":        "llama-3.1-8b-instant",
            "NVIDIA":      "meta/llama-3.1-8b-instruct",
            "HuggingFace": "mistralai/Mistral-7B-Instruct-v0.3",
            "Mistral":     "mistral-small-latest",
            "OpenRouter":  "meta-llama/llama-3.1-8b-instruct:free",
            "LangChain":   "multiple",
            "LiteLLM":     "multiple",
            "CrewAI":      "multiple",
        }.get(provider, "unknown")

    @staticmethod
    def _update_agent(
        agent: Agent, result: Dict[str, Any], rec: RequestRecord
    ):
        m = agent.metrics
        m.total_calls       += 1
        m.total_tokens      += result["total_tokens"]
        m.prompt_tokens     += result["prompt_tokens"]
        m.completion_tokens += result["completion_tokens"]
        m.total_latency_ms  += result["latency_ms"]
        m.last_call_time     = rec.timestamp
        m.last_status        = rec.status
        m.last_error         = result.get("error", "")
        if result["success"]:
            m.success_calls  += 1
            m.min_latency_ms  = min(m.min_latency_ms, result["latency_ms"])
            m.max_latency_ms  = max(m.max_latency_ms, result["latency_ms"])
            agent.status      = "active"
            agent.active      = True
        else:
            m.failed_calls   += 1
            sc = result.get("status_code", 500)
            if sc == 429: m.rate_limit_hits += 1
            if sc == 401: m.auth_failures   += 1

    def _provider_summary(self) -> Dict[str, Any]:
        summary: Dict[str, Any] = {}
        for a in self.agents:
            p = a.provider
            if p not in summary:
                summary[p] = {
                    "name":           p,
                    "agent_count":    0,
                    "active_count":   0,
                    "total_tokens":   0,
                    "total_calls":    0,
                    "success_calls":  0,
                    "avg_latency_ms": 0.0,
                    "files":          [],
                }
            s = summary[p]
            m = a.metrics
            s["agent_count"]  += 1
            s["active_count"] += int(a.active)
            s["total_tokens"] += m.total_tokens
            s["total_calls"]  += m.total_calls
            s["success_calls"]+= m.success_calls
            if a.file_path not in s["files"]:
                s["files"].append(a.file_path)
            if m.total_calls:
                s["avg_latency_ms"] = round(
                    m.total_latency_ms / m.total_calls, 2
                )
        return summary

    def _session_stats(self) -> Dict[str, Any]:
        sc  = self._session["total_calls"]
        ss  = self._session["success_calls"]
        sf  = self._session["failed_calls"]
        rpm = sum(
            1 for r in self.request_history
            if datetime.fromisoformat(r.timestamp)
               > datetime.now() - timedelta(minutes=1)
        )
        return {
            "total_calls":       sc,
            "success_calls":     ss,
            "failed_calls":      sf,
            "success_rate":      round(ss/sc*100, 2) if sc else 0.0,
            "prompt_tokens":     self._session["prompt_tokens"],
            "completion_tokens": self._session["completion_tokens"],
            "total_tokens":      self._session["total_tokens"],
            "rpm":               rpm,
            "rph":               rpm * 60,
            "rpd":               rpm * 60 * 24,
            "uptime_seconds":    round(time.time() - self._start_time, 0),
        }

    # ── serialisers ───────────────────────────────────────────
    def _sys_dict(self) -> Dict[str, Any]:
        m = self.system_metrics
        return {
            "cpu_percent":       m.cpu_percent,
            "memory_percent":    m.memory_percent,
            "memory_used_mb":    m.memory_used_mb,
            "memory_total_mb":   m.memory_total_mb,
            "disk_percent":      m.disk_percent,
            "disk_used_gb":      m.disk_used_gb,
            "disk_total_gb":     m.disk_total_gb,
            "process_memory_mb": m.process_memory_mb,
            "uptime_seconds":    m.uptime_seconds,
            "thread_count":      m.thread_count,
        }

    @staticmethod
    def _agent_dict(a: Agent) -> Dict[str, Any]:
        m   = a.metrics
        avg = round(m.total_latency_ms/m.total_calls, 2) if m.total_calls else 0.0
        return {
            "id":             a.id,
            "name":           a.name,
            "provider":       a.provider,
            "model":          a.model,
            "file_path":      a.file_path,
            "file_ext":       a.file_ext,
            "status":         a.status,
            "active":         a.active,
            "purpose":        a.purpose,
            "patterns_found": a.patterns_found,
            "detected_at":    a.detected_at,
            "metrics": {
                "total_calls":       m.total_calls,
                "success_calls":     m.success_calls,
                "failed_calls":      m.failed_calls,
                "total_tokens":      m.total_tokens,
                "prompt_tokens":     m.prompt_tokens,
                "completion_tokens": m.completion_tokens,
                "avg_latency_ms":    avg,
                "min_latency_ms":    m.min_latency_ms if m.min_latency_ms != float("inf") else 0,
                "max_latency_ms":    m.max_latency_ms,
                "rate_limit_hits":   m.rate_limit_hits,
                "auth_failures":     m.auth_failures,
                "last_call_time":    m.last_call_time,
                "last_status":       m.last_status,
                "last_error":        m.last_error,
                "success_rate":      round(m.success_calls/m.total_calls*100, 2) if m.total_calls else 0.0,
            },
        }

    @staticmethod
    def _file_dict(f: ProjectFile) -> Dict[str, Any]:
        return {
            "path":          f.path,
            "name":          f.name,
            "extension":     f.extension,
            "size_bytes":    f.size_bytes,
            "size_kb":       round(f.size_bytes/1024, 2),
            "lines":         f.lines,
            "is_ai_agent":   f.is_ai_agent,
            "ai_providers":  f.ai_providers,
            "ai_patterns":   f.ai_patterns,
            "purpose":       f.purpose,
            "last_modified": f.last_modified,
        }

    @staticmethod
    def _req_dict(r: RequestRecord) -> Dict[str, Any]:
        return {
            "request_id":        r.request_id,
            "agent_name":        r.agent_name,
            "provider":          r.provider,
            "model":             r.model,
            "timestamp":         r.timestamp,
            "status":            r.status,
            "prompt_tokens":     r.prompt_tokens,
            "completion_tokens": r.completion_tokens,
            "total_tokens":      r.total_tokens,
            "latency_ms":        r.latency_ms,
            "error":             r.error,
        }

    def save_report(self) -> bytes:
        with self._lock:
            data = {
                "generated_at":    datetime.now().isoformat(),
                "session_stats":   self._session_stats(),
                "system_metrics":  self._sys_dict(),
                "quota_trackers":  {k: v.to_dict()
                                    for k, v in self.quota_trackers.items()},
                "agents":          [self._agent_dict(a) for a in self.agents],
                "project_files":   [self._file_dict(f)  for f in self.project_files],
                "request_history": [self._req_dict(r)   for r in self.request_history],
                "providers":       self._provider_summary(),
            }
        return json.dumps(data, indent=2).encode()


# ============================================================================
# FLASK APPLICATION
# ============================================================================

application = Flask(__name__)
CORS(application)
scanner = AIAgentScanner()

# ============================================================================
# HTML TEMPLATE
# ============================================================================
HTML_TEMPLATE = r"""
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>AI Agent Monitor</title>
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:'Segoe UI',Tahoma,Geneva,Verdana,sans-serif;
     background:linear-gradient(135deg,#0f0c29,#302b63,#24243e);
     min-height:100vh;padding:20px;color:#e0e0e0}
.wrap{max-width:1500px;margin:0 auto}

/* header */
header{text-align:center;margin-bottom:26px;animation:slideDown .6s ease-out}
header h1{font-size:2.3em;
  background:linear-gradient(90deg,#667eea,#f093fb,#4facfe);
  -webkit-background-clip:text;-webkit-text-fill-color:transparent;margin-bottom:6px}
header p{opacity:.6;font-size:.9em}

/* provider panel */
.pp{background:rgba(255,255,255,.05);backdrop-filter:blur(12px);
    border:1px solid rgba(255,255,255,.1);border-radius:16px;
    padding:22px;margin-bottom:20px}
.pp-title{color:#f093fb;font-size:1.1em;font-weight:700;
          margin-bottom:16px;display:flex;align-items:center;gap:8px}

/* provider cards */
.prov-cards{display:grid;
  grid-template-columns:repeat(auto-fill,minmax(200px,1fr));
  gap:10px;margin-bottom:18px}
.pc{border-radius:10px;padding:13px;cursor:pointer;
    border:2px solid transparent;transition:all .22s;position:relative}
.pc.avail{background:rgba(56,239,125,.07);border-color:rgba(56,239,125,.2)}
.pc.avail:hover{border-color:#38ef7d;box-shadow:0 0 16px rgba(56,239,125,.2)}
.pc.avail.sel{border-color:#38ef7d;background:rgba(56,239,125,.14)}
.pc.locked{background:rgba(255,255,255,.03);
           border-color:rgba(255,255,255,.07);cursor:default;opacity:.55}
.pc-name{font-weight:700;font-size:.9em;margin-bottom:3px}
.pc-info{color:#888;font-size:.72em}
.pc-badge{position:absolute;top:9px;right:9px;
          font-size:.65em;padding:2px 7px;border-radius:10px;font-weight:700}
.bf{background:rgba(56,239,125,.2);color:#38ef7d;border:1px solid rgba(56,239,125,.35)}
.bl{background:rgba(255,82,82,.12);color:#ff8a80;border:1px solid rgba(255,82,82,.25)}
.su{display:inline-block;margin-top:5px;font-size:.7em;color:#4facfe;text-decoration:none}
.su:hover{text-decoration:underline}

/* model row */
.model-row{display:grid;grid-template-columns:1.2fr 1fr 2fr auto;
           gap:12px;align-items:end;margin-bottom:14px}
.fld{display:flex;flex-direction:column;gap:5px}
.fld label{color:#aaa;font-size:.74em;font-weight:700;text-transform:uppercase}
select,input[type=text],input[type=password]{
  width:100%;padding:10px 12px;
  background:rgba(255,255,255,.08);
  border:1px solid rgba(255,255,255,.14);
  border-radius:8px;color:#e0e0e0;font-size:.9em;transition:all .25s}
select:focus,input:focus{outline:none;border-color:#667eea;
  background:rgba(102,126,234,.12)}
select option{background:#1a1a2e;color:#e0e0e0}
.model-tags{font-size:.68em;color:#888;margin-top:3px}
.model-tags span{background:rgba(56,239,125,.14);color:#38ef7d;
                 padding:1px 7px;border-radius:8px;margin-right:4px}
.model-tags span.caution{background:rgba(255,193,7,.14);color:#ffc107}

/* buttons */
.btn-row{display:flex;gap:9px;flex-wrap:wrap}
.btn{padding:10px 18px;border:none;border-radius:8px;font-size:.85em;
     font-weight:700;cursor:pointer;transition:all .22s;
     text-transform:uppercase;letter-spacing:.4px}
.bp{background:linear-gradient(135deg,#667eea,#764ba2);color:#fff}
.bp:hover{transform:translateY(-2px);box-shadow:0 6px 18px rgba(102,126,234,.4)}
.bs{background:linear-gradient(135deg,#11998e,#38ef7d);color:#000}
.bs:hover{transform:translateY(-2px);box-shadow:0 6px 18px rgba(56,239,125,.3)}
.bi{background:linear-gradient(135deg,#4facfe,#00f2fe);color:#000}
.bi:hover{transform:translateY(-2px)}
.bw{background:linear-gradient(135deg,#f7971e,#ffd200);color:#000}
.bw:hover{transform:translateY(-2px)}

/* messages */
.msg{padding:11px 15px;border-radius:8px;margin-top:11px;
     font-weight:500;font-size:.87em}
.ms{background:rgba(56,239,125,.1);color:#38ef7d;border:1px solid rgba(56,239,125,.25)}
.me{background:rgba(255,82,82,.1); color:#ff5252;border:1px solid rgba(255,82,82,.25)}
.mi{background:rgba(79,172,254,.1);color:#4facfe;border:1px solid rgba(79,172,254,.25)}

/* test result */
.rb{background:rgba(0,0,0,.35);border:1px solid rgba(255,255,255,.1);
    border-radius:12px;padding:16px;margin-top:14px;display:none}
.rb-title{color:#f093fb;font-weight:700;margin-bottom:12px;font-size:.92em}
.rg{display:grid;grid-template-columns:repeat(auto-fit,minmax(130px,1fr));gap:10px}
.ri{background:rgba(255,255,255,.05);border-radius:8px;padding:11px;text-align:center}
.ri-l{color:#666;font-size:.68em;text-transform:uppercase;margin-bottom:4px}
.ri-v{font-size:1.1em;font-weight:800;color:#e0e0e0}
.resp-box{margin-top:11px;background:rgba(255,255,255,.04);border-radius:8px;
          padding:11px;font-family:monospace;font-size:.8em;color:#999;
          word-break:break-all}

/* ── QUOTA SECTION ── */
.quota-section{margin-bottom:20px;display:none}
.quota-title{color:#f093fb;font-size:1em;font-weight:700;
             margin-bottom:12px;display:flex;align-items:center;gap:7px}
.quota-grid{display:grid;
  grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:14px}
.quota-card{background:rgba(255,255,255,.05);
            border:1px solid rgba(255,255,255,.09);border-radius:12px;padding:16px}
.qc-head{display:flex;justify-content:space-between;
         align-items:center;margin-bottom:13px}
.qc-name{font-weight:700;font-size:.9em;color:#f093fb}
.qc-model{font-size:.72em;color:#777;font-family:monospace}
.quota-rows{display:flex;flex-direction:column;gap:9px}
.qrow{display:flex;flex-direction:column;gap:4px}
.qrow-head{display:flex;justify-content:space-between;font-size:.75em}
.qrow-label{color:#888}
.qrow-nums{color:#ccc;font-family:monospace}
.qrow-nums .used{color:#f093fb;font-weight:700}
.qrow-nums .avail{color:#38ef7d}
.qrow-nums .limit{color:#555}
.qbar{width:100%;height:5px;background:rgba(255,255,255,.07);
      border-radius:3px;overflow:hidden}
.qfill{height:100%;border-radius:3px;transition:width .5s ease;
       background:linear-gradient(90deg,#667eea,#f093fb)}
.qfill.warn  {background:linear-gradient(90deg,#f7971e,#ffd200)}
.qfill.danger{background:linear-gradient(90deg,#f44336,#ff5252)}

/* system metrics */
.sg{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));
    gap:12px;margin-bottom:20px;display:none}
.sc{background:rgba(255,255,255,.05);border:1px solid rgba(255,255,255,.08);
    border-radius:12px;padding:15px;text-align:center;
    border-top:3px solid #667eea;
    animation:fadeIn .5s ease-out forwards;opacity:0}
.sc:nth-child(2){border-top-color:#f093fb;animation-delay:.08s}
.sc:nth-child(3){border-top-color:#4facfe;animation-delay:.16s}
.sc:nth-child(4){border-top-color:#38ef7d;animation-delay:.24s}
.sc:nth-child(5){border-top-color:#ffd200;animation-delay:.32s}
.sc:nth-child(6){border-top-color:#ff5252;animation-delay:.40s}
.sl{color:#777;font-size:.7em;text-transform:uppercase;margin-bottom:6px}
.sv{font-size:1.7em;font-weight:800;
    background:linear-gradient(90deg,#667eea,#f093fb);
    -webkit-background-clip:text;-webkit-text-fill-color:transparent}
.ss{color:#555;font-size:.7em;margin-top:3px}
.pb{width:100%;height:5px;background:rgba(255,255,255,.08);
    border-radius:3px;overflow:hidden;margin-top:6px}
.pf{height:100%;border-radius:3px;transition:width .5s;
    background:linear-gradient(90deg,#667eea,#f093fb)}
.pf.warn  {background:linear-gradient(90deg,#f7971e,#ffd200)}
.pf.danger{background:linear-gradient(90deg,#f44336,#ff5252)}

/* main section */
.ms-wrap{background:rgba(255,255,255,.04);border:1px solid rgba(255,255,255,.07);
         border-radius:14px;padding:20px;margin-bottom:18px;display:none}
.tabs{display:flex;gap:5px;margin-bottom:16px;flex-wrap:wrap;
      border-bottom:1px solid rgba(255,255,255,.07);padding-bottom:7px}
.tb{background:none;border:none;padding:8px 14px;cursor:pointer;
    color:#555;font-weight:600;border-radius:7px 7px 0 0;
    transition:all .22s;font-size:.8em;text-transform:uppercase}
.tb.active{background:rgba(102,126,234,.18);color:#667eea;
           border-bottom:2px solid #667eea}
.tc{display:none}
.tc.active{display:block;animation:fadeIn .3s ease-out}

/* tables */
.tbl{width:100%;border-collapse:collapse;font-size:.83em}
.tbl th{background:rgba(255,255,255,.06);padding:9px 12px;text-align:left;
        color:#777;font-weight:700;text-transform:uppercase;font-size:.72em;
        border-bottom:1px solid rgba(255,255,255,.06)}
.tbl td{padding:9px 12px;border-bottom:1px solid rgba(255,255,255,.04);color:#bbb}
.tbl tr:hover td{background:rgba(255,255,255,.025)}
.mono{font-family:monospace;font-size:.8em;color:#777}

/* agent cards */
.ac{background:rgba(255,255,255,.04);border:1px solid rgba(255,255,255,.07);
    border-left:4px solid #667eea;border-radius:10px;
    padding:17px;margin-bottom:13px;transition:all .22s}
.ac:hover{transform:translateX(4px);box-shadow:0 4px 18px rgba(102,126,234,.15)}
.ac.active-a{border-left-color:#38ef7d}
.ac.error-a {border-left-color:#ff5252}
.ah{display:grid;grid-template-columns:2fr 1fr 1fr 1fr;gap:13px;margin-bottom:11px}
.al{color:#555;font-size:.68em;text-transform:uppercase;margin-bottom:3px}
.av{color:#e0e0e0;font-weight:600;font-size:.88em}
.am{display:grid;grid-template-columns:repeat(auto-fit,minmax(90px,1fr));gap:8px}
.mm{background:rgba(255,255,255,.05);border-radius:7px;padding:8px;text-align:center}
.ml{color:#555;font-size:.66em;text-transform:uppercase;margin-bottom:3px}
.mv{color:#ddd;font-weight:700;font-size:.95em}

/* file rows */
.fr{display:grid;grid-template-columns:2.5fr 1fr 1fr 1fr 2fr;
    gap:9px;align-items:center;padding:8px 11px;
    border-bottom:1px solid rgba(255,255,255,.04);font-size:.82em}
.fr:hover{background:rgba(255,255,255,.025)}
.fh{color:#666;font-size:.7em;text-transform:uppercase;font-weight:700}

/* badges */
.badge{display:inline-block;padding:3px 9px;border-radius:11px;font-size:.71em;font-weight:700}
.bok {background:rgba(56,239,125,.15);color:#38ef7d;border:1px solid rgba(56,239,125,.3)}
.berr{background:rgba(255,82,82,.15); color:#ff5252;border:1px solid rgba(255,82,82,.3)}
.bwrn{background:rgba(255,193,7,.15); color:#ffc107;border:1px solid rgba(255,193,7,.3)}
.bgry{background:rgba(200,200,200,.07);color:#888;  border:1px solid rgba(200,200,200,.15)}
.binf{background:rgba(79,172,254,.15);color:#4facfe;border:1px solid rgba(79,172,254,.3)}

/* req summary bar */
.rsb{display:flex;gap:18px;flex-wrap:wrap;
     background:rgba(255,255,255,.04);border-radius:9px;
     padding:12px 16px;margin-bottom:14px;font-size:.83em;display:none}
.rsi{display:flex;flex-direction:column;gap:2px}
.rsl{color:#666;font-size:.7em;text-transform:uppercase}
.rsv{color:#e0e0e0;font-weight:700;font-size:1.05em}

/* live dot */
.live{width:7px;height:7px;background:#38ef7d;border-radius:50%;
      display:inline-block;margin-right:5px;animation:pulse 2s infinite}

/* spinner */
.spn{width:34px;height:34px;border:3px solid rgba(255,255,255,.08);
     border-top:3px solid #667eea;border-radius:50%;
     animation:spin 1s linear infinite;margin:0 auto 12px}
.ldw{text-align:center;padding:32px;display:none}

@keyframes slideDown{from{opacity:0;transform:translateY(-16px)}to{opacity:1;transform:translateY(0)}}
@keyframes fadeIn   {from{opacity:0}to{opacity:1}}
@keyframes spin     {to{transform:rotate(360deg)}}
@keyframes pulse    {0%,100%{opacity:1}50%{opacity:.3}}

@media(max-width:900px){
  .model-row{grid-template-columns:1fr 1fr}
  .ah{grid-template-columns:1fr 1fr}
  .fr{grid-template-columns:1fr 1fr}
  .prov-cards{grid-template-columns:repeat(auto-fill,minmax(160px,1fr))}
}
@media(max-width:560px){
  .model-row,.ah,.quota-grid{grid-template-columns:1fr}
}
</style>
</head>
<body>
<div class="wrap">

<!-- HEADER -->
<header>
  <h1>🤖 AI Agent Monitor</h1>
  <p><span class="live"></span>Real project scanner · Real API metrics · Free models only · Live quota tracking</p>
</header>

<!-- ══════════ PROVIDER PANEL ══════════ -->
<div class="pp">
  <div class="pp-title">🔌 Select Provider &amp; Free Model</div>

  <div class="prov-cards" id="provCards">
    <div style="color:#555;padding:16px">Loading providers…</div>
  </div>

  <div class="model-row">
    <div class="fld">
      <label>Free Model</label>
      <select id="modelSel" onchange="onModelChange()"></select>
      <div class="model-tags" id="modelTags"></div>
    </div>
    <div class="fld">
      <label>API Key <span style="color:#555;font-size:.85em">(or uses env var)</span></label>
      <input type="password" id="apiKey" placeholder="Leave blank → auto from env var">
    </div>
    <div class="fld">
      <label>Test Prompt</label>
      <input type="text" id="prompt" value="Say OK in one word.">
    </div>
    <div class="fld">
      <label>&nbsp;</label>
      <div class="btn-row">
        <button class="btn bp" onclick="scanProject()">📁 SCAN</button>
        <button class="btn bs" onclick="testAgent()">🚀 TEST API</button>
        <button class="btn bi" onclick="refreshAll()">🔄 REFRESH</button>
        <button class="btn bw" onclick="downloadReport()">📥 REPORT</button>
      </div>
    </div>
  </div>

  <div id="msgs"></div>

  <!-- test result box -->
  <div class="rb" id="testResult">
    <div class="rb-title">⚡ Real API Call Result</div>
    <div class="rg">
      <div class="ri"><div class="ri-l">Status</div>            <div class="ri-v" id="r-status">—</div></div>
      <div class="ri"><div class="ri-l">Latency</div>           <div class="ri-v" id="r-lat">—</div></div>
      <div class="ri"><div class="ri-l">Prompt Tokens</div>     <div class="ri-v" id="r-pt">—</div></div>
      <div class="ri"><div class="ri-l">Completion Tokens</div> <div class="ri-v" id="r-ct">—</div></div>
      <div class="ri"><div class="ri-l">Total Tokens</div>      <div class="ri-v" id="r-tt">—</div></div>
      <div class="ri"><div class="ri-l">RPM Used / Limit</div>  <div class="ri-v" id="r-rpm">—</div></div>
      <div class="ri"><div class="ri-l">RPD Used / Limit</div>  <div class="ri-v" id="r-rpd">—</div></div>
      <div class="ri"><div class="ri-l">TPM Used / Limit</div>  <div class="ri-v" id="r-tpm">—</div></div>
    </div>
    <div class="resp-box" id="r-resp"></div>
  </div>
</div>

<!-- ══════════ QUOTA TRACKER ══════════ -->
<div class="quota-section" id="quotaSection">
  <div class="quota-title">📊 Live Quota — Used vs Available</div>
  <div class="quota-grid" id="quotaGrid"></div>
</div>

<!-- loading -->
<div class="ldw" id="ldw">
  <div class="spn"></div>
  <p style="color:#666">Scanning project files…</p>
</div>

<!-- ══════════ SYSTEM METRICS ══════════ -->
<div class="sg" id="sysGrid">
  <div class="sc">
    <div class="sl">CPU</div>
    <div class="sv" id="s-cpu">—</div>
    <div class="pb"><div class="pf" id="b-cpu" style="width:0%"></div></div>
  </div>
  <div class="sc">
    <div class="sl">Memory</div>
    <div class="sv" id="s-mem">—</div>
    <div class="ss" id="s-mem-s">—</div>
    <div class="pb"><div class="pf" id="b-mem" style="width:0%"></div></div>
  </div>
  <div class="sc">
    <div class="sl">Disk</div>
    <div class="sv" id="s-disk">—</div>
    <div class="ss" id="s-disk-s">—</div>
    <div class="pb"><div class="pf" id="b-disk" style="width:0%"></div></div>
  </div>
  <div class="sc">
    <div class="sl">Session Tokens</div>
    <div class="sv" id="s-tok">0</div>
    <div class="ss" id="s-tok-s">prompt + completion</div>
  </div>
  <div class="sc">
    <div class="sl">API Calls</div>
    <div class="sv" id="s-calls">0</div>
    <div class="ss" id="s-calls-s">success / failed</div>
  </div>
  <div class="sc">
    <div class="sl">Process Mem</div>
    <div class="sv" id="s-proc">—</div>
    <div class="ss" id="s-proc-s">this app</div>
  </div>
</div>

<!-- ══════════ MAIN CONTENT ══════════ -->
<div class="ms-wrap" id="mainWrap">
  <div class="tabs">
    <button class="tb active" onclick="tab('agents',   this)">🤖 Agents</button>
    <button class="tb"        onclick="tab('files',    this)">📁 Files</button>
    <button class="tb"        onclick="tab('requests', this)">📊 Requests</button>
    <button class="tb"        onclick="tab('providers',this)">🏢 Providers</button>
  </div>

  <!-- AGENTS -->
  <div id="agents" class="tc active">
    <div id="agentsList">
      <p style="color:#555;text-align:center;padding:28px">Click SCAN to detect AI agents</p>
    </div>
  </div>

  <!-- FILES -->
  <div id="files" class="tc">
    <div style="display:flex;gap:11px;align-items:center;margin-bottom:13px;flex-wrap:wrap">
      <input type="text" id="fileSearch" placeholder="Filter files…"
             oninput="filterFiles()" style="max-width:260px">
      <label style="color:#888;font-size:.83em;display:flex;align-items:center;gap:5px;cursor:pointer">
        <input type="checkbox" id="aiOnly" onchange="filterFiles()"> AI files only
      </label>
      <span id="fileCount" style="color:#555;font-size:.8em"></span>
    </div>
    <div class="fr fh">
      <div>File Path</div><div>Type</div><div>Lines</div>
      <div>Size</div><div>AI Providers</div>
    </div>
    <div id="filesList"></div>
  </div>

  <!-- REQUESTS -->
  <div id="requests" class="tc">
    <div class="rsb" id="reqSummary">
      <div class="rsi"><div class="rsl">Total</div>      <div class="rsv" id="rq-tot">0</div></div>
      <div class="rsi"><div class="rsl">Success</div>    <div class="rsv" id="rq-ok"  style="color:#38ef7d">0</div></div>
      <div class="rsi"><div class="rsl">Failed</div>     <div class="rsv" id="rq-fail"style="color:#ff5252">0</div></div>
      <div class="rsi"><div class="rsl">Total Tokens</div><div class="rsv" id="rq-tok">0</div></div>
      <div class="rsi"><div class="rsl">Prompt Tokens</div><div class="rsv" id="rq-pt">0</div></div>
      <div class="rsi"><div class="rsl">Complete Tokens</div><div class="rsv" id="rq-ct">0</div></div>
      <div class="rsi"><div class="rsl">Avg Latency</div><div class="rsv" id="rq-lat">0ms</div></div>
    </div>
    <table class="tbl">
      <thead><tr>
        <th>Time</th><th>Provider</th><th>Model</th><th>Status</th>
        <th>Prompt T</th><th>Comp T</th><th>Total T</th>
        <th>Latency</th><th>Error</th>
      </tr></thead>
      <tbody id="reqTable"></tbody>
    </table>
  </div>

  <!-- PROVIDERS -->
  <div id="providers" class="tc">
    <div id="provList"></div>
  </div>
</div>

</div><!-- /wrap -->
<script>
// ═══════════════════════════════════════════════
// STATE
// ═══════════════════════════════════════════════
let selProv   = null;
let allProvs  = {};
let allFiles  = [];

// ═══════════════════════════════════════════════
// HELPERS
// ═══════════════════════════════════════════════
function fmt(n){
  if(n==null||n===undefined) return '—';
  if(n>=1e9) return (n/1e9).toFixed(2)+'B';
  if(n>=1e6) return (n/1e6).toFixed(2)+'M';
  if(n>=1e3) return (n/1e3).toFixed(1)+'K';
  return String(n);
}
function esc(t){
  const d=document.createElement('div');
  d.textContent=String(t??''); return d.innerHTML;
}
function showMsg(msg,type='info'){
  const el=document.getElementById('msgs');
  el.innerHTML=`<div class="msg m${type[0]}">${msg}</div>`;
  if(type!=='error') setTimeout(()=>el.innerHTML='',7000);
}
function setBar(id,pct){
  const el=document.getElementById(id);
  if(!el) return;
  el.style.width=Math.min(pct,100)+'%';
  el.className='pf'+(pct>85?' danger':pct>65?' warn':'');
}
function setQBar(el,pct){
  el.style.width=Math.min(pct,100)+'%';
  el.className='qfill'+(pct>85?' danger':pct>65?' warn':'');
}

// ═══════════════════════════════════════════════
// LOAD PROVIDERS
// ═══════════════════════════════════════════════
async function loadProviders(){
  try{
    const res  = await fetch('/api/providers/models');
    const data = await res.json();
    allProvs   = data.providers;
    renderProvCards(allProvs);
    const first = Object.values(allProvs).find(p=>p.available);
    if(first) selProv_(first.id);
  }catch(e){
    document.getElementById('provCards').innerHTML=
      `<div style="color:#ff5252">Failed: ${e.message}</div>`;
  }
}

// ═══════════════════════════════════════════════
// RENDER PROVIDER CARDS
// ═══════════════════════════════════════════════
function renderProvCards(provs){
  document.getElementById('provCards').innerHTML =
    Object.values(provs).map(p=>`
      <div class="pc ${p.available?'avail':'locked'}" id="pc-${p.id}"
           onclick="${p.available?`selProv_('${p.id}')`:''}" >
        <span class="pc-badge ${p.available?'bf':'bl'}">
          ${p.available?'🆓 KEY FOUND':'🔒 NO KEY'}
        </span>
        <div class="pc-name">${esc(p.name)}</div>
        <div class="pc-info">${p.model_count} free models</div>
        ${p.available
          ?`<div class="pc-info" style="color:#38ef7d;margin-top:3px">
              ✅ ${esc(p.env_var)}</div>
            <div class="pc-info" style="margin-top:2px">
              ${p.daily_limit_requests?fmt(p.daily_limit_requests)+' req/day':''}
              ${p.daily_limit_tokens?'· '+fmt(p.daily_limit_tokens)+' tok/day':''}
            </div>`
          :`<div class="pc-info" style="margin-top:3px">
              <code style="color:#f093fb">${esc(p.env_var)}</code>
              <a class="su" href="${esc(p.signup_url)}" target="_blank">
                🔗 Get free key</a>
            </div>`
        }
      </div>
    `).join('');
}

// ═══════════════════════════════════════════════
// SELECT PROVIDER → POPULATE FREE MODELS
// ═══════════════════════════════════════════════
function selProv_(pid){
  selProv = pid;
  document.querySelectorAll('.pc').forEach(c=>c.classList.remove('sel'));
  const card = document.getElementById(`pc-${pid}`);
  if(card) card.classList.add('sel');

  const prov  = allProvs[pid];
  const sel   = document.getElementById('modelSel');
  sel.innerHTML = (prov?.models||[]).map(m=>`
    <option value="${esc(m.id)}"
            data-tier="${m.tier}"
            data-rpm="${m.rpm}"
            data-rpd="${m.rpd}"
            data-tpm="${m.tpm}"
            data-tpd="${m.tpd}"
            data-ctx="${esc(m.context)}"
            data-type="${esc(m.type)}"
            ${m.recommended?'data-rec="1"':''}>
      ${m.recommended?'⭐ ':''}${m.tier==='caution'?'⚠️ ':'🆓 '}${esc(m.name)}
    </option>
  `).join('');
  onModelChange();
}

// ═══════════════════════════════════════════════
// MODEL CHANGE → SHOW TAGS
// ═══════════════════════════════════════════════
function onModelChange(){
  const sel = document.getElementById('modelSel');
  const opt = sel.options[sel.selectedIndex];
  if(!opt) return;
  const tier = opt.getAttribute('data-tier');
  const rpm  = opt.getAttribute('data-rpm');
  const rpd  = opt.getAttribute('data-rpd');
  const tpm  = opt.getAttribute('data-tpm');
  const tpd  = opt.getAttribute('data-tpd');
  const ctx  = opt.getAttribute('data-ctx');
  const type = opt.getAttribute('data-type');
  const rec  = opt.getAttribute('data-rec');
  const caut = tier==='caution';
  document.getElementById('modelTags').innerHTML =
    `<span class="${caut?'caution':''}">${caut?'⚠️ Caution':'🆓 Safe Free'}</span>`+
    (rec?`<span>⭐ Recommended</span>`:'')+
    (type?`<span>${esc(type)}</span>`:'')+
    (rpm?`<span>${rpm} RPM limit</span>`:'')+
    (rpd?`<span>${fmt(parseInt(rpd))} RPD limit</span>`:'')+
    (tpm&&tpm!='0'?`<span>${fmt(parseInt(tpm))} TPM limit</span>`:'')+
    (ctx?`<span>${esc(ctx)} context</span>`:'');
}

// ═══════════════════════════════════════════════
// SCAN PROJECT
// ═══════════════════════════════════════════════
async function scanProject(){
  document.getElementById('ldw').style.display='block';
  document.getElementById('mainWrap').style.display='none';
  try{
    const res  = await fetch('/api/scan/project',{method:'POST'});
    const data = await res.json();
    if(data.success){
      renderSysMetrics(data.system_metrics, data.session_stats);
      renderAgents(data.agents);
      allFiles = data.project_files;
      renderFiles(allFiles);
      renderProvSummary(data.providers);
      if(data.quota_trackers) renderQuota(data.quota_trackers);
      document.getElementById('sysGrid').style.display='grid';
      document.getElementById('mainWrap').style.display='block';
      showMsg(
        `✅ Scanned <b>${data.total_files}</b> files · `+
        `<b>${data.ai_files}</b> AI files · `+
        `<b>${data.agents_detected}</b> agents detected`,
        'success'
      );
    } else {
      showMsg(data.error||'Scan failed','error');
    }
  }catch(e){
    showMsg('Error: '+e.message,'error');
  } finally {
    document.getElementById('ldw').style.display='none';
  }
}

// ═══════════════════════════════════════════════
// TEST AGENT
// ═══════════════════════════════════════════════
async function testAgent(){
  if(!selProv){ showMsg('Select a provider first','error'); return; }
  const model  = document.getElementById('modelSel').value;
  const apiKey = document.getElementById('apiKey').value.trim();
  const prompt = document.getElementById('prompt').value.trim()||'Say OK in one word.';
  showMsg(`⚡ Calling ${selProv}/${model}…`,'info');
  document.getElementById('testResult').style.display='none';
  try{
    const res  = await fetch('/api/agent/test',{
      method:'POST',
      headers:{'Content-Type':'application/json'},
      body:JSON.stringify({provider:selProv,model,api_key:apiKey,prompt})
    });
    const data = await res.json();

    // fill result box
    const rb = document.getElementById('testResult');
    rb.style.display='block';
    document.getElementById('r-status').innerHTML = data.success
      ?'<span class="badge bok">✅ SUCCESS</span>'
      :'<span class="badge berr">❌ FAILED</span>';
    document.getElementById('r-lat').textContent = data.latency_ms+'ms';
    document.getElementById('r-pt').textContent  = data.prompt_tokens;
    document.getElementById('r-ct').textContent  = data.completion_tokens;
    document.getElementById('r-tt').textContent  = data.total_tokens;
    document.getElementById('r-resp').textContent=
      data.response_text||data.error||'(no response)';

    // quota cells from returned quota object
    if(data.quota){
      const q=data.quota;
      document.getElementById('r-rpm').textContent=
        `${q.requests_this_min} / ${q.rpm_limit} (${q.rpm_remaining} left)`;
      document.getElementById('r-rpd').textContent=
        `${q.requests_today} / ${q.rpd_limit} (${q.rpd_remaining} left)`;
      document.getElementById('r-tpm').textContent=
        q.tpm_limit
          ?`${fmt(q.tokens_this_min)} / ${fmt(q.tpm_limit)} (${fmt(q.tpm_remaining)} left)`
          :'N/A';
      renderQuota({'quota': q});
    }

    if(data.session_stats) updateSession(data.session_stats);
    if(data.request_record) prependRow(data.request_record);

    document.getElementById('sysGrid').style.display='grid';
    document.getElementById('mainWrap').style.display='block';
    document.getElementById('quotaSection').style.display='block';

    showMsg(
      data.success
        ?`✅ ${model}: ${data.total_tokens} tokens · ${data.latency_ms}ms`
        :`❌ ${model}: ${data.error}`,
      data.success?'success':'error'
    );
  }catch(e){
    showMsg('Error: '+e.message,'error');
  }
}

// ═══════════════════════════════════════════════
// RENDER QUOTA TRACKERS
// ═══════════════════════════════════════════════
function renderQuota(trackers){
  const qs = document.getElementById('quotaSection');
  const qg = document.getElementById('quotaGrid');

  const items = Object.values(trackers);
  if(!items.length){ qs.style.display='none'; return; }
  qs.style.display='block';

  qg.innerHTML = items.map(q=>`
    <div class="quota-card">
      <div class="qc-head">
        <div class="qc-name">${esc(q.provider)}</div>
        <div class="qc-model">${esc(q.model_id)}</div>
      </div>
      <div class="quota-rows">

        ${q.rpm_limit ? `
        <div class="qrow">
          <div class="qrow-head">
            <span class="qrow-label">Requests / Minute</span>
            <span class="qrow-nums">
              <span class="used">${q.requests_this_min}</span>
              <span class="limit"> / ${q.rpm_limit}</span>
              &nbsp;·&nbsp;
              <span class="avail">${q.rpm_remaining} left</span>
            </span>
          </div>
          <div class="qbar">
            <div class="qfill ${q.rpm_pct>85?'danger':q.rpm_pct>65?'warn':''}"
                 style="width:${Math.min(q.rpm_pct,100)}%"></div>
          </div>
        </div>` : ''}

        ${q.rpd_limit ? `
        <div class="qrow">
          <div class="qrow-head">
            <span class="qrow-label">Requests / Day</span>
            <span class="qrow-nums">
              <span class="used">${q.requests_today}</span>
              <span class="limit"> / ${fmt(q.rpd_limit)}</span>
              &nbsp;·&nbsp;
              <span class="avail">${fmt(q.rpd_remaining)} left</span>
            </span>
          </div>
          <div class="qbar">
            <div class="qfill ${q.rpd_pct>85?'danger':q.rpd_pct>65?'warn':''}"
                 style="width:${Math.min(q.rpd_pct,100)}%"></div>
          </div>
        </div>` : ''}

        ${q.tpm_limit ? `
        <div class="qrow">
          <div class="qrow-head">
            <span class="qrow-label">Tokens / Minute</span>
            <span class="qrow-nums">
              <span class="used">${fmt(q.tokens_this_min)}</span>
              <span class="limit"> / ${fmt(q.tpm_limit)}</span>
              &nbsp;·&nbsp;
              <span class="avail">${fmt(q.tpm_remaining)} left</span>
            </span>
          </div>
          <div class="qbar">
            <div class="qfill ${q.tpm_pct>85?'danger':q.tpm_pct>65?'warn':''}"
                 style="width:${Math.min(q.tpm_pct,100)}%"></div>
          </div>
        </div>` : ''}

        ${q.tpd_limit ? `
        <div class="qrow">
          <div class="qrow-head">
            <span class="qrow-label">Tokens / Day</span>
            <span class="qrow-nums">
              <span class="used">${fmt(q.tokens_today)}</span>
              <span class="limit"> / ${fmt(q.tpd_limit)}</span>
              &nbsp;·&nbsp;
              <span class="avail">${fmt(q.tpd_remaining)} left</span>
            </span>
          </div>
          <div class="qbar">
            <div class="qfill ${q.tpd_pct>85?'danger':q.tpd_pct>65?'warn':''}"
                 style="width:${Math.min(q.tpd_pct,100)}%"></div>
          </div>
        </div>` : ''}

      </div>
    </div>
  `).join('');
}

// ═══════════════════════════════════════════════
// RENDER SYSTEM METRICS
// ═══════════════════════════════════════════════
function renderSysMetrics(sys,sess){
  document.getElementById('s-cpu').textContent  = sys.cpu_percent+'%';
  setBar('b-cpu',sys.cpu_percent);
  document.getElementById('s-mem').textContent  = sys.memory_percent+'%';
  document.getElementById('s-mem-s').textContent=
    `${sys.memory_used_mb}MB / ${sys.memory_total_mb}MB`;
  setBar('b-mem',sys.memory_percent);
  document.getElementById('s-disk').textContent = sys.disk_percent+'%';
  document.getElementById('s-disk-s').textContent=
    `${sys.disk_used_gb}GB / ${sys.disk_total_gb}GB`;
  setBar('b-disk',sys.disk_percent);
  document.getElementById('s-proc').textContent = sys.process_memory_mb+'MB';
  document.getElementById('s-proc-s').textContent=
    `${sys.thread_count} threads · ${sys.uptime_seconds}s up`;
  if(sess) updateSession(sess);
}
function updateSession(sess){
  document.getElementById('s-tok').textContent   = fmt(sess.total_tokens);
  document.getElementById('s-tok-s').textContent =
    `${sess.prompt_tokens}p + ${sess.completion_tokens}c`;
  document.getElementById('s-calls').textContent = sess.total_calls;
  document.getElementById('s-calls-s').textContent=
    `${sess.success_calls} ok / ${sess.failed_calls} fail`;
}

// ═══════════════════════════════════════════════
// RENDER AGENTS
// ═══════════════════════════════════════════════
function renderAgents(agents){
  const el=document.getElementById('agentsList');
  if(!agents.length){
    el.innerHTML='<p style="color:#555;text-align:center;padding:28px">No AI agents detected</p>';
    return;
  }
  el.innerHTML=agents.map(a=>{
    const m=a.metrics;
    const cls=a.active?'active-a':a.status==='auth_error'?'error-a':'';
    const badge=a.active
      ?'<span class="badge bok">🟢 Active</span>'
      :a.status==='auth_error'
        ?'<span class="badge berr">🔴 Auth Error</span>'
        :'<span class="badge bgry">⚪ Detected</span>';
    return `
    <div class="ac ${cls}">
      <div class="ah">
        <div>
          <div class="al">Agent File</div>
          <div style="font-family:monospace;color:#4facfe;font-size:.85em">${esc(a.file_path)}</div>
          <div style="color:#555;font-size:.72em;margin-top:2px">${esc(a.purpose)}</div>
          <div style="margin-top:5px">${badge}</div>
        </div>
        <div><div class="al">Provider</div><div class="av" style="color:#f093fb">${esc(a.provider)}</div></div>
        <div><div class="al">Model</div><div class="av">${esc(a.model)}</div></div>
        <div>
          <div class="al">Patterns</div>
          <div class="av">${a.patterns_found.length}</div>
          <div style="color:#555;font-size:.68em;margin-top:2px">
            ${a.patterns_found.slice(0,2).map(p=>`<code>${esc(p)}</code>`).join(' ')}
          </div>
        </div>
      </div>
      <div class="am">
        <div class="mm"><div class="ml">Calls</div>       <div class="mv">${m.total_calls}</div></div>
        <div class="mm"><div class="ml">Success</div>     <div class="mv" style="color:#38ef7d">${m.success_calls}</div></div>
        <div class="mm"><div class="ml">Failed</div>      <div class="mv" style="color:#ff5252">${m.failed_calls}</div></div>
        <div class="mm"><div class="ml">Success%</div>    <div class="mv">${m.success_rate}%</div></div>
        <div class="mm"><div class="ml">Prompt T</div>    <div class="mv">${fmt(m.prompt_tokens)}</div></div>
        <div class="mm"><div class="ml">Complete T</div>  <div class="mv">${fmt(m.completion_tokens)}</div></div>
        <div class="mm"><div class="ml">Total T</div>     <div class="mv">${fmt(m.total_tokens)}</div></div>
        <div class="mm"><div class="ml">Avg Lat</div>     <div class="mv">${m.avg_latency_ms}ms</div></div>
        <div class="mm"><div class="ml">Min Lat</div>     <div class="mv">${m.min_latency_ms}ms</div></div>
        <div class="mm"><div class="ml">Max Lat</div>     <div class="mv">${m.max_latency_ms}ms</div></div>
        <div class="mm"><div class="ml">Rate Lim</div>    <div class="mv" style="color:#ffd200">${m.rate_limit_hits}</div></div>
        <div class="mm"><div class="ml">Auth Fail</div>   <div class="mv" style="color:#ff5252">${m.auth_failures}</div></div>
      </div>
      ${m.last_error?`<div style="margin-top:8px;color:#ff5252;font-size:.74em">⚠ ${esc(m.last_error)}</div>`:''}
    </div>`;
  }).join('');
}

// ═══════════════════════════════════════════════
// RENDER FILES
// ═══════════════════════════════════════════════
function renderFiles(files){
  document.getElementById('fileCount').textContent=`${files.length} files`;
  document.getElementById('filesList').innerHTML=files.map(f=>`
    <div class="fr">
      <div style="font-family:monospace;color:#4facfe;font-size:.8em">${esc(f.path)}</div>
      <div><span class="badge bgry">${esc(f.extension||'?')}</span></div>
      <div style="color:#777">${f.lines}</div>
      <div style="color:#777">${f.size_kb}KB</div>
      <div>${f.is_ai_agent
        ?f.ai_providers.map(p=>`<span class="badge bok" style="margin:1px">${esc(p)}</span>`).join('')
        :'<span style="color:#333">—</span>'}</div>
    </div>
  `).join('');
}
function filterFiles(){
  const q=document.getElementById('fileSearch').value.toLowerCase();
  const ai=document.getElementById('aiOnly').checked;
  renderFiles(allFiles.filter(f=>(!ai||f.is_ai_agent)&&(!q||f.path.toLowerCase().includes(q))));
}

// ═══════════════════════════════════════════════
// RENDER REQUESTS
// ═══════════════════════════════════════════════
function renderRequests(reqs){
  if(!reqs.length) return;
  const tot=reqs.length;
  const ok =reqs.filter(r=>r.status==='success').length;
  const tok=reqs.reduce((s,r)=>s+r.total_tokens,0);
  const pt =reqs.reduce((s,r)=>s+r.prompt_tokens,0);
  const ct =reqs.reduce((s,r)=>s+r.completion_tokens,0);
  const avg=tot?Math.round(reqs.reduce((s,r)=>s+r.latency_ms,0)/tot):0;

  const sb=document.getElementById('reqSummary');
  sb.style.display='flex';
  document.getElementById('rq-tot').textContent  = tot;
  document.getElementById('rq-ok').textContent   = ok;
  document.getElementById('rq-fail').textContent = tot-ok;
  document.getElementById('rq-tok').textContent  = fmt(tok);
  document.getElementById('rq-pt').textContent   = fmt(pt);
  document.getElementById('rq-ct').textContent   = fmt(ct);
  document.getElementById('rq-lat').textContent  = avg+'ms';

  document.getElementById('reqTable').innerHTML=reqs.map(r=>`
    <tr>
      <td class="mono">${new Date(r.timestamp).toLocaleTimeString()}</td>
      <td>${esc(r.provider)}</td>
      <td class="mono" style="font-size:.77em">${esc(r.model)}</td>
      <td>${r.status==='success'
        ?'<span class="badge bok">✅</span>'
        :'<span class="badge berr">❌</span>'}</td>
      <td>${r.prompt_tokens}</td>
      <td>${r.completion_tokens}</td>
      <td><strong>${r.total_tokens}</strong></td>
      <td>${r.latency_ms}ms</td>
      <td style="color:#ff5252;font-size:.74em">${esc(r.error||'')}</td>
    </tr>
  `).join('');
}

function prependRow(r){
  document.getElementById('reqSummary').style.display='flex';
  const tb=document.getElementById('reqTable');
  const row=document.createElement('tr');
  row.innerHTML=`
    <td class="mono">${new Date(r.timestamp).toLocaleTimeString()}</td>
    <td>${esc(r.provider)}</td>
    <td class="mono" style="font-size:.77em">${esc(r.model)}</td>
    <td>${r.status==='success'
      ?'<span class="badge bok">✅</span>'
      :'<span class="badge berr">❌</span>'}</td>
    <td>${r.prompt_tokens}</td>
    <td>${r.completion_tokens}</td>
    <td><strong>${r.total_tokens}</strong></td>
    <td>${r.latency_ms}ms</td>
    <td style="color:#ff5252;font-size:.74em">${esc(r.error||'')}</td>`;
  tb.insertBefore(row,tb.firstChild);
}

// ═══════════════════════════════════════════════
// RENDER PROVIDER SUMMARY
// ═══════════════════════════════════════════════
function renderProvSummary(provs){
  const el=document.getElementById('provList');
  const items=Object.values(provs);
  if(!items.length){
    el.innerHTML='<p style="color:#555;text-align:center;padding:28px">Scan or test first</p>';
    return;
  }
  el.innerHTML=items.map(p=>`
    <div class="ac">
      <div class="ah">
        <div>
          <div style="color:#f093fb;font-weight:700;font-size:1em">${esc(p.name)}</div>
          <div style="color:#444;font-size:.72em;margin-top:3px">
            ${(p.files||[]).slice(0,3).map(f=>
              `<span style="font-family:monospace;color:#4facfe">${esc(f)}</span>`
            ).join(' · ')}
          </div>
        </div>
        <div>
          <div class="al">Agents</div>
          <div style="font-size:1.4em;font-weight:800;color:#667eea">${p.agent_count}</div>
          <div style="color:#38ef7d;font-size:.76em">${p.active_count} active</div>
        </div>
        <div>
          <div class="al">Total Tokens</div>
          <div style="font-size:1.2em;font-weight:700;color:#f093fb">${fmt(p.total_tokens)}</div>
        </div>
        <div>
          <div class="al">Calls / Avg Lat</div>
          <div style="font-weight:700">${fmt(p.total_calls)}</div>
          <div style="color:#4facfe;font-size:.8em">${p.avg_latency_ms}ms</div>
        </div>
      </div>
    </div>
  `).join('');
}

// ═══════════════════════════════════════════════
// TABS
// ═══════════════════════════════════════════════
function tab(name,btn){
  document.querySelectorAll('.tc').forEach(t=>t.classList.remove('active'));
  document.querySelectorAll('.tb').forEach(b=>b.classList.remove('active'));
  document.getElementById(name).classList.add('active');
  btn.classList.add('active');
  if(name==='requests') loadReqs();
  if(name==='providers') loadProvs();
}
async function loadReqs(){
  try{const res=await fetch('/api/requests?limit=50');
      const d=await res.json();renderRequests(d.requests||[]);}catch(e){}
}
async function loadProvs(){
  try{const res=await fetch('/api/dashboard');
      const d=await res.json();renderProvSummary(d.providers||{});}catch(e){}
}

// ═══════════════════════════════════════════════
// REFRESH ALL
// ═══════════════════════════════════════════════
async function refreshAll(){
  try{
    const res=await fetch('/api/dashboard');
    const d=await res.json();
    renderSysMetrics(d.system_metrics,d.session_stats);
    if(d.agents.length)      renderAgents(d.agents);
    if(d.project_files.length){allFiles=d.project_files;renderFiles(allFiles);}
    renderRequests(d.request_history);
    renderProvSummary(d.providers);
    if(d.quota_trackers&&Object.keys(d.quota_trackers).length)
      renderQuota(d.quota_trackers);
    document.getElementById('sysGrid').style.display='grid';
    document.getElementById('mainWrap').style.display='block';
    showMsg('🔄 Refreshed','success');
  }catch(e){showMsg('Error: '+e.message,'error');}
}

// ═══════════════════════════════════════════════
// DOWNLOAD REPORT
// ═══════════════════════════════════════════════
async function downloadReport(){
  try{
    const res=await fetch('/api/report/download');
    const blob=await res.blob();
    const url=URL.createObjectURL(blob);
    const a=document.createElement('a');
    a.href=url;a.download=`agent_report_${Date.now()}.json`;
    document.body.appendChild(a);a.click();
    URL.revokeObjectURL(url);document.body.removeChild(a);
  }catch(e){showMsg('Download error','error');}
}

// ═══════════════════════════════════════════════
// AUTO REFRESH EVERY 10s
// ═══════════════════════════════════════════════
setInterval(async()=>{
  try{
    const res=await fetch('/api/dashboard');
    const d=await res.json();
    renderSysMetrics(d.system_metrics,d.session_stats);
    if(d.quota_trackers&&Object.keys(d.quota_trackers).length)
      renderQuota(d.quota_trackers);
  }catch(e){}
},10000);

// INIT
loadProviders();
</script>
</body>
</html>
"""

# ============================================================================
# ROUTES
# ============================================================================

@application.get("/")
def index():
    return render_template_string(HTML_TEMPLATE)

@application.get("/api/providers/models")
def api_providers_models():
    return jsonify(scanner.get_providers_and_models())

@application.post("/api/scan/project")
def api_scan_project():
    result = scanner.scan_project()
    return jsonify(result), 200 if result.get("success") else 400

@application.post("/api/agent/test")
def api_agent_test():
    data     = request.get_json() or {}
    provider = data.get("provider", "gemini")
    model    = data.get("model",    "gemini-2.0-flash")
    api_key  = data.get("api_key",  "")
    prompt   = data.get("prompt",   "Say OK in one word.")
    result   = scanner.test_agent(provider, model, api_key, prompt)
    return jsonify(result), 200 if result.get("success") else 400

@application.get("/api/dashboard")
def api_dashboard():
    return jsonify(scanner.get_dashboard_data())

@application.get("/api/agents")
def api_agents():
    return jsonify({
        "agents": [scanner._agent_dict(a) for a in scanner.agents],
        "count":  len(scanner.agents),
    })

@application.get("/api/requests")
def api_requests():
    limit = request.args.get("limit", 50, type=int)
    reqs  = [scanner._req_dict(r)
             for r in list(scanner.request_history)[:limit]]
    return jsonify({"requests": reqs, "count": len(reqs)})

@application.get("/api/providers")
def api_providers():
    return jsonify({
        "providers": scanner._provider_summary(),
        "available": scanner.key_detector.get_available_providers(),
    })

@application.get("/api/quota")
def api_quota():
    with scanner._lock:
        return jsonify({
            "quota_trackers": {
                k: v.to_dict()
                for k, v in scanner.quota_trackers.items()
            },
            "timestamp": datetime.now().isoformat(),
        })

@application.get("/api/status")
def api_status():
    return jsonify({
        "status":        "running",
        "agents_count":  len(scanner.agents),
        "active_agents": sum(1 for a in scanner.agents if a.active),
        "session_stats": scanner._session_stats(),
        "timestamp":     datetime.now().isoformat(),
    })

@application.get("/api/report/download")
def api_report_download():
    return send_file(
        io.BytesIO(scanner.save_report()),
        mimetype="application/json",
        as_attachment=True,
        download_name=f"agent_report_{datetime.now():%Y%m%d_%H%M%S}.json",
    )

@application.get("/health")
def health():
    return "Healthy", 200

@application.errorhandler(404)
def not_found(e):
    return jsonify({"error": "Not found"}), 404

@application.errorhandler(500)
def server_error(e):
    return jsonify({"error": "Internal server error"}), 500

if __name__ == "__main__":
    print("\n"+"="*60)
    print("  🤖  AI AGENT MONITOR — FREE MODELS + QUOTA TRACKING")
    print("="*60)
    print("  URL   : http://localhost:5000")
    print("  Health: http://localhost:5000/health")
    print("="*60+"\n")
    application.run(host="0.0.0.0", port=5000, debug=False, use_reloader=False)
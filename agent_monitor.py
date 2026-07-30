#!/usr/bin/env python3
"""
AI Repository Audit Script
Complete static analysis of AI repositories with detailed reporting.
"""

import os
import sys
import re
import json
import csv
import ast
import hashlib
import argparse
import datetime
import mimetypes
from pathlib import Path
from collections import defaultdict, Counter
from dataclasses import dataclass, field, asdict
from typing import Optional

# ─────────────────────────────────────────────
# Optional dependencies with graceful fallback
# ─────────────────────────────────────────────
try:
    import openpyxl
    from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
    HAS_OPENPYXL = True
except ImportError:
    HAS_OPENPYXL = False

try:
    import markdown
    HAS_MARKDOWN = True
except ImportError:
    HAS_MARKDOWN = False


# ══════════════════════════════════════════════════════════════════════════════
# CONSTANTS AND CONFIGURATION
# ══════════════════════════════════════════════════════════════════════════════

IGNORED_DIRS = {
    ".git", ".terraform", "node_modules", "venv", "__pycache__",
    "dist", "build", "target", "coverage", ".cache", ".idea", ".vscode",
    ".env", ".eggs", "*.egg-info", ".tox", ".pytest_cache", ".mypy_cache",
    ".ruff_cache", "vendor", "bower_components", ".next", ".nuxt", ".svelte-kit",
}

EXTENSION_LANGUAGE_MAP = {
    ".py": "Python", ".pyw": "Python", ".pyi": "Python",
    ".java": "Java", ".kt": "Kotlin", ".kts": "Kotlin", ".scala": "Scala",
    ".cs": "C#", ".vb": "VB.NET", ".fs": "F#",
    ".js": "JavaScript", ".mjs": "JavaScript", ".cjs": "JavaScript",
    ".ts": "TypeScript", ".tsx": "TypeScript", ".jsx": "JavaScript",
    ".go": "Go", ".rs": "Rust", ".c": "C", ".cpp": "C++", ".cc": "C++",
    ".h": "C/C++ Header", ".hpp": "C++ Header", ".cxx": "C++",
    ".sh": "Shell", ".bash": "Shell", ".zsh": "Shell", ".fish": "Shell",
    ".ps1": "PowerShell", ".psm1": "PowerShell", ".psd1": "PowerShell",
    ".yaml": "YAML", ".yml": "YAML",
    ".json": "JSON", ".jsonc": "JSON", ".json5": "JSON",
    ".toml": "TOML", ".ini": "INI", ".cfg": "Config", ".conf": "Config",
    ".xml": "XML", ".xsd": "XML", ".xsl": "XML",
    ".html": "HTML", ".htm": "HTML", ".xhtml": "HTML",
    ".css": "CSS", ".scss": "SCSS", ".sass": "SASS", ".less": "LESS",
    ".sql": "SQL", ".ddl": "SQL", ".dml": "SQL",
    ".md": "Markdown", ".mdx": "Markdown", ".rst": "reStructuredText",
    ".txt": "Text", ".log": "Log",
    ".dockerfile": "Dockerfile", ".Dockerfile": "Dockerfile",
    ".tf": "Terraform", ".tfvars": "Terraform", ".hcl": "HCL",
    ".env": "Environment", ".env.example": "Environment",
    ".proto": "Protobuf", ".graphql": "GraphQL", ".gql": "GraphQL",
    ".r": "R", ".R": "R", ".jl": "Julia", ".lua": "Lua", ".rb": "Ruby",
    ".php": "PHP", ".swift": "Swift", ".dart": "Dart", ".ex": "Elixir",
    ".exs": "Elixir", ".clj": "Clojure", ".cljs": "ClojureScript",
    ".gradle": "Gradle", ".groovy": "Groovy",
    ".ipynb": "Jupyter Notebook", ".csv": "CSV", ".tsv": "TSV",
    ".lock": "Lock File", ".sum": "Checksum",
    ".pem": "Certificate", ".crt": "Certificate", ".key": "Key File",
    "Dockerfile": "Dockerfile", "Makefile": "Makefile",
    "Jenkinsfile": "Jenkinsfile", ".gitignore": "Git Config",
    "requirements.txt": "Requirements", "Pipfile": "Requirements",
    "poetry.lock": "Lock File", "package.json": "NPM Config",
    "package-lock.json": "Lock File", "yarn.lock": "Lock File",
    "go.mod": "Go Module", "go.sum": "Go Checksum",
    "Cargo.toml": "Rust Config", "Cargo.lock": "Lock File",
    "pyproject.toml": "Python Config", "setup.py": "Python Config",
    "setup.cfg": "Python Config",
}

CATEGORY_PATTERNS = {
    "Test": [
        r"test_", r"_test\.", r"spec\.", r"_spec\.", r"\.test\.", r"\.spec\.",
        r"/tests?/", r"/specs?/", r"__tests__", r"testing",
    ],
    "Configuration": [
        r"config", r"settings", r"\.env", r"\.yaml$", r"\.yml$",
        r"\.toml$", r"\.ini$", r"\.cfg$", r"\.conf$",
    ],
    "Documentation": [
        r"\.md$", r"\.rst$", r"readme", r"changelog", r"license",
        r"contributing", r"docs?/", r"documentation",
    ],
    "Infrastructure": [
        r"\.tf$", r"\.hcl$", r"dockerfile", r"docker-compose",
        r"kubernetes", r"k8s", r"helm", r"\.yaml$.*deploy",
        r"terraform", r"ansible", r"puppet", r"chef",
    ],
    "AI": [
        r"agent", r"llm", r"prompt", r"model", r"inference", r"embedding",
        r"vector", r"rag", r"chain", r"langchain", r"openai", r"anthropic",
        r"gemini", r"gpt", r"claude", r"llama", r"mistral", r"groq",
        r"huggingface", r"transformer", r"bert", r"gpt", r"neural",
        r"semantic_kernel", r"autogen", r"crewai", r"llamaindex",
    ],
    "Frontend": [
        r"component", r"view", r"page", r"layout", r"ui", r"frontend",
        r"\.jsx$", r"\.tsx$", r"\.vue$", r"\.svelte$",
    ],
    "Backend": [
        r"server", r"api", r"route", r"controller", r"service",
        r"handler", r"middleware", r"endpoint",
    ],
    "Database": [
        r"database", r"db", r"model", r"schema", r"migration",
        r"repository", r"dao", r"orm", r"\.sql$",
    ],
    "Source": [],  # fallback
}

# ─── AI Provider Detection Patterns ───────────────────────────────────────────
AI_PROVIDER_PATTERNS = {
    "OpenAI": {
        "imports": [r"import openai", r"from openai", r"openai\."],
        "env_vars": [r"OPENAI_API_KEY", r"OPENAI_ORG_ID", r"OPENAI_BASE_URL"],
        "endpoints": [r"api\.openai\.com", r"openai\.azure\.com"],
        "sdk": "openai",
    },
    "Azure OpenAI": {
        "imports": [r"AzureOpenAI", r"azure\.cognitiveservices", r"openai.*azure"],
        "env_vars": [r"AZURE_OPENAI_KEY", r"AZURE_OPENAI_ENDPOINT", r"AZURE_OPENAI_API_KEY",
                     r"AZURE_OPENAI_DEPLOYMENT", r"AZURE_OPENAI_API_VERSION"],
        "endpoints": [r"\.openai\.azure\.com", r"azure.*openai"],
        "sdk": "openai (Azure)",
    },
    "Anthropic": {
        "imports": [r"import anthropic", r"from anthropic", r"anthropic\."],
        "env_vars": [r"ANTHROPIC_API_KEY", r"CLAUDE_API_KEY"],
        "endpoints": [r"api\.anthropic\.com"],
        "sdk": "anthropic",
    },
    "Google Gemini": {
        "imports": [r"import google\.generativeai", r"from google\.generativeai",
                    r"google\.generativeai", r"import vertexai", r"from vertexai",
                    r"genai\.", r"GenerativeModel"],
        "env_vars": [r"GEMINI_API_KEY", r"GOOGLE_API_KEY", r"GOOGLE_APPLICATION_CREDENTIALS",
                     r"VERTEX_AI_PROJECT"],
        "endpoints": [r"generativelanguage\.googleapis\.com", r"aiplatform\.googleapis\.com"],
        "sdk": "google-generativeai / vertexai",
    },
    "AWS Bedrock": {
        "imports": [r"bedrock", r"boto3.*bedrock", r"BedrockRuntime"],
        "env_vars": [r"AWS_ACCESS_KEY_ID", r"AWS_SECRET_ACCESS_KEY", r"AWS_BEDROCK",
                     r"AWS_DEFAULT_REGION", r"AWS_REGION"],
        "endpoints": [r"bedrock\.amazonaws\.com", r"bedrock-runtime"],
        "sdk": "boto3",
    },
    "Groq": {
        "imports": [r"import groq", r"from groq", r"groq\."],
        "env_vars": [r"GROQ_API_KEY"],
        "endpoints": [r"api\.groq\.com"],
        "sdk": "groq",
    },
    "Cohere": {
        "imports": [r"import cohere", r"from cohere", r"cohere\."],
        "env_vars": [r"COHERE_API_KEY", r"CO_API_KEY"],
        "endpoints": [r"api\.cohere\.ai", r"api\.cohere\.com"],
        "sdk": "cohere",
    },
    "Mistral": {
        "imports": [r"import mistralai", r"from mistralai", r"MistralClient",
                    r"mistral_client"],
        "env_vars": [r"MISTRAL_API_KEY"],
        "endpoints": [r"api\.mistral\.ai"],
        "sdk": "mistralai",
    },
    "Ollama": {
        "imports": [r"import ollama", r"from ollama", r"ollama\."],
        "env_vars": [r"OLLAMA_HOST", r"OLLAMA_BASE_URL"],
        "endpoints": [r"localhost:11434", r"ollama"],
        "sdk": "ollama",
    },
    "HuggingFace": {
        "imports": [r"from transformers", r"import transformers", r"huggingface_hub",
                    r"from huggingface_hub", r"pipeline\(", r"AutoModel", r"AutoTokenizer"],
        "env_vars": [r"HUGGINGFACE_API_KEY", r"HF_API_KEY", r"HF_TOKEN",
                     r"HUGGINGFACEHUB_API_TOKEN"],
        "endpoints": [r"api-inference\.huggingface\.co", r"huggingface\.co"],
        "sdk": "transformers / huggingface_hub",
    },
    "OpenRouter": {
        "imports": [r"openrouter", r"openrouter\.ai"],
        "env_vars": [r"OPENROUTER_API_KEY"],
        "endpoints": [r"openrouter\.ai/api"],
        "sdk": "openai (OpenRouter)",
    },
    "DeepSeek": {
        "imports": [r"deepseek"],
        "env_vars": [r"DEEPSEEK_API_KEY"],
        "endpoints": [r"api\.deepseek\.com"],
        "sdk": "openai (DeepSeek)",
    },
    "Perplexity": {
        "imports": [r"perplexity"],
        "env_vars": [r"PERPLEXITY_API_KEY", r"PPLX_API_KEY"],
        "endpoints": [r"api\.perplexity\.ai"],
        "sdk": "openai (Perplexity)",
    },
    "Meta Llama": {
        "imports": [r"llama", r"LlamaForCausalLM", r"meta.*llama"],
        "env_vars": [r"LLAMA_API_KEY", r"META_API_KEY", r"LLAMA_CLOUD_API_KEY"],
        "endpoints": [r"llama-api", r"llama\.meta\.com"],
        "sdk": "llama / transformers",
    },
    "LiteLLM": {
        "imports": [r"import litellm", r"from litellm", r"litellm\."],
        "env_vars": [r"LITELLM_API_KEY", r"LITELLM_PROXY"],
        "endpoints": [r"litellm"],
        "sdk": "litellm",
    },
}

# ─── AI Model Detection Patterns ──────────────────────────────────────────────
AI_MODEL_PATTERNS = [
    # OpenAI GPT
    r"gpt-?4\.?1(?:-mini|-nano|-preview)?",
    r"gpt-?4o(?:-mini|-preview|-audio|-realtime)?",
    r"gpt-?4(?:-turbo|-turbo-preview|-vision|-32k|-0125|-1106|-0613|-0314)?",
    r"gpt-?3\.?5(?:-turbo(?:-16k|-instruct|-0125|-1106|-0613)?)?",
    r"gpt-?5",
    r"\bo3(?:-mini|-preview)?\b",
    r"\bo4(?:-mini)?\b",
    r"\bo1(?:-mini|-preview)?\b",
    r"\bo2\b",
    r"text-davinci-\d+",
    r"text-embedding-(?:ada|3)-(?:small|large|\d+)",
    r"whisper-\d+",
    r"dall-e-\d+",
    r"tts-\d+",
    # Anthropic Claude
    r"claude-?3(?:-\d+)?(?:-opus|-sonnet|-haiku|-instant)?(?:-\d+)?(?:-\d+)?",
    r"claude-?2(?:\.\d+)?",
    r"claude-instant-\d+",
    r"claude-?3\.?5(?:-sonnet|-haiku)?",
    r"claude-?4(?:-opus|-sonnet)?",
    # Google
    r"gemini-?(?:pro|ultra|flash|nano)?(?:-\d+\.\d+)?(?:-latest|-preview)?",
    r"gemini-?1\.?5(?:-pro|-flash)?",
    r"gemini-?2\.?0(?:-flash)?",
    r"palm-?2",
    r"bard",
    r"text-bison",
    r"chat-bison",
    # Meta Llama
    r"llama-?3(?:\.\d+)?(?:-\d+b|-\d+B)?(?:-instruct|-chat|-base)?",
    r"llama-?2(?:-\d+b|-\d+B)?(?:-chat|-instruct)?",
    r"llama-?3\.?1(?:-\d+[bB])?",
    r"llama-?3\.?2(?:-\d+[bB])?",
    r"codellama",
    # Mistral
    r"mistral-(?:7b|large|medium|small|tiny|nemo|next|embed)(?:-instruct)?(?:-\d+)?",
    r"mixtral-?(?:8x7b|8x22b)?(?:-instruct)?",
    r"mistral-\d+",
    r"open-mistral",
    r"open-mixtral",
    # DeepSeek
    r"deepseek-(?:coder|chat|r1|v\d+|v3)(?:-\d+[bB])?(?:-instruct|-base)?",
    # Cohere
    r"command-?(?:r|r-plus|light|nightly|xlarge)?(?:-\d+)?",
    r"embed-(?:english|multilingual)(?:-v\d+)?",
    # Other
    r"phi-?[234](?:-mini|-medium|-vision)?",
    r"phi-?3(?:\.\d+)?(?:-mini|-medium|-vision|-small)?",
    r"qwen(?:\d+(?:\.\d+)?)?(?:-\d+[bB])?(?:-instruct|-chat|-plus|-turbo|-max)?",
    r"yi-(?:6b|9b|34b|large)(?:-chat|-200k)?",
    r"falcon-?(?:7b|40b|180b)?(?:-instruct)?",
    r"vicuna-?(?:7b|13b|33b)?(?:-v\d+)?",
    r"solar-?(?:10\.7b|pro)?(?:-instruct)?",
    r"nous-hermes",
    r"openchat-\d+",
    r"starling-lm",
    r"orca-\d+",
    r"wizardlm",
    r"zephyr-\d+[bB]",
    r"neural-chat",
    r"stablelm",
    r"dolly-v\d+",
    r"mpt-\d+[bB]",
    r"bloom(?:-\d+[bB])?",
    r"opt-\d+[bBmM]",
    r"flan-(?:t5|ul2|alpaca)(?:-(?:small|base|large|xl|xxl))?",
    r"t5-(?:small|base|large|xl|xxl|3b|11b)",
    r"bert-(?:base|large)(?:-uncased|-cased|-multilingual)?",
    r"roberta-(?:base|large)",
    r"distilbert",
    r"albert-(?:base|large|xlarge|xxlarge)-v\d+",
    r"gpt-?j-?6[bB]",
    r"gpt-?neo(?:-(?:125m|1\.3b|2\.7b|6\.7b|20b))?",
    r"gpt-?neox-?20[bB]",
    r"codegen-?\d+[bBmM]",
    r"starcoder(?:-\d+[bB]|-base)?",
    r"codestral",
    r"granite-\d+[bB]",
    r"jamba",
    r"dbrx",
    r"mixtral",
    r"aya-\d+[bB]",
    r"c4ai",
    r"solar",
]

# ─── AI SDK / Framework Patterns ──────────────────────────────────────────────
AI_SDK_PATTERNS = {
    "LangChain": [
        r"from langchain", r"import langchain", r"langchain\.",
        r"LLMChain", r"ConversationChain", r"AgentExecutor",
        r"ChatOpenAI", r"ChatAnthropic", r"ChatGoogleGenerativeAI",
        r"PromptTemplate", r"ChatPromptTemplate", r"LangChain",
    ],
    "LangGraph": [
        r"from langgraph", r"import langgraph", r"langgraph\.",
        r"StateGraph", r"MessageGraph", r"CompiledGraph",
    ],
    "Semantic Kernel": [
        r"semantic_kernel", r"import semantic_kernel",
        r"from semantic_kernel", r"SemanticKernel", r"Kernel\(",
        r"sk\.Kernel", r"KernelPlugin", r"KernelFunction",
    ],
    "AutoGen": [
        r"import autogen", r"from autogen", r"autogen\.",
        r"AssistantAgent", r"UserProxyAgent", r"GroupChat",
        r"ConversableAgent", r"AutoGen",
    ],
    "CrewAI": [
        r"import crewai", r"from crewai", r"crewai\.",
        r"Crew\(", r"Agent\(.*role", r"Task\(.*description",
        r"CrewAI",
    ],
    "LlamaIndex": [
        r"from llama_index", r"import llama_index", r"llama_index\.",
        r"VectorStoreIndex", r"SimpleDirectoryReader", r"QueryEngine",
        r"LlamaIndex", r"GPTSimpleVectorIndex", r"GPTListIndex",
        r"from llama-index",
    ],
    "Haystack": [
        r"import haystack", r"from haystack", r"haystack\.",
        r"Pipeline\(", r"DocumentStore", r"Retriever\(",
    ],
    "DSPy": [
        r"import dspy", r"from dspy", r"dspy\.",
        r"dspy\.Predict", r"dspy\.ChainOfThought", r"dspy\.Module",
    ],
    "Transformers": [
        r"from transformers", r"import transformers",
        r"AutoModel", r"AutoTokenizer", r"pipeline\(",
        r"PreTrainedModel", r"BertModel", r"GPT2Model",
    ],
    "LiteLLM": [
        r"import litellm", r"from litellm", r"litellm\.",
        r"litellm\.completion", r"litellm\.acompletion",
    ],
    "Instructor": [
        r"import instructor", r"from instructor", r"instructor\.",
        r"instructor\.patch", r"instructor\.from_openai",
    ],
    "Ollama SDK": [
        r"import ollama", r"from ollama", r"ollama\.chat",
        r"ollama\.generate", r"ollama\.Client",
    ],
    "OpenAI SDK": [
        r"from openai import", r"import openai",
        r"openai\.ChatCompletion", r"openai\.Completion",
        r"client\.chat\.completions", r"AsyncOpenAI", r"OpenAI\(",
    ],
    "Anthropic SDK": [
        r"from anthropic import", r"import anthropic",
        r"anthropic\.Anthropic", r"client\.messages\.create",
        r"AsyncAnthropic",
    ],
    "Google AI SDK": [
        r"import google\.generativeai", r"from google\.generativeai",
        r"genai\.GenerativeModel", r"vertexai\.init",
    ],
    "Pydantic AI": [
        r"from pydantic_ai", r"import pydantic_ai", r"pydantic_ai\.",
        r"pydantic-ai",
    ],
}

# ─── Agent Detection Patterns ─────────────────────────────────────────────────
AGENT_PATTERNS = [
    r"class\s+\w*[Aa]gent\w*",
    r"class\s+\w*[Bb]ot\w*",
    r"class\s+\w*[Aa]ssistant\w*",
    r"class\s+\w*[Ww]orkflow\w*",
    r"class\s+\w*[Oo]rchestrat\w*",
    r"class\s+\w*[Pp]lanner\w*",
    r"class\s+\w*[Ee]xecutor\w*",
    r"AgentExecutor",
    r"AssistantAgent",
    r"UserProxyAgent",
    r"ConversableAgent",
    r"Crew\s*\(",
    r"StateGraph\s*\(",
    r"MessageGraph\s*\(",
    r"agent_executor",
    r"create_agent",
    r"build_agent",
    r"initialize_agent",
    r"run_agent",
    r"agent\.run\s*\(",
    r"agent\.invoke\s*\(",
    r"agent\.execute\s*\(",
    r"agent\.chat\s*\(",
    r"chat_completion",
    r"completion\.create",
    r"messages\.create",
    r"generate_content",
    r"\.invoke\s*\(",
    r"chain\.run\s*\(",
    r"chain\.invoke\s*\(",
    r"ReActAgent",
    r"OpenAIFunctionsAgent",
    r"StructuredChatAgent",
    r"ZeroShotAgent",
    r"Tool\s*\(",
    r"@tool\b",
    r"function_call",
    r"tool_calls",
]

# ─── Prompt Detection Patterns ────────────────────────────────────────────────
PROMPT_PATTERNS = [
    r'system_prompt\s*=',
    r'user_prompt\s*=',
    r'system_message\s*=',
    r'prompt_template\s*=',
    r'PromptTemplate\s*\(',
    r'ChatPromptTemplate',
    r'SystemMessage\s*\(',
    r'HumanMessage\s*\(',
    r'AIMessage\s*\(',
    r'"role"\s*:\s*"system"',
    r'"role"\s*:\s*"user"',
    r'"role"\s*:\s*"assistant"',
    r"role.*system",
    r'SYSTEM_PROMPT',
    r'USER_PROMPT',
    r'PROMPT\s*=',
    r'prompt\s*=\s*[f\'"]',
    r'prompt\s*=\s*f"""',
    r'prompt\s*=\s*"""',
    r'instruction\s*=',
    r'system_instruction',
    r'developer_message',
]

# ─── API Key / Env Var Patterns ───────────────────────────────────────────────
API_KEY_PATTERNS = {
    "OPENAI_API_KEY": "OpenAI",
    "OPENAI_ORG_ID": "OpenAI",
    "OPENAI_BASE_URL": "OpenAI",
    "AZURE_OPENAI_KEY": "Azure OpenAI",
    "AZURE_OPENAI_API_KEY": "Azure OpenAI",
    "AZURE_OPENAI_ENDPOINT": "Azure OpenAI",
    "AZURE_OPENAI_DEPLOYMENT": "Azure OpenAI",
    "AZURE_OPENAI_API_VERSION": "Azure OpenAI",
    "ANTHROPIC_API_KEY": "Anthropic",
    "CLAUDE_API_KEY": "Anthropic",
    "GEMINI_API_KEY": "Google Gemini",
    "GOOGLE_API_KEY": "Google",
    "GOOGLE_APPLICATION_CREDENTIALS": "Google",
    "VERTEX_AI_PROJECT": "Google Vertex AI",
    "GROQ_API_KEY": "Groq",
    "COHERE_API_KEY": "Cohere",
    "CO_API_KEY": "Cohere",
    "MISTRAL_API_KEY": "Mistral",
    "HUGGINGFACE_API_KEY": "HuggingFace",
    "HF_API_KEY": "HuggingFace",
    "HF_TOKEN": "HuggingFace",
    "HUGGINGFACEHUB_API_TOKEN": "HuggingFace",
    "AWS_ACCESS_KEY_ID": "AWS Bedrock",
    "AWS_SECRET_ACCESS_KEY": "AWS",
    "AWS_DEFAULT_REGION": "AWS",
    "AWS_REGION": "AWS",
    "BEDROCK_REGION": "AWS Bedrock",
    "OPENROUTER_API_KEY": "OpenRouter",
    "DEEPSEEK_API_KEY": "DeepSeek",
    "PERPLEXITY_API_KEY": "Perplexity",
    "PPLX_API_KEY": "Perplexity",
    "LLAMA_API_KEY": "Meta Llama",
    "LLAMA_CLOUD_API_KEY": "LlamaIndex Cloud",
    "META_API_KEY": "Meta",
    "OLLAMA_HOST": "Ollama",
    "OLLAMA_BASE_URL": "Ollama",
    "LITELLM_API_KEY": "LiteLLM",
    "TOGETHER_API_KEY": "Together AI",
    "REPLICATE_API_TOKEN": "Replicate",
    "VOYAGE_API_KEY": "Voyage AI",
    "PINECONE_API_KEY": "Pinecone",
    "WEAVIATE_API_KEY": "Weaviate",
    "QDRANT_API_KEY": "Qdrant",
    "SERPAPI_API_KEY": "SerpAPI",
    "SERPER_API_KEY": "Serper",
    "TAVILY_API_KEY": "Tavily",
    "BRAVE_API_KEY": "Brave Search",
    "EXA_API_KEY": "Exa",
    "WOLFRAM_ALPHA_APPID": "Wolfram Alpha",
    "REDIS_URL": "Redis",
    "POSTGRES_URL": "PostgreSQL",
    "DATABASE_URL": "Database",
    "MONGODB_URI": "MongoDB",
}

# ─── Token Config Patterns ────────────────────────────────────────────────────
TOKEN_PATTERNS = {
    "max_tokens": r"max_tokens\s*=\s*(\d+)",
    "temperature": r"temperature\s*=\s*([\d.]+)",
    "top_p": r"top_p\s*=\s*([\d.]+)",
    "max_completion_tokens": r"max_completion_tokens\s*=\s*(\d+)",
    "max_output_tokens": r"max_output_tokens\s*=\s*(\d+)",
    "n": r'["\']?n["\']?\s*[:=]\s*(\d+)',
    "context_window": r"context_window\s*=\s*(\d+)",
    "num_ctx": r"num_ctx\s*=\s*(\d+)",
    "presence_penalty": r"presence_penalty\s*=\s*([\d.-]+)",
    "frequency_penalty": r"frequency_penalty\s*=\s*([\d.-]+)",
    "top_k": r"top_k\s*=\s*(\d+)",
}

# ─── Tool Detection Patterns ──────────────────────────────────────────────────
TOOL_PATTERNS = {
    "Web Search": [r"serpapi", r"serper", r"tavily", r"brave_search", r"exa", r"DuckDuckGoSearch",
                   r"GoogleSearch", r"web_search", r"search_tool"],
    "Vector Store": [r"pinecone", r"weaviate", r"qdrant", r"chroma", r"faiss", r"milvus",
                     r"pgvector", r"VectorStore", r"vector_store", r"ChromaDB"],
    "Database": [r"sqlite", r"postgresql", r"mysql", r"mongodb", r"redis", r"SQLDatabase",
                 r"sql_tool", r"database_tool"],
    "RAG": [r"RAG", r"retrieval_augmented", r"retrieve_and_generate", r"VectorStoreRetriever",
            r"MultiQueryRetriever", r"EnsembleRetriever", r"ContextualCompressionRetriever"],
    "Calculator": [r"calculator", r"Calculator", r"wolfram", r"math_tool", r"LLMMathChain"],
    "Browser": [r"playwright", r"selenium", r"puppeteer", r"browser_tool", r"WebBrowser"],
    "Email": [r"smtp", r"sendgrid", r"mailgun", r"email_tool", r"EmailTool"],
    "Slack": [r"slack_sdk", r"SlackTool", r"slack_bolt"],
    "GitHub": [r"PyGithub", r"github_tool", r"GitHubToolkit"],
    "Azure Tools": [r"azure.*tool", r"AzureTool"],
    "AWS Tools": [r"boto3", r"aws.*tool"],
    "Filesystem": [r"file_tool", r"ReadFileTool", r"WriteFileTool", r"FilesystemTool"],
    "Shell": [r"BashProcess", r"shell_tool", r"ShellTool", r"subprocess"],
    "Python REPL": [r"PythonREPL", r"python_repl", r"PythonInterpreter"],
    "Memory": [r"ConversationBufferMemory", r"ConversationSummaryMemory", r"VectorStoreMemory",
               r"memory_tool", r"MemorySaver", r"checkpointer"],
    "Code Interpreter": [r"code_interpreter", r"CodeInterpreter", r"E2B"],
}

# ─── Workflow Pattern Detection ───────────────────────────────────────────────
WORKFLOW_PATTERNS = {
    "Planning": [r"plan\s*\(", r"planner", r"create_plan", r"task_planning", r"PlanAndExecute"],
    "Execution": [r"execute\s*\(", r"executor", r"run_task", r"AgentExecutor"],
    "Reflection": [r"reflect\s*\(", r"reflection", r"self_critique", r"evaluate_output"],
    "Retry": [r"retry", r"backoff", r"tenacity", r"max_retries", r"retry_on_failure"],
    "Evaluation": [r"evaluate\s*\(", r"evaluator", r"QAEvalChain", r"criteria_eval"],
    "Memory": [r"memory\s*=", r"ConversationMemory", r"MemorySaver", r"checkpointer"],
    "RAG": [r"retrieve\s*\(", r"retriever\s*=", r"similarity_search", r"vectorstore\.search"],
    "Tool Calling": [r"tool_calls", r"function_call", r"@tool", r"Tool\s*\(", r"StructuredTool"],
    "Streaming": [r"stream\s*\(", r"streaming\s*=\s*True", r"stream_tokens", r"StreamingStdOutCallbackHandler"],
    "Multi-agent": [r"MultiAgent", r"multi_agent", r"GroupChat", r"Crew\s*\(", r"supervisor"],
    "Supervisor": [r"supervisor", r"SupervisorAgent", r"orchestrator", r"coordinator"],
    "Function Calling": [r"functions\s*=\s*\[", r"tools\s*=\s*\[", r"function_definitions"],
}

# ─── Purpose Detection ────────────────────────────────────────────────────────
PURPOSE_KEYWORDS = {
    "AI Agent": ["agent", "multi_agent", "autonomous", "reasoning"],
    "LLM Wrapper": ["llm", "language_model", "chat_model"],
    "Prompt Management": ["prompt", "template", "system_message"],
    "Memory Management": ["memory", "history", "conversation_buffer"],
    "Tool / Function": ["tool", "function_tool", "@tool"],
    "RAG Pipeline": ["rag", "retrieval", "vectorstore", "retriever"],
    "Embedding": ["embedding", "embed", "vectorize"],
    "Workflow Orchestration": ["workflow", "pipeline", "chain", "graph"],
    "API Controller": ["controller", "router", "endpoint", "route"],
    "Service Layer": ["service", "manager", "handler"],
    "Data Model": ["model", "schema", "entity", "dataclass"],
    "Database Access": ["repository", "dao", "database", "db"],
    "Authentication": ["auth", "login", "jwt", "oauth", "token_auth"],
    "Configuration": ["config", "settings", "constants", "env"],
    "Logging": ["logging", "logger", "log"],
    "Monitoring": ["monitor", "metrics", "telemetry", "tracing", "otel"],
    "Testing": ["test", "spec", "unittest", "pytest", "assert"],
    "Deployment": ["deploy", "dockerfile", "kubernetes", "helm", "terraform"],
    "Scheduler": ["scheduler", "cron", "celery", "apscheduler"],
    "Queue": ["queue", "rabbitmq", "kafka", "sqs", "pubsub"],
    "CLI": ["cli", "argparse", "click", "typer", "main"],
    "Frontend UI": ["ui", "frontend", "component", "view", "page"],
    "Utility": ["util", "helper", "common", "shared", "tools"],
    "Documentation": ["readme", "docs", "changelog", "guide"],
    "Infrastructure": ["terraform", "ansible", "pulumi", "cdk"],
    "Vector Database": ["pinecone", "weaviate", "chroma", "qdrant", "faiss"],
    "Streaming": ["streaming", "websocket", "sse", "grpc"],
    "Multi-modal": ["vision", "image", "audio", "multimodal", "dall-e", "whisper"],
}


# ══════════════════════════════════════════════════════════════════════════════
# DATA CLASSES
# ══════════════════════════════════════════════════════════════════════════════

@dataclass
class FileRecord:
    serial: int = 0
    relative_path: str = ""
    file_name: str = ""
    extension: str = ""
    language: str = ""
    category: str = ""
    purpose: str = ""
    description: str = ""
    size_bytes: int = 0
    lines_of_code: int = 0
    is_used: str = "Unknown"
    is_referenced: str = "Unknown"
    is_ai_related: bool = False
    dependencies: list = field(default_factory=list)
    imports: list = field(default_factory=list)
    classes: list = field(default_factory=list)
    functions: list = field(default_factory=list)
    content_hash: str = ""


@dataclass
class AgentRecord:
    name: str = ""
    file: str = ""
    agent_type: str = ""
    purpose: str = ""
    provider: str = "Unknown"
    sdk: str = "Unknown"
    model: str = "Unknown"
    tools: list = field(default_factory=list)
    workflows: list = field(default_factory=list)
    prompts: list = field(default_factory=list)
    token_config: dict = field(default_factory=dict)
    line_number: int = 0


@dataclass
class ProviderRecord:
    name: str = ""
    sdk: str = ""
    endpoint: str = ""
    api_version: str = ""
    auth_method: str = ""
    env_vars: list = field(default_factory=list)
    files: list = field(default_factory=list)
    models_used: list = field(default_factory=list)


@dataclass
class ModelRecord:
    name: str = ""
    version: str = ""
    provider: str = ""
    files: list = field(default_factory=list)
    reference_count: int = 0
    token_config: dict = field(default_factory=dict)


@dataclass
class PromptRecord:
    name: str = ""
    location: str = ""
    line_number: int = 0
    purpose: str = ""
    prompt_type: str = ""
    agent: str = ""
    content_preview: str = ""


@dataclass
class APIKeyRecord:
    variable_name: str = ""
    provider: str = ""
    used_in: list = field(default_factory=list)
    loaded_from: str = ""


@dataclass
class SDKRecord:
    name: str = ""
    files: list = field(default_factory=list)
    version: str = "Unknown"
    import_count: int = 0


@dataclass
class ToolRecord:
    name: str = ""
    files: list = field(default_factory=list)
    agents_using: list = field(default_factory=list)


@dataclass
class WorkflowRecord:
    name: str = ""
    files: list = field(default_factory=list)
    patterns_found: list = field(default_factory=list)


# ══════════════════════════════════════════════════════════════════════════════
# SCANNER CLASS
# ══════════════════════════════════════════════════════════════════════════════

class RepositoryScanner:
    """Core scanner that recursively analyzes a repository."""

    def __init__(self, root_path: str):
        self.root = Path(root_path).resolve()
        self.scan_date = datetime.datetime.now()
        self.files: list[FileRecord] = []
        self.agents: list[AgentRecord] = []
        self.providers: dict[str, ProviderRecord] = {}
        self.models: dict[str, ModelRecord] = {}
        self.prompts: list[PromptRecord] = []
        self.api_keys: dict[str, APIKeyRecord] = {}
        self.sdks: dict[str, SDKRecord] = {}
        self.tools: dict[str, ToolRecord] = {}
        self.workflows: dict[str, WorkflowRecord] = {}
        self.directories: list[str] = []
        self.dependency_graph: dict[str, list[str]] = defaultdict(list)
        self.referenced_files: set[str] = set()
        self.all_file_paths: set[str] = set()
        self.stats = {
            "total_classes": 0,
            "total_functions": 0,
            "total_apis": 0,
            "total_endpoints": 0,
            "total_modules": 0,
            "total_packages": 0,
            "total_tests": 0,
            "total_docker_files": 0,
            "total_yaml_files": 0,
            "total_terraform_files": 0,
            "total_k8s_files": 0,
        }

    # ──────────────────────────────────────────────
    # Main Scan Entry Point
    # ──────────────────────────────────────────────
    def scan(self):
        """Perform complete repository scan."""
        print(f"[*] Scanning repository: {self.root}")
        print("[*] Phase 1: Discovering files and directories...")
        self._discover_files()
        print(f"[*] Discovered {len(self.files)} files in {len(self.directories)} directories")
        print("[*] Phase 2: Analyzing file contents...")
        self._analyze_files()
        print("[*] Phase 3: Building dependency graph...")
        self._build_dependency_graph()
        print("[*] Phase 4: Marking referenced files...")
        self._mark_referenced_files()
        print("[*] Analysis complete.")

    # ──────────────────────────────────────────────
    # Phase 1: File Discovery
    # ──────────────────────────────────────────────
    def _discover_files(self):
        serial = 0
        for dirpath, dirnames, filenames in os.walk(self.root):
            # Filter ignored directories in-place
            dirnames[:] = [
                d for d in sorted(dirnames)
                if d not in IGNORED_DIRS
                and not d.startswith(".")
                and not any(d.endswith(suffix.lstrip("*")) for suffix in IGNORED_DIRS if "*" in suffix)
                or d in {".github", ".circleci", ".gitlab"}  # keep some dot-dirs
            ]
            # Actually be simpler: just filter out exactly what we want to ignore
            dirnames[:] = [
                d for d in sorted(dirnames)
                if d not in IGNORED_DIRS
                and not (d.startswith(".") and d not in {".github", ".circleci", ".gitlab"})
                and not d.endswith(".egg-info")
            ]

            rel_dir = str(Path(dirpath).relative_to(self.root))
            if rel_dir == ".":
                rel_dir = "/"
            self.directories.append(rel_dir)

            for filename in sorted(filenames):
                filepath = Path(dirpath) / filename
                try:
                    stat = filepath.stat()
                except OSError:
                    continue

                serial += 1
                rel_path = str(filepath.relative_to(self.root))
                self.all_file_paths.add(rel_path)

                ext = self._get_extension(filepath)
                lang = self._detect_language(filepath, ext)
                cat = self._detect_category_quick(rel_path, filename, ext)

                record = FileRecord(
                    serial=serial,
                    relative_path=rel_path,
                    file_name=filename,
                    extension=ext,
                    language=lang,
                    category=cat,
                    size_bytes=stat.st_size,
                )
                self.files.append(record)

                # Quick stats
                if "test" in rel_path.lower() or filename.startswith("test_") or "_test." in filename:
                    self.stats["total_tests"] += 1
                if filename.lower() in ("dockerfile",) or ext in (".dockerfile",):
                    self.stats["total_docker_files"] += 1
                if ext in (".yaml", ".yml"):
                    self.stats["total_yaml_files"] += 1
                if ext in (".tf", ".tfvars", ".hcl"):
                    self.stats["total_terraform_files"] += 1

    def _get_extension(self, filepath: Path) -> str:
        name = filepath.name
        # Check exact filename matches first
        if name in EXTENSION_LANGUAGE_MAP:
            return name
        if name.lower() in ("dockerfile", "makefile", "jenkinsfile"):
            return name.lower()
        ext = filepath.suffix.lower()
        return ext if ext else ""

    def _detect_language(self, filepath: Path, ext: str) -> str:
        if ext in EXTENSION_LANGUAGE_MAP:
            return EXTENSION_LANGUAGE_MAP[ext]
        if filepath.name in EXTENSION_LANGUAGE_MAP:
            return EXTENSION_LANGUAGE_MAP[filepath.name]
        return "Unknown"

    def _detect_category_quick(self, rel_path: str, filename: str, ext: str) -> str:
        path_lower = (rel_path + "/" + filename).lower()
        for cat, patterns in CATEGORY_PATTERNS.items():
            if cat == "Source":
                continue
            for p in patterns:
                if re.search(p, path_lower, re.IGNORECASE):
                    return cat
        if ext in (".py", ".js", ".ts", ".java", ".cs", ".go", ".rs", ".kt",
                   ".scala", ".rb", ".php", ".swift", ".dart", ".c", ".cpp"):
            return "Source"
        return "Other"

    # ──────────────────────────────────────────────
    # Phase 2: Content Analysis
    # ──────────────────────────────────────────────
    def _analyze_files(self):
        total = len(self.files)
        for i, record in enumerate(self.files):
            if i % 50 == 0:
                print(f"    [{i}/{total}] Analyzing files...")
            filepath = self.root / record.relative_path
            try:
                content = self._read_file(filepath)
            except Exception:
                continue

            if content is None:
                continue

            record.lines_of_code = content.count("\n") + 1
            record.content_hash = hashlib.md5(content.encode("utf-8", errors="ignore")).hexdigest()[:8]

            # Detect imports, classes, functions
            record.imports = self._extract_imports(content, record.language)
            record.classes = self._extract_classes(content, record.language)
            record.functions = self._extract_functions(content, record.language)

            # Update global stats
            self.stats["total_classes"] += len(record.classes)
            self.stats["total_functions"] += len(record.functions)

            # Purpose and description
            record.purpose, record.description = self._detect_purpose(
                record, content
            )

            # AI detection
            record.is_ai_related = self._is_ai_related(content, record.relative_path)
            if record.is_ai_related:
                record.category = "AI"

            # Override category for AI
            if record.is_ai_related and record.category not in ("Test", "Configuration", "Documentation"):
                record.category = "AI"

            # Provider detection
            self._detect_providers(content, record.relative_path)

            # Model detection
            self._detect_models(content, record.relative_path)

            # Prompt detection
            self._detect_prompts(content, record.relative_path)

            # API Key detection
            self._detect_api_keys(content, record.relative_path)

            # SDK detection
            self._detect_sdks(content, record.relative_path)

            # Tool detection
            self._detect_tools(content, record.relative_path)

            # Workflow detection
            self._detect_workflows(content, record.relative_path)

            # Agent detection
            self._detect_agents(content, record)

            # Endpoint detection
            endpoint_count = len(re.findall(
                r'@(?:app|router|blueprint)\s*\.\s*(?:get|post|put|delete|patch|route)',
                content, re.IGNORECASE
            ))
            self.stats["total_endpoints"] += endpoint_count
            if endpoint_count > 0:
                self.stats["total_apis"] += 1

            # Dependencies (imports as deps)
            record.dependencies = record.imports[:10]  # top 10

    def _read_file(self, filepath: Path) -> Optional[str]:
        """Read file content, skipping binary files."""
        if filepath.stat().st_size > 10 * 1024 * 1024:  # skip >10MB
            return None
        try:
            return filepath.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            try:
                return filepath.read_text(encoding="latin-1", errors="ignore")
            except Exception:
                return None

    def _extract_imports(self, content: str, language: str) -> list[str]:
        imports = []
        if language in ("Python",):
            for m in re.finditer(r'^(?:import|from)\s+([\w.]+)', content, re.MULTILINE):
                imports.append(m.group(1))
        elif language in ("JavaScript", "TypeScript"):
            for m in re.finditer(r"(?:import|require)\s*\(?['\"]([^'\"]+)['\"]", content):
                imports.append(m.group(1))
        elif language in ("Java", "Kotlin", "Scala"):
            for m in re.finditer(r'^import\s+([\w.]+)', content, re.MULTILINE):
                imports.append(m.group(1))
        elif language in ("Go",):
            for m in re.finditer(r'"([^"]+)"', content):
                imports.append(m.group(1))
        elif language in ("C#",):
            for m in re.finditer(r'^using\s+([\w.]+)', content, re.MULTILINE):
                imports.append(m.group(1))
        elif language in ("Rust",):
            for m in re.finditer(r'^use\s+([\w:]+)', content, re.MULTILINE):
                imports.append(m.group(1))
        return list(dict.fromkeys(imports))[:30]  # deduplicate, limit

    def _extract_classes(self, content: str, language: str) -> list[str]:
        classes = []
        if language == "Python":
            for m in re.finditer(r'^class\s+(\w+)', content, re.MULTILINE):
                classes.append(m.group(1))
        elif language in ("Java", "Kotlin", "Scala", "C#"):
            for m in re.finditer(r'(?:class|interface|object)\s+(\w+)', content):
                classes.append(m.group(1))
        elif language in ("JavaScript", "TypeScript"):
            for m in re.finditer(r'class\s+(\w+)', content):
                classes.append(m.group(1))
        elif language == "Go":
            for m in re.finditer(r'type\s+(\w+)\s+struct', content):
                classes.append(m.group(1))
        return list(dict.fromkeys(classes))

    def _extract_functions(self, content: str, language: str) -> list[str]:
        funcs = []
        if language == "Python":
            for m in re.finditer(r'^def\s+(\w+)\s*\(', content, re.MULTILINE):
                funcs.append(m.group(1))
            for m in re.finditer(r'^async\s+def\s+(\w+)\s*\(', content, re.MULTILINE):
                funcs.append(m.group(1))
        elif language in ("JavaScript", "TypeScript"):
            for m in re.finditer(r'(?:function\s+(\w+)|(?:const|let|var)\s+(\w+)\s*=\s*(?:async\s*)?\(?)', content):
                name = m.group(1) or m.group(2)
                if name:
                    funcs.append(name)
        elif language in ("Java", "C#", "Kotlin"):
            for m in re.finditer(r'(?:public|private|protected|static|async)[\s\w<>[\]]+\s+(\w+)\s*\(', content):
                funcs.append(m.group(1))
        elif language == "Go":
            for m in re.finditer(r'^func\s+(?:\(\w+\s+\*?\w+\)\s+)?(\w+)\s*\(', content, re.MULTILINE):
                funcs.append(m.group(1))
        elif language == "Rust":
            for m in re.finditer(r'^(?:pub\s+)?fn\s+(\w+)', content, re.MULTILINE):
                funcs.append(m.group(1))
        return list(dict.fromkeys(funcs))[:50]

    def _is_ai_related(self, content: str, rel_path: str) -> bool:
        path_lower = rel_path.lower()
        for keyword in ["agent", "llm", "prompt", "openai", "anthropic", "gemini",
                        "langchain", "embedding", "vector", "rag", "gpt", "claude",
                        "llama", "mistral", "groq", "cohere", "ollama", "inference",
                        "completion", "transformer", "bert", "neural", "ai_", "_ai",
                        "semantic_kernel", "autogen", "crewai", "llamaindex", "dspy"]:
            if keyword in path_lower:
                return True
        content_lower = content[:5000].lower()
        ai_score = 0
        for keyword in ["openai", "anthropic", "langchain", "llm", "gpt-4", "gpt-3",
                        "claude", "gemini", "llama", "completion", "embedding",
                        "chat_completion", "messages.create", "generate_content",
                        "agent", "prompt_template", "system_prompt"]:
            if keyword in content_lower:
                ai_score += 1
        return ai_score >= 2

    def _detect_purpose(self, record: FileRecord, content: str) -> tuple[str, str]:
        path_lower = (record.relative_path + "/" + record.file_name).lower()
        content_lower = content[:3000].lower()

        matched_purposes = []
        for purpose, keywords in PURPOSE_KEYWORDS.items():
            for kw in keywords:
                if kw in path_lower or kw in content_lower:
                    matched_purposes.append(purpose)
                    break

        if not matched_purposes:
            # Fallback based on category
            cat_map = {
                "Test": "Testing",
                "Configuration": "Configuration",
                "Documentation": "Documentation",
                "Infrastructure": "Deployment",
                "AI": "AI Component",
                "Frontend": "Frontend UI",
                "Backend": "Backend Service",
                "Database": "Database Access",
            }
            matched_purposes = [cat_map.get(record.category, "Utility")]

        primary_purpose = matched_purposes[0] if matched_purposes else "Utility"

        # Build description
        desc_parts = []
        if record.classes:
            desc_parts.append(f"Contains {len(record.classes)} class(es): {', '.join(record.classes[:3])}")
        if record.functions:
            desc_parts.append(f"{len(record.functions)} function(s)")
        if record.imports:
            key_imports = [i for i in record.imports[:5]]
            if key_imports:
                desc_parts.append(f"Imports: {', '.join(key_imports[:3])}")
        if len(matched_purposes) > 1:
            desc_parts.append(f"Roles: {', '.join(matched_purposes[:3])}")

        description = "; ".join(desc_parts) if desc_parts else f"{primary_purpose} file"
        return primary_purpose, description

    def _detect_providers(self, content: str, rel_path: str):
        for provider_name, patterns in AI_PROVIDER_PATTERNS.items():
            found = False
            env_vars_found = []

            for pattern in patterns.get("imports", []):
                if re.search(pattern, content, re.IGNORECASE):
                    found = True
                    break

            for pattern in patterns.get("env_vars", []):
                if re.search(pattern, content, re.IGNORECASE):
                    found = True
                    env_vars_found.append(pattern.rstrip("$"))

            for pattern in patterns.get("endpoints", []):
                if re.search(pattern, content, re.IGNORECASE):
                    found = True

            if found:
                if provider_name not in self.providers:
                    self.providers[provider_name] = ProviderRecord(
                        name=provider_name,
                        sdk=patterns.get("sdk", "Unknown"),
                        env_vars=env_vars_found,
                        files=[rel_path],
                    )
                else:
                    pr = self.providers[provider_name]
                    if rel_path not in pr.files:
                        pr.files.append(rel_path)
                    for ev in env_vars_found:
                        if ev not in pr.env_vars:
                            pr.env_vars.append(ev)

    def _detect_models(self, content: str, rel_path: str):
        for pattern in AI_MODEL_PATTERNS:
            for m in re.finditer(pattern, content, re.IGNORECASE):
                model_name = m.group(0).lower().strip()
                if len(model_name) < 3:
                    continue
                if model_name not in self.models:
                    provider = self._infer_model_provider(model_name)
                    self.models[model_name] = ModelRecord(
                        name=model_name,
                        provider=provider,
                        files=[rel_path],
                        reference_count=1,
                    )
                else:
                    mr = self.models[model_name]
                    mr.reference_count += 1
                    if rel_path not in mr.files:
                        mr.files.append(rel_path)

    def _infer_model_provider(self, model_name: str) -> str:
        mn = model_name.lower()
        if any(x in mn for x in ["gpt", "o1", "o2", "o3", "o4", "davinci", "dall-e", "whisper", "text-embedding"]):
            return "OpenAI"
        if any(x in mn for x in ["claude"]):
            return "Anthropic"
        if any(x in mn for x in ["gemini", "bard", "palm", "text-bison", "chat-bison"]):
            return "Google"
        if any(x in mn for x in ["llama", "codellama"]):
            return "Meta"
        if any(x in mn for x in ["mistral", "mixtral", "codestral"]):
            return "Mistral"
        if any(x in mn for x in ["deepseek"]):
            return "DeepSeek"
        if any(x in mn for x in ["command", "embed-english", "embed-multilingual", "aya"]):
            return "Cohere"
        if any(x in mn for x in ["phi"]):
            return "Microsoft"
        if any(x in mn for x in ["qwen"]):
            return "Alibaba"
        if any(x in mn for x in ["yi"]):
            return "01.AI"
        if any(x in mn for x in ["falcon"]):
            return "TII"
        if any(x in mn for x in ["bert", "roberta", "distilbert", "albert", "t5", "flan", "bloom", "opt", "gpt-j", "gpt-neo", "starcoder"]):
            return "HuggingFace"
        return "Unknown"

    def _detect_prompts(self, content: str, rel_path: str):
        for pattern in PROMPT_PATTERNS:
            for m in re.finditer(pattern, content, re.IGNORECASE | re.MULTILINE):
                line_num = content[:m.start()].count("\n") + 1
                # Get a snippet of what follows
                start = m.end()
                snippet = content[start:start + 200].strip()[:100]
                prompt_type = "System Prompt" if "system" in pattern.lower() else \
                              "User Prompt" if "user" in pattern.lower() else \
                              "Template" if "template" in pattern.lower() else "Prompt"

                pr = PromptRecord(
                    name=f"Prompt at line {line_num}",
                    location=rel_path,
                    line_number=line_num,
                    purpose="Detected inline prompt",
                    prompt_type=prompt_type,
                    agent="Unknown",
                    content_preview=snippet.replace("\n", " ")[:80],
                )
                self.prompts.append(pr)
                break  # one detection per pattern per file to avoid spam

        # Detect .prompt, .j2, .jinja files as prompt files
        if any(rel_path.endswith(ext) for ext in [".prompt", ".j2", ".jinja", ".jinja2"]):
            pr = PromptRecord(
                name=Path(rel_path).name,
                location=rel_path,
                line_number=1,
                purpose="Prompt template file",
                prompt_type="Template File",
                agent="Unknown",
                content_preview=content[:100].replace("\n", " "),
            )
            self.prompts.append(pr)

    def _detect_api_keys(self, content: str, rel_path: str):
        for var_name, provider in API_KEY_PATTERNS.items():
            if re.search(r'\b' + re.escape(var_name) + r'\b', content):
                if var_name not in self.api_keys:
                    # Detect how it's loaded
                    loaded_from = "Unknown"
                    if re.search(r'os\.environ', content):
                        loaded_from = "os.environ"
                    elif re.search(r'os\.getenv', content):
                        loaded_from = "os.getenv"
                    elif re.search(r'dotenv|load_dotenv', content):
                        loaded_from = ".env file"
                    elif re.search(r'\.env', rel_path.lower()):
                        loaded_from = ".env file"
                    elif rel_path.endswith((".yaml", ".yml", ".json")):
                        loaded_from = f"Config file ({rel_path})"

                    self.api_keys[var_name] = APIKeyRecord(
                        variable_name=var_name,
                        provider=provider,
                        used_in=[rel_path],
                        loaded_from=loaded_from,
                    )
                else:
                    rec = self.api_keys[var_name]
                    if rel_path not in rec.used_in:
                        rec.used_in.append(rel_path)

    def _detect_sdks(self, content: str, rel_path: str):
        for sdk_name, patterns in AI_SDK_PATTERNS.items():
            for pattern in patterns:
                if re.search(pattern, content, re.IGNORECASE):
                    if sdk_name not in self.sdks:
                        self.sdks[sdk_name] = SDKRecord(
                            name=sdk_name,
                            files=[rel_path],
                            import_count=1,
                        )
                    else:
                        sr = self.sdks[sdk_name]
                        sr.import_count += 1
                        if rel_path not in sr.files:
                            sr.files.append(rel_path)
                    break

    def _detect_tools(self, content: str, rel_path: str):
        for tool_name, patterns in TOOL_PATTERNS.items():
            for pattern in patterns:
                if re.search(pattern, content, re.IGNORECASE):
                    if tool_name not in self.tools:
                        self.tools[tool_name] = ToolRecord(
                            name=tool_name,
                            files=[rel_path],
                        )
                    else:
                        tr = self.tools[tool_name]
                        if rel_path not in tr.files:
                            tr.files.append(rel_path)
                    break

    def _detect_workflows(self, content: str, rel_path: str):
        for wf_name, patterns in WORKFLOW_PATTERNS.items():
            for pattern in patterns:
                if re.search(pattern, content, re.IGNORECASE):
                    if wf_name not in self.workflows:
                        self.workflows[wf_name] = WorkflowRecord(
                            name=wf_name,
                            files=[rel_path],
                            patterns_found=[pattern],
                        )
                    else:
                        wr = self.workflows[wf_name]
                        if rel_path not in wr.files:
                            wr.files.append(rel_path)
                        if pattern not in wr.patterns_found:
                            wr.patterns_found.append(pattern)
                    break

    def _detect_agents(self, content: str, record: FileRecord):
        """Detect AI agents from file content."""
        for pattern in AGENT_PATTERNS:
            for m in re.finditer(pattern, content, re.IGNORECASE):
                line_num = content[:m.start()].count("\n") + 1
                matched_text = m.group(0)

                # Determine agent name
                agent_name = "Unknown Agent"
                class_match = re.match(r'class\s+(\w+)', matched_text)
                if class_match:
                    agent_name = class_match.group(1)
                elif "AgentExecutor" in matched_text:
                    agent_name = "AgentExecutor"
                elif "AssistantAgent" in matched_text:
                    agent_name = "AssistantAgent"
                elif "UserProxyAgent" in matched_text:
                    agent_name = "UserProxyAgent"
                elif "Crew" in matched_text:
                    agent_name = "CrewAI Agent"
                elif "StateGraph" in matched_text:
                    agent_name = "LangGraph Agent"
                else:
                    # Try to find the variable name
                    ctx_start = max(0, m.start() - 50)
                    ctx = content[ctx_start:m.end() + 50]
                    var_match = re.search(r'(\w+)\s*=\s*' + re.escape(matched_text[:20]), ctx)
                    if var_match:
                        agent_name = var_match.group(1)

                # Detect provider and model from surrounding context
                ctx_start = max(0, m.start() - 500)
                ctx_end = min(len(content), m.end() + 500)
                context = content[ctx_start:ctx_end]

                provider = self._detect_provider_from_context(context)
                model = self._detect_model_from_context(context)
                sdk = self._detect_sdk_from_context(context)
                token_config = self._extract_token_config(context)
                tools = self._detect_tools_from_context(context)
                workflows = self._detect_workflows_from_context(context)

                # Determine agent type
                agent_type = "AI Agent"
                if "class" in matched_text.lower():
                    agent_type = "Class-based Agent"
                elif any(x in matched_text for x in ["AgentExecutor", "create_agent"]):
                    agent_type = "LangChain Agent"
                elif "Crew" in matched_text:
                    agent_type = "CrewAI Agent"
                elif "StateGraph" in matched_text or "MessageGraph" in matched_text:
                    agent_type = "LangGraph Agent"
                elif "AssistantAgent" in matched_text or "UserProxyAgent" in matched_text:
                    agent_type = "AutoGen Agent"
                elif "chat_completion" in matched_text.lower() or "messages.create" in matched_text.lower():
                    agent_type = "API-based Agent"

                agent = AgentRecord(
                    name=agent_name,
                    file=record.relative_path,
                    agent_type=agent_type,
                    purpose=record.purpose,
                    provider=provider,
                    sdk=sdk,
                    model=model,
                    tools=tools,
                    workflows=workflows,
                    token_config=token_config,
                    line_number=line_num,
                )
                self.agents.append(agent)

                # Avoid too many agents per file
                if len([a for a in self.agents if a.file == record.relative_path]) >= 10:
                    return

    def _detect_provider_from_context(self, context: str) -> str:
        for provider_name, patterns in AI_PROVIDER_PATTERNS.items():
            for pattern in patterns.get("imports", []):
                if re.search(pattern, context, re.IGNORECASE):
                    return provider_name
        return "Unknown"

    def _detect_model_from_context(self, context: str) -> str:
        for pattern in AI_MODEL_PATTERNS:
            m = re.search(pattern, context, re.IGNORECASE)
            if m:
                return m.group(0)
        return "Not Specified"

    def _detect_sdk_from_context(self, context: str) -> str:
        for sdk_name, patterns in AI_SDK_PATTERNS.items():
            for pattern in patterns:
                if re.search(pattern, context, re.IGNORECASE):
                    return sdk_name
        return "Unknown"

    def _extract_token_config(self, context: str) -> dict:
        config = {}
        for key, pattern in TOKEN_PATTERNS.items():
            m = re.search(pattern, context, re.IGNORECASE)
            if m:
                config[key] = m.group(1)
        return config

    def _detect_tools_from_context(self, context: str) -> list[str]:
        found = []
        for tool_name, patterns in TOOL_PATTERNS.items():
            for pattern in patterns:
                if re.search(pattern, context, re.IGNORECASE):
                    found.append(tool_name)
                    break
        return found

    def _detect_workflows_from_context(self, context: str) -> list[str]:
        found = []
        for wf_name, patterns in WORKFLOW_PATTERNS.items():
            for pattern in patterns:
                if re.search(pattern, context, re.IGNORECASE):
                    found.append(wf_name)
                    break
        return found

    # ──────────────────────────────────────────────
    # Phase 3: Dependency Graph
    # ──────────────────────────────────────────────
    def _build_dependency_graph(self):
        file_name_map = {}
        for f in self.files:
            stem = Path(f.file_name).stem
            file_name_map[stem] = f.relative_path
            file_name_map[f.file_name] = f.relative_path

        for f in self.files:
            for imp in f.imports:
                parts = imp.replace("/", ".").split(".")
                for i in range(len(parts), 0, -1):
                    key = parts[i-1]
                    if key in file_name_map and file_name_map[key] != f.relative_path:
                        self.dependency_graph[f.relative_path].append(file_name_map[key])
                        self.referenced_files.add(file_name_map[key])
                        break

    def _mark_referenced_files(self):
        for f in self.files:
            if f.relative_path in self.referenced_files:
                f.is_referenced = "Yes"
                f.is_used = "Yes"
            else:
                f.is_referenced = "No"
                # Heuristic: main files, configs, and tests are "used"
                name_lower = f.file_name.lower()
                if any(x in name_lower for x in ["main", "app", "server", "index", "__init__",
                                                    "config", "settings", "requirements", "setup"]):
                    f.is_used = "Likely"
                else:
                    f.is_used = "Unknown"

    # ──────────────────────────────────────────────
    # Computed Statistics
    # ──────────────────────────────────────────────
    def get_summary(self) -> dict:
        cats = Counter(f.category for f in self.files)
        return {
            "repository_name": self.root.name,
            "repository_root": str(self.root),
            "scan_date": self.scan_date.strftime("%Y-%m-%d %H:%M:%S"),
            "total_directories": len(self.directories),
            "total_files": len(self.files),
            "total_source_files": cats.get("Source", 0),
            "total_configuration_files": cats.get("Configuration", 0),
            "total_documentation_files": cats.get("Documentation", 0),
            "total_test_files": cats.get("Test", 0),
            "total_infrastructure_files": cats.get("Infrastructure", 0),
            "total_ai_related_files": sum(1 for f in self.files if f.is_ai_related),
            "total_agents": len(self.agents),
            "total_providers": len(self.providers),
            "total_models": len(self.models),
            "total_prompts": len(self.prompts),
            "total_sdks": len(self.sdks),
            "total_tools": len(self.tools),
            "total_workflows": len(self.workflows),
            "total_api_keys": len(self.api_keys),
            **self.stats,
        }

    def get_directory_tree(self) -> str:
        """Generate ASCII directory tree."""
        tree_lines = [str(self.root.name) + "/"]
        self._build_tree(self.root, "", tree_lines, max_depth=6)
        return "\n".join(tree_lines)

    def _build_tree(self, path: Path, prefix: str, lines: list, depth: int = 0, max_depth: int = 6):
        if depth >= max_depth:
            return
        try:
            entries = sorted(path.iterdir())
        except PermissionError:
            return

        entries = [e for e in entries if e.name not in IGNORED_DIRS and not (e.name.startswith(".") and e.name not in {".github", ".circleci", ".gitlab"})]
        dirs = [e for e in entries if e.is_dir()]
        files = [e for e in entries if e.is_file()]
        all_entries = dirs + files

        for i, entry in enumerate(all_entries):
            is_last = i == len(all_entries) - 1
            connector = "└── " if is_last else "├── "
            lines.append(prefix + connector + entry.name + ("/" if entry.is_dir() else ""))
            if entry.is_dir():
                extension = "    " if is_last else "│   "
                self._build_tree(entry, prefix + extension, lines, depth + 1, max_depth)


# ══════════════════════════════════════════════════════════════════════════════
# REPORT GENERATORS
# ══════════════════════════════════════════════════════════════════════════════

class ReportGenerator:
    """Generates all output reports."""

    def __init__(self, scanner: RepositoryScanner, output_dir: str):
        self.scanner = scanner
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.summary = scanner.get_summary()

    # ──────────────────────────────────────────────
    # JSON Report
    # ──────────────────────────────────────────────
    def generate_json(self):
        data = {
            "summary": self.summary,
            "files": [],
            "agents": [],
            "providers": {},
            "models": {},
            "prompts": [],
            "api_keys": {},
            "sdks": {},
            "tools": {},
            "workflows": {},
            "dependency_graph": dict(self.scanner.dependency_graph),
        }

        for f in self.scanner.files:
            fd = asdict(f)
            fd["dependencies"] = fd["dependencies"][:5]
            fd["imports"] = fd["imports"][:10]
            fd["classes"] = fd["classes"][:10]
            fd["functions"] = fd["functions"][:10]
            data["files"].append(fd)

        for a in self.scanner.agents:
            data["agents"].append(asdict(a))

        for name, pr in self.scanner.providers.items():
            data["providers"][name] = asdict(pr)

        for name, mr in self.scanner.models.items():
            data["models"][name] = asdict(mr)

        for pr in self.scanner.prompts:
            data["prompts"].append(asdict(pr))

        for name, kr in self.scanner.api_keys.items():
            data["api_keys"][name] = asdict(kr)

        for name, sr in self.scanner.sdks.items():
            data["sdks"][name] = asdict(sr)

        for name, tr in self.scanner.tools.items():
            data["tools"][name] = asdict(tr)

        for name, wr in self.scanner.workflows.items():
            data["workflows"][name] = asdict(wr)

        out_path = self.output_dir / "repository_summary.json"
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, default=str)
        print(f"[✓] JSON report: {out_path}")
        return out_path

    # ──────────────────────────────────────────────
    # CSV Report
    # ──────────────────────────────────────────────
    def generate_csv(self):
        out_path = self.output_dir / "repository_summary.csv"
        fieldnames = [
            "serial", "relative_path", "file_name", "extension", "language",
            "category", "purpose", "description", "size_bytes", "lines_of_code",
            "is_used", "is_referenced", "is_ai_related", "dependencies",
            "classes", "functions",
        ]
        with open(out_path, "w", newline="", encoding="utf-8") as csvfile:
            writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
            writer.writeheader()
            for f in self.scanner.files:
                writer.writerow({
                    "serial": f.serial,
                    "relative_path": f.relative_path,
                    "file_name": f.file_name,
                    "extension": f.extension,
                    "language": f.language,
                    "category": f.category,
                    "purpose": f.purpose,
                    "description": f.description[:200],
                    "size_bytes": f.size_bytes,
                    "lines_of_code": f.lines_of_code,
                    "is_used": f.is_used,
                    "is_referenced": f.is_referenced,
                    "is_ai_related": f.is_ai_related,
                    "dependencies": "; ".join(f.dependencies[:5]),
                    "classes": "; ".join(f.classes[:5]),
                    "functions": "; ".join(f.functions[:5]),
                })
        print(f"[✓] CSV report: {out_path}")
        return out_path

    # ──────────────────────────────────────────────
    # Excel Report
    # ──────────────────────────────────────────────
    def generate_xlsx(self):
        if not HAS_OPENPYXL:
            print("[!] openpyxl not installed. Skipping XLSX. Install with: pip install openpyxl")
            return None

        out_path = self.output_dir / "repository_summary.xlsx"
        wb = openpyxl.Workbook()

        # ── Summary Sheet ──
        ws_sum = wb.active
        ws_sum.title = "Summary"
        self._style_sheet_header(ws_sum, "Repository Audit Summary", "A1:C1")

        header_font = Font(bold=True, color="FFFFFF")
        header_fill = PatternFill("solid", fgColor="1F3864")

        ws_sum.append(["Property", "Value", "Notes"])
        for cell in ws_sum[2]:
            cell.font = header_font
            cell.fill = header_fill

        for key, val in self.summary.items():
            ws_sum.append([key.replace("_", " ").title(), str(val), ""])

        ws_sum.column_dimensions["A"].width = 35
        ws_sum.column_dimensions["B"].width = 20
        ws_sum.column_dimensions["C"].width = 30

        # ── Files Sheet ──
        ws_files = wb.create_sheet("File Inventory")
        headers = ["#", "Path", "File Name", "Extension", "Language", "Category",
                   "Purpose", "Description", "Size (B)", "Lines", "Used", "Referenced",
                   "AI Related", "Dependencies"]
        ws_files.append(headers)
        for cell in ws_files[1]:
            cell.font = header_font
            cell.fill = header_fill
            cell.alignment = Alignment(horizontal="center")

        for f in self.scanner.files:
            ai_val = "Yes" if f.is_ai_related else "No"
            ws_files.append([
                f.serial, f.relative_path, f.file_name, f.extension,
                f.language, f.category, f.purpose, f.description[:150],
                f.size_bytes, f.lines_of_code, f.is_used, f.is_referenced,
                ai_val, "; ".join(f.dependencies[:3]),
            ])
            row = ws_files.max_row
            if f.is_ai_related:
                for col in range(1, len(headers) + 1):
                    ws_files.cell(row=row, column=col).fill = PatternFill("solid", fgColor="E8F5E9")

        for col in ws_files.columns:
            max_len = max((len(str(cell.value or "")) for cell in col), default=10)
            ws_files.column_dimensions[col[0].column_letter].width = min(max_len + 2, 60)

        # ── Agents Sheet ──
        ws_agents = wb.create_sheet("AI Agents")
        ag_headers = ["Agent Name", "File", "Type", "Purpose", "Provider", "SDK",
                      "Model", "Tools", "Workflows", "Token Config", "Line #"]
        ws_agents.append(ag_headers)
        for cell in ws_agents[1]:
            cell.font = header_font
            cell.fill = PatternFill("solid", fgColor="1A237E")

        for a in self.scanner.agents:
            ws_agents.append([
                a.name, a.file, a.agent_type, a.purpose, a.provider,
                a.sdk, a.model, "; ".join(a.tools[:3]),
                "; ".join(a.workflows[:3]),
                str(a.token_config)[:100], a.line_number,
            ])

        for col in ws_agents.columns:
            max_len = max((len(str(cell.value or "")) for cell in col), default=10)
            ws_agents.column_dimensions[col[0].column_letter].width = min(max_len + 2, 50)

        # ── Providers Sheet ──
        ws_prov = wb.create_sheet("Providers")
        ws_prov.append(["Provider", "SDK", "Endpoint", "Auth Method", "Env Vars", "Files Count"])
        for cell in ws_prov[1]:
            cell.font = header_font
            cell.fill = PatternFill("solid", fgColor="1B5E20")

        for name, pr in self.scanner.providers.items():
            ws_prov.append([
                pr.name, pr.sdk, pr.endpoint or "Default",
                pr.auth_method or "API Key", "; ".join(pr.env_vars[:3]),
                len(pr.files),
            ])

        # ── Models Sheet ──
        ws_models = wb.create_sheet("Models")
        ws_models.append(["Model Name", "Provider", "Files Count", "Reference Count"])
        for cell in ws_models[1]:
            cell.font = header_font
            cell.fill = PatternFill("solid", fgColor="4A148C")

        for name, mr in self.scanner.models.items():
            ws_models.append([mr.name, mr.provider, len(mr.files), mr.reference_count])

        # ── API Keys Sheet ──
        ws_keys = wb.create_sheet("API Keys")
        ws_keys.append(["Variable Name", "Provider", "Used In Files", "Loaded From"])
        for cell in ws_keys[1]:
            cell.font = header_font
            cell.fill = PatternFill("solid", fgColor="B71C1C")

        for name, kr in self.scanner.api_keys.items():
            ws_keys.append([
                kr.variable_name, kr.provider,
                "; ".join(kr.used_in[:3]), kr.loaded_from,
            ])

        # ── SDKs Sheet ──
        ws_sdks = wb.create_sheet("SDKs")
        ws_sdks.append(["SDK Name", "Files Count", "Import Count"])
        for cell in ws_sdks[1]:
            cell.font = header_font
            cell.fill = PatternFill("solid", fgColor="006064")

        for name, sr in self.scanner.sdks.items():
            ws_sdks.append([sr.name, len(sr.files), sr.import_count])

        wb.save(out_path)
        print(f"[✓] XLSX report: {out_path}")
        return out_path

    def _style_sheet_header(self, ws, title: str, merge_range: str):
        ws.merge_cells(merge_range)
        ws["A1"] = title
        ws["A1"].font = Font(bold=True, size=14, color="FFFFFF")
        ws["A1"].fill = PatternFill("solid", fgColor="0D47A1")
        ws["A1"].alignment = Alignment(horizontal="center")

    # ──────────────────────────────────────────────
    # Markdown Report
    # ──────────────────────────────────────────────
    def generate_markdown(self) -> str:
        s = self.summary
        scanner = self.scanner
        lines = []

        lines.append(f"# Repository Audit Report")
        lines.append(f"\n> Generated: {s['scan_date']}")
        lines.append(f"\n---\n")

        # Summary
        lines.append("## Repository Summary\n")
        lines.append(f"| Property | Value |")
        lines.append(f"|----------|-------|")
        for key, val in s.items():
            lines.append(f"| {key.replace('_', ' ').title()} | {val} |")

        # Directory Tree
        lines.append("\n## Directory Tree\n")
        lines.append("```")
        lines.append(scanner.get_directory_tree())
        lines.append("```")

        # AI Agents
        lines.append("\n## AI Agents\n")
        if scanner.agents:
            lines.append(f"**Total Agents Detected: {len(scanner.agents)}**\n")
            lines.append("| # | Name | File | Type | Provider | SDK | Model | Tools | Line # |")
            lines.append("|---|------|------|------|----------|-----|-------|-------|--------|")
            seen = set()
            i = 1
            for a in scanner.agents:
                key = f"{a.file}:{a.name}:{a.line_number}"
                if key in seen:
                    continue
                seen.add(key)
                tools_str = ", ".join(a.tools[:2]) if a.tools else "None"
                lines.append(f"| {i} | {a.name} | `{a.file}` | {a.agent_type} | {a.provider} | {a.sdk} | `{a.model}` | {tools_str} | {a.line_number} |")
                i += 1
        else:
            lines.append("*No AI agents detected.*")

        # Providers
        lines.append("\n## AI Providers\n")
        if scanner.providers:
            lines.append("| Provider | SDK | Auth Method | Env Variables | Files Count |")
            lines.append("|----------|-----|-------------|---------------|-------------|")
            for name, pr in scanner.providers.items():
                env_str = ", ".join(pr.env_vars[:3]) if pr.env_vars else "None detected"
                lines.append(f"| {pr.name} | {pr.sdk} | {pr.auth_method or 'API Key'} | `{env_str}` | {len(pr.files)} |")
        else:
            lines.append("*No AI providers detected.*")

        # Models
        lines.append("\n## AI Models\n")
        if scanner.models:
            lines.append("| Model | Provider | Files | References |")
            lines.append("|-------|----------|-------|------------|")
            for name, mr in sorted(scanner.models.items(), key=lambda x: -x[1].reference_count):
                lines.append(f"| `{mr.name}` | {mr.provider} | {len(mr.files)} | {mr.reference_count} |")
        else:
            lines.append("*No AI models detected.*")

        # SDKs
        lines.append("\n## AI SDKs & Frameworks\n")
        if scanner.sdks:
            lines.append("| SDK / Framework | Files Using | Import Count |")
            lines.append("|----------------|-------------|--------------|")
            for name, sr in sorted(scanner.sdks.items(), key=lambda x: -x[1].import_count):
                lines.append(f"| {sr.name} | {len(sr.files)} | {sr.import_count} |")
        else:
            lines.append("*No AI SDKs detected.*")

        # API Keys
        lines.append("\n## API Keys & Environment Variables\n")
        if scanner.api_keys:
            lines.append("| Variable | Provider | Loaded From | Files Using |")
            lines.append("|----------|----------|-------------|-------------|")
            for name, kr in scanner.api_keys.items():
                files_str = ", ".join(f"`{f}`" for f in kr.used_in[:2])
                lines.append(f"| `{kr.variable_name}` | {kr.provider} | {kr.loaded_from} | {files_str} |")
        else:
            lines.append("*No API keys detected.*")

        # Prompts
        lines.append("\n## Prompt Inventory\n")
        if scanner.prompts:
            lines.append(f"**Total Prompts Detected: {len(scanner.prompts)}**\n")
            lines.append("| # | Type | Location | Line # | Preview |")
            lines.append("|---|------|----------|--------|---------|")
            for i, pr in enumerate(scanner.prompts[:50], 1):
                preview = pr.content_preview[:60].replace("|", "\\|") if pr.content_preview else ""
                lines.append(f"| {i} | {pr.prompt_type} | `{pr.location}` | {pr.line_number} | {preview} |")
        else:
            lines.append("*No prompts detected.*")

        # Tools
        lines.append("\n## Tools Used by Agents\n")
        if scanner.tools:
            lines.append("| Tool | Files Detected In |")
            lines.append("|------|-------------------|")
            for name, tr in scanner.tools.items():
                lines.append(f"| {tr.name} | {len(tr.files)} file(s) |")
        else:
            lines.append("*No tools detected.*")

        # Workflows
        lines.append("\n## Workflow Patterns\n")
        if scanner.workflows:
            lines.append("| Workflow Pattern | Files |")
            lines.append("|----------------|-------|")
            for name, wr in scanner.workflows.items():
                lines.append(f"| {wr.name} | {len(wr.files)} |")
        else:
            lines.append("*No workflow patterns detected.*")

        # Token Usage Note
        lines.append("\n## Token & Request Usage\n")
        lines.append("> **Note:** Runtime token usage (current tokens used, daily/monthly usage,")
        lines.append("> remaining quota, requests per minute/day) is **Not Available from Source Code**.")
        lines.append("> Only static configuration values (max_tokens, temperature, etc.) can be determined.\n")

        agent_configs = [(a.name, a.token_config) for a in scanner.agents if a.token_config]
        if agent_configs:
            lines.append("### Configured Token Parameters\n")
            lines.append("| Agent | Parameter | Value |")
            lines.append("|-------|-----------|-------|")
            for agent_name, config in agent_configs[:20]:
                for k, v in config.items():
                    lines.append(f"| {agent_name} | {k} | {v} |")

        # File Inventory
        lines.append("\n## Complete File Inventory\n")
        lines.append("| # | Path | Language | Category | Purpose | Lines | AI Related |")
        lines.append("|---|------|----------|----------|---------|-------|------------|")
        for f in scanner.files:
            ai_str = "✓" if f.is_ai_related else ""
            lines.append(f"| {f.serial} | `{f.relative_path}` | {f.language} | {f.category} | {f.purpose} | {f.lines_of_code} | {ai_str} |")

        # Dependency Analysis
        lines.append("\n## Dependency Analysis\n")
        lines.append("### Files With Dependencies\n")
        lines.append("| File | Depends On |")
        lines.append("|------|-----------|")
        for src, deps in list(scanner.dependency_graph.items())[:30]:
            lines.append(f"| `{src}` | {', '.join(f'`{d}`' for d in deps[:3])} |")

        # Unused files
        unused = [f for f in scanner.files if f.is_referenced == "No" and f.is_used == "Unknown"
                  and f.category == "Source"]
        if unused:
            lines.append("\n### Potentially Unused Files\n")
            lines.append("| # | File | Category | Lines |")
            lines.append("|---|------|----------|-------|")
            for i, f in enumerate(unused[:20], 1):
                lines.append(f"| {i} | `{f.relative_path}` | {f.category} | {f.lines_of_code} |")

        lines.append("\n---")
        lines.append(f"\n*Report generated by AI Repository Audit Script on {s['scan_date']}*")

        md_content = "\n".join(lines)
        out_path = self.output_dir / "repository_summary.md"
        with open(out_path, "w", encoding="utf-8") as fh:
            fh.write(md_content)
        print(f"[✓] Markdown report: {out_path}")
        return md_content

    # ──────────────────────────────────────────────
    # HTML Dashboard Report
    # ──────────────────────────────────────────────
    def generate_html(self, md_content: str = ""):
        s = self.summary
        scanner = self.scanner

        # Prepare chart data
        lang_counter = Counter(f.language for f in scanner.files if f.language != "Unknown")
        top_langs = lang_counter.most_common(10)
        cat_counter = Counter(f.category for f in scanner.files)

        html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>AI Repository Audit - {s['repository_name']}</title>
<style>
{self._get_css()}
</style>
</head>
<body>
<div class="sidebar">
  <div class="sidebar-header">
    <div class="sidebar-logo">🔍</div>
    <div class="sidebar-title">AI Repo Audit</div>
  </div>
  <nav class="sidebar-nav">
    <a href="#overview" class="nav-item active">📊 Overview</a>
    <a href="#directory-tree" class="nav-item">📁 Directory Tree</a>
    <a href="#files" class="nav-item">📄 File Inventory</a>
    <a href="#agents" class="nav-item">🤖 AI Agents</a>
    <a href="#providers" class="nav-item">☁️ Providers</a>
    <a href="#models" class="nav-item">🧠 Models</a>
    <a href="#sdks" class="nav-item">🛠️ SDKs</a>
    <a href="#prompts" class="nav-item">💬 Prompts</a>
    <a href="#apikeys" class="nav-item">🔑 API Keys</a>
    <a href="#tools" class="nav-item">⚙️ Tools</a>
    <a href="#workflows" class="nav-item">🔄 Workflows</a>
    <a href="#tokens" class="nav-item">🪙 Tokens</a>
    <a href="#dependencies" class="nav-item">🕸️ Dependencies</a>
    <a href="#unused" class="nav-item">🗑️ Unused Files</a>
  </nav>
  <div class="sidebar-footer">
    <button class="btn-dark-mode" onclick="toggleDarkMode()">🌙 Dark Mode</button>
  </div>
</div>

<div class="main-content">
  <div class="top-bar">
    <div class="top-bar-title">
      <h1>🔍 AI Repository Audit</h1>
      <span class="repo-name">{s['repository_name']}</span>
    </div>
    <div class="top-bar-actions">
      <button class="btn btn-primary" onclick="window.print()">🖨️ Print</button>
      <button class="btn btn-success" onclick="exportTableCSV('files-table', 'files.csv')">⬇️ Export CSV</button>
      <button class="btn btn-info" onclick="window.location.href='repository_summary.json'">📄 JSON</button>
    </div>
  </div>

  <!-- Search Bar -->
  <div class="search-bar">
    <input type="text" id="global-search" placeholder="🔍 Search files, agents, models..." onkeyup="globalSearch(this.value)">
    <div class="search-filters">
      <select id="filter-category" onchange="filterTable()">
        <option value="">All Categories</option>
        {self._options_from_counter(cat_counter)}
      </select>
      <select id="filter-ai" onchange="filterTable()">
        <option value="">All Files</option>
        <option value="true">AI Related Only</option>
        <option value="false">Non-AI Only</option>
      </select>
      <select id="filter-language" onchange="filterTable()">
        <option value="">All Languages</option>
        {self._options_from_list([l for l, _ in top_langs])}
      </select>
    </div>
  </div>

  <!-- SECTION: Overview -->
  <section id="overview">
    <h2 class="section-title">📊 Repository Overview</h2>
    <div class="scan-info">
      <span>📂 <strong>{s['repository_root']}</strong></span>
      <span>📅 Scanned: <strong>{s['scan_date']}</strong></span>
    </div>

    <div class="stats-grid">
      {self._stat_card("📁", "Total Directories", s['total_directories'], "blue")}
      {self._stat_card("📄", "Total Files", s['total_files'], "blue")}
      {self._stat_card("💻", "Source Files", s['total_source_files'], "green")}
      {self._stat_card("⚙️", "Config Files", s['total_configuration_files'], "orange")}
      {self._stat_card("📚", "Documentation", s['total_documentation_files'], "purple")}
      {self._stat_card("🧪", "Test Files", s['total_test_files'], "teal")}
      {self._stat_card("🏗️", "Infrastructure", s['total_infrastructure_files'], "brown")}
      {self._stat_card("🤖", "AI Related Files", s['total_ai_related_files'], "red")}
    </div>

    <div class="stats-grid">
      {self._stat_card("🤖", "AI Agents", s['total_agents'], "red")}
      {self._stat_card("☁️", "Providers", s['total_providers'], "blue")}
      {self._stat_card("🧠", "Models", s['total_models'], "purple")}
      {self._stat_card("💬", "Prompts", s['total_prompts'], "orange")}
      {self._stat_card("🛠️", "SDKs", s['total_sdks'], "green")}
      {self._stat_card("⚙️", "Tools", s['total_tools'], "teal")}
      {self._stat_card("🔑", "API Keys", s['total_api_keys'], "brown")}
      {self._stat_card("🔄", "Workflows", s['total_workflows'], "indigo")}
    </div>

    <div class="stats-grid">
      {self._stat_card("🏛️", "Total Classes", s['total_classes'], "blue")}
      {self._stat_card("⚡", "Total Functions", s['total_functions'], "green")}
      {self._stat_card("🌐", "API Endpoints", s['total_endpoints'], "orange")}
      {self._stat_card("🧪", "Test Count", s['total_tests'], "red")}
    </div>

    <!-- Charts Row -->
    <div class="charts-row">
      <div class="chart-card">
        <h3>File Categories</h3>
        <canvas id="catChart"></canvas>
      </div>
      <div class="chart-card">
        <h3>Top Languages</h3>
        <canvas id="langChart"></canvas>
      </div>
      <div class="chart-card">
        <h3>AI Breakdown</h3>
        <canvas id="aiChart"></canvas>
      </div>
    </div>
  </section>

  <!-- SECTION: Directory Tree -->
  <section id="directory-tree">
    <h2 class="section-title">📁 Directory Tree</h2>
    <pre class="directory-tree">{self._escape_html(scanner.get_directory_tree())}</pre>
  </section>

  <!-- SECTION: File Inventory -->
  <section id="files">
    <h2 class="section-title">📄 File Inventory
      <span class="badge">{len(scanner.files)} files</span>
    </h2>
    <div class="table-controls">
      <button class="btn btn-sm" onclick="sortTable('files-table', 0)">Sort by #</button>
      <button class="btn btn-sm" onclick="sortTable('files-table', 5)">Sort by Category</button>
      <button class="btn btn-sm" onclick="sortTable('files-table', 12)">Sort by AI</button>
      <button class="btn btn-sm" onclick="sortTable('files-table', 9)">Sort by Lines</button>
    </div>
    <div class="table-container">
      <table id="files-table" class="data-table">
        <thead>
          <tr>
            <th>#</th>
            <th>Path</th>
            <th>File Name</th>
            <th>Extension</th>
            <th>Language</th>
            <th>Category</th>
            <th>Purpose</th>
            <th>Description</th>
            <th>Size</th>
            <th>Lines</th>
            <th>Used</th>
            <th>Referenced</th>
            <th>AI Related</th>
            <th>Dependencies</th>
          </tr>
        </thead>
        <tbody>
          {self._file_rows()}
        </tbody>
      </table>
    </div>
  </section>

  <!-- SECTION: AI Agents -->
  <section id="agents">
    <h2 class="section-title">🤖 AI Agents
      <span class="badge badge-red">{len(scanner.agents)} detected</span>
    </h2>
    {self._agents_section()}
  </section>

  <!-- SECTION: Providers -->
  <section id="providers">
    <h2 class="section-title">☁️ AI Providers
      <span class="badge badge-blue">{len(scanner.providers)} detected</span>
    </h2>
    {self._providers_section()}
  </section>

  <!-- SECTION: Models -->
  <section id="models">
    <h2 class="section-title">🧠 AI Models
      <span class="badge badge-purple">{len(scanner.models)} detected</span>
    </h2>
    {self._models_section()}
  </section>

  <!-- SECTION: SDKs -->
  <section id="sdks">
    <h2 class="section-title">🛠️ AI SDKs & Frameworks
      <span class="badge badge-green">{len(scanner.sdks)} detected</span>
    </h2>
    {self._sdks_section()}
  </section>

  <!-- SECTION: Prompts -->
  <section id="prompts">
    <h2 class="section-title">💬 Prompt Inventory
      <span class="badge badge-orange">{len(scanner.prompts)} detected</span>
    </h2>
    {self._prompts_section()}
  </section>

  <!-- SECTION: API Keys -->
  <section id="apikeys">
    <h2 class="section-title">🔑 API Keys & Environment Variables
      <span class="badge badge-red">{len(scanner.api_keys)} detected</span>
    </h2>
    {self._api_keys_section()}
  </section>

  <!-- SECTION: Tools -->
  <section id="tools">
    <h2 class="section-title">⚙️ Agent Tools
      <span class="badge">{len(scanner.tools)} types</span>
    </h2>
    {self._tools_section()}
  </section>

  <!-- SECTION: Workflows -->
  <section id="workflows">
    <h2 class="section-title">🔄 Workflow Patterns
      <span class="badge">{len(scanner.workflows)} detected</span>
    </h2>
    {self._workflows_section()}
  </section>

  <!-- SECTION: Token Usage -->
  <section id="tokens">
    <h2 class="section-title">🪙 Token & Request Usage</h2>
    <div class="info-box warning">
      ⚠️ <strong>Runtime metrics are Not Available from Source Code.</strong>
      Current token usage, daily/monthly quotas, remaining capacity, and request rates
      can only be determined at runtime by querying the provider APIs.
      Only static configuration values (max_tokens, temperature, etc.) from source code are shown below.
    </div>
    {self._tokens_section()}
  </section>

  <!-- SECTION: Dependencies -->
  <section id="dependencies">
    <h2 class="section-title">🕸️ Dependency Analysis</h2>
    {self._dependencies_section()}
  </section>

  <!-- SECTION: Unused Files -->
  <section id="unused">
    <h2 class="section-title">🗑️ Potentially Unused Files</h2>
    {self._unused_section()}
  </section>

  <footer class="footer">
    <p>AI Repository Audit Report | Generated: {s['scan_date']} | Repository: {s['repository_name']}</p>
  </footer>
</div>

<script>
{self._get_javascript(s, cat_counter, lang_counter, top_langs)}
</script>
</body>
</html>"""

        out_path = self.output_dir / "repository_summary.html"
        with open(out_path, "w", encoding="utf-8") as fh:
            fh.write(html)
        print(f"[✓] HTML dashboard: {out_path}")
        return out_path

    # ──────────────────────────────────────────────
    # HTML Section Builders
    # ──────────────────────────────────────────────
    def _stat_card(self, icon: str, label: str, value, color: str = "blue") -> str:
        return f"""
      <div class="stat-card stat-{color}">
        <div class="stat-icon">{icon}</div>
        <div class="stat-value">{value:,}" if isinstance(value, int) else f"{value}</div>
        <div class="stat-label">{label}</div>
      </div>"""

    def _stat_card(self, icon: str, label: str, value, color: str = "blue") -> str:
        val_str = f"{value:,}" if isinstance(value, int) else str(value)
        return f"""
      <div class="stat-card stat-{color}">
        <div class="stat-icon">{icon}</div>
        <div class="stat-value">{val_str}</div>
        <div class="stat-label">{label}</div>
      </div>"""

    def _file_rows(self) -> str:
        rows = []
        for f in self.scanner.files:
            ai_badge = '<span class="badge badge-red">AI</span>' if f.is_ai_related else ""
            cat_class = f"cat-{f.category.lower().replace(' ', '-')}"
            deps_str = ", ".join(f.dependencies[:3])
            row = f"""
          <tr class="{'ai-row' if f.is_ai_related else ''}"
              data-category="{self._escape_html(f.category)}"
              data-ai="{str(f.is_ai_related).lower()}"
              data-language="{self._escape_html(f.language)}">
            <td>{f.serial}</td>
            <td><span class="path-text" title="{self._escape_html(f.relative_path)}">{self._escape_html(f.relative_path)}</span></td>
            <td><strong>{self._escape_html(f.file_name)}</strong></td>
            <td><code>{self._escape_html(f.extension)}</code></td>
            <td><span class="lang-badge">{self._escape_html(f.language)}</span></td>
            <td><span class="cat-badge {cat_class}">{self._escape_html(f.category)}</span></td>
            <td>{self._escape_html(f.purpose)}</td>
            <td class="description-cell" title="{self._escape_html(f.description)}">{self._escape_html(f.description[:80])}</td>
            <td>{self._format_size(f.size_bytes)}</td>
            <td>{f.lines_of_code:,}</td>
            <td><span class="status-{f.is_used.lower().replace(' ', '-')}">{f.is_used}</span></td>
            <td>{f.is_referenced}</td>
            <td>{ai_badge}</td>
            <td class="deps-cell">{self._escape_html(deps_str)}</td>
          </tr>"""
            rows.append(row)
        return "\n".join(rows)

    def _agents_section(self) -> str:
        if not self.scanner.agents:
            return '<div class="empty-state">No AI agents detected in this repository.</div>'

        seen = set()
        rows = []
        i = 1
        for a in self.scanner.agents:
            key = f"{a.file}:{a.name}:{a.line_number}"
            if key in seen:
                continue
            seen.add(key)

            tools_badges = "".join(f'<span class="tool-badge">{t}</span>' for t in a.tools[:3])
            wf_badges = "".join(f'<span class="wf-badge">{w}</span>' for w in a.workflows[:3])
            tc_str = ", ".join(f"{k}: {v}" for k, v in a.token_config.items()) if a.token_config else "Not specified"

            rows.append(f"""
          <tr>
            <td>{i}</td>
            <td><strong>{self._escape_html(a.name)}</strong></td>
            <td><code class="file-path">{self._escape_html(a.file)}</code></td>
            <td><span class="type-badge">{self._escape_html(a.agent_type)}</span></td>
            <td>{self._escape_html(a.purpose)}</td>
            <td><span class="provider-badge">{self._escape_html(a.provider)}</span></td>
            <td>{self._escape_html(a.sdk)}</td>
            <td><code class="model-name">{self._escape_html(a.model)}</code></td>
            <td>{tools_badges if tools_badges else "None"}</td>
            <td>{wf_badges if wf_badges else "None"}</td>
            <td class="token-config">{self._escape_html(tc_str)}</td>
            <td>{a.line_number}</td>
          </tr>""")
            i += 1

        return f"""
      <div class="table-container">
        <table class="data-table">
          <thead>
            <tr>
              <th>#</th><th>Agent Name</th><th>File</th><th>Type</th><th>Purpose</th>
              <th>Provider</th><th>SDK</th><th>Model</th><th>Tools</th><th>Workflows</th>
              <th>Token Config</th><th>Line #</th>
            </tr>
          </thead>
          <tbody>{"".join(rows)}</tbody>
        </table>
      </div>"""

    def _providers_section(self) -> str:
        if not self.scanner.providers:
            return '<div class="empty-state">No AI providers detected.</div>'

        cards = []
        for name, pr in self.scanner.providers.items():
            env_html = "".join(f'<code class="env-var">{ev}</code>' for ev in pr.env_vars[:5])
            files_html = "".join(f'<div class="file-item">{f}</div>' for f in pr.files[:5])
            more = f'<div class="more-indicator">+{len(pr.files)-5} more</div>' if len(pr.files) > 5 else ""
            cards.append(f"""
          <div class="provider-card">
            <div class="provider-header">
              <span class="provider-name">{self._escape_html(pr.name)}</span>
              <span class="file-count">{len(pr.files)} files</span>
            </div>
            <div class="provider-details">
              <div><strong>SDK:</strong> {self._escape_html(pr.sdk)}</div>
              <div><strong>Auth:</strong> {pr.auth_method or "API Key"}</div>
              <div><strong>Endpoint:</strong> {self._escape_html(pr.endpoint) if pr.endpoint else "Default"}</div>
              <div><strong>API Version:</strong> {pr.api_version or "Not Specified"}</div>
            </div>
            <div class="provider-env">
              <strong>Environment Variables:</strong><br>
              {env_html if env_html else '<span class="na">None detected</span>'}
            </div>
            <div class="provider-files">
              <strong>Files ({len(pr.files)}):</strong>
              {files_html}{more}
            </div>
          </div>""")

        return f'<div class="provider-grid">{"".join(cards)}</div>'

    def _models_section(self) -> str:
        if not self.scanner.models:
            return '<div class="empty-state">No AI models detected.</div>'

        rows = []
        sorted_models = sorted(self.scanner.models.items(), key=lambda x: -x[1].reference_count)
        for i, (name, mr) in enumerate(sorted_models, 1):
            files_str = ", ".join(mr.files[:2])
            rows.append(f"""
          <tr>
            <td>{i}</td>
            <td><code class="model-name">{self._escape_html(mr.name)}</code></td>
            <td>{self._escape_html(mr.version) if mr.version else "Latest"}</td>
            <td><span class="provider-badge">{self._escape_html(mr.provider)}</span></td>
            <td>{len(mr.files)}</td>
            <td>{mr.reference_count}</td>
            <td class="description-cell" title="{self._escape_html(', '.join(mr.files))}">{self._escape_html(files_str[:80])}</td>
          </tr>""")

        return f"""
      <div class="table-container">
        <table class="data-table">
          <thead>
            <tr><th>#</th><th>Model</th><th>Version</th><th>Provider</th><th>Files</th><th>References</th><th>Example Files</th></tr>
          </thead>
          <tbody>{"".join(rows)}</tbody>
        </table>
      </div>"""

    def _sdks_section(self) -> str:
        if not self.scanner.sdks:
            return '<div class="empty-state">No AI SDKs detected.</div>'

        rows = []
        sorted_sdks = sorted(self.scanner.sdks.items(), key=lambda x: -x[1].import_count)
        for i, (name, sr) in enumerate(sorted_sdks, 1):
            files_str = ", ".join(sr.files[:2])
            rows.append(f"""
          <tr>
            <td>{i}</td>
            <td><strong>{self._escape_html(sr.name)}</strong></td>
            <td>{sr.version}</td>
            <td>{len(sr.files)}</td>
            <td>{sr.import_count}</td>
            <td class="description-cell">{self._escape_html(files_str[:100])}</td>
          </tr>""")

        return f"""
      <div class="table-container">
        <table class="data-table">
          <thead>
            <tr><th>#</th><th>SDK / Framework</th><th>Version</th><th>Files Using</th><th>Import Count</th><th>Example Files</th></tr>
          </thead>
          <tbody>{"".join(rows)}</tbody>
        </table>
      </div>"""

    def _prompts_section(self) -> str:
        if not self.scanner.prompts:
            return '<div class="empty-state">No prompts detected.</div>'

        rows = []
        for i, pr in enumerate(self.scanner.prompts[:100], 1):
            rows.append(f"""
          <tr>
            <td>{i}</td>
            <td><span class="prompt-type-badge">{self._escape_html(pr.prompt_type)}</span></td>
            <td><code>{self._escape_html(pr.location)}</code></td>
            <td>{pr.line_number}</td>
            <td>{self._escape_html(pr.purpose)}</td>
            <td>{self._escape_html(pr.agent)}</td>
            <td class="description-cell" title="{self._escape_html(pr.content_preview)}">{self._escape_html(pr.content_preview[:80])}</td>
          </tr>""")

        return f"""
      <div class="table-container">
        <table class="data-table">
          <thead>
            <tr><th>#</th><th>Type</th><th>Location</th><th>Line #</th><th>Purpose</th><th>Agent</th><th>Preview</th></tr>
          </thead>
          <tbody>{"".join(rows)}</tbody>
        </table>
      </div>"""

    def _api_keys_section(self) -> str:
        if not self.scanner.api_keys:
            return '<div class="empty-state">No API keys or environment variables detected.</div>'

        rows = []
        for i, (name, kr) in enumerate(self.scanner.api_keys.items(), 1):
            files_str = ", ".join(kr.used_in[:3])
            rows.append(f"""
          <tr>
            <td>{i}</td>
            <td><code class="env-var-display">{self._escape_html(kr.variable_name)}</code></td>
            <td><span class="provider-badge">{self._escape_html(kr.provider)}</span></td>
            <td>{self._escape_html(kr.loaded_from)}</td>
            <td>{len(kr.used_in)}</td>
            <td class="description-cell">{self._escape_html(files_str[:100])}</td>
          </tr>""")

        return f"""
      <div class="info-box info">
        ℹ️ These are environment variable <strong>references</strong> found in source code.
        Actual values are never stored in the audit. Always use secure secret management.
      </div>
      <div class="table-container">
        <table class="data-table">
          <thead>
            <tr><th>#</th><th>Variable Name</th><th>Provider</th><th>Loaded From</th><th>Used In (Files)</th><th>Example Files</th></tr>
          </thead>
          <tbody>{"".join(rows)}</tbody>
        </table>
      </div>"""

    def _tools_section(self) -> str:
        if not self.scanner.tools:
            return '<div class="empty-state">No agent tools detected.</div>'

        cards = []
        for name, tr in self.scanner.tools.items():
            cards.append(f"""
          <div class="tool-card">
            <div class="tool-name">{self._escape_html(tr.name)}</div>
            <div class="tool-count">{len(tr.files)} file(s)</div>
          </div>""")

        return f'<div class="tool-grid">{"".join(cards)}</div>'

    def _workflows_section(self) -> str:
        if not self.scanner.workflows:
            return '<div class="empty-state">No workflow patterns detected.</div>'

        cards = []
        for name, wr in self.scanner.workflows.items():
            cards.append(f"""
          <div class="workflow-card">
            <div class="workflow-name">🔄 {self._escape_html(wr.name)}</div>
            <div class="workflow-count">{len(wr.files)} file(s)</div>
          </div>""")

        return f'<div class="workflow-grid">{"".join(cards)}</div>'

    def _tokens_section(self) -> str:
        agent_configs = [(a.name, a.file, a.model, a.token_config)
                         for a in self.scanner.agents if a.token_config]

        if not agent_configs:
            return '<div class="info-box info">No static token configuration found in source code.</div>'

        rows = []
        for agent_name, agent_file, model, config in agent_configs[:50]:
            for k, v in config.items():
                rows.append(f"""
          <tr>
            <td>{self._escape_html(agent_name)}</td>
            <td><code>{self._escape_html(agent_file)}</code></td>
            <td><code>{self._escape_html(model)}</code></td>
            <td>{self._escape_html(k)}</td>
            <td><strong>{self._escape_html(v)}</strong></td>
            <td><span class="na-text">Not Available from Source Code</span></td>
            <td><span class="na-text">Not Available from Source Code</span></td>
          </tr>""")

        return f"""
      <div class="table-container">
        <table class="data-table">
          <thead>
            <tr>
              <th>Agent</th><th>File</th><th>Model</th><th>Parameter</th><th>Configured Value</th>
              <th>Runtime Usage</th><th>Remaining</th>
            </tr>
          </thead>
          <tbody>{"".join(rows)}</tbody>
        </table>
      </div>"""

    def _dependencies_section(self) -> str:
        graph = self.scanner.dependency_graph
        if not graph:
            return '<div class="empty-state">No dependencies could be resolved from static analysis.</div>'

        rows = []
        for src, deps in list(graph.items())[:50]:
            deps_html = " ".join(f'<code class="dep-badge">{self._escape_html(d)}</code>' for d in deps[:5])
            rows.append(f"""
          <tr>
            <td><code>{self._escape_html(src)}</code></td>
            <td>{deps_html}</td>
            <td>{len(deps)}</td>
          </tr>""")

        return f"""
      <div class="table-container">
        <table class="data-table">
          <thead>
            <tr><th>Source File</th><th>Depends On</th><th>Dependency Count</th></tr>
          </thead>
          <tbody>{"".join(rows)}</tbody>
        </table>
      </div>"""

    def _unused_section(self) -> str:
        unused = [f for f in self.scanner.files
                  if f.is_referenced == "No" and f.is_used == "Unknown"
                  and f.category in ("Source", "AI")]

        if not unused:
            return '<div class="info-box success">No obviously unused source files detected.</div>'

        rows = []
        for i, f in enumerate(unused[:50], 1):
            rows.append(f"""
          <tr>
            <td>{i}</td>
            <td><code>{self._escape_html(f.relative_path)}</code></td>
            <td>{self._escape_html(f.language)}</td>
            <td>{self._escape_html(f.category)}</td>
            <td>{f.lines_of_code:,}</td>
            <td>{self._format_size(f.size_bytes)}</td>
          </tr>""")

        return f"""
      <div class="info-box warning">
        ⚠️ These files have no detected imports from other files and may be unused.
        Verify manually before removing.
      </div>
      <div class="table-container">
        <table class="data-table">
          <thead>
            <tr><th>#</th><th>File</th><th>Language</th><th>Category</th><th>Lines</th><th>Size</th></tr>
          </thead>
          <tbody>{"".join(rows)}</tbody>
        </table>
      </div>"""

    # ──────────────────────────────────────────────
    # Helpers
    # ──────────────────────────────────────────────
    def _escape_html(self, text: str) -> str:
        if not isinstance(text, str):
            text = str(text)
        return (text.replace("&", "&amp;").replace("<", "&lt;")
                .replace(">", "&gt;").replace('"', "&quot;"))

    def _format_size(self, size_bytes: int) -> str:
        if size_bytes < 1024:
            return f"{size_bytes} B"
        elif size_bytes < 1024 * 1024:
            return f"{size_bytes / 1024:.1f} KB"
        else:
            return f"{size_bytes / (1024*1024):.1f} MB"

    def _options_from_counter(self, counter: Counter) -> str:
        return "\n".join(f'<option value="{k}">{k} ({v})</option>'
                         for k, v in counter.most_common())

    def _options_from_list(self, items: list) -> str:
        return "\n".join(f'<option value="{item}">{item}</option>' for item in items)

    # ──────────────────────────────────────────────
    # CSS
    # ──────────────────────────────────────────────
    def _get_css(self) -> str:
        return """
/* === Reset & Variables === */
*, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
:root {
  --bg: #f0f2f5;
  --surface: #ffffff;
  --sidebar-bg: #1a1d2e;
  --sidebar-text: #c8d0e7;
  --sidebar-active: #6c63ff;
  --text: #1a1a2e;
  --text-secondary: #555577;
  --border: #e0e4ef;
  --accent-blue: #4361ee;
  --accent-green: #2ec4b6;
  --accent-red: #e63946;
  --accent-orange: #f77f00;
  --accent-purple: #7209b7;
  --accent-teal: #06a77d;
  --accent-brown: #8d5524;
  --accent-indigo: #3d348b;
  --card-shadow: 0 4px 20px rgba(0,0,0,0.08);
  --radius: 12px;
  --font: 'Segoe UI', -apple-system, BlinkMacSystemFont, sans-serif;
  --mono: 'Cascadia Code', 'Fira Code', 'Consolas', monospace;
}
.dark-mode {
  --bg: #0d0f1a;
  --surface: #1a1d2e;
  --text: #e0e4ff;
  --text-secondary: #8892b0;
  --border: #2d3050;
  --card-shadow: 0 4px 20px rgba(0,0,0,0.4);
}

/* === Layout === */
body { font-family: var(--font); background: var(--bg); color: var(--text);
       display: flex; min-height: 100vh; transition: background 0.3s, color 0.3s; }

.sidebar {
  width: 260px; min-height: 100vh; background: var(--sidebar-bg);
  position: fixed; left: 0; top: 0; bottom: 0; display: flex;
  flex-direction: column; z-index: 100; overflow-y: auto;
}
.sidebar-header { padding: 24px 20px; border-bottom: 1px solid rgba(255,255,255,0.1); }
.sidebar-logo { font-size: 32px; margin-bottom: 8px; }
.sidebar-title { color: #ffffff; font-size: 14px; font-weight: 700; letter-spacing: 1px; text-transform: uppercase; }
.sidebar-nav { flex: 1; padding: 16px 0; }
.nav-item {
  display: block; padding: 12px 20px; color: var(--sidebar-text);
  text-decoration: none; font-size: 13px; font-weight: 500;
  border-left: 3px solid transparent; transition: all 0.2s;
}
.nav-item:hover, .nav-item.active {
  background: rgba(108,99,255,0.2); color: #ffffff;
  border-left-color: var(--sidebar-active);
}
.sidebar-footer { padding: 16px 20px; border-top: 1px solid rgba(255,255,255,0.1); }

.main-content { margin-left: 260px; flex: 1; padding: 24px; max-width: calc(100vw - 260px); }

/* === Top Bar === */
.top-bar {
  display: flex; justify-content: space-between; align-items: center;
  margin-bottom: 24px; padding: 16px 24px; background: var(--surface);
  border-radius: var(--radius); box-shadow: var(--card-shadow);
}
.top-bar-title h1 { font-size: 22px; color: var(--accent-blue); }
.repo-name { font-size: 13px; color: var(--text-secondary); margin-left: 8px; }
.top-bar-actions { display: flex; gap: 8px; }

/* === Buttons === */
.btn {
  padding: 8px 16px; border: none; border-radius: 8px; cursor: pointer;
  font-size: 13px; font-weight: 600; transition: all 0.2s; text-decoration: none;
}
.btn-primary { background: var(--accent-blue); color: white; }
.btn-success { background: var(--accent-green); color: white; }
.btn-info { background: var(--accent-purple); color: white; }
.btn-sm { padding: 5px 10px; font-size: 12px; background: var(--bg); border: 1px solid var(--border); color: var(--text); }
.btn-sm:hover { background: var(--accent-blue); color: white; }
.btn-dark-mode { width: 100%; padding: 10px; background: rgba(255,255,255,0.1); color: white;
                  border: 1px solid rgba(255,255,255,0.2); border-radius: 8px; cursor: pointer; font-size: 13px; }
.btn:hover { opacity: 0.85; transform: translateY(-1px); }

/* === Search Bar === */
.search-bar {
  background: var(--surface); padding: 16px; border-radius: var(--radius);
  box-shadow: var(--card-shadow); margin-bottom: 24px; display: flex; gap: 12px; flex-wrap: wrap;
}
.search-bar input {
  flex: 1; min-width: 200px; padding: 10px 16px; border: 2px solid var(--border);
  border-radius: 8px; font-size: 14px; background: var(--bg); color: var(--text);
}
.search-bar input:focus { outline: none; border-color: var(--accent-blue); }
.search-filters { display: flex; gap: 8px; flex-wrap: wrap; }
.search-filters select {
  padding: 8px 12px; border: 1px solid var(--border); border-radius: 8px;
  background: var(--bg); color: var(--text); font-size: 13px;
}

/* === Stats Grid === */
.stats-grid {
  display: grid; grid-template-columns: repeat(auto-fill, minmax(160px, 1fr));
  gap: 16px; margin-bottom: 16px;
}
.stat-card {
  background: var(--surface); border-radius: var(--radius); padding: 20px;
  box-shadow: var(--card-shadow); text-align: center; border-top: 4px solid;
  transition: transform 0.2s, box-shadow 0.2s;
}
.stat-card:hover { transform: translateY(-3px); box-shadow: 0 8px 30px rgba(0,0,0,0.12); }
.stat-icon { font-size: 28px; margin-bottom: 8px; }
.stat-value { font-size: 26px; font-weight: 800; margin-bottom: 4px; }
.stat-label { font-size: 11px; color: var(--text-secondary); font-weight: 600; text-transform: uppercase; letter-spacing: 0.5px; }
.stat-blue { border-color: var(--accent-blue); } .stat-blue .stat-value { color: var(--accent-blue); }
.stat-green { border-color: var(--accent-green); } .stat-green .stat-value { color: var(--accent-green); }
.stat-red { border-color: var(--accent-red); } .stat-red .stat-value { color: var(--accent-red); }
.stat-orange { border-color: var(--accent-orange); } .stat-orange .stat-value { color: var(--accent-orange); }
.stat-purple { border-color: var(--accent-purple); } .stat-purple .stat-value { color: var(--accent-purple); }
.stat-teal { border-color: var(--accent-teal); } .stat-teal .stat-value { color: var(--accent-teal); }
.stat-brown { border-color: var(--accent-brown); } .stat-brown .stat-value { color: var(--accent-brown); }
.stat-indigo { border-color: var(--accent-indigo); } .stat-indigo .stat-value { color: var(--accent-indigo); }

/* === Charts === */
.charts-row { display: grid; grid-template-columns: repeat(auto-fill, minmax(280px, 1fr)); gap: 16px; margin-top: 16px; }
.chart-card {
  background: var(--surface); border-radius: var(--radius); padding: 20px;
  box-shadow: var(--card-shadow);
}
.chart-card h3 { font-size: 14px; margin-bottom: 16px; color: var(--text-secondary); text-transform: uppercase; }
canvas { max-height: 200px; }

/* === Sections === */
section { margin-bottom: 40px; scroll-margin-top: 20px; }
.section-title {
  font-size: 20px; font-weight: 700; color: var(--text); margin-bottom: 16px;
  display: flex; align-items: center; gap: 12px;
  padding-bottom: 10px; border-bottom: 2px solid var(--border);
}
.scan-info {
  display: flex; gap: 24px; flex-wrap: wrap; padding: 12px 16px;
  background: var(--bg); border-radius: 8px; margin-bottom: 16px;
  font-size: 13px; color: var(--text-secondary);
}

/* === Badges === */
.badge {
  display: inline-flex; align-items: center; padding: 3px 10px;
  border-radius: 20px; font-size: 12px; font-weight: 600;
  background: var(--accent-blue); color: white;
}
.badge-red { background: var(--accent-red); }
.badge-blue { background: var(--accent-blue); }
.badge-green { background: var(--accent-green); }
.badge-purple { background: var(--accent-purple); }
.badge-orange { background: var(--accent-orange); }
.lang-badge { background: #e8f0fe; color: var(--accent-blue); padding: 2px 8px; border-radius: 4px; font-size: 11px; font-weight: 600; }
.cat-badge { padding: 2px 8px; border-radius: 4px; font-size: 11px; font-weight: 600; }
.cat-ai { background: #fce4ec; color: #c62828; }
.cat-source { background: #e8f5e9; color: #2e7d32; }
.cat-test { background: #fff9c4; color: #f57f17; }
.cat-configuration { background: #f3e5f5; color: #6a1b9a; }
.cat-documentation { background: #e3f2fd; color: #1565c0; }
.cat-infrastructure { background: #fbe9e7; color: #bf360c; }
.type-badge { background: #ede7f6; color: #4527a0; padding: 2px 8px; border-radius: 4px; font-size: 11px; }
.provider-badge { background: #e1f5fe; color: #01579b; padding: 2px 8px; border-radius: 4px; font-size: 11px; font-weight: 600; }
.prompt-type-badge { background: #fff3e0; color: #e65100; padding: 2px 8px; border-radius: 4px; font-size: 11px; }
.tool-badge { background: #e8f5e9; color: #2e7d32; padding: 2px 6px; border-radius: 4px; font-size: 10px; margin: 1px; display: inline-block; }
.wf-badge { background: #e3f2fd; color: #0d47a1; padding: 2px 6px; border-radius: 4px; font-size: 10px; margin: 1px; display: inline-block; }
.dep-badge { background: #fafafa; border: 1px solid var(--border); padding: 1px 6px; border-radius: 4px; font-size: 10px; margin: 2px; }

/* === Tables === */
.table-container { overflow-x: auto; border-radius: var(--radius); box-shadow: var(--card-shadow); }
.data-table { width: 100%; border-collapse: collapse; background: var(--surface); font-size: 13px; }
.data-table thead { position: sticky; top: 0; z-index: 10; }
.data-table th {
  background: linear-gradient(135deg, #1a1d2e, #2d3250);
  color: #ffffff; padding: 12px 14px; text-align: left;
  font-size: 11px; text-transform: uppercase; letter-spacing: 0.5px;
  white-space: nowrap; cursor: pointer;
}
.data-table th:hover { background: #3d4172; }
.data-table td { padding: 10px 14px; border-bottom: 1px solid var(--border); vertical-align: middle; }
.data-table tbody tr:hover { background: rgba(67,97,238,0.05); }
.data-table tbody tr.ai-row { background: rgba(230,57,70,0.04); }
.data-table tbody tr.hidden { display: none; }
.path-text { font-family: var(--mono); font-size: 11px; color: var(--text-secondary);
             max-width: 250px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; display: block; }
.file-path { font-family: var(--mono); font-size: 11px; color: var(--accent-blue); }
.model-name { font-family: var(--mono); font-size: 11px; color: var(--accent-purple); }
.description-cell { max-width: 200px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; color: var(--text-secondary); font-size: 12px; }
.deps-cell { font-family: var(--mono); font-size: 10px; color: var(--text-secondary); max-width: 180px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.token-config { font-family: var(--mono); font-size: 10px; max-width: 150px; }
.status-yes { color: var(--accent-green); font-weight: 600; }
.status-no { color: var(--accent-red); }
.status-likely { color: var(--accent-orange); font-weight: 600; }
.status-unknown { color: var(--text-secondary); }
.na-text { color: var(--text-secondary); font-style: italic; font-size: 11px; }
.env-var { background: #fff8e1; color: #e65100; padding: 1px 6px; border-radius: 3px; font-size: 11px; margin: 2px; display: inline-block; }
.env-var-display { background: #ffebee; color: #c62828; padding: 2px 8px; border-radius: 4px; font-size: 12px; }

/* === Table Controls === */
.table-controls { display: flex; gap: 8px; flex-wrap: wrap; margin-bottom: 12px; }

/* === Directory Tree === */
.directory-tree {
  background: var(--sidebar-bg); color: #a8b2d8; padding: 24px;
  border-radius: var(--radius); font-family: var(--mono); font-size: 13px;
  line-height: 1.8; overflow-x: auto; max-height: 500px; box-shadow: var(--card-shadow);
}

/* === Provider Cards === */
.provider-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(300px, 1fr)); gap: 16px; }
.provider-card {
  background: var(--surface); border-radius: var(--radius); padding: 20px;
  box-shadow: var(--card-shadow); border-left: 4px solid var(--accent-blue);
}
.provider-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px; }
.provider-name { font-size: 16px; font-weight: 700; color: var(--accent-blue); }
.file-count { background: var(--bg); padding: 3px 8px; border-radius: 12px; font-size: 12px; }
.provider-details { display: grid; grid-template-columns: 1fr 1fr; gap: 6px; font-size: 12px; margin-bottom: 12px; color: var(--text-secondary); }
.provider-env, .provider-files { margin-top: 8px; font-size: 12px; }
.file-item { font-family: var(--mono); font-size: 11px; color: var(--text-secondary); padding: 2px 0; }
.more-indicator { color: var(--accent-blue); font-size: 11px; font-style: italic; }

/* === Tool Grid === */
.tool-grid { display: flex; flex-wrap: wrap; gap: 12px; }
.tool-card {
  background: var(--surface); border-radius: 10px; padding: 14px 18px;
  box-shadow: var(--card-shadow); border-top: 3px solid var(--accent-green);
  min-width: 140px; text-align: center;
}
.tool-name { font-weight: 700; margin-bottom: 4px; }
.tool-count { font-size: 12px; color: var(--text-secondary); }

/* === Workflow Grid === */
.workflow-grid { display: flex; flex-wrap: wrap; gap: 12px; }
.workflow-card {
  background: var(--surface); border-radius: 10px; padding: 14px 18px;
  box-shadow: var(--card-shadow); border-top: 3px solid var(--accent-blue);
  min-width: 160px;
}
.workflow-name { font-weight: 700; margin-bottom: 4px; }
.workflow-count { font-size: 12px; color: var(--text-secondary); }

/* === Info Boxes === */
.info-box {
  padding: 14px 18px; border-radius: 10px; margin-bottom: 16px;
  font-size: 13px; line-height: 1.6; border-left: 4px solid;
}
.info-box.info { background: #e3f2fd; color: #0d47a1; border-color: #2196f3; }
.info-box.warning { background: #fff8e1; color: #7c4400; border-color: #ff9800; }
.info-box.success { background: #e8f5e9; color: #1b5e20; border-color: #4caf50; }

/* === Empty State === */
.empty-state { padding: 40px; text-align: center; color: var(--text-secondary); font-size: 14px;
               background: var(--surface); border-radius: var(--radius); box-shadow: var(--card-shadow); }

/* === Footer === */
.footer { margin-top: 40px; padding: 20px; text-align: center; color: var(--text-secondary);
          font-size: 12px; border-top: 1px solid var(--border); }

/* === Responsive === */
@media (max-width: 768px) {
  .sidebar { width: 0; overflow: hidden; }
  .main-content { margin-left: 0; max-width: 100vw; padding: 16px; }
  .stats-grid { grid-template-columns: repeat(2, 1fr); }
}

/* === Print === */
@media print {
  .sidebar, .top-bar-actions, .search-bar, .table-controls { display: none !important; }
  .main-content { margin-left: 0; }
  section { page-break-inside: avoid; }
}
"""

    # ──────────────────────────────────────────────
    # JavaScript
    # ──────────────────────────────────────────────
    def _get_javascript(self, s: dict, cat_counter: Counter, lang_counter: Counter, top_langs: list) -> str:
        cat_labels = json.dumps([k for k, v in cat_counter.most_common(8)])
        cat_values = json.dumps([v for k, v in cat_counter.most_common(8)])
        lang_labels = json.dumps([k for k, _ in top_langs])
        lang_values = json.dumps([v for _, v in top_langs])
        ai_count = sum(1 for f in self.scanner.files if f.is_ai_related)
        non_ai_count = len(self.scanner.files) - ai_count

        return f"""
// ── Dark Mode ──────────────────────────────────
function toggleDarkMode() {{
  document.body.classList.toggle('dark-mode');
  localStorage.setItem('darkMode', document.body.classList.contains('dark-mode'));
}}
if (localStorage.getItem('darkMode') === 'true') document.body.classList.add('dark-mode');

// ── Sidebar Active Link ─────────────────────────
const sections = document.querySelectorAll('section[id]');
const navItems = document.querySelectorAll('.nav-item');
window.addEventListener('scroll', () => {{
  let current = '';
  sections.forEach(s => {{
    if (window.scrollY >= s.offsetTop - 80) current = s.id;
  }});
  navItems.forEach(item => {{
    item.classList.remove('active');
    if (item.getAttribute('href') === '#' + current) item.classList.add('active');
  }});
}});

// ── Global Search ───────────────────────────────
function globalSearch(query) {{
  const q = query.toLowerCase();
  const rows = document.querySelectorAll('#files-table tbody tr');
  rows.forEach(row => {{
    const text = row.textContent.toLowerCase();
    row.classList.toggle('hidden', q.length > 0 && !text.includes(q));
  }});
}}

// ── Filter Table ────────────────────────────────
function filterTable() {{
  const cat = document.getElementById('filter-category').value.toLowerCase();
  const ai = document.getElementById('filter-ai').value.toLowerCase();
  const lang = document.getElementById('filter-language').value.toLowerCase();
  const rows = document.querySelectorAll('#files-table tbody tr');
  rows.forEach(row => {{
    const rowCat = (row.dataset.category || '').toLowerCase();
    const rowAi = (row.dataset.ai || '').toLowerCase();
    const rowLang = (row.dataset.language || '').toLowerCase();
    let show = true;
    if (cat && rowCat !== cat) show = false;
    if (ai && rowAi !== ai) show = false;
    if (lang && rowLang !== lang) show = false;
    row.classList.toggle('hidden', !show);
  }});
}}

// ── Sort Table ──────────────────────────────────
let sortState = {{}};
function sortTable(tableId, colIndex) {{
  const table = document.getElementById(tableId);
  if (!table) return;
  const tbody = table.querySelector('tbody');
  const rows = Array.from(tbody.querySelectorAll('tr'));
  const asc = !sortState[tableId + colIndex];
  sortState[tableId + colIndex] = asc;
  rows.sort((a, b) => {{
    const aVal = a.cells[colIndex]?.textContent.trim() || '';
    const bVal = b.cells[colIndex]?.textContent.trim() || '';
    const aNum = parseFloat(aVal.replace(/[^0-9.-]/g, ''));
    const bNum = parseFloat(bVal.replace(/[^0-9.-]/g, ''));
    if (!isNaN(aNum) && !isNaN(bNum)) return asc ? aNum - bNum : bNum - aNum;
    return asc ? aVal.localeCompare(bVal) : bVal.localeCompare(aVal);
  }});
  rows.forEach(r => tbody.appendChild(r));
}}

// ── Export CSV ──────────────────────────────────
function exportTableCSV(tableId, filename) {{
  const table = document.getElementById(tableId);
  if (!table) return;
  const rows = Array.from(table.querySelectorAll('tr'));
  const csv = rows.map(row =>
    Array.from(row.querySelectorAll('th,td'))
      .map(cell => '"' + cell.textContent.replace(/"/g, '""').trim() + '"')
      .join(',')
  ).join('\\n');
  const blob = new Blob([csv], {{type: 'text/csv'}});
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url; a.download = filename; a.click();
  URL.revokeObjectURL(url);
}}

// ── Charts (Pure Canvas, no external deps) ──────
function drawPieChart(canvasId, labels, values, colors) {{
  const canvas = document.getElementById(canvasId);
  if (!canvas) return;
  const ctx = canvas.getContext('2d');
  canvas.width = canvas.offsetWidth || 280;
  canvas.height = 200;
  const total = values.reduce((a, b) => a + b, 0);
  if (total === 0) return;
  let startAngle = -Math.PI / 2;
  const cx = canvas.width / 2;
  const cy = canvas.height / 2 - 10;
  const r = Math.min(cx, cy) - 10;

  values.forEach((val, i) => {{
    const slice = (val / total) * 2 * Math.PI;
    ctx.beginPath();
    ctx.moveTo(cx, cy);
    ctx.arc(cx, cy, r, startAngle, startAngle + slice);
    ctx.closePath();
    ctx.fillStyle = colors[i % colors.length];
    ctx.fill();
    ctx.strokeStyle = '#fff';
    ctx.lineWidth = 2;
    ctx.stroke();
    startAngle += slice;
  }});

  // Legend
  const legendY = canvas.height - (Math.ceil(labels.length / 2) * 18) + 5;
  labels.forEach((label, i) => {{
    const col = i % 2;
    const row = Math.floor(i / 2);
    const lx = col === 0 ? 4 : canvas.width / 2 + 4;
    const ly = legendY + row * 18;
    ctx.fillStyle = colors[i % colors.length];
    ctx.fillRect(lx, ly, 10, 10);
    ctx.fillStyle = getComputedStyle(document.documentElement).getPropertyValue('--text') || '#333';
    ctx.font = '10px sans-serif';
    ctx.fillText(`${{label}} (${{val}})`.substring(0, 20), lx + 14, ly + 9);
  }});
}}

function drawBarChart(canvasId, labels, values, color) {{
  const canvas = document.getElementById(canvasId);
  if (!canvas) return;
  const ctx = canvas.getContext('2d');
  canvas.width = canvas.offsetWidth || 280;
  canvas.height = 200;
  const pad = {{top: 10, right: 10, bottom: 60, left: 40}};
  const w = canvas.width - pad.left - pad.right;
  const h = canvas.height - pad.top - pad.bottom;
  const max = Math.max(...values) || 1;
  const barW = w / values.length;
  const textColor = '#666';

  values.forEach((val, i) => {{
    const barH = (val / max) * h;
    const x = pad.left + i * barW + barW * 0.1;
    const y = pad.top + h - barH;
    ctx.fillStyle = color;
    ctx.fillRect(x, y, barW * 0.8, barH);
    ctx.fillStyle = textColor;
    ctx.font = '9px sans-serif';
    ctx.save();
    ctx.translate(pad.left + i * barW + barW / 2, canvas.height - pad.bottom + 8);
    ctx.rotate(-Math.PI / 4);
    ctx.fillText(labels[i].substring(0, 12), 0, 0);
    ctx.restore();
    ctx.fillStyle = textColor;
    ctx.font = '9px sans-serif';
    ctx.fillText(val, pad.left + i * barW + barW / 2 - 5, y - 3);
  }});

  // Axes
  ctx.strokeStyle = '#ccc';
  ctx.beginPath();
  ctx.moveTo(pad.left, pad.top);
  ctx.lineTo(pad.left, pad.top + h);
  ctx.lineTo(pad.left + w, pad.top + h);
  ctx.stroke();
}}

const COLORS = ['#4361ee','#7209b7','#e63946','#f77f00','#2ec4b6','#06a77d','#3d348b','#8d5524','#e040fb','#00b0ff'];

window.addEventListener('load', () => {{
  setTimeout(() => {{
    drawPieChart('catChart', {cat_labels}, {cat_values}, COLORS);
    drawBarChart('langChart', {lang_labels}, {lang_values}, '#4361ee');
    drawPieChart('aiChart',
      ['AI Related', 'Non-AI'],
      [{ai_count}, {non_ai_count}],
      ['#e63946', '#4361ee']
    );
  }}, 100);
}});
"""


# ══════════════════════════════════════════════════════════════════════════════
# MAIN ENTRY POINT
# ══════════════════════════════════════════════════════════════════════════════

def print_banner():
    print("""
╔══════════════════════════════════════════════════════════════════╗
║          AI REPOSITORY AUDIT SCRIPT v1.0                        ║
║          Complete Static Analysis & Report Generation           ║
╚══════════════════════════════════════════════════════════════════╝
""")


def print_summary(scanner: RepositoryScanner):
    s = scanner.get_summary()
    print(f"""
┌─────────────────────────────────────────────────────────────────┐
│  SCAN RESULTS SUMMARY                                           │
├─────────────────────────────────────────────────────────────────┤
│  Repository      : {s['repository_name']:<44} │
│  Scan Date       : {s['scan_date']:<44} │
├─────────────────────────────────────────────────────────────────┤
│  STRUCTURE                                                      │
│  Directories     : {s['total_directories']:<44} │
│  Total Files     : {s['total_files']:<44} │
│  Source Files    : {s['total_source_files']:<44} │
│  Config Files    : {s['total_configuration_files']:<44} │
│  Documentation   : {s['total_documentation_files']:<44} │
│  Test Files      : {s['total_test_files']:<44} │
│  Infrastructure  : {s['total_infrastructure_files']:<44} │
│  AI Files        : {s['total_ai_related_files']:<44} │
├─────────────────────────────────────────────────────────────────┤
│  AI COMPONENTS                                                  │
│  AI Agents       : {s['total_agents']:<44} │
│  AI Providers    : {s['total_providers']:<44} │
│  AI Models       : {s['total_models']:<44} │
│  AI SDKs         : {s['total_sdks']:<44} │
│  Prompts         : {s['total_prompts']:<44} │
│  Tools           : {s['total_tools']:<44} │
│  API Keys        : {s['total_api_keys']:<44} │
│  Workflows       : {s['total_workflows']:<44} │
├─────────────────────────────────────────────────────────────────┤
│  CODE METRICS                                                   │
│  Total Classes   : {s['total_classes']:<44} │
│  Total Functions : {s['total_functions']:<44} │
│  API Endpoints   : {s['total_endpoints']:<44} │
└─────────────────────────────────────────────────────────────────┘
""")


def main():
    print_banner()

    parser = argparse.ArgumentParser(
        description="AI Repository Audit - Complete static analysis and report generation",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python audit.py .
  python audit.py /path/to/repo
  python audit.py /path/to/repo --output ./reports
  python audit.py /path/to/repo --output ./reports --format all
  python audit.py /path/to/repo --format html json
        """
    )
    parser.add_argument("root", nargs="?", default=".",
                        help="Repository root path (default: current directory)")
    parser.add_argument("--output", "-o", default="./audit_reports",
                        help="Output directory for reports (default: ./audit_reports)")
    parser.add_argument("--format", "-f", nargs="+",
                        choices=["json", "csv", "xlsx", "html", "md", "all"],
                        default=["all"],
                        help="Output formats to generate (default: all)")
    args = parser.parse_args()

    root_path = os.path.abspath(args.root)
    if not os.path.isdir(root_path):
        print(f"[ERROR] Path does not exist or is not a directory: {root_path}")
        sys.exit(1)

    formats = args.format
    if "all" in formats:
        formats = ["json", "csv", "xlsx", "html", "md"]

    # ── Scan ──────────────────────────────────────
    scanner = RepositoryScanner(root_path)
    scanner.scan()
    print_summary(scanner)

    # ── Generate Reports ──────────────────────────
    generator = ReportGenerator(scanner, args.output)
    md_content = ""

    print("\n[*] Generating reports...")

    if "json" in formats:
        generator.generate_json()

    if "csv" in formats:
        generator.generate_csv()

    if "xlsx" in formats:
        generator.generate_xlsx()

    if "md" in formats:
        md_content = generator.generate_markdown()

    if "html" in formats:
        generator.generate_html(md_content)

    print(f"""
╔══════════════════════════════════════════════════════════════════╗
║  AUDIT COMPLETE                                                 ║
╠══════════════════════════════════════════════════════════════════╣
║  Reports saved to: {args.output:<43} ║
║                                                                 ║
║  Files generated:                                               │""")

    output_path = Path(args.output)
    for fname in sorted(output_path.glob("repository_summary.*")):
        size = fname.stat().st_size
        size_str = f"{size/1024:.1f}KB" if size > 1024 else f"{size}B"
        print(f"║    📄 {fname.name:<50} {size_str:>6} ║")

    print("╚══════════════════════════════════════════════════════════════════╝")
    print(f"\n[✓] Open the HTML dashboard: {output_path / 'repository_summary.html'}")
    print("[✓] All reports are static and ready for distribution.\n")


if __name__ == "__main__":
    main()
#!/usr/bin/env python3
"""
Project Document Generator v2.0
================================
Comprehensive project documentation generator that:
- Scans entire project directory structure including subfolders
- Parses all CI/CD pipeline YAML files (GitHub Actions, Azure DevOps, Jenkins, GitLab CI)
- Detects project name using AI heuristic agents
- Detects technology stack, frameworks, languages
- Generates local development run instructions (Linux/Windows/macOS)
- Generates push-to-DevOps deployment instructions
- Generates Docker run instructions
- Produces a detailed, professionally formatted Word document

Formatting Spec:
  - All text: Black color
  - Tables: Colorful (no silver or black)
  - Project Title: Times New Roman 22pt Bold
  - Headings: Times New Roman 16pt Bold
  - Sub Headings: Calibri 14pt Bold
  - Content: Calibri 12pt
  - Bullets, numbered lists, code blocks included

Supports: GitHub Actions, Azure DevOps, Jenkins, GitLab CI, CircleCI, Travis CI
Runs on: Linux, Windows, macOS

Usage:
  python project_doc_generator.py [project_path] [-o output.docx] [-v]

Prerequisites:
  pip install python-docx pyyaml
"""

import os
import sys
import re
import json
import yaml
import glob
import platform
import subprocess
import argparse
import logging
import shutil
import socket
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Optional, Tuple, Any
from collections import defaultdict

try:
    from docx import Document
    from docx.shared import Pt, Inches, Cm, RGBColor
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.enum.table import WD_TABLE_ALIGNMENT
    from docx.enum.style import WD_STYLE_TYPE
    from docx.oxml.ns import qn, nsdecls
    from docx.oxml import parse_xml
except ImportError:
    print("ERROR: python-docx is required. Install it with:")
    print("  pip install python-docx")
    sys.exit(1)

try:
    import yaml
except ImportError:
    print("ERROR: PyYAML is required. Install it with:")
    print("  pip install pyyaml")
    sys.exit(1)

# ---------------------------------------------------------------------------
# Configuration & Constants
# ---------------------------------------------------------------------------

PIPELINE_PATTERNS = [
    ".github/workflows/*.yml",
    ".github/workflows/*.yaml",
    "azure-pipelines.yml",
    "azure-pipelines.yaml",
    ".azure-pipelines/*.yml",
    ".azure-pipelines/*.yaml",
    "pipelines/*.yml",
    "pipelines/*.yaml",
    "Jenkinsfile",
    "Jenkinsfile.*",
    "jenkins/*.groovy",
    "jenkins/*.yml",
    "jenkins/*.yaml",
    ".gitlab-ci.yml",
    ".gitlab-ci.yaml",
    "bitbucket-pipelines.yml",
    ".circleci/config.yml",
    ".travis.yml",
    "ci/*.yml",
    "ci/*.yaml",
    ".ci/*.yml",
    ".ci/*.yaml",
]

FILE_CATEGORIES = {
    "Source Code": [
        ".py", ".js", ".ts", ".java", ".cs", ".go", ".rs", ".rb",
        ".php", ".swift", ".kt", ".scala", ".cpp", ".c", ".h",
        ".hpp", ".m", ".mm", ".r", ".R", ".jl", ".dart", ".lua",
        ".pl", ".pm", ".ex", ".exs", ".clj", ".hs", ".erl",
    ],
    "Web Frontend": [
        ".html", ".htm", ".css", ".scss", ".sass", ".less",
        ".jsx", ".tsx", ".vue", ".svelte", ".astro",
    ],
    "Configuration": [
        ".yml", ".yaml", ".json", ".toml", ".ini", ".cfg",
        ".conf", ".env", ".properties", ".xml", ".hcl",
    ],
    "Infrastructure as Code": [
        ".tf", ".tfvars", ".bicep", ".pulumi",
    ],
    "Containerization": [
        "Dockerfile", "docker-compose.yml", "docker-compose.yaml",
        ".dockerignore",
    ],
    "Documentation": [
        ".md", ".rst", ".txt", ".adoc", ".tex",
    ],
    "Scripts": [
        ".sh", ".bash", ".zsh", ".ps1", ".psm1", ".bat", ".cmd",
    ],
    "Data & Database": [
        ".sql", ".csv", ".tsv", ".parquet", ".avro",
    ],
    "Testing": [
        "_test.go", "_test.py", ".test.js", ".test.ts",
        ".spec.js", ".spec.ts", "_spec.rb",
    ],
    "Build Files": [
        "Makefile", "CMakeLists.txt", "build.gradle",
        "pom.xml", "package.json", "Cargo.toml",
        "go.mod", "requirements.txt", "Pipfile",
        "setup.py", "setup.cfg", "pyproject.toml",
        "Gemfile", "composer.json",
    ],
}

TABLE_COLORS = {
    "header": "2E86AB",
    "header_text": "FFFFFF",
    "row_even": "F0F7FA",
    "row_odd": "FFFFFF",
}

IGNORE_DIRS = {
    ".git", ".svn", ".hg", "__pycache__", "node_modules",
    ".tox", ".mypy_cache", ".pytest_cache", "venv", ".venv",
    "env", ".env_dir", "dist", "build", ".eggs",
    ".idea", ".vscode", ".vs", "bin", "obj", "target",
    ".terraform", ".next", ".nuxt", "coverage",
}

IMPORTANT_DOT_ENTRIES = {
    ".github", ".gitlab-ci.yml", ".circleci",
    ".azure-pipelines", ".travis.yml", ".dockerignore",
    ".env.example", ".gitignore", ".editorconfig",
    ".eslintrc", ".prettierrc", ".babelrc",
}

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)


# ===========================================================================
# AI PROJECT AGENT
# ===========================================================================

class AIProjectAgent:
    """
    AI Agent that analyzes project structure, infers project name,
    purpose, tech stack, and generates intelligent summaries using
    heuristic analysis.
    """

    def __init__(self, project_path: str):
        self.project_path = Path(project_path)

    def detect_project_name(self) -> str:
        """Detect project name using multiple heuristics."""
        candidates = []

        # 1. package.json
        pkg_json = self.project_path / "package.json"
        if pkg_json.exists():
            try:
                with open(pkg_json, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if data.get("name"):
                        candidates.append(("package.json", data["name"], 95))
            except Exception:
                pass

        # 2. setup.py / setup.cfg / pyproject.toml
        for setup_file in ["setup.py", "setup.cfg", "pyproject.toml"]:
            fpath = self.project_path / setup_file
            if fpath.exists():
                try:
                    content = fpath.read_text(encoding="utf-8")
                    match = re.search(r'name\s*=\s*["\']([^"\']+)["\']', content)
                    if not match:
                        match = re.search(r'name\s*=\s*(.+)', content)
                    if match:
                        candidates.append((setup_file, match.group(1).strip().strip("'\""), 90))
                except Exception:
                    pass

        # 3. Cargo.toml
        cargo = self.project_path / "Cargo.toml"
        if cargo.exists():
            try:
                content = cargo.read_text(encoding="utf-8")
                match = re.search(r'name\s*=\s*["\']([^"\']+)["\']', content)
                if match:
                    candidates.append(("Cargo.toml", match.group(1), 90))
            except Exception:
                pass

        # 4. pom.xml
        pom = self.project_path / "pom.xml"
        if pom.exists():
            try:
                content = pom.read_text(encoding="utf-8")
                match = re.search(r'<artifactId>([^<]+)</artifactId>', content)
                if match:
                    candidates.append(("pom.xml", match.group(1), 90))
            except Exception:
                pass

        # 5. build.gradle / settings.gradle
        for gf in ["build.gradle", "settings.gradle"]:
            gradle = self.project_path / gf
            if gradle.exists():
                try:
                    content = gradle.read_text(encoding="utf-8")
                    match = re.search(r"rootProject\.name\s*=\s*['\"]([^'\"]+)", content)
                    if match:
                        candidates.append((gf, match.group(1), 88))
                        break
                except Exception:
                    pass

        # 6. go.mod
        gomod = self.project_path / "go.mod"
        if gomod.exists():
            try:
                content = gomod.read_text(encoding="utf-8")
                match = re.search(r'module\s+(\S+)', content)
                if match:
                    mod_name = match.group(1).split("/")[-1]
                    candidates.append(("go.mod", mod_name, 88))
            except Exception:
                pass

        # 7. Git remote
        try:
            result = subprocess.run(
                ["git", "remote", "get-url", "origin"],
                cwd=str(self.project_path),
                capture_output=True, text=True, timeout=10
            )
            if result.returncode == 0:
                url = result.stdout.strip()
                repo_name = url.rstrip("/").split("/")[-1].replace(".git", "")
                candidates.append(("git remote", repo_name, 85))
        except Exception:
            pass

        # 8. README
        for readme in ["README.md", "README.rst", "README.txt", "README"]:
            rpath = self.project_path / readme
            if rpath.exists():
                try:
                    content = rpath.read_text(encoding="utf-8")
                    for line in content.strip().split("\n")[:5]:
                        match = re.match(r'^#{1,2}\s+(.+)', line.strip())
                        if match:
                            candidates.append(("README", match.group(1).strip(), 80))
                            break
                except Exception:
                    pass

        # 9. Directory name fallback
        dir_name = self.project_path.resolve().name
        candidates.append(("directory", dir_name, 50))

        candidates.sort(key=lambda x: x[2], reverse=True)
        if candidates:
            source, name, confidence = candidates[0]
            logger.info(f"Detected project name: '{name}' (source: {source}, confidence: {confidence}%)")
            return name
        return "Unknown Project"

    def detect_tech_stack(self, file_tree: Dict) -> Dict[str, List[str]]:
        """Detect technology stack from file analysis."""
        tech = {
            "Languages": set(),
            "Frameworks": set(),
            "Databases": set(),
            "CI/CD": set(),
            "Cloud & Infrastructure": set(),
            "Testing": set(),
            "Package Managers": set(),
            "Containerization": set(),
        }

        all_files = []
        self._flatten_files(file_tree, all_files)
        all_filenames = {Path(f).name for f in all_files}
        all_extensions = {Path(f).suffix.lower() for f in all_files}

        lang_map = {
            ".py": "Python", ".js": "JavaScript", ".ts": "TypeScript",
            ".java": "Java", ".cs": "C#", ".go": "Go", ".rs": "Rust",
            ".rb": "Ruby", ".php": "PHP", ".swift": "Swift",
            ".kt": "Kotlin", ".scala": "Scala", ".cpp": "C++",
            ".c": "C", ".r": "R", ".R": "R", ".jl": "Julia",
            ".dart": "Dart", ".lua": "Lua", ".pl": "Perl",
            ".ex": "Elixir", ".clj": "Clojure", ".hs": "Haskell",
            ".erl": "Erlang",
        }
        for ext, lang in lang_map.items():
            if ext in all_extensions:
                tech["Languages"].add(lang)

        # Frameworks
        if "requirements.txt" in all_filenames:
            tech["Frameworks"].update(self._check_python_frameworks())
        if "package.json" in all_filenames:
            tech["Frameworks"].update(self._check_node_frameworks())
        if (self.project_path / "config" / "routes.rb").exists():
            tech["Frameworks"].add("Ruby on Rails")
        if "pom.xml" in all_filenames:
            tech["Frameworks"].add("Spring Boot / Java")
        if "build.gradle" in all_filenames:
            tech["Frameworks"].add("Gradle / Java")
        if "pubspec.yaml" in all_filenames:
            tech["Frameworks"].add("Flutter / Dart")

        # CI/CD
        if any(f.startswith(".github/workflows/") or f.startswith(".github\\workflows\\") for f in all_files):
            tech["CI/CD"].add("GitHub Actions")
        if any("azure-pipelines" in f.lower() for f in all_files):
            tech["CI/CD"].add("Azure DevOps Pipelines")
        if any("Jenkinsfile" in Path(f).name for f in all_files):
            tech["CI/CD"].add("Jenkins")
        if ".gitlab-ci.yml" in all_filenames:
            tech["CI/CD"].add("GitLab CI")
        if ".travis.yml" in all_filenames:
            tech["CI/CD"].add("Travis CI")
        if "bitbucket-pipelines.yml" in all_filenames:
            tech["CI/CD"].add("Bitbucket Pipelines")

        # Infrastructure
        if any(f.endswith(".tf") for f in all_files):
            tech["Cloud & Infrastructure"].add("Terraform")
        if any(f.endswith(".bicep") for f in all_files):
            tech["Cloud & Infrastructure"].add("Azure Bicep")
        if any("kubernetes" in f.lower() or "k8s" in f.lower() for f in all_files):
            tech["Cloud & Infrastructure"].add("Kubernetes")
        if any("helm" in f.lower() for f in all_files):
            tech["Cloud & Infrastructure"].add("Helm")
        if any("ansible" in f.lower() for f in all_files):
            tech["Cloud & Infrastructure"].add("Ansible")

        # Containerization
        if "Dockerfile" in all_filenames:
            tech["Containerization"].add("Docker")
        if any("docker-compose" in f for f in all_filenames):
            tech["Containerization"].add("Docker Compose")

        # Package managers
        pkg_mgr = {
            "package.json": "npm/yarn", "requirements.txt": "pip",
            "Pipfile": "pipenv", "poetry.lock": "Poetry",
            "Cargo.lock": "Cargo", "go.sum": "Go Modules",
            "Gemfile.lock": "Bundler", "composer.lock": "Composer",
            "pnpm-lock.yaml": "pnpm", "yarn.lock": "Yarn",
            "package-lock.json": "npm",
        }
        for file, mgr in pkg_mgr.items():
            if file in all_filenames:
                tech["Package Managers"].add(mgr)

        # Testing
        test_indicators = {
            "pytest.ini": "pytest", "conftest.py": "pytest",
            "jest.config.js": "Jest", "jest.config.ts": "Jest",
            "karma.conf.js": "Karma",
            "cypress.json": "Cypress", "cypress.config.js": "Cypress",
            "cypress.config.ts": "Cypress",
            "playwright.config.ts": "Playwright",
            ".rspec": "RSpec", "phpunit.xml": "PHPUnit",
        }
        for file, framework in test_indicators.items():
            if file in all_filenames:
                tech["Testing"].add(framework)

        return {k: sorted(v) for k, v in tech.items() if v}

    def _check_python_frameworks(self) -> set:
        frameworks = set()
        req_file = self.project_path / "requirements.txt"
        if req_file.exists():
            try:
                content = req_file.read_text(encoding="utf-8").lower()
                fw_map = {
                    "django": "Django", "flask": "Flask", "fastapi": "FastAPI",
                    "tornado": "Tornado", "celery": "Celery",
                    "airflow": "Apache Airflow", "pandas": "Pandas",
                    "numpy": "NumPy", "tensorflow": "TensorFlow",
                    "torch": "PyTorch", "scikit-learn": "Scikit-learn",
                    "streamlit": "Streamlit", "langchain": "LangChain",
                    "transformers": "Hugging Face Transformers",
                }
                for pkg, name in fw_map.items():
                    if pkg in content:
                        frameworks.add(name)
            except Exception:
                pass
        return frameworks

    def _check_node_frameworks(self) -> set:
        frameworks = set()
        pkg_file = self.project_path / "package.json"
        if pkg_file.exists():
            try:
                with open(pkg_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                all_deps = {}
                all_deps.update(data.get("dependencies", {}))
                all_deps.update(data.get("devDependencies", {}))
                fw_map = {
                    "react": "React", "next": "Next.js", "vue": "Vue.js",
                    "nuxt": "Nuxt.js", "@angular/core": "Angular",
                    "svelte": "Svelte", "express": "Express.js",
                    "@nestjs/core": "NestJS", "fastify": "Fastify",
                    "gatsby": "Gatsby", "electron": "Electron",
                    "tailwindcss": "Tailwind CSS",
                    "@mui/material": "Material UI",
                    "redux": "Redux", "prisma": "Prisma",
                    "mongoose": "Mongoose",
                }
                for pkg, name in fw_map.items():
                    if pkg in all_deps:
                        frameworks.add(name)
            except Exception:
                pass
        return frameworks

    def _flatten_files(self, file_tree: Dict, result: List, prefix: str = ""):
        for key, value in file_tree.items():
            path = f"{prefix}/{key}" if prefix else key
            if isinstance(value, dict) and "name" not in value:
                self._flatten_files(value, result, path)
            else:
                result.append(path)

    def generate_project_summary(self, project_name: str, tech_stack: Dict,
                                 pipeline_info: List[Dict], file_stats: Dict) -> str:
        languages = tech_stack.get("Languages", [])
        frameworks = tech_stack.get("Frameworks", [])
        cicd = tech_stack.get("CI/CD", [])

        parts = [f"{project_name} is a software project"]
        if languages:
            if len(languages) == 1:
                parts.append(f" built primarily with {languages[0]}")
            else:
                parts.append(f" built with {', '.join(languages[:-1])} and {languages[-1]}")
        if frameworks:
            parts.append(f", utilizing {', '.join(frameworks)}")
        parts.append(".")

        if cicd:
            parts.append(f" The project employs {', '.join(cicd)} for continuous integration and deployment.")

        if pipeline_info:
            total_stages = sum(len(p.get("stages", [])) for p in pipeline_info)
            total_jobs = sum(len(p.get("jobs", [])) for p in pipeline_info)
            if total_stages > 0 or total_jobs > 0:
                parts.append(
                    f" The CI/CD pipeline consists of {len(pipeline_info)} pipeline file(s) "
                    f"with {total_stages} stage(s) and {total_jobs} job(s)."
                )

        total_files = sum(file_stats.get("by_category", {}).values())
        total_dirs = file_stats.get("total_directories", 0)
        parts.append(f" The project contains {total_files} files across {total_dirs} directories.")

        infra = tech_stack.get("Cloud & Infrastructure", [])
        containers = tech_stack.get("Containerization", [])
        if infra or containers:
            items = infra + containers
            parts.append(f" Infrastructure is managed using {', '.join(items)}.")

        return "".join(parts)

    def detect_project_type(self, tech_stack: Dict) -> str:
        languages = set(tech_stack.get("Languages", []))
        frameworks = set(tech_stack.get("Frameworks", []))

        if frameworks & {"React", "Vue.js", "Angular", "Svelte", "Next.js", "Nuxt.js", "Gatsby"}:
            if frameworks & {"Express.js", "NestJS", "Fastify", "Django", "Flask", "FastAPI"}:
                return "Full-Stack Web Application"
            return "Frontend Web Application"
        if frameworks & {"Express.js", "NestJS", "Fastify", "Django", "Flask", "FastAPI",
                         "Spring Boot / Java", "Ruby on Rails"}:
            return "Backend Web Application / API"
        if frameworks & {"TensorFlow", "PyTorch", "Scikit-learn", "LangChain",
                         "Hugging Face Transformers"}:
            return "Machine Learning / AI Project"
        if frameworks & {"Apache Airflow", "Celery"}:
            return "Data Pipeline / ETL"
        if frameworks & {"Electron"}:
            return "Desktop Application"
        if frameworks & {"Flutter / Dart"}:
            return "Mobile Application"
        if tech_stack.get("Cloud & Infrastructure"):
            return "Infrastructure / DevOps Project"
        if languages & {"Python"}:
            return "Python Application"
        if languages & {"JavaScript", "TypeScript"}:
            return "JavaScript/TypeScript Application"
        if languages & {"Java"}:
            return "Java Application"
        if languages & {"Go"}:
            return "Go Application"
        if languages & {"Rust"}:
            return "Rust Application"
        if languages & {"C#"}:
            return "C# / .NET Application"
        return "Software Project"


# ===========================================================================
# PROJECT SCANNER
# ===========================================================================

class ProjectScanner:
    """Scans the project directory for files, pipelines, and metadata."""

    def __init__(self, project_path: str):
        self.project_path = Path(project_path).resolve()
        if not self.project_path.exists():
            raise FileNotFoundError(f"Project path does not exist: {self.project_path}")

    def scan_file_tree(self) -> Dict:
        logger.info(f"Scanning directory: {self.project_path}")
        tree = {}
        self._build_tree(self.project_path, tree)
        return tree

    def _build_tree(self, current_path: Path, tree: Dict):
        try:
            items = sorted(current_path.iterdir(), key=lambda x: (not x.is_dir(), x.name.lower()))
        except PermissionError:
            return

        for item in items:
            if item.name in IGNORE_DIRS:
                continue
            if item.name.startswith(".") and item.name not in IMPORTANT_DOT_ENTRIES:
                if not item.is_dir():
                    rel = str(item.relative_to(self.project_path))
                    tree[rel] = self._get_file_info(item)
                continue

            if item.is_dir():
                subtree = {}
                self._build_tree(item, subtree)
                if subtree:
                    rel = str(item.relative_to(self.project_path))
                    tree[rel] = subtree
            else:
                rel = str(item.relative_to(self.project_path))
                tree[rel] = self._get_file_info(item)

    def _get_file_info(self, file_path: Path) -> Dict:
        try:
            stat = file_path.stat()
            return {
                "size": stat.st_size,
                "modified": datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M"),
                "extension": file_path.suffix.lower(),
                "name": file_path.name,
            }
        except Exception:
            return {"size": 0, "modified": "Unknown", "extension": file_path.suffix.lower(), "name": file_path.name}

    def get_file_statistics(self, file_tree: Dict) -> Dict:
        stats = {
            "total_files": 0,
            "total_directories": 0,
            "total_size": 0,
            "by_extension": defaultdict(int),
            "by_category": defaultdict(int),
            "largest_files": [],
        }
        all_files = []
        self._collect_stats(file_tree, stats, all_files)

        for finfo in all_files:
            categorized = False
            for category, extensions in FILE_CATEGORIES.items():
                if finfo.get("extension", "") in extensions or finfo.get("name", "") in extensions:
                    stats["by_category"][category] += 1
                    categorized = True
                    break
            if not categorized:
                stats["by_category"]["Other"] += 1

        all_files.sort(key=lambda x: x.get("size", 0), reverse=True)
        stats["largest_files"] = all_files[:10]
        return stats

    def _collect_stats(self, tree: Dict, stats: Dict, all_files: List):
        for key, value in tree.items():
            if isinstance(value, dict):
                if "name" in value and "size" in value:
                    stats["total_files"] += 1
                    stats["total_size"] += value.get("size", 0)
                    ext = value.get("extension", "")
                    if ext:
                        stats["by_extension"][ext] += 1
                    value["path"] = key
                    all_files.append(value)
                else:
                    stats["total_directories"] += 1
                    self._collect_stats(value, stats, all_files)

    def find_pipeline_files(self) -> List[Path]:
        pipeline_files = []

        for pattern in PIPELINE_PATTERNS:
            full_pattern = str(self.project_path / pattern)
            matches = glob.glob(full_pattern, recursive=False)
            for match in matches:
                p = Path(match)
                if p.is_file() and p not in pipeline_files:
                    pipeline_files.append(p)

        for root, dirs, files in os.walk(self.project_path):
            dirs[:] = [d for d in dirs if d not in IGNORE_DIRS]
            for fname in files:
                fpath = Path(root) / fname
                if fpath in pipeline_files:
                    continue
                if fname == "Jenkinsfile":
                    pipeline_files.append(fpath)
                elif fname.endswith((".yml", ".yaml")):
                    try:
                        content = fpath.read_text(encoding="utf-8", errors="ignore")[:2000]
                        strong_indicators = ["stages:", "jobs:", "pipeline:", "trigger:", "on:", "pool:"]
                        if sum(1 for si in strong_indicators if si in content) >= 2:
                            if fpath not in pipeline_files:
                                pipeline_files.append(fpath)
                    except Exception:
                        pass

        logger.info(f"Found {len(pipeline_files)} pipeline file(s)")
        return pipeline_files

    def parse_pipeline_file(self, filepath: Path) -> Dict:
        result = {
            "file": str(filepath.relative_to(self.project_path)),
            "type": "Unknown", "raw_content": "", "stages": [],
            "jobs": [], "triggers": [], "variables": {},
            "environments": [], "services": [], "parameters": [],
            "error": None, "workflow_name": "", "pool": "", "agent": "",
        }

        try:
            content = filepath.read_text(encoding="utf-8")
            result["raw_content"] = content
        except Exception as e:
            result["error"] = str(e)
            return result

        if "Jenkinsfile" in filepath.name or filepath.suffix == ".groovy":
            result["type"] = "Jenkins"
            self._parse_jenkinsfile(content, result)
        elif ".github" in str(filepath) and "workflows" in str(filepath):
            result["type"] = "GitHub Actions"
            self._parse_github_actions(content, result)
        elif "azure-pipelines" in filepath.name.lower() or ".azure-pipelines" in str(filepath):
            result["type"] = "Azure DevOps"
            self._parse_azure_pipelines(content, result)
        elif ".gitlab-ci" in filepath.name:
            result["type"] = "GitLab CI"
            self._parse_gitlab_ci(content, result)
        else:
            self._parse_generic_yaml(content, result)

        return result

    def _parse_github_actions(self, content: str, result: Dict):
        try:
            data = yaml.safe_load(content)
            if not isinstance(data, dict):
                return
            result["type"] = "GitHub Actions"
            on_config = data.get("on", {})
            if isinstance(on_config, str):
                result["triggers"].append(on_config)
            elif isinstance(on_config, list):
                result["triggers"].extend(on_config)
            elif isinstance(on_config, dict):
                result["triggers"].extend(on_config.keys())

            result["workflow_name"] = data.get("name", "Unnamed Workflow")
            env = data.get("env", {})
            if isinstance(env, dict):
                result["variables"] = env

            jobs = data.get("jobs", {})
            if isinstance(jobs, dict):
                for job_name, job_config in jobs.items():
                    job_info = {"name": job_name, "runs_on": "", "steps": [], "needs": [],
                                "condition": "", "environment": ""}
                    if isinstance(job_config, dict):
                        job_info["runs_on"] = str(job_config.get("runs-on", ""))
                        needs = job_config.get("needs", [])
                        job_info["needs"] = [needs] if isinstance(needs, str) else needs
                        job_info["condition"] = str(job_config.get("if", ""))
                        job_info["environment"] = str(job_config.get("environment", ""))

                        for step in job_config.get("steps", []):
                            if isinstance(step, dict):
                                job_info["steps"].append({
                                    "name": step.get("name", step.get("uses", step.get("run", "")[:50])),
                                    "uses": step.get("uses", ""),
                                    "run": step.get("run", ""),
                                })
                        if job_info["environment"]:
                            result["environments"].append(job_info["environment"])
                    result["jobs"].append(job_info)

            if result["jobs"]:
                result["stages"] = [j["name"] for j in result["jobs"]]
        except yaml.YAMLError as e:
            result["error"] = f"YAML parse error: {e}"

    def _parse_azure_pipelines(self, content: str, result: Dict):
        try:
            data = yaml.safe_load(content)
            if not isinstance(data, dict):
                return
            result["type"] = "Azure DevOps"

            trigger = data.get("trigger", {})
            if isinstance(trigger, list):
                result["triggers"] = trigger
            elif isinstance(trigger, dict):
                branches = trigger.get("branches", {})
                if isinstance(branches, dict):
                    result["triggers"].extend(branches.get("include", []))
            elif isinstance(trigger, str):
                result["triggers"].append(trigger)

            pr = data.get("pr", {})
            if pr:
                result["triggers"].append("Pull Request")

            variables = data.get("variables", {})
            if isinstance(variables, dict):
                result["variables"] = variables
            elif isinstance(variables, list):
                for var in variables:
                    if isinstance(var, dict):
                        if "name" in var:
                            result["variables"][var["name"]] = var.get("value", "")
                        elif "group" in var:
                            result["variables"][f"group:{var['group']}"] = "(Variable Group)"

            pool = data.get("pool", {})
            if isinstance(pool, dict):
                result["pool"] = pool.get("vmImage", str(pool))
            elif isinstance(pool, str):
                result["pool"] = pool

            params = data.get("parameters", [])
            if isinstance(params, list):
                for param in params:
                    if isinstance(param, dict):
                        result["parameters"].append({
                            "name": param.get("name", ""),
                            "type": param.get("type", "string"),
                            "default": str(param.get("default", "")),
                        })

            stages = data.get("stages", [])
            if isinstance(stages, list):
                for stage in stages:
                    if isinstance(stage, dict):
                        stage_name = stage.get("stage", stage.get("displayName", "Unnamed"))
                        stage_jobs = stage.get("jobs", [])
                        for job in stage_jobs:
                            if isinstance(job, dict):
                                job_info = {
                                    "name": job.get("job", job.get("deployment", job.get("displayName", "Unnamed"))),
                                    "displayName": job.get("displayName", ""),
                                    "pool": str(job.get("pool", "")),
                                    "steps": [], "environment": str(job.get("environment", "")),
                                }
                                for step in job.get("steps", []):
                                    if isinstance(step, dict):
                                        job_info["steps"].append({
                                            "name": step.get("displayName", step.get("task", step.get("script", "")[:50])),
                                            "task": step.get("task", ""),
                                            "script": step.get("script", ""),
                                        })
                                result["jobs"].append(job_info)
                                if job_info["environment"]:
                                    result["environments"].append(job_info["environment"])
                        result["stages"].append(stage_name)

            if not stages:
                jobs = data.get("jobs", [])
                if isinstance(jobs, list):
                    for job in jobs:
                        if isinstance(job, dict):
                            job_info = {"name": job.get("job", job.get("displayName", "Unnamed")),
                                        "displayName": job.get("displayName", ""), "steps": []}
                            for step in job.get("steps", []):
                                if isinstance(step, dict):
                                    job_info["steps"].append({"name": step.get("displayName", step.get("task", ""))})
                            result["jobs"].append(job_info)
                if not jobs:
                    steps = data.get("steps", [])
                    if isinstance(steps, list):
                        job_info = {"name": "Default Job", "steps": []}
                        for step in steps:
                            if isinstance(step, dict):
                                job_info["steps"].append({
                                    "name": step.get("displayName", step.get("task", step.get("script", "")[:50]))
                                })
                        if job_info["steps"]:
                            result["jobs"].append(job_info)

            resources = data.get("resources", {})
            if isinstance(resources, dict):
                for res_type, res_list in resources.items():
                    if isinstance(res_list, list):
                        for res in res_list:
                            if isinstance(res, dict):
                                result["services"].append({
                                    "type": res_type,
                                    "name": str(res.get(res_type.rstrip("s"), res.get("repository", res.get("container", "")))),
                                })
        except yaml.YAMLError as e:
            result["error"] = f"YAML parse error: {e}"

    def _parse_jenkinsfile(self, content: str, result: Dict):
        result["type"] = "Jenkins"
        stages = re.findall(r"stage\s*\(\s*['\"]([^'\"]+)['\"]\s*\)", content)
        result["stages"] = stages

        agent_match = re.search(r"agent\s*\{([^}]+)\}", content)
        if agent_match:
            result["agent"] = agent_match.group(1).strip()

        env_match = re.search(r"environment\s*\{([^}]+)\}", content)
        if env_match:
            for var_match in re.finditer(r"(\w+)\s*=\s*['\"]?([^'\"\n]+)['\"]?", env_match.group(1)):
                result["variables"][var_match.group(1)] = var_match.group(2).strip()

        trigger_match = re.search(r"triggers\s*\{([^}]+)\}", content)
        if trigger_match:
            result["triggers"] = [t.strip() for t in trigger_match.group(1).strip().split("\n") if t.strip()]

        param_match = re.search(r"parameters\s*\{([^}]+)\}", content)
        if param_match:
            for p_match in re.finditer(r"(string|boolean|choice|text)\s*\([^)]*name:\s*['\"]([^'\"]+)['\"]", param_match.group(1)):
                result["parameters"].append({"type": p_match.group(1), "name": p_match.group(2)})

        for stage in stages:
            result["jobs"].append({"name": stage, "steps": []})

    def _parse_gitlab_ci(self, content: str, result: Dict):
        try:
            data = yaml.safe_load(content)
            if not isinstance(data, dict):
                return
            result["type"] = "GitLab CI"
            stages = data.get("stages", [])
            result["stages"] = stages if isinstance(stages, list) else []

            variables = data.get("variables", {})
            if isinstance(variables, dict):
                result["variables"] = {k: str(v) for k, v in variables.items()}

            reserved = {"stages", "variables", "image", "services", "before_script",
                        "after_script", "cache", "include", "default", "workflow", "pages"}
            for key, value in data.items():
                if key.startswith(".") or key in reserved:
                    continue
                if isinstance(value, dict):
                    job_info = {
                        "name": key, "stage": value.get("stage", ""),
                        "image": value.get("image", ""), "script": value.get("script", []),
                        "environment": str(value.get("environment", "")),
                    }
                    result["jobs"].append(job_info)
                    if job_info["environment"]:
                        result["environments"].append(job_info["environment"])

            services = data.get("services", [])
            if isinstance(services, list):
                for svc in services:
                    if isinstance(svc, str):
                        result["services"].append({"name": svc})
                    elif isinstance(svc, dict):
                        result["services"].append(svc)
        except yaml.YAMLError as e:
            result["error"] = f"YAML parse error: {e}"

    def _parse_generic_yaml(self, content: str, result: Dict):
        try:
            data = yaml.safe_load(content)
            if not isinstance(data, dict):
                return
            if "on" in data and "jobs" in data:
                self._parse_github_actions(content, result)
            elif "trigger" in data or "pool" in data:
                self._parse_azure_pipelines(content, result)
            elif "stages" in data and "variables" in data:
                self._parse_gitlab_ci(content, result)
            else:
                result["type"] = "Generic YAML Pipeline"
                for key in ["stages", "jobs", "steps", "tasks"]:
                    if key in data and isinstance(data[key], list):
                        result["stages"] = [
                            str(item) if not isinstance(item, dict)
                            else item.get("name", item.get("stage", str(item)))
                            for item in data[key]
                        ]
        except yaml.YAMLError:
            pass

    def get_git_info(self) -> Dict:
        info = {
            "is_git_repo": False, "remote_url": "", "current_branch": "",
            "last_commit": "", "last_commit_author": "", "last_commit_date": "",
            "total_commits": 0, "contributors": [],
        }
        try:
            result = subprocess.run(["git", "rev-parse", "--is-inside-work-tree"],
                                    cwd=str(self.project_path), capture_output=True, text=True, timeout=10)
            if result.returncode != 0:
                return info
            info["is_git_repo"] = True

            r = subprocess.run(["git", "remote", "get-url", "origin"],
                               cwd=str(self.project_path), capture_output=True, text=True, timeout=10)
            if r.returncode == 0:
                info["remote_url"] = r.stdout.strip()

            r = subprocess.run(["git", "branch", "--show-current"],
                               cwd=str(self.project_path), capture_output=True, text=True, timeout=10)
            if r.returncode == 0:
                info["current_branch"] = r.stdout.strip()

            r = subprocess.run(["git", "log", "-1", "--format=%H|%an|%ad|%s", "--date=short"],
                               cwd=str(self.project_path), capture_output=True, text=True, timeout=10)
            if r.returncode == 0:
                parts = r.stdout.strip().split("|", 3)
                if len(parts) >= 4:
                    info["last_commit"] = parts[3]
                    info["last_commit_author"] = parts[1]
                    info["last_commit_date"] = parts[2]

            r = subprocess.run(["git", "rev-list", "--count", "HEAD"],
                               cwd=str(self.project_path), capture_output=True, text=True, timeout=10)
            if r.returncode == 0:
                info["total_commits"] = int(r.stdout.strip())

            r = subprocess.run(["git", "shortlog", "-sn", "--all"],
                               cwd=str(self.project_path), capture_output=True, text=True, timeout=15)
            if r.returncode == 0:
                for line in r.stdout.strip().split("\n")[:10]:
                    line = line.strip()
                    if line:
                        match = re.match(r'\s*(\d+)\s+(.+)', line)
                        if match:
                            info["contributors"].append({"name": match.group(2).strip(), "commits": int(match.group(1))})
        except (subprocess.TimeoutExpired, FileNotFoundError):
            pass
        return info


# ===========================================================================
# LOCAL DEV & DEPLOYMENT DETECTOR
# ===========================================================================

class LocalDevDeploymentDetector:
    """Detects how to run the project locally and how to push/deploy to DevOps."""

    def __init__(self, project_path: str):
        self.project_path = Path(project_path).resolve()

    def detect_local_run_commands(self) -> Dict[str, Any]:
        commands = {
            "prerequisites": [], "environment_setup": {},
            "install_dependencies": {}, "run_commands": {},
            "test_commands": {}, "build_commands": {},
            "docker_commands": {}, "environment_variables": [],
            "ports": [], "notes": [],
        }
        self._detect_python_commands(commands)
        self._detect_node_commands(commands)
        self._detect_java_commands(commands)
        self._detect_go_commands(commands)
        self._detect_dotnet_commands(commands)
        self._detect_rust_commands(commands)
        self._detect_docker_commands(commands)
        self._detect_makefile_commands(commands)
        self._detect_env_variables(commands)
        self._detect_ports(commands)
        return commands

    def _detect_python_commands(self, commands: Dict):
        req_file = self.project_path / "requirements.txt"
        pipfile = self.project_path / "Pipfile"
        pyproject = self.project_path / "pyproject.toml"
        setup_py = self.project_path / "setup.py"
        manage_py = self.project_path / "manage.py"

        is_python = any([req_file.exists(), pipfile.exists(), pyproject.exists(),
                         setup_py.exists(), list(self.project_path.glob("*.py"))])
        if not is_python:
            return

        commands["prerequisites"].extend(["Python 3.8+ installed", "pip package manager"])

        if pipfile.exists():
            commands["environment_setup"] = {
                "Linux/macOS": ["pip install pipenv", "pipenv install", "pipenv shell"],
                "Windows (PowerShell)": ["pip install pipenv", "pipenv install", "pipenv shell"],
            }
            commands["install_dependencies"] = {"All Platforms": ["pipenv install --dev"]}
        elif pyproject.exists():
            content = pyproject.read_text(encoding="utf-8") if pyproject.exists() else ""
            if "poetry" in content.lower():
                commands["environment_setup"] = {
                    "Linux/macOS": [
                        "curl -sSL https://install.python-poetry.org | python3 -",
                        "poetry install", "poetry shell",
                    ],
                    "Windows (PowerShell)": [
                        "(Invoke-WebRequest -Uri https://install.python-poetry.org -UseBasicParsing).Content | python -",
                        "poetry install", "poetry shell",
                    ],
                }
                commands["install_dependencies"] = {"All Platforms": ["poetry install --with dev"]}
            else:
                self._add_venv_setup(commands)
        else:
            self._add_venv_setup(commands)

        req_content = ""
        if req_file.exists():
            try:
                req_content = req_file.read_text(encoding="utf-8").lower()
            except Exception:
                pass

        if manage_py.exists():
            commands["run_commands"] = {
                "Linux/macOS": [
                    "python manage.py migrate",
                    "python manage.py createsuperuser  # optional",
                    "python manage.py runserver",
                    "python manage.py runserver 0.0.0.0:8000",
                ],
                "Windows (PowerShell)": [
                    "python manage.py migrate",
                    "python manage.py runserver",
                ],
            }
            commands["test_commands"] = {"All Platforms": [
                "python manage.py test",
                "coverage run manage.py test && coverage report",
            ]}
            commands["ports"].append({"port": "8000", "service": "Django Dev Server"})
            return

        entry_files = ["main.py", "app.py", "run.py", "server.py", "wsgi.py", "asgi.py", "cli.py"]
        found_entry = None
        for ef in entry_files:
            if (self.project_path / ef).exists():
                found_entry = ef
                break

        if "fastapi" in req_content or "uvicorn" in req_content:
            app_module = "main:app" if (self.project_path / "main.py").exists() else "app:app"
            commands["run_commands"] = {
                "Linux/macOS": [
                    f"uvicorn {app_module} --reload",
                    f"uvicorn {app_module} --host 0.0.0.0 --port 8000 --reload",
                    f"uvicorn {app_module} --host 0.0.0.0 --port 8000 --workers 4  # production",
                ],
                "Windows (PowerShell)": [f"uvicorn {app_module} --reload"],
            }
            commands["ports"].append({"port": "8000", "service": "FastAPI Server"})
        elif "flask" in req_content:
            commands["run_commands"] = {
                "Linux/macOS": [
                    "export FLASK_APP=app.py", "export FLASK_ENV=development",
                    "flask run", "flask run --host=0.0.0.0 --port=5000",
                ],
                "Windows (PowerShell)": [
                    "$env:FLASK_APP = 'app.py'", "$env:FLASK_ENV = 'development'", "flask run",
                ],
                "Windows (CMD)": ["set FLASK_APP=app.py", "set FLASK_ENV=development", "flask run"],
            }
            commands["ports"].append({"port": "5000", "service": "Flask Dev Server"})
        elif found_entry:
            commands["run_commands"] = {
                "Linux/macOS": [f"python {found_entry}"],
                "Windows (PowerShell)": [f"python {found_entry}"],
            }

        if "pytest" in req_content or (self.project_path / "conftest.py").exists():
            commands["test_commands"] = {
                "All Platforms": [
                    "pytest", "pytest -v", "pytest --cov=. --cov-report=html",
                    "pytest tests/test_main.py -v  # specific file",
                ],
            }

    def _add_venv_setup(self, commands: Dict):
        req_file = self.project_path / "requirements.txt"
        commands["environment_setup"] = {
            "Linux/macOS": [
                "python3 -m venv venv", "source venv/bin/activate",
                "pip install -r requirements.txt" if req_file.exists() else "# install deps manually",
            ],
            "Windows (PowerShell)": [
                "python -m venv venv", r".\venv\Scripts\Activate.ps1",
                "pip install -r requirements.txt" if req_file.exists() else "# install deps manually",
            ],
            "Windows (CMD)": [
                "python -m venv venv", r"venv\Scripts\activate.bat",
                "pip install -r requirements.txt" if req_file.exists() else "# install deps manually",
            ],
        }
        if req_file.exists():
            commands["install_dependencies"] = {"All Platforms": ["pip install -r requirements.txt"]}

    def _detect_node_commands(self, commands: Dict):
        pkg_json = self.project_path / "package.json"
        if not pkg_json.exists():
            return
        try:
            with open(pkg_json, "r", encoding="utf-8") as f:
                pkg = json.load(f)
        except Exception:
            return

        commands["prerequisites"].extend(["Node.js 16+ installed", "npm or yarn package manager"])

        has_pnpm = (self.project_path / "pnpm-lock.yaml").exists()
        has_yarn = (self.project_path / "yarn.lock").exists()
        pkg_cmd = "pnpm" if has_pnpm else "yarn" if has_yarn else "npm"
        install_cmd = f"{pkg_cmd} install"

        commands["environment_setup"] = {
            "Linux/macOS": [
                "# Install nvm (Node Version Manager)",
                "curl -o- https://raw.githubusercontent.com/nvm-sh/nvm/v0.39.0/install.sh | bash",
                "nvm install --lts", "nvm use --lts", install_cmd,
            ],
            "Windows (PowerShell)": [
                "# Install nvm-windows from https://github.com/coreybutler/nvm-windows",
                "nvm install lts", "nvm use lts", install_cmd,
            ],
            "macOS (Homebrew)": ["brew install node", install_cmd],
        }
        commands["install_dependencies"] = {"All Platforms": [install_cmd]}

        scripts = pkg.get("scripts", {})
        run_list = []
        if scripts.get("dev"):
            run_list.append(f"{pkg_cmd} run dev  # development server")
        if scripts.get("start"):
            start_cmd = f"{pkg_cmd} start" if pkg_cmd != "npm" else "npm start"
            run_list.append(f"{start_cmd}  # production/start")
        if not run_list:
            run_list = [f"{pkg_cmd} start"]

        commands["run_commands"] = {"All Platforms": run_list}

        if scripts.get("build"):
            commands["build_commands"] = {"All Platforms": [f"{pkg_cmd} run build"]}
        if scripts.get("test"):
            commands["test_commands"] = {"All Platforms": [
                f"{pkg_cmd} test", f"{pkg_cmd} test -- --coverage  # with coverage",
            ]}

        deps = {}
        deps.update(pkg.get("dependencies", {}))
        deps.update(pkg.get("devDependencies", {}))
        if "next" in deps:
            commands["ports"].append({"port": "3000", "service": "Next.js Dev Server"})
        elif "react-scripts" in deps:
            commands["ports"].append({"port": "3000", "service": "React Dev Server"})
        elif "@angular/core" in deps:
            commands["ports"].append({"port": "4200", "service": "Angular Dev Server"})
        elif "vue" in deps:
            commands["ports"].append({"port": "5173", "service": "Vue/Vite Dev Server"})

        if scripts:
            commands["notes"].append(f"All package.json scripts: {', '.join(scripts.keys())}")

    def _detect_java_commands(self, commands: Dict):
        pom = self.project_path / "pom.xml"
        gradle = self.project_path / "build.gradle"
        if not (pom.exists() or gradle.exists()):
            return

        commands["prerequisites"].extend(["Java 11+ installed", "JAVA_HOME configured"])
        mvnw = self.project_path / "mvnw"
        gradlew = self.project_path / "gradlew"

        if pom.exists():
            mvn = "./mvnw" if mvnw.exists() else "mvn"
            mvn_w = "mvnw.cmd" if mvnw.exists() else "mvn"
            commands["environment_setup"] = {
                "Linux/macOS": ["sudo apt-get install -y openjdk-17-jdk  # Ubuntu",
                                "export JAVA_HOME=/usr/lib/jvm/java-17-openjdk-amd64", "java -version"],
                "Windows": ["choco install openjdk17", "java -version"],
                "macOS": ["brew install openjdk@17", "java -version"],
            }
            commands["install_dependencies"] = {"Linux/macOS": [f"{mvn} dependency:resolve"], "Windows": [f"{mvn_w} dependency:resolve"]}
            commands["build_commands"] = {
                "Linux/macOS": [f"{mvn} clean install", f"{mvn} clean install -DskipTests", f"{mvn} clean package"],
                "Windows": [f"{mvn_w} clean install", f"{mvn_w} clean package"],
            }
            commands["run_commands"] = {
                "Linux/macOS": [f"{mvn} spring-boot:run", "java -jar target/*.jar",
                                "java -jar target/*.jar --spring.profiles.active=dev"],
                "Windows": [f"{mvn_w} spring-boot:run", "java -jar target\\*.jar"],
            }
            commands["test_commands"] = {"Linux/macOS": [f"{mvn} test"], "Windows": [f"{mvn_w} test"]}
            commands["ports"].append({"port": "8080", "service": "Spring Boot Server"})
        elif gradle.exists():
            g = "./gradlew" if gradlew.exists() else "gradle"
            gw = "gradlew.bat" if gradlew.exists() else "gradle"
            commands["build_commands"] = {"Linux/macOS": [f"{g} build"], "Windows": [f"{gw} build"]}
            commands["run_commands"] = {"Linux/macOS": [f"{g} bootRun", "java -jar build/libs/*.jar"], "Windows": [f"{gw} bootRun"]}
            commands["test_commands"] = {"Linux/macOS": [f"{g} test"], "Windows": [f"{gw} test"]}

    def _detect_go_commands(self, commands: Dict):
        if not (self.project_path / "go.mod").exists():
            return
        commands["prerequisites"].extend(["Go 1.19+ installed", "GOPATH configured"])
        commands["environment_setup"] = {
            "Linux/macOS": ["# Install: https://go.dev/dl/", "go version", "go mod download"],
            "Windows": ["choco install golang", "go version", "go mod download"],
        }
        commands["install_dependencies"] = {"All Platforms": ["go mod download", "go mod tidy"]}
        commands["run_commands"] = {
            "Linux/macOS": ["go run .", "go build -o app .", "./app"],
            "Windows": ["go run .", "go build -o app.exe .", ".\\app.exe"],
        }
        commands["test_commands"] = {"All Platforms": ["go test ./...", "go test -v ./...", "go test -cover ./..."]}
        commands["build_commands"] = {
            "Linux": ["GOOS=linux GOARCH=amd64 go build -o app ."],
            "Windows": ["GOOS=windows GOARCH=amd64 go build -o app.exe ."],
            "macOS": ["GOOS=darwin GOARCH=amd64 go build -o app ."],
        }

    def _detect_dotnet_commands(self, commands: Dict):
        csproj = list(self.project_path.glob("**/*.csproj"))
        sln = list(self.project_path.glob("*.sln"))
        if not (csproj or sln):
            return
        commands["prerequisites"].append(".NET 6+ SDK installed")
        proj = str(sln[0].name) if sln else str(csproj[0].relative_to(self.project_path))
        commands["install_dependencies"] = {"All Platforms": [f"dotnet restore {proj}"]}
        commands["build_commands"] = {"All Platforms": [f"dotnet build {proj}", f"dotnet build {proj} --configuration Release"]}
        commands["run_commands"] = {"All Platforms": [f"dotnet run --project {proj}"]}
        commands["test_commands"] = {"All Platforms": [f"dotnet test {proj}"]}
        commands["ports"].append({"port": "5000/5001", "service": "ASP.NET Core HTTP/HTTPS"})

    def _detect_rust_commands(self, commands: Dict):
        if not (self.project_path / "Cargo.toml").exists():
            return
        commands["prerequisites"].append("Rust toolchain installed (rustup)")
        commands["environment_setup"] = {
            "Linux/macOS": ["curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh",
                            "source $HOME/.cargo/env", "rustc --version"],
            "Windows": ["# Download from https://rustup.rs/", "rustc --version"],
        }
        commands["install_dependencies"] = {"All Platforms": ["cargo fetch"]}
        commands["build_commands"] = {"All Platforms": ["cargo build", "cargo build --release"]}
        commands["run_commands"] = {"All Platforms": ["cargo run", "cargo run --release"]}
        commands["test_commands"] = {"All Platforms": ["cargo test", "cargo test -- --nocapture"]}

    def _detect_docker_commands(self, commands: Dict):
        dockerfile = self.project_path / "Dockerfile"
        compose_yml = self.project_path / "docker-compose.yml"
        compose_yaml = self.project_path / "docker-compose.yaml"
        has_dockerfile = dockerfile.exists()
        has_compose = compose_yml.exists() or compose_yaml.exists()
        compose_file = "docker-compose.yml" if compose_yml.exists() else "docker-compose.yaml" if compose_yaml.exists() else None

        if not (has_dockerfile or has_compose):
            return

        project_name = self.project_path.name.lower().replace(" ", "-")
        docker_cmds = {"Linux/macOS": [], "Windows (PowerShell)": []}

        if has_dockerfile:
            docker_cmds["Linux/macOS"].extend([
                f"# Build Docker image",
                f"docker build -t {project_name}:latest .",
                f"", f"# Run container",
                f"docker run -d --name {project_name} -p 8080:8080 {project_name}:latest",
                f"", f"# View logs",
                f"docker logs -f {project_name}",
                f"", f"# Stop & remove",
                f"docker stop {project_name} && docker rm {project_name}",
            ])
            docker_cmds["Windows (PowerShell)"].extend([
                f"docker build -t {project_name}:latest .",
                f"docker run -d --name {project_name} -p 8080:8080 {project_name}:latest",
                f"docker logs -f {project_name}",
                f"docker stop {project_name}; docker rm {project_name}",
            ])

        if has_compose and compose_file:
            dc = f"docker-compose -f {compose_file}"
            docker_cmds["Linux/macOS"].extend([
                "", "# --- Docker Compose ---", "",
                f"{dc} up -d", f"{dc} up --build -d",
                f"{dc} logs -f", f"{dc} down", f"{dc} down -v",
                f"{dc} exec web bash  # shell into service",
            ])
            docker_cmds["Windows (PowerShell)"].extend([
                "", f"{dc} up -d", f"{dc} up --build -d",
                f"{dc} logs -f", f"{dc} down",
            ])

        commands["docker_commands"] = docker_cmds

    def _detect_makefile_commands(self, commands: Dict):
        makefile = self.project_path / "Makefile"
        if not makefile.exists():
            return
        try:
            content = makefile.read_text(encoding="utf-8")
            targets = re.findall(r'^([a-zA-Z][a-zA-Z0-9_-]*)\s*:', content, re.MULTILINE)
            if targets:
                commands["notes"].insert(0, "Makefile detected - use 'make help' for all targets")
                commands["notes"].append(f"Makefile targets: {', '.join(targets[:20])}")
        except Exception:
            pass

    def _detect_env_variables(self, commands: Dict):
        for ef in [".env.example", ".env.sample", ".env.template"]:
            env_file = self.project_path / ef
            if env_file.exists():
                try:
                    content = env_file.read_text(encoding="utf-8")
                    for line in content.split("\n"):
                        line = line.strip()
                        if line and not line.startswith("#") and "=" in line:
                            key = line.split("=")[0].strip()
                            if key:
                                commands["environment_variables"].append(key)
                    if commands["environment_variables"]:
                        commands["notes"].append(f"Copy {ef} to .env and fill in values")
                except Exception:
                    pass
                break

    def _detect_ports(self, commands: Dict):
        for cf_name in ["docker-compose.yml", "docker-compose.yaml"]:
            cf = self.project_path / cf_name
            if cf.exists():
                try:
                    with open(cf, "r", encoding="utf-8") as f:
                        compose = yaml.safe_load(f)
                    if isinstance(compose, dict):
                        for svc_name, svc_config in compose.get("services", {}).items():
                            if isinstance(svc_config, dict):
                                for port in svc_config.get("ports", []):
                                    port_str = str(port)
                                    if ":" in port_str:
                                        commands["ports"].append({"port": port_str.split(":")[0], "service": svc_name})
                except Exception:
                    pass

    # ── DevOps Push Instructions ──────────────────────────────────────

    def detect_devops_push_instructions(self, pipeline_info: List[Dict], git_info: Dict) -> Dict[str, Any]:
        instructions = {
            "git_workflow": [], "platforms": {},
            "branch_strategy": {}, "pre_push_checklist": [],
            "environment_promotion": [],
        }

        platforms_detected = set()
        for p in pipeline_info:
            if p.get("type"):
                platforms_detected.add(p["type"])

        remote_url = git_info.get("remote_url", "")
        if "github.com" in remote_url:
            platforms_detected.add("GitHub Actions")
        if "dev.azure.com" in remote_url or "visualstudio.com" in remote_url:
            platforms_detected.add("Azure DevOps")

        instructions["git_workflow"] = self._build_git_workflow(git_info)
        instructions["branch_strategy"] = {
            "main_branches": ["main", "master"],
            "development_branch": "develop",
            "feature_pattern": "feature/*",
            "hotfix_pattern": "hotfix/*",
            "release_pattern": "release/*",
        }

        for pn in platforms_detected:
            if "GitHub" in pn:
                instructions["platforms"]["GitHub Actions"] = self._github_push(git_info, pipeline_info)
            elif "Azure" in pn:
                instructions["platforms"]["Azure DevOps"] = self._azure_devops_push(git_info, pipeline_info)
            elif "Jenkins" in pn:
                instructions["platforms"]["Jenkins"] = self._jenkins_push(git_info, pipeline_info)
            elif "GitLab" in pn:
                instructions["platforms"]["GitLab CI"] = self._gitlab_push(git_info, pipeline_info)

        if not instructions["platforms"]:
            instructions["platforms"]["Generic Git"] = {
                "platform": "Generic Git",
                "push_workflow": {"All Platforms": [
                    "git add .", 'git commit -m "your message"', "git push origin main",
                ]},
            }

        instructions["pre_push_checklist"] = [
            "All tests pass locally",
            "Code changes reviewed with git diff",
            "No secrets or sensitive data committed",
            "Documentation updated if needed",
            "Environment variables not hardcoded",
            ".gitignore properly configured",
            "Commit messages follow conventions",
            "Latest changes pulled to avoid conflicts",
        ]
        instructions["environment_promotion"] = [
            {"step": "1. Development", "action": "Push feature branch → triggers CI build & tests", "branch": "feature/*, develop"},
            {"step": "2. Staging", "action": "Merge to staging/develop → triggers staging deployment", "branch": "staging, develop"},
            {"step": "3. Production", "action": "Merge to main/master → triggers production deployment", "branch": "main, master"},
        ]
        return instructions

    def _build_git_workflow(self, git_info: Dict) -> List[Dict]:
        branch = git_info.get("current_branch", "main")
        return [
            {"step": "1. Check Status", "All Platforms": ["git status", "git branch --show-current", "git log --oneline -10"]},
            {"step": "2. Pull Latest", "All Platforms": [f"git fetch origin --prune", f"git pull --rebase origin {branch}"]},
            {"step": "3. Create Branch", "All Platforms": ["git checkout -b feature/your-feature-name"]},
            {"step": "4. Stage Files", "All Platforms": ["git diff", "git add .", "git add -p  # interactive"]},
            {"step": "5. Commit", "All Platforms": [
                'git commit -m "feat: add new feature"',
                "# Commit types: feat, fix, docs, style, refactor, test, chore, ci",
            ]},
            {"step": "6. Push", "All Platforms": [
                "git push -u origin feature/your-feature-name",
                "git push origin HEAD",
            ]},
        ]

    def _github_push(self, git_info: Dict, pipeline_info: List[Dict]) -> Dict:
        remote = git_info.get("remote_url", "")
        match = re.search(r'github\.com[:/]([^/]+)/([^/.]+)', remote)
        repo = f"{match.group(1)}/{match.group(2)}" if match else "owner/repo"
        wf_files = [p["file"] for p in pipeline_info if "GitHub" in p.get("type", "")]
        triggers = []
        for p in pipeline_info:
            if "GitHub" in p.get("type", ""):
                triggers.extend(p.get("triggers", []))

        return {
            "platform": "GitHub Actions",
            "prerequisites": ["GitHub account with repo access", "Git configured with SSH or token"],
            "initial_setup": {
                "Linux/macOS": [
                    'git config --global user.name "Your Name"',
                    'git config --global user.email "you@email.com"',
                    "ssh-keygen -t ed25519 -C 'you@email.com'  # SSH key",
                    "# Add key: GitHub → Settings → SSH keys",
                    f"git clone git@github.com:{repo}.git",
                ],
                "Windows (PowerShell)": [
                    'git config --global user.name "Your Name"',
                    'git config --global user.email "you@email.com"',
                    "winget install GitHub.cli", "gh auth login",
                    f"git clone https://github.com/{repo}.git",
                ],
            },
            "push_workflow": {"All Platforms": [
                "git checkout -b feature/my-feature",
                "git add .", 'git commit -m "feat: your changes"',
                "git push origin feature/my-feature",
                f"# Pipeline triggers automatically! Monitor: https://github.com/{repo}/actions",
                f"gh pr create --title 'My Feature' --body 'Description' --base main",
                "gh pr merge --merge  # after approval",
            ]},
            "manage_secrets": {"All Platforms": [
                "gh secret set MY_SECRET --body 'value'", "gh secret list",
                f"# Web: https://github.com/{repo}/settings/secrets/actions",
            ]},
            "monitor": {
                "CLI": ["gh run list", "gh run watch", "gh run view --log", "gh run rerun --failed"],
                "Web": [f"https://github.com/{repo}/actions", f"https://github.com/{repo}/pulls"],
            },
            "workflow_files": wf_files, "auto_triggers": triggers,
        }

    def _azure_devops_push(self, git_info: Dict, pipeline_info: List[Dict]) -> Dict:
        remote = git_info.get("remote_url", "")
        org, proj, repo = "your-org", "your-project", "your-repo"
        match = re.search(r'dev\.azure\.com/([^/]+)/([^/]+)/_git/([^/]+)', remote)
        if match:
            org, proj, repo = match.group(1), match.group(2), match.group(3)
        else:
            match = re.search(r'([^.]+)\.visualstudio\.com/([^/]+)/_git/([^/]+)', remote)
            if match:
                org, proj, repo = match.group(1), match.group(2), match.group(3)

        pf = [p["file"] for p in pipeline_info if "Azure" in p.get("type", "")]
        return {
            "platform": "Azure DevOps",
            "prerequisites": ["Azure DevOps account", "Azure CLI with devops extension", "Git credentials configured"],
            "initial_setup": {
                "Linux/macOS": [
                    "curl -sL https://aka.ms/InstallAzureCLIDeb | sudo bash  # or brew install azure-cli",
                    "az extension add --name azure-devops", "az login",
                    f"az devops configure --defaults organization=https://dev.azure.com/{org} project={proj}",
                    f"git clone https://dev.azure.com/{org}/{proj}/_git/{repo}",
                ],
                "Windows (PowerShell)": [
                    "winget install Microsoft.AzureCLI",
                    "az extension add --name azure-devops", "az login",
                    f"az devops configure --defaults organization=https://dev.azure.com/{org} project={proj}",
                    f"git clone https://dev.azure.com/{org}/{proj}/_git/{repo}",
                ],
            },
            "push_workflow": {"All Platforms": [
                "git checkout -b feature/my-feature",
                "git add .", 'git commit -m "feat: your changes"',
                "git push origin feature/my-feature",
                f"# Pipeline triggers! Monitor: https://dev.azure.com/{org}/{proj}/_build",
                "az repos pr create --title 'My Feature' --description 'Changes' --source-branch feature/my-feature --target-branch main",
                "az repos pr list --status active",
            ]},
            "trigger_pipeline_manually": {"All Platforms": [
                f"az pipelines list --project {proj}",
                f"az pipelines run --name 'pipeline-name' --project {proj}",
                f"az pipelines runs list --project {proj}",
            ]},
            "manage_variables": {"All Platforms": [
                "az pipelines variable-group create --name 'MyVarGroup' --variables key1=value1",
                "az pipelines variable-group variable create --group-id <ID> --name MY_SECRET --value 'val' --secret true",
            ]},
            "monitor": {
                "CLI": [f"az pipelines runs list --project {proj}", "az pipelines runs show --id <RUN_ID>"],
                "Web": [f"https://dev.azure.com/{org}/{proj}/_build", f"https://dev.azure.com/{org}/{proj}/_git/{repo}"],
            },
            "pipeline_files": pf,
        }

    def _jenkins_push(self, git_info: Dict, pipeline_info: List[Dict]) -> Dict:
        jf = [p["file"] for p in pipeline_info if "Jenkins" in p.get("type", "")]
        return {
            "platform": "Jenkins",
            "prerequisites": ["Jenkins server accessible", "Jenkins CLI or web access", "Git plugin configured"],
            "initial_setup": {"All Platforms": [
                "wget http://jenkins-server:8080/jnlpJars/jenkins-cli.jar",
                "java -jar jenkins-cli.jar -s http://jenkins-server:8080/ -auth admin:token who-am-i",
            ]},
            "push_workflow": {"All Platforms": [
                "# Jenkins uses webhooks - push triggers build automatically",
                "git add .", 'git commit -m "feat: changes"', "git push origin feature/my-feature",
                "",
                "# Manual trigger via CLI:",
                "java -jar jenkins-cli.jar -s http://jenkins-server:8080/ -auth admin:token build 'job-name' -s -v",
                "",
                "# Manual trigger via REST API:",
                "curl -X POST 'http://jenkins-server:8080/job/job-name/build' --user admin:token",
            ]},
            "manage_credentials": {"Steps": [
                "1. Jenkins → Manage Jenkins → Credentials",
                "2. Click (global) → Add Credentials",
                "3. Choose type: Username/Password, SSH Key, or Secret text",
                "4. Set ID (referenced in Jenkinsfile)",
                "5. Save",
            ]},
            "monitor": {
                "CLI": ["java -jar jenkins-cli.jar ... console 'job-name' <build-num>", "java -jar jenkins-cli.jar ... list-jobs"],
                "Web": ["http://jenkins-server:8080", "http://jenkins-server:8080/blue"],
            },
            "jenkinsfile_info": jf,
        }

    def _gitlab_push(self, git_info: Dict, pipeline_info: List[Dict]) -> Dict:
        remote = git_info.get("remote_url", "")
        match = re.search(r'gitlab\.com[:/]([^/]+/[^/.]+)', remote)
        repo = match.group(1) if match else "group/project"
        return {
            "platform": "GitLab CI",
            "prerequisites": ["GitLab account", "glab CLI installed"],
            "initial_setup": {"Linux/macOS": [
                "brew install glab  # or apt install", "glab auth login",
                f"git clone git@gitlab.com:{repo}.git",
            ], "Windows": ["winget install glab", "glab auth login"]},
            "push_workflow": {"All Platforms": [
                "git checkout -b feature/my-feature",
                "git add .", 'git commit -m "feat: changes"',
                "git push origin feature/my-feature",
                f"# Monitor: https://gitlab.com/{repo}/-/pipelines",
                "glab mr create --title 'Feature' --target-branch main",
                "glab ci run  # trigger manually", "glab ci view  # view status",
            ]},
            "monitor": {
                "CLI": ["glab ci list", "glab ci view", "glab ci trace"],
                "Web": [f"https://gitlab.com/{repo}/-/pipelines", f"https://gitlab.com/{repo}/-/merge_requests"],
            },
        }


# ===========================================================================
# DOCUMENT GENERATOR
# ===========================================================================

class DocumentGenerator:
    """Generates a professional Word document from project analysis."""

    def __init__(self):
        self.doc = Document()
        self._setup_styles()

    def _setup_styles(self):
        styles = self.doc.styles

        # Project Title
        if "ProjectTitle" not in [s.name for s in styles]:
            title_style = styles.add_style("ProjectTitle", WD_STYLE_TYPE.PARAGRAPH)
        else:
            title_style = styles["ProjectTitle"]
        tf = title_style.font
        tf.name = "Times New Roman"
        tf.size = Pt(22)
        tf.bold = True
        tf.color.rgb = RGBColor(0, 0, 0)
        title_style.paragraph_format.alignment = WD_ALIGN_PARAGRAPH.CENTER
        title_style.paragraph_format.space_after = Pt(12)

        # Heading 1 - Times New Roman 16
        h1 = styles["Heading 1"]
        h1.font.name = "Times New Roman"
        h1.font.size = Pt(16)
        h1.font.bold = True
        h1.font.color.rgb = RGBColor(0, 0, 0)
        h1.paragraph_format.space_before = Pt(18)
        h1.paragraph_format.space_after = Pt(8)

        # Heading 2 - Calibri 14
        h2 = styles["Heading 2"]
        h2.font.name = "Calibri"
        h2.font.size = Pt(14)
        h2.font.bold = True
        h2.font.color.rgb = RGBColor(0, 0, 0)
        h2.paragraph_format.space_before = Pt(14)
        h2.paragraph_format.space_after = Pt(6)

        # Heading 3
        h3 = styles["Heading 3"]
        h3.font.name = "Calibri"
        h3.font.size = Pt(13)
        h3.font.bold = True
        h3.font.color.rgb = RGBColor(0, 0, 0)

        # Normal - Calibri 12
        normal = styles["Normal"]
        normal.font.name = "Calibri"
        normal.font.size = Pt(12)
        normal.font.color.rgb = RGBColor(0, 0, 0)
        normal.paragraph_format.space_after = Pt(4)
        normal.paragraph_format.line_spacing = 1.15

        # List Bullet
        if "List Bullet" in [s.name for s in styles]:
            lb = styles["List Bullet"]
            lb.font.name = "Calibri"
            lb.font.size = Pt(12)
            lb.font.color.rgb = RGBColor(0, 0, 0)

        for section in self.doc.sections:
            section.top_margin = Cm(2.54)
            section.bottom_margin = Cm(2.54)
            section.left_margin = Cm(2.54)
            section.right_margin = Cm(2.54)

    def _add_title(self, text: str):
        return self.doc.add_paragraph(text, style="ProjectTitle")

    def _add_heading(self, text: str, level: int = 1):
        return self.doc.add_heading(text, level=level)

    def _add_paragraph(self, text: str, bold: bool = False, italic: bool = False):
        para = self.doc.add_paragraph()
        run = para.add_run(text)
        run.font.name = "Calibri"
        run.font.size = Pt(12)
        run.font.color.rgb = RGBColor(0, 0, 0)
        run.bold = bold
        run.italic = italic
        return para

    def _add_bullet_list(self, items: List[str]):
        for item in items:
            para = self.doc.add_paragraph(style="List Bullet")
            run = para.add_run(str(item))
            run.font.name = "Calibri"
            run.font.size = Pt(12)
            run.font.color.rgb = RGBColor(0, 0, 0)

    def _add_numbered_list(self, items: List[str]):
        for i, item in enumerate(items, 1):
            para = self.doc.add_paragraph()
            run = para.add_run(f"{i}. {item}")
            run.font.name = "Calibri"
            run.font.size = Pt(12)
            run.font.color.rgb = RGBColor(0, 0, 0)
            para.paragraph_format.left_indent = Inches(0.5)

    def _add_table(self, headers: List[str], rows: List[List[str]], color_scheme: str = "default"):
        table = self.doc.add_table(rows=1 + len(rows), cols=len(headers))
        table.alignment = WD_TABLE_ALIGNMENT.CENTER
        table.style = "Table Grid"

        schemes = {
            "default": {"hbg": "2E86AB", "hfg": "FFFFFF", "even": "E8F4F8", "odd": "FFFFFF"},
            "green": {"hbg": "1B4332", "hfg": "FFFFFF", "even": "D8F3DC", "odd": "FFFFFF"},
            "purple": {"hbg": "7209B7", "hfg": "FFFFFF", "even": "F3E5F5", "odd": "FFFFFF"},
            "orange": {"hbg": "E85D04", "hfg": "FFFFFF", "even": "FFF3E0", "odd": "FFFFFF"},
            "berry": {"hbg": "A23B72", "hfg": "FFFFFF", "even": "FCE4EC", "odd": "FFFFFF"},
            "teal": {"hbg": "006D77", "hfg": "FFFFFF", "even": "E0F2F1", "odd": "FFFFFF"},
        }
        s = schemes.get(color_scheme, schemes["default"])

        header_row = table.rows[0]
        for i, header in enumerate(headers):
            cell = header_row.cells[i]
            cell.text = ""
            para = cell.paragraphs[0]
            run = para.add_run(header)
            run.font.name = "Calibri"
            run.font.size = Pt(11)
            run.font.bold = True
            run.font.color.rgb = RGBColor.from_string(s["hfg"])
            para.alignment = WD_ALIGN_PARAGRAPH.CENTER
            shading = parse_xml(f'<w:shd {nsdecls("w")} w:fill="{s["hbg"]}"/>')
            cell._tc.get_or_add_tcPr().append(shading)

        for row_idx, row_data in enumerate(rows):
            row = table.rows[row_idx + 1]
            bg = s["even"] if row_idx % 2 == 0 else s["odd"]
            for col_idx, cell_text in enumerate(row_data):
                if col_idx < len(row.cells):
                    cell = row.cells[col_idx]
                    cell.text = ""
                    para = cell.paragraphs[0]
                    run = para.add_run(str(cell_text))
                    run.font.name = "Calibri"
                    run.font.size = Pt(11)
                    run.font.color.rgb = RGBColor(0, 0, 0)
                    shading = parse_xml(f'<w:shd {nsdecls("w")} w:fill="{bg}"/>')
                    cell._tc.get_or_add_tcPr().append(shading)

        self.doc.add_paragraph()
        return table

    def _add_code_block(self, code: str, max_lines: int = 40):
        lines = code.split("\n")
        if len(lines) > max_lines:
            lines = lines[:max_lines] + [f"... ({len(code.split(chr(10))) - max_lines} more lines)"]

        for line in lines:
            para = self.doc.add_paragraph()
            run = para.add_run(line)
            run.font.name = "Consolas"
            run.font.size = Pt(9)
            run.font.color.rgb = RGBColor(0, 0, 0)
            para.paragraph_format.space_after = Pt(0)
            para.paragraph_format.space_before = Pt(0)
            para.paragraph_format.left_indent = Inches(0.5)
            shading = parse_xml(f'<w:shd {nsdecls("w")} w:fill="F5F5F0"/>')
            para._p.get_or_add_pPr().append(shading)

    def _add_horizontal_line(self):
        para = self.doc.add_paragraph()
        pPr = para._p.get_or_add_pPr()
        pBdr = parse_xml(f'<w:pBdr {nsdecls("w")}><w:bottom w:val="single" w:sz="6" w:space="1" w:color="2E86AB"/></w:pBdr>')
        pPr.append(pBdr)

    def _format_size(self, size_bytes: int) -> str:
        if size_bytes < 1024:
            return f"{size_bytes} B"
        elif size_bytes < 1024 * 1024:
            return f"{size_bytes / 1024:.1f} KB"
        elif size_bytes < 1024 * 1024 * 1024:
            return f"{size_bytes / (1024 * 1024):.1f} MB"
        return f"{size_bytes / (1024 * 1024 * 1024):.1f} GB"

    def _render_tree(self, tree: Dict, lines: List[str], prefix: str = ""):
        items = sorted(tree.keys())
        for i, key in enumerate(items):
            is_last = (i == len(items) - 1)
            value = tree[key]
            connector = "└── " if is_last else "├── "
            name = Path(key).name if ("/" in key or "\\" in key) else key

            if isinstance(value, dict) and "name" not in value:
                lines.append(f"{prefix}{connector}📁 {name}/")
                new_prefix = prefix + ("    " if is_last else "│   ")
                self._render_tree(value, lines, new_prefix)
            else:
                if isinstance(value, dict):
                    size = self._format_size(value.get("size", 0))
                    lines.append(f"{prefix}{connector}📄 {name} ({size})")
                else:
                    lines.append(f"{prefix}{connector}📄 {name}")

    def _collect_all_files(self, tree: Dict, result: List[Dict]):
        for key, value in tree.items():
            if isinstance(value, dict):
                if "name" in value and "size" in value:
                    value["path"] = key
                    result.append(value)
                else:
                    self._collect_all_files(value, result)

    # ── GENERATE COMPLETE DOCUMENT ────────────────────────────────────

    def generate(
        self, project_name: str, project_type: str, project_summary: str,
        tech_stack: Dict, pipeline_info: List[Dict], file_tree: Dict,
        file_stats: Dict, git_info: Dict, project_path: str,
        local_dev: Dict, deploy_instructions: Dict, output_path: str,
    ):
        colors = ["default", "green", "purple", "orange", "berry", "teal"]

        # ════════════════════════════════════════════════════════════
        # COVER PAGE
        # ════════════════════════════════════════════════════════════
        for _ in range(4):
            self.doc.add_paragraph()
        self._add_title("PROJECT DOCUMENTATION")
        self._add_horizontal_line()

        para = self.doc.add_paragraph()
        para.alignment = WD_ALIGN_PARAGRAPH.CENTER
        run = para.add_run(project_name.upper())
        run.font.name = "Times New Roman"
        run.font.size = Pt(18)
        run.font.bold = True
        run.font.color.rgb = RGBColor(0, 0, 0)

        para = self.doc.add_paragraph()
        para.alignment = WD_ALIGN_PARAGRAPH.CENTER
        run = para.add_run(project_type)
        run.font.name = "Calibri"
        run.font.size = Pt(14)
        run.font.italic = True
        run.font.color.rgb = RGBColor(0, 0, 0)

        para = self.doc.add_paragraph()
        para.alignment = WD_ALIGN_PARAGRAPH.CENTER
        run = para.add_run(
            f"\nGenerated: {datetime.now().strftime('%B %d, %Y %H:%M')}"
            f"\nPlatform: {platform.system()} {platform.release()}"
            f"\nPath: {project_path}"
        )
        run.font.name = "Calibri"
        run.font.size = Pt(11)
        run.font.color.rgb = RGBColor(0, 0, 0)

        self.doc.add_page_break()

        # ════════════════════════════════════════════════════════════
        # TABLE OF CONTENTS
        # ════════════════════════════════════════════════════════════
        self._add_heading("Table of Contents", level=1)
        toc = [
            "1. Executive Summary",
            "2. Project Overview",
            "   2.1 Project Information",
            "   2.2 Technology Stack",
            "   2.3 Repository Information",
            "3. Project Structure",
            "   3.1 Directory Overview",
            "   3.2 File Statistics",
            "   3.3 File Categories",
            "   3.4 Largest Files",
            "4. Local Development & Run Guide",
            "   4.1 Prerequisites",
            "   4.2 Environment Setup",
            "   4.3 Install Dependencies",
            "   4.4 Run Project Locally",
            "   4.5 Build Project",
            "   4.6 Run Tests",
            "   4.7 Run with Docker",
            "5. Push & Deploy to DevOps",
            "   5.1 Pre-Push Checklist",
            "   5.2 Git Workflow",
            "   5.3 Branch Strategy",
            "   5.4 Platform-Specific Instructions",
            "   5.5 Environment Promotion",
            "6. CI/CD Pipeline Analysis",
            "   6.1 Pipeline Overview",
            "   6.2 Detailed Configuration",
            "   6.3 Stages & Jobs",
            "   6.4 Variables & Parameters",
            "7. Environment Configuration",
            "8. Complete File Listing",
            "9. Appendix",
        ]
        for item in toc:
            para = self.doc.add_paragraph()
            run = para.add_run(item)
            run.font.name = "Calibri"
            run.font.size = Pt(12)
            run.font.color.rgb = RGBColor(0, 0, 0)
            if not item.startswith("   "):
                run.bold = True

        self.doc.add_page_break()

        # ════════════════════════════════════════════════════════════
        # 1. EXECUTIVE SUMMARY
        # ════════════════════════════════════════════════════════════
        self._add_heading("1. Executive Summary", level=1)
        self._add_paragraph(project_summary)
        self._add_horizontal_line()

        # ════════════════════════════════════════════════════════════
        # 2. PROJECT OVERVIEW
        # ════════════════════════════════════════════════════════════
        self._add_heading("2. Project Overview", level=1)

        self._add_heading("2.1 Project Information", level=2)
        info_data = [
            ["Project Name", project_name],
            ["Project Type", project_type],
            ["Project Path", str(project_path)],
            ["Operating System", f"{platform.system()} {platform.release()}"],
            ["Document Generated", datetime.now().strftime("%Y-%m-%d %H:%M:%S")],
            ["Total Files", str(file_stats.get("total_files", 0))],
            ["Total Directories", str(file_stats.get("total_directories", 0))],
            ["Total Size", self._format_size(file_stats.get("total_size", 0))],
        ]
        self._add_table(["Property", "Value"], info_data, "teal")

        self._add_heading("2.2 Technology Stack", level=2)
        if tech_stack:
            for category, items in tech_stack.items():
                self._add_heading(f"  {category}", level=3)
                self._add_bullet_list(items)
        else:
            self._add_paragraph("No specific technology stack detected.")

        self._add_heading("2.3 Repository Information", level=2)
        if git_info.get("is_git_repo"):
            gd = []
            if git_info["remote_url"]:
                gd.append(["Remote URL", git_info["remote_url"]])
            if git_info["current_branch"]:
                gd.append(["Current Branch", git_info["current_branch"]])
            if git_info["last_commit"]:
                gd.append(["Last Commit", git_info["last_commit"]])
            if git_info["last_commit_author"]:
                gd.append(["Last Author", git_info["last_commit_author"]])
            if git_info["last_commit_date"]:
                gd.append(["Last Commit Date", git_info["last_commit_date"]])
            gd.append(["Total Commits", str(git_info.get("total_commits", 0))])
            if gd:
                self._add_table(["Property", "Value"], gd, "green")
            if git_info.get("contributors"):
                self._add_heading("Contributors", level=3)
                cr = [[c["name"], str(c["commits"])] for c in git_info["contributors"]]
                self._add_table(["Contributor", "Commits"], cr, "purple")
        else:
            self._add_paragraph("This project is not tracked by Git or Git is not available.")

        self.doc.add_page_break()

        # ════════════════════════════════════════════════════════════
        # 3. PROJECT STRUCTURE
        # ════════════════════════════════════════════════════════════
        self._add_heading("3. Project Structure", level=1)

        self._add_heading("3.1 Directory Overview", level=2)
        self._add_paragraph("The following is the directory structure of the project:")
        tree_lines = []
        self._render_tree(file_tree, tree_lines)
        if tree_lines:
            tree_text = "\n".join(tree_lines[:100])
            if len(tree_lines) > 100:
                tree_text += f"\n... ({len(tree_lines) - 100} more entries)"
            self._add_code_block(tree_text, 100)

        self._add_heading("3.2 File Statistics", level=2)
        self._add_bullet_list([
            f"Total Files: {file_stats.get('total_files', 0)}",
            f"Total Directories: {file_stats.get('total_directories', 0)}",
            f"Total Size: {self._format_size(file_stats.get('total_size', 0))}",
        ])

        ext_stats = file_stats.get("by_extension", {})
        if ext_stats:
            self._add_heading("Files by Extension", level=3)
            ext_sorted = sorted(ext_stats.items(), key=lambda x: x[1], reverse=True)[:20]
            self._add_table(["Extension", "Count"],
                            [[ext or "(none)", str(c)] for ext, c in ext_sorted], "orange")

        self._add_heading("3.3 File Categories", level=2)
        cat_stats = file_stats.get("by_category", {})
        if cat_stats:
            cat_sorted = sorted(cat_stats.items(), key=lambda x: x[1], reverse=True)
            self._add_table(["Category", "Count"], [[c, str(n)] for c, n in cat_sorted], "berry")

        self._add_heading("3.4 Largest Files", level=2)
        largest = file_stats.get("largest_files", [])
        if largest:
            lr = [[f.get("path", f.get("name", "")), self._format_size(f.get("size", 0)),
                   f.get("modified", "")] for f in largest[:10]]
            self._add_table(["File Path", "Size", "Modified"], lr, "teal")

        self.doc.add_page_break()

        # ════════════════════════════════════════════════════════════
        # 4. LOCAL DEVELOPMENT & RUN GUIDE
        # ════════════════════════════════════════════════════════════
        self._add_heading("4. Local Development & Run Guide", level=1)
        self._add_paragraph(
            "This section provides step-by-step instructions for setting up the project locally, "
            "running it on your machine (Linux, Windows, macOS), building, and testing."
        )

        # 4.1 Prerequisites
        self._add_heading("4.1 Prerequisites", level=2)
        prereqs = local_dev.get("prerequisites", [])
        if prereqs:
            self._add_bullet_list(list(set(prereqs)))
        else:
            self._add_paragraph("No specific prerequisites detected.")

        ports = local_dev.get("ports", [])
        if ports:
            self._add_heading("Required Ports", level=3)
            self._add_table(["Port", "Service"], [[p["port"], p["service"]] for p in ports], "teal")

        # 4.2 Environment Setup
        self._add_heading("4.2 Environment Setup", level=2)
        env_vars = local_dev.get("environment_variables", [])
        if env_vars:
            self._add_heading("Required Environment Variables", level=3)
            self._add_paragraph("Copy the example .env file and configure:")
            self._add_bullet_list(env_vars)
            self._add_code_block("# Linux/macOS\ncp .env.example .env\nnano .env\n\n# Windows\ncopy .env.example .env\nnotepad .env")

        env_setup = local_dev.get("environment_setup", {})
        if env_setup:
            self._add_heading("Runtime Environment Setup", level=3)
            for pname, cmds in env_setup.items():
                self._add_heading(f"  {pname}", level=3)
                if isinstance(cmds, list):
                    self._add_code_block("\n".join(cmds))

        # 4.3 Install Dependencies
        self._add_heading("4.3 Install Dependencies", level=2)
        install = local_dev.get("install_dependencies", {})
        if install:
            for pname, cmds in install.items():
                self._add_heading(pname, level=3)
                if isinstance(cmds, list):
                    self._add_code_block("\n".join(cmds))
        else:
            self._add_paragraph("No specific dependency installation commands detected.")

        # 4.4 Run Locally
        self._add_heading("4.4 Run Project Locally", level=2)
        run_cmds = local_dev.get("run_commands", {})
        if run_cmds:
            for pname, cmds in run_cmds.items():
                self._add_heading(f"  {pname}", level=3)
                if isinstance(cmds, list):
                    self._add_code_block("\n".join(cmds))
        else:
            self._add_paragraph("No specific run commands detected. Refer to README.")

        # 4.5 Build
        build_cmds = local_dev.get("build_commands", {})
        if build_cmds:
            self._add_heading("4.5 Build Project", level=2)
            for pname, cmds in build_cmds.items():
                self._add_heading(pname, level=3)
                if isinstance(cmds, list):
                    self._add_code_block("\n".join(cmds))

        # 4.6 Tests
        test_cmds = local_dev.get("test_commands", {})
        if test_cmds:
            self._add_heading("4.6 Run Tests Locally", level=2)
            for pname, cmds in test_cmds.items():
                self._add_heading(pname, level=3)
                if isinstance(cmds, list):
                    self._add_code_block("\n".join(cmds))

        # 4.7 Docker
        docker_cmds = local_dev.get("docker_commands", {})
        if docker_cmds:
            self._add_heading("4.7 Run with Docker", level=2)
            self._add_paragraph(
                "Docker lets you run the project in an isolated container without "
                "installing dependencies directly on your machine."
            )
            for pname, cmds in docker_cmds.items():
                self._add_heading(pname, level=3)
                if isinstance(cmds, list):
                    self._add_code_block("\n".join(cmds))

        notes = local_dev.get("notes", [])
        if notes:
            self._add_heading("Notes & Tips", level=3)
            self._add_bullet_list(notes)

        self.doc.add_page_break()

        # ════════════════════════════════════════════════════════════
        # 5. PUSH & DEPLOY TO DEVOPS
        # ════════════════════════════════════════════════════════════
        self._add_heading("5. Push & Deploy to DevOps Environments", level=1)
        self._add_paragraph(
            "This section covers the complete workflow for pushing code from your local "
            "machine to remote DevOps platforms and triggering CI/CD pipelines."
        )

        # 5.1 Pre-Push Checklist
        self._add_heading("5.1 Pre-Push Checklist", level=2)
        checklist = deploy_instructions.get("pre_push_checklist", [])
        if checklist:
            for item in checklist:
                para = self.doc.add_paragraph()
                run = para.add_run(f"☐  {item}")
                run.font.name = "Calibri"
                run.font.size = Pt(12)
                run.font.color.rgb = RGBColor(0, 0, 0)
                para.paragraph_format.left_indent = Inches(0.3)

        # 5.2 Git Workflow
        self._add_heading("5.2 Standard Git Workflow", level=2)
        git_wf = deploy_instructions.get("git_workflow", [])
        for step_info in git_wf:
            self._add_heading(step_info.get("step", ""), level=3)
            for pname, cmds in step_info.items():
                if pname != "step" and isinstance(cmds, list):
                    self._add_code_block("\n".join(cmds))

        # 5.3 Branch Strategy
        self._add_heading("5.3 Branch Strategy", level=2)
        branch_rows = [
            ["main / master", "Production-ready code", "Protected, requires PR"],
            ["develop", "Integration branch", "Merge feature branches here"],
            ["feature/*", "New features", "Branch from develop, PR to develop"],
            ["hotfix/*", "Critical fixes", "Branch from main, PR to main + develop"],
            ["release/*", "Release prep", "Branch from develop, PR to main"],
        ]
        self._add_table(["Branch", "Purpose", "Workflow"], branch_rows, "orange")

        # 5.4 Platform-Specific Instructions
        self._add_heading("5.4 Platform-Specific Instructions", level=2)
        platforms = deploy_instructions.get("platforms", {})
        for ci, (pname, pdata) in enumerate(platforms.items()):
            color = colors[ci % len(colors)]
            self._add_heading(f"Platform: {pname}", level=2)

            for section_key, section_label in [
                ("prerequisites", "Prerequisites"),
                ("initial_setup", "Initial Setup"),
                ("push_workflow", "Push & Deploy Workflow"),
                ("trigger_pipeline_manually", "Trigger Pipeline Manually"),
                ("manage_secrets", "Manage Secrets"),
                ("manage_variables", "Manage Variables"),
                ("manage_credentials", "Manage Credentials"),
            ]:
                section_data = pdata.get(section_key)
                if not section_data:
                    continue

                self._add_paragraph(f"{section_label}:", bold=True)

                if isinstance(section_data, list):
                    self._add_bullet_list([str(s) for s in section_data])
                elif isinstance(section_data, dict):
                    for sub_key, sub_cmds in section_data.items():
                        self._add_heading(f"    {sub_key}", level=3)
                        if isinstance(sub_cmds, list):
                            # Check if it looks like code or bullet items
                            if any(cmd.startswith("#") or cmd.startswith("git ") or
                                   cmd.startswith("az ") or cmd.startswith("gh ") or
                                   cmd.startswith("curl") or cmd.startswith("docker") or
                                   "=" in cmd or cmd.startswith("./") or
                                   cmd.startswith("java ") or cmd.startswith("glab ") or
                                   cmd.strip() == "" for cmd in sub_cmds[:5]):
                                self._add_code_block("\n".join(sub_cmds))
                            else:
                                self._add_bullet_list(sub_cmds)

            # Monitor
            monitor = pdata.get("monitor", {})
            if monitor:
                self._add_paragraph("Monitor Pipeline & Deployments:", bold=True)
                monitor_rows = []
                for mtype, items in monitor.items():
                    if isinstance(items, list):
                        for item in items:
                            if str(item).strip():
                                monitor_rows.append([mtype, str(item)])
                if monitor_rows:
                    self._add_table(["Method", "Command / URL"], monitor_rows, color)

            # Files
            for fk in ["workflow_files", "pipeline_files", "jenkinsfile_info"]:
                files = pdata.get(fk, [])
                if files:
                    self._add_paragraph("Pipeline Configuration Files:", bold=True)
                    self._add_bullet_list([str(f) for f in files])

            triggers = pdata.get("auto_triggers", [])
            if triggers:
                self._add_paragraph("Auto Trigger Events:", bold=True)
                self._add_bullet_list([str(t) for t in triggers])

        # 5.5 Environment Promotion
        self._add_heading("5.5 Environment Promotion Flow", level=2)
        promo = deploy_instructions.get("environment_promotion", [])
        if promo:
            promo_rows = [[p["step"], p["action"], p["branch"]] for p in promo]
            self._add_table(["Stage", "Action", "Branch"], promo_rows, "berry")

        # Quick Reference
        self._add_heading("5.6 Quick Reference Commands", level=2)
        qr = [
            ["git status", "Check working tree status"],
            ["git fetch --prune", "Fetch & prune remote branches"],
            ["git pull --rebase", "Pull with rebase"],
            ["git diff HEAD", "Show all uncommitted changes"],
            ["git log --oneline -10", "View last 10 commits"],
            ["git stash / git stash pop", "Stash/restore changes"],
            ["git reset --soft HEAD~1", "Undo last commit (keep changes)"],
            ["git cherry-pick <hash>", "Apply specific commit"],
            ["git tag -a v1.0 -m 'Release'", "Create tag"],
            ["git push origin --tags", "Push tags"],
            ["git branch -d branch-name", "Delete local branch"],
            ["git push origin --delete branch", "Delete remote branch"],
        ]
        self._add_table(["Command", "Description"], qr, "teal")

        self.doc.add_page_break()

        # ════════════════════════════════════════════════════════════
        # 6. CI/CD PIPELINE ANALYSIS
        # ════════════════════════════════════════════════════════════
        self._add_heading("6. CI/CD Pipeline Analysis", level=1)

        if not pipeline_info:
            self._add_paragraph("No CI/CD pipeline configuration files were detected.")
        else:
            self._add_heading("6.1 Pipeline Overview", level=2)
            ov_rows = [[p.get("file", ""), p.get("type", "Unknown"),
                        str(len(p.get("stages", []))), str(len(p.get("jobs", []))),
                        str(len(p.get("triggers", [])))] for p in pipeline_info]
            self._add_table(["File", "Type", "Stages", "Jobs", "Triggers"], ov_rows, "default")

            self._add_heading("6.2 Detailed Pipeline Configuration", level=2)
            for pi, pipeline in enumerate(pipeline_info):
                color = colors[pi % len(colors)]
                self._add_heading(f"Pipeline: {pipeline.get('file', 'Unknown')}", level=3)

                meta = [f"Type: {pipeline.get('type', 'Unknown')}"]
                if pipeline.get("workflow_name"):
                    meta.append(f"Workflow: {pipeline['workflow_name']}")
                if pipeline.get("pool"):
                    meta.append(f"Pool: {pipeline['pool']}")
                if pipeline.get("agent"):
                    meta.append(f"Agent: {pipeline['agent']}")
                self._add_bullet_list(meta)

                if pipeline.get("triggers"):
                    self._add_paragraph("Triggers:", bold=True)
                    self._add_bullet_list([str(t) for t in pipeline["triggers"]])

                if pipeline.get("error"):
                    self._add_paragraph(f"⚠ Parse Warning: {pipeline['error']}", italic=True)

                if pipeline.get("raw_content"):
                    self._add_paragraph("Configuration Preview:", bold=True)
                    self._add_code_block(pipeline["raw_content"], 40)

            self._add_heading("6.3 Pipeline Stages & Jobs", level=2)
            for pi, pipeline in enumerate(pipeline_info):
                color = colors[pi % len(colors)]
                if pipeline.get("stages") or pipeline.get("jobs"):
                    self._add_heading(f"Stages/Jobs: {pipeline.get('file', '')}", level=3)

                    if pipeline.get("stages"):
                        self._add_paragraph("Stages:", bold=True)
                        self._add_numbered_list([
                            str(s) if isinstance(s, str) else s.get("name", str(s))
                            for s in pipeline["stages"]
                        ])

                    if pipeline.get("jobs"):
                        self._add_paragraph("Jobs Detail:", bold=True)
                        jr = []
                        for job in pipeline["jobs"]:
                            jname = job.get("name", job.get("displayName", "Unnamed"))
                            runs = job.get("runs_on", job.get("pool", job.get("image", "")))
                            steps_ct = len(job.get("steps", []))
                            env = job.get("environment", "")
                            needs = ", ".join(job.get("needs", [])) if job.get("needs") else job.get("condition", "")
                            jr.append([str(jname), str(runs), str(steps_ct), str(env), str(needs)])
                        self._add_table(["Job", "Runs On", "Steps", "Environment", "Deps/Conditions"], jr, color)

                        for job in pipeline["jobs"]:
                            steps = job.get("steps", [])
                            if steps:
                                jn = job.get("name", job.get("displayName", "Unnamed"))
                                self._add_paragraph(f"Steps in '{jn}':", bold=True)
                                step_items = []
                                for step in steps:
                                    name = step.get("name", "")
                                    uses = step.get("uses", "")
                                    task = step.get("task", "")
                                    if uses:
                                        step_items.append(f"{name} (uses: {uses})")
                                    elif task:
                                        step_items.append(f"{name} (task: {task})")
                                    else:
                                        step_items.append(str(name))
                                self._add_bullet_list(step_items)

            self._add_heading("6.4 Pipeline Variables & Parameters", level=2)
            has_vars = False
            for pipeline in pipeline_info:
                if pipeline.get("variables") or pipeline.get("parameters"):
                    has_vars = True
                    self._add_heading(f"Variables: {pipeline.get('file', '')}", level=3)
                    if pipeline.get("variables"):
                        self._add_paragraph("Environment Variables:", bold=True)
                        vr = [[k, str(v)[:60]] for k, v in pipeline["variables"].items()]
                        self._add_table(["Variable", "Value"], vr, "green")
                    if pipeline.get("parameters"):
                        self._add_paragraph("Parameters:", bold=True)
                        pr = [[p.get("name", ""), p.get("type", ""), str(p.get("default", ""))]
                              for p in pipeline["parameters"]]
                        self._add_table(["Parameter", "Type", "Default"], pr, "purple")
            if not has_vars:
                self._add_paragraph("No variables or parameters detected.")

        self.doc.add_page_break()

        # ════════════════════════════════════════════════════════════
        # 7. ENVIRONMENT CONFIGURATION
        # ════════════════════════════════════════════════════════════
        self._add_heading("7. Environment Configuration", level=1)
        all_envs = set()
        for pipeline in pipeline_info:
            all_envs.update(e for e in pipeline.get("environments", []) if e)
        if all_envs:
            self._add_paragraph("Environments referenced in pipelines:")
            self._add_bullet_list(sorted(all_envs))
        else:
            self._add_paragraph("No specific environment configurations detected.")

        env_files = [k for k in file_tree if ".env" in k.lower() or "environment" in k.lower()]
        if env_files:
            self._add_heading("Environment Configuration Files", level=2)
            self._add_bullet_list(env_files)

        all_services = []
        for pipeline in pipeline_info:
            all_services.extend(pipeline.get("services", []))
        if all_services:
            self._add_heading("External Services & Resources", level=2)
            sr = [[s.get("type", s.get("name", "")), s.get("name", str(s))] for s in all_services]
            self._add_table(["Type", "Name"], sr, "teal")

        self.doc.add_page_break()

        # ════════════════════════════════════════════════════════════
        # 8. COMPLETE FILE LISTING
        # ════════════════════════════════════════════════════════════
        self._add_heading("8. Complete File Listing", level=1)
        self._add_paragraph("All files in the project with details:")

        all_files_list = []
        self._collect_all_files(file_tree, all_files_list)
        if all_files_list:
            chunk_size = 50
            for ci in range(0, len(all_files_list), chunk_size):
                chunk = all_files_list[ci:ci + chunk_size]
                fr = [[f.get("path", f.get("name", "")), f.get("extension", ""),
                       self._format_size(f.get("size", 0)), f.get("modified", "")] for f in chunk]
                color = colors[(ci // chunk_size) % len(colors)]
                self._add_table(["File Path", "Type", "Size", "Modified"], fr, color)

        self.doc.add_page_break()

        # ════════════════════════════════════════════════════════════
        # 9. APPENDIX
        # ════════════════════════════════════════════════════════════
        self._add_heading("9. Appendix", level=1)

        self._add_heading("9.1 System Information", level=2)
        sys_info = [
            ["Python Version", platform.python_version()],
            ["Operating System", platform.platform()],
            ["Architecture", platform.machine()],
            ["Hostname", platform.node()],
            ["Generator Version", "2.0.0"],
        ]
        self._add_table(["Property", "Value"], sys_info, "teal")

        self._add_heading("9.2 Glossary", level=2)
        glossary = [
            ["CI/CD", "Continuous Integration / Continuous Deployment"],
            ["YAML", "YAML Ain't Markup Language - configuration format"],
            ["Pipeline", "Automated workflow for building, testing, deploying"],
            ["Stage", "Logical grouping of jobs in a pipeline"],
            ["Job", "Unit of work on an agent/runner"],
            ["Step", "Individual task within a job"],
            ["Artifact", "Build output that can be published"],
            ["Trigger", "Event that initiates a pipeline run"],
            ["PR", "Pull Request / Merge Request"],
            ["Branch", "Independent line of development in Git"],
        ]
        self._add_table(["Term", "Definition"], glossary, "purple")

        self._add_horizontal_line()
        para = self.doc.add_paragraph()
        para.alignment = WD_ALIGN_PARAGRAPH.CENTER
        run = para.add_run(
            f"— End of Document —\n"
            f"Generated by Project Document Generator v2.0\n"
            f"{datetime.now().strftime('%B %d, %Y')}"
        )
        run.font.name = "Calibri"
        run.font.size = Pt(10)
        run.font.italic = True
        run.font.color.rgb = RGBColor(0, 0, 0)

        # Save
        self.doc.save(output_path)
        logger.info(f"Document saved to: {output_path}")


# ===========================================================================
# MAIN
# ===========================================================================

def main():
    parser = argparse.ArgumentParser(
        description="Project Document Generator v2.0 - Scan, analyze, and document your project",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s /path/to/project
  %(prog)s . --output my_project_doc.docx
  %(prog)s /path/to/project -o docs/project.docx -v
        """,
    )
    parser.add_argument("project_path", nargs="?", default=".",
                        help="Path to project directory (default: current)")
    parser.add_argument("--output", "-o", default=None,
                        help="Output document path (default: <name>_documentation.docx)")
    parser.add_argument("--verbose", "-v", action="store_true",
                        help="Enable verbose logging")

    args = parser.parse_args()
    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    project_path = Path(args.project_path).resolve()
    if not project_path.exists():
        logger.error(f"Project path does not exist: {project_path}")
        sys.exit(1)

    logger.info("=" * 65)
    logger.info("  PROJECT DOCUMENT GENERATOR v2.0")
    logger.info("=" * 65)
    logger.info(f"  Path     : {project_path}")
    logger.info(f"  Platform : {platform.system()} {platform.release()}")
    logger.info("=" * 65)

    # Step 1
    logger.info("[1/8] Initializing components...")
    scanner = ProjectScanner(str(project_path))
    ai_agent = AIProjectAgent(str(project_path))
    local_detector = LocalDevDeploymentDetector(str(project_path))

    # Step 2
    logger.info("[2/8] Detecting project name with AI agent...")
    project_name = ai_agent.detect_project_name()
    logger.info(f"      → {project_name}")

    # Step 3
    logger.info("[3/8] Scanning project file tree...")
    file_tree = scanner.scan_file_tree()
    file_stats = scanner.get_file_statistics(file_tree)
    logger.info(f"      → {file_stats['total_files']} files / {file_stats['total_directories']} directories")

    # Step 4
    logger.info("[4/8] Analyzing technology stack...")
    tech_stack = ai_agent.detect_tech_stack(file_tree)
    for cat, items in tech_stack.items():
        logger.info(f"      → {cat}: {', '.join(items)}")

    # Step 5
    logger.info("[5/8] Scanning CI/CD pipeline configurations...")
    pipeline_files = scanner.find_pipeline_files()
    pipeline_info = []
    for pf in pipeline_files:
        logger.info(f"      → Parsing: {pf.relative_to(project_path)}")
        info = scanner.parse_pipeline_file(pf)
        pipeline_info.append(info)
        if info.get("error"):
            logger.warning(f"        ⚠ {info['error']}")

    # Step 6
    logger.info("[6/8] Collecting repository information...")
    git_info = scanner.get_git_info()
    if git_info["is_git_repo"]:
        logger.info(f"      → Branch: {git_info.get('current_branch', 'N/A')}, Commits: {git_info.get('total_commits', 0)}")

    # Step 7
    logger.info("[7/8] Generating local dev & deployment guide...")
    local_dev = local_detector.detect_local_run_commands()
    deploy_instructions = local_detector.detect_devops_push_instructions(pipeline_info, git_info)

    has_run = bool(local_dev.get("run_commands"))
    has_docker = bool(local_dev.get("docker_commands"))
    has_platforms = len(deploy_instructions.get("platforms", {}))
    logger.info(f"      → Local run: {'Yes' if has_run else 'No'} | Docker: {'Yes' if has_docker else 'No'} | Platforms: {has_platforms}")

    # Step 8
    logger.info("[8/8] Generating Word document...")
    project_type = ai_agent.detect_project_type(tech_stack)
    project_summary = ai_agent.generate_project_summary(project_name, tech_stack, pipeline_info, file_stats)

    output_path = args.output
    if not output_path:
        safe_name = re.sub(r'[^\w\-.]', '_', project_name)
        output_path = f"{safe_name}_documentation.docx"

    doc_gen = DocumentGenerator()
    doc_gen.generate(
        project_name=project_name,
        project_type=project_type,
        project_summary=project_summary,
        tech_stack=tech_stack,
        pipeline_info=pipeline_info,
        file_tree=file_tree,
        file_stats=file_stats,
        git_info=git_info,
        project_path=str(project_path),
        local_dev=local_dev,
        deploy_instructions=deploy_instructions,
        output_path=output_path,
    )

    logger.info("")
    logger.info("=" * 65)
    logger.info("  ✅ DOCUMENT GENERATION COMPLETE")
    logger.info("=" * 65)
    logger.info(f"  Output    : {os.path.abspath(output_path)}")
    logger.info(f"  Project   : {project_name}")
    logger.info(f"  Type      : {project_type}")
    logger.info(f"  Files     : {file_stats['total_files']}")
    logger.info(f"  Pipelines : {len(pipeline_info)}")
    logger.info(f"  Platforms : {has_platforms} DevOps platform(s)")
    logger.info("=" * 65)


if __name__ == "__main__":
    main()
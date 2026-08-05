#!/usr/bin/env python3
"""
Automated Project Documentation Generator
Scans entire project and generates comprehensive documentation in DOCX format
Supports: GitHub Actions, Jenkins, Azure DevOps
Uses AI (OpenAI GPT) for intelligent analysis
"""

import os
import sys
import json
import subprocess
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Any, Optional
import re
from collections import defaultdict

# Install required packages if not available
def install_requirements():
    """Install required packages"""
    required_packages = {
        'python-docx': 'docx',
        'gitpython': 'git',
        'openai': 'openai',
        'python-dotenv': 'dotenv',
        'requests': 'requests'
    }
    
    for package, import_name in required_packages.items():
        try:
            __import__(import_name)
        except ImportError:
            print(f"Installing {package}...")
            subprocess.check_call([sys.executable, "-m", "pip", "install", package])

install_requirements()

from docx import Document
from docx.shared import Inches, Pt, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml.ns import qn
from docx.oxml import OxmlElement
import git
from dotenv import load_dotenv
import openai

# Load environment variables
load_dotenv()

class ProjectDocumentationGenerator:
    """Main class for generating project documentation"""
    
    def __init__(self, project_path: str = ".", use_ai: bool = True):
        self.project_path = Path(project_path).resolve()
        self.use_ai = use_ai and os.getenv("OPENAI_API_KEY")
        self.doc = Document()
        self.project_data = {}
        
        if self.use_ai:
            openai.api_key = os.getenv("OPENAI_API_KEY")
        
        # File extensions to analyze
        self.code_extensions = {
            '.py', '.js', '.ts', '.java', '.cpp', '.c', '.cs', '.go', 
            '.rb', '.php', '.swift', '.kt', '.rs', '.scala', '.r'
        }
        
        self.config_extensions = {
            '.json', '.yaml', '.yml', '.toml', '.ini', '.conf', '.xml',
            '.env.example', 'Dockerfile', 'docker-compose.yml'
        }
        
        self.doc_extensions = {
            '.md', '.txt', '.rst', '.adoc'
        }
        
        # Ignore patterns
        self.ignore_patterns = {
            'node_modules', '.git', '__pycache__', 'venv', 'env',
            '.venv', 'dist', 'build', '.pytest_cache', '.idea',
            'target', 'bin', 'obj', '.vs', '.vscode'
        }

    def should_ignore(self, path: Path) -> bool:
        """Check if path should be ignored"""
        parts = path.parts
        return any(pattern in parts for pattern in self.ignore_patterns)

    def scan_project(self):
        """Scan entire project structure"""
        print("🔍 Scanning project structure...")
        
        self.project_data = {
            'name': self.project_path.name,
            'path': str(self.project_path),
            'files': [],
            'directories': [],
            'code_files': [],
            'config_files': [],
            'doc_files': [],
            'languages': defaultdict(int),
            'total_lines': 0,
            'file_count': 0,
            'git_info': self.get_git_info(),
            'dependencies': self.get_dependencies(),
            'errors_found': [],
            'commands': self.find_commands(),
            'background_processes': self.find_background_processes(),
        }
        
        for item in self.project_path.rglob('*'):
            if self.should_ignore(item):
                continue
                
            if item.is_file():
                self.project_data['file_count'] += 1
                file_info = self.analyze_file(item)
                self.project_data['files'].append(file_info)
                
                if item.suffix in self.code_extensions:
                    self.project_data['code_files'].append(file_info)
                    self.project_data['languages'][item.suffix] += 1
                elif item.suffix in self.config_extensions or item.name in self.config_extensions:
                    self.project_data['config_files'].append(file_info)
                elif item.suffix in self.doc_extensions:
                    self.project_data['doc_files'].append(file_info)
            
            elif item.is_dir():
                self.project_data['directories'].append(str(item.relative_to(self.project_path)))
        
        print(f"✅ Scanned {self.project_data['file_count']} files")

    def analyze_file(self, file_path: Path) -> Dict[str, Any]:
        """Analyze individual file"""
        try:
            relative_path = file_path.relative_to(self.project_path)
            file_info = {
                'path': str(relative_path),
                'name': file_path.name,
                'extension': file_path.suffix,
                'size': file_path.stat().st_size,
                'lines': 0,
                'errors': [],
                'imports': [],
                'classes': [],
                'functions': [],
            }
            
            if file_path.suffix in self.code_extensions:
                try:
                    with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                        content = f.read()
                        lines = content.split('\n')
                        file_info['lines'] = len(lines)
                        self.project_data['total_lines'] += len(lines)
                        
                        # Extract code elements (Python example)
                        if file_path.suffix == '.py':
                            file_info['imports'] = re.findall(r'^import\s+(\S+)|^from\s+(\S+)', content, re.MULTILINE)
                            file_info['classes'] = re.findall(r'^class\s+(\w+)', content, re.MULTILINE)
                            file_info['functions'] = re.findall(r'^def\s+(\w+)', content, re.MULTILINE)
                            
                            # Find potential errors/todos
                            for i, line in enumerate(lines, 1):
                                if 'TODO' in line or 'FIXME' in line or 'BUG' in line:
                                    file_info['errors'].append({
                                        'line': i,
                                        'content': line.strip()
                                    })
                                    self.project_data['errors_found'].append({
                                        'file': str(relative_path),
                                        'line': i,
                                        'content': line.strip()
                                    })
                except Exception as e:
                    file_info['errors'].append(str(e))
            
            return file_info
        except Exception as e:
            return {'path': str(file_path), 'error': str(e)}

    def get_git_info(self) -> Dict[str, Any]:
        """Extract Git repository information"""
        try:
            repo = git.Repo(self.project_path)
            return {
                'active_branch': repo.active_branch.name,
                'remotes': [remote.url for remote in repo.remotes],
                'total_commits': len(list(repo.iter_commits())),
                'contributors': list(set([commit.author.name for commit in repo.iter_commits()])),
                'last_commit': {
                    'hash': repo.head.commit.hexsha[:7],
                    'message': repo.head.commit.message.strip(),
                    'author': repo.head.commit.author.name,
                    'date': repo.head.commit.committed_datetime.strftime('%Y-%m-%d %H:%M:%S')
                }
            }
        except Exception as e:
            return {'error': str(e)}

    def get_dependencies(self) -> Dict[str, List[str]]:
        """Extract project dependencies"""
        dependencies = {}
        
        # Python - requirements.txt, Pipfile, pyproject.toml
        req_files = ['requirements.txt', 'Pipfile', 'pyproject.toml']
        for req_file in req_files:
            req_path = self.project_path / req_file
            if req_path.exists():
                try:
                    with open(req_path, 'r') as f:
                        dependencies[req_file] = [line.strip() for line in f if line.strip() and not line.startswith('#')]
                except:
                    pass
        
        # Node.js - package.json
        package_json = self.project_path / 'package.json'
        if package_json.exists():
            try:
                with open(package_json, 'r') as f:
                    data = json.load(f)
                    dependencies['package.json'] = list(data.get('dependencies', {}).keys())
            except:
                pass
        
        return dependencies

    def find_commands(self) -> List[Dict[str, str]]:
        """Find command references in project"""
        commands = []
        
        # Check common files
        files_to_check = ['README.md', 'Makefile', 'package.json', '.gitlab-ci.yml', 
                          '.github/workflows/*.yml', 'Jenkinsfile', 'azure-pipelines.yml']
        
        for pattern in files_to_check:
            for file_path in self.project_path.glob(pattern):
                if file_path.is_file():
                    try:
                        with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                            content = f.read()
                            
                            # Find bash commands
                            bash_commands = re.findall(r'```(?:bash|sh)\n(.*?)```', content, re.DOTALL)
                            for cmd in bash_commands:
                                commands.append({
                                    'source': str(file_path.name),
                                    'type': 'bash',
                                    'command': cmd.strip()
                                })
                            
                            # Find npm scripts
                            if file_path.name == 'package.json':
                                try:
                                    data = json.loads(content)
                                    scripts = data.get('scripts', {})
                                    for name, cmd in scripts.items():
                                        commands.append({
                                            'source': 'package.json',
                                            'type': 'npm',
                                            'name': name,
                                            'command': cmd
                                        })
                                except:
                                    pass
                    except:
                        pass
        
        return commands

    def find_background_processes(self) -> List[Dict[str, str]]:
        """Find background processes and services"""
        processes = []
        
        # Check docker-compose
        docker_compose = self.project_path / 'docker-compose.yml'
        if docker_compose.exists():
            processes.append({
                'type': 'docker-compose',
                'file': 'docker-compose.yml',
                'description': 'Container orchestration'
            })
        
        # Check for Celery
        for code_file in self.project_data.get('code_files', []):
            if 'celery' in code_file.get('path', '').lower():
                processes.append({
                    'type': 'celery',
                    'file': code_file['path'],
                    'description': 'Task queue worker'
                })
        
        # Check for cron jobs
        for code_file in self.project_data.get('code_files', []):
            if 'cron' in code_file.get('path', '').lower():
                processes.append({
                    'type': 'cron',
                    'file': code_file['path'],
                    'description': 'Scheduled tasks'
                })
        
        return processes

    def ai_analyze(self, prompt: str, context: str) -> str:
        """Use AI to analyze and generate content"""
        if not self.use_ai:
            return "AI analysis not available. Set OPENAI_API_KEY environment variable."
        
        try:
            response = openai.ChatCompletion.create(
                model="gpt-3.5-turbo",
                messages=[
                    {"role": "system", "content": "You are a technical documentation expert."},
                    {"role": "user", "content": f"{prompt}\n\nContext:\n{context}"}
                ],
                max_tokens=1000,
                temperature=0.7
            )
            return response.choices[0].message.content.strip()
        except Exception as e:
            return f"AI analysis failed: {str(e)}"

    def add_heading(self, text: str, level: int = 1):
        """Add formatted heading to document"""
        heading = self.doc.add_heading(text, level=level)
        heading.alignment = WD_ALIGN_PARAGRAPH.LEFT
        return heading

    def add_paragraph(self, text: str, bold: bool = False, italic: bool = False):
        """Add formatted paragraph"""
        p = self.doc.add_paragraph()
        run = p.add_run(text)
        if bold:
            run.bold = True
        if italic:
            run.italic = True
        return p

    def add_table_from_dict(self, data: Dict[str, str], headers: List[str] = None):
        """Add table from dictionary"""
        if not data:
            self.add_paragraph("No data available.", italic=True)
            return
        
        if headers is None:
            headers = ['Key', 'Value']
        
        table = self.doc.add_table(rows=1, cols=len(headers))
        table.style = 'Light Grid Accent 1'
        
        # Header
        for i, header in enumerate(headers):
            table.rows[0].cells[i].text = header
            table.rows[0].cells[i].paragraphs[0].runs[0].bold = True
        
        # Data
        for key, value in data.items():
            row = table.add_row()
            row.cells[0].text = str(key)
            row.cells[1].text = str(value)

    def add_code_block(self, code: str, language: str = ""):
        """Add code block with formatting"""
        p = self.doc.add_paragraph()
        p.style = 'Normal'
        run = p.add_run(code)
        run.font.name = 'Courier New'
        run.font.size = Pt(9)
        
        # Add border
        pPr = p._element.get_or_add_pPr()
        pBdr = OxmlElement('w:pBdr')
        for border_name in ['top', 'left', 'bottom', 'right']:
            border = OxmlElement(f'w:{border_name}')
            border.set(qn('w:val'), 'single')
            border.set(qn('w:sz'), '4')
            border.set(qn('w:space'), '1')
            border.set(qn('w:color'), 'CCCCCC')
            pBdr.append(border)
        pPr.append(pBdr)
        
        # Add shading
        shd = OxmlElement('w:shd')
        shd.set(qn('w:fill'), 'F5F5F5')
        pPr.append(shd)

    def generate_document(self):
        """Generate complete documentation"""
        print("📝 Generating documentation...")
        
        # Title Page
        title = self.doc.add_heading(f'{self.project_data["name"]}', 0)
        title.alignment = WD_ALIGN_PARAGRAPH.CENTER
        
        subtitle = self.doc.add_heading('Project Documentation', 2)
        subtitle.alignment = WD_ALIGN_PARAGRAPH.CENTER
        
        date_para = self.doc.add_paragraph(f'Generated on: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}')
        date_para.alignment = WD_ALIGN_PARAGRAPH.CENTER
        
        self.doc.add_page_break()
        
        # 1. Project Overview
        self.add_heading('1. 📋 Project Overview', 1)
        
        overview_data = {
            'Project Name': self.project_data['name'],
            'Total Files': self.project_data['file_count'],
            'Total Lines of Code': self.project_data['total_lines'],
            'Primary Languages': ', '.join([ext for ext, _ in sorted(self.project_data['languages'].items(), key=lambda x: x[1], reverse=True)[:5]]),
            'Scan Date': datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        }
        
        self.add_table_from_dict(overview_data)
        
        # AI-generated project summary
        if self.use_ai:
            self.add_heading('AI-Generated Summary', 2)
            context = f"Project: {self.project_data['name']}\n"
            context += f"Languages: {', '.join(self.project_data['languages'].keys())}\n"
            context += f"Files: {self.project_data['file_count']}\n"
            context += f"Dependencies: {json.dumps(self.project_data['dependencies'], indent=2)}"
            
            summary = self.ai_analyze(
                "Provide a brief 2-3 paragraph overview of this project based on the context.",
                context
            )
            self.add_paragraph(summary)
        
        self.doc.add_page_break()
        
        # 2. Project Architecture
        self.add_heading('2. 🏗️ Project Architecture', 1)
        
        self.add_heading('Directory Structure', 2)
        dirs = sorted(self.project_data['directories'])[:20]  # Top 20 directories
        for dir_path in dirs:
            self.add_paragraph(f"📁 {dir_path}")
        
        self.add_heading('File Distribution', 2)
        lang_data = {ext: count for ext, count in sorted(self.project_data['languages'].items(), key=lambda x: x[1], reverse=True)}
        self.add_table_from_dict(lang_data, ['Language/Extension', 'File Count'])
        
        if self.use_ai:
            self.add_heading('Architecture Analysis', 2)
            arch_context = f"Directory structure: {json.dumps(dirs[:10], indent=2)}\n"
            arch_context += f"Languages: {json.dumps(lang_data, indent=2)}"
            
            arch_analysis = self.ai_analyze(
                "Analyze the project architecture and explain the likely structure and organization pattern.",
                arch_context
            )
            self.add_paragraph(arch_analysis)
        
        self.doc.add_page_break()
        
        # 3. Project Workflow
        self.add_heading('3. ⚙️ Project Workflow', 1)
        
        if self.project_data['git_info'].get('active_branch'):
            self.add_heading('Git Information', 2)
            git_data = {
                'Active Branch': self.project_data['git_info'].get('active_branch', 'N/A'),
                'Total Commits': self.project_data['git_info'].get('total_commits', 'N/A'),
                'Contributors': ', '.join(self.project_data['git_info'].get('contributors', [])[:5]),
            }
            
            if 'last_commit' in self.project_data['git_info']:
                last_commit = self.project_data['git_info']['last_commit']
                git_data['Last Commit'] = f"{last_commit['hash']} by {last_commit['author']}"
                git_data['Commit Message'] = last_commit['message'][:100]
                git_data['Commit Date'] = last_commit['date']
            
            self.add_table_from_dict(git_data)
        
        # CI/CD Detection
        self.add_heading('CI/CD Configuration', 2)
        ci_files = ['.github/workflows', '.gitlab-ci.yml', 'Jenkinsfile', 'azure-pipelines.yml', '.circleci']
        found_ci = []
        
        for ci_file in ci_files:
            if (self.project_path / ci_file).exists():
                found_ci.append(ci_file)
        
        if found_ci:
            self.add_paragraph(f"Detected CI/CD: {', '.join(found_ci)}", bold=True)
        else:
            self.add_paragraph("No CI/CD configuration detected.", italic=True)
        
        self.doc.add_page_break()
        
        # 4. Tech Stack
        self.add_heading('4. 🛠️ Tech Stack', 1)
        
        self.add_heading('Dependencies', 2)
        for dep_file, deps in self.project_data['dependencies'].items():
            self.add_heading(dep_file, 3)
            for dep in deps[:20]:  # Show first 20
                self.add_paragraph(f"• {dep}")
        
        if not self.project_data['dependencies']:
            self.add_paragraph("No dependency files detected.", italic=True)
        
        self.add_heading('Configuration Files', 2)
        for config_file in self.project_data['config_files'][:15]:
            self.add_paragraph(f"⚙️ {config_file['path']}")
        
        self.doc.add_page_break()
        
        # 5. Commands Reference
        self.add_heading('5. 💻 Commands Reference', 1)
        
        commands = self.project_data['commands']
        if commands:
            for cmd_group in ['npm', 'bash', 'make']:
                group_cmds = [c for c in commands if c.get('type') == cmd_group]
                if group_cmds:
                    self.add_heading(f'{cmd_group.upper()} Commands', 2)
                    for cmd in group_cmds[:10]:
                        if 'name' in cmd:
                            self.add_paragraph(f"Command: {cmd['name']}", bold=True)
                        self.add_code_block(cmd['command'])
                        self.add_paragraph("")
        else:
            self.add_paragraph("No command references found.", italic=True)
        
        self.doc.add_page_break()
        
        # 6. Background Processes
        self.add_heading('6. 🔄 Background Processes', 1)
        
        processes = self.project_data['background_processes']
        if processes:
            for proc in processes:
                self.add_heading(f"{proc['type'].upper()}", 2)
                self.add_paragraph(f"File: {proc['file']}")
                self.add_paragraph(f"Description: {proc['description']}")
                self.add_paragraph("")
        else:
            self.add_paragraph("No background processes detected.", italic=True)
        
        self.doc.add_page_break()
        
        # 7. Results & Outcomes
        self.add_heading('7. 📈 Results & Outcomes', 1)
        
        self.add_heading('Project Statistics', 2)
        stats = {
            'Total Files Analyzed': self.project_data['file_count'],
            'Total Lines of Code': self.project_data['total_lines'],
            'Code Files': len(self.project_data['code_files']),
            'Configuration Files': len(self.project_data['config_files']),
            'Documentation Files': len(self.project_data['doc_files']),
            'Languages Detected': len(self.project_data['languages']),
        }
        self.add_table_from_dict(stats)
        
        self.add_heading('Top Files by Lines of Code', 2)
        top_files = sorted([f for f in self.project_data['code_files'] if f.get('lines', 0) > 0], 
                          key=lambda x: x.get('lines', 0), reverse=True)[:10]
        
        for file in top_files:
            self.add_paragraph(f"📄 {file['path']} - {file['lines']} lines")
        
        self.doc.add_page_break()
        
        # 8. Errors & Solutions
        self.add_heading('8. 🐛 Errors & Solutions', 1)
        
        errors = self.project_data['errors_found']
        if errors:
            self.add_paragraph(f"Found {len(errors)} TODO/FIXME/BUG markers:", bold=True)
            self.add_paragraph("")
            
            for error in errors[:20]:  # Show first 20
                self.add_paragraph(f"File: {error['file']}", bold=True)
                self.add_paragraph(f"Line {error['line']}: {error['content']}")
                self.add_paragraph("")
        else:
            self.add_paragraph("✅ No error markers found in code!", bold=True)
        
        self.doc.add_page_break()
        
        # 9. Key Learnings
        self.add_heading('9. 🎓 Key Learnings', 1)
        
        if self.use_ai:
            learning_context = f"Project analysis:\n"
            learning_context += f"Languages: {json.dumps(dict(self.project_data['languages']), indent=2)}\n"
            learning_context += f"Total files: {self.project_data['file_count']}\n"
            learning_context += f"Dependencies: {json.dumps(self.project_data['dependencies'], indent=2)}\n"
            learning_context += f"CI/CD: {', '.join(found_ci) if found_ci else 'None'}"
            
            learnings = self.ai_analyze(
                "Based on this project analysis, provide 5-7 key technical learnings or insights about the project structure, technologies used, and best practices observed.",
                learning_context
            )
            self.add_paragraph(learnings)
        else:
            self.add_paragraph("Key learnings based on project analysis:", bold=True)
            self.add_paragraph(f"• Project uses {len(self.project_data['languages'])} different programming languages")
            self.add_paragraph(f"• Codebase contains {self.project_data['total_lines']} lines of code across {self.project_data['file_count']} files")
            self.add_paragraph(f"• {'Has' if found_ci else 'Missing'} CI/CD configuration")
            self.add_paragraph(f"• {'Has' if self.project_data['dependencies'] else 'Missing'} dependency management")
        
        self.doc.add_page_break()
        
        # 10. Appendix
        self.add_heading('10. 📎 Appendix', 1)
        
        self.add_heading('Complete File List', 2)
        self.add_paragraph(f"Total files: {len(self.project_data['files'])}")
        self.add_paragraph("")
        
        for file in sorted(self.project_data['files'], key=lambda x: x.get('path', ''))[:100]:
            if 'path' in file:
                size = file.get('size', 0)
                size_str = f"{size/1024:.1f}KB" if size > 1024 else f"{size}B"
                self.add_paragraph(f"• {file['path']} ({size_str})")
        
        if len(self.project_data['files']) > 100:
            self.add_paragraph(f"... and {len(self.project_data['files']) - 100} more files", italic=True)
        
        self.add_heading('Environment Variables Required', 2)
        self.add_paragraph("For full AI-powered analysis, set the following environment variable:")
        self.add_code_block("export OPENAI_API_KEY='your-api-key-here'")
        
        self.add_heading('Generation Metadata', 2)
        metadata = {
            'Generated By': 'Automated Project Documentation Generator',
            'Python Version': sys.version.split()[0],
            'Generation Time': datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            'AI Enabled': 'Yes' if self.use_ai else 'No',
            'Project Path': str(self.project_path)
        }
        self.add_table_from_dict(metadata)

    def save_document(self, output_path: str = None):
        """Save document to file"""
        if output_path is None:
            output_path = f"{self.project_data['name']}_Documentation_{datetime.now().strftime('%Y%m%d_%H%M%S')}.docx"
        
        self.doc.save(output_path)
        print(f"✅ Documentation saved to: {output_path}")
        return output_path

    def run(self, output_path: str = None):
        """Main execution method"""
        print("=" * 60)
        print("🚀 Automated Project Documentation Generator")
        print("=" * 60)
        
        self.scan_project()
        self.generate_document()
        return self.save_document(output_path)


def detect_ci_environment():
    """Detect if running in CI/CD environment"""
    ci_indicators = {
        'GITHUB_ACTIONS': 'GitHub Actions',
        'JENKINS_HOME': 'Jenkins',
        'AZURE_PIPELINES': 'Azure DevOps',
        'GITLAB_CI': 'GitLab CI',
        'CIRCLECI': 'CircleCI',
        'TRAVIS': 'Travis CI'
    }
    
    for env_var, ci_name in ci_indicators.items():
        if os.getenv(env_var):
            return ci_name
    
    return None


def main():
    """Main entry point"""
    import argparse
    
    parser = argparse.ArgumentParser(description='Generate comprehensive project documentation')
    parser.add_argument('--path', default='.', help='Project path to analyze (default: current directory)')
    parser.add_argument('--output', help='Output file path (default: auto-generated)')
    parser.add_argument('--no-ai', action='store_true', help='Disable AI analysis')
    parser.add_argument('--openai-key', help='OpenAI API key (or set OPENAI_API_KEY env variable)')
    
    args = parser.parse_args()
    
    # Set OpenAI key if provided
    if args.openai_key:
        os.environ['OPENAI_API_KEY'] = args.openai_key
    
    # Detect CI environment
    ci_env = detect_ci_environment()
    if ci_env:
        print(f"🔧 Running in {ci_env} environment")
    
    # Generate documentation
    generator = ProjectDocumentationGenerator(
        project_path=args.path,
        use_ai=not args.no_ai
    )
    
    try:
        output_file = generator.run(args.output)
        
        # If in CI, try to upload artifact
        if ci_env == 'GitHub Actions':
            gh_output = os.environ.get("GITHUB_OUTPUT")
            if gh_output:
                with open(gh_output, "a", encoding="utf-8") as fh:
                    fh.write(f"documentation_file={output_file}\n")
            else:
                # Fallback for older runners
                print(f"::set-output name=documentation_file::{output_file}")
        
        print("\n" + "=" * 60)
        print("✨ Documentation generation completed successfully!")
        print("=" * 60)
                
        return 0
    
    except Exception as e:
        print(f"\n❌ Error: {str(e)}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
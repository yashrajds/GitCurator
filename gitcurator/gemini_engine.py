import json
import re
import time
from typing import Any, Dict, List, Optional
from google import genai
from google.genai import types
from rich.console import Console

console = Console()

class GeminiEngine:
    def __init__(self, api_key: str, model_name: str = "gemini-3.6-flash", temperature: float = 0.7):
        if not api_key:
            raise ValueError("Gemini API key is required.")
        self.api_key = api_key
        self.model_name = model_name
        self.temperature = temperature
        self.client = genai.Client(api_key=api_key)

    def _call_model(self, prompt: str, system_instruction: Optional[str] = None, max_retries: int = 3) -> str:
        """Call Gemini API with automatic exponential backoff for rate limits."""
        for attempt in range(1, max_retries + 1):
            try:
                config = types.GenerateContentConfig(
                    temperature=self.temperature,
                    system_instruction=system_instruction,
                )
                response = self.client.models.generate_content(
                    model=self.model_name,
                    contents=prompt,
                    config=config
                )
                return response.text or ""
            except Exception as e:
                err_str = str(e).lower()
                if "rate limit" in err_str or "resource_exhausted" in err_str or "429" in err_str:
                    wait_time = 2 ** attempt * 2
                    console.print(f"[bold yellow]Gemini rate limit encountered. Retrying in {wait_time}s (attempt {attempt}/{max_retries})...[/bold yellow]")
                    time.sleep(wait_time)
                else:
                    if attempt == max_retries:
                        raise
                    time.sleep(2)
        return ""

    def generate_profile_readme(
        self,
        username: str,
        bio: str,
        top_languages: List[str],
        pinned_repos: List[Dict[str, Any]],
        recent_activity: List[Dict[str, Any]],
        tone: str = "professional yet personable, modern tech-forward",
    ) -> str:
        system_instruction = (
            "You are an elite developer portfolio and GitHub profile designer. "
            "You write stunning, modern, clean GitHub Profile README.md files that showcase technical proficiency, "
            "real project achievements, and an authentic engineering personality. "
            "Use clean Markdown, GitHub badges (shields.io), crisp layout, and GitHub stats elements."
        )

        pinned_summary = []
        for r in pinned_repos:
            lang = r.get("primaryLanguage", {}).get("name", "Various") if isinstance(r.get("primaryLanguage"), dict) else "Various"
            pinned_summary.append(f"- **{r.get('name')}**: {r.get('description') or 'No description'} (Language: {lang}, Stars: {r.get('stargazerCount', 0)})")
        pinned_text = "\n".join(pinned_summary) if pinned_summary else "No pinned repos provided."

        recent_summary = []
        for ev in recent_activity[:10]:
            ev_type = ev.get("type", "Activity")
            repo_name = ev.get("repo", {}).get("name", "")
            recent_summary.append(f"- {ev_type} on {repo_name}")
        recent_text = "\n".join(recent_summary) if recent_summary else "Active development across various repositories."

        prompt = f"""
Generate a complete, production-ready GitHub Profile README.md for user: @{username}.

Profile Context:
- Current Bio: {bio or 'Software Engineer & Open Source Builder'}
- Core Languages / Technologies: {', '.join(top_languages) if top_languages else 'Python, JavaScript, TypeScript, Web Development'}
- Featured / Pinned Projects:
{pinned_text}
- Recent Activity Context:
{recent_text}
- Tone style: {tone}

Requirements:
1. Greet visitors with an engaging header (e.g. Hi there, I'm {username} ??).
2. Include an 'About Me' / Bio summary showcasing passions and domains.
3. Tech Stack section categorized cleanly (Languages, Frameworks, Developer Tools/Cloud) using Shields.io badges where appropriate.
4. 'Featured Projects' section presenting the pinned repositories with concise impact bullets and links (https://github.com/{username}/<repo>).
5. 'Currently Building & Exploring' section highlighting ongoing momentum.
6. GitHub streak/stats badges:
   - Include https://github-readme-stats.vercel.app/api?username={username}&show_icons=true&theme=radical
   - Include https://github-readme-stats.vercel.app/api/top-langs/?username={username}&layout=compact&theme=radical
7. A modern 'Connect with Me' or footer section.
8. Output ONLY the raw Markdown content. Do not enclose it in triple backtick code fences (no ```markdown at start or end).
"""
        raw = self._call_model(prompt, system_instruction=system_instruction)
        # Strip any extraneous fences if Gemini wrapped it
        clean = re.sub(r"^```(?:markdown)?\s*", "", raw.strip(), flags=re.IGNORECASE)
        clean = re.sub(r"\s*```$", "", clean.strip())
        return clean

    def enhance_repo_metadata(
        self,
        repo_name: str,
        current_description: Optional[str],
        readme_snippet: Optional[str],
        languages: List[str]
    ) -> Dict[str, Any]:
        """Generates improved description, suggested tags/topics, and a better name suggestion if unclear."""
        system_instruction = (
            "You are a repository curator and technical writer. Output valid JSON only."
        )

        prompt = f"""
Analyze this GitHub repository:
- Name: {repo_name}
- Current Description: {current_description or 'None'}
- Languages used: {', '.join(languages) if languages else 'Unknown'}
- README excerpt:
\"\"\"
{readme_snippet[:2000] if readme_snippet else 'No README available'}
\"\"\"

Task:
1. Provide an improved, punchy, professional description (under 140 characters).
2. Recommend 4 to 7 relevant GitHub topics/tags (lowercase, dash-separated, e.g. 'python', 'cli-tool').
3. If the repository name is ambiguous, messy, or generic (like 'test1', 'my-proj', 'code2'), suggest a clearer, better name. Otherwise keep suggest_better_name as null.
4. Briefly explain why this metadata is suggested.

Output format must be strictly JSON with keys:
{{
  "improved_description": "...",
  "topics": ["topic1", "topic2"],
  "suggest_better_name": null or "clean-name",
  "reason": "..."
}}
"""
        raw = self._call_model(prompt, system_instruction=system_instruction)
        match = re.search(r"\{.*\}", raw, re.DOTALL)
        if match:
            try:
                return json.loads(match.group(0))
            except Exception:
                pass
        return {
            "improved_description": current_description or f"A {languages[0] if languages else 'software'} project: {repo_name}",
            "topics": [l.lower() for l in languages[:5]],
            "suggest_better_name": None,
            "reason": "Default fallback metadata"
        }

    def generate_changelog(
        self,
        repo_name: str,
        commits: List[Dict[str, Any]],
        previous_version: str = "v0.1.0",
        target_version: str = "v0.2.0"
    ) -> str:
        """Generates a Conventional Changelog section based on recent commits."""
        system_instruction = (
            "You are a software release manager who crafts beautiful, human-readable Keep-a-Changelog "
            "style release notes based on git commit history. Output clean Markdown only."
        )

        commit_lines = []
        for c in commits:
            msg = c.get("commit", {}).get("message", "").split("\n")[0]
            sha = c.get("sha", "")[:7]
            author = c.get("commit", {}).get("author", {}).get("name", "Contributor")
            commit_lines.append(f"- [{sha}] {msg} (by {author})")
        commits_str = "\n".join(commit_lines) if commit_lines else "No detailed commit messages found."

        prompt = f"""
Generate release notes / changelog entry for repository '{repo_name}'.
- Previous Version: {previous_version}
- Next Version: {target_version}
- Commits since last release:
{commits_str}

Format according to Keep a Changelog standards:
- Header: ## [{target_version}] - YYYY-MM-DD
- Sections:
  - ### ?? Features (if any)
  - ### ?? Bug Fixes (if any)
  - ### ? Performance & Maintenance (if any)
  - ### ?? Breaking Changes (if any)
- Write concise, clear bullet points summarizing user-facing value. Do not output raw commit hashes as the sole text.
- Return ONLY the markdown changelog section.
"""
        raw = self._call_model(prompt, system_instruction=system_instruction)
        clean = re.sub(r"^```(?:markdown)?\s*", "", raw.strip(), flags=re.IGNORECASE)
        clean = re.sub(r"\s*```$", "", clean.strip())
        return clean

    def suggest_semver_bump(self, commits: List[Dict[str, Any]], current_version: str = "0.1.0") -> Dict[str, Any]:
        """Analyzes commit messages to determine if release is major, minor, or patch."""
        system_instruction = "You are a Semantic Versioning expert. Output valid JSON only."

        messages = [c.get("commit", {}).get("message", "").split("\n")[0] for c in commits]
        messages_str = "\n".join(messages[:50])

        prompt = f"""
Given the current version '{current_version}' and these commit messages:
\"\"\"
{messages_str}
\"\"\"

Determine whether the next release bump should be 'major', 'minor', or 'patch' according to SemVer rules:
- 'major': breaking changes, BREAKING CHANGE in commits, major architectural overhauls.
- 'minor': new features ('feat: ...'), backwards-compatible additions.
- 'patch': bug fixes ('fix: ...'), documentation, minor maintenance ('chore: ...').

Return strictly a JSON object:
{{
  "bump_type": "patch|minor|major",
  "recommended_version": "x.y.z",
  "reasoning": "short explanation"
}}
"""
        raw = self._call_model(prompt, system_instruction=system_instruction)
        match = re.search(r"\{.*\}", raw, re.DOTALL)
        if match:
            try:
                return json.loads(match.group(0))
            except Exception:
                pass

        # Fallback heuristic
        return {
            "bump_type": "patch",
            "recommended_version": "0.1.1",
            "reasoning": "Default fallback patch bump"
        }

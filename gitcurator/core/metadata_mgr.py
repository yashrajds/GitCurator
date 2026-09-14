import sys
import os
if sys.platform == 'win32':
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
        sys.stderr.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass
from typing import List, Optional
import click
from rich.console import Console
from rich.panel import Panel
from gitcurator.config import Config
from gitcurator.gemini_engine import GeminiEngine
from gitcurator.github_client import GitHubClient
from gitcurator.logger import ActivityLogger

console = Console(safe_box=True, highlight=False)

class MetadataManager:
    def __init__(self, config: Config, gh_client: GitHubClient, gemini_engine: GeminiEngine, logger: ActivityLogger):
        self.config = config
        self.gh = gh_client
        self.ai = gemini_engine
        self.logger = logger

    def curate_repo_metadata(self, repo_name: str, dry_run: bool = False, auto_apply: bool = False):
        user = self.gh.get_authenticated_user()
        username = user.get("login")

        console.print(f"[bold cyan]Inspecting repository {username}/{repo_name}...[/bold cyan]")
        repos = self.gh.get_user_repos(repo_type="owner")
        target_repo = next((r for r in repos if r["name"].lower() == repo_name.lower()), None)

        if not target_repo:
            console.print(f"[bold red]Repository '{repo_name}' not found under @{username}.[/bold red]")
            return

        current_desc = target_repo.get("description")
        readme_info = self.gh.get_repo_readme(username, repo_name)
        readme_text = readme_info[0] if readme_info else ""
        languages_dict = self.gh.get_repo_languages(username, repo_name)
        languages = list(languages_dict.keys())

        console.print("[bold cyan]Asking Gemini AI to analyze codebase and generate optimized metadata...[/bold cyan]")
        suggestion = self.ai.enhance_repo_metadata(
            repo_name=repo_name,
            current_description=current_desc,
            readme_snippet=readme_text,
            languages=languages
        )

        improved_desc = suggestion.get("improved_description", current_desc or "")
        topics = suggestion.get("topics", [])
        name_advice = suggestion.get("suggest_better_name")
        reason = suggestion.get("reason", "")

        summary = (
            f"[bold]Current Description:[/bold] {current_desc or 'None'}\n"
            f"[bold green]Suggested Description:[/bold green] {improved_desc}\n"
            f"[bold cyan]Suggested Topics:[/bold cyan] {', '.join(topics)}\n"
        )
        if name_advice:
            summary += f"[bold yellow]Name Advisory:[/bold yellow] Consider renaming '{repo_name}' -> '{name_advice}'\n"
        summary += f"[dim]Reasoning: {reason}[/dim]"

        console.print(Panel(summary, title=f"Metadata Recommendation: {repo_name}"))

        if dry_run:
            self.logger.log(
                action_type="CURATE_METADATA",
                repo=f"{username}/{repo_name}",
                details={"suggested_description": improved_desc, "topics": topics, "name_advice": name_advice},
                dry_run=True,
                status="SUCCESS"
            )
            return

        if not auto_apply:
            if not click.confirm(f"Apply new description and topics to {repo_name}?", default=True):
                console.print("[yellow]Changes discarded by user.[/yellow]")
                return

        # Apply description
        desc_ok = self.gh.update_repo_metadata(username, repo_name, description=improved_desc)
        # Apply topics
        topics_ok = self.gh.replace_repo_topics(username, repo_name, topics=topics)

        status = "SUCCESS" if (desc_ok and topics_ok) else "PARTIAL"
        self.logger.log(
            action_type="UPDATE_METADATA",
            repo=f"{username}/{repo_name}",
            details={"description": improved_desc, "topics": topics},
            dry_run=False,
            status=status
        )
        if desc_ok and topics_ok:
            console.print(f"[bold green]Updated metadata for {username}/{repo_name}![/bold green]")
        else:
            console.print(f"[bold yellow]Metadata update completed with issues (desc={desc_ok}, topics={topics_ok}).[/bold yellow]")

    def curate_all_repos(self, dry_run: bool = False, auto_apply: bool = False):
        user = self.gh.get_authenticated_user()
        username = user.get("login")
        repos = self.gh.get_user_repos(repo_type="owner")

        active_repos = [r for r in repos if not r.get("fork") and not r.get("archived")]
        console.print(f"[bold cyan]Found {len(active_repos)} active repositories to curate.[/bold cyan]")

        for r in active_repos:
            self.curate_repo_metadata(r["name"], dry_run=dry_run, auto_apply=auto_apply)

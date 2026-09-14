import sys
import os
if sys.platform == 'win32':
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
        sys.stderr.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass
from datetime import datetime
from typing import Optional
import click
from rich.console import Console
from rich.panel import Panel
from rich.syntax import Syntax
from gitcurator.config import Config
from gitcurator.gemini_engine import GeminiEngine
from gitcurator.github_client import GitHubClient
from gitcurator.logger import ActivityLogger

console = Console(safe_box=True, highlight=False)

class ChangelogManager:
    def __init__(self, config: Config, gh_client: GitHubClient, gemini_engine: GeminiEngine, logger: ActivityLogger):
        self.config = config
        self.gh = gh_client
        self.ai = gemini_engine
        self.logger = logger

    def generate_repo_changelog(
        self,
        repo_name: str,
        dry_run: bool = False,
        create_release: bool = False,
        target_version: Optional[str] = None
    ):
        user = self.gh.get_authenticated_user()
        username = user.get("login")

        console.print(f"[bold cyan]Analyzing tags and release history for {username}/{repo_name}...[/bold cyan]")
        tags = self.gh.get_repo_tags(username, repo_name)
        releases = self.gh.get_repo_releases(username, repo_name)

        latest_tag = tags[0]["name"] if tags else "v0.1.0"
        commits = self.gh.get_repo_commits(username, repo_name, per_page=40)

        if not commits:
            console.print(f"[bold yellow]No commits found for {username}/{repo_name}.[/bold yellow]")
            return

        # Infer SemVer bump if target version is not specified
        clean_tag = latest_tag.lstrip("v")
        bump_info = self.ai.suggest_semver_bump(commits, current_version=clean_tag)
        next_ver = target_version or f"v{bump_info.get('recommended_version', '0.2.0')}"
        reason = bump_info.get("reasoning", "")

        console.print(f"[bold]Latest Tag:[/bold] {latest_tag}")
        console.print(f"[bold green]Suggested Next Version:[/bold green] {next_ver} ({bump_info.get('bump_type', 'patch').upper()})")
        console.print(f"[dim]Rationale: {reason}[/dim]\n")

        console.print("[bold cyan]Generating release changelog with Gemini AI...[/bold cyan]")
        changelog_section = self.ai.generate_changelog(
            repo_name=repo_name,
            commits=commits,
            previous_version=latest_tag,
            target_version=next_ver
        )

        console.print(Panel(
            Syntax(changelog_section, "markdown", theme="monokai"),
            title=f"Changelog Entry for {repo_name} ({next_ver})"
        ))

        if dry_run:
            self.logger.log(
                action_type="GENERATE_CHANGELOG",
                repo=f"{username}/{repo_name}",
                details={"suggested_version": next_ver, "commits_analyzed": len(commits)},
                dry_run=True,
                status="SUCCESS"
            )
            return

        if not click.confirm("Do you want to prepend this to CHANGELOG.md in the repo?", default=True):
            console.print("[yellow]Changelog commit skipped by user.[/yellow]")
            return

        # Fetch existing CHANGELOG.md
        readme_tuple = self.gh.get_repo_readme(username, repo_name) # check general files
        # Check CHANGELOG.md directly
        url = f"{self.gh.REST_API_BASE}/repos/{username}/{repo_name}/contents/CHANGELOG.md"
        res = self.gh.session.get(url)
        existing_sha = None
        existing_content = ""
        if res.status_code == 200:
            import base64
            data = res.json()
            existing_sha = data.get("sha")
            existing_content = base64.b64decode(data.get("content", "")).decode("utf-8", errors="replace")

        full_changelog = f"# Changelog\n\n{changelog_section}\n\n"
        if existing_content:
            # strip title if present
            stripped = existing_content.replace("# Changelog\n\n", "").replace("# Changelog\n", "")
            full_changelog += stripped

        update_ok = self.gh.create_or_update_file(
            owner=username,
            repo=repo_name,
            path="CHANGELOG.md",
            content=full_changelog,
            message=f"docs(changelog): update for {next_ver} [skip ci]",
            sha=existing_sha
        )

        if update_ok:
            console.print(f"[bold green]CHANGELOG.md updated on {username}/{repo_name}![/bold green]")
            self.logger.log(
                action_type="COMMIT_CHANGELOG",
                repo=f"{username}/{repo_name}",
                details={"version": next_ver},
                dry_run=False,
                status="SUCCESS"
            )
        else:
            console.print(f"[bold red]Failed to write CHANGELOG.md to {username}/{repo_name}.[/bold red]")

        if create_release:
            if click.confirm(f"Create GitHub Release {next_ver} on {repo_name}?", default=True):
                rel = self.gh.create_release(
                    owner=username,
                    repo=repo_name,
                    tag_name=next_ver,
                    name=f"Release {next_ver}",
                    body=changelog_section
                )
                if rel.get("id"):
                    console.print(f"[bold green]Release {next_ver} created successfully![/bold green]")
                    self.logger.log(
                        action_type="CREATE_RELEASE",
                        repo=f"{username}/{repo_name}",
                        details={"tag": next_ver, "release_url": rel.get("html_url")},
                        dry_run=False,
                        status="SUCCESS"
                    )

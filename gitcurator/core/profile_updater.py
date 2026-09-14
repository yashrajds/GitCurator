import sys
import os
if sys.platform == 'win32':
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
        sys.stderr.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass
from typing import Optional
from rich.console import Console
from rich.panel import Panel
from rich.syntax import Syntax
from gitcurator.config import Config
from gitcurator.gemini_engine import GeminiEngine
from gitcurator.github_client import GitHubClient
from gitcurator.logger import ActivityLogger

console = Console(safe_box=True, highlight=False)

class ProfileUpdater:
    def __init__(self, config: Config, gh_client: GitHubClient, gemini_engine: GeminiEngine, logger: ActivityLogger):
        self.config = config
        self.gh = gh_client
        self.ai = gemini_engine
        self.logger = logger

    def update_profile(self, dry_run: bool = False, output_file: Optional[str] = None) -> str:
        console.print("[bold cyan]Scanning user profile and repositories...[/bold cyan]")
        user = self.gh.get_authenticated_user()
        username = user.get("login")
        bio = user.get("bio") or ""

        # Gather pinned repositories
        pinned = self.gh.get_pinned_repos(username)
        if not pinned:
            # Fallback to top starred repos
            repos = self.gh.get_user_repos(sort="pushed", per_page=10)
            pinned = [
                {
                    "name": r.get("name"),
                    "description": r.get("description"),
                    "stargazerCount": r.get("stargazers_count", 0),
                    "primaryLanguage": {"name": r.get("language") or "Code"},
                    "url": r.get("html_url")
                }
                for r in repos if not r.get("fork")
            ][:6]

        # Aggregate top languages
        user_repos = self.gh.get_user_repos(per_page=30)
        lang_counts = {}
        for r in user_repos:
            lang = r.get("language")
            if lang:
                lang_counts[lang] = lang_counts.get(lang, 0) + 1
        sorted_languages = [k for k, _ in sorted(lang_counts.items(), key=lambda item: item[1], reverse=True)]

        # Fetch recent events
        recent_events = self.gh.get_recent_events(username, limit=20)

        tone = self.config.get("profile_readme.tone", "professional yet personable, modern tech-forward")

        console.print("[bold cyan]Synthesizing profile README with Gemini AI...[/bold cyan]")
        new_readme = self.ai.generate_profile_readme(
            username=username,
            bio=bio,
            top_languages=sorted_languages[:8],
            pinned_repos=pinned,
            recent_activity=recent_events,
            tone=tone
        )

        if output_file:
            with open(output_file, "w", encoding="utf-8") as f:
                f.write(new_readme)
            console.print(f"[bold green]README preview saved to: {output_file}[/bold green]")

        target_repo = self.config.get("profile_readme.target_repo") or username
        commit_msg = self.config.get("profile_readme.commit_message", "chore: autonomous profile update by GitCurator")

        if dry_run:
            console.print(Panel(
                Syntax(new_readme[:1200] + ("\n... [truncated for display]" if len(new_readme) > 1200 else ""), "markdown", theme="monokai"),
                title=f"[yellow]Preview of generated README for {target_repo}/README.md[/yellow]"
            ))
            self.logger.log(
                action_type="UPDATE_PROFILE_README",
                repo=f"{username}/{target_repo}",
                details={"characters": len(new_readme), "pinned_count": len(pinned)},
                dry_run=True,
                status="SUCCESS"
            )
            return new_readme

        # Check existing README in special repository
        existing = self.gh.get_repo_readme(username, target_repo)
        sha = existing[1] if existing else None

        success = self.gh.create_or_update_file(
            owner=username,
            repo=target_repo,
            path="README.md",
            content=new_readme,
            message=commit_msg,
            sha=sha
        )

        if success:
            self.logger.log(
                action_type="UPDATE_PROFILE_README",
                repo=f"{username}/{target_repo}",
                details={"bytes": len(new_readme.encode('utf-8'))},
                dry_run=False,
                status="SUCCESS"
            )
            console.print(f"[bold green]Successfully published updated README to https://github.com/{username}/{target_repo}![/bold green]")
        else:
            self.logger.log(
                action_type="UPDATE_PROFILE_README",
                repo=f"{username}/{target_repo}",
                details={},
                dry_run=False,
                status="FAILED",
                error=f"Could not push to {username}/{target_repo} (ensure the repo exists and token has 'repo' scope)."
            )

        return new_readme

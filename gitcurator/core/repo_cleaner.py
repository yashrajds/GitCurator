import sys
import os
if sys.platform == 'win32':
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
        sys.stderr.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass
from datetime import datetime, timezone
from typing import Any, Dict, List
import click
from rich.console import Console
from rich.table import Table
from gitcurator.config import Config
from gitcurator.github_client import GitHubClient
from gitcurator.logger import ActivityLogger

console = Console(safe_box=True, highlight=False)

class RepoCleaner:
    def __init__(self, config: Config, gh_client: GitHubClient, logger: ActivityLogger):
        self.config = config
        self.gh = gh_client
        self.logger = logger

    def audit_repositories(self, threshold_months: int = 6) -> List[Dict[str, Any]]:
        console.print("[bold cyan]Analyzing repositories for hygiene and stale states...[/bold cyan]")
        user = self.gh.get_authenticated_user()
        username = user.get("login")
        repos = self.gh.get_user_repos(repo_type="owner", sort="updated")

        now = datetime.now(timezone.utc)
        audit_results = []

        for r in repos:
            name = r.get("name")
            full_name = r.get("full_name")
            is_fork = r.get("fork", False)
            is_archived = r.get("archived", False)
            pushed_at_str = r.get("pushed_at") or r.get("updated_at")
            size = r.get("size", 0)
            has_description = bool(r.get("description"))
            has_license = bool(r.get("license"))

            # Inactivity calculation
            months_inactive = 0
            if pushed_at_str:
                pushed_at = datetime.fromisoformat(pushed_at_str.replace("Z", "+00:00"))
                days_inactive = (now - pushed_at).days
                months_inactive = round(days_inactive / 30.4, 1)

            issues = []
            if size == 0:
                issues.append("EMPTY_REPO")
            if months_inactive >= threshold_months and not is_archived:
                issues.append(f"STALE ({months_inactive}mo)")
            if is_fork:
                issues.append("FORK")
            if not has_description:
                issues.append("NO_DESC")
            if not has_license:
                issues.append("NO_LICENSE")

            # Check for README
            readme_data = self.gh.get_repo_readme(username, name)
            has_readme = readme_data is not None
            if not has_readme:
                issues.append("NO_README")

            audit_results.append({
                "name": name,
                "full_name": full_name,
                "archived": is_archived,
                "fork": is_fork,
                "size": size,
                "months_inactive": months_inactive,
                "has_readme": has_readme,
                "has_license": has_license,
                "has_description": has_description,
                "issues": issues,
                "stars": r.get("stargazers_count", 0)
            })

        return audit_results

    def display_audit_table(self, audit_results: List[Dict[str, Any]]):
        table = Table(title="GitCurator - Repository Hygiene & Inactivity Audit", show_header=True, header_style="bold magenta")
        table.add_column("Repository", style="bold cyan")
        table.add_column("Status", style="yellow")
        table.add_column("Inactive (Mo)", justify="right")
        table.add_column("Issues / Flags", style="red")
        table.add_column("Stars", justify="right")

        for r in audit_results:
            status = "Archived" if r["archived"] else ("Fork" if r["fork"] else "Active")
            issue_str = ", ".join(r["issues"]) if r["issues"] else "[green]Clean[/green]"
            table.add_row(
                r["name"],
                status,
                str(r["months_inactive"]),
                issue_str,
                str(r["stars"])
            )

        console.print(table)

    def cleanup(
        self,
        dry_run: bool = False,
        threshold_months: int = 6,
        target_repo: str = None,
        action: str = "archive",  # "archive" or "delete"
        auto_confirm: bool = False
    ):
        results = self.audit_repositories(threshold_months=threshold_months)
        self.display_audit_table(results)

        stale_or_empty = [
            r for r in results
            if not r["archived"] and any("STALE" in iss or iss == "EMPTY_REPO" for iss in r["issues"])
        ]

        if target_repo:
            stale_or_empty = [r for r in stale_or_empty if r["name"] == target_repo]

        if not stale_or_empty:
            console.print("[bold green]No candidates found for cleanup under current criteria.[/bold green]")
            return

        console.print(f"\n[bold yellow]Identified {len(stale_or_empty)} candidate(s) for cleanup ({action}):[/bold yellow]")
        for item in stale_or_empty:
            console.print(f" - [bold]{item['name']}[/bold] (Issues: {', '.join(item['issues'])})")

        for item in stale_or_empty:
            repo_name = item["name"]
            user = self.gh.get_authenticated_user()["login"]

            if dry_run:
                self.logger.log(
                    action_type=f"CLEANUP_{action.upper()}",
                    repo=f"{user}/{repo_name}",
                    details={"issues": item["issues"], "months_inactive": item["months_inactive"]},
                    dry_run=True,
                    status="SUCCESS"
                )
                continue

            # Safety confirmation
            if not auto_confirm:
                confirm = click.prompt(
                    f"Type '{repo_name}' to confirm {action.upper()} (or press Enter to skip)",
                    default="",
                    show_default=False
                )
                if confirm.strip() != repo_name:
                    console.print(f"[yellow]Skipping {repo_name}.[/yellow]")
                    continue

            if action == "archive":
                success = self.gh.archive_repo(user, repo_name)
                status = "SUCCESS" if success else "FAILED"
                self.logger.log(
                    action_type="ARCHIVE_REPO",
                    repo=f"{user}/{repo_name}",
                    details={"months_inactive": item["months_inactive"]},
                    dry_run=False,
                    status=status
                )
            elif action == "delete":
                success = self.gh.delete_repo(user, repo_name)
                status = "SUCCESS" if success else "FAILED"
                self.logger.log(
                    action_type="DELETE_REPO",
                    repo=f"{user}/{repo_name}",
                    details={"size": item["size"]},
                    dry_run=False,
                    status=status
                )

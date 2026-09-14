import sys
import os
if sys.platform == 'win32':
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
        sys.stderr.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass
import sys
import click
from rich.console import Console
from rich.table import Table
from gitcurator.config import Config
from gitcurator.core.changelog_mgr import ChangelogManager
from gitcurator.core.metadata_mgr import MetadataManager
from gitcurator.core.profile_updater import ProfileUpdater
from gitcurator.core.repo_cleaner import RepoCleaner
from gitcurator.gemini_engine import GeminiEngine
from gitcurator.github_client import GitHubClient
from gitcurator.logger import ActivityLogger

console = Console(safe_box=True, highlight=False)

def get_context():
    cfg = Config()
    try:
        cfg.validate_credentials()
    except ValueError as e:
        console.print(f"[bold red]Configuration Error:[/bold red]\n{e}")
        sys.exit(1)

    logger = ActivityLogger(cfg.log_file)
    gh_client = GitHubClient(cfg.github_token)
    gemini_engine = GeminiEngine(cfg.gemini_api_key, model_name=cfg.ai_model)
    return cfg, gh_client, gemini_engine, logger

@click.group()
@click.version_option()
def cli():
    """GitCurator: Autonomous AI GitHub Profile & Repository Manager."""
    pass

@cli.command("update-readme")
@click.option("--dry-run", is_flag=True, help="Preview generated README without committing.")
@click.option("--output", type=click.Path(), help="Optional local path to save generated README.md.")
def update_readme(dry_run: bool, output: str):
    """Generate and deploy an updated, modern profile README using Gemini AI."""
    cfg, gh, ai, logger = get_context()
    updater = ProfileUpdater(cfg, gh, ai, logger)
    updater.update_profile(dry_run=dry_run, output_file=output)

@cli.command("cleanup")
@click.option("--dry-run", is_flag=True, help="Preview cleanup candidates without modifying.")
@click.option("--threshold-months", default=6, help="Inactivity threshold in months.")
@click.option("--repo", "target_repo", help="Target specific repository.")
@click.option("--action", type=click.Choice(["archive", "delete"], case_sensitive=False), default="archive", help="Action to take.")
@click.option("--yes", "-y", is_flag=True, help="Auto-confirm actions (CAUTION).")
def cleanup(dry_run: bool, threshold_months: int, target_repo: str, action: str, yes: bool):
    """Detect stale/empty repos, missing hygiene elements, and archive/clean up."""
    cfg, gh, ai, logger = get_context()
    cleaner = RepoCleaner(cfg, gh, logger)
    cleaner.cleanup(
        dry_run=dry_run,
        threshold_months=threshold_months,
        target_repo=target_repo,
        action=action.lower(),
        auto_confirm=yes
    )

@cli.command("audit")
@click.option("--threshold-months", default=6, help="Inactivity threshold in months.")
def audit(threshold_months: int):
    """Run a comprehensive hygiene & activity audit on all repositories."""
    cfg, gh, ai, logger = get_context()
    cleaner = RepoCleaner(cfg, gh, logger)
    results = cleaner.audit_repositories(threshold_months=threshold_months)
    cleaner.display_audit_table(results)

@cli.command("update-metadata")
@click.argument("repo", required=False)
@click.option("--all", "all_repos", is_flag=True, help="Process all repositories.")
@click.option("--dry-run", is_flag=True, help="Preview suggested description and tags.")
@click.option("--yes", "-y", is_flag=True, help="Auto-apply recommendations without prompt.")
def update_metadata(repo: str, all_repos: bool, dry_run: bool, yes: bool):
    """Generate or enhance repo descriptions, topics/tags, and name suggestions."""
    if not repo and not all_repos:
        console.print("[yellow]Please specify a repo name or pass --all.[/yellow]")
        return
    cfg, gh, ai, logger = get_context()
    mgr = MetadataManager(cfg, gh, ai, logger)
    if all_repos:
        mgr.curate_all_repos(dry_run=dry_run, auto_apply=yes)
    else:
        mgr.curate_repo_metadata(repo_name=repo, dry_run=dry_run, auto_apply=yes)

@cli.command("changelog")
@click.argument("repo")
@click.option("--dry-run", is_flag=True, help="Preview changelog section without committing.")
@click.option("--create-release", is_flag=True, help="Also publish as a GitHub Release.")
@click.option("--target-version", help="Explicit target version (e.g. v1.2.0).")
def changelog(repo: str, dry_run: bool, create_release: bool, target_version: str):
    """Generate CHANGELOG.md and analyze SemVer bump using Gemini AI."""
    cfg, gh, ai, logger = get_context()
    mgr = ChangelogManager(cfg, gh, ai, logger)
    mgr.generate_repo_changelog(
        repo_name=repo,
        dry_run=dry_run,
        create_release=create_release,
        target_version=target_version
    )

@cli.command("logs")
@click.option("--limit", default=10, help="Number of recent logs to show.")
def show_logs(limit: int):
    """View recent action history from activity_log.json."""
    cfg = Config()
    logger = ActivityLogger(cfg.log_file)
    logs = logger.get_recent_logs(limit=limit)

    if not logs:
        console.print("[yellow]No activity logs recorded yet.[/yellow]")
        return

    table = Table(title="GitCurator Activity Log", show_header=True, header_style="bold cyan")
    table.add_column("Timestamp", style="dim")
    table.add_column("Action", style="bold")
    table.add_column("Target Repo", style="yellow")
    table.add_column("Dry Run", justify="center")
    table.add_column("Status")

    for entry in logs:
        status_style = "[green]SUCCESS[/green]" if entry.get("status") == "SUCCESS" else "[red]FAILED[/red]"
        dry_run_str = "Yes" if entry.get("dry_run") else "No"
        table.add_row(
            entry.get("timestamp", "")[:19].replace("T", " "),
            entry.get("action", ""),
            entry.get("repo", "profile") or "profile",
            dry_run_str,
            status_style
        )
    console.print(table)

def main():
    cli()

if __name__ == "__main__":
    main()

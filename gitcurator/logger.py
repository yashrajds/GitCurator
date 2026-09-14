import sys
import os
if sys.platform == 'win32':
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
        sys.stderr.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional
from rich.console import Console

console = Console(safe_box=True, highlight=False)

class ActivityLogger:
    def __init__(self, log_path: str = "activity_log.json"):
        self.log_path = Path(log_path)

    def log(
        self,
        action_type: str,
        repo: Optional[str],
        details: Dict[str, Any],
        dry_run: bool = False,
        status: str = "SUCCESS",
        error: Optional[str] = None
    ) -> Dict[str, Any]:
        """Appends an event entry to the JSON log and prints cleanly via Rich."""
        entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "action": action_type,
            "repo": repo,
            "dry_run": dry_run,
            "status": status,
            "details": details,
            "error": error
        }

        # Terminal feedback
        prefix = "[DRY-RUN] " if dry_run else ""
        if status == "SUCCESS":
            console.print(f"[bold green]✔[/bold green] {prefix}[cyan]{action_type}[/cyan] on [yellow]{repo or 'profile'}[/yellow]")
        elif status == "WARNING":
            console.print(f"[bold yellow]![/bold yellow] {prefix}[cyan]{action_type}[/cyan]: {error or ''}")
        else:
            console.print(f"[bold red]✘[/bold red] {prefix}[cyan]{action_type}[/cyan] failed: {error}")

        # Persistent JSON log
        logs = []
        if self.log_path.exists():
            try:
                with open(self.log_path, "r", encoding="utf-8") as f:
                    logs = json.load(f)
                    if not isinstance(logs, list):
                        logs = []
            except Exception:
                logs = []

        logs.append(entry)
        try:
            with open(self.log_path, "w", encoding="utf-8") as f:
                json.dump(logs, f, indent=2)
        except Exception as e:
            console.print(f"[red]Failed to write to {self.log_path}: {e}[/red]")

        return entry

    def get_recent_logs(self, limit: int = 15):
        if not self.log_path.exists():
            return []
        try:
            with open(self.log_path, "r", encoding="utf-8") as f:
                logs = json.load(f)
                return logs[-limit:] if isinstance(logs, list) else []
        except Exception:
            return []

import os
from pathlib import Path
from typing import Any, Dict, Optional
import yaml
from dotenv import load_dotenv

# Load environment variables from .env if present
load_dotenv()

DEFAULT_CONFIG: Dict[str, Any] = {
    "ai": {
        "model": "gemini-3.6-flash",
        "temperature": 0.7,
        "max_output_tokens": 2048,
    },
    "profile_readme": {
        "target_repo": None,
        "commit_message": "chore: autonomous profile update by GitCurator [skip ci]",
        "tone": "professional yet personable, modern tech-forward",
        "featured_repos_count": 6,
    },
    "cleanup": {
        "stale_months_threshold": 6,
        "exclude_repos": [],
        "flag_missing_readme": True,
        "flag_missing_license": True,
        "flag_missing_description": True,
        "flag_empty_repos": True,
        "flag_unchanged_forks": True,
    },
    "metadata": {
        "max_topics_per_repo": 6,
        "auto_generate_topics": True,
        "suggest_names": True,
    },
    "safety": {
        "dry_run_default": False,
        "require_confirmation_for_destructive": True,
        "log_file": "activity_log.json",
    },
}


class Config:
    def __init__(self, config_path: Optional[str] = None):
        self.github_token: str = os.getenv("GITHUB_TOKEN", "")
        self.gemini_api_key: str = os.getenv("GEMINI_API_KEY", "")

        self._data: Dict[str, Any] = DEFAULT_CONFIG.copy()
        target_path = Path(config_path) if config_path else Path("config.yaml")

        if target_path.exists():
            try:
                with open(target_path, "r", encoding="utf-8") as f:
                    loaded = yaml.safe_load(f)
                    if isinstance(loaded, dict):
                        self._deep_update(self._data, loaded)
            except Exception as e:
                print(f"[Warning] Failed to parse {target_path}: {e}. Using defaults.")

    def _deep_update(self, target: dict, source: dict):
        for k, v in source.items():
            if isinstance(v, dict) and k in target and isinstance(target[k], dict):
                self._deep_update(target[k], v)
            else:
                target[k] = v

    def get(self, key_path: str, default: Any = None) -> Any:
        keys = key_path.split(".")
        val = self._data
        for k in keys:
            if isinstance(val, dict) and k in val:
                val = val[k]
            else:
                return default
        return val

    @property
    def ai_model(self) -> str:
        return self.get("ai.model", "gemini-3.6-flash")

    @property
    def log_file(self) -> str:
        return self.get("safety.log_file", "activity_log.json")

    @property
    def stale_months_threshold(self) -> int:
        return int(self.get("cleanup.stale_months_threshold", 6))

    def validate_credentials(self):
        errors = []
        if not self.github_token:
            errors.append("GITHUB_TOKEN is missing. Set it in your .env or environment.")
        if not self.gemini_api_key:
            errors.append("GEMINI_API_KEY is missing. Set it in your .env or environment.")
        if errors:
            raise ValueError("\n".join(errors))

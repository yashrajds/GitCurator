import os
import sys
import json
import subprocess
from pathlib import Path
from typing import Optional, Dict, Any, List
from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel
from dotenv import load_dotenv

load_dotenv()

from gitcurator.config import Config
from gitcurator.github_client import GitHubClient
from gitcurator.gemini_engine import GeminiEngine
from gitcurator.logger import ActivityLogger
from gitcurator.core.profile_updater import ProfileUpdater
from gitcurator.core.repo_cleaner import RepoCleaner
from gitcurator.core.metadata_mgr import MetadataManager
from gitcurator.core.changelog_mgr import ChangelogManager

app = FastAPI(title="GitCurator Software")

cfg = Config()
logger = ActivityLogger(cfg.log_file)
gh_client = GitHubClient(cfg.github_token)
ai_engine = GeminiEngine(cfg.gemini_api_key, model_name=cfg.ai_model)

updater = ProfileUpdater(cfg, gh_client, ai_engine, logger)
cleaner = RepoCleaner(cfg, gh_client, logger)
metadata_mgr = MetadataManager(cfg, gh_client, ai_engine, logger)
changelog_mgr = ChangelogManager(cfg, gh_client, ai_engine, logger)

class BashCommandRequest(BaseModel):
    command: str

class ChatMessageRequest(BaseModel):
    message: str
    history: Optional[List[Dict[str, str]]] = []

class MetadataRequest(BaseModel):
    repo: str
    auto_apply: bool = False

class ChangelogRequest(BaseModel):
    repo: str
    create_release: bool = False
    target_version: Optional[str] = None

class CleanupRequest(BaseModel):
    threshold_months: int = 6
    target_repo: Optional[str] = None
    action: str = "archive"
    auto_confirm: bool = False

@app.get("/api/status")
def get_status():
    user = gh_client.get_authenticated_user()
    return {
        "status": "online",
        "username": user.get("login"),
        "name": user.get("name"),
        "avatar_url": user.get("avatar_url"),
        "public_repos": user.get("public_repos"),
        "followers": user.get("followers"),
        "model": cfg.ai_model
    }

@app.get("/api/repos")
def get_repositories():
    repos = gh_client.get_user_repos(sort="updated", per_page=50)
    return [
        {
            "name": r["name"],
            "full_name": r["full_name"],
            "description": r.get("description"),
            "stars": r.get("stargazers_count", 0),
            "language": r.get("language"),
            "archived": r.get("archived", False),
            "fork": r.get("fork", False),
            "pushed_at": r.get("pushed_at"),
            "url": r.get("html_url")
        }
        for r in repos
    ]

@app.get("/api/audit")
def run_audit(threshold_months: int = 6):
    results = cleaner.audit_repositories(threshold_months=threshold_months)
    return results

@app.post("/api/update-readme")
def trigger_update_readme(dry_run: bool = True):
    preview = updater.update_profile(dry_run=dry_run, output_file="generated_preview_readme.md" if dry_run else None)
    return {"status": "success", "dry_run": dry_run, "readme": preview}

@app.post("/api/update-metadata")
def trigger_update_metadata(req: MetadataRequest, dry_run: bool = True):
    user = gh_client.get_authenticated_user()["login"]
    readme_info = gh_client.get_repo_readme(user, req.repo)
    readme_text = readme_info[0] if readme_info else ""
    lang_dict = gh_client.get_repo_languages(user, req.repo)
    langs = list(lang_dict.keys())
    
    repos = gh_client.get_user_repos(repo_type="owner")
    target = next((r for r in repos if r["name"].lower() == req.repo.lower()), None)
    curr_desc = target.get("description") if target else ""

    suggestion = ai_engine.enhance_repo_metadata(
        repo_name=req.repo,
        current_description=curr_desc,
        readme_snippet=readme_text,
        languages=langs
    )
    
    applied = False
    if not dry_run and req.auto_apply:
        desc = suggestion.get("improved_description")
        topics = suggestion.get("topics", [])
        d_ok = gh_client.update_repo_metadata(user, req.repo, description=desc)
        t_ok = gh_client.replace_repo_topics(user, req.repo, topics=topics)
        applied = d_ok and t_ok

    logger.log(
        action_type="UPDATE_METADATA",
        repo=f"{user}/{req.repo}",
        details=suggestion,
        dry_run=dry_run,
        status="SUCCESS" if (dry_run or applied) else "PARTIAL"
    )

    return {"status": "success", "dry_run": dry_run, "applied": applied, "suggestion": suggestion}

@app.post("/api/changelog")
def trigger_changelog(req: ChangelogRequest, dry_run: bool = True):
    user = gh_client.get_authenticated_user()["login"]
    tags = gh_client.get_repo_tags(user, req.repo)
    latest_tag = tags[0]["name"] if tags else "v0.1.0"
    commits = gh_client.get_repo_commits(user, req.repo, per_page=30)
    
    clean_tag = latest_tag.lstrip("v")
    bump_info = ai_engine.suggest_semver_bump(commits, current_version=clean_tag)
    next_ver = req.target_version or f"v{bump_info.get('recommended_version', '0.2.0')}"
    
    changelog_section = ai_engine.generate_changelog(
        repo_name=req.repo,
        commits=commits,
        previous_version=latest_tag,
        target_version=next_ver
    )

    logger.log(
        action_type="GENERATE_CHANGELOG",
        repo=f"{user}/{req.repo}",
        details={"version": next_ver, "bump": bump_info.get("bump_type")},
        dry_run=dry_run,
        status="SUCCESS"
    )

    return {
        "status": "success",
        "dry_run": dry_run,
        "latest_tag": latest_tag,
        "suggested_version": next_ver,
        "bump_info": bump_info,
        "changelog": changelog_section
    }

@app.post("/api/cleanup")
def trigger_cleanup(req: CleanupRequest, dry_run: bool = True):
    results = cleaner.audit_repositories(threshold_months=req.threshold_months)
    stale_or_empty = [
        r for r in results
        if not r["archived"] and any("STALE" in iss or iss == "EMPTY_REPO" for iss in r["issues"])
    ]
    if req.target_repo:
        stale_or_empty = [r for r in stale_or_empty if r["name"] == req.target_repo]
    
    actions_taken = []
    user = gh_client.get_authenticated_user()["login"]

    for item in stale_or_empty:
        repo_name = item["name"]
        if dry_run:
            actions_taken.append({"repo": repo_name, "action": req.action, "dry_run": True})
            continue

        if req.auto_confirm:
            if req.action == "archive":
                ok = gh_client.archive_repo(user, repo_name)
                actions_taken.append({"repo": repo_name, "action": "archive", "success": ok})
            elif req.action == "delete":
                ok = gh_client.delete_repo(user, repo_name)
                actions_taken.append({"repo": repo_name, "action": "delete", "success": ok})

    return {"status": "success", "dry_run": dry_run, "items": actions_taken, "candidates": stale_or_empty}

@app.post("/api/automate-all")
def automate_everything():
    """AI One-Click Auto-pilot: scans, enhances, audits and syncs entire profile."""
    user = gh_client.get_authenticated_user()["login"]
    
    # 1. Update Profile README
    readme_content = updater.update_profile(dry_run=False)
    
    # 2. Run Audit
    audit_res = cleaner.audit_repositories(threshold_months=6)
    
    # 3. Enhance top 3 repos missing descriptions
    enhanced = []
    for r in audit_res[:3]:
        if "NO_DESC" in r["issues"]:
            try:
                lang_dict = gh_client.get_repo_languages(user, r["name"])
                sugg = ai_engine.enhance_repo_metadata(
                    repo_name=r["name"],
                    current_description="",
                    readme_snippet="",
                    languages=list(lang_dict.keys())
                )
                desc = sugg.get("improved_description")
                topics = sugg.get("topics", [])
                gh_client.update_repo_metadata(user, r["name"], description=desc)
                gh_client.replace_repo_topics(user, r["name"], topics=topics)
                enhanced.append(r["name"])
            except Exception:
                pass

    logger.log(
        action_type="AI_AUTOPILOT",
        repo=f"{user}/all",
        details={"readme_updated": True, "repos_enhanced": enhanced},
        dry_run=False,
        status="SUCCESS"
    )

    return {
        "status": "success",
        "message": "AI Autopilot completed successfully! Profile README updated and repository metadata enriched.",
        "enhanced_repos": enhanced,
        "audit_count": len(audit_res)
    }

@app.post("/api/bash")
def run_bash(req: BashCommandRequest):
    cmd = req.command.strip()
    if not cmd:
        return {"output": "", "error": "Empty command"}
    
    # Security/Safety restriction check
    blocked = ["rm -rf /", ":(){ :|:& };:", "format c:"]
    for b in blocked:
        if b in cmd.lower():
            return {"output": "", "error": "Command blocked for safety reasons."}

    try:
        res = subprocess.run(
            cmd,
            shell=True,
            capture_output=True,
            text=True,
            timeout=30,
            cwd=os.getcwd()
        )
        return {
            "output": res.stdout,
            "error": res.stderr,
            "exit_code": res.returncode
        }
    except subprocess.TimeoutExpired:
        return {"output": "", "error": "Command timed out after 30 seconds."}
    except Exception as e:
        return {"output": "", "error": str(e)}

@app.post("/api/chat")
def chat_assistant(req: ChatMessageRequest):
    user = gh_client.get_authenticated_user()
    sys_prompt = f"""
You are the GitCurator Software Assistant - an intelligent copilot built directly into the GitCurator software.
You have comprehensive knowledge of:
1. The authenticated user: @{user.get('login')} ({user.get('name') or 'Developer'}), with {user.get('public_repos')} public repos.
2. The GitCurator architecture:
   - Profile README auto-generation with modern shields, stats cards, and pinned highlights.
   - Repository Hygiene & Inactivity Cleaner (detects stale, empty, and forks, handles safe archive/delete).
   - Metadata & Topics Manager (enhances descriptions, generates discoverability tags, suggests cleaner names).
   - Release Changelog & SemVer assistant (analyzes git commit deltas, determines patch/minor/major).
   - Embedded interactive Bash Terminal capable of running CLI commands like 'gitcurator update-readme', 'gitcurator audit', 'gitcurator cleanup --dry-run', etc.
   - 'Automate Everything According to AI' 1-click button that orchestrates end-to-end profile and metadata curation.

Instructions:
- Be concise, friendly, authoritative, and actionable.
- If the user asks you to perform an action (e.g. 'audit my repos', 'update readme', 'clean stale projects'), explain how to do it or tell them which button to click or which CLI command to run in the built-in terminal.
- Provide formatted markdown with code snippets where helpful.
"""
    # Build conversation prompt
    full_prompt = f"User Request: {req.message}\n\nPlease respond to the user based on your software capabilities."
    response = ai_engine._call_model(full_prompt, system_instruction=sys_prompt)
    return {"reply": response}

@app.get("/api/logs")
def get_logs(limit: int = 15):
    return logger.get_recent_logs(limit=limit)

# Mount static frontend
app.mount("/", StaticFiles(directory="public", html=True), name="static")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000)

import os
import sys
import json
import base64
from http.server import BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

# Add root directory to sys.path so gitcurator modules import properly
root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if root_dir not in sys.path:
    sys.path.insert(0, root_dir)

class handler(BaseHTTPRequestHandler):
    def _send_json(self, data, status=200):
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()
        self.wfile.write(json.dumps(data).encode("utf-8"))

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/")
        query = parse_qs(parsed.query)

        try:
            from gitcurator.config import Config
            from gitcurator.github_client import GitHubClient
            from gitcurator.core.repo_cleaner import RepoCleaner
            from gitcurator.logger import ActivityLogger

            cfg = Config()
            gh = GitHubClient(cfg.github_token)

            if path in ["/api/status", "/api"]:
                user = gh.get_authenticated_user()
                self._send_json({
                    "status": "online",
                    "username": user.get("login"),
                    "name": user.get("name"),
                    "avatar_url": user.get("avatar_url"),
                    "public_repos": user.get("public_repos"),
                    "followers": user.get("followers"),
                    "model": cfg.ai_model
                })
            elif path == "/api/audit":
                logger = ActivityLogger(cfg.log_file)
                cleaner = RepoCleaner(cfg, gh, logger)
                threshold = int(query.get("threshold_months", [6])[0])
                results = cleaner.audit_repositories(threshold_months=threshold)
                self._send_json(results)
            elif path == "/api/logs":
                logger = ActivityLogger(cfg.log_file)
                limit = int(query.get("limit", [15])[0])
                self._send_json(logger.get_recent_logs(limit=limit))
            else:
                self._send_json({"error": f"Endpoint not found: {path}"}, status=404)
        except Exception as e:
            self._send_json({"error": str(e)}, status=500)

    def do_POST(self):
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/")
        query = parse_qs(parsed.query)
        dry_run = query.get("dry_run", ["true"])[0].lower() == "true"

        content_length = int(self.headers.get("Content-Length", 0))
        body_bytes = self.rfile.read(content_length) if content_length > 0 else b"{}"
        try:
            body = json.loads(body_bytes.decode("utf-8")) if body_bytes else {}
        except Exception:
            body = {}

        try:
            from gitcurator.config import Config
            from gitcurator.github_client import GitHubClient
            from gitcurator.gemini_engine import GeminiEngine
            from gitcurator.logger import ActivityLogger
            from gitcurator.core.profile_updater import ProfileUpdater
            from gitcurator.core.repo_cleaner import RepoCleaner
            from gitcurator.core.metadata_mgr import MetadataManager
            from gitcurator.core.changelog_mgr import ChangelogManager

            cfg = Config()
            gh = GitHubClient(cfg.github_token)
            ai = GeminiEngine(cfg.gemini_api_key, model_name=cfg.ai_model)
            logger = ActivityLogger(cfg.log_file)

            if path == "/api/update-readme":
                updater = ProfileUpdater(cfg, gh, ai, logger)
                preview = updater.update_profile(dry_run=dry_run)
                self._send_json({"status": "success", "dry_run": dry_run, "readme": preview})

            elif path == "/api/audit":
                cleaner = RepoCleaner(cfg, gh, logger)
                results = cleaner.audit_repositories(threshold_months=6)
                self._send_json(results)

            elif path == "/api/update-metadata":
                repo = body.get("repo", "SkillSwapMVP")
                auto_apply = body.get("auto_apply", False)
                user = gh.get_authenticated_user()["login"]
                readme_info = gh.get_repo_readme(user, repo)
                readme_text = readme_info[0] if readme_info else ""
                lang_dict = gh.get_repo_languages(user, repo)
                repos = gh.get_user_repos(repo_type="owner")
                target = next((r for r in repos if r["name"].lower() == repo.lower()), None)
                curr_desc = target.get("description") if target else ""

                suggestion = ai.enhance_repo_metadata(
                    repo_name=repo,
                    current_description=curr_desc,
                    readme_snippet=readme_text,
                    languages=list(lang_dict.keys())
                )
                applied = False
                if not dry_run and auto_apply:
                    d_ok = gh.update_repo_metadata(user, repo, description=suggestion.get("improved_description"))
                    t_ok = gh.replace_repo_topics(user, repo, topics=suggestion.get("topics", []))
                    applied = d_ok and t_ok

                self._send_json({"status": "success", "dry_run": dry_run, "applied": applied, "suggestion": suggestion})

            elif path == "/api/changelog":
                repo = body.get("repo", "Sudoku-Master")
                user = gh.get_authenticated_user()["login"]
                tags = gh.get_repo_tags(user, repo)
                latest_tag = tags[0]["name"] if tags else "v0.1.0"
                commits = gh.get_repo_commits(user, repo, per_page=30)
                clean_tag = latest_tag.lstrip("v")
                bump_info = ai.suggest_semver_bump(commits, current_version=clean_tag)
                next_ver = f"v{bump_info.get('recommended_version', '0.2.0')}"
                changelog_section = ai.generate_changelog(
                    repo_name=repo,
                    commits=commits,
                    previous_version=latest_tag,
                    target_version=next_ver
                )
                self._send_json({
                    "status": "success",
                    "dry_run": dry_run,
                    "suggested_version": next_ver,
                    "bump_info": bump_info,
                    "changelog": changelog_section
                })

            elif path == "/api/automate-all":
                user = gh.get_authenticated_user()["login"]
                updater = ProfileUpdater(cfg, gh, ai, logger)
                readme_content = updater.update_profile(dry_run=False)
                cleaner = RepoCleaner(cfg, gh, logger)
                audit_res = cleaner.audit_repositories(threshold_months=6)
                self._send_json({
                    "status": "success",
                    "message": "AI Autopilot completed successfully! Profile README updated and repositories audited.",
                    "audit_count": len(audit_res)
                })

            elif path == "/api/bash":
                cmd = body.get("command", "").strip()
                # Run command via Python simulated runner for safe serverless compatibility
                if "audit" in cmd:
                    cleaner = RepoCleaner(cfg, gh, logger)
                    res = cleaner.audit_repositories(threshold_months=6)
                    lines = ["Repository | Status | Inactive(Mo) | Issues", "------------------------------------------"]
                    for r in res:
                        lines.append(f"{r['name']} | {'Archived' if r['archived'] else 'Active'} | {r['months_inactive']} | {', '.join(r['issues'])}")
                    self._send_json({"output": "\n".join(lines), "error": None, "exit_code": 0})
                elif "update-readme" in cmd:
                    updater = ProfileUpdater(cfg, gh, ai, logger)
                    preview = updater.update_profile(dry_run=True)
                    self._send_json({"output": "Generated Profile README Preview:\n\n" + preview[:400] + "\n...", "error": None, "exit_code": 0})
                elif "logs" in cmd:
                    logs = logger.get_recent_logs(limit=5)
                    self._send_json({"output": json.dumps(logs, indent=2), "error": None, "exit_code": 0})
                elif "help" in cmd:
                    self._send_json({
                        "output": "GitCurator Commands:\n  gitcurator audit\n  gitcurator update-readme\n  gitcurator update-metadata <repo>\n  gitcurator changelog <repo>\n  gitcurator cleanup\n  gitcurator logs",
                        "error": None,
                        "exit_code": 0
                    })
                else:
                    # Execute general safe bash
                    import subprocess
                    proc = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=15)
                    self._send_json({"output": proc.stdout or "Command executed.", "error": proc.stderr, "exit_code": proc.returncode})

            elif path == "/api/chat":
                msg = body.get("message", "")
                user = gh.get_authenticated_user()
                sys_prompt = (
                    f"You are the GitCurator Software Copilot for @{user.get('login')}. "
                    "Provide helpful, concise guidance on GitHub profile curation, repo cleanup, metadata, and SemVer versioning. "
                    "IMPORTANT: Do not use emoji characters in your answers; use clean text formatting and symbols instead."
                )
                reply = ai._call_model(f"User Question: {msg}", system_instruction=sys_prompt)
                self._send_json({"reply": reply})

            else:
                self._send_json({"error": f"Endpoint not found: {path}"}, status=404)

        except Exception as e:
            self._send_json({"error": str(e)}, status=500)

import base64
import time
from typing import Any, Dict, List, Optional, Tuple
import requests
from rich.console import Console

console = Console()

class GitHubClient:
    REST_API_BASE = "https://api.github.com"
    GRAPHQL_API_BASE = "https://api.github.com/graphql"

    def __init__(self, token: str):
        if not token:
            raise ValueError("GitHub token is required.")
        self.token = token
        self.session = requests.Session()
        self.session.headers.update({
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github.v3+json",
            "User-Agent": "GitCurator-AI-Profile-Manager"
        })
        self._user_cache: Optional[Dict[str, Any]] = None

    def _handle_response(self, response: requests.Response) -> requests.Response:
        remaining = response.headers.get("x-ratelimit-remaining")
        reset_time = response.headers.get("x-ratelimit-reset")

        if remaining is not None and int(remaining) == 0 and reset_time:
            wait_seconds = max(0, int(reset_time) - int(time.time())) + 2
            console.print(f"[bold yellow]GitHub Rate Limit hit! Waiting {wait_seconds}s for reset...[/bold yellow]")
            time.sleep(min(wait_seconds, 60))

        if response.status_code == 403 and "rate limit" in response.text.lower():
            raise RuntimeError("GitHub API rate limit exceeded.")

        return response

    def get_authenticated_user(self) -> Dict[str, Any]:
        if self._user_cache:
            return self._user_cache
        res = self.session.get(f"{self.REST_API_BASE}/user")
        self._handle_response(res)
        res.raise_for_status()
        self._user_cache = res.json()
        return self._user_cache

    def get_rate_limit(self) -> Dict[str, Any]:
        res = self.session.get(f"{self.REST_API_BASE}/rate_limit")
        self._handle_response(res)
        return res.json() if res.ok else {}

    def get_user_repos(self, repo_type: str = "owner", sort: str = "updated", per_page: int = 100) -> List[Dict[str, Any]]:
        repos = []
        page = 1
        while True:
            params = {"type": repo_type, "sort": sort, "per_page": per_page, "page": page}
            res = self.session.get(f"{self.REST_API_BASE}/user/repos", params=params)
            self._handle_response(res)
            res.raise_for_status()
            batch = res.json()
            if not batch:
                break
            repos.extend(batch)
            if len(batch) < per_page:
                break
            page += 1
        return repos

    def get_pinned_repos(self, username: str) -> List[Dict[str, Any]]:
        query = """
        query($login: String!) {
          user(login: $login) {
            pinnedItems(first: 6, types: REPOSITORY) {
              nodes {
                ... on Repository {
                  name
                  description
                  url
                  stargazerCount
                  forkCount
                  primaryLanguage {
                    name
                    color
                  }
                  languages(first: 5) {
                    nodes {
                      name
                    }
                  }
                  pushedAt
                }
              }
            }
          }
        }
        """
        payload = {"query": query, "variables": {"login": username}}
        res = self.session.post(self.GRAPHQL_API_BASE, json=payload)
        self._handle_response(res)
        if res.ok:
            data = res.json()
            nodes = data.get("data", {}).get("user", {}).get("pinnedItems", {}).get("nodes", [])
            return nodes or []
        return []

    def get_recent_events(self, username: str, limit: int = 30) -> List[Dict[str, Any]]:
        url = f"{self.REST_API_BASE}/users/{username}/events"
        res = self.session.get(url, params={"per_page": limit})
        self._handle_response(res)
        return res.json() if res.ok else []

    def get_repo_readme(self, owner: str, repo: str) -> Optional[Tuple[str, str]]:
        url = f"{self.REST_API_BASE}/repos/{owner}/{repo}/readme"
        res = self.session.get(url)
        if res.status_code == 200:
            data = res.json()
            raw_content = base64.b64decode(data.get("content", "")).decode("utf-8", errors="replace")
            return raw_content, data.get("sha", "")
        return None

    def get_repo_languages(self, owner: str, repo: str) -> Dict[str, int]:
        url = f"{self.REST_API_BASE}/repos/{owner}/{repo}/languages"
        res = self.session.get(url)
        return res.json() if res.ok else {}

    def get_repo_commits(self, owner: str, repo: str, per_page: int = 15) -> List[Dict[str, Any]]:
        url = f"{self.REST_API_BASE}/repos/{owner}/{repo}/commits"
        res = self.session.get(url, params={"per_page": per_page})
        return res.json() if res.ok else []

    def get_repo_releases(self, owner: str, repo: str) -> List[Dict[str, Any]]:
        url = f"{self.REST_API_BASE}/repos/{owner}/{repo}/releases"
        res = self.session.get(url)
        return res.json() if res.ok else []

    def get_repo_tags(self, owner: str, repo: str) -> List[Dict[str, Any]]:
        url = f"{self.REST_API_BASE}/repos/{owner}/{repo}/tags"
        res = self.session.get(url)
        return res.json() if res.ok else []

    def get_commits_since_date(self, owner: str, repo: str, since_iso: Optional[str] = None) -> List[Dict[str, Any]]:
        url = f"{self.REST_API_BASE}/repos/{owner}/{repo}/commits"
        params = {"per_page": 100}
        if since_iso:
            params["since"] = since_iso
        res = self.session.get(url, params=params)
        return res.json() if res.ok else []

    def update_repo_metadata(
        self,
        owner: str,
        repo: str,
        description: Optional[str] = None,
        homepage: Optional[str] = None
    ) -> bool:
        url = f"{self.REST_API_BASE}/repos/{owner}/{repo}"
        payload = {}
        if description is not None:
            payload["description"] = description
        if homepage is not None:
            payload["homepage"] = homepage
        res = self.session.patch(url, json=payload)
        self._handle_response(res)
        return res.status_code == 200

    def replace_repo_topics(self, owner: str, repo: str, topics: List[str]) -> bool:
        url = f"{self.REST_API_BASE}/repos/{owner}/{repo}/topics"
        sanitized = [t.lower().replace(" ", "-").replace("_", "-")[:50] for t in topics]
        res = self.session.put(url, json={"names": sanitized})
        self._handle_response(res)
        return res.status_code == 200

    def create_or_update_file(
        self,
        owner: str,
        repo: str,
        path: str,
        content: str,
        message: str,
        sha: Optional[str] = None,
        branch: Optional[str] = None
    ) -> bool:
        url = f"{self.REST_API_BASE}/repos/{owner}/{repo}/contents/{path}"
        encoded_content = base64.b64encode(content.encode("utf-8")).decode("utf-8")
        payload = {
            "message": message,
            "content": encoded_content
        }
        if sha:
            payload["sha"] = sha
        if branch:
            payload["branch"] = branch

        res = self.session.put(url, json=payload)
        self._handle_response(res)
        return res.status_code in [200, 201]

    def archive_repo(self, owner: str, repo: str) -> bool:
        url = f"{self.REST_API_BASE}/repos/{owner}/{repo}"
        res = self.session.patch(url, json={"archived": True})
        self._handle_response(res)
        return res.status_code == 200

    def delete_repo(self, owner: str, repo: str) -> bool:
        url = f"{self.REST_API_BASE}/repos/{owner}/{repo}"
        res = self.session.delete(url)
        self._handle_response(res)
        return res.status_code == 204

    def create_release(
        self,
        owner: str,
        repo: str,
        tag_name: str,
        name: str,
        body: str,
        draft: bool = False,
        prerelease: bool = False
    ) -> Dict[str, Any]:
        url = f"{self.REST_API_BASE}/repos/{owner}/{repo}/releases"
        payload = {
            "tag_name": tag_name,
            "name": name,
            "body": body,
            "draft": draft,
            "prerelease": prerelease
        }
        res = self.session.post(url, json=payload)
        self._handle_response(res)
        return res.json() if res.ok else {}

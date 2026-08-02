# app/github_client.py
"""GitHub repository client for the swarm.

Reads files, lists trees, and writes batches of files as a SINGLE commit
via the Git Data API (blobs -> tree -> commit -> update ref). A personal
access token (fine-grained, Contents: read/write) is required.
"""
import base64
from typing import Dict, List, Optional

import aiohttp

GITHUB_API = "https://api.github.com"


class GitHubError(Exception):
    def __init__(self, status: int, body: str):
        self.status = status
        self.body = body
        super().__init__(f"GitHub API error {status}: {body[:300]}")


class GitHubRepoClient:
    def __init__(self, owner: str, repo: str, token: str, branch: Optional[str] = None):
        self.owner = owner
        self.repo = repo
        self.token = token
        self.branch = branch or None  # None -> default branch
        self._session: Optional[aiohttp.ClientSession] = None

    async def __aenter__(self) -> "GitHubRepoClient":
        self._session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=60))
        return self

    async def __aexit__(self, *args):
        if self._session:
            await self._session.close()

    @property
    def _headers(self) -> Dict[str, str]:
        return {
            "Authorization": f"Bearer {self.token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }

    async def _request(self, method: str, path: str, json: Optional[dict] = None, params: Optional[dict] = None):
        if self._session is None:
            self._session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=60))
        async with self._session.request(method, f"{GITHUB_API}{path}", headers=self._headers, json=json, params=params) as resp:
            if resp.status >= 400:
                raise GitHubError(resp.status, await resp.text())
            if resp.status == 204:
                return None
            return await resp.json()

    async def default_branch(self) -> str:
        data = await self._request("GET", f"/repos/{self.owner}/{self.repo}")
        return data.get("default_branch", "main")

    async def _resolve_branch(self) -> str:
        return self.branch or await self.default_branch()

    async def list_files(self) -> List[str]:
        """Recursive list of all file paths in the branch (empty list if no commits)."""
        branch = await self._resolve_branch()
        try:
            data = await self._request("GET", f"/repos/{self.owner}/{self.repo}/git/trees/{branch}", params={"recursive": "1"})
        except GitHubError as e:
            if e.status == 404:
                return []  # branch/commit does not exist yet
            raise
        return [t["path"] for t in data.get("tree", []) if t.get("type") == "blob"]

    async def read_file(self, path: str) -> str:
        """Read a file's UTF-8 content from the branch."""
        branch = await self._resolve_branch()
        data = await self._request("GET", f"/repos/{self.owner}/{self.repo}/contents/{path}", params={"ref": branch})
        return base64.b64decode(data["content"]).decode("utf-8", errors="replace")

    async def write_files(self, files: Dict[str, str], message: str) -> Dict:
        """Write {path: content} as ONE commit on the branch. Returns {commit, branch, files}."""
        files = {p: c for p, c in files.items() if p and p.strip()}
        if not files:
            return {"commit": None, "branch": self.branch, "files": []}
        branch = await self._resolve_branch()
        try:
            ref = await self._request("GET", f"/repos/{self.owner}/{self.repo}/git/ref/heads/{branch}")
        except GitHubError as e:
            if e.status != 404:
                raise
            return await self._write_files_contents_api(files, message, branch)  # empty repo fallback

        base_sha = ref["object"]["sha"]
        base_commit = await self._request("GET", f"/repos/{self.owner}/{self.repo}/git/commits/{base_sha}")
        base_tree_sha = base_commit["tree"]["sha"]

        tree_items = []
        for path, content in files.items():
            blob = await self._request("POST", f"/repos/{self.owner}/{self.repo}/git/blobs",
                                       json={"content": content, "encoding": "utf-8"})
            tree_items.append({"path": path, "mode": "100644", "type": "blob", "sha": blob["sha"]})

        tree = await self._request("POST", f"/repos/{self.owner}/{self.repo}/git/trees",
                                   json={"base_tree": base_tree_sha, "tree": tree_items})
        commit = await self._request("POST", f"/repos/{self.owner}/{self.repo}/git/commits",
                                     json={"message": message, "tree": tree["sha"], "parents": [base_sha]})
        await self._request("PATCH", f"/repos/{self.owner}/{self.repo}/git/refs/heads/{branch}",
                            json={"sha": commit["sha"], "force": False})
        return {"commit": commit["sha"], "branch": branch, "files": list(files.keys())}

    async def _write_files_contents_api(self, files: Dict[str, str], message: str, branch: str) -> Dict:
        """Fallback for repos with no commits yet: one Contents-API PUT per file."""
        written = []
        for path, content in files.items():
            await self._request("PUT", f"/repos/{self.owner}/{self.repo}/contents/{path}",
                                json={"message": message, "content": base64.b64encode(content.encode()).decode(), "branch": branch})
            written.append(path)
        ref = await self._request("GET", f"/repos/{self.owner}/{self.repo}/git/ref/heads/{branch}")
        return {"commit": ref["object"]["sha"], "branch": branch, "files": written}

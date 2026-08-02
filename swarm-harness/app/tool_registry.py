# app/tool_registry.py
"""Tool registry with repo-backed tools.

The swarm pipeline does not do live function-calling: agents emit structured
file manifests, and the coordinator drives these tools. Tools stage file
writes and commit them as ONE commit at the end of the build.
"""
import asyncio
from typing import Callable, Dict, List

from app.github_client import GitHubError, GitHubRepoClient


class ToolRegistry:
    def __init__(self):
        self.tools: Dict[str, Callable] = {}

    def register(self, name: str, func: Callable):
        self.tools[name] = func

    async def execute(self, name: str, params: Dict) -> str:
        if name not in self.tools:
            return f"Error: Tool '{name}' not found"
        try:
            func = self.tools[name]
            result = await func(**params) if asyncio.iscoroutinefunction(func) else func(**params)
            return str(result)
        except Exception as e:
            return f"Tool error: {str(e)}"


def repo_registry(client: GitHubRepoClient) -> ToolRegistry:
    """Real tools bound to a GitHub repo. Writes are staged and committed at build end."""
    registry = ToolRegistry()
    staging: Dict[str, str] = {}

    async def _read_file(path: str) -> str:
        if path in staging:
            return staging[path]
        try:
            return await client.read_file(path)
        except GitHubError as e:
            return f"Error reading {path}: {e}"

    async def _list_files() -> str:
        try:
            files = await client.list_files()
            return "\n".join(files) if files else "(empty repository)"
        except GitHubError as e:
            return f"Error listing files: {e}"

    async def _write_file(path: str, content: str) -> str:
        staging[path] = content
        return f"Staged {len(content)} chars to {path} (committed at end of build)"

    async def _commit(message: str) -> str:
        if not staging:
            return "No changes to commit"
        result = await client.write_files(dict(staging), message)
        staging.clear()
        return f"Committed {len(result['files'])} files to {client.owner}/{client.repo}@{result['branch']} ({result['commit'][:10]})"

    registry.register("read_file", _read_file)
    registry.register("list_files", _list_files)
    registry.register("write_file", _write_file)
    registry.register("commit", _commit)
    registry.staging = staging  # type: ignore[attr-defined]
    return registry

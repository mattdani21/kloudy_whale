# tests/test_tool_registry.py
import pytest

from app.tool_registry import repo_registry


class FakeGitHubClient:
    owner = "acme"
    repo = "proj"

    def __init__(self):
        self.files = {}
        self.commits = []

    async def read_file(self, path):
        return self.files.get(path, "NOT IN REPO")

    async def list_files(self):
        return list(self.files.keys())

    async def write_files(self, files, message):
        self.files.update(files)
        self.commits.append((message, dict(files)))
        return {"commit": "sha123", "branch": "main", "files": list(files.keys())}


@pytest.mark.asyncio
async def test_write_then_commit_stages_one_commit():
    client = FakeGitHubClient()
    reg = repo_registry(client)  # type: ignore[arg-type]

    await reg.execute("write_file", {"path": "app.py", "content": "x = 1"})
    await reg.execute("write_file", {"path": "readme.md", "content": "# hi"})
    out = await reg.execute("commit", {"message": "build 1"})

    assert "Committed 2 files" in out
    assert "acme/proj@main" in out or "acme/proj" in out
    assert len(client.commits) == 1
    assert set(client.commits[0][1].keys()) == {"app.py", "readme.md"}
    assert reg.staging == {}  # type: ignore[attr-defined]


@pytest.mark.asyncio
async def test_read_returns_staged_content_first():
    client = FakeGitHubClient()
    reg = repo_registry(client)  # type: ignore[arg-type]

    await reg.execute("write_file", {"path": "new.py", "content": "fresh"})
    out = await reg.execute("read_file", {"path": "new.py"})
    assert out == "fresh"


@pytest.mark.asyncio
async def test_read_passes_through_to_repo():
    client = FakeGitHubClient()
    client.files["existing.py"] = "old"
    reg = repo_registry(client)  # type: ignore[arg-type]

    out = await reg.execute("read_file", {"path": "existing.py"})
    assert out == "old"


@pytest.mark.asyncio
async def test_list_files_and_empty_commit():
    client = FakeGitHubClient()
    client.files["a.py"] = "1"
    reg = repo_registry(client)  # type: ignore[arg-type]

    listing = await reg.execute("list_files", {})
    assert "a.py" in listing

    out = await reg.execute("commit", {"message": "nothing"})
    assert out == "No changes to commit"
    assert client.commits == []

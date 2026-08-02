# tests/test_github_client.py
import base64
import pytest

from app.github_client import GitHubError, GitHubRepoClient


class FakeResponse:
    def __init__(self, status, payload=None, text=""):
        self.status = status
        self._payload = payload
        self._text = text

    async def json(self):
        return self._payload

    async def text(self):
        return self._text


class _Ctx:
    def __init__(self, resp):
        self._resp = resp

    async def __aenter__(self):
        return self._resp

    async def __aexit__(self, *a):
        return False


class FakeSession:
    """Scripted aiohttp session: each request pops the next queued response."""

    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def request(self, method, url, **kwargs):
        entry = self.responses.pop(0)
        if len(entry) == 2:
            entry = (entry[0], entry[1], "")
        status, payload, text = entry
        self.calls.append((method, url, kwargs.get("json")))
        return _Ctx(FakeResponse(status, payload, text))


def make_client(session):
    client = GitHubRepoClient(owner="acme", repo="proj", token="tok", branch="main")
    client._session = session  # inject fake (avoids real aiohttp session)
    return client


@pytest.mark.asyncio
async def test_list_files_parses_recursive_tree():
    client = make_client(FakeSession([
        (200, {"tree": [{"path": "a.py", "type": "blob"}, {"path": "src/b.py", "type": "blob"},
                        {"path": "src", "type": "tree"}]}),
    ]))
    files = await client.list_files()
    assert files == ["a.py", "src/b.py"]


@pytest.mark.asyncio
async def test_list_files_empty_repo_returns_empty():
    client = make_client(FakeSession([(404, None, "not found")]))
    assert await client.list_files() == []


@pytest.mark.asyncio
async def test_read_file_decodes_base64():
    content = "print('hi')\n"
    encoded = base64.b64encode(content.encode()).decode()
    client = make_client(FakeSession([(200, {"content": encoded})]))
    assert await client.read_file("hello.py") == content


@pytest.mark.asyncio
async def test_write_files_single_commit_flow():
    client = make_client(FakeSession([
        (200, {"object": {"sha": "base"}}),                          # ref
        (200, {"tree": {"sha": "t1"}}),                              # base commit
        (200, {"sha": "b1"}),                                        # blob 1
        (200, {"sha": "b2"}),                                        # blob 2
        (200, {"sha": "t2"}),                                        # new tree
        (200, {"sha": "c1"}),                                        # commit
        (204, None),                                                 # update ref
    ]))
    result = await client.write_files({"a.py": "x", "b.py": "y"}, "msg")
    assert result == {"commit": "c1", "branch": "main", "files": ["a.py", "b.py"]}
    methods = [c[0] for c in client._session.calls]
    assert methods == ["GET", "GET", "POST", "POST", "POST", "POST", "PATCH"]
    # blobs carry utf-8 content
    blob_payloads = [c[2] for c in client._session.calls if c[0] == "POST" and "blobs" in c[1]]
    assert {p["content"] for p in blob_payloads} == {"x", "y"}
    commit_payload = [c[2] for c in client._session.calls if c[0] == "POST" and "commits" in c[1]][0]
    assert commit_payload["message"] == "msg"
    assert commit_payload["tree"] == "t2"
    assert commit_payload["parents"] == ["base"]


@pytest.mark.asyncio
async def test_write_files_empty_repo_uses_contents_api():
    client = make_client(FakeSession([
        (404, None, "no ref"),                          # ref -> 404 (no commits)
        (200, {"content": "ignored"}),                  # contents PUT (returns file object)
        (200, {"object": {"sha": "c9"}}),               # ref after write
    ]))
    result = await client.write_files({"a.py": "x"}, "initial")
    assert result["commit"] == "c9"
    assert result["files"] == ["a.py"]
    assert client._session.calls[1][0] == "PUT"


@pytest.mark.asyncio
async def test_http_error_surfaces_status():
    client = make_client(FakeSession([(401, None, '{"message":"Bad credentials"}')]))
    with pytest.raises(GitHubError) as exc:
        await client.list_files()
    assert exc.value.status == 401
    assert "Bad credentials" in exc.value.body


@pytest.mark.asyncio
async def test_write_files_skips_empty_paths():
    client = make_client(FakeSession([
        (200, {"object": {"sha": "base"}}),
        (200, {"tree": {"sha": "t1"}}),
        (200, {"sha": "b1"}),
        (200, {"sha": "t2"}),
        (200, {"sha": "c1"}),
        (204, None),
    ]))
    result = await client.write_files({"": "junk", "ok.py": "y"}, "msg")
    assert result["files"] == ["ok.py"]
    assert len([c for c in client._session.calls if c[0] == "POST" and "blobs" in c[1]]) == 1

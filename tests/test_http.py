from __future__ import annotations

import hashlib

import httpx
import pytest

from envxx import http
from envxx.errors import ChecksumError


def test_apply_mirror_default():
    assert http.apply_mirror("https://nodejs.org/dist/index.json") == (
        "https://nodejs.org/dist/index.json"
    )


def test_apply_mirror_override(monkeypatch):
    monkeypatch.setenv("ENVXX_NODE_DIST", "https://mirror.example/node/")
    assert http.apply_mirror("https://nodejs.org/dist/index.json") == (
        "https://mirror.example/node/index.json"
    )


def test_apply_mirror_github_api(monkeypatch):
    monkeypatch.setenv("ENVXX_GITHUB_API", "https://gh-proxy.example/api.github.com")
    url = "https://api.github.com/repos/a/b/releases/latest"
    assert http.apply_mirror(url) == (
        "https://gh-proxy.example/api.github.com/repos/a/b/releases/latest"
    )


def test_apply_mirror_cc_switch_release_asset(monkeypatch):
    monkeypatch.delenv("ENVXX_CCSWITCH_MIRROR", raising=False)
    url = (
        "https://github.com/farion1231/cc-switch/releases/download/"
        "v4.0.31/CC-Switch-v4.0.31-Windows-Portable.zip"
    )
    assert http.apply_mirror(url) == (
        "https://dl.ccswitch.io/v4.0.31/CC-Switch-v4.0.31-Windows-Portable.zip"
    )


def test_apply_mirror_cc_switch_can_be_disabled(monkeypatch):
    monkeypatch.setenv("ENVXX_CCSWITCH_MIRROR", "")
    url = (
        "https://github.com/farion1231/cc-switch/releases/download/"
        "v4.0.31/CC-Switch-v4.0.31-Windows-Portable.zip"
    )
    assert http.apply_mirror(url) == url


def test_apply_mirror_leaves_other_release_assets_alone():
    url = "https://github.com/sst/opencode/releases/download/v2.3.0/opencode-windows-x64.zip"
    assert http.apply_mirror(url) == url


def test_sha256_file(tmp_path):
    target = tmp_path / "blob.bin"
    target.write_bytes(b"hello")
    assert http.sha256_file(target) == hashlib.sha256(b"hello").hexdigest()


def test_parse_sha256_sum():
    text = (
        "abc123  node-v22.14.0-win-x64.zip\n"
        "def456 *node-v22.14.0-linux-x64.tar.gz\n"
        "deadbeef  other.zip\n"
    )
    assert http.parse_sha256_sum(text, "node-v22.14.0-win-x64.zip") == "abc123"
    assert http.parse_sha256_sum(text, "node-v22.14.0-linux-x64.tar.gz") == "def456"
    assert http.parse_sha256_sum(text, "missing.zip") is None


def _mock_client(monkeypatch, handler):
    real_client = httpx.Client

    def factory():
        return real_client(transport=httpx.MockTransport(handler), follow_redirects=True)

    monkeypatch.setattr(http, "client", factory)


def test_download_verifies_checksum(tmp_path, monkeypatch):
    payload = b"artifact-bytes"
    digest = hashlib.sha256(payload).hexdigest()

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=payload, headers={"content-length": str(len(payload))})

    _mock_client(monkeypatch, handler)

    dest = tmp_path / "out.bin"
    http.download("https://example.test/a", dest, expected=digest, show_progress=False)
    assert dest.read_bytes() == payload
    assert not dest.with_name(dest.name + ".part").exists()


def test_download_rejects_bad_checksum(tmp_path, monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"tampered")

    _mock_client(monkeypatch, handler)

    dest = tmp_path / "out.bin"
    with pytest.raises(ChecksumError):
        http.download("https://example.test/a", dest, expected="00", show_progress=False)
    assert not dest.exists()


def test_download_resumes_partial_file(tmp_path, monkeypatch):
    payload = b"0123456789"
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["range"] = request.headers.get("range")
        start = int(seen["range"].split("=")[1].rstrip("-")) if seen["range"] else 0
        return httpx.Response(
            206 if start else 200,
            content=payload[start:],
            headers={"content-length": str(len(payload) - start)},
        )

    _mock_client(monkeypatch, handler)

    dest = tmp_path / "out.bin"
    dest.with_name(dest.name + ".part").write_bytes(payload[:4])
    http.download("https://example.test/a", dest, show_progress=False)
    assert seen["range"] == "bytes=4-"
    assert dest.read_bytes() == payload
    assert not dest.with_name(dest.name + ".part").exists()


def test_download_restarts_when_server_ignores_range(tmp_path, monkeypatch):
    payload = b"0123456789"

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=payload)

    _mock_client(monkeypatch, handler)

    dest = tmp_path / "out.bin"
    dest.with_name(dest.name + ".part").write_bytes(b"stale")
    http.download("https://example.test/a", dest, show_progress=False)
    assert dest.read_bytes() == payload


def test_download_resume_disabled_drops_part(tmp_path, monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        assert "range" not in request.headers
        return httpx.Response(200, content=b"fresh")

    _mock_client(monkeypatch, handler)

    dest = tmp_path / "out.bin"
    dest.with_name(dest.name + ".part").write_bytes(b"stale")
    http.download("https://example.test/a", dest, show_progress=False, resume=False)
    assert dest.read_bytes() == b"fresh"


def test_download_falls_back_when_mirror_lacks_the_file(tmp_path, monkeypatch):
    payload = b"from-github"
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        if "dl.ccswitch.io" in str(request.url):
            return httpx.Response(404)
        return httpx.Response(200, content=payload)

    _mock_client(monkeypatch, handler)
    monkeypatch.delenv("ENVXX_CCSWITCH_MIRROR", raising=False)

    url = (
        "https://github.com/farion1231/cc-switch/releases/download/"
        "v4.0.31/CC-Switch-v4.0.31-Windows-Portable.zip"
    )
    dest = tmp_path / "cc.zip"
    http.download(url, dest, show_progress=False)
    assert dest.read_bytes() == payload
    assert seen[0].startswith("https://dl.ccswitch.io/v4.0.31/")
    assert seen[-1].startswith("https://github.com/")


class _DroppingBody(httpx.SyncByteStream):
    """Hand over one chunk, then lose the peer mid-transfer."""

    def __init__(self, first: bytes) -> None:
        self.first = first

    def __iter__(self):
        yield self.first
        raise httpx.ReadError("connection dropped")


def test_download_resumes_after_midstream_drop(tmp_path, monkeypatch):
    payload = b"0123456789"
    ranges: list[str | None] = []
    encodings: list[str | None] = []

    def handler(request: httpx.Request) -> httpx.Response:
        ranges.append(request.headers.get("range"))
        encodings.append(request.headers.get("accept-encoding"))
        start = int(ranges[-1].split("=")[1].rstrip("-")) if ranges[-1] else 0
        if start:
            return httpx.Response(
                206,
                content=payload[start:],
                headers={"content-length": str(len(payload) - start)},
            )
        return httpx.Response(
            200,
            stream=_DroppingBody(payload[:4]),
            headers={"content-length": str(len(payload))},
        )

    monkeypatch.setattr(http.time, "sleep", lambda _seconds: None)
    # small chunks so the first body's bytes reach the file before it drops:
    # iter_bytes buffers anything shorter than one chunk
    monkeypatch.setattr(http, "_CHUNK", 4)
    _mock_client(monkeypatch, handler)

    dest = tmp_path / "out.bin"
    http.download(
        "https://example.test/a",
        dest,
        expected=hashlib.sha256(payload).hexdigest(),
        show_progress=False,
    )
    assert ranges == [None, "bytes=4-"]
    assert encodings == ["identity", "identity"]
    assert dest.read_bytes() == payload
    assert not dest.with_name(dest.name + ".part").exists()


def test_download_detects_body_shorter_than_content_length(tmp_path, monkeypatch):
    payload = b"0123456789"
    ranges: list[str | None] = []

    def handler(request: httpx.Request) -> httpx.Response:
        ranges.append(request.headers.get("range"))
        if ranges[-1]:
            start = int(ranges[-1].split("=")[1].rstrip("-"))
            return httpx.Response(
                206,
                content=payload[start:],
                headers={"content-length": str(len(payload) - start)},
            )
        # the peer closed cleanly after 4 of the 10 promised bytes
        return httpx.Response(
            200, content=payload[:4], headers={"content-length": str(len(payload))}
        )

    monkeypatch.setattr(http.time, "sleep", lambda _seconds: None)
    _mock_client(monkeypatch, handler)

    dest = tmp_path / "out.bin"
    http.download("https://example.test/a", dest, show_progress=False)
    assert ranges == [None, "bytes=4-"]
    assert dest.read_bytes() == payload


def test_download_keeps_partial_file_when_retries_run_out(tmp_path, monkeypatch):
    from envxx.errors import NetworkError

    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(
            200,
            stream=_DroppingBody(b"1234"),
            headers={"content-length": "10"},
        )

    monkeypatch.setattr(http.time, "sleep", lambda _seconds: None)
    monkeypatch.setattr(http, "_CHUNK", 4)
    _mock_client(monkeypatch, handler)

    dest = tmp_path / "out.bin"
    with pytest.raises(NetworkError):
        http.download("https://example.test/a", dest, show_progress=False)
    assert calls["n"] == http._RETRIES
    assert not dest.exists()
    # the next run picks up from here instead of starting over
    assert dest.with_name(dest.name + ".part").read_bytes() == b"1234"


def test_download_falls_back_when_mirror_is_unreachable(tmp_path, monkeypatch):
    payload = b"from-github"
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        if "dl.ccswitch.io" in str(request.url):
            raise httpx.ConnectError("mirror down")
        return httpx.Response(200, content=payload)

    monkeypatch.setattr(http.time, "sleep", lambda _seconds: None)
    monkeypatch.delenv("ENVXX_CCSWITCH_MIRROR", raising=False)
    _mock_client(monkeypatch, handler)

    url = (
        "https://github.com/farion1231/cc-switch/releases/download/"
        "v4.0.31/CC-Switch-v4.0.31-Windows-Portable.zip"
    )
    dest = tmp_path / "cc.zip"
    http.download(url, dest, show_progress=False)
    assert dest.read_bytes() == payload
    assert seen[0].startswith("https://dl.ccswitch.io/")
    assert seen[-1].startswith("https://github.com/")
    assert sum("dl.ccswitch.io" in seen_url for seen_url in seen) == http._RETRIES


def test_get_json_missing_ok_returns_none(tmp_path, monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"message": "Not Found"})

    _mock_client(monkeypatch, handler)
    assert http.get_json("https://example.test/x", "missing", ttl=0, missing_ok=True) is None


def test_get_json_404_still_raises_by_default(tmp_path, monkeypatch):
    from envxx.errors import NetworkError

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"message": "Not Found"})

    _mock_client(monkeypatch, handler)
    with pytest.raises(NetworkError):
        http.get_json("https://example.test/x", "missing2", ttl=0)


def test_rate_limit_error_mentions_reset_and_token(tmp_path, monkeypatch):
    import time

    from envxx.errors import NetworkError

    reset = int(time.time()) + 600

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            403,
            json={"message": "API rate limit exceeded"},
            headers={"x-ratelimit-reset": str(reset)},
        )

    _mock_client(monkeypatch, handler)
    with pytest.raises(NetworkError) as exc:
        http.get_json("https://api.github.com/x", "rl", ttl=0)
    message = str(exc.value)
    assert "rate limit" in message
    assert "GITHUB_TOKEN" in message
    assert "min" in message


def test_get_json_uses_cache(tmp_path, monkeypatch):
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(200, json={"tag_name": "20261110"})

    _mock_client(monkeypatch, handler)
    first = http.get_json("https://example.test/index.json", "test-index")
    second = http.get_json("https://example.test/index.json", "test-index")
    assert first == second == {"tag_name": "20261110"}
    assert calls["n"] == 1

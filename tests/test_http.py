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

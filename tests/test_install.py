from __future__ import annotations

from pathlib import Path

import pytest

from envxx import store
from envxx.install import _cache_name


def test_versioned_asset_names_are_kept_verbatim():
    # python, node and claude all embed the version already
    assert _cache_name("22.14.0", "node-v22.14.0-win-x64.zip") == (
        "node-v22.14.0-win-x64.zip"
    )
    assert _cache_name("3.11.18", "cpython-3.11.18+x86_64-pc-windows-msvc-install_only.tar.gz") == (
        "cpython-3.11.18+x86_64-pc-windows-msvc-install_only.tar.gz"
    )


def test_constant_asset_names_are_qualified_per_version():
    # opencode ships the same filename for every release
    first = _cache_name("2.3.0", "opencode-windows-x64.zip")
    second = _cache_name("2.2.6", "opencode-windows-x64.zip")
    assert first != second
    assert first == "2.3.0-opencode-windows-x64.zip"


def test_cached_downloads_do_not_collide(tmp_path, monkeypatch):
    monkeypatch.setenv(store.HOME_ENV, str(tmp_path / "home"))
    store.ensure_dirs()

    a = store.downloads_dir() / _cache_name("2.3.0", "opencode-windows-x64.zip")
    b = store.downloads_dir() / _cache_name("2.2.6", "opencode-windows-x64.zip")
    a.write_bytes(b"new")
    b.write_bytes(b"old")

    assert a.read_bytes() == b"new"
    assert b.read_bytes() == b"old"

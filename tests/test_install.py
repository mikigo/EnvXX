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


# -- incomplete installs -----------------------------------------------------
def _fake_tarball_with(entry: str) -> bytes:
    """A .tar.gz holding one file at the wrapper directory's given path."""
    import io
    import tarfile

    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        payload = b"binary"
        info = tarfile.TarInfo(f"python-3.11.18/{entry}")
        info.size = len(payload)
        tar.addfile(info, io.BytesIO(payload))
    return buf.getvalue()


class _FakePython:
    """A python provider whose download writes a tarball we control."""

    def __init__(self, entry: str = "python.exe"):
        from envxx.platforms import Platform
        from envxx.providers.python_provider import PythonProvider

        self.inner = PythonProvider(Platform("windows", "x64"))
        self.entry = entry
        self.downloads = 0

    def __getattr__(self, name):
        return getattr(self.inner, name)

    def plan(self, version):
        from envxx.providers.spec import Asset, InstallPlan

        return InstallPlan(
            version=version,
            asset=Asset(url="file:///unused", filename="fake.tar.gz", format="tar.gz"),
        )


def _install_with_fake(monkeypatch, provider, version="3.11.18"):
    from envxx import http
    from envxx.install import install

    def fake_download(url, dest, expected=None, show_progress=True, resume=True):
        provider.downloads += 1
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(_fake_tarball_with(provider.entry))
        return dest

    monkeypatch.setattr(http, "download", fake_download)
    return install(provider, version, quiet=True)


def test_install_replaces_a_directory_that_has_no_entrypoint(monkeypatch):
    # an interrupted install leaves the version dir behind with nothing in it;
    # trusting the directory would make the broken state permanent
    provider = _FakePython()
    root = store.version_dir("python", "3.11.18")
    root.mkdir(parents=True)
    assert root.is_dir() and not (root / "python.exe").exists()

    result = _install_with_fake(monkeypatch, provider)

    assert provider.downloads == 1
    assert (result / "python.exe").is_file()


def test_install_skips_a_complete_directory(monkeypatch):
    provider = _FakePython()
    root = store.version_dir("python", "3.11.18")
    root.mkdir(parents=True)
    (root / "python.exe").write_bytes(b"already here")

    result = _install_with_fake(monkeypatch, provider)

    assert provider.downloads == 0          # nothing downloaded
    assert result == root
    assert (result / "python.exe").read_bytes() == b"already here"


def test_install_replaces_a_directory_whose_entrypoint_is_missing(monkeypatch):
    # the directory looks populated but the launcher is gone
    provider = _FakePython()
    root = store.version_dir("python", "3.11.18")
    (root / "Lib").mkdir(parents=True)

    result = _install_with_fake(monkeypatch, provider)

    assert provider.downloads == 1
    assert (result / "python.exe").is_file()


def test_remove_version_clears_read_only_files(tmp_path, monkeypatch):
    # Windows keeps extracted archives' mode bits; rmtree used to swallow the
    # permission error and leave the directory in place
    import os

    monkeypatch.setenv(store.HOME_ENV, str(tmp_path / "home"))
    root = store.version_dir("python", "3.11.18")
    (root / "bin").mkdir(parents=True)
    locked = root / "bin" / "stale.dll"
    locked.write_bytes(b"x")
    os.chmod(locked, 0o444)

    store.remove_version("python", "3.11.18")

    assert not root.exists()

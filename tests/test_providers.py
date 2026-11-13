from __future__ import annotations

from pathlib import Path

import pytest

from envxx import store
from envxx.platforms import Platform
from envxx.providers import provider_for
from envxx.providers.node_provider import NodeProvider
from envxx.providers.python_provider import PythonProvider


@pytest.fixture
def win():
    return Platform("windows", "x64")


@pytest.fixture
def linux():
    return Platform("linux", "x64")


@pytest.fixture(autouse=True)
def isolated_home(tmp_path, monkeypatch):
    monkeypatch.setenv(store.HOME_ENV, str(tmp_path / "home"))
    return tmp_path / "home"


# -- node -------------------------------------------------------------------
_NODE_INDEX = [
    {"version": "v24.22.3", "lts": "Krypton", "date": "2026-11-10",
     "files": ["win-x64-zip", "linux-x64"]},
    {"version": "v25.0.0", "lts": False, "date": "2026-10-01",
     "files": ["win-x64-zip"]},
    {"version": "v23.0.0", "lts": "Jod", "date": "2025-01-01",
     "files": ["linux-x64"]},
    {"version": "v22.14.0", "lts": "Jod", "date": "2025-02-11",
     "files": ["win-x64-zip"]},
]


def _node_provider(plat, monkeypatch):
    monkeypatch.setattr("envxx.http.get_json", lambda *a, **k: _NODE_INDEX)
    return NodeProvider(plat)


def test_node_filters_to_lts_and_platform(win, monkeypatch):
    versions = _node_provider(win, monkeypatch).search()
    # ascending
    assert [v.version for v in versions] == ["22.14.0", "24.22.3"]


def test_node_display_collapses_to_latest_per_major(win, monkeypatch):
    provider = _node_provider(win, monkeypatch)
    shown = [info.version for info in provider.display_versions()]
    assert shown == ["22.14.0", "24.22.3"]
    assert provider.resolve("22.14.0") == "22.14.0"


def test_node_display_one_row_per_major(win, monkeypatch):
    index = [
        {"version": "v24.22.3", "lts": "Krypton", "date": "2026-11-10", "files": ["win-x64-zip"]},
        {"version": "v24.22.2", "lts": "Krypton", "date": "2026-11-01", "files": ["win-x64-zip"]},
        {"version": "v24.21.0", "lts": "Krypton", "date": "2026-09-07", "files": ["win-x64-zip"]},
        {"version": "v22.14.0", "lts": "Jod", "date": "2025-02-11", "files": ["win-x64-zip"]},
        {"version": "v22.13.1", "lts": "Jod", "date": "2025-01-11", "files": ["win-x64-zip"]},
    ]
    monkeypatch.setattr("envxx.http.get_json", lambda *a, **k: index)
    shown = [info.version for info in NodeProvider(win).display_versions()]
    assert shown == ["22.14.0", "24.22.3"]


def test_node_excludes_non_lts(win, monkeypatch):
    versions = [v.version for v in _node_provider(win, monkeypatch).search()]
    assert "25.0.0" not in versions


def test_node_excludes_old_majors(win, monkeypatch):
    index = [
        {"version": "v22.14.0", "lts": "Jod", "date": "2025-02-11", "files": ["win-x64-zip"]},
        {"version": "v20.19.0", "lts": "Iron", "date": "2025-03-24", "files": ["win-x64-zip"]},
        {"version": "v18.20.8", "lts": "Hydrogen", "date": "2025-03-27", "files": ["win-x64-zip"]},
        {"version": "v16.20.2", "lts": "Gallium", "date": "2023-08-08", "files": ["win-x64-zip"]},
    ]
    monkeypatch.setattr("envxx.http.get_json", lambda *a, **k: index)
    versions = [v.version for v in NodeProvider(win).search()]
    assert versions == ["20.19.0", "22.14.0"]


@pytest.mark.parametrize(
    "plat,arch,filename",
    [
        ("windows", "x64", "node-v22.14.0-win-x64.zip"),
        ("windows", "arm64", "node-v22.14.0-win-arm64.zip"),
        ("linux", "x64", "node-v22.14.0-linux-x64.tar.gz"),
        ("macos", "arm64", "node-v22.14.0-darwin-arm64.tar.gz"),
    ],
)
def test_node_plan_asset_names(plat, arch, filename):
    plan = NodeProvider(Platform(plat, arch)).plan("22.14.0")
    assert plan.asset.filename == filename
    assert plan.asset.url.endswith(f"/v22.14.0/{filename}")
    assert plan.asset.sha256_url.endswith("/v22.14.0/SHASUMS256.txt")
    assert plan.asset.sha256_filename == filename


def test_node_entrypoints_per_os(win, linux):
    win_provider = NodeProvider(win)
    assert win_provider.entrypoint_candidates("node") == ["node.exe"]
    assert "npm.cmd" in win_provider.entrypoint_candidates("npm")

    linux_provider = NodeProvider(linux)
    assert linux_provider.entrypoint_candidates("node") == ["bin/node"]
    assert linux_provider.entrypoint_candidates("npm") == ["bin/npm"]


# -- python ------------------------------------------------------------------
def _pbs_payload():
    def asset(name, digest="sha256:abc"):
        return {
            "name": name,
            "size": 100,
            "digest": digest,
            "browser_download_url": f"https://github.com/dl/{name}",
        }

    return {
        "published_at": "2026-11-11T00:00:00Z",
        "assets": [
            asset("cpython-3.11.18+20261110-x86_64-pc-windows-msvc-install_only.tar.gz"),
            asset("cpython-3.11.18+20261110-x86_64-pc-windows-msvc-install_only_stripped.tar.gz"),
            asset("cpython-3.11.18+20261110-x86_64-pc-windows-msvc-freethreaded-install_only.tar.gz"),
            asset("cpython-3.11.18+20261110-aarch64-pc-windows-msvc-install_only.tar.gz"),
            asset("cpython-3.11.18+20261110-x86_64-apple-darwin-install_only.tar.gz"),
            asset("cpython-3.12.16+20261110-x86_64-pc-windows-msvc-install_only.tar.gz"),
            asset("cpython-3.16.0a2+20261110-x86_64-pc-windows-msvc-install_only.tar.gz"),
            asset("cpython-3.11.18+20261110-x86_64-pc-windows-msvc-debug-full.tar.zst"),
            asset("cpython-3.11.18+20261110-x86_64-pc-windows-msvc-install_only.tar.gz.sha256"),
        ],
    }


def _python_provider(plat, monkeypatch):
    provider = PythonProvider(plat)
    monkeypatch.setattr("envxx.http.get_json", lambda *a, **k: _pbs_payload())
    return provider


def test_python_picks_only_matching_triple(win, monkeypatch):
    provider = _python_provider(win, monkeypatch)
    versions = [info.version for info in provider.search()]
    # ascending, oldest line first
    assert versions == ["3.11.18", "3.12.16", "3.16.0a2"]


def test_python_variant_preference(win, monkeypatch):
    provider = _python_provider(win, monkeypatch)
    plan = provider.plan("3.11.18")
    assert plan.asset.filename.endswith(
        "x86_64-pc-windows-msvc-install_only.tar.gz"
    )
    assert plan.asset.format == "tar.gz"
    assert plan.asset.sha256 == "abc"


def test_python_prerelease_not_default(win, monkeypatch):
    provider = _python_provider(win, monkeypatch)
    assert provider.default_version() == "3.12.16"
    assert provider.resolve("3.11") == "3.11.18"
    assert provider.resolve("3.16.0a2") == "3.16.0a2"


def test_python_missing_version(win, monkeypatch):
    from envxx.errors import VersionNotFound

    provider = _python_provider(win, monkeypatch)
    with pytest.raises(VersionNotFound):
        provider.plan("3.13.18")


def test_python_entrypoints(win, linux):
    assert PythonProvider(win).entrypoint_candidates("python") == ["python.exe", "python"]
    assert "Scripts/pip.exe" in PythonProvider(win).entrypoint_candidates("pip")
    assert PythonProvider(linux).entrypoint_candidates("python") == ["bin/python3", "bin/python"]


# -- registry ----------------------------------------------------------------
def test_provider_for_registered_tools():
    plat = Platform("windows", "x64")
    assert isinstance(provider_for("node", plat), NodeProvider)
    assert isinstance(provider_for("python", plat), PythonProvider)

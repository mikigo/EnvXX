from __future__ import annotations

from pathlib import Path

import pytest

from envxx import store
from envxx.errors import UnsupportedPlatform
from envxx.platforms import Platform
from envxx.providers import provider_for
from envxx.providers.cc_switch_provider import CcSwitchProvider
from envxx.providers.claude_provider import ClaudeProvider
from envxx.providers.dbeaver_provider import DbeaverProvider
from envxx.providers.dufs_provider import DufsProvider
from envxx.providers.marktext_provider import MarktextProvider
from envxx.providers.mobaxterm_provider import MobaXtermProvider
from envxx.providers.node_provider import NodeProvider
from envxx.providers.notepad_minus_minus_provider import NotepadMinusMinusProvider
from envxx.providers.opencode_provider import OpencodeProvider
from envxx.providers.python_provider import PythonProvider
from envxx.providers.windows_terminal_provider import WindowsTerminalProvider


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
    # newest first
    assert [v.version for v in versions] == ["24.22.3", "22.14.0"]


def test_node_display_collapses_to_latest_per_major(win, monkeypatch):
    provider = _node_provider(win, monkeypatch)
    shown = [info.version for info in provider.display_versions()]
    assert shown == ["24.22.3", "22.14.0"]
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
    assert shown == ["24.22.3", "22.14.0"]


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
    assert versions == ["22.14.0", "20.19.0"]


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
    # newest first
    assert versions == ["3.16.0a2", "3.12.16", "3.11.18"]


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


# -- claude ------------------------------------------------------------------
_OPEN_VSX_VERSIONS = {
    "2.1.325": "https://open-vsx.org/api/Anthropic/claude-code/win32-x64/2.1.325",
    "2.1.323": "https://open-vsx.org/api/Anthropic/claude-code/win32-x64/2.1.323",
    "2.1.9": "https://open-vsx.org/api/Anthropic/claude-code/win32-x64/2.1.9",
    "2.0.0-beta.3": "https://open-vsx.org/api/Anthropic/claude-code/win32-x64/2.0.0-beta.3",
}


def _open_vsx_payload(plat="win32-x64"):
    return {"offset": 0, "totalSize": len(_OPEN_VSX_VERSIONS), "versions": dict(_OPEN_VSX_VERSIONS)}


def _claude_provider(plat, monkeypatch):
    monkeypatch.setattr("envxx.http.get_json", lambda *a, **k: _open_vsx_payload())
    return ClaudeProvider(plat)


def test_claude_filters_to_releases(win, monkeypatch):
    versions = [info.version for info in _claude_provider(win, monkeypatch).search()]
    assert versions == ["2.1.325", "2.1.323", "2.1.9"]


def test_claude_display_versions_is_newest_first(win, monkeypatch):
    shown = [info.version for info in _claude_provider(win, monkeypatch).display_versions()]
    assert shown == ["2.1.325", "2.1.323", "2.1.9"]


def test_claude_pages_through_the_catalogue(win, monkeypatch):
    seen: list[str] = []

    def fake_json(url, cache_key, ttl=86400):
        seen.append(url)
        offset = int(url.rsplit("offset=", 1)[-1]) if "offset=" in url else 0
        return {
            "offset": offset,
            "totalSize": 3,
            "versions": {f"2.1.{n}": "u" for n in range(offset, min(offset + 2, 3))},
        }

    monkeypatch.setattr("envxx.http.get_json", fake_json)
    versions = [info.version for info in ClaudeProvider(win).search()]
    assert versions == ["2.1.2", "2.1.1", "2.1.0"]
    assert len(seen) == 2


def test_claude_plan_asset(win, monkeypatch):
    meta = {
        "downloads": {
            "win32-x64": "https://open-vsx.org/api/Anthropic/claude-code/win32-x64/"
            "2.1.325/file/Anthropic.claude-code-2.1.325@win32-x64.vsix"
        },
        "downloadSizes": {"win32-x64": 176812625},
    }
    monkeypatch.setattr("envxx.http.get_json", lambda *a, **k: meta)
    plan = ClaudeProvider(win).plan("2.1.325")
    assert plan.asset.filename == "Anthropic.claude-code-2.1.325@win32-x64.vsix"
    assert plan.asset.format == "zip"
    assert plan.asset.size == 176812625
    assert plan.asset.sha256_url.endswith(
        "Anthropic.claude-code-2.1.325@win32-x64.sha256"
    )
    assert plan.strip_top is True


def test_claude_unquotes_encoded_filename(win, monkeypatch):
    meta = {
        "downloads": {
            "win32-x64": "https://open-vsx.org/api/Anthropic/claude-code/win32-x64/"
            "2.1.325/file/Anthropic.claude-code-2.1.325%40win32-x64.vsix"
        }
    }
    monkeypatch.setattr("envxx.http.get_json", lambda *a, **k: meta)
    plan = ClaudeProvider(win).plan("2.1.325")
    assert plan.asset.filename == "Anthropic.claude-code-2.1.325@win32-x64.vsix"
    assert plan.asset.size is None


def test_claude_missing_platform_build(win, monkeypatch):
    from envxx.errors import VersionNotFound

    monkeypatch.setattr(
        "envxx.http.get_json", lambda *a, **k: {"downloads": {"linux-x64": "u"}}
    )
    with pytest.raises(VersionNotFound):
        ClaudeProvider(win).plan("2.1.325")


def test_claude_entrypoints_per_os(win, linux):
    assert ClaudeProvider(win).entrypoint_candidates("claude") == [
        "resources/native-binary/claude.exe"
    ]
    assert ClaudeProvider(linux).entrypoint_candidates("claude") == [
        "resources/native-binary/claude"
    ]


# -- opencode ----------------------------------------------------------------
def _oc_tag(tag):
    return {"name": tag, "commit": {"sha": "x"}}


_OC_TAGS = [
    _oc_tag("v2.3.0"),
    _oc_tag("vscode-v1.0.0"),        # the VSCode wrapper, not the CLI
    _oc_tag("process-daemon-v0.5.2"),  # another product in the same repo
    _oc_tag("v2.2.7"),
    _oc_tag("v2.2.6"),
    _oc_tag("v2.2.5"),
]

_OC_FEED = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry><id>tag:github.com,2008:Repository/900832854/v2.3.0</id></entry>
  <entry><id>tag:github.com,2008:Repository/900832854/process-daemon-v0.5.2</id></entry>
  <entry><id>tag:github.com,2008:Repository/900832854/v2.2.7</id></entry>
  <entry><id>tag:github.com,2008:Repository/900832854/vscode-v1.0.0</id></entry>
  <entry><id>tag:github.com,2008:Repository/900832854/v2.2.6</id></entry>
</feed>
"""


def _oc_release(tag, *, assets=None):
    if assets is None:
        assets = [
            {
                "name": "opencode-windows-x64.zip",
                "size": 124586665,
                "digest": "sha256:2e14eee5",
                "browser_download_url": f"https://github.com/dl/{tag}/opencode-windows-x64.zip",
            }
        ]
    return {"tag_name": tag, "assets": assets}


def _opencode_provider(plat, monkeypatch, release=None):
    def fake_json(url, cache_key, ttl=86400, missing_ok=False):
        if "/releases/" in url:
            return release if release is not None else _oc_release("v2.3.0")
        return _OC_TAGS if "page=1" in url else []

    monkeypatch.setattr("envxx.http.get_json", fake_json)
    monkeypatch.setattr(
        "envxx.http.get_text", lambda url, cache_key=None, ttl=86400: _OC_FEED
    )
    return OpencodeProvider(plat)


def test_opencode_default_listing_uses_the_feed(win, monkeypatch):
    provider = _opencode_provider(win, monkeypatch)
    versions = [i.version for i in provider.search()]
    # feed order is newest first, non-CLI tags dropped
    assert versions == ["2.3.0", "2.2.7", "2.2.6"]


def test_opencode_default_listing_never_touches_the_api(win, monkeypatch):
    calls: list[str] = []

    def fake_json(url, cache_key, ttl=86400, missing_ok=False):
        calls.append(url)
        return []

    monkeypatch.setattr("envxx.http.get_json", fake_json)
    monkeypatch.setattr(
        "envxx.http.get_text", lambda url, cache_key=None, ttl=86400: _OC_FEED
    )
    OpencodeProvider(win).search()
    assert calls == []


def test_opencode_search_all_walks_tags(win, monkeypatch):
    provider = _opencode_provider(win, monkeypatch)
    versions = [i.version for i in provider.search_all()]
    assert versions == ["2.3.0", "2.2.7", "2.2.6", "2.2.5"]


def test_opencode_display_versions_is_newest_first(win, monkeypatch):
    shown = [i.version for i in _opencode_provider(win, monkeypatch).display_versions()]
    assert shown == ["2.3.0", "2.2.7", "2.2.6"]


def test_opencode_plan_fetches_release_digest(win, monkeypatch):
    urls: list[str] = []

    def fake_json(url, cache_key, ttl=86400, missing_ok=False):
        urls.append(url)
        if "/releases/" in url:
            return _oc_release("v2.3.0")
        return _OC_TAGS

    monkeypatch.setattr("envxx.http.get_json", fake_json)
    plan = OpencodeProvider(win).plan("2.3.0")
    assert any("/releases/tags/v2.3.0" in u for u in urls)
    assert plan.asset.filename == "opencode-windows-x64.zip"
    assert plan.asset.format == "zip"
    assert plan.asset.sha256 == "2e14eee5"
    assert plan.asset.url.endswith("/v2.3.0/opencode-windows-x64.zip")
    # the archive holds the binary at its root
    assert plan.strip_top is False


@pytest.mark.parametrize(
    "plat,arch,filename,fmt",
    [
        ("windows", "x64", "opencode-windows-x64.zip", "zip"),
        ("windows", "arm64", "opencode-windows-arm64.zip", "zip"),
        ("linux", "x64", "opencode-linux-x64.tar.gz", "tar.gz"),
        ("macos", "arm64", "opencode-darwin-arm64.zip", "zip"),
    ],
)
def test_opencode_asset_per_platform(plat, arch, filename, fmt):
    platform = Platform(plat, arch)
    assert platform.opencode_asset == filename
    assert platform.opencode_format == fmt


def test_opencode_unknown_version_is_rejected(win, monkeypatch):
    from envxx.errors import VersionNotFound

    monkeypatch.setattr(
        "envxx.http.get_json",
        lambda url, cache_key, ttl=86400, missing_ok=False: None,
    )
    with pytest.raises(VersionNotFound):
        OpencodeProvider(win).plan("9.9.9")


def test_opencode_plan_does_not_walk_the_catalogue(win, monkeypatch):
    urls: list[str] = []

    def fake_json(url, cache_key, ttl=86400, missing_ok=False):
        urls.append(url)
        return _oc_release("2.3.0")

    monkeypatch.setattr("envxx.http.get_json", fake_json)
    OpencodeProvider(win).plan("2.3.0")
    assert len(urls) == 1
    assert "/releases/tags/v2.3.0" in urls[0]


def test_opencode_missing_platform_build(win, monkeypatch):
    from envxx.errors import VersionNotFound

    provider = _opencode_provider(
        win, monkeypatch, release=_oc_release("v2.3.0", assets=[])
    )
    with pytest.raises(VersionNotFound):
        provider.plan("2.3.0")


def test_opencode_walks_every_page(win, monkeypatch):
    seen: list[int] = []

    def fake_json(url, cache_key, ttl=86400, missing_ok=False):
        page = int(url.rsplit("page=", 1)[-1])
        seen.append(page)
        if page > 2:
            return []
        return [_oc_tag(f"v2.{page}.{n}") for n in range(100)]

    monkeypatch.setattr("envxx.http.get_json", fake_json)
    versions = [i.version for i in OpencodeProvider(win).search_all()]
    assert seen == [1, 2, 3]
    assert len(versions) == 200
    assert versions[0] == "2.2.99"      # newest first
    assert versions[-1] == "2.1.0"


def test_opencode_entrypoint_has_no_wrapper_dir(win, linux):
    assert OpencodeProvider(win).entrypoint_candidates("opencode") == [
        "opencode.exe",
        "opencode",
    ]
    assert OpencodeProvider(linux).entrypoint_candidates("opencode") == ["opencode"]


# -- cc-switch ---------------------------------------------------------------
_CC_TAGS = [
    {"name": "v4.0.33"},
    {"name": "v4.0.32"},
    {"name": "v4.0.31"},
    {"name": "v4.0.30"},
    {"name": "v4.0.29"},
    {"name": "v4.0.28"},
]


def _cc_assets(version="4.0.31"):
    def asset(name, size=20498344, digest="sha256:44d7c00a"):
        return {
            "name": name,
            "size": size,
            "digest": digest,
            "browser_download_url": (
                f"https://github.com/farion1231/cc-switch/releases/download/"
                f"v{version}/{name}"
            ),
        }

    return [
        asset(f"CC-Switch-v{version}-Linux-x86_64.deb", 20617066),
        asset(f"CC-Switch-v{version}-Windows.msi", 20434944),
        asset(f"CC-Switch-v{version}-Windows-Portable.zip"),
        asset(f"CC-Switch-v{version}-Windows-Portable.zip.sig", 444),
    ]


def _cc_provider(plat, monkeypatch, release=None):
    def fake_json(url, cache_key, ttl=86400, missing_ok=False):
        if "/releases/" in url:
            return release if release is not None else {
                "tag_name": "v4.0.31",
                "assets": _cc_assets(),
            }
        return _CC_TAGS if "page=1" in url else []

    monkeypatch.setattr("envxx.http.get_json", fake_json)
    return CcSwitchProvider(plat)


def test_cc_switch_lists_tagged_releases(win, monkeypatch):
    versions = [i.version for i in _cc_provider(win, monkeypatch).search()]
    assert versions == ["4.0.33", "4.0.32", "4.0.31", "4.0.30", "4.0.29", "4.0.28"]


def test_cc_switch_display_versions_is_newest_first(win, monkeypatch):
    shown = [i.version for i in _cc_provider(win, monkeypatch).display_versions()]
    assert shown == ["4.0.33", "4.0.32", "4.0.31", "4.0.30", "4.0.29", "4.0.28"]


def test_cc_switch_picks_portable_not_msi(win, monkeypatch):
    plan = _cc_provider(win, monkeypatch).plan("4.0.31")
    assert plan.asset.filename == "CC-Switch-v4.0.31-Windows-Portable.zip"
    assert plan.asset.format == "zip"
    assert plan.asset.sha256 == "44d7c00a"
    assert plan.asset.size == 20498344
    # the zip holds cc-switch.exe at the root, no wrapper directory
    assert plan.strip_top is False


def test_cc_switch_matches_older_asset_naming(win, monkeypatch):
    # before v3.5.0 the filename carried no version
    release = {
        "tag_name": "v3.4.0",
        "assets": [
            {
                "name": "CC-Switch-Windows-Portable.zip",
                "size": 1,
                "digest": "sha256:aa",
                "browser_download_url": "https://github.com/dl/old.zip",
            },
            {
                "name": "CC-Switch-Windows-Portable.zip.sig",
                "size": 1,
                "digest": "sha256:bb",
                "browser_download_url": "https://github.com/dl/old.zip.sig",
            },
        ],
    }
    plan = _cc_provider(win, monkeypatch, release=release).plan("3.4.0")
    assert plan.asset.filename == "CC-Switch-Windows-Portable.zip"


@pytest.mark.parametrize(
    "plat,arch,suffix,fmt,launcher",
    [
        ("windows", "x64", "-Windows-Portable.zip", "zip", "cc-switch.exe"),
        ("windows", "arm64", "-Windows-arm64-Portable.zip", "zip", "cc-switch.exe"),
        ("linux", "x64", "-Linux-x86_64.AppImage", "exe", "cc-switch.AppImage"),
        ("linux", "arm64", "-Linux-arm64.AppImage", "exe", "cc-switch.AppImage"),
        (
            "macos",
            "arm64",
            "-macOS.tar.gz",
            "tar.gz",
            "CC Switch.app/Contents/MacOS/cc-switch",
        ),
    ],
)
def test_cc_switch_asset_per_platform(plat, arch, suffix, fmt, launcher):
    platform = Platform(plat, arch)
    assert platform.cc_switch_suffix == suffix
    assert platform.cc_switch_format == fmt
    assert platform.cc_switch_launcher == launcher


def test_cc_switch_arm64_is_not_matched_by_x64_assets(monkeypatch):
    from envxx.errors import VersionNotFound

    release = {"tag_name": "v4.0.31", "assets": _cc_assets()}
    provider = _cc_provider(Platform("windows", "arm64"), monkeypatch, release=release)
    with pytest.raises(VersionNotFound):
        provider.plan("4.0.31")


def test_cc_switch_appimage_is_installed_under_a_stable_name():
    platform = Platform("linux", "x64")
    assert platform.cc_switch_single_name == "cc-switch.AppImage"
    assert Platform("windows", "x64").cc_switch_single_name is None


def test_cc_switch_macos_keeps_the_app_bundle(win, monkeypatch):
    release = {
        "tag_name": "v4.0.31",
        "assets": [
            {
                "name": "CC-Switch-v4.0.31-macOS.tar.gz",
                "size": 42624306,
                "digest": "sha256:3d45b9e0",
                "browser_download_url": "https://github.com/dl/mac.tar.gz",
            }
        ],
    }
    provider = _cc_provider(Platform("macos", "arm64"), monkeypatch, release=release)
    plan = provider.plan("4.0.31")
    assert plan.asset.format == "tar.gz"
    # the launcher lives inside 'CC Switch.app/Contents/MacOS'
    assert plan.strip_top is False
    assert provider.entrypoint_candidates("cc-switch") == [
        "CC Switch.app/Contents/MacOS/cc-switch"
    ]


def test_cc_switch_plan_does_not_walk_the_catalogue(win, monkeypatch):
    urls: list[str] = []

    def fake_json(url, cache_key, ttl=86400, missing_ok=False):
        urls.append(url)
        return {"tag_name": "v4.0.31", "assets": _cc_assets()}

    monkeypatch.setattr("envxx.http.get_json", fake_json)
    CcSwitchProvider(win).plan("4.0.31")
    assert len(urls) == 1
    assert "/releases/tags/v4.0.31" in urls[0]


def test_cc_switch_unknown_version_is_rejected(win, monkeypatch):
    from envxx.errors import VersionNotFound

    monkeypatch.setattr(
        "envxx.http.get_json",
        lambda url, cache_key, ttl=86400, missing_ok=False: None,
    )
    with pytest.raises(VersionNotFound):
        CcSwitchProvider(win).plan("9.9.9")


# -- xterm (MobaXterm) -------------------------------------------------------
_XTERM_PAGE = """<html><body>
<p>Download MobaXterm Home Edition (current version):</p>
<a class="btn_bleu" href="https://download.mobatek.net/2662026100713843/MobaXterm_Portable_v26.6.zip">Portable</a>
<a class="btn_vert" href="https://download.mobatek.net/2662026100713843/MobaXterm_Installer_v26.6.zip">Installer</a>
<p>Download previous stable version:&nbsp;<a href="https://download.mobatek.net/2652026082870834/MobaXterm_Portable_v26.5.zip">v26.5</a></p>
<p class="version_titre">Version 26.6 (2026-10-25)</p>
<ul><li>new RDP engine</li></ul>
<p class="version_titre">Version 26.5 (2026-09-11)</p>
<ul><li>better WebAuthn</li></ul>
<p class="version_titre">Version 26.4 (2026-06-11)</p>
<ul><li>older build</li></ul>
</body></html>
"""


def _xterm_provider(plat, monkeypatch, page=_XTERM_PAGE):
    monkeypatch.setattr(
        "envxx.http.get_text", lambda url, cache_key=None, ttl=86400: page
    )
    return MobaXtermProvider(plat)


def test_xterm_lists_changelog_versions_newest_first(win, monkeypatch):
    versions = [i.version for i in _xterm_provider(win, monkeypatch).search()]
    assert versions == ["26.6", "26.5", "26.4"]


def test_xterm_marks_only_downloadable_builds_stable(win, monkeypatch):
    infos = {i.version: i for i in _xterm_provider(win, monkeypatch).search()}
    assert infos["26.6"].channel == "stable"
    assert infos["26.5"].channel == "stable"
    assert infos["26.4"].channel == "archived"


def test_xterm_reports_release_dates(win, monkeypatch):
    infos = {i.version: i for i in _xterm_provider(win, monkeypatch).search()}
    assert infos["26.6"].released == "2026-10-25"


def test_xterm_default_is_the_newest_downloadable(win, monkeypatch):
    # the changelog goes back years; only the two newest have links
    provider = _xterm_provider(win, monkeypatch)
    assert provider.default_version() == "26.6"
    assert provider.resolve("26") == "26.6"
    assert provider.resolve("26.5") == "26.5"


def test_xterm_refuses_versions_without_a_download_link(win, monkeypatch):
    from envxx.errors import VersionNotFound

    provider = _xterm_provider(win, monkeypatch)
    with pytest.raises(VersionNotFound) as exc:
        provider.resolve("26.4")
    assert "26.6" in str(exc.value)


def test_xterm_plan_uses_the_scraped_portable_url(win, monkeypatch):
    plan = _xterm_provider(win, monkeypatch).plan("26.6")
    assert plan.asset.filename == "MobaXterm_Portable_v26.6.zip"
    assert plan.asset.url == (
        "https://download.mobatek.net/2662026100713843/MobaXterm_Portable_v26.6.zip"
    )
    assert plan.asset.format == "zip"
    # the zip holds the .exe and its plugins at the root
    assert plan.strip_top is False


def test_xterm_ignores_the_installer_link(win, monkeypatch):
    provider = _xterm_provider(win, monkeypatch)
    assert "Installer" not in provider.plan("26.6").asset.url


def test_xterm_entrypoint_carries_the_version(win, monkeypatch):
    provider = _xterm_provider(win, monkeypatch)
    assert provider.entrypoint_candidates("xterm", "26.6") == [
        "MobaXterm_Personal_26.6.exe",
        "MobaXterm_Personal_26.6",
    ]


def test_xterm_entrypoint_path_substitutes_the_version(win, monkeypatch, isolated_home):
    from envxx import store

    root = store.version_dir("xterm", "26.6")
    root.mkdir(parents=True)
    (root / "MobaXterm_Personal_26.6.exe").write_bytes(b"bin")

    provider = _xterm_provider(win, monkeypatch)
    assert provider.entrypoint_path("26.6").name == "MobaXterm_Personal_26.6.exe"


def test_xterm_is_windows_only(monkeypatch):
    from envxx.platforms import Platform

    with pytest.raises(UnsupportedPlatform):
        _xterm_provider(Platform("linux", "x64"), monkeypatch)


# -- dufs --------------------------------------------------------------------
_DUFS_TAGS = [
    {"name": "v0.47.0"},
    {"name": "v0.46.0"},
    {"name": "v0.45.0"},
]


def _dufs_release(version="0.47.0", assets=None):
    if assets is None:
        assets = [
            {
                "name": f"dufs-v{version}-{triple}{suffix}",
                "size": 1761134,
                "digest": "sha256:39a000b70de42",
                "browser_download_url": (
                    f"https://github.com/sigoden/dufs/releases/download/"
                    f"v{version}/dufs-v{version}-{triple}{suffix}"
                ),
            }
            for triple, suffix in (
                ("x86_64-pc-windows-msvc", ".zip"),
                ("aarch64-pc-windows-msvc", ".zip"),
                ("x86_64-unknown-linux-musl", ".tar.gz"),
                ("aarch64-unknown-linux-musl", ".tar.gz"),
                ("x86_64-apple-darwin", ".tar.gz"),
                ("aarch64-apple-darwin", ".tar.gz"),
            )
        ]
    return {"tag_name": f"v{version}", "assets": assets}


def _dufs_provider(plat, monkeypatch, release=None):
    def fake_json(url, cache_key, ttl=86400, missing_ok=False):
        if "/releases/" in url:
            return release if release is not None else _dufs_release()
        return _DUFS_TAGS if "page=1" in url else []

    monkeypatch.setattr("envxx.http.get_json", fake_json)
    return DufsProvider(plat)


def test_dufs_lists_tags_newest_first(win, monkeypatch):
    versions = [i.version for i in _dufs_provider(win, monkeypatch).search()]
    assert versions == ["0.47.0", "0.46.0", "0.45.0"]


def test_dufs_display_versions_is_newest_first(win, monkeypatch):
    shown = [i.version for i in _dufs_provider(win, monkeypatch).display_versions()]
    assert shown == ["0.47.0", "0.46.0", "0.45.0"]


@pytest.mark.parametrize(
    "plat,arch,filename,fmt",
    [
        ("windows", "x64", "dufs-v0.47.0-x86_64-pc-windows-msvc.zip", "zip"),
        ("windows", "arm64", "dufs-v0.47.0-aarch64-pc-windows-msvc.zip", "zip"),
        ("linux", "x64", "dufs-v0.47.0-x86_64-unknown-linux-musl.tar.gz", "tar.gz"),
        ("macos", "arm64", "dufs-v0.47.0-aarch64-apple-darwin.tar.gz", "tar.gz"),
    ],
)
def test_dufs_plan_asset_per_platform(plat, arch, filename, fmt, monkeypatch):
    provider = _dufs_provider(Platform(plat, arch), monkeypatch)
    plan = provider.plan("0.47.0")
    assert plan.asset.filename == filename
    assert plan.asset.format == fmt
    assert plan.asset.sha256 == "39a000b70de42"
    # the archive holds dufs[.exe] at the root
    assert plan.strip_top is False


def test_dufs_plan_skips_the_catalogue(win, monkeypatch):
    urls: list[str] = []

    def fake_json(url, cache_key, ttl=86400, missing_ok=False):
        urls.append(url)
        return _dufs_release()

    monkeypatch.setattr("envxx.http.get_json", fake_json)
    DufsProvider(win).plan("0.47.0")
    assert len(urls) == 1
    assert "/releases/tags/v0.47.0" in urls[0]


def test_dufs_prerelease_tags_are_ignored(win, monkeypatch):
    tags = [{"name": "v0.48.0-rc.1"}, {"name": "v0.47.0"}]

    def fake_json(url, cache_key, ttl=86400, missing_ok=False):
        if "/releases/" in url:
            return _dufs_release()
        return tags if "page=1" in url else []

    monkeypatch.setattr("envxx.http.get_json", fake_json)
    versions = [i.version for i in DufsProvider(win).search()]
    assert versions == ["0.47.0"]


def test_dufs_missing_platform_build(win, monkeypatch):
    from envxx.errors import VersionNotFound

    provider = _dufs_provider(
        win, monkeypatch, release=_dufs_release(assets=[])
    )
    with pytest.raises(VersionNotFound):
        provider.plan("0.47.0")


def test_dufs_unknown_version_is_rejected(win, monkeypatch):
    from envxx.errors import VersionNotFound

    monkeypatch.setattr(
        "envxx.http.get_json",
        lambda url, cache_key, ttl=86400, missing_ok=False: None,
    )
    with pytest.raises(VersionNotFound):
        DufsProvider(win).plan("9.9.9")


def test_dufs_entrypoints(win, linux):
    assert DufsProvider(win).entrypoint_candidates("dufs") == ["dufs.exe", "dufs"]
    assert DufsProvider(linux).entrypoint_candidates("dufs") == ["dufs"]


def _dufs_assets_ready(monkeypatch, tmp_path):
    """Pretend the shadcn theme is already unpacked."""
    from envxx import store

    target = store.assets_dir("dufs")
    target.mkdir(parents=True)
    (target / "index.html").write_text("<html></html>", encoding="utf-8")
    return target


def test_dufs_run_injects_the_assets_flag(win, monkeypatch):
    _dufs_assets_ready(monkeypatch, None)
    provider = DufsProvider(win)
    args = provider.augment_args("0.47.0", [".", "--port", "5000"])
    assert args[0] == "--assets"
    assert args[1].endswith(".assets")
    assert args[2:] == [".", "--port", "5000"]


def test_dufs_run_respects_an_explicit_assets_flag(win, monkeypatch):
    _dufs_assets_ready(monkeypatch, None)
    provider = DufsProvider(win)
    assert provider.augment_args("0.47.0", ["--assets", "mine", "."]) == [
        "--assets",
        "mine",
        ".",
    ]


def test_dufs_run_respects_the_equals_form(win, monkeypatch):
    _dufs_assets_ready(monkeypatch, None)
    provider = DufsProvider(win)
    assert provider.augment_args("0.47.0", ["--assets=mine", "."]) == [
        "--assets=mine",
        ".",
    ]


def test_dufs_run_passes_everything_else_through(win, monkeypatch):
    _dufs_assets_ready(monkeypatch, None)
    provider = DufsProvider(win)
    args = [".", "--port", "8080", "-A", "--render-spa", "--allow-all"]
    assert provider.augment_args("0.47.0", args)[2:] == args


def test_dufs_run_works_without_network(win, monkeypatch):
    """An unreachable assets repo must not break the command."""
    from envxx import http, store

    target = store.assets_dir("dufs")
    assert not (target / "index.html").exists()

    def boom(*args, **kwargs):
        raise AssertionError("network access in a unit test")

    monkeypatch.setattr(http, "get_json", boom)
    monkeypatch.setattr(http, "client", boom)
    assert DufsProvider(win).augment_args("0.47.0", ["."]) == ["."]


def test_dufs_assets_are_downloaded_once(win, monkeypatch, tmp_path):
    from envxx import http, store

    calls = {"n": 0}

    def fake_json(url, cache_key, ttl=86400, missing_ok=False):
        calls["n"] += 1
        return {
            "tag_name": "v2.1.1",
            "assets": [
                {
                    "name": "assets.zip",
                    "digest": "sha256:abc",
                    "browser_download_url": "https://github.com/dl/assets.zip",
                }
            ],
        }

    def fake_download(url, dest, expected=None, show_progress=True, resume=True):
        import zipfile

        with zipfile.ZipFile(dest, "w") as zf:
            zf.writestr("index.html", "<html></html>")
        return dest

    monkeypatch.setattr(http, "get_json", fake_json)
    monkeypatch.setattr(http, "download", fake_download)
    # the fake archive never matches the digest above; skip the cache check
    monkeypatch.setattr(http, "sha256_file", lambda path: "abc")

    first = DufsProvider(win).augment_args("0.47.0", ["."])
    assert first[:2] == ["--assets", str(store.assets_dir("dufs"))]
    assert (store.assets_dir("dufs") / "index.html").is_file()

    # second run sees index.html and asks the API nothing
    before = calls["n"]
    DufsProvider(win).augment_args("0.47.0", ["."])
    assert calls["n"] == before


# -- registry ----------------------------------------------------------------
def test_provider_for_registered_tools():
    plat = Platform("windows", "x64")
    assert isinstance(provider_for("node", plat), NodeProvider)
    assert isinstance(provider_for("python", plat), PythonProvider)
    assert isinstance(provider_for("claude", plat), ClaudeProvider)
    assert isinstance(provider_for("opencode", plat), OpencodeProvider)
    assert isinstance(provider_for("cc-switch", plat), CcSwitchProvider)
    assert isinstance(provider_for("xterm", plat), MobaXtermProvider)
    assert isinstance(provider_for("dufs", plat), DufsProvider)


# -- windows terminal --------------------------------------------------------
_WT_RELEASES = [
    {
        "tag_name": "v1.26.3133.0",
        "prerelease": True,
        "draft": False,
        "assets": [
            {"name": "Microsoft.WindowsTerminalPreview_1.26.3133.0_x64.zip"},
            {"name": "Microsoft.WindowsTerminalPreview_1.26.3133.0_8wekyb3d8bbwe.msixbundle"},
        ],
    },
    {
        "tag_name": "v1.25.3131.0",
        "prerelease": False,
        "draft": False,
        "published_at": "2026-11-01T00:00:00Z",
        "assets": [
            {"name": "Microsoft.WindowsTerminal_1.25.3131.0_x64.zip"},
            {"name": "Microsoft.WindowsTerminal_1.25.3131.0_arm64.zip"},
            {"name": "Microsoft.WindowsTerminal_1.25.3131.0_x86.zip"},
        ],
    },
    {
        "tag_name": "v1.25.2733.0",
        "prerelease": False,
        "draft": False,
        "assets": [{"name": "Microsoft.WindowsTerminal_1.25.2733.0_x64.zip"}],
    },
    {
        "tag_name": "v1.24.12741.0",
        "prerelease": False,
        "draft": False,
        "assets": [{"name": "Microsoft.WindowsTerminal_1.24.12741.0_x64.zip"}],
    },
]


def _wt_provider(plat, monkeypatch, releases=None):
    payload = _WT_RELEASES if releases is None else releases
    monkeypatch.setattr(
        "envxx.http.get_json",
        lambda url, *a, **k: payload if "page=1" in url else [],
    )
    return WindowsTerminalProvider(plat)


def test_wt_hides_preview_releases(win, monkeypatch):
    provider = _wt_provider(win, monkeypatch)
    # search() lists every stable build, newest first
    versions = [i.version for i in provider.search()]
    assert versions == ["1.25.3131.0", "1.25.2733.0", "1.24.12741.0"]
    # the preview tag must not appear at all
    assert "1.26.3133.0" not in versions


def test_wt_filters_a_preview_that_forgot_its_flag(win, monkeypatch):
    # a preview release whose asset names carry Preview but whose flag is off
    sneaky = {
        "tag_name": "v1.26.9999.0",
        "prerelease": False,
        "draft": False,
        "assets": [{"name": "Microsoft.WindowsTerminalPreview_1.26.9999.0_x64.zip"}],
    }
    provider = _wt_provider(win, monkeypatch, [sneaky, *_WT_RELEASES[1:]])
    versions = [i.version for i in provider.search()]
    assert "1.26.9999.0" not in versions


def test_wt_skips_drafts(win, monkeypatch):
    draft = {
        "tag_name": "v1.99.1.0",
        "prerelease": False,
        "draft": True,
        "assets": [{"name": "Microsoft.WindowsTerminal_1.99.1.0_x64.zip"}],
    }
    provider = _wt_provider(win, monkeypatch, [draft, *_WT_RELEASES[1:]])
    assert "1.99.1.0" not in [i.version for i in provider.search()]


def test_wt_requires_a_stable_asset_for_this_arch(win, monkeypatch):
    # arm-only release must not show up on an x64 machine
    arm_only = {
        "tag_name": "v1.27.1.0",
        "prerelease": False,
        "draft": False,
        "assets": [{"name": "Microsoft.WindowsTerminal_1.27.1.0_arm64.zip"}],
    }
    provider = _wt_provider(win, monkeypatch, [arm_only, *_WT_RELEASES[1:]])
    assert "1.27.1.0" not in [i.version for i in provider.search()]


def test_wt_display_keeps_one_row_per_minor_line(win, monkeypatch):
    shown = [i.version for i in _wt_provider(win, monkeypatch).display_versions()]
    assert shown == ["1.25.3131.0", "1.24.12741.0"]


@pytest.mark.parametrize(
    "arch,filename",
    [
        ("x64", "Microsoft.WindowsTerminal_1.25.3131.0_x64.zip"),
        ("arm64", "Microsoft.WindowsTerminal_1.25.3131.0_arm64.zip"),
    ],
)
def test_wt_plan_asset_names(arch, filename):
    plan = WindowsTerminalProvider(Platform("windows", arch)).plan("1.25.3131.0")
    assert plan.asset.filename == filename
    assert plan.asset.url.endswith(f"/v1.25.3131.0/{filename}")
    assert plan.asset.format == "zip"


def test_wt_strips_the_terminal_version_directory(win, monkeypatch):
    # the archive unpacks to terminal-<version>/, so the wrapper is stripped
    provider = _wt_provider(win, monkeypatch)
    assert provider.plan("1.25.3131.0").strip_top is True


def test_wt_entrypoints(win):
    provider = WindowsTerminalProvider(win)
    assert provider.entrypoint_candidates("wt") == ["wt.exe", "wt"]
    assert provider.entrypoint_candidates("WindowsTerminal") == [
        "WindowsTerminal.exe",
        "WindowsTerminal",
    ]


@pytest.mark.parametrize("plat", ["linux", "macos"])
def test_wt_is_windows_only(plat, monkeypatch):
    with pytest.raises(UnsupportedPlatform):
        _wt_provider(Platform(plat, "x64"), monkeypatch)


def test_wt_is_registered():
    from envxx.providers import provider_for, tool_specs

    assert "wt" in [spec.name for spec in tool_specs()]
    assert isinstance(
        provider_for("wt", Platform("windows", "x64")), WindowsTerminalProvider
    )


# -- notepad-- ---------------------------------------------------------------
_NP_RELEASES = [
    {
        "tag_name": "notepad-v3.9.2",
        "prerelease": False,
        "draft": False,
        "published_at": "2026-11-01T00:00:00Z",
        "assets": [
            {"name": "Notepad--v3.9.2-win10-portable.zip"},
            {"name": "Notepad--v3.9.2-mac_arm64_12.3.dmg"},
            {"name": "Notepad--v3.9.2-plugin-Installer.exe"},
        ],
    },
    {
        "tag_name": "notepad-v3.9.1",
        "prerelease": False,
        "draft": False,
        "assets": [
            {"name": "Notepad--v3.9.1-win10-portable.zip"},
            {"name": "Notepad--v3.9.1-windows-arm64-portable.zip"},
        ],
    },
    {
        "tag_name": "notepad-v3.9.0",
        "prerelease": False,
        "draft": False,
        "assets": [{"name": "Notepad--v3.9.0-win10-portable.zip"}],
    },
]


def _np_provider(plat, monkeypatch, releases=None):
    payload = _NP_RELEASES if releases is None else releases
    monkeypatch.setattr(
        "envxx.http.get_json",
        lambda url, *a, **k: payload if "page=1" in url else [],
    )
    return NotepadMinusMinusProvider(plat)


def test_notepad_lists_versions_with_a_portable_zip(win, monkeypatch):
    versions = [i.version for i in _np_provider(win, monkeypatch).search()]
    assert versions == ["3.9.2", "3.9.1", "3.9.0"]


def test_notepad_arm64_only_offers_releases_that_have_an_arm64_zip(
    monkeypatch,
):
    # 3.9.2 and 3.9.0 have no arm64 asset, so offering them would 404
    provider = _np_provider(Platform("windows", "arm64"), monkeypatch)
    assert [i.version for i in provider.search()] == ["3.9.1"]


def test_notepad_skips_a_release_without_the_zip(win, monkeypatch):
    dmg_only = {
        "tag_name": "notepad-v3.8.0",
        "prerelease": False,
        "draft": False,
        "assets": [{"name": "Notepad--v3.8.0-mac_arm64_12.3.dmg"}],
    }
    provider = _np_provider(win, monkeypatch, [dmg_only, *_NP_RELEASES])
    assert "3.8.0" not in [i.version for i in provider.search()]


def test_notepad_skips_prereleases_and_drafts(win, monkeypatch):
    for flag in ("prerelease", "draft"):
        release = {
            "tag_name": "notepad-v9.9.9",
            "prerelease": False,
            "draft": False,
            "assets": [{"name": "Notepad--v9.9.9-win10-portable.zip"}],
        }
        release[flag] = True
        provider = _np_provider(win, monkeypatch, [release, *_NP_RELEASES])
        assert "9.9.9" not in [i.version for i in provider.search()]


@pytest.mark.parametrize(
    "arch,filename",
    [
        ("x64", "Notepad--v3.9.2-win10-portable.zip"),
        ("arm64", "Notepad--v3.9.1-windows-arm64-portable.zip"),
    ],
)
def test_notepad_plan_asset_names(arch, filename):
    version = "3.9.2" if arch == "x64" else "3.9.1"
    plan = NotepadMinusMinusProvider(Platform("windows", arch)).plan(version)
    assert plan.asset.filename == filename
    assert plan.asset.url.endswith(f"/notepad-v{version}/{filename}")
    assert plan.asset.format == "zip"


def test_notepad_strips_the_portable_version_directory(win, monkeypatch):
    # the zip unpacks to Notepad--v<version>-win10-portable/
    provider = _np_provider(win, monkeypatch)
    assert provider.plan("3.9.2").strip_top is True


def test_notepad_entrypoint_keeps_the_double_dash(win, monkeypatch):
    provider = _np_provider(win, monkeypatch)
    assert provider.entrypoint_candidates("notepad--") == [
        "Notepad--.exe",
        "Notepad--",
    ]


@pytest.mark.parametrize("plat", ["linux", "macos"])
def test_notepad_is_windows_only(plat, monkeypatch):
    with pytest.raises(UnsupportedPlatform):
        _np_provider(Platform(plat, "x64"), monkeypatch)


def test_notepad_is_registered():
    from envxx.providers import provider_for, tool_specs

    assert "notepad--" in [spec.name for spec in tool_specs()]
    assert isinstance(
        provider_for("notepad--", Platform("windows", "x64")),
        NotepadMinusMinusProvider,
    )


# -- marktext ----------------------------------------------------------------
_MT_RELEASES = [
    {
        "tag_name": "v0.24.0-rc.2",
        "prerelease": True,
        "draft": False,
        "assets": [{"name": "marktext-win-x64-0.24.0-rc.2.zip"}],
    },
    {
        "tag_name": "v0.23.0",
        "prerelease": False,
        "draft": False,
        "published_at": "2026-01-01T00:00:00Z",
        "assets": [
            {"name": "marktext-win-x64-0.23.0.zip"},
            {"name": "marktext-win-arm64-0.23.0.zip"},
            {"name": "marktext-mac-x64-0.23.0.zip"},
            {"name": "marktext-mac-arm64-0.23.0.zip"},
            {"name": "marktext-linux-0.23.0.tar.gz"},
        ],
    },
    {
        "tag_name": "v0.22.0",
        "prerelease": False,
        "draft": False,
        "assets": [{"name": "marktext-win-x64-0.22.0.zip"}],
    },
]


def _mt_provider(plat, monkeypatch, releases=None):
    payload = _MT_RELEASES if releases is None else releases
    monkeypatch.setattr(
        "envxx.http.get_json",
        lambda url, *a, **k: payload if "page=1" in url else [],
    )
    return MarktextProvider(plat)


def test_marktext_hides_release_candidates(win, monkeypatch):
    versions = [i.version for i in _mt_provider(win, monkeypatch).search()]
    assert versions == ["0.23.0", "0.22.0"]
    assert "0.24.0" not in versions


def test_marktext_filters_by_asset_not_just_tag(win, monkeypatch):
    # an arm64-only release must not be offered to an x64 machine
    arm_only = {
        "tag_name": "v0.25.0",
        "prerelease": False,
        "draft": False,
        "assets": [{"name": "marktext-win-arm64-0.25.0.zip"}],
    }
    provider = _mt_provider(win, monkeypatch, [arm_only, *_MT_RELEASES[1:]])
    assert "0.25.0" not in [i.version for i in provider.search()]


@pytest.mark.parametrize(
    "plat,arch,filename,strip",
    [
        ("windows", "x64", "marktext-win-x64-0.23.0.zip", False),
        ("windows", "arm64", "marktext-win-arm64-0.23.0.zip", False),
        ("macos", "arm64", "marktext-mac-arm64-0.23.0.zip", False),
        ("linux", "x64", "marktext-linux-0.23.0.tar.gz", False),
    ],
)
def test_marktext_plan_asset_names(plat, arch, filename, strip):
    plan = MarktextProvider(Platform(plat, arch)).plan("0.23.0")
    assert plan.asset.filename == filename
    assert plan.asset.url.endswith(f"/v0.23.0/{filename}")
    # electron-builder archives are flat, so nothing is stripped
    assert plan.strip_top is strip


def test_marktext_uses_the_published_checksum_list(win):
    plan = MarktextProvider(win).plan("0.23.0")
    assert plan.asset.sha256_url.endswith("/v0.23.0/SHA256SUMS.txt")
    assert plan.asset.sha256_filename == plan.asset.filename


def test_marktext_entrypoints(win, linux):
    assert MarktextProvider(win).entrypoint_candidates("marktext") == [
        "marktext.exe",
        "marktext",
    ]
    assert MarktextProvider(linux).entrypoint_candidates("marktext") == ["marktext"]


def test_marktext_is_registered():
    from envxx.providers import provider_for, tool_specs

    assert "marktext" in [spec.name for spec in tool_specs()]
    assert isinstance(
        provider_for("marktext", Platform("windows", "x64")), MarktextProvider
    )


# -- dbeaver -----------------------------------------------------------------
_DB_RELEASES = [
    {
        "tag_name": "26.2.5",
        "prerelease": False,
        "draft": False,
        "published_at": "2026-11-01T00:00:00Z",
        "assets": [
            {"name": "dbeaver-ce-26.2.5-windows-x86_64.zip"},
            {"name": "dbeaver-ce-26.2.5-windows-aarch64.zip"},
            {"name": "dbeaver-ce-26.2.5-linux-x86_64.tar.gz"},
            {"name": "dbeaver-ce-26.2.5-macos-x86_64.dmg"},
        ],
    },
    {
        "tag_name": "26.2.4",
        "prerelease": False,
        "draft": False,
        "assets": [
            {"name": "dbeaver-ce-26.2.4-windows-x86_64.zip"},
            {"name": "dbeaver-ce-26.2.4-linux-x86_64.tar.gz"},
        ],
    },
]


def _db_provider(plat, monkeypatch, releases=None):
    payload = _DB_RELEASES if releases is None else releases
    monkeypatch.setattr(
        "envxx.http.get_json",
        lambda url, *a, **k: payload if "page=1" in url else [],
    )
    return DbeaverProvider(plat)


def test_dbeaver_lists_versions_newest_first(win, monkeypatch):
    versions = [i.version for i in _db_provider(win, monkeypatch).search()]
    assert versions == ["26.2.5", "26.2.4"]


def test_dbeaver_reports_when_no_release_fits_the_platform(monkeypatch):
    from envxx.errors import NetworkError

    releases = [
        {
            "tag_name": "26.2.5",
            "prerelease": False,
            "draft": False,
            "assets": [{"name": "dbeaver-ce-26.2.5-windows-x86_64.zip"}],
        }
    ]
    provider = _db_provider(Platform("linux", "x64"), monkeypatch, releases)
    # a linux machine sees no archive at all rather than an x64 windows one
    with pytest.raises(NetworkError):
        provider.search()


@pytest.mark.parametrize(
    "plat,arch,filename,fmt",
    [
        ("windows", "x64", "dbeaver-ce-26.2.5-windows-x86_64.zip", "zip"),
        ("windows", "arm64", "dbeaver-ce-26.2.5-windows-aarch64.zip", "zip"),
        ("linux", "x64", "dbeaver-ce-26.2.5-linux-x86_64.tar.gz", "tar.gz"),
        ("linux", "arm64", "dbeaver-ce-26.2.5-linux-aarch64.tar.gz", "tar.gz"),
    ],
)
def test_dbeaver_plan_asset_names(plat, arch, filename, fmt):
    plan = DbeaverProvider(Platform(plat, arch)).plan("26.2.5")
    assert plan.asset.filename == filename
    assert plan.asset.format == fmt
    assert plan.asset.url.endswith(f"/26.2.5/{filename}")


def test_dbeaver_strips_the_package_directory(win):
    # the archive unpacks to a single dbeaver/ directory
    assert DbeaverProvider(win).plan("26.2.5").strip_top is True


def test_dbeaver_entrypoint(win, linux):
    assert DbeaverProvider(win).entrypoint_candidates("dbeaver") == [
        "dbeaver.exe",
        "dbeaver",
    ]
    assert DbeaverProvider(linux).entrypoint_candidates("dbeaver") == ["dbeaver"]


def test_dbeaver_rejects_macos(monkeypatch):
    # macOS only ships a dmg, which is an install image, not a portable tree
    with pytest.raises(UnsupportedPlatform):
        _db_provider(Platform("macos", "arm64"), monkeypatch)


def test_dbeaver_is_registered():
    from envxx.providers import provider_for, tool_specs

    assert "dbeaver" in [spec.name for spec in tool_specs()]
    assert isinstance(
        provider_for("dbeaver", Platform("windows", "x64")), DbeaverProvider
    )

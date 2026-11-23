"""Tools that ship only an installer: fetched, then offered to the user."""
from __future__ import annotations

import io
import os
import sys
from pathlib import Path

import pytest

from envxx import store
from envxx.errors import NetworkError, UnsupportedPlatform
from envxx.install import install
from envxx.platforms import Platform
from envxx.providers.sevenzip_provider import SevenZipProvider, _build_to_version
from envxx.providers.vscode_provider import VscodeProvider
from envxx.providers.wechat_provider import WechatProvider
from envxx.providers.wecom_provider import WecomProvider


@pytest.fixture
def win():
    return Platform("windows", "x64")


@pytest.fixture
def linux():
    return Platform("linux", "x64")


# -- vscode ------------------------------------------------------------------
_VSCODE_RELEASES = ["1.147.0", "1.146.0", "1.145.3", "not-a-version"]


def _vscode(plat, monkeypatch):
    monkeypatch.setattr("envxx.http.get_json", lambda *a, **k: _VSCODE_RELEASES)
    return VscodeProvider(plat)


def test_vscode_lists_versions_newest_first(win, monkeypatch):
    versions = [i.version for i in _vscode(win, monkeypatch).search()]
    assert versions == ["1.147.0", "1.146.0", "1.145.3"]


def test_vscode_ignores_non_version_entries(win, monkeypatch):
    assert "not-a-version" not in [
        i.version for i in _vscode(win, monkeypatch).search()
    ]


@pytest.mark.parametrize(
    "plat,arch,filename",
    [
        ("windows", "x64", "VSCodeUserSetup-x64-1.147.0.exe"),
        ("windows", "arm64", "VSCodeUserSetup-arm64-1.147.0.exe"),
        ("linux", "x64", "code_1.147.0_amd64.deb"),
        ("macos", "arm64", "VSCode-darwin-arm64.zip"),
    ],
)
def test_vscode_plan_is_download_only(plat, arch, filename):
    plan = VscodeProvider(Platform(plat, arch)).plan("1.147.0")
    assert plan.download_only is True
    assert plan.asset.filename == filename
    assert "1.147.0" in plan.asset.url


def test_vscode_spec_is_marked_as_installer():
    assert VscodeProvider.spec.installer is True
    assert VscodeProvider.spec.entrypoints == ()


# -- 7-zip -------------------------------------------------------------------
_7Z_PAGE = """
<a href="https://github.com/ip7z/7zip/releases/download/26.06/7z2606-x64.exe">x64</a>
<a href="https://github.com/ip7z/7zip/releases/download/26.06/7z2606-arm64.exe">arm64</a>
<a href="https://github.com/ip7z/7zip/releases/download/26.06/7z2606.exe">32-bit</a>
"""


def _sevenzip(plat, monkeypatch, page=_7Z_PAGE):
    monkeypatch.setattr("envxx.http.get_text", lambda *a, **k: page)
    return SevenZipProvider(plat)


@pytest.mark.parametrize(
    "build,expected", [("2606", "26.06"), ("2301", "23.01"), ("99", "99")]
)
def test_7zip_build_number_becomes_a_version(build, expected):
    assert _build_to_version(build) == expected


def test_7zip_reads_the_page(win, monkeypatch):
    assert [i.version for i in _sevenzip(win, monkeypatch).search()] == ["26.06"]


@pytest.mark.parametrize("arch,suffix", [("x64", "-x64"), ("arm64", "-arm64")])
def test_7zip_picks_the_arch_installer(arch, suffix, monkeypatch):
    provider = _sevenzip(Platform("windows", arch), monkeypatch)
    plan = provider.plan("26.06")
    assert plan.asset.filename == f"7z2606{suffix}.exe"
    assert plan.download_only is True


def test_7zip_is_windows_only(linux, monkeypatch):
    with pytest.raises(UnsupportedPlatform):
        _sevenzip(linux, monkeypatch)


# -- wechat ------------------------------------------------------------------
_WECHAT_PAGE = (
    '<a href="https://dldir1v6.qq.com/weixin/Universal/Windows/'
    'WeChatWin_4.2.0.exe">dl</a>'
)


def _wechat(plat, monkeypatch, page=_WECHAT_PAGE):
    monkeypatch.setattr("envxx.http.get_text", lambda *a, **k: page)
    return WechatProvider(plat)


def test_wechat_reads_the_version_from_the_page(win, monkeypatch):
    assert [i.version for i in _wechat(win, monkeypatch).search()] == ["4.2.0"]


def test_wechat_plan_points_at_the_cdn_file(win, monkeypatch):
    plan = _wechat(win, monkeypatch).plan("4.2.0")
    assert plan.asset.filename == "WeChatWin_4.2.0.exe"
    assert plan.asset.url.endswith("/WeChatWin_4.2.0.exe")
    assert plan.download_only is True


def test_wechat_reports_a_changed_page(win, monkeypatch):
    with pytest.raises(NetworkError):
        _wechat(win, monkeypatch, page="<html>nothing here</html>").search()


def test_wechat_is_windows_only(linux, monkeypatch):
    with pytest.raises(UnsupportedPlatform):
        _wechat(linux, monkeypatch)


# -- wecom -------------------------------------------------------------------
_WECOM_TARGET = "https://dldir1.qq.com/wework/work_weixin/WeCom_5.0.13.6005.exe"


def _wecom(plat, monkeypatch, target=_WECOM_TARGET):
    monkeypatch.setattr("envxx.http.redirect_target", lambda url: target)
    return WecomProvider(plat)


def test_wecom_reads_the_version_from_the_redirect(win, monkeypatch):
    assert [i.version for i in _wecom(win, monkeypatch).search()] == ["5.0.13.6005"]


def test_wecom_plan_uses_the_resolved_file(win, monkeypatch):
    plan = _wecom(win, monkeypatch).plan("5.0.13.6005")
    assert plan.asset.filename == "WeCom_5.0.13.6005.exe"
    assert plan.asset.url == _WECOM_TARGET
    assert plan.download_only is True


def test_wecom_rejects_linux(linux, monkeypatch):
    with pytest.raises(UnsupportedPlatform):
        _wecom(linux, monkeypatch)


# -- the download path -------------------------------------------------------
def test_installer_is_downloaded_and_not_unpacked(tmp_path, monkeypatch, win):
    monkeypatch.setenv(store.HOME_ENV, str(tmp_path / "home"))

    def fake_download(url, dest, expected=None, show_progress=True, resume=True):
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(b"MZ fake installer")
        return dest

    monkeypatch.setattr("envxx.http.download", fake_download)
    monkeypatch.setattr("envxx.http.get_text", lambda *a, **k: _WECHAT_PAGE)

    path = install(WechatProvider(win), "4.2.0", quiet=True)

    # the file keeps the publisher's name and sits in downloads/; no tools/
    # directory is created at all
    assert path == store.downloads_dir() / "WeChatWin_4.2.0.exe"
    assert path.read_bytes() == b"MZ fake installer"
    assert not store.tool_dir("wechat").exists()


def test_installer_redownload_is_free(tmp_path, monkeypatch, win):
    monkeypatch.setenv(store.HOME_ENV, str(tmp_path / "home"))
    calls = {"n": 0}

    def fake_download(url, dest, expected=None, show_progress=True, resume=True):
        calls["n"] += 1
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(b"MZ")
        return dest

    monkeypatch.setattr("envxx.http.download", fake_download)
    monkeypatch.setattr("envxx.http.get_text", lambda *a, **k: _WECHAT_PAGE)

    provider = WechatProvider(win)
    install(provider, "4.2.0", quiet=True)
    install(provider, "4.2.0", quiet=True)

    assert calls["n"] == 1


def test_a_part_file_does_not_count_as_downloaded(tmp_path, monkeypatch, win):
    """An interrupted run leaves .part, not the destination name."""
    monkeypatch.setenv(store.HOME_ENV, str(tmp_path / "home"))
    calls = {"n": 0}

    def fake_download(url, dest, expected=None, show_progress=True, resume=True):
        calls["n"] += 1
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(b"complete")
        return dest

    monkeypatch.setattr("envxx.http.download", fake_download)
    monkeypatch.setattr("envxx.http.get_text", lambda *a, **k: _WECHAT_PAGE)

    store.ensure_dirs()
    (store.downloads_dir() / "WeChatWin_4.2.0.exe.part").write_bytes(b"half")

    install(WechatProvider(win), "4.2.0", quiet=True)

    assert calls["n"] == 1
    assert (store.downloads_dir() / "WeChatWin_4.2.0.exe").read_bytes() == b"complete"


def test_installer_specs_are_registered():
    from envxx.providers import tool_specs

    by_name = {spec.name: spec for spec in tool_specs()}
    for name in ("vscode", "7zip", "wechat", "wecom"):
        assert by_name[name].installer is True
        assert by_name[name].entrypoints == ()


# -- launching the installer -------------------------------------------------
@pytest.fixture
def on_windows(monkeypatch):
    """Pin the desktop convention regardless of the host running the tests.

    launch_installer branches on the platform. os.startfile does not exist
    on the Ubuntu runner, so a test that patches it and expects it to be
    called passes on Windows and hits xdg-open on Linux.
    """
    monkeypatch.setattr("envxx.install._host", lambda: "windows")


def test_an_installer_is_opened_for_the_user(tmp_path, monkeypatch, on_windows):
    """Downloading an installer is only useful if it gets offered to run."""
    from envxx.install import launch_installer

    opened = []
    monkeypatch.setattr(sys, "stdin", _TtyStdin())
    monkeypatch.setattr(os, "startfile", opened.append, raising=False)

    assert launch_installer(tmp_path / "a.exe", quiet=False) is True
    assert opened == [tmp_path / "a.exe"]


def test_a_quiet_run_never_opens_anything(tmp_path, monkeypatch, on_windows):
    from envxx.install import launch_installer

    opened = []
    monkeypatch.setattr(os, "startfile", opened.append, raising=False)

    assert launch_installer(tmp_path / "a.exe", quiet=True) is False
    assert opened == []


def test_a_piped_run_never_opens_anything(tmp_path, monkeypatch, on_windows):
    """CI has no desktop; opening a window there would hang or fail."""
    from envxx.install import launch_installer

    opened = []
    monkeypatch.setattr(sys, "stdin", io.StringIO())
    monkeypatch.setattr(os, "startfile", opened.append, raising=False)

    assert launch_installer(tmp_path / "a.exe", quiet=False) is False
    assert opened == []


def test_a_failure_to_open_is_reported_not_raised(
    tmp_path, monkeypatch, capsys, on_windows
):
    from envxx.install import launch_installer

    def boom(path):
        raise OSError("no desktop")

    monkeypatch.setattr(sys, "stdin", _TtyStdin())
    monkeypatch.setattr(os, "startfile", boom, raising=False)

    # the file is already downloaded; failing to open it is not fatal
    assert launch_installer(tmp_path / "a.exe", quiet=False) is False
    assert "could not open" in capsys.readouterr().err + capsys.readouterr().out


@pytest.mark.parametrize(
    "host,expected",
    [
        ("windows", None),
        ("macos", ["open", "VSCodeUserSetup-x64-1.147.0.exe"]),
        ("linux", ["xdg-open", "VSCodeUserSetup-x64-1.147.0.exe"]),
    ],
)
def test_each_platform_uses_its_own_opener(host, expected):
    """The POSIX branches must be reachable on any host, not only on Linux."""
    from envxx.install import _opener_argv

    argv = _opener_argv(host, Path("VSCodeUserSetup-x64-1.147.0.exe"))
    if expected is None:
        assert argv is None, "Windows uses the shell file association"
    else:
        assert argv[0] == expected[0]
        assert argv[1].endswith(expected[1])


def test_the_host_is_one_the_opener_knows():
    """A host _opener_argv does not recognise would fall through to xdg-open,
    which is wrong everywhere except Linux."""
    from envxx.install import _host

    assert _host() in ("windows", "macos", "linux")


class _TtyStdin(io.StringIO):
    def isatty(self):
        return True

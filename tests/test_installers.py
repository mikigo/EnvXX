"""Tools that ship only an installer: fetched, never unpacked or run."""
from __future__ import annotations

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

"""Git for Windows: installers whose version includes the repackaging number."""
from __future__ import annotations

import pytest

from envxx.errors import NetworkError, UnsupportedPlatform
from envxx.platforms import Platform
from envxx.providers.git_provider import GitProvider
from envxx.versions import best_match, version_key


def _release(tag: str, assets: list[str], *, prerelease: bool = False) -> dict:
    return {
        "tag_name": tag,
        "prerelease": prerelease,
        "draft": False,
        "assets": [{"name": name} for name in assets],
    }


_GIT_RELEASES = [
    # the first repackaging drops its number from the file name
    _release("v2.56.1.windows.1", [
        "MinGit-2.56.1-64-bit.zip",
        "MinGit-2.56.1-arm64.zip",
        "MinGit-2.56.1-busybox-64-bit.zip",
        "PortableGit-2.56.1-64-bit.7z.exe",
        "Git-2.56.1-64-bit.exe",
    ]),
    # later repackagings fold the number into the version
    _release("v2.56.0.windows.4", [
        "MinGit-2.56.0.4-64-bit.zip",
        "MinGit-2.56.0.4-arm64.zip",
    ]),
    _release("v2.56.0.windows.1", [
        "MinGit-2.56.0-64-bit.zip",
        "MinGit-2.56.0-arm64.zip",
    ]),
    _release("v2.55.0.windows.2", [
        "MinGit-2.55.0.2-64-bit.zip",
    ]),
    _release("v2.57.0-rc0.windows.1", [
        "MinGit-2.57.0-rc0-64-bit.zip",
    ], prerelease=True),
]


def _git(plat, monkeypatch, releases=None):
    payload = _GIT_RELEASES if releases is None else releases
    monkeypatch.setattr(
        "envxx.http.get_json",
        lambda url, *a, **k: payload if "page=1" in url else [],
    )
    return GitProvider(plat)


@pytest.fixture
def win():
    return Platform("windows", "x64")


# -- version numbering -------------------------------------------------------
def test_the_repackaging_number_is_part_of_the_version():
    # four repackagings of one upstream version must not compare equal
    assert version_key("2.56.0.windows.4") > version_key("2.56.0.windows.1")
    assert version_key("2.56.1.windows.1") > version_key("2.56.0.windows.4")


def test_the_repackaging_suffix_does_not_disturb_other_versions():
    # ordinary dotted versions keep their plain keys
    assert version_key("3.11.9") == (3, 11, 9)
    assert version_key("1.25.3131.0") == (1, 25, 3131, 0)


def test_a_query_matches_every_repackaging_of_that_version():
    candidates = ["2.56.1.windows.1", "2.56.0.windows.4", "2.56.0.windows.1"]
    assert best_match(candidates, "2.56.0") == "2.56.0.windows.4"
    assert best_match(candidates, "2.56") == "2.56.1.windows.1"


# -- asset naming ------------------------------------------------------------
def test_the_first_repackaging_ships_the_bare_version():
    # v2.56.0.windows.1 -> Git-2.56.0-64-bit.exe
    provider = GitProvider(Platform("windows", "x64"))
    assert provider._asset_name("2.56.0.windows.1") == "MinGit-2.56.0-64-bit.zip"


def test_later_repackagings_fold_their_number_in():
    provider = GitProvider(Platform("windows", "x64"))
    assert provider._asset_name("2.56.0.windows.4") == "MinGit-2.56.0.4-64-bit.zip"


def test_arm64_uses_its_own_installer():
    provider = GitProvider(Platform("windows", "arm64"))
    assert provider._asset_name("2.56.1.windows.1") == "MinGit-2.56.1-arm64.zip"


# -- catalogue ---------------------------------------------------------------
def test_git_lists_every_repackaging(win, monkeypatch):
    versions = [i.version for i in _git(win, monkeypatch).search()]
    assert versions == [
        "2.56.1.windows.1",
        "2.56.0.windows.4",
        "2.56.0.windows.1",
        "2.55.0.windows.2",
    ]


def test_git_hides_release_candidates(win, monkeypatch):
    assert "2.57.0-rc0.windows.1" not in [
        i.version for i in _git(win, monkeypatch).search()
    ]


def test_git_display_collapses_repackagings(win, monkeypatch):
    shown = [i.version for i in _git(win, monkeypatch).display_versions()]
    # one row per upstream version, newest first
    assert shown == ["2.56.1.windows.1", "2.56.0.windows.4", "2.55.0.windows.2"]


def test_git_filters_by_asset_for_the_arch(win, monkeypatch):
    # an x64 machine must not be offered a build with only an arm64 installer
    arm_only = _release("v2.58.0.windows.1", ["MinGit-2.58.0-arm64.zip"])
    provider = _git(win, monkeypatch, [arm_only, *_GIT_RELEASES])
    assert "2.58.0.windows.1" not in [i.version for i in provider.search()]


def test_git_plan_points_at_the_mingit_zip(win, monkeypatch):
    plan = _git(win, monkeypatch).plan("2.56.0.windows.4")
    assert plan.asset.filename == "MinGit-2.56.0.4-64-bit.zip"
    assert plan.asset.url.endswith(
        "/v2.56.0.windows.4/MinGit-2.56.0.4-64-bit.zip"
    )
    assert plan.asset.format == "zip"
    # MinGit unpacks flat, so the root stays the root
    assert plan.strip_top is False
    assert plan.download_only is False


def test_git_is_a_portable_zip_not_an_installer():
    # MinGit is a plain zip, so git is unpacked and runnable, not downloaded
    # as an installer for the user to open
    assert GitProvider.spec.installer is False
    assert [e.name for e in GitProvider.spec.entrypoints] == ["git", "scalar"]


def test_git_entrypoint_is_the_cmd_launcher(win):
    provider = GitProvider(win)
    # cmd/git.exe is what Git for Windows puts on PATH
    assert provider.entrypoint_candidates("git") == ["cmd/git.exe", "cmd/git"]


@pytest.mark.parametrize("plat", ["linux", "macos"])
def test_git_is_windows_only(plat, monkeypatch):
    with pytest.raises(UnsupportedPlatform):
        _git(Platform(plat, "x64"), monkeypatch)


def test_git_reports_when_nothing_matches(win, monkeypatch):
    with pytest.raises(NetworkError):
        _git(win, monkeypatch, releases=[]).search()


def test_git_is_registered():
    from envxx.providers import provider_for, tool_specs

    names = [spec.name for spec in tool_specs()]
    assert "git" in names
    assert isinstance(provider_for("git", Platform("windows", "x64")), GitProvider)

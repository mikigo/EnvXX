from __future__ import annotations

import pytest

from envxx.platforms import Platform
from envxx.providers.go_provider import GoProvider
from envxx.providers.jdk_provider import JdkProvider


@pytest.fixture
def win():
    return Platform("windows", "x64")


@pytest.fixture
def linux():
    return Platform("linux", "x64")


# -- go ----------------------------------------------------------------------
_GO_MANIFEST = [
    {
        "version": "go1.27.4",
        "stable": True,
        "files": [
            {"filename": "go1.27.4.windows-amd64.zip", "os": "windows",
             "arch": "amd64", "kind": "archive", "sha256": "a" * 64, "size": 79077744},
            {"filename": "go1.27.4.windows-amd64.msi", "os": "windows",
             "arch": "amd64", "kind": "installer", "sha256": "b" * 64},
            {"filename": "go1.27.4.linux-amd64.tar.gz", "os": "linux",
             "arch": "amd64", "kind": "archive", "sha256": "c" * 64},
            {"filename": "go1.27.4.darwin-arm64.tar.gz", "os": "darwin",
             "arch": "arm64", "kind": "archive", "sha256": "d" * 64},
        ],
    },
    {
        "version": "go1.26.5",
        "stable": True,
        "files": [
            {"filename": "go1.26.5.windows-amd64.zip", "os": "windows",
             "arch": "amd64", "kind": "archive", "sha256": "e" * 64},
        ],
    },
    {
        "version": "go1.28rc1",
        "stable": False,
        "files": [
            {"filename": "go1.28rc1.windows-amd64.zip", "os": "windows",
             "arch": "amd64", "kind": "archive", "sha256": "f" * 64},
        ],
    },
]


def _go(plat, monkeypatch):
    monkeypatch.setattr("envxx.http.get_json", lambda *a, **k: _GO_MANIFEST)
    return GoProvider(plat)


def test_go_versions_are_newest_first_and_hide_the_prefix(win, monkeypatch):
    versions = [info.version for info in _go(win, monkeypatch).search()]
    assert versions == ["1.28rc1", "1.27.4", "1.26.5"]


def test_go_marks_release_candidates_as_prerelease(win, monkeypatch):
    channels = {
        info.version: info.channel for info in _go(win, monkeypatch).search()
    }
    assert channels["1.27.4"] == "stable"
    assert channels["1.28rc1"] == "prerelease"


def test_go_default_version_skips_prereleases(win, monkeypatch):
    assert _go(win, monkeypatch).default_version() == "1.27.4"


def test_go_display_keeps_one_row_per_minor_line(monkeypatch):
    manifest = [
        {
            "version": version,
            "files": [
                {"filename": f"go{version}.windows-amd64.zip", "os": "windows",
                 "arch": "amd64", "kind": "archive", "sha256": "a" * 64},
            ],
        }
        for version in ("go1.27.4", "go1.27.3", "go1.27.1", "go1.26.11", "go1.26.10")
    ]
    monkeypatch.setattr("envxx.http.get_json", lambda *a, **k: manifest)

    provider = GoProvider(Platform("windows", "x64"))
    assert [info.version for info in provider.search()] == [
        "1.27.4", "1.27.3", "1.27.1", "1.26.11", "1.26.10",
    ]
    assert [info.version for info in provider.display_versions()] == [
        "1.27.4", "1.26.11",
    ]


@pytest.mark.parametrize(
    "plat,arch,filename,fmt",
    [
        ("windows", "x64", "go1.27.4.windows-amd64.zip", "zip"),
        ("linux", "x64", "go1.27.4.linux-amd64.tar.gz", "tar.gz"),
        ("macos", "arm64", "go1.27.4.darwin-arm64.tar.gz", "tar.gz"),
    ],
)
def test_go_plan_targets_the_archive_not_the_installer(plat, arch, filename, fmt):
    provider = GoProvider(Platform(plat, arch))
    provider._files = {
        "1.27.4": next(
            f
            for f in _GO_MANIFEST[0]["files"]
            if f["filename"] == filename
        )
    }
    plan = provider.plan("1.27.4")
    assert plan.asset.filename == filename
    assert plan.asset.format == fmt
    assert plan.asset.url == f"https://dl.google.com/go/{filename}"


def test_go_plan_rejects_a_version_with_no_build_for_this_platform(
    monkeypatch,
):
    from envxx.errors import VersionNotFound

    manifest = [
        {
            "version": "go1.27.4",
            # a release that exists, but only for another operating system
            "files": [
                {"filename": "go1.27.4.linux-amd64.tar.gz", "os": "linux",
                 "arch": "amd64", "kind": "archive", "sha256": "c" * 64},
            ],
        }
    ]
    monkeypatch.setattr("envxx.http.get_json", lambda *a, **k: manifest)

    provider = GoProvider(Platform("windows", "x64"))
    assert provider.search() == []
    with pytest.raises(VersionNotFound):
        provider.plan("1.27.4")


def test_go_entrypoints_use_the_bin_directory(win, linux):
    assert GoProvider(win).entrypoint_candidates("go") == ["bin/go.exe", "bin/go"]
    assert GoProvider(linux).entrypoint_candidates("go") == ["bin/go"]
    assert GoProvider(win).entrypoint_candidates("gofmt") == [
        "bin/gofmt.exe",
        "bin/gofmt",
    ]


# -- jdk ---------------------------------------------------------------------
def _jdk_row(version: str, build: int, name: str, arch: str = "x64", os_: str = "windows"):
    return {
        "release_name": f"jdk-{version}+{build}",
        "release_type": "ga",
        "version_data": {
            "openjdk_version": f"{version}+{build}-LTS",
            "semver": f"{version}+{build}.0.LTS",
            "build": build,
        },
        "binaries": [
            {
                "image_type": "jdk",
                "os": os_,
                "architecture": arch,
                "package": {
                    "name": name,
                    "link": f"https://github.com/adoptium/temurin21-binaries/releases/download/x/{name}",
                    "checksum": "e" * 64,
                    "size": 205421281,
                },
            }
        ],
    }


def _jdk(plat, monkeypatch, rows=None):
    if rows is None:
        rows = [_jdk_row("21.0.13", 9, "OpenJDK21U-jdk_x64_windows_hotspot_21.0.13_9.zip")]

    def fake_json(url, cache_key, ttl=86400, missing_ok=False):
        if "available_releases" in url:
            return {"available_lts_releases": [17, 21, 25], "most_recent_feature_release": 27}
        return rows

    monkeypatch.setattr("envxx.http.get_json", fake_json)
    return JdkProvider(plat)


def test_jdk_reports_openjdk_versions_without_the_build_suffix(win, monkeypatch):
    versions = [info.version for info in _jdk(win, monkeypatch).search()]
    assert versions == ["21.0.13"]


def test_jdk_skips_majors_below_the_floor(win, monkeypatch):
    # available_releases lists 8 and 11; a runtime that offers Java 8 is noise
    provider = _jdk(win, monkeypatch)
    assert min(provider._majors()) >= 17


def test_jdk_keeps_the_newest_build_for_one_version(win, monkeypatch):
    rows = [
        _jdk_row("21.0.13", 9, "new.zip"),
        _jdk_row("21.0.13", 8, "old.zip"),
    ]
    provider = _jdk(win, monkeypatch, rows)
    assert provider.plan("21.0.13").asset.filename == "new.zip"


def test_jdk_reads_the_version_from_semver(win, monkeypatch):
    # real payloads disagree: 27.0.1.0.2 reports openjdk_version '27.0.1.0'
    # while another 27 build reports '27+35'. semver is three-part in both.
    row = _jdk_row("27.0.1", 0, "jdk27.zip")
    row["version_data"] = {
        "openjdk_version": "27.0.1.0",
        "semver": "27.0.1+0",
        "build": 0,
    }
    provider = _jdk(win, monkeypatch, [row])
    assert [info.version for info in provider.search()] == ["27.0.1"]


def test_jdk_falls_back_to_openjdk_version_without_semver(win, monkeypatch):
    row = _jdk_row("21.0.13", 9, "jdk21.zip")
    row["version_data"] = {"openjdk_version": "21.0.13+9-LTS", "build": 9}
    provider = _jdk(win, monkeypatch, [row])
    assert [info.version for info in provider.search()] == ["21.0.13"]


def test_jdk_prefers_the_archive_over_the_installer(win, monkeypatch):
    row = _jdk_row("21.0.13", 9, "jdk.zip")
    row["binaries"][0]["installer"] = {
        "name": "jdk.msi",
        "link": "https://example.invalid/jdk.msi",
    }
    provider = _jdk(win, monkeypatch, [row])
    plan = provider.plan("21.0.13")
    assert plan.asset.filename == "jdk.zip"
    assert plan.asset.format == "zip"


def test_jdk_falls_back_to_lts_lines_when_the_probe_fails(win, monkeypatch):
    from envxx.errors import NetworkError

    def fake_json(url, cache_key, ttl=86400, missing_ok=False):
        if "available_releases" in url:
            raise NetworkError("offline")
        return [_jdk_row("21.0.13", 9, "jdk.zip")]

    monkeypatch.setattr("envxx.http.get_json", fake_json)
    provider = JdkProvider(win)
    assert provider._majors() == [21, 25]
    # both lines answer with the same row, and the duplicate collapses
    assert [info.version for info in provider.search()] == ["21.0.13"]


def test_jdk_entrypoints_are_bin_java(win, linux):
    assert JdkProvider(win).entrypoint_candidates("java") == ["bin/java.exe", "bin/java"]
    assert JdkProvider(linux).entrypoint_candidates("javac") == ["bin/javac"]


def test_jdk_needs_contents_home_on_macos():
    # the macOS build is a .app-style bundle: jdk-21.0.13+9/Contents/Home/bin/java
    mac = Platform("macos", "arm64")
    assert JdkProvider(mac).entrypoint_candidates("java") == [
        "Contents/Home/bin/java"
    ]



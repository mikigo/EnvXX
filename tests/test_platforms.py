from __future__ import annotations

import pytest

from envxx.errors import UnsupportedPlatform
from envxx.platforms import detect_platform


@pytest.mark.parametrize(
    "system,machine,os_name,arch",
    [
        ("Windows", "AMD64", "windows", "x64"),
        ("Windows", "ARM64", "windows", "arm64"),
        ("Linux", "x86_64", "linux", "x64"),
        ("Linux", "aarch64", "linux", "arm64"),
        ("Darwin", "arm64", "macos", "arm64"),
        ("Darwin", "x86_64", "macos", "x64"),
    ],
)
def test_detect_platform(system, machine, os_name, arch):
    plat = detect_platform(system, machine)
    assert (plat.os, plat.arch) == (os_name, arch)


def test_platform_triples_and_node_keys():
    win = detect_platform("Windows", "AMD64")
    assert win.python_triples == ("x86_64-pc-windows-msvc",)
    assert win.node_files_key == "win-x64-zip"
    assert win.node_asset_os == "win-x64"
    assert win.node_archive_ext == ".zip"
    assert win.exe_suffix == ".exe"

    mac = detect_platform("Darwin", "arm64")
    assert mac.python_triples == ("aarch64-apple-darwin",)
    assert mac.node_files_key == "osx-arm64-tar"
    assert mac.node_asset_os == "darwin-arm64"
    assert mac.exe_suffix == ""


def test_unsupported_platforms():
    with pytest.raises(UnsupportedPlatform):
        detect_platform("FreeBSD", "x86_64")
    with pytest.raises(UnsupportedPlatform):
        detect_platform("Linux", "mips")

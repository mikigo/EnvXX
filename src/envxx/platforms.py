from __future__ import annotations

import platform as _platform
from dataclasses import dataclass

from .errors import UnsupportedPlatform

# host os/arch -> python-build-standalone target triple, in preference order
_PYTHON_TRIPLES: dict[tuple[str, str], tuple[str, ...]] = {
    ("windows", "x64"): ("x86_64-pc-windows-msvc",),
    ("windows", "arm64"): ("aarch64-pc-windows-msvc",),
    ("linux", "x64"): ("x86_64-unknown-linux-gnu",),
    ("linux", "arm64"): ("aarch64-unknown-linux-gnu",),
    ("macos", "x64"): ("x86_64-apple-darwin",),
    ("macos", "arm64"): ("aarch64-apple-darwin",),
}

# host os/arch -> (node dist index "files" key, node asset os token, archive ext)
_NODE_KEYS: dict[tuple[str, str], tuple[str, str, str]] = {
    ("windows", "x64"): ("win-x64-zip", "win-x64", ".zip"),
    ("windows", "arm64"): ("win-arm64-zip", "win-arm64", ".zip"),
    ("linux", "x64"): ("linux-x64", "linux-x64", ".tar.gz"),
    ("linux", "arm64"): ("linux-arm64", "linux-arm64", ".tar.gz"),
    ("macos", "x64"): ("osx-x64-tar", "darwin-x64", ".tar.gz"),
    ("macos", "arm64"): ("osx-arm64-tar", "darwin-arm64", ".tar.gz"),
}


@dataclass(frozen=True)
class Platform:
    os: str  # windows | linux | macos
    arch: str  # x64 | arm64

    @property
    def tag(self) -> str:
        return f"{self.os}-{self.arch}"

    @property
    def exe_suffix(self) -> str:
        return ".exe" if self.os == "windows" else ""

    @property
    def python_triples(self) -> tuple[str, ...]:
        return _PYTHON_TRIPLES[(self.os, self.arch)]

    @property
    def node_files_key(self) -> str:
        return _NODE_KEYS[(self.os, self.arch)][0]

    @property
    def node_asset_os(self) -> str:
        return _NODE_KEYS[(self.os, self.arch)][1]

    @property
    def node_archive_ext(self) -> str:
        return _NODE_KEYS[(self.os, self.arch)][2]


def _normalize_arch(machine: str) -> str:
    normalized = machine.lower()
    if normalized in ("amd64", "x86_64", "x64"):
        return "x64"
    if normalized in ("arm64", "aarch64"):
        return "arm64"
    raise UnsupportedPlatform(f"unsupported CPU architecture: {machine}")


def detect_platform(system: str | None = None, machine: str | None = None) -> Platform:
    system = system if system is not None else _platform.system()
    machine = machine if machine is not None else _platform.machine()
    name = system.lower()
    if name.startswith("win"):
        os_name = "windows"
    elif name == "darwin":
        os_name = "macos"
    elif name == "linux":
        os_name = "linux"
    else:
        raise UnsupportedPlatform(f"unsupported operating system: {system}")

    plat = Platform(os_name, _normalize_arch(machine))
    if (plat.os, plat.arch) not in _PYTHON_TRIPLES:
        raise UnsupportedPlatform(f"unsupported platform: {plat.tag}")
    return plat

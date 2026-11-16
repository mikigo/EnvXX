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

# host os/arch -> Open VSX / marketplace targetPlatform value
_VSIX_PLATFORMS: dict[tuple[str, str], str] = {
    ("windows", "x64"): "win32-x64",
    ("windows", "arm64"): "win32-arm64",
    ("linux", "x64"): "linux-x64",
    ("linux", "arm64"): "linux-arm64",
    ("macos", "x64"): "darwin-x64",
    ("macos", "arm64"): "darwin-arm64",
}

# host os/arch -> (opencode release asset name, archive format)
_OPENCODE_ASSETS: dict[tuple[str, str], tuple[str, str]] = {
    ("windows", "x64"): ("opencode-windows-x64.zip", "zip"),
    ("windows", "arm64"): ("opencode-windows-arm64.zip", "zip"),
    ("linux", "x64"): ("opencode-linux-x64.tar.gz", "tar.gz"),
    ("linux", "arm64"): ("opencode-linux-arm64.tar.gz", "tar.gz"),
    ("macos", "x64"): ("opencode-darwin-x64.zip", "zip"),
    ("macos", "arm64"): ("opencode-darwin-arm64.zip", "zip"),
}

# host os/arch -> release asset suffix (the version sits between the prefix
# 'CC-Switch-v' and this suffix), archive format, launcher path inside the
# install dir, and the fixed name a single-file asset is stored under
_CC_SWITCH_ASSETS: dict[tuple[str, str], tuple[str, str, str, str | None]] = {
    ("windows", "x64"): ("-Windows-Portable.zip", "zip", "cc-switch.exe", None),
    ("windows", "arm64"): (
        "-Windows-arm64-Portable.zip",
        "zip",
        "cc-switch.exe",
        None,
    ),
    ("linux", "x64"): (
        "-Linux-x86_64.AppImage",
        "exe",
        "cc-switch.AppImage",
        "cc-switch.AppImage",
    ),
    ("linux", "arm64"): (
        "-Linux-arm64.AppImage",
        "exe",
        "cc-switch.AppImage",
        "cc-switch.AppImage",
    ),
    ("macos", "x64"): (
        "-macOS.tar.gz",
        "tar.gz",
        "CC Switch.app/Contents/MacOS/cc-switch",
        None,
    ),
    ("macos", "arm64"): (
        "-macOS.tar.gz",
        "tar.gz",
        "CC Switch.app/Contents/MacOS/cc-switch",
        None,
    ),
}


# host os/arch -> (rust target triple used in dufs asset names, archive format)
_DUFS_ASSETS: dict[tuple[str, str], tuple[str, str]] = {
    ("windows", "x64"): ("x86_64-pc-windows-msvc", "zip"),
    ("windows", "arm64"): ("aarch64-pc-windows-msvc", "zip"),
    ("linux", "x64"): ("x86_64-unknown-linux-musl", "tar.gz"),
    ("linux", "arm64"): ("aarch64-unknown-linux-musl", "tar.gz"),
    ("macos", "x64"): ("x86_64-apple-darwin", "tar.gz"),
    ("macos", "arm64"): ("aarch64-apple-darwin", "tar.gz"),
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

    @property
    def vsix_platform(self) -> str:
        """VSCode marketplace targetPlatform, e.g. win32-x64."""
        return _VSIX_PLATFORMS[(self.os, self.arch)]

    @property
    def opencode_asset(self) -> str:
        """opencode release asset filename for this platform."""
        return _OPENCODE_ASSETS[(self.os, self.arch)][0]

    @property
    def opencode_format(self) -> str:
        return _OPENCODE_ASSETS[(self.os, self.arch)][1]

    @property
    def cc_switch_suffix(self) -> str:
        """Release asset suffix that identifies this platform's portable build."""
        return _CC_SWITCH_ASSETS[(self.os, self.arch)][0]

    @property
    def cc_switch_format(self) -> str:
        return _CC_SWITCH_ASSETS[(self.os, self.arch)][1]

    @property
    def cc_switch_launcher(self) -> str:
        """Launcher path relative to the install dir."""
        return _CC_SWITCH_ASSETS[(self.os, self.arch)][2]

    @property
    def cc_switch_single_name(self) -> str | None:
        """Name for a one-file asset; None when the asset is an archive."""
        return _CC_SWITCH_ASSETS[(self.os, self.arch)][3]

    @property
    def dufs_triple(self) -> str:
        """Rust target triple, as spelled in dufs release asset names."""
        return _DUFS_ASSETS[(self.os, self.arch)][0]

    @property
    def dufs_format(self) -> str:
        return _DUFS_ASSETS[(self.os, self.arch)][1]


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

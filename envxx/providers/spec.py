from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from ..platforms import Platform

Kind = Literal["runtime", "app"]
AssetFormat = Literal["zip", "tar.gz", "exe"]
# sha256_file: raw hex at sha256_url; shasums_file: '<hex>  <name>' listing;
# api_digest: digest carried in the API payload; none: unverified
ChecksumKind = Literal["sha256_file", "shasums_file", "api_digest", "none"]


@dataclass(frozen=True)
class EntryPoint:
    """A user-facing command that lives inside an installed version directory."""

    name: str
    relpath: str
    kind: Literal["exe", "cmd", "sh", "node"] = "exe"
    # run as '<default entrypoint> -m <module>' when no launcher file exists
    module: str | None = None


@dataclass(frozen=True)
class ToolSpec:
    name: str
    kind: Kind
    versioned: bool
    # one line for the command list in 'envxx --help'
    summary: str
    selector_prefixes: tuple[str, ...]
    aliases: tuple[str, ...] = ()
    entrypoints: tuple[EntryPoint, ...] = ()
    default_entrypoint: str = ""
    # dirs inside a version dir where package managers drop console scripts,
    # e.g. 'pip install black' writes Scripts/black.exe on Windows (bin/ on Unix)
    script_dirs: tuple[str, ...] = ()
    # the tool is an installer, not a portable tree: it is downloaded into
    # downloads/ and the path handed to the user, who runs it themselves.
    # Such specs usually declare no entrypoints.
    installer: bool = False
    checksum: ChecksumKind = "none"

    def __post_init__(self) -> None:
        if self.entrypoints and not self.default_entrypoint:
            object.__setattr__(self, "default_entrypoint", self.entrypoints[0].name)

    def entrypoint(self, name: str | None = None) -> EntryPoint:
        wanted = name or self.default_entrypoint
        for candidate in self.entrypoints:
            if candidate.name == wanted:
                return candidate
        raise KeyError(f"{self.name} has no entrypoint named {wanted!r}")

    def declared_entrypoint(self, name: str) -> EntryPoint | None:
        for candidate in self.entrypoints:
            if candidate.name == name:
                return candidate
        return None


@dataclass(frozen=True)
class Asset:
    """One downloadable artifact.

    The provider resolves a sha256 itself whenever the API already carries one
    (python's asset digest); otherwise it points at a checksum URL to fetch.
    """

    url: str
    filename: str
    format: AssetFormat
    sha256: str | None = None
    sha256_url: str | None = None
    sha256_filename: str | None = None
    size: int | None = None


@dataclass(frozen=True)
class VersionInfo:
    version: str
    channel: str = "stable"
    lts: bool | None = None
    released: str | None = None
    notes: str = ""
    size: int | None = None


@dataclass(frozen=True)
class InstallPlan:
    """Everything the pipeline needs to install one concrete version."""

    version: str
    asset: Asset
    strip_top: bool = True
    # for single-file assets: store under this name instead of the asset's
    single_name: str | None = None
    post_install: list[str] = field(default_factory=list)
    # Installers (.exe/.dmg/.deb/.rpm) are not portable trees: there is
    # nothing to unpack and nothing to run on the user's behalf. Such a tool
    # is fetched into downloads/ and the path printed, so the user can run
    # the installer themselves.
    download_only: bool = False

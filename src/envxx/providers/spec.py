from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from ..platforms import Platform

Kind = Literal["runtime", "app"]
AssetFormat = Literal["zip", "tar.gz", "exe"]
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
    selector_prefixes: tuple[str, ...]
    aliases: tuple[str, ...] = ()
    entrypoints: tuple[EntryPoint, ...] = ()
    default_entrypoint: str = ""
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


@dataclass(frozen=True)
class Asset:
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


@dataclass(frozen=True)
class InstallPlan:
    """Everything the pipeline needs to install one concrete version."""

    version: str
    asset: Asset
    strip_top: bool = True
    post_install: list[str] = field(default_factory=list)

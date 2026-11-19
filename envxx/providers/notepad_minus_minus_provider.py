from __future__ import annotations

import re

from ..errors import NetworkError, UnsupportedPlatform
from .base import AppProvider
from .spec import Asset, EntryPoint, InstallPlan, ToolSpec, VersionInfo

# notepad-- publishes portable Windows zips and a macOS .dmg. The dmg is an
# install image rather than a directory of binaries, which is the opposite of
# what this tool is for, and the Linux assets stopped after v3.8, so only the
# Windows zip is usable here.
_REPO = "https://api.github.com/repos/cxasm/notepad--"
_PAGE = 30

NP_SPEC = ToolSpec(
    name="notepad--",
    kind="app",
    versioned=True,
    summary="Notepad-- portable build, Windows only",
    selector_prefixes=("notepad--", "ndd"),
    # the exe keeps the double dash; it is a Qt app that needs its sibling
    # dlls, so the whole directory is installed and the exe run from inside
    entrypoints=(EntryPoint("notepad--", "Notepad--"),),
    default_entrypoint="notepad--",
    # the release carries no checksum sidecar and the API reports no digest
    checksum="none",
)

_TAG_RE = re.compile(r"^notepad-v(?P<version>\d+(?:\.\d+)+)$")

# x64 assets are 'Notepad--v3.9.2-win10-portable.zip' (no arch token), arm64
# ones spell it out. The arm64 build is only attached to some releases.
_X64_RE = re.compile(r"^Notepad--v[\d.]+-win10-portable\.zip$")
_ARM64_RE = re.compile(r"^Notepad--v[\d.]+-windows-arm64-portable\.zip$")


class NotepadMinusMinusProvider(AppProvider):
    """Notepad--, the portable Windows zip from cxasm/notepad--."""

    spec = NP_SPEC

    def __init__(self, platform) -> None:
        super().__init__(platform)
        if platform.os != "windows":
            raise UnsupportedPlatform(
                f"notepad-- ships a Windows portable zip only, "
                f"not available for {platform.tag}"
            )
        self._arm64 = platform.arch == "arm64"
        self._asset_re = _ARM64_RE if self._arm64 else _X64_RE

    # -- catalogue -------------------------------------------------------
    def _fetch_versions(self) -> list[VersionInfo]:
        """Releases that carry a portable zip for this architecture.

        The arm64 zip is attached to only some releases, so filtering on the
        asset rather than the tag is what keeps 'search' from offering a
        version whose download would 404.
        """
        from .. import http

        result: list[VersionInfo] = []
        page = 1
        while True:
            batch = http.get_json(
                f"{_REPO}/releases?per_page={_PAGE}&page={page}",
                f"notepad--releases-{page}",
            )
            if not isinstance(batch, list):
                raise NetworkError("unexpected notepad-- releases payload")
            if not batch:
                break

            for release in batch:
                if release.get("prerelease") or release.get("draft"):
                    continue
                match = _TAG_RE.match(str(release.get("tag_name", "")))
                if not match:
                    continue
                if not self._has_asset(release):
                    continue
                result.append(
                    VersionInfo(
                        version=match.group("version"),
                        released=str(release.get("published_at", ""))[:10] or None,
                    )
                )

            if len(batch) < _PAGE:
                break
            page += 1

        if not result:
            raise NetworkError("no notepad-- releases have a portable zip")
        return result

    def _has_asset(self, release: dict) -> bool:
        return any(
            self._asset_re.match(str(asset.get("name", "")))
            for asset in release.get("assets") or ()
        )

    def plan(self, version: str) -> InstallPlan:
        if self._arm64:
            name = f"Notepad--v{version}-windows-arm64-portable.zip"
        else:
            name = f"Notepad--v{version}-win10-portable.zip"
        base = "https://github.com/cxasm/notepad--/releases/download"
        return InstallPlan(
            version=version,
            asset=Asset(
                url=f"{base}/notepad-v{version}/{name}",
                filename=name,
                format="zip",
            ),
            # entries live under Notepad--v<version>-win10-portable/
            strip_top=True,
        )

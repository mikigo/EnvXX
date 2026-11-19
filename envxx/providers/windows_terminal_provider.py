from __future__ import annotations

import re

from ..errors import NetworkError, UnsupportedPlatform
from .base import AppProvider, latest_per_line
from .spec import Asset, EntryPoint, InstallPlan, ToolSpec, VersionInfo

# Windows Terminal ships two channels from the same releases endpoint: the
# stable tags are 'v1.25.3131.0' and the preview tags are the same shape but
# carry a 'Preview' asset prefix and a prerelease flag. Only the stable ones
# are wanted, so the filter looks at both signals.
_REPO = "https://api.github.com/repos/microsoft/terminal"
_PAGE = 30

WT_SPEC = ToolSpec(
    name="wt",
    kind="app",
    versioned=True,
    summary="Windows Terminal portable, Windows only",
    selector_prefixes=("wt", "windows-terminal"),
    entrypoints=(
        # wt.exe is the command-line front end (split panes, new-tab, ...)
        EntryPoint("wt", "wt"),
        # the GUI entry point, for launching a window
        EntryPoint("WindowsTerminal", "WindowsTerminal"),
    ),
    default_entrypoint="wt",
    # the release carries no checksum sidecar and the API reports no digest
    checksum="none",
)

# Stable asset: Microsoft.WindowsTerminal_1.25.3131.0_x64.zip
# Preview asset: Microsoft.WindowsTerminalPreview_1.26.3133.0_x64.zip
_STABLE_ASSET_RE = re.compile(
    r"^Microsoft\.WindowsTerminal_(?P<version>[\d.]+)_(?P<arch>x64|arm64|x86)\.zip$"
)
_TAG_RE = re.compile(r"^v(?P<version>[\d.]+)$")

# host arch -> the arch token used in the asset name
_ARCHES = {"x64": "x64", "arm64": "arm64"}


class WindowsTerminalProvider(AppProvider):
    """Windows Terminal, the portable zip from microsoft/terminal.

    The archive unpacks to a 'terminal-<version>/' directory containing
    WindowsTerminal.exe and wt.exe, so the wrapper is stripped on install.
    """

    spec = WT_SPEC

    def __init__(self, platform) -> None:
        super().__init__(platform)
        if platform.os != "windows":
            raise UnsupportedPlatform(
                f"wt is a Windows application, not available for {platform.tag}"
            )
        self._arch = _ARCHES.get(platform.arch)
        if self._arch is None:
            raise UnsupportedPlatform(
                f"wt has no build for {platform.tag}"
            )

    # -- catalogue -------------------------------------------------------
    def _fetch_versions(self) -> list[VersionInfo]:
        """Stable releases only; previews are filtered out.

        The prerelease flag is the reliable signal, and the asset name is
        checked as well: a preview release whose flag was forgotten would
        still ship 'Microsoft.WindowsTerminalPreview_...' and must not be
        offered as a stable version.
        """
        from .. import http

        result: list[VersionInfo] = []
        page = 1
        while True:
            batch = http.get_json(
                f"{_REPO}/releases?per_page={_PAGE}&page={page}",
                f"wt-releases-{page}",
            )
            if not isinstance(batch, list):
                raise NetworkError("unexpected windows terminal releases payload")
            if not batch:
                break

            for release in batch:
                if release.get("prerelease") or release.get("draft"):
                    continue
                match = _TAG_RE.match(str(release.get("tag_name", "")))
                if not match:
                    continue
                if not _has_stable_asset(release, self._arch):
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
            raise NetworkError("no stable windows terminal releases found")
        return result

    def display_versions(self) -> list[VersionInfo]:
        """One row per minor line, newest first: 1.25, 1.24, ...

        Each minor line gets a patch release per servicing build; the full
        history is noise unless 'search --all' asks for it.
        """
        return latest_per_line(self.search(), depth=2)

    def plan(self, version: str) -> InstallPlan:
        name = f"Microsoft.WindowsTerminal_{version}_{self._arch}.zip"
        base = "https://github.com/microsoft/terminal/releases/download"
        return InstallPlan(
            version=version,
            asset=Asset(
                url=f"{base}/v{version}/{name}",
                filename=name,
                format="zip",
            ),
            # entries live under terminal-<version>/
            strip_top=True,
        )


def _has_stable_asset(release: dict, arch: str) -> bool:
    """True when the release carries the non-preview zip for this arch."""
    for asset in release.get("assets") or ():
        match = _STABLE_ASSET_RE.match(str(asset.get("name", "")))
        if match and match.group("arch") == arch:
            return True
    return False

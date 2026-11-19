from __future__ import annotations

import re

from ..errors import NetworkError, UnsupportedPlatform
from .base import AppProvider
from .spec import Asset, EntryPoint, InstallPlan, ToolSpec, VersionInfo

# DBeaver Community ships a zip for Windows and a tar.gz for Linux, plus a
# macOS .dmg. The archive unpacks to a single 'dbeaver/' directory holding
# its own bundled JRE, which is why the wrapper has to be stripped.
_REPO = "https://api.github.com/repos/dbeaver/dbeaver"
_DOWNLOAD = "https://github.com/dbeaver/dbeaver/releases/download"
_PAGE = 30

DBEAVER_SPEC = ToolSpec(
    name="dbeaver",
    kind="app",
    versioned=True,
    summary="DBeaver Community portable build from GitHub releases",
    selector_prefixes=("dbeaver", "dbeaver-ce"),
    entrypoints=(
        # dbeaver.exe is the GUI launcher; dbeaverc.exe is the console variant
        EntryPoint("dbeaver", "dbeaver"),
    ),
    default_entrypoint="dbeaver",
    # no checksum sidecar, and the API carries no digest for these assets
    checksum="none",
)

_TAG_RE = re.compile(r"^(?P<version>\d+(?:\.\d+)+)$")

# host os/arch -> the token in the asset name, and the archive extension.
# macOS only publishes a dmg, which is an install image rather than a
# directory of binaries, so it is deliberately absent.
_ASSETS = {
    ("windows", "x64"): ("windows-x86_64", ".zip"),
    ("windows", "arm64"): ("windows-aarch64", ".zip"),
    ("linux", "x64"): ("linux-x86_64", ".tar.gz"),
    ("linux", "arm64"): ("linux-aarch64", ".tar.gz"),
}


class DbeaverProvider(AppProvider):
    """DBeaver Community, the portable archive from dbeaver/dbeaver."""

    spec = DBEAVER_SPEC

    def __init__(self, platform) -> None:
        super().__init__(platform)
        self._token = _ASSETS.get((platform.os, platform.arch))
        if self._token is None:
            raise UnsupportedPlatform(
                f"dbeaver ships a portable archive for Windows and Linux only, "
                f"not available for {platform.tag}"
            )

    # -- catalogue -------------------------------------------------------
    def _fetch_versions(self) -> list[VersionInfo]:
        from .. import http

        token, ext = self._token
        result: list[VersionInfo] = []
        page = 1
        while True:
            batch = http.get_json(
                f"{_REPO}/releases?per_page={_PAGE}&page={page}",
                f"dbeaver-releases-{page}",
            )
            if not isinstance(batch, list):
                raise NetworkError("unexpected dbeaver releases payload")
            if not batch:
                break

            for release in batch:
                if release.get("prerelease") or release.get("draft"):
                    continue
                match = _TAG_RE.match(str(release.get("tag_name", "")))
                if not match:
                    continue
                version = match.group("version")
                wanted = f"dbeaver-ce-{version}-{token}{ext}"
                names = {str(a.get("name", "")) for a in release.get("assets") or ()}
                if wanted not in names:
                    continue
                result.append(
                    VersionInfo(
                        version=version,
                        released=str(release.get("published_at", ""))[:10] or None,
                    )
                )

            if len(batch) < _PAGE:
                break
            page += 1

        if not result:
            raise NetworkError("dbeaver has no release archive for this platform")
        return result

    def plan(self, version: str) -> InstallPlan:
        token, ext = self._token
        name = f"dbeaver-ce-{version}-{token}{ext}"
        return InstallPlan(
            version=version,
            asset=Asset(
                url=f"{_DOWNLOAD}/{version}/{name}",
                filename=name,
                format="zip" if ext == ".zip" else "tar.gz",
            ),
            # the archive unpacks to a single dbeaver/ directory
            strip_top=True,
        )

    def entrypoint_candidates(
        self, name: str, version: str | None = None
    ) -> list[str]:
        entry = self.spec.entrypoint(name)
        if self.platform.os == "windows":
            return [entry.relpath + ".exe", entry.relpath]
        return [entry.relpath]
